from flask import jsonify, send_file, request, current_app, Response, make_response
from collections import OrderedDict
import csv
import os
import re
import math
import subprocess
import hmac
import hashlib as std_hashlib
from threading import Lock, Thread
from urllib.parse import urlparse
from pathlib import Path
import pydicom
from pydicom.pixel_data_handlers.util import apply_voi_lut
from PIL import Image, ImageDraw, ImageFont, ImageOps
import io
import numpy as np
import pandas as pd
import json
import base64
import tempfile
import zipfile
import uuid
import cv2
import torch
import httpx
from sqlalchemy.exc import IntegrityError
from openai import OpenAI
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db
from models import User, UserMessage, EvaluationResult, FunctionalAssessment, LGEAnalysis, ImageAnalysis, StructureAssessment, OtherFindings, SegmentationAnnotation, CardiacAnnotation, CviCaseCatalog, CaseAssignment, DatasetAccessGrant, DatasetAccessAudit, MediaAccessLog, FeedbackSession, FeedbackMessage, FeedbackAttachment, FeedbackIssue, FeedbackWorkPlan, FeedbackCodexRun, FeedbackExecutionRun
from feedback_agent import build_messages as build_feedback_agent_messages, derive_session_title, normalize_agent_result, redact_external_text, resolve_feedback_model, safe_page_context
from codex_feedback_runner import (
    CodexInvestigationError,
    investigation_markdown,
    investigation_to_proposal,
    repository_snapshot,
    run_codex_investigation,
)
from codex_feedback_executor import (
    CodexExecutionError,
    CodexExecutionStopped,
    merge_candidate,
    request_stop as request_feedback_execution_stop,
    run_controlled_execution,
    validate_allowed_paths,
    validate_clean_execution_base,
)
from utils_cardiac.report_parser import ReportParser

# Helper for Excel Data Sources
DATA_SOURCES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data_sources')
excel_data_cache = {}
excel_bundle_member_cache = {}
excel_row_lookup_cache = {}
auth_attempts = {}
media_attempts = {}
functional_image_cache = OrderedDict()
functional_image_cache_lock = Lock()
eval_prewarm_lock = Lock()
eval_prewarm_status = {
    'running': False,
    'started_at': None,
    'finished_at': None,
    'total': 0,
    'processed': 0,
    'cache_hits': 0,
    'cache_misses': 0,
    'errors': [],
}

DEFAULT_ALLOWED_ORIGINS = {
    'http://47.108.84.221:8282',
    'http://127.0.0.1:5173',
    'http://localhost:5173',
    'http://127.0.0.1:5000',
    'http://localhost:5000',
}
MEDIA_TOKEN_COOKIE = 'ls_media_token'
MEDIA_TOKEN_TTL_SECONDS = 20 * 60
FUNCTIONAL_IMAGE_CACHE_MAX_ITEMS = int(os.environ.get('LABELSYSTEM_FUNCTIONAL_IMAGE_CACHE_ITEMS', '240'))
BACKEND_DIR = Path(__file__).resolve().parent
REPOSITORY_DIR = BACKEND_DIR.parent
INSTANCE_DIR = BACKEND_DIR / 'instance'
try:
    DEFAULT_RELEASE_VERSION = (REPOSITORY_DIR / 'VERSION').read_text(encoding='utf-8').strip()
except OSError:
    DEFAULT_RELEASE_VERSION = 'development'
LABELSYSTEM_RELEASE_VERSION = os.environ.get(
    'LABELSYSTEM_RELEASE_VERSION',
    DEFAULT_RELEASE_VERSION or 'development',
).strip()
LLM_GATEWAY_CONFIG_PATH = INSTANCE_DIR / 'llm_gateway_config.json'
LLM_METRIC_CACHE_DIR = INSTANCE_DIR / 'llm_metric_cache'
LLM_GATEWAY_MODEL_CACHE_PATH = INSTANCE_DIR / 'llm_gateway_models_cache.json'
LLM_METRIC_SUGGESTION_CACHE_PATH = INSTANCE_DIR / 'llm_metric_suggestions_cache.json'
FEEDBACK_ATTACHMENT_DIR = INSTANCE_DIR / 'feedback_attachments'
FEEDBACK_CODEX_RUN_DIR = INSTANCE_DIR / 'feedback_codex_runs'
FEEDBACK_EXECUTION_RUN_DIR = INSTANCE_DIR / 'feedback_execution_runs'
FEEDBACK_ATTACHMENT_MAX_BYTES = 8 * 1024 * 1024
FEEDBACK_ATTACHMENT_MAX_DIMENSION = 2400
EVAL_EXPORT_DIR = INSTANCE_DIR / 'eval_exports'
eval_export_jobs_lock = Lock()
eval_export_jobs = {}
feedback_codex_execution_lock = Lock()
admin_monitor_refresh_lock = Lock()
dataset_access_update_lock = Lock()
admin_monitor_cache = {'generated_monotonic': 0.0, 'payload': None}
ADMIN_MONITOR_CACHE_TTL_SECONDS = max(1, int(os.environ.get('LABELSYSTEM_MONITOR_CACHE_SECONDS', '10')))


def _invalidate_admin_monitor_cache():
    with admin_monitor_refresh_lock:
        admin_monitor_cache['generated_monotonic'] = 0.0
        admin_monitor_cache['payload'] = None

def get_excel_data(filename, header_row=None):
    cache_key = f'{filename}::header={0 if header_row is None else header_row}'
    if cache_key not in excel_data_cache:
        path = _excel_file_path(filename)
        if os.path.exists(path):
            try:
                if str(filename).lower().endswith('.zip'):
                    excel_data_cache[cache_key] = _load_excel_bundle_from_zip(path, cache_key)
                else:
                    # Load all columns as string to avoid type issues
                    df = pd.read_excel(path, dtype=str, header=0 if header_row is None else header_row)
                    df.columns = [str(col).strip() for col in df.columns]
                    excel_data_cache[cache_key] = df
            except Exception as e:
                print(f"Error loading Excel {filename}: {e}")
                return None
        else:
            print(f"Excel file not found: {path}")
            return None
    return excel_data_cache[cache_key]


def _load_excel_bundle_from_zip(path, cache_key):
    dataframes = []
    member_meta = {}
    with zipfile.ZipFile(path) as bundle:
        members = sorted(
            name for name in bundle.namelist()
            if not name.endswith('/') and name.lower().endswith(('.xlsx', '.xls', '.csv'))
        )
        for member in members:
            suffix = Path(member).suffix.lower()
            with bundle.open(member) as handle:
                payload = handle.read()
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(payload)
                tmp_path = tmp.name
            try:
                if suffix == '.csv':
                    df = pd.read_csv(tmp_path, dtype=str)
                else:
                    df = pd.read_excel(tmp_path, dtype=str)
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            if df is None or df.empty:
                continue
            df = df.copy()
            df['__source_member__'] = member
            dataframes.append(df)
            member_meta[member] = {
                'path': member,
                'display_name': Path(member).name,
            }
    excel_bundle_member_cache[cache_key] = member_meta
    if not dataframes:
        return pd.DataFrame()
    return pd.concat(dataframes, ignore_index=True, sort=False)

EXCEL_DATASET_CONFIGS = {
    'CMR_Chendu': {
        'excel_file': 'CD_515_step6.xlsx',
        'id_col': '编号',
        'description_cols': ['影像学表现'],
        'conclusion_cols': ['影像学诊断'],
        'extra_cols': ['Trans'],
    },
    'CMR_SCS': {
        'excel_file': 'SCS_CMR_dcm_step8.xlsx',
        'id_col': '检查号',
        'description_cols': ['诊断结果'],
        'conclusion_cols': ['诊断意见'],
        'extra_cols': ['Trans'],
    },
    'CMR_YA': {
        'excel_file': 'YA690_CMR3_S1.xlsx',
        'id_col': '住院号',
        'description_cols': ['影像学描述', '心脏形态', '心脏电影', 'LGE'],
        'conclusion_cols': ['影像诊断'],
        'extra_cols': ['临床诊断'],
    },
    'CMR_ALL': {
        'excel_file': '昆医附二院2014-2026.1.29病例分类.zip',
        'id_col': '登记号',
        # 昆医这份 Excel 中其余拆分列多为训练/增强字段，标准报告页仅展示原始影像描述与结论。
        'description_cols': ['检查所见'],
        'conclusion_cols': ['诊断意见'],
        'extra_cols': [],
    },
    'CMR_RenJi_HCM': {
        'excel_file': '/home/Larry/data/CMR_RenJi/仁济.xlsx',
        'header_row': 1,
        'id_col': '放射编号',
        'dicom_match': {
            'accession_cols': ['放射编号'],
            'patient_id_cols': [],
            'study_date_cols': ['检查时间', '检查时间.2'],
        },
        'description_cols': ['核磁表现'],
        'conclusion_cols': ['核磁诊断'],
        'extra_cols': [
            '病人姓名', '年龄', '性别', '身高cm', '体重kg',
            'LGE （% of LV mass）', 'LV EDV', 'LV ESV', 'LV SV', 'LVEF', 'LV mass',
            'RV EDV', 'RV ESV', 'RV SV', 'RVEF',
            'LA RS', 'LA BS', 'LA CS', 'RA RS', 'RA BS', 'RA CS',
            '入院情况（主诉）', '入院情况（现病史）', '出院诊断',
            '超声报告描述', '超声报告诊断',
            '心超静息左室流出道最高压差(LVOT gradient, mm Hg)',
            '左室流出道梗阻（LVOT gradient≥30 mm Hg)',
            'SAM征（二尖瓣前向运动，评估HCM，（0=无，1=有）',
            '延迟强化（0无，1有）', 'Maximal wall thickness （mm）', 'Apical aneurysm',
            'SCD', 'SCD-events', '全因死亡', '心脏移植', '心衰', '新发房颤', '脑卒中', '随访结局时间',
        ],
    },
    'CMR_RenJi_MI': {
        'excel_file': '/home/Larry/data/CMR_RenJi/仁济MI.xlsx',
        'id_col': '登记号',
        'dicom_match': {
            'accession_cols': ['登记号'],
            'patient_id_cols': ['patient ID'],
            'study_date_cols': ['检查时间'],
        },
        'description_cols': ['CMR报告及诊断.1'],
        'conclusion_cols': ['CMR报告及诊断'],
        'extra_cols': [
            '姓名', 'patient ID', '性别', '年龄', '身高', '体重', '体表面积', 'BMI',
            'ST段抬高/非ST段抬高', 'NYHA分级', 'Killip分级（入院或出院）', '心电图',
            '糖尿病', '高血压', '高血脂', '吸烟',
            '冠脉介入造影术中所见', 'PCI/PTCA术', '造影累及犯罪血管', '造影累及罪犯血管数量',
            'CO,L/min', 'CI,L/min/m*2', 'EDV，ml', 'ESV，ml', 'EDVI', 'ESVI', 'EF,%',
            'GRS', 'GCS', 'GLS', 'LAEDV', 'LAESV', 'LVmass', 'LVMI',
            'LGE（g）', 'LGE（%）', '室壁瘤', 'MVO',
            '罪犯血管总数', '罪犯血管（LAD、LCX、RCA））', 'LAD', 'RCA', 'LCX',
            '透壁性（0:局限;1:<50%; 2: >50%; 3: 透壁)',
            '梗死累及部位（间壁、前壁、下壁、侧壁、心尖）',
            '心尖', '前壁', '室间隔', '下壁', '侧壁',
            '累计17节段分段', '累计17节段总数', '中层LGE',
            '临床诊断', '随访时间',
            'MACE(全因死亡、SCD、再发非致命MI、心衰、VA、ICD植入治疗、脑卒中发生风险预测\n0=无，1=有、严重心绞痛再入院、其他)',
            'MACE时间', '全因死亡', 'SCD', '再发非致命MI', '心衰', 'VA', 'ICD植入治疗', '脑卒中发生风险预测', '其他',
        ],
    },
}

MANUAL_EXCEL_INDEX_OVERRIDES = {
    # Doctor-confirmed RenJi HCM mappings. DICOM headers for these folders point
    # to a different accession/study, so use the source table's Index column.
    ('CMR_RenJi_HCM', '20180606 zhouwei'): '200',
    ('CMR_RenJi_HCM', '20200812 he li ping'): '273',
}

QUANTITATIVE_METRIC_RULES = {
    'LVEDV': {'label': 'LVEDV', 'unit': 'mL', 'tolerance_abs': 15.0},
    'LVESV': {'label': 'LVESV', 'unit': 'mL', 'tolerance_abs': 15.0},
    'SV': {'label': 'SV', 'unit': 'mL', 'tolerance_abs': 15.0},
    'LVEF': {'label': 'LVEF', 'unit': '%', 'tolerance_abs': 5.0, 'reference_range': (50.0, 70.0)},
    'RVEDV': {'label': 'RVEDV', 'unit': 'mL', 'tolerance_abs': 15.0},
    'RVESV': {'label': 'RVESV', 'unit': 'mL', 'tolerance_abs': 15.0},
    'RVEF': {'label': 'RVEF', 'unit': '%', 'tolerance_abs': 5.0, 'reference_range': (45.0, 60.0)},
    'LAV': {'label': 'LAV', 'unit': 'mL', 'tolerance_abs': 15.0},
    'RAV': {'label': 'RAV', 'unit': 'mL', 'tolerance_abs': 15.0},
    'LVEDD': {'label': 'LVEDD', 'unit': 'mm', 'tolerance_abs': 3.0, 'reference_range': (35.0, 55.0)},
    'RVEDD': {'label': 'RVEDD', 'unit': 'mm', 'tolerance_abs': 3.0, 'reference_range': (20.0, 42.0)},
    'IVS': {'label': 'IVS', 'unit': 'mm', 'tolerance_abs': 3.0, 'reference_range': (6.0, 12.0)},
    'LVPW': {'label': 'LVPW', 'unit': 'mm', 'tolerance_abs': 3.0, 'reference_range': (6.0, 11.0)},
    'RWT': {'label': 'RWT', 'unit': '', 'tolerance_abs': 0.08, 'reference_range': (0.32, 0.42)},
    'SI': {'label': 'SI', 'unit': '', 'tolerance_abs': 0.10},
    'LV/RV ratio': {'label': 'LV/RV ratio', 'unit': '', 'tolerance_abs': 0.15, 'reference_range': (0.8, 1.2)},
}

QUANTITATIVE_METRIC_ORDER = [
    'LVEDV', 'LVESV', 'SV', 'LVEF',
    'RVEDV', 'RVESV', 'RVEF',
    'LAV', 'RAV',
    'LVEDD', 'RVEDD', 'IVS', 'LVPW', 'RWT', 'SI', 'LV/RV ratio'
]

DEFAULT_LLM_GATEWAY_CONFIG = {
    'enabled': True,
    'api_base': 'https://a.loping151.net',
    'api_key': '',
    'model': '[j]gpt-5.4',
    'temperature': 0,
    'max_tokens': 1200,
    'metric_definitions': None,
    'prompt_system_template': '',
    'prompt_user_template': '',
    'prompt_extra_instructions': '',
    'last_check': None,
}

DEFAULT_LLM_MODEL_OPTIONS = [
    'gpt-5.4',
    'gpt-5.3-codex',
    'gpt-5.2',
    'gpt-5.2-codex',
    'gpt-5.3-codex-spark',
    'deepseek-chat',
    'deepseek-reasoner',
    'gemini-2.5-pro',
    'gemini-2.5-flash',
    'gemini-3-flash',
    'gemini-3-pro-preview',
    'gemini-3.1-pro-preview',
    'claude-sonnet-4-6-c',
    'claude-opus-4-6-c',
    'GLM-5',
    'GLM-5.1',
    'kimi-for-coding',
]

ADDITIONAL_LLM_METRIC_DEFINITIONS = [
    {'key': 'LA_SI', 'label': 'LA_SI', 'unit': 'mm', 'tolerance_abs': 5.0},
    {'key': 'LA_LR', 'label': 'LA_LR', 'unit': 'mm', 'tolerance_abs': 5.0},
    {'key': 'RA_SI', 'label': 'RA_SI', 'unit': 'mm', 'tolerance_abs': 5.0},
    {'key': 'RA_LR', 'label': 'RA_LR', 'unit': 'mm', 'tolerance_abs': 5.0},
    {'key': 'LVESD', 'label': 'LVESD', 'unit': 'mm', 'tolerance_abs': 3.0},
    {'key': 'RVESD', 'label': 'RVESD', 'unit': 'mm', 'tolerance_abs': 3.0},
    {'key': 'CO', 'label': 'CO', 'unit': 'L/min', 'tolerance_abs': 0.8},
    {'key': 'CI', 'label': 'CI', 'unit': 'L/min/m²', 'tolerance_abs': 0.5},
    {'key': 'LVM', 'label': 'LVM', 'unit': 'g', 'tolerance_abs': 15.0},
    {'key': 'T1', 'label': 'T1', 'unit': 'ms', 'tolerance_abs': 50.0},
    {'key': 'T2', 'label': 'T2', 'unit': 'ms', 'tolerance_abs': 5.0},
    {'key': 'ECV', 'label': 'ECV', 'unit': '%', 'tolerance_abs': 5.0},
]

DEFAULT_LLM_PROMPT_EXTRA_INSTRUCTIONS = (
    '如果报告中出现了预设列表之外、但确实属于明确量化/测量指标的数值，'
    '请把它们放进 unexpected_metrics 数组，不要丢失。'
    '不要把 SAX、4CH、LGE、ED、ES 这类序列名或时相名当成指标。'
)

DEFAULT_LLM_PROMPT_SYSTEM_TEMPLATE = (
    '你是心脏 MRI 定量指标抽取助手。'
    '请只提取报告文本里明确出现的数值指标，不要猜测，不要补全。'
    '输出必须是 JSON 对象，格式为 '
    '{"metrics":{"指标名":{"value":数值,"unit":"单位","evidence":"原文片段"}},'
    '"unexpected_metrics":[{"name":"原文指标名","value":数值,"unit":"单位","evidence":"原文片段","reason":"为什么归入意外指标"}]}。'
    'metrics 中的指标名只能使用给定列表中的标准名。'
    'unexpected_metrics 用于承接预设列表之外、但确实明确出现的量化指标。'
)

DEFAULT_LLM_PROMPT_USER_TEMPLATE = (
    '来源：{{source_label}}\n'
    '允许提取的指标如下：\n'
    '{{allowed_metrics}}\n\n'
    '补充要求：{{prompt_extra_instructions}}\n\n'
    '请严格输出 JSON，不要输出额外解释。\n\n'
    '报告文本：\n'
    '{{report_text}}'
)

METRIC_SUGGESTION_CANDIDATES = [
    {'key': 'LA_SI', 'label': 'LA_SI', 'unit': 'mm', 'pattern': r'\bLA[_\s/-]?SI\b'},
    {'key': 'LA_LR', 'label': 'LA_LR', 'unit': 'mm', 'pattern': r'\bLA[_\s/-]?LR\b'},
    {'key': 'RA_SI', 'label': 'RA_SI', 'unit': 'mm', 'pattern': r'\bRA[_\s/-]?SI\b'},
    {'key': 'RA_LR', 'label': 'RA_LR', 'unit': 'mm', 'pattern': r'\bRA[_\s/-]?LR\b'},
    {'key': 'CO', 'label': 'CO', 'unit': 'L/min', 'pattern': r'\bCO\b'},
    {'key': 'CI', 'label': 'CI', 'unit': 'L/min/m²', 'pattern': r'\bCI\b'},
    {'key': 'LVESD', 'label': 'LVESD', 'unit': 'mm', 'pattern': r'\bLVESD\b'},
    {'key': 'RVESD', 'label': 'RVESD', 'unit': 'mm', 'pattern': r'\bRVESD\b'},
    {'key': 'LVM', 'label': 'LVM', 'unit': 'g', 'pattern': r'\b(?:LVM|LV\s*mass|Mass)\b'},
    {'key': 'T1', 'label': 'T1', 'unit': 'ms', 'pattern': r'\bT1\b'},
    {'key': 'T2', 'label': 'T2', 'unit': 'ms', 'pattern': r'\bT2\b'},
    {'key': 'ECV', 'label': 'ECV', 'unit': '%', 'pattern': r'\bECV\b'},
]

QUANTITATIVE_METRIC_ALIASES = {
    'LVEF': 'LVEF',
    'LVEDV': 'LVEDV',
    'LVESV': 'LVESV',
    'SV': 'SV',
    'RVEF': 'RVEF',
    'RVEDV': 'RVEDV',
    'RVESV': 'RVESV',
    'LAV': 'LAV',
    'RAV': 'RAV',
    'LVEDD': 'LVEDD',
    'RVEDD': 'RVEDD',
    'IVS': 'IVS',
    'LVPW': 'LVPW',
    'RWT': 'RWT',
    'SI': 'SI',
    'LA SI': 'LA_SI',
    'LA_SI': 'LA_SI',
    'LA LR': 'LA_LR',
    'LA_LR': 'LA_LR',
    'RA SI': 'RA_SI',
    'RA_SI': 'RA_SI',
    'RA LR': 'RA_LR',
    'RA_LR': 'RA_LR',
    'CO': 'CO',
    'CI': 'CI',
    'LVM': 'LVM',
    'LV MASS': 'LVM',
    'MASS': 'LVM',
    'LVESD': 'LVESD',
    'RVESD': 'RVESD',
    'T1': 'T1',
    'T2': 'T2',
    'ECV': 'ECV',
    'LV/RV RATIO': 'LV/RV ratio',
    'LV RV RATIO': 'LV/RV ratio',
    'LA VOLUME': 'LAV',
    'RA VOLUME': 'RAV',
    'LA VOL': 'LAV',
    'RA VOL': 'RAV',
}


def _normalize_metric_key(metric_name):
    raw = str(metric_name or '').strip()
    if not raw:
        return ''
    cleaned = (
        raw.replace('（', '(')
        .replace('）', ')')
        .replace('_', ' ')
        .replace('-', ' ')
    )
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    alias_key = cleaned.upper()
    return QUANTITATIVE_METRIC_ALIASES.get(alias_key, cleaned)


def _normalize_openai_base_url(value):
    raw = str(value or '').strip()
    if not raw:
        return ''
    normalized = raw.rstrip('/')
    parsed = urlparse(normalized)
    if not parsed.scheme or not parsed.netloc:
        return normalized
    path = parsed.path.rstrip('/')
    if not path:
        path = '/v1'
    elif not path.endswith('/v1'):
        path = f'{path}/v1'
    return f'{parsed.scheme}://{parsed.netloc}{path}'


def _load_llm_gateway_config():
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    config = dict(DEFAULT_LLM_GATEWAY_CONFIG)
    if LLM_GATEWAY_CONFIG_PATH.exists():
        try:
            with open(LLM_GATEWAY_CONFIG_PATH, 'r', encoding='utf-8') as f:
                loaded = json.load(f) or {}
            if isinstance(loaded, dict):
                config.update({key: loaded.get(key) for key in config.keys() if key in loaded})
                if 'last_check' in loaded:
                    config['last_check'] = loaded.get('last_check')
        except Exception as exc:
            current_app.logger.warning('Failed to load LLM gateway config: %s', exc)
    config['api_base'] = str(config.get('api_base') or DEFAULT_LLM_GATEWAY_CONFIG['api_base']).strip()
    config['api_key'] = str(config.get('api_key') or '').strip()
    config['model'] = str(config.get('model') or DEFAULT_LLM_GATEWAY_CONFIG['model']).strip() or DEFAULT_LLM_GATEWAY_CONFIG['model']
    config['temperature'] = float(config.get('temperature') or 0)
    config['max_tokens'] = int(config.get('max_tokens') or DEFAULT_LLM_GATEWAY_CONFIG['max_tokens'])
    config['enabled'] = bool(config.get('enabled'))
    config['metric_definitions'] = _normalize_metric_definitions(config.get('metric_definitions'))
    config['prompt_system_template'] = str(
        config.get('prompt_system_template') or DEFAULT_LLM_PROMPT_SYSTEM_TEMPLATE
    ).strip()
    config['prompt_user_template'] = str(
        config.get('prompt_user_template') or DEFAULT_LLM_PROMPT_USER_TEMPLATE
    ).strip()
    config['prompt_extra_instructions'] = str(config.get('prompt_extra_instructions') or DEFAULT_LLM_PROMPT_EXTRA_INSTRUCTIONS).strip()
    return config


def _save_llm_gateway_config(next_config):
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    config = dict(DEFAULT_LLM_GATEWAY_CONFIG)
    config.update(next_config or {})
    config['api_base'] = str(config.get('api_base') or '').strip()
    config['api_key'] = str(config.get('api_key') or '').strip()
    config['model'] = str(config.get('model') or DEFAULT_LLM_GATEWAY_CONFIG['model']).strip() or DEFAULT_LLM_GATEWAY_CONFIG['model']
    config['temperature'] = float(config.get('temperature') or 0)
    config['max_tokens'] = int(config.get('max_tokens') or DEFAULT_LLM_GATEWAY_CONFIG['max_tokens'])
    config['enabled'] = bool(config.get('enabled'))
    config['metric_definitions'] = _normalize_metric_definitions(config.get('metric_definitions'))
    config['prompt_system_template'] = str(
        config.get('prompt_system_template') or DEFAULT_LLM_PROMPT_SYSTEM_TEMPLATE
    ).strip()
    config['prompt_user_template'] = str(
        config.get('prompt_user_template') or DEFAULT_LLM_PROMPT_USER_TEMPLATE
    ).strip()
    config['prompt_extra_instructions'] = str(config.get('prompt_extra_instructions') or DEFAULT_LLM_PROMPT_EXTRA_INSTRUCTIONS).strip()
    with open(LLM_GATEWAY_CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    return config


def _masked_api_key(api_key):
    raw = str(api_key or '').strip()
    if len(raw) <= 8:
        return '已设置' if raw else ''
    return f'{raw[:6]}...{raw[-4:]}'


def _default_metric_definitions():
    definitions = []
    for metric_key in QUANTITATIVE_METRIC_ORDER:
        rule = QUANTITATIVE_METRIC_RULES.get(metric_key, {})
        metric_range = rule.get('reference_range')
        definitions.append({
            'key': metric_key,
            'label': rule.get('label', metric_key),
            'unit': rule.get('unit', ''),
            'tolerance_abs': rule.get('tolerance_abs'),
            'reference_range': list(metric_range) if metric_range else None,
        })
    definitions.extend(ADDITIONAL_LLM_METRIC_DEFINITIONS)
    return definitions


def _normalize_reference_range(value):
    if not value or not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    lower = _normalize_metric_value(value[0])
    upper = _normalize_metric_value(value[1])
    if lower is None or upper is None:
        return None
    return [lower, upper]


def _normalize_metric_definition(item):
    if not isinstance(item, dict):
        return None
    metric_key = _normalize_metric_key(item.get('key') or item.get('label'))
    if not metric_key:
        return None
    tolerance_abs = _normalize_metric_value(item.get('tolerance_abs'))
    return {
        'key': metric_key,
        'label': str(item.get('label') or metric_key).strip() or metric_key,
        'unit': _normalize_unit(item.get('unit')),
        'tolerance_abs': tolerance_abs,
        'reference_range': _normalize_reference_range(item.get('reference_range')),
    }


def _normalize_metric_definitions(items):
    normalized = []
    seen = set()
    source = items if isinstance(items, list) and items else _default_metric_definitions()
    for item in source:
        definition = _normalize_metric_definition(item)
        if not definition:
            continue
        if definition['key'] in seen:
            continue
        seen.add(definition['key'])
        normalized.append(definition)
    return normalized


def _metric_rules_from_definitions(metric_definitions=None):
    rules = {}
    for item in _normalize_metric_definitions(metric_definitions):
        rules[item['key']] = {
            'label': item['label'],
            'unit': item['unit'],
            'tolerance_abs': item['tolerance_abs'],
            'reference_range': tuple(item['reference_range']) if item.get('reference_range') else None,
        }
    return rules


def _metric_order_from_definitions(metric_definitions=None):
    return [item['key'] for item in _normalize_metric_definitions(metric_definitions)]


def _llm_gateway_http_client(timeout=20.0):
    proxy_url = (
        os.environ.get('HTTPS_PROXY')
        or os.environ.get('https_proxy')
        or os.environ.get('HTTP_PROXY')
        or os.environ.get('http_proxy')
        or None
    )
    return httpx.Client(timeout=timeout, trust_env=False, proxy=proxy_url)


def _llm_gateway_pricing_url(api_base):
    raw = str(api_base or '').strip() or DEFAULT_LLM_GATEWAY_CONFIG['api_base']
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return ''
    path = parsed.path.rstrip('/')
    if path.endswith('/v1'):
        path = path[:-3]
    path = path.rstrip('/')
    if path:
        return f'{parsed.scheme}://{parsed.netloc}{path}/api/pricing'
    return f'{parsed.scheme}://{parsed.netloc}/api/pricing'


def _load_llm_gateway_model_cache():
    if not LLM_GATEWAY_MODEL_CACHE_PATH.exists():
        return None
    try:
        with open(LLM_GATEWAY_MODEL_CACHE_PATH, 'r', encoding='utf-8') as f:
            payload = json.load(f) or {}
        if isinstance(payload, dict):
            return payload
    except Exception as exc:
        current_app.logger.warning('Failed to load LLM model cache: %s', exc)
    return None


def _save_llm_gateway_model_cache(payload):
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    with open(LLM_GATEWAY_MODEL_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(payload or {}, f, ensure_ascii=False, indent=2)


def _normalize_llm_model_options(items):
    seen = set()
    normalized = []
    for item in items or []:
        model_name = str(item or '').strip()
        if not model_name or model_name in seen:
            continue
        seen.add(model_name)
        normalized.append(model_name)
    return sorted(
        normalized,
        key=lambda value: (
            re.sub(r'^\[[^\]]+\]', '', value).strip().lower(),
            value.lower(),
        ),
    )


def _format_model_pricing(model_item):
    quota_type = model_item.get('quota_type')
    model_price = _normalize_metric_value(model_item.get('model_price'))
    model_ratio = _normalize_metric_value(model_item.get('model_ratio'))
    completion_ratio = _normalize_metric_value(model_item.get('completion_ratio'))
    cache_ratio = _normalize_metric_value(model_item.get('cache_ratio'))
    if quota_type == 1 and model_price is not None:
        return f'按次 ${model_price:g}'
    parts = []
    if model_ratio is not None:
        parts.append(f'输入 {model_ratio:g}x')
    if completion_ratio is not None:
        parts.append(f'输出 {completion_ratio:g}x')
    if cache_ratio is not None:
        parts.append(f'缓存 {cache_ratio:g}x')
    return ' / '.join(parts) or '倍率未公开'


def _build_model_catalog_payload(payload):
    vendor_lookup = {}
    vendors = []
    for vendor in payload.get('vendors') or []:
        if not isinstance(vendor, dict):
            continue
        vendor_id = vendor.get('id')
        vendor_name = str(vendor.get('name') or '').strip() or f'Vendor {vendor_id}'
        vendor_info = {
            'id': vendor_id,
            'name': vendor_name,
            'icon': vendor.get('icon') or '',
        }
        vendors.append(vendor_info)
        vendor_lookup[vendor_id] = vendor_info

    model_catalog = []
    remote_models = []
    for item in payload.get('data') or []:
        if not isinstance(item, dict):
            continue
        endpoint_types = item.get('supported_endpoint_types') or []
        if endpoint_types and 'openai' not in endpoint_types:
            continue
        model_name = str(item.get('model_name') or '').strip()
        if not model_name:
            continue
        remote_models.append(model_name)
        prefix_match = re.match(r'^\[([^\]]+)\]', model_name)
        model_catalog.append({
            'name': model_name,
            'clean_name': re.sub(r'^\[[^\]]+\]', '', model_name).strip(),
            'prefix': prefix_match.group(1) if prefix_match else '',
            'vendor_id': item.get('vendor_id'),
            'vendor_name': vendor_lookup.get(item.get('vendor_id'), {}).get('name') or '其他',
            'vendor_icon': vendor_lookup.get(item.get('vendor_id'), {}).get('icon') or '',
            'quota_type': item.get('quota_type'),
            'price_text': _format_model_pricing(item),
            'model_ratio': _normalize_metric_value(item.get('model_ratio')),
            'model_price': _normalize_metric_value(item.get('model_price')),
            'completion_ratio': _normalize_metric_value(item.get('completion_ratio')),
            'cache_ratio': _normalize_metric_value(item.get('cache_ratio')),
            'groups': list(item.get('enable_groups') or []),
            'supported_endpoint_types': list(endpoint_types),
        })

    model_options = _normalize_llm_model_options(remote_models) or list(DEFAULT_LLM_MODEL_OPTIONS)
    model_catalog = sorted(
        model_catalog,
        key=lambda item: (
            str(item.get('vendor_name') or '').lower(),
            str(item.get('clean_name') or item.get('name') or '').lower(),
            str(item.get('name') or '').lower(),
        ),
    )
    return vendors, model_catalog, model_options


def _load_metric_suggestion_cache():
    if not LLM_METRIC_SUGGESTION_CACHE_PATH.exists():
        return None
    try:
        with open(LLM_METRIC_SUGGESTION_CACHE_PATH, 'r', encoding='utf-8') as f:
            payload = json.load(f) or {}
        if isinstance(payload, dict):
            return payload
    except Exception as exc:
        current_app.logger.warning('Failed to load metric suggestion cache: %s', exc)
    return None


def _save_metric_suggestion_cache(payload):
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    with open(LLM_METRIC_SUGGESTION_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(payload or {}, f, ensure_ascii=False, indent=2)


def _mine_metric_suggestions(report_root, configured_keys=None, sample_limit=240):
    if not report_root:
        return {
            'sample_size': 0,
            'scanned_reports': 0,
            'suggestions': [],
            'generated_at': datetime.utcnow().isoformat() + 'Z',
        }
    report_paths = sorted(Path(report_root).glob('**/report.json'))
    if not report_paths:
        return {
            'sample_size': 0,
            'scanned_reports': 0,
            'suggestions': [],
            'generated_at': datetime.utcnow().isoformat() + 'Z',
        }
    sample_size = min(sample_limit, len(report_paths))
    step = max(1, len(report_paths) // sample_size)
    sampled_paths = report_paths[::step][:sample_size]
    configured = set(configured_keys or [])
    suggestions = []
    for candidate in METRIC_SUGGESTION_CANDIDATES:
        pattern = re.compile(candidate['pattern'], re.I)
        examples = []
        count = 0
        for path in sampled_paths:
            try:
                payload = json.loads(path.read_text(encoding='utf-8'))
            except Exception:
                continue
            text = payload.get('text', '') if isinstance(payload, dict) else str(payload)
            if not text:
                continue
            for match in pattern.finditer(text):
                count += 1
                if len(examples) < 2:
                    start = max(0, match.start() - 48)
                    end = min(len(text), match.end() + 120)
                    examples.append(text[start:end].replace('\n', ' ').strip())
                break
        if count <= 0:
            continue
        suggestions.append({
            'key': candidate['key'],
            'label': candidate['label'],
            'unit': candidate['unit'],
            'count': count,
            'already_configured': candidate['key'] in configured,
            'examples': examples,
        })
    suggestions.sort(key=lambda item: (-item['count'], item['key']))
    cache_payload = {
        'sample_size': len(sampled_paths),
        'scanned_reports': len(report_paths),
        'suggestions': suggestions,
        'generated_at': datetime.utcnow().isoformat() + 'Z',
    }
    _save_metric_suggestion_cache(cache_payload)
    return cache_payload


def _refresh_llm_gateway_model_cache(api_base=None):
    pricing_url = _llm_gateway_pricing_url(api_base)
    if not pricing_url:
        raise ValueError('无法根据 API 地址生成 pricing 接口地址')
    with _llm_gateway_http_client(timeout=20.0) as client:
        response = client.get(pricing_url, headers={'Accept': 'application/json'})
        response.raise_for_status()
        payload = response.json() or {}

    vendors, model_catalog, model_options = _build_model_catalog_payload(payload)
    cache_payload = {
        'model_options': model_options,
        'model_count': len(model_options),
        'vendors': vendors,
        'model_catalog': model_catalog,
        'pricing_url': pricing_url,
        'synced_at': datetime.utcnow().isoformat() + 'Z',
        'source': 'pricing-api',
    }
    _save_llm_gateway_model_cache(cache_payload)
    return cache_payload


def _llm_gateway_monitor_payload():
    config = _load_llm_gateway_config()
    metric_definitions = _normalize_metric_definitions(config.get('metric_definitions'))
    model_cache = _load_llm_gateway_model_cache()
    if not model_cache or 'model_catalog' not in model_cache or 'vendors' not in model_cache:
        try:
            model_cache = _refresh_llm_gateway_model_cache(config.get('api_base'))
        except Exception as exc:
            current_app.logger.warning('Failed to sync LLM model options: %s', exc)
            model_cache = {
                'model_options': list(DEFAULT_LLM_MODEL_OPTIONS),
                'model_count': len(DEFAULT_LLM_MODEL_OPTIONS),
                'vendors': [],
                'model_catalog': [],
                'pricing_url': _llm_gateway_pricing_url(config.get('api_base')),
                'synced_at': None,
                'source': 'fallback',
            }
    metric_suggestions = _load_metric_suggestion_cache()
    max_cache_age_seconds = 6 * 3600
    refresh_suggestions = True
    if metric_suggestions and metric_suggestions.get('generated_at'):
        try:
            generated_at = datetime.fromisoformat(str(metric_suggestions['generated_at']).replace('Z', '+00:00'))
            refresh_suggestions = (datetime.utcnow() - generated_at.replace(tzinfo=None)).total_seconds() > max_cache_age_seconds
        except Exception:
            refresh_suggestions = True
    if refresh_suggestions:
        try:
            metric_suggestions = _mine_metric_suggestions(
                current_app.config.get('EVAL_ROOT'),
                configured_keys=[item['key'] for item in metric_definitions],
            )
        except Exception as exc:
            current_app.logger.warning('Failed to mine metric suggestions: %s', exc)
            metric_suggestions = metric_suggestions or {
                'sample_size': 0,
                'scanned_reports': 0,
                'suggestions': [],
                'generated_at': None,
            }
    return {
        'enabled': bool(config.get('enabled')),
        'api_base': config.get('api_base') or '',
        'normalized_api_base': _normalize_openai_base_url(config.get('api_base')),
        'model': config.get('model') or DEFAULT_LLM_GATEWAY_CONFIG['model'],
        'temperature': config.get('temperature', DEFAULT_LLM_GATEWAY_CONFIG['temperature']),
        'max_tokens': config.get('max_tokens', DEFAULT_LLM_GATEWAY_CONFIG['max_tokens']),
        'prompt_system_template': config.get('prompt_system_template') or DEFAULT_LLM_PROMPT_SYSTEM_TEMPLATE,
        'prompt_user_template': config.get('prompt_user_template') or DEFAULT_LLM_PROMPT_USER_TEMPLATE,
        'has_api_key': bool(config.get('api_key')),
        'api_key_masked': _masked_api_key(config.get('api_key')),
        'last_check': config.get('last_check'),
        'model_options': model_cache.get('model_options') or list(DEFAULT_LLM_MODEL_OPTIONS),
        'model_count': int(model_cache.get('model_count') or 0),
        'model_source': model_cache.get('source') or 'fallback',
        'models_synced_at': model_cache.get('synced_at'),
        'pricing_url': model_cache.get('pricing_url') or _llm_gateway_pricing_url(config.get('api_base')),
        'vendors': model_cache.get('vendors') or [],
        'model_catalog': model_cache.get('model_catalog') or [],
        'metric_targets': _metric_order_from_definitions(metric_definitions),
        'metric_definitions': metric_definitions,
        'prompt_extra_instructions': config.get('prompt_extra_instructions') or DEFAULT_LLM_PROMPT_EXTRA_INSTRUCTIONS,
        'metric_suggestions': metric_suggestions,
        'output_schema': {
            'metrics': {
                'LVEF': {'value': 62.0, 'unit': '%', 'evidence': 'LVEF: 62%'},
                'LVEDV': {'value': 135.0, 'unit': 'mL', 'evidence': 'LVEDV: 135 mL'}
            },
            'unexpected_metrics': [
                {'name': 'LA_SI', 'value': 76.3, 'unit': 'mm', 'evidence': 'LA_SI: 76.31 mm', 'reason': '明确出现，但未在预设指标列表中'}
            ],
        },
    }


def _llm_gateway_client(config):
    api_key = str(config.get('api_key') or '').strip()
    if not api_key:
        raise ValueError('API Key 未配置')
    base_url = _normalize_openai_base_url(config.get('api_base'))
    if not base_url:
        raise ValueError('API URL 未配置')
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        http_client=_llm_gateway_http_client(timeout=30.0),
    )


def _run_llm_gateway_health_check(config_override=None, persist_result=None):
    effective = dict(_load_llm_gateway_config())
    if config_override:
        effective.update({key: value for key, value in (config_override or {}).items() if value is not None})
    if persist_result is None:
        persist_result = not bool(config_override)
    checked_at = datetime.utcnow().isoformat() + 'Z'
    try:
        client = _llm_gateway_client(effective)
        started = time.time()
        response = client.chat.completions.create(
            model=effective.get('model') or DEFAULT_LLM_GATEWAY_CONFIG['model'],
            messages=[
                {'role': 'system', 'content': 'You are a health check responder.'},
                {'role': 'user', 'content': 'Reply with OK only.'},
            ],
            temperature=0,
            max_tokens=8,
        )
        latency_ms = int((time.time() - started) * 1000)
        content = ''
        try:
            content = (response.choices[0].message.content or '').strip()
        except Exception:
            content = ''
        result = {
            'ok': True,
            'checked_at': checked_at,
            'latency_ms': latency_ms,
            'message': content or 'OK',
            'model': effective.get('model') or DEFAULT_LLM_GATEWAY_CONFIG['model'],
            'base_url': _normalize_openai_base_url(effective.get('api_base')),
        }
    except Exception as exc:
        result = {
            'ok': False,
            'checked_at': checked_at,
            'latency_ms': None,
            'message': str(exc),
            'model': effective.get('model') or DEFAULT_LLM_GATEWAY_CONFIG['model'],
            'base_url': _normalize_openai_base_url(effective.get('api_base')),
        }

    if persist_result:
        persisted = dict(_load_llm_gateway_config())
        persisted['last_check'] = result
        _save_llm_gateway_config(persisted)
    return result


def _extract_json_object(raw_text):
    text = str(raw_text or '').strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None


def _render_llm_prompt_template(template, replacements, fallback):
    rendered = str(template or fallback or '').strip() or fallback
    for key, value in (replacements or {}).items():
        rendered = rendered.replace(f'{{{{{key}}}}}', str(value))
    return rendered


def _metric_extraction_prompt(
    report_text,
    source_label,
    metric_definitions=None,
    prompt_extra_instructions='',
    prompt_system_template='',
    prompt_user_template='',
):
    metric_lines = []
    for item in _normalize_metric_definitions(metric_definitions):
        metric_key = item['key']
        unit = item.get('unit', '')
        metric_lines.append(f'- {metric_key}{f" ({unit})" if unit else ""}')
    allowed_metrics = '\n'.join(metric_lines) if metric_lines else '- 无预设指标'
    effective_instructions = prompt_extra_instructions or DEFAULT_LLM_PROMPT_EXTRA_INSTRUCTIONS
    rendered_system_prompt = _render_llm_prompt_template(
        prompt_system_template,
        {},
        DEFAULT_LLM_PROMPT_SYSTEM_TEMPLATE,
    )
    rendered_user_prompt = _render_llm_prompt_template(
        prompt_user_template,
        {
            'source_label': source_label,
            'allowed_metrics': allowed_metrics,
            'prompt_extra_instructions': effective_instructions,
            'report_text': report_text,
        },
        DEFAULT_LLM_PROMPT_USER_TEMPLATE,
    )
    return [
        {
            'role': 'system',
            'content': rendered_system_prompt,
        },
        {
            'role': 'user',
            'content': rendered_user_prompt,
        },
    ]


def _normalize_llm_metric_payload(payload, metric_definitions=None):
    metrics = {}
    units = {}
    configured_keys = set(_metric_order_from_definitions(metric_definitions))
    raw_metrics = payload.get('metrics') if isinstance(payload, dict) else None
    if not isinstance(raw_metrics, dict):
        raw_metrics = {}
    for raw_key, raw_value in raw_metrics.items():
        metric_key = _normalize_metric_key(raw_key)
        if not metric_key:
            continue
        value = None
        unit = None
        if isinstance(raw_value, dict):
            value = _normalize_metric_value(raw_value.get('value'))
            unit = _normalize_unit(raw_value.get('unit'))
        else:
            value = _normalize_metric_value(raw_value)
        if value is None:
            continue
        metrics[metric_key] = value
        if unit:
            units[metric_key] = unit
    unexpected_metrics = payload.get('unexpected_metrics') if isinstance(payload, dict) else None
    if isinstance(unexpected_metrics, list):
        for item in unexpected_metrics:
            if not isinstance(item, dict):
                continue
            metric_key = _normalize_metric_key(item.get('name') or item.get('key') or item.get('label'))
            if not metric_key:
                continue
            if metric_key in configured_keys and metric_key in metrics:
                continue
            value = _normalize_metric_value(item.get('value'))
            if value is None:
                continue
            metrics.setdefault(metric_key, value)
            unit = _normalize_unit(item.get('unit'))
            if unit:
                units.setdefault(metric_key, unit)
    return metrics, units


def _hash_json_payload(payload):
    return std_hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')
    ).hexdigest()


def _hash_text_payload(text):
    return std_hashlib.sha256(str(text or '').encode('utf-8')).hexdigest()


def _iso_utc_now():
    return datetime.utcnow().isoformat() + 'Z'


def _llm_metric_cache_descriptor(dataset, case_id, source_label, report_text, config):
    LLM_METRIC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    model_name = str(config.get('model') or DEFAULT_LLM_GATEWAY_CONFIG['model']).strip()
    report_hash = _hash_text_payload(str(report_text or '').strip())
    prompt_hash = _hash_json_payload({
        'model': model_name,
        'temperature': float(config.get('temperature') or 0),
        'max_tokens': int(config.get('max_tokens') or DEFAULT_LLM_GATEWAY_CONFIG['max_tokens']),
        'metric_definitions': _normalize_metric_definitions(config.get('metric_definitions')),
        'prompt_system_template': str(config.get('prompt_system_template') or DEFAULT_LLM_PROMPT_SYSTEM_TEMPLATE).strip(),
        'prompt_user_template': str(config.get('prompt_user_template') or DEFAULT_LLM_PROMPT_USER_TEMPLATE).strip(),
        'prompt_extra_instructions': str(config.get('prompt_extra_instructions') or DEFAULT_LLM_PROMPT_EXTRA_INSTRUCTIONS).strip(),
    })
    digest = _hash_json_payload({
        'dataset': dataset,
        'case_id': case_id,
        'source': source_label,
        'model': model_name,
        'report_hash': report_hash,
        'prompt_hash': prompt_hash,
    })
    safe_name = re.sub(r'[^a-zA-Z0-9_-]+', '_', f'{dataset}_{case_id}_{source_label}')[:80]
    return (
        LLM_METRIC_CACHE_DIR / f'{safe_name}_{digest}.json',
        {
            'dataset': dataset,
            'case_id': case_id,
            'source_label': source_label,
            'model': model_name,
            'input_hash': digest,
            'report_hash': report_hash,
            'prompt_hash': prompt_hash,
        },
    )


def _extract_quantitative_metrics_with_llm(report_text, *, dataset, case_id, source_label):
    config = _load_llm_gateway_config()
    if not config.get('enabled') or not str(report_text or '').strip():
        return {}, {}, None

    cache_path, trace_base = _llm_metric_cache_descriptor(dataset, case_id, source_label, report_text, config)
    if cache_path.exists():
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            if isinstance(cached, dict) and 'result' in cached:
                cached_payload = cached.get('result') or {}
                cached_trace = dict(cached.get('_trace') or {})
            else:
                cached_payload = cached if isinstance(cached, dict) else {}
                cached_trace = {}
            cached_metrics, cached_units = _normalize_llm_metric_payload(cached_payload, config.get('metric_definitions'))
            return (
                cached_metrics,
                cached_units,
                {
                    **trace_base,
                    **cached_trace,
                    'cache_hit': True,
                    'cache_status': 'hit' if cached_trace else 'legacy-hit',
                    'generated_at': cached_trace.get('generated_at') or _iso_utc_now(),
                },
            )
        except Exception:
            pass

    client = _llm_gateway_client(config)
    messages = _metric_extraction_prompt(
        report_text,
        source_label,
        config.get('metric_definitions'),
        config.get('prompt_extra_instructions'),
        config.get('prompt_system_template'),
        config.get('prompt_user_template'),
    )
    response_text = ''
    started = time.time()
    try:
        response = client.chat.completions.create(
            model=config.get('model') or DEFAULT_LLM_GATEWAY_CONFIG['model'],
            messages=messages,
            temperature=float(config.get('temperature') or 0),
            max_tokens=int(config.get('max_tokens') or DEFAULT_LLM_GATEWAY_CONFIG['max_tokens']),
            response_format={'type': 'json_object'},
        )
        response_text = (response.choices[0].message.content or '').strip()
    except Exception:
        response = client.chat.completions.create(
            model=config.get('model') or DEFAULT_LLM_GATEWAY_CONFIG['model'],
            messages=messages,
            temperature=float(config.get('temperature') or 0),
            max_tokens=int(config.get('max_tokens') or DEFAULT_LLM_GATEWAY_CONFIG['max_tokens']),
        )
        response_text = (response.choices[0].message.content or '').strip()

    payload = _extract_json_object(response_text) or {}
    trace = {
        **trace_base,
        'cache_hit': False,
        'cache_status': 'miss',
        'generated_at': _iso_utc_now(),
        'latency_ms': int((time.time() - started) * 1000),
    }
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump({'_trace': trace, 'result': payload}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    metrics, units = _normalize_llm_metric_payload(payload, config.get('metric_definitions'))
    return metrics, units, trace


def _llm_metric_cache_exists(report_text, *, dataset, case_id, source_label, config=None):
    config = config or _load_llm_gateway_config()
    if not config.get('enabled') or not str(report_text or '').strip():
        return False
    cache_path, _ = _llm_metric_cache_descriptor(dataset, case_id, source_label, report_text, config)
    return cache_path.exists()


def _extract_ai_metrics_from_metrics_json(raw_ai):
    ai_metrics = {}
    ai_metric_units = {}
    if not isinstance(raw_ai, dict):
        return ai_metrics, ai_metric_units

    requested_metrics = raw_ai.get('requested_metrics')
    if isinstance(requested_metrics, list):
        for metric in requested_metrics:
            if not isinstance(metric, dict) or 'name' not in metric:
                continue
            value = metric.get('value')
            if value is not None and not isinstance(value, (dict, list)):
                ai_metrics[metric['name']] = value
            if metric.get('unit') is not None:
                ai_metric_units[metric['name']] = metric.get('unit')

    if ai_metrics:
        return ai_metrics, ai_metric_units

    raw_measurements = raw_ai.get('raw_measurements') if isinstance(raw_ai, dict) else None
    if not isinstance(raw_measurements, dict):
        return ai_metrics, ai_metric_units

    sax_metrics = raw_measurements.get('sax_metrics') or {}
    four_ch_metrics = raw_measurements.get('four_ch_metrics') or {}
    lv = sax_metrics.get('lv') or {}
    rv = sax_metrics.get('rv') or {}
    structure = sax_metrics.get('structure') or {}
    if 'EF_percent' in lv:
        ai_metrics['LVEF'] = lv['EF_percent']
        ai_metric_units['LVEF'] = '%'
    if 'EDV_ml' in lv:
        ai_metrics['LVEDV'] = lv['EDV_ml']
        ai_metric_units['LVEDV'] = 'mL'
    if 'ESV_ml' in lv:
        ai_metrics['LVESV'] = lv['ESV_ml']
        ai_metric_units['LVESV'] = 'mL'
    if 'SV_ml' in lv:
        ai_metrics['SV'] = lv['SV_ml']
        ai_metric_units['SV'] = 'mL'
    if 'EF_percent' in rv:
        ai_metrics['RVEF'] = rv['EF_percent']
        ai_metric_units['RVEF'] = '%'
    if 'EDV_ml' in rv:
        ai_metrics['RVEDV'] = rv['EDV_ml']
        ai_metric_units['RVEDV'] = 'mL'
    if 'ESV_ml' in rv:
        ai_metrics['RVESV'] = rv['ESV_ml']
        ai_metric_units['RVESV'] = 'mL'
    if 'ivs_thickness_mm' in structure:
        ai_metrics['IVS'] = structure['ivs_thickness_mm']
        ai_metric_units['IVS'] = 'mm'
    if 'lvpw_thickness_mm' in structure:
        ai_metrics['LVPW'] = structure['lvpw_thickness_mm']
        ai_metric_units['LVPW'] = 'mm'
    if 'LA_volume_ml' in four_ch_metrics:
        ai_metrics['LAV'] = four_ch_metrics['LA_volume_ml']
        ai_metric_units['LAV'] = 'mL'
    if 'RA_volume_ml' in four_ch_metrics:
        ai_metrics['RAV'] = four_ch_metrics['RA_volume_ml']
        ai_metric_units['RAV'] = 'mL'
    if 'LA_SI_mm' in four_ch_metrics:
        ai_metrics['LA_SI'] = four_ch_metrics['LA_SI_mm']
        ai_metric_units['LA_SI'] = 'mm'
    if 'LA_LR_mm' in four_ch_metrics:
        ai_metrics['LA_LR'] = four_ch_metrics['LA_LR_mm']
        ai_metric_units['LA_LR'] = 'mm'
    if 'RA_SI_mm' in four_ch_metrics:
        ai_metrics['RA_SI'] = four_ch_metrics['RA_SI_mm']
        ai_metric_units['RA_SI'] = 'mm'
    if 'RA_LR_mm' in four_ch_metrics:
        ai_metrics['RA_LR'] = four_ch_metrics['RA_LR_mm']
        ai_metric_units['RA_LR'] = 'mm'
    return ai_metrics, ai_metric_units


def _normalize_metric_value(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text.lower() in {'nan', 'n/a', 'none', '-', '--'}:
        return None
    match = re.search(r'-?\d+(?:\.\d+)?', text.replace(',', ''))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _normalize_metric_map(metrics):
    normalized = {}
    if not isinstance(metrics, dict):
        return normalized
    for key, value in metrics.items():
        metric_key = _normalize_metric_key(key)
        if not metric_key:
            continue
        normalized[metric_key] = _normalize_metric_value(value)
    return normalized


def _normalize_unit(unit):
    text = str(unit or '').strip().lower()
    if not text:
        return ''
    if text in {'%', 'percent', 'percentage'}:
        return '%'
    if text in {'ml', 'm l', '毫升'}:
        return 'mL'
    if text in {'mm', '毫米'}:
        return 'mm'
    if text in {'l/min', 'l min', 'lpm'}:
        return 'L/min'
    if text in {'l/min/m²', 'l/min/m2', 'l min m2', 'l/min/m^2'}:
        return 'L/min/m²'
    if text in {'g', 'gram'}:
        return 'g'
    if text in {'ms', '毫秒'}:
        return 'ms'
    return text


def _normalize_metric_units(metric_units):
    normalized = {}
    if not isinstance(metric_units, dict):
        return normalized
    for key, unit in metric_units.items():
        metric_key = _normalize_metric_key(key)
        if not metric_key:
            continue
        normalized[metric_key] = _normalize_unit(unit)
    return normalized


def _classify_metric_against_range(value, metric_rule):
    if value is None:
        return None
    metric_range = metric_rule.get('reference_range')
    if not metric_range or len(metric_range) != 2:
        return None
    lower, upper = metric_range
    if value < lower:
        return 'low'
    if value > upper:
        return 'high'
    return 'normal'


def _build_quantitative_accuracy_summary(report_metrics, ai_metrics, ai_metric_units=None, metric_definitions=None, trace=None):
    report_values = _normalize_metric_map(report_metrics)
    ai_values = _normalize_metric_map(ai_metrics)
    ai_units = _normalize_metric_units(ai_metric_units)
    metric_order = _metric_order_from_definitions(metric_definitions)
    metric_rules = _metric_rules_from_definitions(metric_definitions)

    ordered_keys = []
    seen = set()
    for metric_key in metric_order + list(report_values.keys()) + list(ai_values.keys()):
        if metric_key in seen:
            continue
        seen.add(metric_key)
        ordered_keys.append(metric_key)

    rows = []
    comparable_count = 0
    within_tolerance_count = 0
    missing_ai_count = 0
    missing_reference_count = 0
    unit_checked_count = 0
    unit_consistent_count = 0
    abnormal_checked_count = 0
    abnormal_consistent_count = 0

    for metric_key in ordered_keys:
        report_value = report_values.get(metric_key)
        ai_value = ai_values.get(metric_key)
        if report_value is None and ai_value is None:
            continue

        rule = metric_rules.get(metric_key, {})
        unit = rule.get('unit', '')
        tolerance_abs = rule.get('tolerance_abs')
        abs_error = round(abs(ai_value - report_value), 2) if report_value is not None and ai_value is not None else None
        rel_error_pct = None
        if abs_error is not None and report_value not in (None, 0):
            rel_error_pct = round(abs_error / abs(report_value) * 100.0, 1)

        within_tolerance = None
        if abs_error is not None and tolerance_abs is not None:
            comparable_count += 1
            within_tolerance = abs_error <= tolerance_abs
            if within_tolerance:
                within_tolerance_count += 1

        if report_value is not None and ai_value is None:
            missing_ai_count += 1
        if report_value is None and ai_value is not None:
            missing_reference_count += 1

        ai_unit = ai_units.get(metric_key, '')
        unit_consistent = None
        if unit:
            normalized_ai_unit = _normalize_unit(ai_unit)
            if normalized_ai_unit:
                unit_checked_count += 1
                unit_consistent = normalized_ai_unit == _normalize_unit(unit)
                if unit_consistent:
                    unit_consistent_count += 1

        report_abnormal = _classify_metric_against_range(report_value, rule)
        ai_abnormal = _classify_metric_against_range(ai_value, rule)
        abnormal_consistent = None
        if report_abnormal is not None and ai_abnormal is not None:
            abnormal_checked_count += 1
            abnormal_consistent = report_abnormal == ai_abnormal
            if abnormal_consistent:
                abnormal_consistent_count += 1

        rows.append({
            'metric': metric_key,
            'label': rule.get('label', metric_key),
            'unit': unit,
            'expected_unit': unit,
            'ai_unit': ai_unit or None,
            'reference_value': report_value,
            'ai_value': ai_value,
            'abs_error': abs_error,
            'rel_error_pct': rel_error_pct,
            'tolerance_abs': tolerance_abs,
            'within_tolerance': within_tolerance,
            'report_abnormal': report_abnormal,
            'ai_abnormal': ai_abnormal,
            'abnormal_consistent': abnormal_consistent,
        })

    pass_rate = round(within_tolerance_count / comparable_count * 100.0, 1) if comparable_count else None
    if comparable_count == 0:
        overall_level = 'insufficient'
        overall_text = '暂无足够定量对照'
    elif within_tolerance_count == comparable_count:
        overall_level = 'good'
        overall_text = '定量误差整体在阈值内'
    elif pass_rate is not None and pass_rate >= 70:
        overall_level = 'warning'
        overall_text = '大部分指标在阈值内，少数需复核'
    else:
        overall_level = 'poor'
        overall_text = '多项指标误差偏大，建议重点复核'

    return {
        'summary': {
            'displayed_metrics': len(rows),
            'comparable_metrics': comparable_count,
            'within_tolerance_count': within_tolerance_count,
            'pass_rate': pass_rate,
            'missing_ai_metrics': missing_ai_count,
            'missing_reference_metrics': missing_reference_count,
            'unit_checked_metrics': unit_checked_count,
            'unit_consistent_count': unit_consistent_count,
            'abnormal_checked_metrics': abnormal_checked_count,
            'abnormal_consistent_count': abnormal_consistent_count,
            'overall_level': overall_level,
            'overall_text': overall_text,
        },
        'thresholds': [
            {'label': '射血分数类', 'rule': '误差 <= 5 个百分点', 'metrics': ['LVEF', 'RVEF']},
            {'label': '容积类', 'rule': '误差 <= 15 mL', 'metrics': ['LVEDV', 'LVESV', 'SV', 'RVEDV', 'RVESV', 'LAV', 'RAV']},
            {'label': '距离/厚度类', 'rule': '误差 <= 3 mm', 'metrics': ['LVEDD', 'RVEDD', 'IVS', 'LVPW']},
            {'label': '比例/指数类', 'rule': '误差 <= 0.08-0.15', 'metrics': ['RWT', 'SI', 'LV/RV ratio']},
        ],
        'notes': [
            '这是便于快速扫一眼的粗评标准，不替代正式统计学验证。',
            '异常判断使用成人通用参考范围，仅用于辅助复核；容积类指标受性别、体表面积影响较大，因此默认不做自动异常判定。',
        ],
        'trace': trace or {},
        'rows': rows,
    }


def _base_dataset_name(dataset_name):
    if not dataset_name:
        return ''
    normalized = str(dataset_name).strip()
    if normalized.startswith('new_'):
        normalized = normalized.replace('new_', '', 1)
    if normalized.startswith('SOLO_CMR_ALL_'):
        return 'CMR_ALL'
    if normalized.startswith('SOLO_CMR_Chendu_'):
        return 'CMR_Chendu'
    if normalized.startswith('SOLO_CMR_SCS_'):
        return 'CMR_SCS'
    if normalized.startswith('SOLO_CMR_YA_'):
        return 'CMR_YA'
    return normalized


def _dataset_storage_candidates(dataset_name):
    if not dataset_name:
        return []

    raw = str(dataset_name).strip()
    base = _base_dataset_name(raw)
    candidates = [raw]

    if raw.startswith('new_'):
        candidates.append(raw.replace('new_', '', 1))
    elif raw and not raw.startswith('SOLO_'):
        candidates.append(f'new_{raw}')

    if base and base not in candidates:
        candidates.append(base)

    if base:
        new_base = f'new_{base}'
        if new_base not in candidates:
            candidates.append(new_base)

    values = []
    for item in candidates:
        if item and item not in values:
            values.append(item)
    return values


def _resolve_case_dir(root, dataset_name, case_id):
    case_candidates = [str(case_id or '')]
    basename = Path(str(case_id or '')).name
    if basename and basename not in case_candidates:
        case_candidates.append(basename)

    for candidate in _dataset_storage_candidates(dataset_name):
        for case_candidate in case_candidates:
            case_path = os.path.join(root, candidate, case_candidate)
            if os.path.exists(case_path):
                return case_path, candidate
    return os.path.join(root, str(dataset_name or ''), case_candidates[0]), str(dataset_name or '')


def _normalize_dataset_name(dataset_name):
    return _base_dataset_name(dataset_name)


def _excel_dataset_config(dataset_name):
    return EXCEL_DATASET_CONFIGS.get(_normalize_dataset_name(dataset_name))


def _excel_file_path(filename):
    if os.path.isabs(str(filename)) and os.path.exists(str(filename)):
        return str(filename)
    candidates = [
        os.path.join(DATA_SOURCES_DIR, filename),
        os.path.join(os.path.dirname(DATA_SOURCES_DIR), filename),
        os.path.join(os.path.dirname(os.path.dirname(DATA_SOURCES_DIR)), filename),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return candidates[0]


def _normalize_excel_cell(value):
    if value is None or pd.isna(value):
        return ''
    text = str(value).replace('_x000D_', '')
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    lines = [line.rstrip() for line in text.split('\n')]
    return '\n'.join(lines).strip()


def _normalized_id_variants(raw_value):
    text = _normalize_excel_cell(raw_value)
    if not text:
        return set()

    variants = {text}

    parts = re.split(r'[_/\-\s]+', text)
    for part in parts:
        normalized_part = part.strip()
        if not normalized_part:
            continue
        variants.add(normalized_part)
        digits = ''.join(ch for ch in normalized_part if ch.isdigit())
        if digits:
            variants.add(digits)
            variants.add(digits.lstrip('0') or '0')

    digits = ''.join(ch for ch in text if ch.isdigit())
    if digits:
        variants.add(digits)
        variants.add(digits.lstrip('0') or '0')

    return {item for item in variants if item}


def _normalized_date_digits(raw_value):
    text = _normalize_excel_cell(raw_value)
    if not text:
        return ''
    try:
        parsed = pd.to_datetime(text, errors='coerce')
        if not pd.isna(parsed):
            return parsed.strftime('%Y%m%d')
    except Exception:
        pass
    match = re.search(r'(20\d{2}|19\d{2})\D?(\d{1,2})\D?(\d{1,2})', text)
    if not match:
        return ''.join(ch for ch in text if ch.isdigit())[:8]
    year, month, day = match.groups()
    return f'{year}{int(month):02d}{int(day):02d}'


def _looks_like_dicom_file(path):
    name = Path(path).name.strip()
    lower = name.lower()
    if lower.endswith(('.dcm', '.ima')):
        return True
    if lower == 'dicomdir':
        return False
    return bool(re.fullmatch(r'(?:im[_-]?)?\d{4,}', lower) or re.fullmatch(r'\d[\d.]{15,}', lower))


def _find_first_dicom_file(case_path):
    if not case_path:
        return None
    root = Path(case_path)
    if not root.exists():
        return None
    try:
        for item in root.rglob('*'):
            if item.is_file() and _looks_like_dicom_file(item):
                return item
    except OSError:
        return None
    return None


def _read_dicom_identity(case_path):
    dicom_file = _find_first_dicom_file(case_path)
    if not dicom_file:
        return {}
    try:
        ds = pydicom.dcmread(str(dicom_file), stop_before_pixels=True, force=True)
    except Exception:
        return {}
    return {
        'patient_name': _normalize_excel_cell(getattr(ds, 'PatientName', '')),
        'patient_id': _normalize_excel_cell(getattr(ds, 'PatientID', '')),
        'study_date': _normalized_date_digits(getattr(ds, 'StudyDate', '')),
        'accession_number': _normalize_excel_cell(getattr(ds, 'AccessionNumber', '')),
    }


def _dicom_identity_for_catalog_case(dataset_name, case_id):
    try:
        case = CviCaseCatalog.query.filter_by(
            source='functional',
            dataset=_normalize_dataset_name(dataset_name),
            case_id=str(case_id or ''),
        ).first()
        if case is None:
            case = CviCaseCatalog.query.filter_by(
                dataset=_normalize_dataset_name(dataset_name),
                case_id=str(case_id or ''),
            ).first()
        if case is not None:
            return _read_dicom_identity(case.path)
    except Exception:
        pass
    return {}


def _row_matches_dicom_identity(row, dicom_identity, match_config):
    if not dicom_identity or not match_config:
        return False

    accession = dicom_identity.get('accession_number')
    if accession:
        for col in match_config.get('accession_cols', []):
            if col in row and accession in _normalized_id_variants(row[col]):
                return True

    patient_id = dicom_identity.get('patient_id')
    if patient_id:
        for col in match_config.get('patient_id_cols', []):
            if col in row and patient_id in _normalized_id_variants(row[col]):
                return True

    study_date = dicom_identity.get('study_date')
    if study_date:
        for col in match_config.get('study_date_cols', []):
            if col in row and _normalized_date_digits(row[col]) == study_date:
                return True
    return False


def _find_matching_excel_row_by_dicom(df, match_config, dicom_identity):
    if not match_config or not dicom_identity:
        return None
    for _, row in df.iterrows():
        if _row_matches_dicom_identity(row, dicom_identity, match_config):
            return row
    return None


def _find_manual_excel_index_override_row(df, dataset_name, case_id):
    manual_index = MANUAL_EXCEL_INDEX_OVERRIDES.get(
        (_normalize_dataset_name(dataset_name), str(case_id or '').strip())
    )
    if not manual_index or 'Index' not in df.columns:
        return None
    for _, row in df.iterrows():
        if _normalize_excel_cell(row.get('Index')) == manual_index:
            return row
    return None


def _find_matching_excel_row(df, id_col, case_id):
    if id_col not in df.columns:
        return None

    normalized_case_id = str(case_id or '').strip()
    case_variants = _normalized_id_variants(normalized_case_id)
    if not case_variants:
        return None

    lookup_cache_key = f'{id_col}::{id(df)}'
    lookup = excel_row_lookup_cache.get(lookup_cache_key)
    if lookup is None:
        lookup = {}
        for row_index, raw_value in df[id_col].items():
            excel_id = _normalize_excel_cell(raw_value)
            if not excel_id:
                continue
            for variant in _normalized_id_variants(excel_id):
                lookup.setdefault(variant, row_index)
        excel_row_lookup_cache[lookup_cache_key] = lookup

    for variant in case_variants:
        row_index = lookup.get(variant)
        if row_index is not None:
            try:
                return df.loc[row_index]
            except Exception:
                continue
    return None


def _collect_excel_sections(row, columns):
    sections = []
    for col in columns:
        if col not in row:
            continue
        value = _normalize_excel_cell(row[col])
        if not value:
            continue
        sections.append({
            'title': col,
            'text': value,
        })
    return sections


def _render_section_text(sections):
    parts = []
    for section in sections:
        title = str(section.get('title') or '').strip()
        text = str(section.get('text') or '').strip()
        if not text:
            continue
        if title:
            parts.append(f"{title}\n{text}")
        else:
            parts.append(text)
    return '\n\n'.join(parts).strip()


def _render_raw_report_markdown(description_sections, conclusion_sections, extra_sections):
    blocks = []
    if description_sections:
        blocks.append('### 影像描述')
        for section in description_sections:
            blocks.append(f"#### {section['title']}\n{section['text']}")
    if conclusion_sections:
        blocks.append('### 影像结论')
        for section in conclusion_sections:
            blocks.append(f"#### {section['title']}\n{section['text']}")
    if extra_sections:
        blocks.append('### 补充信息')
        for section in extra_sections:
            blocks.append(f"#### {section['title']}\n{section['text']}")
    return '\n\n'.join(blocks).strip()


def build_raw_report_from_excel(dataset_name, case_id):
    config = _excel_dataset_config(dataset_name)
    if not config:
        return None

    excel_file = config['excel_file']
    df = get_excel_data(excel_file, header_row=config.get('header_row'))
    if df is None:
        return None

    id_col = config['id_col']
    if id_col not in df.columns:
        print(f"Column {id_col} not found in {excel_file}")
        return None

    match_strategy = None
    matched_row = _find_manual_excel_index_override_row(df, dataset_name, case_id)
    if matched_row is not None:
        match_strategy = 'manual_excel_index'
    dicom_identity = _dicom_identity_for_catalog_case(dataset_name, case_id)
    if matched_row is None:
        matched_row = _find_matching_excel_row_by_dicom(df, config.get('dicom_match'), dicom_identity)
        if matched_row is not None:
            match_strategy = 'dicom_identity'
    if matched_row is None:
        matched_row = _find_matching_excel_row(df, id_col, case_id)
        if matched_row is not None:
            match_strategy = 'case_id'
    if matched_row is None:
        return None

    description_sections = _collect_excel_sections(matched_row, config.get('description_cols', []))
    conclusion_sections = _collect_excel_sections(matched_row, config.get('conclusion_cols', []))
    extra_sections = _collect_excel_sections(matched_row, config.get('extra_cols', []))

    return {
        'source': 'excel',
        'dataset': _normalize_dataset_name(dataset_name),
        'excel_file': excel_file,
        'excel_path': _excel_file_path(excel_file),
        'excel_member': _normalize_excel_cell(matched_row.get('__source_member__')) if '__source_member__' in matched_row else None,
        'id_column': id_col,
        'match_strategy': match_strategy,
        'description_sections': description_sections,
        'conclusion_sections': conclusion_sections,
        'extra_sections': extra_sections,
        'description_text': _render_section_text(description_sections),
        'conclusion_text': _render_section_text(conclusion_sections),
        'extra_text': _render_section_text(extra_sections),
        'markdown': _render_raw_report_markdown(description_sections, conclusion_sections, extra_sections),
    }


def find_raw_report_from_excel(dataset_name, case_id):
    report = build_raw_report_from_excel(dataset_name, case_id)
    if not report:
        return None
    return report.get('markdown') or None


def _build_standard_report_payload(*, source='generated', description_sections=None, conclusion_sections=None, extra_sections=None):
    description_sections = description_sections or []
    conclusion_sections = conclusion_sections or []
    extra_sections = extra_sections or []
    return {
        'source': source,
        'description_sections': description_sections,
        'conclusion_sections': conclusion_sections,
        'extra_sections': extra_sections,
        'description_text': _render_section_text(description_sections),
        'conclusion_text': _render_section_text(conclusion_sections),
        'extra_text': _render_section_text(extra_sections),
        'markdown': _render_raw_report_markdown(description_sections, conclusion_sections, extra_sections),
    }


def _requested_review_user_id(payload=None):
    raw_value = request.args.get('review_user_id')
    if raw_value in (None, '') and isinstance(payload, dict):
        raw_value = payload.get('review_user_id')
    if raw_value in (None, ''):
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def _normalize_email(email):
    return str(email or '').strip().lower()


def _valid_email(email):
    normalized = _normalize_email(email)
    if not normalized or len(normalized) > 255:
        return False
    return bool(re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', normalized))


def _can_send_message(sender, recipient):
    if sender is None or recipient is None:
        return False
    if int(sender.id) == int(recipient.id):
        return False
    if sender.is_admin:
        return True
    return bool(recipient.is_admin)


def _approved_admin_users():
    return User.query.filter_by(is_admin=True, is_approved=True).order_by(User.username.asc()).all()


def _create_system_message(*, recipient_id: int, subject: str, body: str, category: str = 'system_notice') -> None:
    message_record = UserMessage(
        sender_id=None,
        recipient_id=recipient_id,
        subject=(subject or '').strip()[:200],
        body=(body or '').strip(),
        category=(category or 'system_notice').strip() or 'system_notice',
        is_read=False,
        created_at=datetime.utcnow(),
    )
    db.session.add(message_record)


def _effective_rater_id(payload=None):
    if not getattr(current_user, 'is_authenticated', False):
        return None
    requested_id = _requested_review_user_id(payload)
    if getattr(current_user, 'is_admin', False) and requested_id:
        target_user = User.query.get(requested_id)
        if target_user is not None:
            return int(target_user.id)
    return int(current_user.id)


def _effective_rater_user(payload=None):
    rater_id = _effective_rater_id(payload)
    if not rater_id:
        return None
    return User.query.get(rater_id)


def _dataset_aliases(dataset: str | None) -> list[str]:
    if not dataset:
        return []
    values: list[str] = []
    candidates = [dataset]
    if dataset.startswith('new_'):
        candidates.append(dataset.replace('new_', '', 1))
    else:
        candidates.append(f'new_{dataset}')
    for item in candidates:
        if item and item not in values:
            values.append(item)
    return values


def _canonical_dataset(dataset: str | None) -> str:
    if not dataset:
        return ''
    return dataset.replace('new_', '', 1) if dataset.startswith('new_') else dataset


def _configured_assessment_roots() -> list[Path]:
    roots: list[Path] = []
    raw_roots = [
        current_app.config.get('FUNCTIONAL_DATA_ROOT'),
        current_app.config.get('DATA_ROOT'),
        *[
            item.get('path')
            for item in current_app.config.get('CVI_LIBRARY_MULTICENTER_ROOTS', [])
            if isinstance(item, dict)
        ],
    ]
    for raw_root in raw_roots:
        if not raw_root:
            continue
        root = Path(str(raw_root)).expanduser().resolve(strict=False)
        if root not in roots:
            roots.append(root)
    return roots


def _path_is_within_roots(path: Path, roots: list[Path]) -> bool:
    resolved = path.expanduser().resolve(strict=False)
    return any(resolved == root or root in resolved.parents for root in roots)


def _resolve_assessment_case_path(dataset: str, case_id: str) -> Path | None:
    """Resolve the selected catalogue case without exposing arbitrary database paths."""
    raw_case_id = str(case_id or '').strip()
    if not raw_case_id or Path(raw_case_id).is_absolute() or '..' in Path(raw_case_id).parts:
        return None

    allowed_roots = _configured_assessment_roots()
    catalog_rows = (
        CviCaseCatalog.query
        .filter(
            CviCaseCatalog.dataset.in_(_dataset_aliases(dataset)),
            CviCaseCatalog.case_id == raw_case_id,
            CviCaseCatalog.source.in_(['functional', 'annotation']),
        )
        .order_by(CviCaseCatalog.updated_at.desc(), CviCaseCatalog.id.desc())
        .all()
    )
    for row in catalog_rows:
        candidate = Path(row.path).expanduser().resolve(strict=False)
        if candidate.is_dir() and _path_is_within_roots(candidate, allowed_roots):
            return candidate

    functional_root = Path(str(current_app.config['FUNCTIONAL_DATA_ROOT'])).expanduser().resolve(strict=False)
    for dataset_alias in _dataset_aliases(dataset):
        candidate = (functional_root / dataset_alias / raw_case_id).resolve(strict=False)
        if candidate.is_dir() and _path_is_within_roots(candidate, [functional_root]):
            return candidate
    return None


def _latest_assessment_for_aliases(model_class, dataset: str, case_id: str, rater_id: int, report_version: str | None = None):
    query = model_class.query.filter(
        model_class.case_id == case_id,
        model_class.rater_id == rater_id,
        model_class.dataset.in_(_dataset_aliases(dataset)),
    )
    if report_version and hasattr(model_class, 'report_version'):
        query = query.filter(model_class.report_version == str(report_version).strip().upper())
    return query.order_by(model_class.created_at.desc()).first()


def _evaluation_has_content(*, score_coverage=None, score_consistency=None, score_hallucination=None, dimension_scores=None, comment=''):
    if any(value not in [None, '', 0] for value in [score_coverage, score_consistency, score_hallucination]):
        return True
    if isinstance(dimension_scores, dict) and any(value not in [None, '', 0] for value in dimension_scores.values()):
        return True
    return bool(str(comment or '').strip())


def _parse_sequence_image_tokens(image_path: str) -> tuple[str, str]:
    file_name = os.path.basename(image_path)
    stem, _ = os.path.splitext(file_name)
    parts = stem.split('-')
    bucket = parts[1] if len(parts) > 1 else '0001'
    phase_label = parts[2] if len(parts) > 2 else '0001'
    return bucket, phase_label


def _resolve_eval_case_dir(eval_root: str, dataset: str, case_id: str) -> str | None:
    if not eval_root:
        return None

    possible_paths = [
        os.path.join(eval_root, dataset, case_id),
        os.path.join(eval_root, f"new_{dataset}", case_id),
        os.path.join(eval_root, dataset.replace("new_", ""), case_id),
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return path
    return None


def _load_metrics_phase_targets(eval_root: str, dataset: str, case_id: str) -> dict[str, dict[str, float]]:
    case_eval_path = _resolve_eval_case_dir(eval_root, dataset, case_id)
    if not case_eval_path:
        return {}

    metrics_path = os.path.join(case_eval_path, 'metrics.json')
    if not os.path.exists(metrics_path):
        return {}

    try:
        with open(metrics_path, 'r', encoding='utf-8') as f:
            raw_metrics = json.load(f)
    except Exception as exc:
        print(f"Error loading metrics for phase labels {case_id}: {exc}")
        return {}

    raw_measurements = raw_metrics.get('raw_measurements', {}) if isinstance(raw_metrics, dict) else {}
    sax_assignments = raw_measurements.get('sax_metrics', {}).get('phase_assignments', {}) or {}
    four_ch_assignments = raw_measurements.get('four_ch_metrics', {}).get('phase_assignments', {}) or {}

    def extract_targets(assignments: dict) -> dict[str, float]:
        targets: dict[str, float] = {}
        if not isinstance(assignments, dict):
            return targets
        for target_key, assignment_key in (('ed', 'ED_trigger'), ('es', 'ES_trigger')):
            value = assignments.get(assignment_key)
            if value is None:
                continue
            try:
                targets[target_key] = float(value)
            except (TypeError, ValueError):
                continue
        return targets

    sax_targets = extract_targets(sax_assignments)
    four_ch_targets = extract_targets(four_ch_assignments)

    if not four_ch_targets and sax_targets:
        four_ch_targets = dict(sax_targets)

    targets_by_sequence: dict[str, dict[str, float]] = {}
    if sax_targets:
        targets_by_sequence['SAX'] = sax_targets
    if four_ch_targets:
        targets_by_sequence['4CH'] = four_ch_targets
    return targets_by_sequence


def _sequence_phase_trigger_map(case_path: str, sequence: str, images: list[str]) -> dict[str, float]:
    if not images:
        return {}

    reference_bucket = None
    if sequence == 'SAX':
        reference_bucket, _ = _parse_sequence_image_tokens(images[0])

    phase_triggers: dict[str, float] = {}
    for relative_path in images:
        bucket, phase_label = _parse_sequence_image_tokens(relative_path)
        if sequence == 'SAX' and reference_bucket is not None and bucket != reference_bucket:
            continue
        if phase_label in phase_triggers:
            continue

        file_path = os.path.join(case_path, relative_path)
        try:
            ds = pydicom.dcmread(file_path, stop_before_pixels=True, specific_tags=['TriggerTime'])
            trigger_time = getattr(ds, 'TriggerTime', None)
            if trigger_time is None:
                continue
            phase_triggers[phase_label] = float(trigger_time)
        except Exception as exc:
            print(f"Error reading trigger time from {file_path}: {exc}")
            continue

    return phase_triggers


def _nearest_phase_label(target_trigger: float | None, phase_triggers: dict[str, float]) -> str | None:
    if target_trigger is None or not phase_triggers:
        return None

    best_label = None
    best_delta = None
    for label, trigger_time in phase_triggers.items():
        delta = abs(trigger_time - target_trigger)
        if best_delta is None or delta < best_delta:
            best_label = label
            best_delta = delta
    return best_label


def _build_sequence_phase_labels(
    case_path: str,
    dataset: str,
    case_id: str,
    images: dict[str, list[str]],
    eval_root: str,
) -> dict[str, dict[str, str]]:
    targets_by_sequence = _load_metrics_phase_targets(eval_root, dataset, case_id)
    if not targets_by_sequence:
        return {}

    phase_labels: dict[str, dict[str, str]] = {}
    for sequence in ('SAX', '4CH'):
        targets = targets_by_sequence.get(sequence)
        if not targets:
            continue
        phase_triggers = _sequence_phase_trigger_map(case_path, sequence, images.get(sequence, []))
        if not phase_triggers:
            continue

        resolved = {
            phase_key: _nearest_phase_label(target_trigger, phase_triggers)
            for phase_key, target_trigger in targets.items()
        }
        filtered = {phase_key: label for phase_key, label in resolved.items() if label is not None}
        if filtered:
            phase_labels[sequence] = filtered

    return phase_labels

# Global SAM model cache
sam_model = None
sam_predictor = None

def get_sam_predictor():
    global sam_model, sam_predictor
    if sam_predictor is None:
        try:
            from segment_anything import sam_model_registry, SamPredictor
            
            checkpoint = os.path.join("backend", "checkpoints", "sam_vit_h_4b8939.pth")
            if not os.path.exists(checkpoint):
                print(f"SAM Checkpoint not found at {checkpoint}")
                return None
                
            model_type = "vit_h"
            device = "cuda" if torch.cuda.is_available() else "cpu"
            
            print(f"Loading SAM model ({model_type}) to {device}...")
            sam = sam_model_registry[model_type](checkpoint=checkpoint)
            sam.to(device=device)
            sam_predictor = SamPredictor(sam)
            print("SAM Model Loaded Successfully")
        except ImportError:
            print("segment_anything not installed")
        except Exception as e:
            print(f"Error loading SAM: {e}")
    return sam_predictor

import tarfile
import zipfile
import shutil
import hashlib
from werkzeug.utils import secure_filename

from pathlib import Path
import sys
import threading
import queue
import time
from datetime import datetime, timedelta
from functools import wraps

# Add src to sys.path
SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src')
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# Import DiagnosisPipeline (lazy import inside route might be better to avoid circular deps if any, but top level is fine usually)
# However, DiagnosisPipeline imports config which imports other things. 
# Let's try importing here.
try:
    from pipelines.diagnosis_pipeline import DiagnosisPipeline
except ImportError:
    print("Warning: Could not import DiagnosisPipeline. Make sure src directory is correct.")

def validate_structure(target_dir: str) -> tuple[bool, str]:
    """
    检查解压后的目录结构是否符合预期
    """
    target_path = Path(target_dir)
    required_dirs = ["4CH", "SAX"]
    # LGE is sometimes named differently (e.g. LGE=15-22), so we look for any directory starting with LGE
    # or just enforce existence of LGE if strictly following reference.
    # The reference code had: required_dirs = ["4CH", "LGE=15-22", "SAX"] which is very specific.
    # However, in get_functional_case_detail I saw logic to scan for LGE*.
    # Let's be a bit flexible but ensure at least 4CH and SAX exist, and verify LGE exists.
    
    missing = []
    if not (target_path / "4CH").is_dir():
        missing.append("4CH")
    if not (target_path / "SAX").is_dir():
        missing.append("SAX")
    
    # Check for LGE
    lge_found = False
    for item in target_path.iterdir():
        if item.is_dir() and "LGE" in item.name:
            lge_found = True
            break
    if not lge_found:
        missing.append("LGE (or similar)")

    required_files = ["patient_info.json"]
    for f in required_files:
        if not (target_path / f).is_file():
            missing.append(f)

    if missing:
        return False, f"Missing: {', '.join(missing)}"

    return True, "Valid"

def find_patient_info_dir(search_dir: Path) -> Path:
    """
    递归搜索 patient_info.json 所在的目录。
    """
    # Check current
    if (search_dir / "patient_info.json").exists():
        return search_dir

    # Recursive search
    for item in search_dir.iterdir():
        if item.is_dir() and not item.name.startswith(".") and item.name != "__MACOSX":
            result = find_patient_info_dir(item)
            if result != item:
                return result
            if (item / "patient_info.json").exists():
                return item

    return search_dir

def flatten_directory(target_dir: str):
    """
    智能展平目录结构。
    """
    target_path = Path(target_dir)
    
    def is_ignorable(path: Path) -> bool:
        return path.name.startswith(".") or path.name == "__MACOSX"

    patient_info_dir = find_patient_info_dir(target_path)

    if patient_info_dir == target_path:
        return

    # Move content from patient_info_dir to target_path
    # First clear target_path (except patient_info_dir path components)
    # But wait, we might delete the folder we are trying to move from if it's a direct child.
    # The reference implementation deletes everything in target_dir first.
    # Let's follow reference logic carefully.
    
    # Reference logic:
    # 1. Clear target_dir (except ignorable)
    # 2. Move contents of patient_info_dir to target_dir
    # 3. Clean up empty dirs
    
    # However, if patient_info_dir is a subdirectory of target_dir, we must NOT delete it in step 1.
    
    # Let's implement a safer move: move to a temp dir, clear target, move back.
    import tempfile
    
    # If patient_info_dir is effectively valid
    if not patient_info_dir.exists():
        return

    # Move contents of patient_info_dir to a temp folder
    with tempfile.TemporaryDirectory() as tmp_dir:
        for item in patient_info_dir.iterdir():
            if not is_ignorable(item):
                shutil.move(str(item), tmp_dir)
        
        # Now clear target_path
        for item in target_path.iterdir():
             if item.is_dir():
                 shutil.rmtree(item)
             else:
                 item.unlink()
        
        # Move back from temp to target_path
        for item in Path(tmp_dir).iterdir():
            shutil.move(str(item), str(target_path))


def _safe_archive_member_path(target_dir: str, member_name: str) -> str:
    target_root = os.path.realpath(target_dir)
    member_path = os.path.realpath(os.path.join(target_root, member_name))
    if member_path != target_root and not member_path.startswith(target_root + os.sep):
        raise ValueError(f"Unsafe archive member path: {member_name}")
    return member_path


def safe_extract_zip(zip_ref: zipfile.ZipFile, target_dir: str) -> None:
    for member in zip_ref.infolist():
        _safe_archive_member_path(target_dir, member.filename)
    zip_ref.extractall(target_dir)


def safe_extract_tar(tar_ref: tarfile.TarFile, target_dir: str) -> None:
    for member in tar_ref.getmembers():
        _safe_archive_member_path(target_dir, member.name)
        if member.issym() or member.islnk():
            raise ValueError(f"Archive links are not allowed: {member.name}")
    tar_ref.extractall(target_dir)


def require_admin(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not getattr(current_user, 'is_admin', False):
            return jsonify({'error': 'Administrator privileges required'}), 403
        return view(*args, **kwargs)
    return wrapped


def require_feedback_dashboard_viewer(view):
    """Permit the dedicated test observer account to inspect feedback, not mutate it."""
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        configured = {
            username.strip()
            for username in os.environ.get('LABELSYSTEM_FEEDBACK_DASHBOARD_VIEWERS', 'ziantestpov').split(',')
            if username.strip()
        }
        if getattr(current_user, 'is_admin', False) or current_user.username in configured:
            return view(*args, **kwargs)
        return jsonify({'error': 'Feedback dashboard access required'}), 403
    return wrapped


def require_feedback_operator(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        configured = {
            username.strip()
            for username in os.environ.get('LABELSYSTEM_FEEDBACK_OPERATORS', 'ziantestpov').split(',')
            if username.strip()
        }
        if getattr(current_user, 'is_admin', False) or current_user.username in configured:
            return view(*args, **kwargs)
        return jsonify({'error': 'Feedback operator privileges required'}), 403
    return wrapped




def _assignment_report100_list_path() -> Path | None:
    configured = current_app.config.get('CMR_ALL_REPORT100_CASE_LIST')
    if not configured:
        return None
    return Path(str(configured)).expanduser()


def _assignment_candidate_rows():
    candidate_paths = [
        Path(current_app.root_path).parent / 'tmp' / 'km_correctroot_2025_candidates_dedup.csv',
        Path(current_app.root_path).parent / 'tmp' / 'km_replacement_strict_2025_available.csv',
        Path(current_app.root_path).parent / 'tmp' / 'km_classified_2025_200_candidates.csv',
    ]
    rows = []
    seen = set()
    for path in candidate_paths:
        if not path.exists():
            continue
        try:
            frame = pd.read_csv(path, dtype=str).fillna('')
        except Exception as exc:
            current_app.logger.warning(f'Failed to read assignment candidate CSV {path}: {exc}')
            continue
        for _, row in frame.iterrows():
            case_id = str(row.get('relative_path') or '').strip() or str(row.get('case_name') or '').strip()
            if not case_id or case_id in seen:
                continue
            seen.add(case_id)
            item = {key: str(row.get(key) or '').strip() for key in row.index}
            item['case_id'] = case_id
            rows.append(item)
    return rows


def _assignment_anon_label(index: int) -> str:
    return f"病例{index + 1:03d}"


def _assignment_public_case_code(case_id: str, register_id: str = "", case_date: str = "") -> str:
    if register_id and case_date:
        return f"{register_id}_{case_date}"
    match = re.search(r"(\d{10})[^\d]+(20\d{6})", case_id or "")
    if match:
        return f"{match.group(1)}_{match.group(2)}"
    match = re.search(r"(\d{10}).*?(20\d{6})", case_id or "")
    if match:
        return f"{match.group(1)}_{match.group(2)}"
    return re.sub(r"[A-Za-z][A-Za-z\s_-]*$", "", case_id or "").strip("_- /") or "-"


def _assignment_case_detail_lookup(case_ids):
    detail_paths = [
        Path(current_app.root_path).parent / 'tmp' / 'km_replacement_strict_2025_available.csv',
        Path(current_app.root_path).parent / 'tmp' / 'km_replacement_strict2025_latest_correctroot.csv',
        Path(current_app.root_path).parent / 'tmp' / 'km_correctroot_2025_candidates_dedup.csv',
    ]
    wanted = set(case_ids or [])
    details = {}
    for path in detail_paths:
        if not path.exists():
            continue
        try:
            frame = pd.read_csv(path, dtype=str).fillna('')
        except Exception as exc:
            current_app.logger.warning(f'Failed to read assignment detail CSV {path}: {exc}')
            continue
        if 'case_name' not in frame.columns:
            continue
        for _, row in frame.iterrows():
            case_name = str(row.get('case_name') or '').strip()
            original_path = str(row.get('original_path') or '').strip()
            candidates = [case_name]
            if '/CMR_ALL/' in original_path:
                candidates.append(original_path.split('/CMR_ALL/', 1)[1].strip('/'))
            matched_case_id = next((candidate for candidate in candidates if candidate in wanted), '')
            if not matched_case_id or matched_case_id in details:
                continue
            register_id = str(row.get('register_id') or '').strip()
            case_date = str(row.get('case_date') or '').strip()
            details[matched_case_id] = {
                'case_id': matched_case_id,
                'case_name': case_name,
                'public_case_code': _assignment_public_case_code(matched_case_id, register_id, case_date),
                'register_id': register_id,
                'case_date': case_date,
                'year': str(row.get('year') or '').strip(),
                'diseases': str(row.get('diseases') or row.get('disease_files') or '').strip(),
                'sex': str(row.get('sex') or '').strip(),
                'age': str(row.get('age') or '').strip(),
                'subdirs': str(row.get('subdirs') or '').strip(),
                'match_quality': str(row.get('match_quality') or '').strip(),
                'excel_refs': str(row.get('excel_refs') or '').strip(),
            }
    return details


def _assignment_catalog_case_details(dataset):
    rows = (
        CviCaseCatalog.query
        .filter_by(source='functional', dataset=dataset, has_dicom=True)
        .order_by(CviCaseCatalog.id.asc())
        .all()
    )
    width = max(3, len(str(max(1, len(rows)))))
    details = []
    try:
        from cvi_workstation import _case_display_identity, _public_case_code
    except ImportError:
        _case_display_identity = None
        _public_case_code = None

    for index, row in enumerate(rows):
        identity = (
            _case_display_identity(row.dataset, row.case_id)
            if _case_display_identity is not None
            else {'primary_id_label': '', 'primary_id': ''}
        )
        public_case_code = (
            _public_case_code(row.case_id)
            if _public_case_code is not None
            else _assignment_public_case_code(row.case_id)
        )
        details.append({
            'case_id': row.case_id,
            'case_name': row.case_id,
            'anon_label': f"病例{index + 1:0{width}d}",
            'library_order': index + 1,
            'public_case_code': public_case_code,
            'primary_id_label': str(identity.get('primary_id_label') or ''),
            'primary_id': str(identity.get('primary_id') or ''),
            'register_id': str(identity.get('primary_id') or ''),
            'has_dicom': bool(row.has_dicom),
            'is_imported': row.cvi_study_id is not None,
            'sequence_summary': row.sequence_summary or [],
        })
    return details


def _configured_dataset_access_definitions():
    definitions = []
    seen = set()
    for item in current_app.config.get('CVI_LIBRARY_MULTICENTER_ROOTS', []) or []:
        if not isinstance(item, dict):
            continue
        dataset = str(item.get('dataset') or '').strip()
        if not dataset or dataset in seen:
            continue
        seen.add(dataset)
        is_private = _config_flag_enabled(item.get('private_by_assignment'))
        system_shared = dataset == 'CMR_ALL'
        definitions.append({
            'namespace': 'functional',
            'dataset': dataset,
            'label': str(item.get('label') or dataset).strip(),
            'private_by_assignment': is_private,
            'system_shared': system_shared,
            'grant_supported': not system_shared,
            'object_access_mode': 'assignment_required' if is_private else 'authenticated_shared',
            'grant_effect': (
                'already_shared'
                if system_shared
                else 'library_import_and_objects'
                if is_private
                else 'library_and_import'
            ),
        })
    return definitions


def _configured_dataset_access_definition(namespace, dataset):
    namespace = str(namespace or '').strip()
    dataset = str(dataset or '').strip()
    if namespace != 'functional' or not dataset:
        return None
    return next(
        (
            item
            for item in _configured_dataset_access_definitions()
            if item['dataset'] == dataset
        ),
        None,
    )


def _normalize_dataset_access_user_ids(raw_user_ids):
    if not isinstance(raw_user_ids, list):
        raise ValueError('user_ids must be a list')
    normalized = []
    seen = set()
    for raw_user_id in raw_user_ids:
        if isinstance(raw_user_id, bool):
            raise ValueError('Invalid user_id')
        if isinstance(raw_user_id, int):
            user_id = raw_user_id
        elif isinstance(raw_user_id, str) and re.fullmatch(r'[1-9]\d*', raw_user_id.strip()):
            user_id = int(raw_user_id)
        else:
            raise ValueError('Invalid user_id')
        if user_id <= 0:
            raise ValueError('Invalid user_id')
        if user_id not in seen:
            normalized.append(user_id)
            seen.add(user_id)
    return normalized


def _replace_dataset_access_grants(namespace, dataset, raw_user_ids, created_by_id):
    definition = _configured_dataset_access_definition(namespace, dataset)
    if definition is None:
        raise LookupError('数据集不存在或不支持整库权限')
    if not definition.get('grant_supported', True):
        raise ValueError('该数据集已经对所有已审核账号开放，不需要重复分配整库权限')

    user_ids = _normalize_dataset_access_user_ids(raw_user_ids)
    users = (
        User.query
        .filter(User.id.in_(user_ids))
        .all()
        if user_ids
        else []
    )
    users_by_id = {int(user.id): user for user in users}
    invalid_user_ids = [
        user_id
        for user_id in user_ids
        if user_id not in users_by_id
        or not users_by_id[user_id].is_approved
        or users_by_id[user_id].is_admin
    ]
    if invalid_user_ids:
        raise ValueError('整库权限只能分配给已审核的非管理员账号')

    existing = DatasetAccessGrant.query.filter_by(
        namespace=definition['namespace'],
        dataset=definition['dataset'],
    ).all()
    existing_by_user_id = {int(item.user_id): item for item in existing}
    selected = set(user_ids)
    now = datetime.utcnow()

    for user_id, grant in existing_by_user_id.items():
        should_be_active = user_id in selected
        if bool(grant.active) != should_be_active:
            grant.active = should_be_active
            grant.updated_at = now
            grant.created_by_id = created_by_id

    for user_id in user_ids:
        if user_id in existing_by_user_id:
            continue
        db.session.add(DatasetAccessGrant(
            namespace=definition['namespace'],
            dataset=definition['dataset'],
            user_id=user_id,
            created_by_id=created_by_id,
            created_at=now,
            updated_at=now,
            active=True,
        ))
    return user_ids


def _active_dataset_access_user_ids(namespace, dataset):
    return {
        int(item.user_id)
        for item in DatasetAccessGrant.query.filter_by(
            namespace=str(namespace or '').strip(),
            dataset=str(dataset or '').strip(),
            active=True,
        ).all()
    }


def _dataset_access_revision(namespace, dataset):
    namespace = str(namespace or '').strip()
    dataset = str(dataset or '').strip()
    user_ids = sorted(_active_dataset_access_user_ids(namespace, dataset))
    latest_audit_id = (
        db.session.query(db.func.max(DatasetAccessAudit.id))
        .filter_by(namespace=namespace, dataset=dataset)
        .scalar()
        or 0
    )
    revision_source = json.dumps(
        {
            'namespace': namespace,
            'dataset': dataset,
            'user_ids': user_ids,
            'latest_audit_id': int(latest_audit_id),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    )
    return std_hashlib.sha256(revision_source.encode('utf-8')).hexdigest()[:24]


def _append_dataset_access_audit(
    namespace,
    dataset,
    *,
    added_user_ids,
    removed_user_ids,
    actor,
    request_ip='',
):
    added = sorted({int(user_id) for user_id in added_user_ids})
    removed = sorted({int(user_id) for user_id in removed_user_ids})
    changed_user_ids = sorted(set(added) | set(removed))
    if not changed_user_ids:
        return []

    definition = _configured_dataset_access_definition(namespace, dataset)
    if definition is None:
        raise LookupError('数据集不存在或不支持整库权限')
    users = User.query.filter(User.id.in_(changed_user_ids)).all()
    users_by_id = {int(user.id): user for user in users}
    batch_id = str(uuid.uuid4())
    now = datetime.utcnow()
    actor_id = int(getattr(actor, 'id', 0) or 0)
    if actor_id <= 0 or not getattr(actor, 'is_admin', False):
        raise ValueError('Administrator identity is required for dataset access audit')
    actor_username = str(getattr(actor, 'username', '') or f'admin-{actor_id}')[:64]
    ip_snapshot = str(request_ip or '')[:64]
    dataset_label = str(definition.get('label') or definition['dataset'])[:200]
    events = []

    for action, user_ids in (('grant', added), ('revoke', removed)):
        for user_id in user_ids:
            user = users_by_id.get(user_id)
            if user is not None:
                target_username = str(user.username or f'user-{user_id}')[:64]
            else:
                previous = (
                    DatasetAccessAudit.query
                    .filter_by(
                        namespace=definition['namespace'],
                        dataset=definition['dataset'],
                        target_user_id=user_id,
                    )
                    .order_by(DatasetAccessAudit.id.desc())
                    .first()
                )
                target_username = (
                    str(previous.target_username)[:64]
                    if previous is not None and previous.target_username
                    else f'已删除账号#{user_id}'
                )
            event = DatasetAccessAudit(
                batch_id=batch_id,
                namespace=definition['namespace'],
                dataset=definition['dataset'],
                dataset_label=dataset_label,
                target_user_id=user_id,
                target_username=target_username,
                action=action,
                actor_user_id=actor_id,
                actor_username=actor_username,
                request_ip=ip_snapshot,
                release_version=LABELSYSTEM_RELEASE_VERSION[:64],
                created_at=now,
            )
            db.session.add(event)
            events.append(event)
    return events


def _dataset_access_overview():
    definitions = _configured_dataset_access_definitions()
    dataset_names = [item['dataset'] for item in definitions]
    configured_keys = {(item['namespace'], item['dataset']) for item in definitions}
    users = (
        User.query
        .filter_by(is_approved=True, is_admin=False)
        .order_by(User.username.asc(), User.id.asc())
        .all()
    )

    catalog_case_ids = {dataset: set() for dataset in dataset_names}
    catalog_stats = {
        dataset: {'catalog_count': 0, 'dicom_case_count': 0, 'imported_count': 0}
        for dataset in dataset_names
    }
    if dataset_names:
        catalog_rows = (
            db.session.query(
                CviCaseCatalog.dataset,
                CviCaseCatalog.case_id,
                CviCaseCatalog.has_dicom,
                CviCaseCatalog.cvi_study_id,
            )
            .filter(
                CviCaseCatalog.source == 'functional',
                CviCaseCatalog.dataset.in_(dataset_names),
            )
            .all()
        )
        for row in catalog_rows:
            dataset = str(row.dataset)
            catalog_case_ids[dataset].add(str(row.case_id))
            catalog_stats[dataset]['catalog_count'] += 1
            catalog_stats[dataset]['dicom_case_count'] += int(bool(row.has_dicom))
            catalog_stats[dataset]['imported_count'] += int(row.cvi_study_id is not None)

    assignment_case_ids = {}
    if dataset_names:
        assignment_rows = (
            db.session.query(
                CaseAssignment.dataset,
                CaseAssignment.user_id,
                CaseAssignment.case_id,
            )
            .filter(
                CaseAssignment.namespace == 'functional',
                CaseAssignment.dataset.in_(dataset_names),
                CaseAssignment.active.is_(True),
            )
            .all()
        )
        for row in assignment_rows:
            assignment_case_ids.setdefault(
                (str(row.dataset), int(row.user_id)),
                set(),
            ).add(str(row.case_id))

    active_grants = DatasetAccessGrant.query.filter_by(active=True).all()
    active_grant_keys = {
        (str(item.namespace), str(item.dataset), int(item.user_id))
        for item in active_grants
    }
    orphan_grants = sum(
        1
        for item in active_grants
        if (str(item.namespace), str(item.dataset)) not in configured_keys
    )

    datasets = []
    for definition in definitions:
        dataset = definition['dataset']
        current_case_ids = catalog_case_ids[dataset]
        catalog_count = catalog_stats[dataset]['catalog_count']
        user_access = []
        for user in users:
            assigned_ids = assignment_case_ids.get((dataset, int(user.id)), set())
            current_assignments = assigned_ids & current_case_ids
            stale_assignments = assigned_ids - current_case_ids
            has_dataset_grant = (
                definition['namespace'],
                dataset,
                int(user.id),
            ) in active_grant_keys
            if definition.get('system_shared'):
                access_scope = 'system_shared'
            elif has_dataset_grant:
                access_scope = 'dataset'
            elif catalog_count > 0 and len(current_assignments) == catalog_count:
                access_scope = 'all_current'
            elif current_assignments:
                access_scope = 'partial'
            else:
                access_scope = 'none'
            user_access.append({
                'user_id': int(user.id),
                'username': user.username,
                'has_dataset_grant': has_dataset_grant,
                'case_assignment_count': len(current_assignments),
                'stale_case_assignment_count': len(stale_assignments),
                'effective_case_count': (
                    catalog_count
                    if has_dataset_grant or definition.get('system_shared')
                    else len(current_assignments)
                ),
                'access_scope': access_scope,
                'future_cases_included': bool(has_dataset_grant or definition.get('system_shared')),
            })
        datasets.append({
            **definition,
            **catalog_stats[dataset],
            'revision': _dataset_access_revision(definition['namespace'], dataset),
            'dataset_grant_count': sum(1 for item in user_access if item['has_dataset_grant']),
            'user_access': user_access,
        })

    recent_audits = (
        DatasetAccessAudit.query
        .order_by(DatasetAccessAudit.created_at.desc(), DatasetAccessAudit.id.desc())
        .limit(100)
        .all()
    )
    return {
        'datasets': datasets,
        'users': [user.to_admin_dict() for user in users],
        'admin_access_inherited': User.query.filter_by(is_approved=True, is_admin=True).count(),
        'orphan_active_grants': orphan_grants,
        'release_version': LABELSYSTEM_RELEASE_VERSION,
        'audit_total': DatasetAccessAudit.query.count(),
        'recent_audit': [item.to_dict() for item in recent_audits],
    }


def _assignment_dataset_library_presets():
    presets = []
    for item in current_app.config.get('CVI_LIBRARY_MULTICENTER_ROOTS', []) or []:
        dataset = str(item.get('dataset') or '').strip()
        if not dataset:
            continue
        case_count = (
            CviCaseCatalog.query
            .filter_by(source='functional', dataset=dataset, has_dicom=True)
            .count()
        )
        label = str(item.get('label') or dataset).strip()
        presets.append({
            'id': f'dataset:{dataset}',
            'label': f'{label} · 全部已登记病例',
            'namespace': 'functional',
            'dataset': dataset,
            'case_ids': [],
            'case_details': [],
            'case_count': case_count,
            'kind': 'dataset',
            'lazy': True,
            'source': 'cvi_case_catalog',
            'description': f'{label}工作站病例目录；库内序号按首次登记顺序生成，仅在当前数据集内有效。',
            'identifier_labels': ['库内序号', '登记号/检查号', '匿名病例号', '病例 ID'],
        })
    return presets


def _assignment_case_library_presets():
    presets = _assignment_dataset_library_presets()
    report100_path = current_app.config.get('CMR_ALL_REPORT100_CASE_LIST')
    report100_cases = []
    if report100_path:
        path = Path(str(report100_path)).expanduser()
        if path.exists():
            report100_cases = [
                line.strip()
                for line in path.read_text(encoding='utf-8', errors='ignore').splitlines()
                if line.strip()
            ]
    if report100_cases:
        detail_lookup = _assignment_case_detail_lookup(report100_cases)
        case_details = []
        for index, case_id in enumerate(report100_cases):
            detail = dict(detail_lookup.get(case_id, {'case_id': case_id, 'case_name': case_id}))
            detail['anon_label'] = _assignment_anon_label(index)
            detail['public_case_code'] = detail.get('public_case_code') or _assignment_public_case_code(case_id, detail.get('register_id', ''), detail.get('case_date', ''))
            case_details.append(detail)
        presets.append({
            'id': 'km_report100_2025',
            'label': '专项子集：昆医附二院报告评分100例（2025）',
            'namespace': 'functional',
            'dataset': 'CMR_ALL',
            'case_ids': report100_cases,
            'case_details': case_details,
            'case_count': len(report100_cases),
            'kind': 'subset',
            'lazy': False,
            'source': 'configured_report_subset',
            'description': '当前替换后的昆医附二院 2025 年报告评分病例库，可直接分配给标记者。',
            'identifier_labels': ['子集序号', '登记号/检查号', '病例 ID'],
        })
    return presets


def _assignment_preset_by_id(preset_id):
    return next(
        (item for item in _assignment_case_library_presets() if item['id'] == preset_id),
        None,
    )


def _assignment_details_for_preset(preset):
    if not preset:
        return []
    if preset.get('kind') == 'dataset':
        return _assignment_catalog_case_details(preset['dataset'])
    return [dict(item) for item in (preset.get('case_details') or [])]


def _assignment_case_aliases(detail):
    aliases = {
        str(detail.get('case_id') or '').strip(),
        Path(str(detail.get('case_id') or '')).name.strip(),
        str(detail.get('anon_label') or '').strip(),
        str(detail.get('public_case_code') or '').strip(),
        str(detail.get('primary_id') or detail.get('register_id') or '').strip(),
    }
    return {alias.casefold() for alias in aliases if alias and alias != '-'}


def _resolve_assignment_identifier_selection(raw_selection, case_details):
    tokens = [
        item.strip()
        for item in re.split(r'[\n,，;；、]+', str(raw_selection or ''))
        if item.strip()
    ]
    if not tokens:
        raise ValueError('Missing case selection')

    alias_map = {}
    for detail in case_details:
        for alias in _assignment_case_aliases(detail):
            alias_map.setdefault(alias, []).append(detail['case_id'])

    selected = []
    selected_set = set()
    unmatched_count = 0
    ambiguous_count = 0
    for token in tokens:
        matches = alias_map.get(token.casefold(), [])
        if not matches:
            unmatched_count += 1
            continue
        if len(matches) > 1:
            ambiguous_count += 1
        for case_id in matches:
            if case_id not in selected_set:
                selected.append(case_id)
                selected_set.add(case_id)

    if not selected:
        raise ValueError('没有匹配到病例，请检查登记号、检查号或病例 ID')
    warnings = []
    if unmatched_count:
        warnings.append(f'{unmatched_count} 个输入标识未匹配')
    if ambiguous_count:
        warnings.append(f'{ambiguous_count} 个输入标识匹配到多次检查，已全部列入预览')
    return selected, warnings


def _parse_assignment_ordered_case_selection(raw_selection, ordered_case_ids):
    ordered_cases = [str(item).strip() for item in (ordered_case_ids or []) if str(item).strip()]
    if not ordered_cases:
        raise ValueError('Missing ordered case list')

    raw_text = str(raw_selection or '').strip()
    if not raw_text:
        raise ValueError('Missing case selection')

    normalized_text = re.sub(r'\s*(?:-|~|～|至|到)\s*', '-', raw_text)
    tokens = [
        item.strip()
        for item in re.split(r'[\n,，;；、]+', normalized_text)
        if item.strip()
    ]
    if not tokens:
        raise ValueError('Missing case selection')

    selected = []
    seen = set()
    ordered_set = set(ordered_cases)

    def add_case(case_id):
        if case_id not in seen:
            selected.append(case_id)
            seen.add(case_id)

    for token in tokens:
        range_match = re.fullmatch(r'(\d+)-(\d+)', token)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            if start < 1 or end < 1 or start > end:
                raise ValueError(f'Invalid case range: {token}')
            if end > len(ordered_cases):
                raise ValueError(f'Case range out of bounds: {token}; total {len(ordered_cases)}')
            for index in range(start - 1, end):
                add_case(ordered_cases[index])
            continue

        if re.fullmatch(r'\d+', token):
            index = int(token)
            if index < 1 or index > len(ordered_cases):
                raise ValueError(f'Case index out of bounds: {token}; total {len(ordered_cases)}')
            add_case(ordered_cases[index - 1])
            continue

        if token in ordered_set:
            add_case(token)
            continue

        raise ValueError(f'Invalid case selection item: {token}')

    if not selected:
        raise ValueError('No cases selected')
    return selected


def _resolve_assignment_preset_selection(preset, raw_selection, selection_mode):
    case_details = _assignment_details_for_preset(preset)
    ordered_case_ids = [item['case_id'] for item in case_details]
    if selection_mode == 'order':
        normalized = str(raw_selection or '').strip()
        if normalized.casefold() in {'all', '全部'}:
            selected = ordered_case_ids
        else:
            selected = _parse_assignment_ordered_case_selection(normalized, ordered_case_ids)
        warnings = []
    elif selection_mode == 'identifier':
        selected, warnings = _resolve_assignment_identifier_selection(raw_selection, case_details)
    else:
        raise ValueError('Invalid selection mode')
    detail_map = {item['case_id']: item for item in case_details}
    return selected, [detail_map[item] for item in selected if item in detail_map], warnings


def _client_ip() -> str:
    forwarded_for = request.headers.get('X-Forwarded-For', '')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.remote_addr or 'unknown'


def _check_auth_rate_limit(action: str, limit: int = 20, window_seconds: int = 300):
    now = time.time()
    key = (action, _client_ip())
    attempts = [ts for ts in auth_attempts.get(key, []) if now - ts < window_seconds]
    if len(attempts) >= limit:
        auth_attempts[key] = attempts
        return False
    attempts.append(now)
    auth_attempts[key] = attempts
    return True


def _media_token_signature(user_id: int, expires_at: int) -> str:
    payload = f'{user_id}:{expires_at}'.encode('utf-8')
    secret = current_app.config['SECRET_KEY'].encode('utf-8')
    return hmac.new(secret, payload, std_hashlib.sha256).hexdigest()


def _build_media_token(user_id: int) -> str:
    expires_at = int(time.time()) + MEDIA_TOKEN_TTL_SECONDS
    signature = _media_token_signature(user_id, expires_at)
    return f'{user_id}:{expires_at}:{signature}'


def _valid_media_token() -> bool:
    if not current_user.is_authenticated:
        return False
    token = request.cookies.get(MEDIA_TOKEN_COOKIE, '')
    try:
        raw_user_id, raw_expires, signature = token.split(':', 2)
        user_id = int(raw_user_id)
        expires_at = int(raw_expires)
    except (TypeError, ValueError):
        return False
    if user_id != current_user.id or expires_at < int(time.time()):
        return False
    expected = _media_token_signature(user_id, expires_at)
    return hmac.compare_digest(signature, expected)


def _json_with_media_cookie(payload, status: int = 200):
    response = make_response(jsonify(payload), status)
    if current_user.is_authenticated:
        response.set_cookie(
            MEDIA_TOKEN_COOKIE,
            _build_media_token(current_user.id),
            max_age=MEDIA_TOKEN_TTL_SECONDS,
            httponly=True,
            secure=current_app.config.get('SESSION_COOKIE_SECURE', False),
            samesite='Lax',
            path='/',
        )
    return response


def _allowed_media_origins() -> set[str]:
    configured = {
        origin.strip().rstrip('/')
        for origin in os.environ.get('LABELSYSTEM_CORS_ORIGINS', '').split(',')
        if origin.strip()
    }
    return DEFAULT_ALLOWED_ORIGINS | configured


def _origin_from_url(value: str) -> str:
    parsed = urlparse(value or '')
    if not parsed.scheme or not parsed.netloc:
        return ''
    return f"{parsed.scheme}://{parsed.netloc}"


def _is_same_origin_media_request() -> bool:
    allowed = _allowed_media_origins()
    referer_origin = _origin_from_url(request.headers.get('Referer', ''))
    origin = request.headers.get('Origin', '').rstrip('/')
    if referer_origin in allowed or origin in allowed:
        return True

    # Browser same-origin fetches often include Sec-Fetch-* even when Origin is absent.
    fetch_site = request.headers.get('Sec-Fetch-Site', '')
    fetch_dest = request.headers.get('Sec-Fetch-Dest', '')
    if fetch_site in {'same-origin', 'same-site'} and fetch_dest in {'image', 'empty'}:
        return True

    # Keep local development and Vite proxy usable, while public direct requests still need browser headers.
    if request.remote_addr in {'127.0.0.1', '::1'}:
        return True

    return False


def _check_media_rate_limit(kind: str, limit: int = 900, window_seconds: int = 60) -> bool:
    now = time.time()
    user_part = getattr(current_user, 'id', None) if current_user.is_authenticated else _client_ip()
    key = (kind, user_part)
    attempts = [ts for ts in media_attempts.get(key, []) if now - ts < window_seconds]
    if len(attempts) >= limit:
        media_attempts[key] = attempts
        return False
    attempts.append(now)
    media_attempts[key] = attempts
    return True


def _log_media_access(kind: str, status: str, *, namespace: str = '', dataset: str = '', case_id: str = '', path: str = '') -> None:
    try:
        username = current_user.username if current_user.is_authenticated else None
        user_id = current_user.id if current_user.is_authenticated else None
        db.session.add(MediaAccessLog(
            user_id=user_id,
            username=username,
            kind=kind,
            namespace=namespace or '',
            dataset=dataset or '',
            case_id=case_id or '',
            path=(path or '')[:1000],
            status=status,
            ip_address=_client_ip(),
            user_agent=(request.headers.get('User-Agent') or '')[:500],
        ))
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning("Failed to write media access log: %s", exc)


def _case_has_assignments(namespace: str, dataset: str, case_id: str) -> bool:
    raw_case_id = str(case_id or '').strip()
    case_name = Path(raw_case_id).name
    query = CaseAssignment.query.filter_by(
        namespace=namespace,
        dataset=dataset or '',
        active=True,
    )
    if case_name:
        query = query.filter(db.or_(
            CaseAssignment.case_id == raw_case_id,
            CaseAssignment.case_id == case_name,
            CaseAssignment.case_id.like(f'%/{case_name}'),
        ))
    return query.first() is not None


def _config_flag_enabled(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or '').strip().lower() in {'1', 'true', 'yes', 'on'}


def _base_dicom_dataset_name(dataset: str | None) -> str:
    raw = _canonical_dataset(dataset)
    if raw.startswith('SOLO_CMR_ALL_'):
        return 'CMR_ALL'
    if raw.startswith('SOLO_CMR_Chendu_'):
        return 'CMR_Chendu'
    if raw.startswith('SOLO_CMR_SCS_'):
        return 'CMR_SCS'
    if raw.startswith('SOLO_CMR_YA_'):
        return 'CMR_YA'
    return raw


def _dataset_is_private_by_assignment(namespace: str, dataset: str) -> bool:
    if str(namespace or '').strip().lower() != 'functional':
        return False
    target = _base_dicom_dataset_name(dataset)
    if not target:
        return False
    for item in current_app.config.get('CVI_LIBRARY_MULTICENTER_ROOTS', []):
        if not isinstance(item, dict):
            continue
        configured_dataset = _base_dicom_dataset_name(item.get('dataset'))
        if configured_dataset == target and _config_flag_enabled(item.get('private_by_assignment')):
            return True
    return False


def _user_has_dataset_access_grant(namespace: str, dataset: str, user_id: int | None = None) -> bool:
    definition = _configured_dataset_access_definition(namespace, dataset)
    if definition is None or not definition.get('grant_supported', True):
        return False
    target_user_id = user_id if user_id is not None else getattr(current_user, 'id', None)
    if not target_user_id:
        return False
    return DatasetAccessGrant.query.filter_by(
        namespace=str(namespace or '').strip(),
        dataset=str(dataset or '').strip(),
        user_id=int(target_user_id),
        active=True,
    ).first() is not None


def _normalized_case_id(case_id: str) -> str:
    return Path(str(case_id or '')).name


def _configured_report_set_case_names(base_dataset: str = 'CMR_ALL') -> set[str]:
    if base_dataset != 'CMR_ALL':
        return set()
    configured_case_list = current_app.config.get('CMR_ALL_REPORT100_CASE_LIST')
    if not configured_case_list:
        return set()
    case_list_path = Path(str(configured_case_list)).expanduser()
    if not case_list_path.exists():
        return set()
    return {
        _normalized_case_id(line.strip())
        for line in case_list_path.read_text(encoding='utf-8').splitlines()
        if line.strip()
    }


def _user_can_access_case(namespace: str, dataset: str, case_id: str) -> bool:
    if not current_user.is_authenticated:
        return False
    if getattr(current_user, 'is_admin', False):
        return True
    dataset = dataset or ''
    if _user_has_dataset_access_grant(namespace, dataset):
        return True
    raw_case_id = str(case_id or '').strip()
    if _dataset_is_private_by_assignment(namespace, dataset):
        if not raw_case_id:
            return False
        return CaseAssignment.query.filter_by(
            namespace=namespace,
            dataset=dataset,
            case_id=raw_case_id,
            user_id=current_user.id,
            active=True,
        ).first() is not None
    case_name = _normalized_case_id(case_id)
    base_dataset = dataset.replace('new_', '', 1) if dataset.startswith('new_') else dataset
    if namespace == 'functional' and base_dataset == 'CMR_ALL' and case_name in _configured_report_set_case_names(base_dataset):
        return True
    if not _case_has_assignments(namespace, dataset, case_id):
        return True
    return CaseAssignment.query.filter_by(
        namespace=namespace,
        dataset=dataset,
        user_id=current_user.id,
        active=True,
    ).filter(db.or_(
        CaseAssignment.case_id == raw_case_id,
        CaseAssignment.case_id == case_name,
        CaseAssignment.case_id.like(f'%/{case_name}'),
    )).first() is not None


def _guard_case_assignment(namespace: str, dataset: str, case_id: str):
    if not _user_can_access_case(namespace, dataset, case_id):
        return jsonify({'error': 'This case is not assigned to your account'}), 403
    return None


def _guard_media_access(kind: str = 'image', *, namespace: str = '', dataset: str = '', case_id: str = '', path: str = ''):
    if not _is_same_origin_media_request():
        _log_media_access(kind, 'blocked_origin', namespace=namespace, dataset=dataset, case_id=case_id, path=path)
        return jsonify({'error': 'Image access must come from the workstation viewer'}), 403
    if not _check_media_rate_limit(kind):
        _log_media_access(kind, 'rate_limited', namespace=namespace, dataset=dataset, case_id=case_id, path=path)
        return jsonify({'error': 'Too many image requests. Please slow down.'}), 429
    assignment_guard = _guard_case_assignment(namespace, dataset, case_id) if case_id else None
    if assignment_guard:
        _log_media_access(kind, 'blocked_assignment', namespace=namespace, dataset=dataset, case_id=case_id, path=path)
        return assignment_guard
    if not _valid_media_token():
        # Some workstation sessions can keep the Flask login cookie while losing the auxiliary
        # media token. The request has already passed login, origin, assignment, and rate checks,
        # so let the image through and refresh the token on the media response.
        _log_media_access(kind, 'token_refreshed', namespace=namespace, dataset=dataset, case_id=case_id, path=path)
    return None


def _secure_media_response(
    response: Response,
    *,
    inline_filename: str | None = None,
    viewer_user_id: int | None = None,
) -> Response:
    response.headers['Cache-Control'] = 'no-store, private, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Robots-Tag'] = 'noindex, noarchive, nosnippet'
    response.headers['Accept-Ranges'] = 'none'
    if inline_filename:
        response.headers['Content-Disposition'] = f'inline; filename="{secure_filename(inline_filename) or "image"}"'
    if viewer_user_id is None and current_user.is_authenticated:
        viewer_user_id = int(current_user.id)
    if viewer_user_id is not None:
        response.set_cookie(
            MEDIA_TOKEN_COOKIE,
            _build_media_token(viewer_user_id),
            max_age=MEDIA_TOKEN_TTL_SECONDS,
            httponly=True,
            secure=current_app.config.get('SESSION_COOKIE_SECURE', False),
            samesite='Lax',
            path='/',
        )
    return response


def _watermark_text(username: str | None = None) -> str:
    if username is None:
        username = current_user.username if current_user.is_authenticated else 'viewer'
    username = str(username or 'viewer')
    return f"{username} {datetime.utcnow().strftime('%Y-%m-%d %H:%MZ')}"


def _add_edge_watermark(img: Image.Image, text: str | None = None) -> Image.Image:
    if os.environ.get('LABELSYSTEM_IMAGE_WATERMARK', '1').lower() in {'0', 'false', 'no'}:
        return img

    base = img.convert('RGBA')
    width, height = base.size
    if width < 64 or height < 64:
        return img

    overlay = Image.new('RGBA', base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    text = text or _watermark_text()
    font_size = max(10, min(16, width // 28))
    try:
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', font_size)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    pad_x = max(5, width // 90)
    pad_y = max(3, height // 120)
    margin = max(4, min(width, height) // 70)

    # Put the watermark in a thin lower-right edge band so it avoids the central anatomy.
    x = max(margin, width - text_w - pad_x * 2 - margin)
    y = max(margin, height - text_h - pad_y * 2 - margin)
    rect = (x, y, min(width - margin, x + text_w + pad_x * 2), min(height - margin, y + text_h + pad_y * 2))
    draw.rounded_rectangle(rect, radius=3, fill=(0, 0, 0, 92), outline=(255, 255, 255, 45))
    draw.text((x + pad_x, y + pad_y - 1), text, font=font, fill=(255, 255, 255, 135))
    marked = Image.alpha_composite(base, overlay)
    return marked.convert(img.mode if img.mode in {'L', 'RGB'} else 'RGB')


def _watermarked_png_response(
    img: Image.Image,
    filename: str = 'viewer-image.png',
    *,
    watermark_text: str | None = None,
    viewer_user_id: int | None = None,
) -> Response:
    marked = _add_edge_watermark(img, watermark_text)
    img_io = io.BytesIO()
    marked.save(img_io, 'PNG')
    img_io.seek(0)
    return _secure_media_response(
        send_file(img_io, mimetype='image/png'),
        inline_filename=filename,
        viewer_user_id=viewer_user_id,
    )


def _watermarked_png_bytes(img: Image.Image) -> bytes:
    marked = _add_edge_watermark(img)
    img_io = io.BytesIO()
    marked.save(img_io, 'PNG')
    return img_io.getvalue()


def _cached_png_response(body: bytes, filename: str = 'viewer-image.png') -> Response:
    response = Response(body, mimetype='image/png')
    return _secure_media_response(response, inline_filename=filename)


def _watermarked_file_response(
    file_path: str,
    filename: str | None = None,
    *,
    watermark_text: str | None = None,
    viewer_user_id: int | None = None,
) -> Response:
    try:
        with Image.open(file_path) as img:
            return _watermarked_png_response(
                img.convert('RGB'),
                filename or os.path.basename(file_path) or 'viewer-image.png',
                watermark_text=watermark_text,
                viewer_user_id=viewer_user_id,
            )
    except Exception:
        return _secure_media_response(
            send_file(file_path),
            inline_filename=filename or os.path.basename(file_path),
            viewer_user_id=viewer_user_id,
        )


def _resolve_under(root: str, *parts: str) -> str:
    root_real = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root_real, *parts))
    if target != root_real and not target.startswith(root_real + os.sep):
        raise ValueError('Unsafe path')
    return target


def _functional_image_cache_key(file_path: str) -> str:
    user_id = getattr(current_user, 'id', 'anonymous') if current_user.is_authenticated else 'anonymous'
    username = getattr(current_user, 'username', 'viewer') if current_user.is_authenticated else 'viewer'
    watermark_enabled = os.environ.get('LABELSYSTEM_IMAGE_WATERMARK', '1').lower() not in {'0', 'false', 'no'}
    watermark_key = _watermark_text() if watermark_enabled else 'wm-disabled'
    try:
        mtime_ns = os.stat(file_path).st_mtime_ns
    except OSError:
        mtime_ns = 0
    return f'{user_id}|{username}|wm={int(watermark_enabled)}|{watermark_key}|{mtime_ns}|{file_path}'


def _functional_image_cache_get(cache_key: str) -> bytes | None:
    if FUNCTIONAL_IMAGE_CACHE_MAX_ITEMS <= 0:
        return None
    with functional_image_cache_lock:
        body = functional_image_cache.get(cache_key)
        if body is None:
            return None
        functional_image_cache.move_to_end(cache_key)
        return body


def _functional_image_cache_put(cache_key: str, body: bytes) -> None:
    if FUNCTIONAL_IMAGE_CACHE_MAX_ITEMS <= 0 or not body:
        return
    with functional_image_cache_lock:
        functional_image_cache[cache_key] = body
        functional_image_cache.move_to_end(cache_key)
        while len(functional_image_cache) > FUNCTIONAL_IMAGE_CACHE_MAX_ITEMS:
            functional_image_cache.popitem(last=False)


PHI_DICOM_TAGS = (
    'PatientName',
    'PatientID',
    'PatientBirthDate',
    'PatientBirthTime',
    'PatientSex',
    'OtherPatientIDs',
    'OtherPatientNames',
    'PatientAddress',
    'PatientTelephoneNumbers',
    'ReferringPhysicianName',
    'PerformingPhysicianName',
    'OperatorsName',
    'InstitutionName',
    'InstitutionAddress',
    'StationName',
    'AccessionNumber',
    'StudyID',
    'IssuerOfPatientID',
)


def _anonymized_dicom_bytes(file_path: str) -> io.BytesIO:
    ds = pydicom.dcmread(file_path)
    ds.remove_private_tags()
    for tag in PHI_DICOM_TAGS:
        if tag in ds:
            if tag in {'PatientName', 'PatientID'}:
                ds.data_element(tag).value = 'ANONYMIZED'
            else:
                del ds[tag]
    ds.PatientIdentityRemoved = 'YES'
    ds.DeidentificationMethod = 'LabelSystem viewer anonymized response'

    buffer = io.BytesIO()
    ds.save_as(buffer, write_like_original=False)
    buffer.seek(0)
    return buffer


def _iso_datetime(value):
    return value.isoformat() if value else None


def _case_key(record):
    dataset = getattr(record, 'dataset', None)
    case_id = getattr(record, 'case_id', None)
    if dataset is not None and case_id is not None:
        return f"{dataset}/{case_id}"
    sample_id = getattr(record, 'sample_id', None)
    sequence = getattr(record, 'sequence', None)
    if sample_id is not None and sequence is not None:
        return f"{sample_id}/{sequence}"
    return str(getattr(record, 'id', 'unknown'))


def _case_key_from_projection(row):
    values = row._mapping
    if 'dataset' in values and values['dataset'] is not None:
        return f"{values['dataset']}/{values['case_id']}"
    return f"{values.get('sample_id')}/{values.get('sequence')}"


def _annotation_modules():
    return [
        {'key': 'segmentation', 'label': '分割标注', 'model': SegmentationAnnotation, 'time_field': 'updated_at'},
        {'key': 'cardiac', 'label': '4CH 标注', 'model': CardiacAnnotation, 'time_field': 'updated_at'},
        {'key': 'functional', 'label': '功能评估', 'model': FunctionalAssessment, 'time_field': 'created_at'},
        {'key': 'structure', 'label': '结构评估', 'model': StructureAssessment, 'time_field': 'created_at'},
        {'key': 'lge', 'label': 'LGE 分析', 'model': LGEAnalysis, 'time_field': 'created_at'},
        {'key': 'image_quality', 'label': '影像质量', 'model': ImageAnalysis, 'time_field': 'created_at'},
        {'key': 'other_findings', 'label': '其他发现', 'model': OtherFindings, 'time_field': 'created_at'},
        {'key': 'report_eval', 'label': '报告评分', 'model': EvaluationResult, 'time_field': 'created_at'},
    ]


def _projected_annotation_records(module, rater_id=None, limit=None, include_user=False, order_desc=False):
    model = module['model']
    time_column = getattr(model, module['time_field'])
    columns = [model.rater_id.label('rater_id'), time_column.label('event_time')]
    if hasattr(model, 'dataset'):
        columns.extend([model.dataset.label('dataset'), model.case_id.label('case_id')])
    else:
        columns.extend([model.sample_id.label('sample_id'), model.sequence.label('sequence')])
    if include_user:
        columns.append(User.username.label('username'))

    query = db.session.query(*columns)
    if include_user:
        query = query.outerjoin(User, model.rater_id == User.id)
    if rater_id is not None:
        query = query.filter(model.rater_id == rater_id)
    if order_desc:
        query = query.order_by(time_column.desc())
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def _count_case_tree(root_path, mode='two_level'):
    if not root_path or not os.path.exists(root_path):
        return {'exists': False, 'datasets': 0, 'cases': 0}

    dataset_count = 0
    case_count = 0
    try:
        children = [
            item for item in os.scandir(root_path)
            if item.is_dir(follow_symlinks=False) and not item.name.startswith('.')
        ]
        if mode == 'flat':
            return {'exists': True, 'datasets': 1, 'cases': len(children)}

        dataset_count = len(children)
        for dataset in children:
            try:
                case_count += sum(
                    1 for item in os.scandir(dataset.path)
                    if item.is_dir(follow_symlinks=False) and not item.name.startswith('.')
                )
            except OSError:
                continue
    except OSError:
        return {'exists': True, 'datasets': dataset_count, 'cases': case_count}

    return {'exists': True, 'datasets': dataset_count, 'cases': case_count}


def _safe_disk_usage(path):
    probe = path
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    if not probe or not os.path.exists(probe):
        return None
    try:
        usage = shutil.disk_usage(probe)
        return {'total': usage.total, 'used': usage.used, 'free': usage.free}
    except OSError:
        return None


def _database_table_counts():
    counts = {}
    for table_name in [
        'user',
        'cvi_case_catalog',
        'segmentation_annotation',
        'cardiac_annotation',
        'functional_assessment',
        'structure_assessment',
        'lge_analysis',
        'image_analysis',
        'other_findings',
        'evaluation_result',
    ]:
        try:
            row = db.session.execute(db.text(f'SELECT COUNT(*) FROM {table_name}')).first()
            counts[table_name] = int(row[0]) if row else 0
        except Exception:
            counts[table_name] = None
    return counts


def _count_directories(path):
    if not path or not os.path.isdir(path):
        return 0
    try:
        return sum(
            1
            for item in os.scandir(path)
            if item.is_dir(follow_symlinks=False) and not item.name.startswith('.')
        )
    except OSError:
        return 0


def _resolve_dataset_directory(base_root, dataset_name, *, allow_flat_match=False):
    if not base_root:
        return {'path': '', 'exists': False, 'cases': 0}

    normalized_root = os.path.abspath(base_root)
    root_basename = os.path.basename(normalized_root.rstrip(os.sep))
    if allow_flat_match and root_basename == dataset_name and os.path.isdir(normalized_root):
        return {
            'path': normalized_root,
            'exists': True,
            'cases': _count_directories(normalized_root),
        }

    candidate = os.path.join(normalized_root, dataset_name)
    return {
        'path': candidate,
        'exists': os.path.isdir(candidate),
        'cases': _count_directories(candidate),
    }


def _excel_variable_count(excel_file):
    df = get_excel_data(excel_file)
    if df is None:
        return None
    return len(df.columns)


def _dataset_monitor_overview(data_root, functional_root, eval_root):
    rows = []
    for dataset_name, config in EXCEL_DATASET_CONFIGS.items():
        annotation_info = _resolve_dataset_directory(data_root, dataset_name, allow_flat_match=True)
        functional_info = _resolve_dataset_directory(functional_root, dataset_name)
        eval_info = _resolve_dataset_directory(eval_root, dataset_name)
        eval_new_info = _resolve_dataset_directory(eval_root, f'new_{dataset_name}')

        rows.append({
            'dataset': dataset_name,
            'config_keys': ['DATA_ROOT', 'FUNCTIONAL_DATA_ROOT', 'EVAL_ROOT'],
            'excel_file': config['excel_file'],
            'excel_path': _excel_file_path(config['excel_file']),
            'excel_columns': _excel_variable_count(config['excel_file']),
            'id_column': config['id_col'],
            'description_cols': config.get('description_cols', []),
            'conclusion_cols': config.get('conclusion_cols', []),
            'extra_cols': config.get('extra_cols', []),
            'annotation_path': annotation_info['path'],
            'annotation_exists': annotation_info['exists'],
            'annotation_cases': annotation_info['cases'],
            'functional_path': functional_info['path'],
            'functional_exists': functional_info['exists'],
            'functional_cases': functional_info['cases'],
            'eval_path': eval_info['path'],
            'eval_exists': eval_info['exists'],
            'eval_cases': eval_info['cases'],
            'eval_new_path': eval_new_info['path'],
            'eval_new_exists': eval_new_info['exists'],
            'eval_new_cases': eval_new_info['cases'],
        })
    return rows


def _system_snapshot():
    mem = {}
    try:
        with open('/proc/meminfo', 'r', encoding='utf-8') as f:
            for line in f:
                key, raw = line.split(':', 1)
                mem[key] = int(raw.strip().split()[0]) * 1024
    except Exception:
        mem = {}

    loadavg = None
    try:
        with open('/proc/loadavg', 'r', encoding='utf-8') as f:
            parts = f.read().split()
            loadavg = [float(parts[0]), float(parts[1]), float(parts[2])]
    except Exception:
        pass

    uptime_seconds = None
    try:
        with open('/proc/uptime', 'r', encoding='utf-8') as f:
            uptime_seconds = float(f.read().split()[0])
    except Exception:
        pass

    gpus = []
    try:
        result = subprocess.run(
            [
                'nvidia-smi',
                '--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu',
                '--format=csv,noheader,nounits',
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                parts = [part.strip() for part in line.split(',')]
                if len(parts) >= 6:
                    gpus.append({
                        'index': int(parts[0]),
                        'name': parts[1],
                        'utilization': float(parts[2]),
                        'memory_used_mb': float(parts[3]),
                        'memory_total_mb': float(parts[4]),
                        'temperature': float(parts[5]),
                    })
    except Exception:
        gpus = []

    mem_total = mem.get('MemTotal')
    mem_available = mem.get('MemAvailable')
    return {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'backend_pid': os.getpid(),
        'loadavg': loadavg,
        'uptime_seconds': uptime_seconds,
        'memory': {
            'total': mem_total,
            'available': mem_available,
            'used': mem_total - mem_available if mem_total and mem_available else None,
        },
        'gpus': gpus,
    }


def _annotation_overview():
    modules = []
    recent_activity = []
    for module in _annotation_modules():
        records = _projected_annotation_records(module)
        known_records = [record for record in records if record._mapping['rater_id'] is not None]
        unique_cases = {_case_key_from_projection(record) for record in records}
        modules.append({
            'key': module['key'],
            'label': module['label'],
            'records': len(records),
            'assigned_records': len(known_records),
            'unique_cases': len(unique_cases),
        })

        for record in _projected_annotation_records(module, include_user=True, order_desc=True, limit=12):
            values = record._mapping
            recent_activity.append({
                'module': module['label'],
                'case': _case_key_from_projection(record),
                'user': values.get('username'),
                'time': _iso_datetime(values.get('event_time')),
            })

    recent_activity.sort(key=lambda item: item['time'] or '', reverse=True)
    return {'modules': modules, 'recent_activity': recent_activity[:30]}


def _annotation_payload(record):
    try:
        return record.to_dict()
    except Exception:
        payload = {}
        for column in record.__table__.columns:
            value = getattr(record, column.name)
            if hasattr(value, 'isoformat'):
                value = value.isoformat()
            payload[column.name] = value
        return payload


def _annotation_result_summary(payload):
    if not isinstance(payload, dict):
        return ''
    source = payload.get('answers')
    if not isinstance(source, dict):
        source = payload.get('metrics_data') if isinstance(payload.get('metrics_data'), dict) else payload
    parts = []
    for key, value in source.items():
        if key in {'id', 'dataset', 'case_id', 'sample_id', 'sequence', 'rater', 'created_at', 'updated_at'}:
            continue
        if value in (None, '', [], {}):
            continue
        if isinstance(value, (list, dict)):
            text = f"{key}: {len(value)} 项"
        else:
            text = f"{key}: {value}"
        parts.append(text)
        if len(parts) >= 4:
            break
    return '；'.join(parts)


def _annotation_result_item(module, record):
    payload = _annotation_payload(record)
    time_value = getattr(record, module['time_field'], None)
    dataset = getattr(record, 'dataset', None)
    case_id = getattr(record, 'case_id', None)
    sample_id = getattr(record, 'sample_id', None)
    sequence = getattr(record, 'sequence', None)
    rater = getattr(record, 'rater', None)
    case_key = f"{dataset}/{case_id}" if dataset is not None and case_id is not None else f"{sample_id}/{sequence}"
    return {
        'id': record.id,
        'module': module['key'],
        'module_label': module['label'],
        'dataset': dataset,
        'case_id': case_id,
        'sample_id': sample_id,
        'sequence': sequence,
        'case_key': case_key,
        'rater_id': getattr(record, 'rater_id', None),
        'rater': getattr(rater, 'username', None),
        'time': _iso_datetime(time_value),
        'summary': _annotation_result_summary(payload),
        'payload': payload,
    }


def _filtered_annotation_results(module_key=None, rater_id=None, dataset=None, case_id=None, search=None):
    search = (search or '').strip()
    dataset = (dataset or '').strip()
    case_id = (case_id or '').strip()
    modules = [
        module for module in _annotation_modules()
        if not module_key or module['key'] == module_key
    ]
    results = []
    for module in modules:
        model = module['model']
        query = model.query.outerjoin(User, model.rater_id == User.id)
        if rater_id is not None:
            query = query.filter(model.rater_id == rater_id)
        if hasattr(model, 'dataset'):
            if dataset:
                query = query.filter(model.dataset.ilike(f"%{dataset}%"))
            if case_id:
                query = query.filter(model.case_id.ilike(f"%{case_id}%"))
            if search:
                like = f"%{search}%"
                query = query.filter(db.or_(
                    model.dataset.ilike(like),
                    model.case_id.ilike(like),
                    User.username.ilike(like),
                ))
        else:
            if dataset:
                query = query.filter(model.sample_id.ilike(f"%{dataset}%"))
            if case_id:
                query = query.filter(model.sequence.ilike(f"%{case_id}%"))
            if search:
                like = f"%{search}%"
                query = query.filter(db.or_(
                    model.sample_id.ilike(like),
                    model.sequence.ilike(like),
                    User.username.ilike(like),
                ))
        for record in query.all():
            results.append(_annotation_result_item(module, record))
    results.sort(key=lambda item: item.get('time') or '', reverse=True)
    return results


def _user_workloads():
    rows = []
    for user in User.query.order_by(User.id.asc()).all():
        module_counts = {}
        all_cases = set()
        activity_times = []
        for module in _annotation_modules():
            records = _projected_annotation_records(module, rater_id=user.id)
            module_counts[module['key']] = len(records)
            for record in records:
                values = record._mapping
                all_cases.add(_case_key_from_projection(record))
                when = values.get('event_time')
                if when:
                    activity_times.append(when)

        rows.append({
            **user.to_admin_dict(),
            'status': '待审核' if not user.is_approved else '管理员' if user.is_admin else '已通过',
            'total_records': sum(module_counts.values()),
            'unique_cases': len(all_cases),
            'module_counts': module_counts,
            'first_activity_at': _iso_datetime(min(activity_times)) if activity_times else None,
            'last_activity_at': _iso_datetime(max(activity_times)) if activity_times else None,
            'is_online': bool(user.last_login_at and (not user.last_logout_at or user.last_login_at > user.last_logout_at)),
        })
    return rows


def _security_overview():
    status_counts = {
        row.status: row.count
        for row in db.session.query(MediaAccessLog.status, db.func.count(MediaAccessLog.id).label('count'))
        .group_by(MediaAccessLog.status)
        .all()
    }
    recent_logs = MediaAccessLog.query.order_by(MediaAccessLog.created_at.desc()).limit(40).all()
    assignment_counts = {
        row.namespace: row.count
        for row in db.session.query(CaseAssignment.namespace, db.func.count(CaseAssignment.id).label('count'))
        .filter_by(active=True)
        .group_by(CaseAssignment.namespace)
        .all()
    }
    return {
        'assignments_total': CaseAssignment.query.filter_by(active=True).count(),
        'assignments_by_namespace': assignment_counts,
        'dataset_grants_total': DatasetAccessGrant.query.filter_by(active=True).count(),
        'dataset_access_audits_total': DatasetAccessAudit.query.count(),
        'media_logs_total': MediaAccessLog.query.count(),
        'media_status_counts': status_counts,
        'recent_media_logs': [item.to_dict() for item in recent_logs],
        'watermark_enabled': os.environ.get('LABELSYSTEM_IMAGE_WATERMARK', '1').lower() not in {'0', 'false', 'no'},
    }


def _feedback_session_for_user(session_id, user=None, allow_admin=False):
    session_record = FeedbackSession.query.get(session_id)
    actor = user or current_user
    if session_record is None:
        return None
    if allow_admin and getattr(actor, 'is_admin', False):
        return session_record
    if int(session_record.user_id) != int(actor.id):
        return None
    return session_record


def _run_feedback_agent(history, page_context, category_hint, reasoning_level, attachments=None):
    config = _load_llm_gateway_config()
    if not config.get('enabled'):
        raise RuntimeError('AI 服务当前未启用')
    client = _llm_gateway_client(config)
    fallback_model = str(config.get('model') or DEFAULT_LLM_GATEWAY_CONFIG['model']).strip()
    preferred_model = resolve_feedback_model(
        fallback_model,
        reasoning_level,
        standard_model=os.environ.get('LABELSYSTEM_FEEDBACK_MODEL', ''),
        high_model=os.environ.get('LABELSYSTEM_FEEDBACK_HIGH_MODEL', ''),
    )
    messages = build_feedback_agent_messages(
        history,
        page_context=page_context,
        category_hint=category_hint,
    )
    if attachments:
        image_items = []
        for attachment in attachments[:4]:
            try:
                image_bytes = Path(attachment.storage_path).read_bytes()
            except OSError:
                continue
            image_items.append({
                'type': 'image_url',
                'image_url': {
                    'url': f'data:{attachment.mime_type};base64,{base64.b64encode(image_bytes).decode("ascii")}',
                    'detail': 'high',
                },
            })
        if image_items:
            for item in reversed(messages):
                if item.get('role') == 'user':
                    item['content'] = [
                        {'type': 'text', 'text': str(item.get('content') or '')},
                        *image_items,
                    ]
                    break
    started = time.time()
    attempts = []
    for attempt in (
        (preferred_model, True),
        (fallback_model, True),
        (fallback_model, False),
    ):
        if attempt[0] and attempt not in attempts:
            attempts.append(attempt)
    minimum_response_tokens = 3200 if reasoning_level == 'high' else 2400
    last_error = None
    for model_name, use_reasoning_contract in attempts:
        try:
            request_payload = {
                'model': model_name,
                'messages': messages,
                'max_tokens': max(int(config.get('max_tokens') or 1200), minimum_response_tokens),
            }
            if use_reasoning_contract:
                request_payload.update({
                    'response_format': {'type': 'json_object'},
                    'extra_body': {'reasoning_effort': reasoning_level},
                })
            response = client.chat.completions.create(**request_payload)
            response_text = (response.choices[0].message.content or '').strip()
            return {
                **normalize_agent_result(response_text),
                'model_name': model_name,
                'latency_ms': int((time.time() - started) * 1000),
            }
        except Exception as exc:
            last_error = exc
    raise RuntimeError('AI 服务暂时不可用') from last_error


def _safe_feedback_change_scope(ticket):
    requested = str(ticket.get('change_scope') or 'needs_review')
    if requested != 'minimal_candidate':
        return requested
    text = ' '.join(str(ticket.get(key) or '') for key in (
        'category', 'title', 'summary', 'operation', 'expected_behavior', 'actual_behavior'
    )).lower()
    blocked_terms = {
        'dicom', '标注', '轮廓', '测量', '公式', '报告', '诊断', '权限', '数据库',
        '删除', '模型', '传播', '分割', '批量', '部署', '服务', '接口', '病例',
    }
    if ticket.get('category') != 'bug' or any(term in text for term in blocked_terms):
        return 'needs_review'
    return 'minimal_candidate'


def _feedback_work_plan_payload(issue):
    raw = {
        'category': issue.category,
        'title': issue.title,
        'summary': issue.summary,
        'page': issue.page,
        'operation': issue.operation,
        'expected_behavior': issue.expected_behavior,
        'actual_behavior': issue.actual_behavior,
        'impact': issue.impact,
        'severity': issue.severity,
        'acceptance_criteria': issue.acceptance_criteria,
        'change_scope': issue.change_scope,
    }
    return {key: redact_external_text(value) for key, value in raw.items()}


def _normalize_feedback_work_plan(raw_text, issue):
    parsed = _extract_json_object(raw_text)
    if not isinstance(parsed, dict):
        parsed = {
            'solution_summary': str(raw_text or '').strip() or '未生成有效方案。',
            'implementation_steps': [],
            'risks': [],
            'verification_steps': [],
            'execution_scope': 'needs_review',
            'codex_brief': '',
        }
    def text(key, default=''):
        return str(parsed.get(key) or default).strip()
    def text_list(key):
        value = parsed.get(key)
        return [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []
    risks = []
    for item in parsed.get('risks') if isinstance(parsed.get('risks'), list) else []:
        if isinstance(item, dict):
            risks.append({
                'level': str(item.get('level') or 'medium').strip(),
                'risk': str(item.get('risk') or '').strip(),
                'mitigation': str(item.get('mitigation') or '').strip(),
            })
    scope = text('execution_scope', 'needs_review')
    if scope not in {'guidance_only', 'minimal_candidate', 'needs_review', 'large_change'}:
        scope = 'needs_review'
    codex_brief = text('codex_brief')
    if not codex_brief:
        codex_brief = (
            f'处理工作站反馈：{issue.title}\n'
            f'问题摘要：{issue.summary}\n'
            f'发生页面：{issue.page}\n'
            f'实际表现：{issue.actual_behavior}\n'
            f'期望表现：{issue.expected_behavior}\n'
            f'验收标准：{issue.acceptance_criteria}\n'
            '先只读定位调用链，给出最小改动方案、风险和验证结果；未经批准不要修改数据、标注、数据库或服务。'
        )
    repository_evidence = []
    for item in parsed.get('repository_evidence') if isinstance(parsed.get('repository_evidence'), list) else []:
        if not isinstance(item, dict):
            continue
        path = str(item.get('path') or '').strip().lstrip('/')
        try:
            line_start = max(1, int(item.get('line_start') or 1))
            line_end = max(line_start, int(item.get('line_end') or line_start))
        except (TypeError, ValueError):
            continue
        if path and '..' not in Path(path).parts:
            repository_evidence.append({
                'path': path[:1000],
                'line_start': line_start,
                'line_end': line_end,
                'reason': str(item.get('reason') or '').strip()[:4000],
            })
    confidence = text('confidence', 'low')
    if confidence not in {'high', 'medium', 'low'}:
        confidence = 'low'
    implementation_size = text('implementation_size', 'medium')
    if implementation_size not in {'small', 'medium', 'large'}:
        implementation_size = 'medium'
    reproducibility = text('reproducibility', 'production_data_required')
    if reproducibility not in {'code_only', 'demo_cases', 'production_data_required'}:
        reproducibility = 'production_data_required'
    return {
        'solution_summary': text('solution_summary', '需人工补充解决方案。'),
        'root_cause': text('root_cause'),
        'implementation_steps': text_list('implementation_steps'),
        'allowed_paths': [
            str(item).strip()[:1000]
            for item in parsed.get('allowed_paths') if isinstance(parsed.get('allowed_paths'), list)
            if str(item).strip() and '..' not in Path(str(item).strip()).parts
        ][:80],
        'risks': risks,
        'verification_steps': text_list('verification_steps'),
        'execution_scope': scope,
        'codex_brief': codex_brief,
        'repository_evidence': repository_evidence,
        'confidence': confidence,
        'implementation_size': implementation_size,
        'clarifying_question': text('clarifying_question'),
        'base_sha': text('base_sha')[:64],
        'branch': text('branch')[:160],
        'dirty_worktree': bool(parsed.get('dirty_worktree')),
        'prompt_hash': text('prompt_hash')[:64],
        'reproducibility': reproducibility,
        'data_requirements': text('data_requirements'),
    }


def _generate_feedback_work_plan(issue, revision_note=''):
    config = _load_llm_gateway_config()
    if not config.get('enabled'):
        raise RuntimeError('AI 服务当前未启用')
    client = _llm_gateway_client(config)
    model_name = str(config.get('model') or DEFAULT_LLM_GATEWAY_CONFIG['model']).strip()
    issue_payload = _feedback_work_plan_payload(issue)
    messages = [
        {
            'role': 'system',
            'content': (
                '你是 CMR 工作站的工程方案审查助手。根据已结构化的问题单，生成可供负责人确认的修复方案。'
                '不要声称已经检查代码或执行修改；不能把 DICOM、标注、测量、报告、权限、数据库、模型、部署或批处理归为小修复。'
                '只输出 JSON：solution_summary、implementation_steps（字符串数组）、'
                'risks（含 level/risk/mitigation 的数组）、verification_steps（字符串数组）、'
                'execution_scope（guidance_only|minimal_candidate|needs_review|large_change）、codex_brief。'
            ),
        },
        {
            'role': 'user',
            'content': json.dumps({
                'issue': issue_payload,
                'revision_note': redact_external_text(revision_note),
            }, ensure_ascii=False),
        },
    ]
    response_text = ''
    last_error = None
    for structured in (True, False):
        try:
            payload = {
                'model': model_name,
                'messages': messages,
                'max_tokens': max(int(config.get('max_tokens') or 1200), 1400),
            }
            if structured:
                payload['response_format'] = {'type': 'json_object'}
            response = client.chat.completions.create(**payload)
            response_text = (response.choices[0].message.content or '').strip()
            break
        except Exception as exc:
            last_error = exc
    if not response_text:
        raise RuntimeError('方案生成暂不可用') from last_error
    result = _normalize_feedback_work_plan(response_text, issue)
    if revision_note.strip():
        result['revision_note'] = redact_external_text(revision_note).strip()
    return result


def _feedback_issue_codex_payload(issue):
    return {
        'id': issue.id,
        'session_id': issue.session_id,
        'category': issue.category,
        'title': issue.title,
        'summary': issue.summary,
        'page': issue.page,
        'operation': issue.operation,
        'expected_behavior': issue.expected_behavior,
        'actual_behavior': issue.actual_behavior,
        'impact': issue.impact,
        'severity': issue.severity,
        'acceptance_criteria': issue.acceptance_criteria,
        'change_scope': issue.change_scope,
    }


def _feedback_codex_source_message(issue):
    source = issue.source_message
    if source is not None and source.role == 'user':
        return source
    query = FeedbackMessage.query.filter_by(session_id=issue.session_id, role='user')
    if source is not None and source.created_at is not None:
        query = query.filter(FeedbackMessage.created_at <= source.created_at)
    return query.order_by(FeedbackMessage.created_at.desc(), FeedbackMessage.id.desc()).first()


def _feedback_codex_conversation(issue):
    records = (
        FeedbackMessage.query
        .filter_by(session_id=issue.session_id)
        .order_by(FeedbackMessage.created_at.desc(), FeedbackMessage.id.desc())
        .limit(24)
        .all()
    )
    records.reverse()
    return [
        {
            'message_id': item.id,
            'role': item.role,
            'content': item.content,
            'created_at': item.created_at.isoformat() if item.created_at else None,
        }
        for item in records
    ]


def _latest_feedback_codex_run(issue_id):
    return (
        FeedbackCodexRun.query
        .filter_by(issue_id=issue_id, phase='investigation')
        .order_by(FeedbackCodexRun.id.desc())
        .first()
    )


def _feedback_plan_baseline_status(plan):
    proposal = plan.proposal_json if plan is not None and isinstance(plan.proposal_json, dict) else {}
    plan_base_sha = str(proposal.get('base_sha') or '')
    investigated_dirty = bool(proposal.get('dirty_worktree'))
    try:
        snapshot = repository_snapshot()
    except CodexInvestigationError as exc:
        return {
            'available': False,
            'executable': False,
            'current_clean': False,
            'current_base_sha': '',
            'plan_base_sha': plan_base_sha,
            'investigated_dirty': investigated_dirty,
            'reason': 'repository_unavailable',
            'message': str(exc),
        }
    current_base_sha = str(snapshot.get('base_sha') or '')
    current_clean = not bool(snapshot.get('dirty'))
    executable = bool(
        plan_base_sha
        and not investigated_dirty
        and current_clean
        and plan_base_sha == current_base_sha
    )
    if investigated_dirty:
        reason = 'investigation_was_dirty'
        message = '该方案调查时仓库含未提交改动，必须在当前干净基线上重新调查。'
    elif not current_clean:
        reason = 'current_repository_dirty'
        message = '当前主仓库含未提交或未跟踪改动，需先建立干净基线。'
    elif not plan_base_sha:
        reason = 'plan_base_missing'
        message = '该方案没有绑定有效的 Git 基线，必须重新调查。'
    elif plan_base_sha != current_base_sha:
        reason = 'plan_base_stale'
        message = '当前仓库已经前进到新的 commit，旧方案必须重新调查。'
    else:
        reason = 'ready'
        message = '方案与当前干净 Git 基线一致，可以启动受控执行。'
    return {
        'available': True,
        'executable': executable,
        'current_clean': current_clean,
        'current_base_sha': current_base_sha,
        'plan_base_sha': plan_base_sha,
        'investigated_dirty': investigated_dirty,
        'reason': reason,
        'message': message,
    }


def _feedback_codex_history(issue_id, *, before_run_id=None, limit=8, completed_only=False):
    query = FeedbackCodexRun.query.filter_by(issue_id=issue_id, phase='investigation')
    if before_run_id is not None:
        query = query.filter(FeedbackCodexRun.id < before_run_id)
    if completed_only:
        query = query.filter(FeedbackCodexRun.status == 'completed')
    records = query.order_by(FeedbackCodexRun.id.desc()).limit(max(1, min(int(limit), 12))).all()
    records.reverse()
    return records


def _feedback_codex_prompt_history(issue_id, current_run_id, limit=5):
    records = _feedback_codex_history(
        issue_id,
        before_run_id=current_run_id,
        limit=limit,
        completed_only=True,
    )
    history = []
    for item in records:
        result = item.result_json or {}
        history.append({
            'run_id': item.id,
            'administrator_message': item.revision_note or '',
            'assistant_result': {
                'investigation_summary': result.get('investigation_summary'),
                'root_cause': result.get('root_cause'),
                'confidence': result.get('confidence'),
                'implementation_size': result.get('implementation_size'),
                'evidence': (result.get('evidence') or [])[:12],
                'recommended_changes': (result.get('recommended_changes') or [])[:12],
                'risks': (result.get('risks') or [])[:8],
                'verification_steps': (result.get('verification_steps') or [])[:10],
                'execution_scope': result.get('execution_scope'),
                'reproducibility': result.get('reproducibility'),
                'data_requirements': result.get('data_requirements'),
                'clarifying_question': result.get('clarifying_question'),
            },
        })
    return history


def _queue_feedback_codex_investigation(issue, initiated_by_id, revision_note=''):
    active = (
        FeedbackCodexRun.query
        .filter(
            FeedbackCodexRun.issue_id == issue.id,
            FeedbackCodexRun.phase == 'investigation',
            FeedbackCodexRun.status.in_(['pending', 'running']),
        )
        .order_by(FeedbackCodexRun.id.desc())
        .first()
    )
    if active is not None:
        return active, False
    run = FeedbackCodexRun(
        issue_id=issue.id,
        initiated_by_id=initiated_by_id,
        status='pending',
        phase='investigation',
        revision_note=str(revision_note or '').strip()[:4000],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.session.add(run)
    db.session.commit()
    app = current_app._get_current_object()
    Thread(
        target=_execute_feedback_codex_investigation,
        args=(app, run.id),
        daemon=True,
        name=f'feedback-codex-{run.id}',
    ).start()
    return run, True


def _execute_feedback_codex_investigation(app, run_id):
    with feedback_codex_execution_lock:
        with app.app_context():
            run = FeedbackCodexRun.query.get(run_id)
            if run is None or run.status != 'pending':
                return
            issue = FeedbackIssue.query.get(run.issue_id)
            if issue is None:
                run.status = 'failed'
                run.error_message = '问题单不存在'
                run.finished_at = datetime.utcnow()
                run.updated_at = run.finished_at
                db.session.commit()
                return
            run.status = 'running'
            run.started_at = datetime.utcnow()
            run.updated_at = run.started_at
            db.session.commit()

            source_message = _feedback_codex_source_message(issue)
            attachment_paths = [
                item.storage_path
                for item in (source_message.attachments if source_message is not None else [])
            ]
            artifact_dir = FEEDBACK_CODEX_RUN_DIR / str(run.id)
            run.artifact_dir = str(artifact_dir)
            db.session.commit()
            try:
                result, metadata = run_codex_investigation(
                    _feedback_issue_codex_payload(issue),
                    _feedback_codex_conversation(issue),
                    revision_note=run.revision_note,
                    investigation_history=_feedback_codex_prompt_history(issue.id, run.id),
                    attachment_paths=attachment_paths,
                    run_dir=artifact_dir,
                )
            except Exception as exc:
                safe_error = str(exc) if isinstance(exc, CodexInvestigationError) else f'{type(exc).__name__}: {exc}'
                current_app.logger.exception('Feedback Codex investigation failed for run %s', run.id)
                run.status = 'failed'
                run.error_message = safe_error[:12000]
                run.finished_at = datetime.utcnow()
                run.updated_at = run.finished_at
                failure_message = FeedbackMessage(
                    session_id=issue.session_id,
                    author_id=None,
                    role='assistant',
                    content=(
                        '## Codex 仓库调查未完成\n\n'
                        f'{safe_error}\n\n'
                        '问题单已经保留，负责人可以在反馈看板中重新发起仓库调查。'
                    ),
                    reasoning_level='high',
                    page_context=source_message.page_context if source_message is not None else {},
                    model_name='codex-repository-investigator',
                    created_at=datetime.utcnow(),
                )
                db.session.add(failure_message)
                issue.session.last_message_at = failure_message.created_at
                issue.session.updated_at = failure_message.created_at
                db.session.commit()
                return

            proposal = investigation_to_proposal(result, metadata, _feedback_issue_codex_payload(issue))
            plan = FeedbackWorkPlan.query.filter_by(issue_id=issue.id).first()
            if plan is None:
                plan = FeedbackWorkPlan(issue_id=issue.id, created_at=datetime.utcnow())
                db.session.add(plan)
            if plan.status not in {'queued', 'verified'}:
                plan.proposal_json = proposal
                plan.status = 'draft'
                plan.generated_by_id = run.initiated_by_id
                plan.approved_by_id = None
                plan.approved_at = None
                plan.queue_note = ''
                plan.execution_note = ''
                plan.updated_at = datetime.utcnow()
                issue.status = 'reviewing'
                issue.updated_at = plan.updated_at

            completion_message = FeedbackMessage(
                session_id=issue.session_id,
                author_id=None,
                role='assistant',
                content=investigation_markdown(result, metadata),
                reasoning_level='high',
                page_context=source_message.page_context if source_message is not None else {},
                model_name=f"codex-repository-investigator:{metadata.get('model', '')}"[:120],
                created_at=datetime.utcnow(),
            )
            db.session.add(completion_message)
            issue.session.last_message_at = completion_message.created_at
            issue.session.updated_at = completion_message.created_at
            run.status = 'completed'
            run.base_sha = str(metadata.get('base_sha') or '')[:64]
            run.branch = str(metadata.get('branch') or '')[:160]
            run.dirty_worktree = bool(metadata.get('dirty'))
            run.model_name = str(metadata.get('model') or '')[:120]
            run.prompt_hash = str(metadata.get('prompt_hash') or '')[:64]
            run.result_json = result
            run.error_message = ''
            run.finished_at = datetime.utcnow()
            run.updated_at = run.finished_at
            db.session.commit()


def _latest_feedback_execution(issue_id):
    return (
        FeedbackExecutionRun.query
        .filter_by(issue_id=issue_id)
        .order_by(FeedbackExecutionRun.id.desc())
        .first()
    )


def _feedback_execution_issue_snapshot(issue):
    return {
        'id': issue.id,
        'category': issue.category,
        'title': issue.title,
        'summary': issue.summary,
        'page': issue.page,
        'operation': issue.operation,
        'expected_behavior': issue.expected_behavior,
        'actual_behavior': issue.actual_behavior,
        'impact': issue.impact,
        'severity': issue.severity,
        'acceptance_criteria': issue.acceptance_criteria,
        'change_scope': issue.change_scope,
    }


def _feedback_plan_hash(snapshot):
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return std_hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _execution_to_dict(run):
    if run is None:
        return None
    return run.to_dict(include_paths=bool(getattr(current_user, 'is_admin', False)))


def _queue_feedback_execution(issue, plan, initiated_by_id):
    active = (
        FeedbackExecutionRun.query
        .filter(
            FeedbackExecutionRun.work_plan_id == plan.id,
            FeedbackExecutionRun.status.in_([
                'queued', 'preparing', 'running', 'stopping', 'review_ready',
                'review_approved', 'merging',
            ]),
        )
        .order_by(FeedbackExecutionRun.id.desc())
        .first()
    )
    if active is not None:
        return active, False
    proposal = plan.proposal_json if isinstance(plan.proposal_json, dict) else {}
    if bool(proposal.get('dirty_worktree')):
        raise CodexExecutionError('该方案调查时仓库含未提交改动，不能作为受控执行基线；请先固化代码并重新调查')
    if not isinstance(proposal.get('allowed_paths'), list) or not proposal.get('allowed_paths'):
        raise CodexExecutionError('该方案没有冻结允许修改的文件范围，请重新调查仓库后再批准')
    proposal = {**proposal, 'allowed_paths': validate_allowed_paths(proposal['allowed_paths'])}
    base_sha = validate_clean_execution_base(str(proposal.get('base_sha') or ''))
    snapshot = {
        'issue': _feedback_execution_issue_snapshot(issue),
        'proposal': proposal,
        'base_sha': base_sha,
        'approved_by_id': plan.approved_by_id,
        'approved_at': plan.approved_at.isoformat() if plan.approved_at else None,
    }
    previous = (
        FeedbackExecutionRun.query
        .filter_by(work_plan_id=plan.id, status='review_rejected')
        .order_by(FeedbackExecutionRun.id.desc())
        .first()
    )
    if previous is not None and previous.review_note:
        snapshot['previous_rejection_note'] = previous.review_note
    run = FeedbackExecutionRun(
        issue_id=issue.id,
        work_plan_id=plan.id,
        attempt=(
            db.session.query(db.func.coalesce(db.func.max(FeedbackExecutionRun.attempt), 0))
            .filter(FeedbackExecutionRun.work_plan_id == plan.id)
            .scalar()
            + 1
        ),
        initiated_by_id=initiated_by_id,
        status='queued',
        phase='queued',
        base_sha=base_sha,
        target_branch=str(proposal.get('branch') or 'main')[:160],
        plan_snapshot_json=snapshot,
        plan_hash=_feedback_plan_hash(snapshot),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.session.add(run)
    plan.status = 'queued'
    plan.queue_note = '已进入受控 Codex 执行队列；将在独立 Git worktree 中产生候选改动。'
    plan.updated_at = datetime.utcnow()
    db.session.commit()
    app = current_app._get_current_object()
    Thread(
        target=_execute_feedback_code_change,
        args=(app, run.id),
        daemon=True,
        name=f'feedback-execution-{run.id}',
    ).start()
    return run, True


def _execute_feedback_code_change(app, run_id):
    with app.app_context():
        claimed = (
            FeedbackExecutionRun.query
            .filter_by(id=run_id, status='queued')
            .update({
                FeedbackExecutionRun.status: 'preparing',
                FeedbackExecutionRun.phase: 'claiming',
                FeedbackExecutionRun.started_at: datetime.utcnow(),
                FeedbackExecutionRun.updated_at: datetime.utcnow(),
                FeedbackExecutionRun.version: FeedbackExecutionRun.version + 1,
            })
        )
        db.session.commit()
        if claimed != 1:
            return
        run = FeedbackExecutionRun.query.get(run_id)
        if run is None:
            return
        snapshot = run.plan_snapshot_json if isinstance(run.plan_snapshot_json, dict) else {}
        issue_snapshot = snapshot.get('issue') if isinstance(snapshot.get('issue'), dict) else {}
        proposal = snapshot.get('proposal') if isinstance(snapshot.get('proposal'), dict) else {}
        if snapshot.get('previous_rejection_note'):
            proposal = {
                **proposal,
                'previous_execution_rejection': str(snapshot.get('previous_rejection_note'))[:12000],
            }
        artifact_dir = FEEDBACK_EXECUTION_RUN_DIR / str(run.id)
        run.artifact_dir = str(artifact_dir)
        run.updated_at = datetime.utcnow()
        db.session.commit()

        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / 'request.json').write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True),
            encoding='utf-8',
        )

        def update(**fields):
            current = FeedbackExecutionRun.query.get(run_id)
            if current is None:
                return
            allowed = {
                'phase', 'worktree_path', 'candidate_branch', 'prompt_hash',
                'process_id', 'exit_code', 'changed_files',
            }
            for key, value in fields.items():
                if key not in allowed:
                    continue
                target = 'changed_files_json' if key == 'changed_files' else key
                setattr(current, target, value)
            if current.status == 'preparing' and current.phase == 'running_codex':
                current.status = 'running'
            current.version = int(current.version or 1) + 1
            current.updated_at = datetime.utcnow()
            db.session.commit()

        def should_stop():
            current = FeedbackExecutionRun.query.get(run_id)
            return current is None or bool(current.stop_requested)

        try:
            result = run_controlled_execution(
                run.id,
                issue_snapshot,
                proposal,
                base_sha=run.base_sha,
                artifact_dir=artifact_dir,
                model=str(os.environ.get('LABELSYSTEM_CODEX_EXECUTION_MODEL') or '').strip(),
                update=update,
                should_stop=should_stop,
            )
        except CodexExecutionStopped as exc:
            run = FeedbackExecutionRun.query.get(run_id)
            run.status = 'stopped'
            run.phase = 'stopped'
            run.error_message = str(exc)
            run.finished_at = datetime.utcnow()
            run.process_id = None
            run.version = int(run.version or 1) + 1
            run.updated_at = run.finished_at
            db.session.commit()
            return
        except Exception as exc:
            current_app.logger.exception('Controlled feedback execution failed for run %s', run_id)
            run = FeedbackExecutionRun.query.get(run_id)
            changed_files_path = artifact_dir / 'changed_files.json'
            tests_path = artifact_dir / 'tests.json'
            try:
                changed_files = json.loads(changed_files_path.read_text(encoding='utf-8')) if changed_files_path.is_file() else []
            except (OSError, ValueError):
                changed_files = []
            try:
                tests = json.loads(tests_path.read_text(encoding='utf-8')) if tests_path.is_file() else {}
            except (OSError, ValueError):
                tests = {}
            run.status = 'failed'
            run.phase = 'failed'
            run.error_message = str(exc)[:12000]
            run.changed_files_json = changed_files if isinstance(changed_files, list) else []
            run.tests_json = tests if isinstance(tests, dict) else {}
            run.tests_passed = tests.get('passed') if isinstance(tests, dict) else None
            run.finished_at = datetime.utcnow()
            run.process_id = None
            run.version = int(run.version or 1) + 1
            run.updated_at = run.finished_at
            db.session.commit()
            return

        run = FeedbackExecutionRun.query.get(run_id)
        run.status = 'review_ready'
        run.phase = 'awaiting_human_review'
        run.candidate_sha = result['candidate_sha']
        run.candidate_branch = result['candidate_branch']
        run.worktree_path = result['worktree_path']
        run.artifact_dir = result['artifact_dir']
        run.prompt_hash = result['prompt_hash']
        run.diff_hash = result['diff_hash']
        run.model_name = result['model_name']
        run.changed_files_json = result['changed_files']
        run.tests_json = result['tests']
        run.tests_passed = bool(result['tests_passed'])
        run.exit_code = result['exit_code']
        run.error_message = ''
        run.finished_at = datetime.utcnow()
        run.process_id = None
        run.version = int(run.version or 1) + 1
        run.updated_at = run.finished_at
        run.work_plan.execution_note = f"候选提交 {run.candidate_sha[:12]} 已生成，等待人工审查。"
        db.session.commit()


def _upsert_feedback_issue(session_record, source_message, ticket):
    category = str(ticket.get('category') or 'other')
    issue = FeedbackIssue(
        session_id=session_record.id,
        reporter_id=session_record.user_id,
        category=category,
        title=str(ticket.get('title') or '未命名问题')[:200],
        created_at=datetime.utcnow(),
    )
    db.session.add(issue)
    issue.source_message_id = source_message.id
    issue.category = category
    issue.title = str(ticket.get('title') or issue.title or '未命名问题')[:200]
    issue.summary = str(ticket.get('summary') or '')
    issue.page = str(ticket.get('page') or '')[:120]
    issue.operation = str(ticket.get('operation') or '')
    issue.expected_behavior = str(ticket.get('expected_behavior') or '')
    issue.actual_behavior = str(ticket.get('actual_behavior') or '')
    issue.impact = str(ticket.get('impact') or '')
    issue.severity = str(ticket.get('severity') or 'medium')
    issue.acceptance_criteria = str(ticket.get('acceptance_criteria') or '')
    issue.change_scope = _safe_feedback_change_scope(ticket)
    issue.status = 'open'
    issue.updated_at = datetime.utcnow()
    return issue


def _parse_feedback_datetime(value):
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        return None


def _feedback_sessions_by_latest_user_message(query, limit):
    latest_user_message_at = (
        db.session.query(db.func.max(FeedbackMessage.created_at))
        .filter(
            FeedbackMessage.session_id == FeedbackSession.id,
            FeedbackMessage.role == 'user',
        )
        .correlate(FeedbackSession)
        .scalar_subquery()
    )
    return (
        query
        .add_columns(latest_user_message_at.label('last_user_message_at'))
        .order_by(latest_user_message_at.desc(), FeedbackSession.created_at.desc())
        .limit(limit)
        .all()
    )


def _store_feedback_attachment(upload, session_record):
    raw = upload.stream.read(FEEDBACK_ATTACHMENT_MAX_BYTES + 1)
    if not raw:
        raise ValueError('截图文件为空')
    if len(raw) > FEEDBACK_ATTACHMENT_MAX_BYTES:
        raise ValueError('单张截图不能超过 8MB')
    try:
        image = Image.open(io.BytesIO(raw))
        if str(image.format or '').upper() not in {'PNG', 'JPEG', 'WEBP'}:
            raise ValueError('仅支持 PNG、JPEG 或 WebP 图片')
        image = ImageOps.exif_transpose(image)
        image.load()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('无法识别这张截图') from exc
    if image.width < 1 or image.height < 1 or image.width * image.height > 30_000_000:
        raise ValueError('截图尺寸不合法或像素过大')
    if max(image.width, image.height) > FEEDBACK_ATTACHMENT_MAX_DIMENSION:
        image.thumbnail(
            (FEEDBACK_ATTACHMENT_MAX_DIMENSION, FEEDBACK_ATTACHMENT_MAX_DIMENSION),
            Image.Resampling.LANCZOS,
        )
    if image.mode not in {'RGB', 'RGBA'}:
        image = image.convert('RGBA' if 'transparency' in image.info else 'RGB')
    encoded = io.BytesIO()
    image.save(encoded, format='PNG', optimize=True)
    payload = encoded.getvalue()
    user_dir = FEEDBACK_ATTACHMENT_DIR / str(session_record.user_id)
    user_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    storage_path = user_dir / f'{uuid.uuid4().hex}.png'
    storage_path.write_bytes(payload)
    try:
        os.chmod(storage_path, 0o600)
    except OSError:
        pass
    original_name = secure_filename(str(upload.filename or '').strip()) or 'screenshot.png'
    record = FeedbackAttachment(
        session_id=session_record.id,
        uploader_id=session_record.user_id,
        storage_path=str(storage_path),
        original_name=original_name[:255],
        mime_type='image/png',
        size_bytes=len(payload),
        width=image.width,
        height=image.height,
        created_at=datetime.utcnow(),
    )
    db.session.add(record)
    return record

def register_routes(app):
    # Register new diagnosis blueprint
    from diagnosis_module.routes import diagnosis_bp
    app.register_blueprint(diagnosis_bp, url_prefix='/api/cardiac')

    # Old inline routes
    @app.route('/api/upload', methods=['POST'])
    def upload_case():
        if 'file' not in request.files:

            return jsonify({'error': 'No file part'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400

        filename = secure_filename(file.filename)
        if not (filename.lower().endswith('.zip') or filename.lower().endswith('.tar') or filename.lower().endswith('.tar.gz')):
            return jsonify({'error': 'Only .zip, .tar, .tar.gz supported'}), 400

        # Define upload target
        func_root = current_app.config['FUNCTIONAL_DATA_ROOT']
        dataset_name = "Uploaded"
        dataset_dir = os.path.join(func_root, dataset_name)
        os.makedirs(dataset_dir, exist_ok=True)

        # Generate case_id from filename (remove extension)
        case_id = os.path.splitext(filename)[0]
        if filename.lower().endswith('.tar.gz'):
             case_id = os.path.splitext(case_id)[0]
        
        # Avoid duplicates by appending timestamp if needed
        target_dir = os.path.join(dataset_dir, case_id)
        if os.path.exists(target_dir):
            import time
            case_id = f"{case_id}_{int(time.time())}"
            target_dir = os.path.join(dataset_dir, case_id)

        os.makedirs(target_dir, exist_ok=True)
        
        temp_path = os.path.join(dataset_dir, f"temp_{filename}")
        try:
            file.save(temp_path)
            
            # Extract
            if filename.lower().endswith('.zip'):
                with zipfile.ZipFile(temp_path, 'r') as zip_ref:
                    safe_extract_zip(zip_ref, target_dir)
            elif filename.lower().endswith(('.tar', '.tar.gz')):
                with tarfile.open(temp_path, 'r:*') as tar_ref:
                    safe_extract_tar(tar_ref, target_dir)
            
            # Cleanup temp file
            os.remove(temp_path)

            # Automated workflow checks: Structure Flattening and Validation
            try:
                flatten_directory(target_dir)
                is_valid, error_msg = validate_structure(target_dir)
                if not is_valid:
                     # Validation failed
                     shutil.rmtree(target_dir)
                     return jsonify({'error': f'Invalid structure: {error_msg}'}), 400
            except Exception as e:
                if os.path.exists(target_dir):
                    shutil.rmtree(target_dir)
                return jsonify({'error': f'Processing error: {str(e)}'}), 500

            # Generate metadata if valid
            try:
                import datetime
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with open(os.path.join(target_dir, "meta.json"), "w") as f:
                    json.dump({
                        "original_filename": filename,
                        "upload_time": timestamp,
                        "case_id": case_id
                    }, f, indent=4)
            except:
                pass # Non-critical

            return jsonify({
                'message': 'Upload successful',
                'dataset': dataset_name,
                'case_id': case_id
            })

        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            if os.path.exists(target_dir):
                shutil.rmtree(target_dir)
            return jsonify({'error': str(e)}), 500

    # ---------------------------------------------------------
    # Diagnosis Pipeline Routes
    # ---------------------------------------------------------
    
    @app.route('/api/diagnose', methods=['POST'])
    def diagnose_case():
        data = request.json
        if not data or 'case_id' not in data:
            return jsonify({'error': 'Missing case_id'}), 400
            
        case_id = data['case_id']
        dataset = data.get('dataset', 'Uploaded') # Default to Uploaded dataset
        custom_prompt = data.get('prompt', None)
        
        # Verify case exists
        # Note: DiagnosisPipeline expects patient_id which maps to a directory in DATA_DIR.
        # In LabelSystem settings.py, we set DATA_DIR = MRI_AGENT_ROOT/data.
        # But our upload puts files in FUNCTIONAL_DATA_ROOT/Uploaded/case_id.
        # The DiagnosisPipeline likely expects "patient_id" to be a direct folder in DATA_DIR.
        # Or maybe it scans subfolders?
        # Let's check `core/data_loader.py` in src.
        # For now, let's assume we might need to symlink or move the uploaded case to where pipeline expects it.
        # OR, we update pipeline logic.
        # But `load_patient_case(patient_id)` probably looks in DATA_DIR/patient_id.
        # If we uploaded to `.../data/Uploaded/case_id`, then `patient_id` should probably be `Uploaded/case_id`?
        # Let's verify `load_patient_case`.
        
        # For this turn, I will assume case_id is passed.
        # I will start the thread and stream response.
        
        event_queue = queue.Queue()
        
        def event_emitter(event):
            event_queue.put(event)
            
        def run_pipeline_thread():
            try:
                # We need to ensure the case is accessible.
                # If using Uploaded dataset, we might need to handle path.
                # Assuming pipeline can handle it or we pass a path.
                # Pipeline.run takes patient_id.
                
                pipeline = DiagnosisPipeline(event_emitter=event_emitter)
                
                # Check if we need to adjust patient_id or move data
                # Actually, `load_patient_case` uses `DATA_DIR / patient_id`.
                # So if our data is in `DATA_DIR / Uploaded / patient_id`, we should pass `Uploaded/patient_id`?
                # Path objects usually handle '/' on Linux.
                
                # If dataset is provided and not empty, prepend it.
                actual_patient_id = f"{dataset}/{case_id}" if dataset else case_id
                
                # Wait, `load_patient_case` might not support nested IDs if it does `DATA_DIR / patient_id`.
                # If `patient_id` contains slashes, it works.
                
                pipeline.run(actual_patient_id, custom_prompt=custom_prompt)
                event_queue.put(None) # Sentinel
            except Exception as e:
                import traceback
                traceback.print_exc()
                event_queue.put({
                    "type": "error",
                    "content": {"message": str(e)}
                })
                event_queue.put(None)

        thread = threading.Thread(target=run_pipeline_thread)
        thread.start()
        
        def generate():
            while True:
                event = event_queue.get()
                if event is None:
                    break
                
                # Format as SSE
                yield f"data: {json.dumps(event)}\n\n"
                
        return current_app.response_class(generate(), mimetype='text/event-stream')

    # ---------------------------------------------------------
    # Authentication Routes
    # ---------------------------------------------------------
    @app.route('/api/auth/register', methods=['POST'])
    def register():
        if not _check_auth_rate_limit('register', limit=10):
            return jsonify({'error': 'Too many registration attempts. Please try again later.'}), 429
        data = request.json
        if not data or not data.get('username') or not data.get('password') or not data.get('email'):
            return jsonify({'error': 'Missing username, email, or password'}), 400

        username = str(data['username']).strip()
        email = _normalize_email(data['email'])
        password = str(data['password'])
        if len(username) < 2 or len(username) > 64:
            return jsonify({'error': 'Username must be 2-64 characters'}), 400
        if not _valid_email(email):
            return jsonify({'error': 'Please provide a valid email address'}), 400
        if len(password) < 8:
            return jsonify({'error': 'Password must be at least 8 characters'}), 400
        
        if User.query.filter_by(username=username).first():
            return jsonify({'error': 'Username already exists'}), 400
        if db.session.query(User.id).filter(db.func.lower(User.email) == email).first():
            return jsonify({'error': 'Email already exists'}), 400

        is_first_user = User.query.count() == 0
        user = User(
            username=username,
            email=email,
            is_approved=is_first_user,
            is_admin=is_first_user,
            requested_at=datetime.utcnow(),
            approved_at=datetime.utcnow() if is_first_user else None,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        if is_first_user:
            return jsonify({'message': 'Initial administrator registered successfully', 'status': 'approved'}), 201
        return jsonify({'message': 'Registration request submitted. Please wait for administrator approval.', 'status': 'pending'}), 202

    @app.route('/api/auth/forgot-password', methods=['POST'])
    def forgot_password():
        data = request.json or {}
        identifier = str(data.get('identifier') or '').strip()
        note = str(data.get('note') or '').strip()
        if len(identifier) < 2:
            return jsonify({'error': '请输入用户名或邮箱'}), 400
        if len(note) > 1000:
            return jsonify({'error': '补充说明过长'}), 400

        normalized_email = _normalize_email(identifier) if '@' in identifier else ''
        user = None
        if normalized_email:
            user = db.session.query(User).filter(db.func.lower(User.email) == normalized_email).first()
        if user is None:
            user = User.query.filter_by(username=identifier).first()

        generic_message = '如果账号存在且已通过审核，重置密码申请已提交给管理员，请等待审核。'
        if user is None or not user.is_approved:
            return jsonify({'message': generic_message, 'status': 'submitted'}), 200

        user.password_reset_status = 'pending'
        user.password_reset_requested_at = datetime.utcnow()
        user.password_reset_handled_at = None
        user.password_reset_note = note or None

        detail_lines = [
            f'用户：{user.username}',
            f'邮箱：{user.email or "-"}',
            f'申请时间：{user.password_reset_requested_at.isoformat()}',
        ]
        if note:
            detail_lines.append(f'说明：{note}')
        for admin in _approved_admin_users():
            if admin.id == user.id:
                continue
            _create_system_message(
                recipient_id=admin.id,
                subject=f'密码重置申请：{user.username}',
                body='\n'.join(detail_lines),
                category='password_reset_request',
            )
        db.session.commit()
        return jsonify({'message': generic_message, 'status': 'submitted'}), 200

    @app.route('/api/auth/login', methods=['POST'])
    def login():
        try:
            if not _check_auth_rate_limit('login'):
                return jsonify({'error': 'Too many login attempts. Please try again later.'}), 429
            data = request.json
            if not data or not data.get('username') or not data.get('password'):
                return jsonify({'error': 'Missing username or password'}), 400
            
            user = User.query.filter_by(username=data['username']).first()
            if user is None or not user.check_password(data['password']):
                return jsonify({'error': 'Invalid username or password'}), 401
            if not user.is_approved:
                return jsonify({'error': 'Account is pending administrator approval'}), 403
            
            user.last_login_at = datetime.utcnow()
            user.login_count = (user.login_count or 0) + 1
            db.session.commit()
            login_user(user)
            return _json_with_media_cookie({'message': 'Logged in successfully', 'user': user.to_dict()})
        except Exception as e:
            current_app.logger.error(f"Login error: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': f"Internal Server Error: {str(e)}"}), 500

    @app.route('/api/auth/change-password', methods=['POST'])
    @login_required
    def change_password():
        data = request.json or {}
        current_password = str(data.get('current_password') or '')
        new_password = str(data.get('new_password') or '')
        if not current_password or not new_password:
            return jsonify({'error': 'Missing current_password or new_password'}), 400
        if not current_user.check_password(current_password):
            return jsonify({'error': '当前密码不正确'}), 400
        if len(new_password) < 8:
            return jsonify({'error': '新密码至少需要 8 位'}), 400
        if current_password == new_password:
            return jsonify({'error': '新密码不能与当前密码相同'}), 400

        current_user.set_password(new_password)
        current_user.password_reset_status = 'none'
        current_user.password_reset_handled_at = datetime.utcnow()
        current_user.password_reset_note = None
        db.session.commit()
        return jsonify({'message': '密码修改成功'})

    @app.route('/api/auth/logout', methods=['POST'])
    @login_required
    def logout():
        current_user.last_logout_at = datetime.utcnow()
        db.session.commit()
        logout_user()
        return jsonify({'message': 'Logged out successfully'})

    @app.route('/api/auth/me', methods=['GET'])
    def get_current_user_info():
        if current_user.is_authenticated:
            return _json_with_media_cookie({'authenticated': True, 'user': current_user.to_dict()})
        return jsonify({'authenticated': False}), 200

    @app.route('/api/messages/summary', methods=['GET'])
    @login_required
    def message_summary():
        unread_count = UserMessage.query.filter_by(recipient_id=current_user.id, is_read=False).count()
        recent = UserMessage.query.filter_by(recipient_id=current_user.id).order_by(UserMessage.created_at.desc()).limit(5).all()
        return jsonify({
            'unread_count': unread_count,
            'recent': [item.to_dict() for item in recent],
        })

    @app.route('/api/messages', methods=['GET', 'POST'])
    @login_required
    def user_messages():
        if request.method == 'GET':
            limit = min(max(int(request.args.get('limit', 30)), 1), 100)
            messages = (
                UserMessage.query
                .filter_by(recipient_id=current_user.id)
                .order_by(UserMessage.created_at.desc())
                .limit(limit)
                .all()
            )
            unread_count = UserMessage.query.filter_by(recipient_id=current_user.id, is_read=False).count()
            return jsonify({
                'messages': [item.to_dict() for item in messages],
                'unread_count': unread_count,
            })

        data = request.json or {}
        recipient_id_raw = data.get('recipient_id')
        body = str(data.get('body') or '').strip()
        subject = str(data.get('subject') or '').strip()
        category = str(data.get('category') or 'direct').strip() or 'direct'

        try:
            recipient_id = int(recipient_id_raw)
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid recipient'}), 400

        recipient = User.query.get(recipient_id)
        if recipient is None or not recipient.is_approved:
            return jsonify({'error': 'Recipient not found'}), 404
        if not _can_send_message(current_user, recipient):
            return jsonify({'error': 'You are not allowed to message this user'}), 403
        if len(subject) > 200:
            return jsonify({'error': 'Subject is too long'}), 400
        if not body:
            return jsonify({'error': 'Message body is required'}), 400

        message_record = UserMessage(
            sender_id=current_user.id,
            recipient_id=recipient.id,
            subject=subject,
            body=body,
            category=category,
            is_read=False,
            created_at=datetime.utcnow(),
        )
        db.session.add(message_record)
        db.session.commit()
        return jsonify({'message': message_record.to_dict(), 'status': 'sent'})

    @app.route('/api/messages/<int:message_id>/read', methods=['POST'])
    @login_required
    def mark_message_read(message_id):
        message_record = UserMessage.query.get(message_id)
        if message_record is None or message_record.recipient_id != current_user.id:
            return jsonify({'error': 'Message not found'}), 404
        if not message_record.is_read:
            message_record.is_read = True
            message_record.read_at = datetime.utcnow()
            db.session.commit()
        return jsonify({'message': message_record.to_dict(), 'status': 'ok'})

    @app.route('/api/feedback/sessions', methods=['GET', 'POST'])
    @login_required
    def feedback_sessions():
        if request.method == 'GET':
            records = (
                FeedbackSession.query
                .filter_by(user_id=current_user.id)
                .order_by(FeedbackSession.last_message_at.desc())
                .limit(60)
                .all()
            )
            return jsonify({'sessions': [item.to_dict() for item in records]})

        payload = request.json or {}
        context = safe_page_context(payload.get('page_context'))
        record = FeedbackSession(
            user_id=current_user.id,
            title='新对话',
            context_json=context,
            status='active',
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            last_message_at=datetime.utcnow(),
        )
        db.session.add(record)
        db.session.commit()
        return jsonify({'session': record.to_dict()}), 201

    @app.route('/api/feedback/sessions/<int:session_id>/messages', methods=['GET', 'POST'])
    @login_required
    def feedback_session_messages(session_id):
        session_record = _feedback_session_for_user(session_id)
        if session_record is None:
            return jsonify({'error': 'Conversation not found'}), 404
        if request.method == 'GET':
            messages = (
                FeedbackMessage.query
                .filter_by(session_id=session_record.id)
                .order_by(FeedbackMessage.created_at.asc(), FeedbackMessage.id.asc())
                .limit(300)
                .all()
            )
            return jsonify({
                'session': session_record.to_dict(),
                'messages': [item.to_dict() for item in messages],
                'issues': [item.to_dict() for item in session_record.issues],
            })

        payload = request.json or {}
        content = str(payload.get('content') or '').strip()
        if not content:
            return jsonify({'error': '请输入内容'}), 400
        if len(content) > 12000:
            return jsonify({'error': '单条消息不能超过 12000 字符'}), 400
        reasoning_level = str(payload.get('reasoning_level') or 'medium').strip()
        if reasoning_level not in {'medium', 'high'}:
            return jsonify({'error': 'Invalid reasoning level'}), 400
        category_hint = str(payload.get('category_hint') or '').strip()
        if category_hint not in {'', 'usage_help', 'bug', 'feature_request', 'data_issue', 'ai_experience', 'other'}:
            category_hint = ''
        page_context = safe_page_context(payload.get('page_context'))
        now = datetime.utcnow()
        recent_message_count = (
            FeedbackMessage.query
            .join(FeedbackSession, FeedbackSession.id == FeedbackMessage.session_id)
            .filter(
                FeedbackSession.user_id == current_user.id,
                FeedbackMessage.role == 'user',
                FeedbackMessage.created_at >= now - timedelta(minutes=1),
            )
            .count()
        )
        if recent_message_count >= 8:
            return jsonify({'error': '发送过于频繁，请稍后再试'}), 429
        raw_attachment_ids = payload.get('attachment_ids') or []
        if not isinstance(raw_attachment_ids, list) or len(raw_attachment_ids) > 4:
            return jsonify({'error': '每条消息最多携带 4 张截图'}), 400
        try:
            attachment_ids = list(dict.fromkeys(int(item) for item in raw_attachment_ids))
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid attachment'}), 400
        attachments = []
        if attachment_ids:
            attachments = (
                FeedbackAttachment.query
                .filter(
                    FeedbackAttachment.id.in_(attachment_ids),
                    FeedbackAttachment.session_id == session_record.id,
                    FeedbackAttachment.uploader_id == current_user.id,
                    FeedbackAttachment.message_id.is_(None),
                )
                .order_by(FeedbackAttachment.id.asc())
                .all()
            )
            if len(attachments) != len(attachment_ids):
                return jsonify({'error': '截图不存在或已发送'}), 400
        user_message = FeedbackMessage(
            session_id=session_record.id,
            author_id=current_user.id,
            role='user',
            content=content,
            reasoning_level=reasoning_level,
            page_context=page_context,
            created_at=now,
        )
        db.session.add(user_message)
        db.session.flush()
        for attachment in attachments:
            attachment.message_id = user_message.id
        if session_record.title == '新对话':
            session_record.title = derive_session_title(content)
        session_record.context_json = page_context or session_record.context_json
        session_record.last_message_at = now
        session_record.updated_at = now
        db.session.commit()

        history = (
            FeedbackMessage.query
            .filter_by(session_id=session_record.id)
            .order_by(FeedbackMessage.created_at.desc(), FeedbackMessage.id.desc())
            .limit(80)
            .all()
        )
        history.reverse()
        ai_available = True
        agent_result = None
        try:
            agent_result = _run_feedback_agent(
                [item.to_dict() for item in history],
                page_context,
                category_hint,
                reasoning_level,
                attachments,
            )
            assistant_content = agent_result['reply']
        except Exception as exc:
            current_app.logger.warning('Feedback assistant call failed: %s', exc)
            ai_available = False
            assistant_content = 'AI 专家暂时不可用。你的消息已经保存在当前对话中，管理员仍可在反馈面板查看。'

        assistant_message = FeedbackMessage(
            session_id=session_record.id,
            author_id=None,
            role='assistant',
            content=assistant_content,
            reasoning_level=reasoning_level,
            page_context=page_context,
            model_name=agent_result.get('model_name') if agent_result else None,
            latency_ms=agent_result.get('latency_ms') if agent_result else None,
            created_at=datetime.utcnow(),
        )
        db.session.add(assistant_message)
        db.session.flush()
        issue = None
        if (
            agent_result
            and agent_result.get('ready_for_ticket')
            and agent_result.get('ticket')
            and agent_result['ticket'].get('category') != 'usage_help'
        ):
            issue = _upsert_feedback_issue(session_record, user_message, agent_result['ticket'])
        session_record.last_message_at = assistant_message.created_at
        session_record.updated_at = assistant_message.created_at
        db.session.commit()
        codex_run = None
        if (
            issue is not None
            and os.environ.get('LABELSYSTEM_CODEX_AUTO_INVESTIGATE', '1').lower() not in {'0', 'false', 'no'}
        ):
            try:
                codex_run, _ = _queue_feedback_codex_investigation(issue, current_user.id)
            except Exception:
                db.session.rollback()
                current_app.logger.exception('Failed to queue automatic Feedback Codex investigation')
        return jsonify({
            'session': session_record.to_dict(),
            'user_message': user_message.to_dict(),
            'assistant_message': assistant_message.to_dict(),
            'issue': issue.to_dict() if issue else None,
            'codex_investigation': codex_run.to_dict(include_result=False) if codex_run else None,
            'intent': agent_result.get('intent') if agent_result else category_hint or 'other',
            'ai_available': ai_available,
        })

    @app.route('/api/feedback/sessions/<int:session_id>/attachments', methods=['POST'])
    @login_required
    def upload_feedback_attachment(session_id):
        session_record = _feedback_session_for_user(session_id)
        if session_record is None:
            return jsonify({'error': 'Conversation not found'}), 404
        upload = request.files.get('file')
        if upload is None:
            return jsonify({'error': '请选择截图'}), 400
        pending_count = FeedbackAttachment.query.filter_by(
            session_id=session_record.id,
            uploader_id=current_user.id,
            message_id=None,
        ).count()
        if pending_count >= 4:
            return jsonify({'error': '请先发送或删除当前截图'}), 400
        try:
            attachment = _store_feedback_attachment(upload, session_record)
            db.session.commit()
        except ValueError as exc:
            db.session.rollback()
            return jsonify({'error': str(exc)}), 400
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Failed to store feedback screenshot')
            return jsonify({'error': '保存截图失败'}), 500
        return jsonify({'attachment': attachment.to_dict()}), 201

    @app.route('/api/feedback/attachments/<int:attachment_id>', methods=['GET', 'DELETE'])
    @login_required
    def feedback_attachment_file(attachment_id):
        attachment = FeedbackAttachment.query.get(attachment_id)
        if attachment is None:
            return jsonify({'error': 'Screenshot not found'}), 404
        is_owner = int(attachment.uploader_id) == int(current_user.id)
        if not is_owner and not getattr(current_user, 'is_admin', False):
            return jsonify({'error': 'Screenshot not found'}), 404
        storage_path = Path(attachment.storage_path)
        if request.method == 'GET':
            if not storage_path.is_file():
                return jsonify({'error': 'Screenshot file not found'}), 404
            return send_file(
                storage_path,
                mimetype=attachment.mime_type,
                download_name=attachment.original_name,
                conditional=True,
                max_age=0,
            )
        if not is_owner or attachment.message_id is not None:
            return jsonify({'error': '已发送的截图不能删除'}), 409
        try:
            storage_path.unlink(missing_ok=True)
        except OSError:
            pass
        db.session.delete(attachment)
        db.session.commit()
        return jsonify({'status': 'deleted'})

    @app.route('/api/feedback/messages/<int:message_id>/rating', methods=['POST'])
    @login_required
    def rate_feedback_message(message_id):
        message_record = FeedbackMessage.query.get(message_id)
        if message_record is None or message_record.role != 'assistant':
            return jsonify({'error': 'Message not found'}), 404
        session_record = _feedback_session_for_user(message_record.session_id)
        if session_record is None:
            return jsonify({'error': 'Message not found'}), 404
        rating = str((request.json or {}).get('rating') or '').strip()
        if rating not in {'helpful', 'unhelpful'}:
            return jsonify({'error': 'Invalid rating'}), 400
        message_record.rating = rating
        issue = None
        if rating == 'unhelpful':
            issue = FeedbackIssue.query.filter_by(
                source_message_id=message_record.id,
                category='ai_experience',
            ).first()
            if issue is None:
                issue = FeedbackIssue(
                    session_id=session_record.id,
                    reporter_id=session_record.user_id,
                    source_message_id=message_record.id,
                    category='ai_experience',
                    title='工作站专家回答未解决医生问题',
                    summary='用户将本条 AI 回答标记为未解决，需结合上下文检查回答准确性和追问策略。',
                    page=str((message_record.page_context or {}).get('module_label') or (message_record.page_context or {}).get('module') or '')[:120],
                    impact='医生未能通过本条回答完成当前任务。',
                    severity='medium',
                    status='open',
                    acceptance_criteria='复核对话上下文，给出准确操作路径或补充一个关键追问。',
                    change_scope='needs_review',
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
                db.session.add(issue)
        db.session.commit()
        return jsonify({
            'message': message_record.to_dict(),
            'issue': issue.to_dict() if issue else None,
        })

    @app.route('/api/admin/feedback/overview', methods=['GET'])
    @require_feedback_dashboard_viewer
    def admin_feedback_overview():
        total_sessions = FeedbackSession.query.count()
        total_messages = FeedbackMessage.query.count()
        total_issues = FeedbackIssue.query.count()
        open_issues = FeedbackIssue.query.filter(FeedbackIssue.status.notin_(['fixed', 'closed'])).count()
        category_rows = (
            db.session.query(FeedbackIssue.category, db.func.count(FeedbackIssue.id))
            .group_by(FeedbackIssue.category)
            .all()
        )
        status_rows = (
            db.session.query(FeedbackIssue.status, db.func.count(FeedbackIssue.id))
            .group_by(FeedbackIssue.status)
            .all()
        )
        user_rows = (
            db.session.query(User.id, User.username, db.func.count(FeedbackSession.id))
            .outerjoin(FeedbackSession, FeedbackSession.user_id == User.id)
            .filter(User.is_approved.is_(True))
            .group_by(User.id, User.username)
            .order_by(User.username.asc())
            .all()
        )
        since = datetime.utcnow() - timedelta(days=13)
        recent_sessions = FeedbackSession.query.filter(FeedbackSession.created_at >= since).all()
        daily = {
            (since + timedelta(days=offset)).strftime('%Y-%m-%d'): 0
            for offset in range(14)
        }
        for record in recent_sessions:
            key = record.created_at.strftime('%Y-%m-%d')
            daily[key] = daily.get(key, 0) + 1
        return jsonify({
            'summary': {
                'sessions': total_sessions,
                'messages': total_messages,
                'issues': total_issues,
                'open_issues': open_issues,
            },
            'categories': {str(key or 'other'): count for key, count in category_rows},
            'statuses': {str(key or 'open'): count for key, count in status_rows},
            'daily_sessions': [{'date': key, 'count': daily[key]} for key in sorted(daily)],
            'users': [
                {'id': user_id, 'username': username, 'session_count': session_count}
                for user_id, username, session_count in user_rows
            ],
        })

    @app.route('/api/admin/feedback/issues', methods=['GET'])
    @require_feedback_dashboard_viewer
    def admin_feedback_issues():
        query = FeedbackIssue.query
        user_id = request.args.get('user_id', type=int)
        category = str(request.args.get('category') or '').strip()
        status = str(request.args.get('status') or '').strip()
        keyword = str(request.args.get('search') or '').strip()
        start = _parse_feedback_datetime(request.args.get('start'))
        end_raw = str(request.args.get('end') or '').strip()
        end = _parse_feedback_datetime(end_raw)
        if user_id:
            query = query.filter(FeedbackIssue.reporter_id == user_id)
        if category:
            query = query.filter(FeedbackIssue.category == category)
        if status:
            query = query.filter(FeedbackIssue.status == status)
        if keyword:
            like = f'%{keyword}%'
            query = query.filter(db.or_(FeedbackIssue.title.ilike(like), FeedbackIssue.summary.ilike(like)))
        if start:
            query = query.filter(FeedbackIssue.created_at >= start)
        if end:
            if len(end_raw) == 10:
                query = query.filter(FeedbackIssue.created_at < end + timedelta(days=1))
            else:
                query = query.filter(FeedbackIssue.created_at <= end)
        limit = min(max(request.args.get('limit', default=200, type=int), 1), 500)
        records = query.order_by(FeedbackIssue.updated_at.desc()).limit(limit).all()
        return jsonify({'issues': [item.to_dict(include_user=True) for item in records]})

    @app.route('/api/admin/feedback/issues/<int:issue_id>', methods=['PATCH'])
    @require_feedback_operator
    def admin_update_feedback_issue(issue_id):
        issue = FeedbackIssue.query.get(issue_id)
        if issue is None:
            return jsonify({'error': 'Issue not found'}), 404
        existing_plan = FeedbackWorkPlan.query.filter_by(issue_id=issue.id).first()
        if existing_plan and existing_plan.status in {'queued', 'verified'}:
            return jsonify({'error': '执行中的问题单不能直接修改，请先新建后续问题'}), 409
        payload = request.json or {}
        text_fields = {
            'title': 200,
            'summary': 12000,
            'page': 120,
            'operation': 12000,
            'expected_behavior': 12000,
            'actual_behavior': 12000,
            'impact': 12000,
            'acceptance_criteria': 12000,
        }
        for field, limit in text_fields.items():
            if field in payload:
                value = str(payload.get(field) or '').strip()
                if field == 'title' and not value:
                    return jsonify({'error': '问题标题不能为空'}), 400
                setattr(issue, field, value[:limit])
        if 'status' in payload:
            if not getattr(current_user, 'is_admin', False):
                return jsonify({'error': 'Only administrators can directly change issue status'}), 403
            status = str(payload.get('status') or '')
            if status not in {'open', 'reviewing', 'planned', 'fixed', 'closed'}:
                return jsonify({'error': 'Invalid status'}), 400
            issue.status = status
        if 'severity' in payload:
            severity = str(payload.get('severity') or '')
            if severity not in {'low', 'medium', 'high', 'critical'}:
                return jsonify({'error': 'Invalid severity'}), 400
            issue.severity = severity
        if 'admin_note' in payload:
            if not getattr(current_user, 'is_admin', False):
                return jsonify({'error': 'Only administrators can edit internal notes'}), 403
            issue.admin_note = str(payload.get('admin_note') or '')[:12000]
        if existing_plan and existing_plan.status == 'approved':
            existing_plan.status = 'draft'
            existing_plan.approved_by_id = None
            existing_plan.approved_at = None
            existing_plan.updated_at = datetime.utcnow()
        issue.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'issue': issue.to_dict(include_user=True)})

    @app.route('/api/admin/feedback/issues/<int:issue_id>/work-plan', methods=['GET'])
    @require_feedback_dashboard_viewer
    def get_feedback_work_plan(issue_id):
        issue = FeedbackIssue.query.get(issue_id)
        if issue is None:
            return jsonify({'error': 'Issue not found'}), 404
        plan = FeedbackWorkPlan.query.filter_by(issue_id=issue.id).first()
        investigation = _latest_feedback_codex_run(issue.id)
        execution = _latest_feedback_execution(issue.id)
        return jsonify({
            'work_plan': plan.to_dict() if plan else None,
            'baseline_status': _feedback_plan_baseline_status(plan) if plan else None,
            'codex_investigation': investigation.to_dict() if investigation else None,
            'investigation_history': [
                item.to_dict()
                for item in _feedback_codex_history(issue.id, limit=8)
            ],
            'execution': _execution_to_dict(execution),
            'execution_capability': {
                'enabled': True,
                'version': 1,
                'mode': 'isolated-worktree-review',
            },
        })

    @app.route('/api/admin/feedback/issues/<int:issue_id>/work-plan/reinvestigate', methods=['POST'])
    @require_feedback_operator
    def reinvestigate_feedback_work_plan(issue_id):
        issue = FeedbackIssue.query.get(issue_id)
        plan = FeedbackWorkPlan.query.filter_by(issue_id=issue_id).first()
        if issue is None or plan is None:
            return jsonify({'error': 'Work plan not found'}), 404
        if plan.status not in {'draft', 'approved'}:
            return jsonify({'error': '当前方案已有执行记录，请先完成或退回代码审查'}), 409
        active_execution = (
            FeedbackExecutionRun.query
            .filter(
                FeedbackExecutionRun.work_plan_id == plan.id,
                FeedbackExecutionRun.status.in_([
                    'queued', 'preparing', 'running', 'stopping', 'review_ready',
                    'review_approved', 'merging',
                ]),
            )
            .order_by(FeedbackExecutionRun.id.desc())
            .first()
        )
        if active_execution is not None:
            return jsonify({'error': '当前已有受控执行或候选改动，不能覆盖其批准基线'}), 409
        active_investigation = (
            FeedbackCodexRun.query
            .filter(
                FeedbackCodexRun.issue_id == issue.id,
                FeedbackCodexRun.phase == 'investigation',
                FeedbackCodexRun.status.in_(['pending', 'running']),
            )
            .order_by(FeedbackCodexRun.id.desc())
            .first()
        )
        if active_investigation is not None:
            return jsonify({
                'work_plan': plan.to_dict(),
                'codex_investigation': active_investigation.to_dict(include_result=False),
                'baseline_status': _feedback_plan_baseline_status(plan),
                'issue': issue.to_dict(include_user=True),
                'created': False,
            }), 202
        baseline = _feedback_plan_baseline_status(plan)
        if not baseline.get('available'):
            return jsonify({'error': baseline.get('message') or '当前无法读取 Git 基线'}), 503
        if not baseline.get('current_clean'):
            return jsonify({'error': '当前主仓库仍有未提交或未跟踪改动，请先让服务器 Codex 建立干净基线'}), 409
        previous_base = str(baseline.get('plan_base_sha') or '')[:12] or '未知'
        current_base = str(baseline.get('current_base_sha') or '')[:12]
        user_note = str((request.json or {}).get('revision_note') or '').strip()[:2500]
        revision_note = (
            f'请按当前干净 Git 基线 {current_base} 重新调查。旧方案绑定 {previous_base}'
            f'（原因：{baseline.get("reason") or "基线不一致"}），不得沿用旧方案的可写文件范围。'
            '保留仍然成立的需求判断，重新核对真实受版本控制源码、实现工作量、风险和验证步骤。'
        )
        if user_note:
            revision_note += f'\n\n管理员补充：{user_note}'
        plan.status = 'draft'
        plan.approved_by_id = None
        plan.approved_at = None
        plan.queue_note = ''
        plan.execution_note = ''
        plan.updated_at = datetime.utcnow()
        issue.status = 'reviewing'
        issue.updated_at = plan.updated_at
        try:
            run, created = _queue_feedback_codex_investigation(issue, current_user.id, revision_note)
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Failed to re-investigate Feedback Codex plan on clean baseline')
            return jsonify({'error': '重新调查暂时无法入队，旧方案未被覆盖，请稍后重试'}), 503
        return jsonify({
            'work_plan': plan.to_dict(),
            'codex_investigation': run.to_dict(include_result=False),
            'baseline_status': _feedback_plan_baseline_status(plan),
            'issue': issue.to_dict(include_user=True),
            'created': created,
        }), 202

    @app.route('/api/admin/feedback/issues/<int:issue_id>/work-plan/generate', methods=['POST'])
    @require_feedback_operator
    def generate_feedback_work_plan(issue_id):
        issue = FeedbackIssue.query.get(issue_id)
        if issue is None:
            return jsonify({'error': 'Issue not found'}), 404
        existing = FeedbackWorkPlan.query.filter_by(issue_id=issue.id).first()
        if existing and existing.status != 'draft':
            return jsonify({'error': '已批准或已执行的方案不能直接覆盖，请先完成审查或明确退回草案'}), 409
        revision_note = str((request.json or {}).get('revision_note') or '').strip()[:4000]
        try:
            run, created = _queue_feedback_codex_investigation(issue, current_user.id, revision_note)
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Failed to queue Feedback Codex investigation')
            return jsonify({'error': 'Codex 仓库调查暂时无法入队，请稍后重试'}), 503
        return jsonify({
            'work_plan': existing.to_dict() if existing else None,
            'codex_investigation': run.to_dict(include_result=False),
            'issue': issue.to_dict(include_user=True),
            'created': created,
        }), 202

    @app.route('/api/admin/feedback/issues/<int:issue_id>/work-plan', methods=['PATCH'])
    @require_feedback_operator
    def update_feedback_work_plan(issue_id):
        issue = FeedbackIssue.query.get(issue_id)
        plan = FeedbackWorkPlan.query.filter_by(issue_id=issue_id).first()
        if issue is None or plan is None:
            return jsonify({'error': 'Work plan not found'}), 404
        if plan.status != 'draft':
            return jsonify({'error': '请先重新生成或撤回到草案状态后再编辑'}), 409
        proposal = (request.json or {}).get('proposal')
        if not isinstance(proposal, dict):
            return jsonify({'error': 'Invalid proposal'}), 400
        plan.proposal_json = _normalize_feedback_work_plan(json.dumps(proposal, ensure_ascii=False), issue)
        plan.generated_by_id = current_user.id
        plan.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'work_plan': plan.to_dict()})

    @app.route('/api/admin/feedback/issues/<int:issue_id>/work-plan/approve', methods=['POST'])
    @require_feedback_operator
    def approve_feedback_work_plan(issue_id):
        issue = FeedbackIssue.query.get(issue_id)
        plan = FeedbackWorkPlan.query.filter_by(issue_id=issue_id).first()
        if issue is None or plan is None:
            return jsonify({'error': 'Work plan not found'}), 404
        if plan.status not in {'draft', 'approved'}:
            return jsonify({'error': '当前方案不能批准'}), 409
        plan.status = 'approved'
        plan.approved_by_id = current_user.id
        plan.approved_at = datetime.utcnow()
        plan.updated_at = datetime.utcnow()
        issue.status = 'planned'
        issue.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'work_plan': plan.to_dict(), 'issue': issue.to_dict(include_user=True)})

    @app.route('/api/admin/feedback/issues/<int:issue_id>/work-plan/queue', methods=['POST'])
    @require_admin
    def queue_feedback_work_plan(issue_id):
        if request.headers.get('X-LabelSystem-Action') != 'controlled-feedback':
            return jsonify({'error': 'Missing controlled execution request header'}), 400
        issue = FeedbackIssue.query.get(issue_id)
        plan = FeedbackWorkPlan.query.filter_by(issue_id=issue_id).first()
        if issue is None or plan is None:
            return jsonify({'error': 'Work plan not found'}), 404
        if plan.status not in {'approved', 'queued'}:
            return jsonify({'error': '请先批准方案'}), 409
        investigation = _latest_feedback_codex_run(issue_id)
        if investigation is not None and investigation.status in {'pending', 'running'}:
            return jsonify({'error': '该问题仍在进行仓库调查，不能同时启动旧方案执行'}), 409
        try:
            execution, created = _queue_feedback_execution(issue, plan, current_user.id)
        except CodexExecutionError as exc:
            db.session.rollback()
            return jsonify({'error': str(exc)}), 409
        except IntegrityError:
            db.session.rollback()
            execution = (
                FeedbackExecutionRun.query
                .filter_by(work_plan_id=plan.id)
                .order_by(FeedbackExecutionRun.id.desc())
                .first()
            )
            if execution is None:
                return jsonify({'error': '执行队列并发冲突，请刷新后重试'}), 409
            created = False
        return jsonify({
            'work_plan': plan.to_dict(),
            'execution': _execution_to_dict(execution),
            'created': created,
        }), 202 if created else 200

    @app.route('/api/admin/feedback/issues/<int:issue_id>/execution', methods=['GET'])
    @require_feedback_dashboard_viewer
    def get_feedback_execution(issue_id):
        issue = FeedbackIssue.query.get(issue_id)
        if issue is None:
            return jsonify({'error': 'Issue not found'}), 404
        return jsonify({'execution': _execution_to_dict(_latest_feedback_execution(issue_id))})

    def _feedback_execution_or_404(execution_id):
        return FeedbackExecutionRun.query.get(execution_id)

    @app.route('/api/admin/feedback/executions/<int:execution_id>/events', methods=['GET'])
    @require_admin
    def get_feedback_execution_events(execution_id):
        run = _feedback_execution_or_404(execution_id)
        if run is None:
            return jsonify({'error': 'Execution not found'}), 404
        try:
            offset = max(0, int(request.args.get('offset') or 0))
        except ValueError:
            return jsonify({'error': 'Invalid offset'}), 400
        artifact_dir = FEEDBACK_EXECUTION_RUN_DIR / str(run.id)
        events_path = artifact_dir / 'events.jsonl'
        chunk = ''
        next_offset = offset
        if events_path.is_file():
            size = events_path.stat().st_size
            if offset > size:
                offset = 0
            with events_path.open('rb') as handle:
                handle.seek(offset)
                data = handle.read(65536)
                next_offset = handle.tell()
            chunk = data.decode('utf-8', errors='replace')
        stderr_tail = ''
        if run.status in {'failed', 'stopped'}:
            stderr_path = artifact_dir / 'stderr.log'
            if stderr_path.is_file():
                stderr_tail = stderr_path.read_text(encoding='utf-8', errors='replace')[-12000:]
        summary = ''
        summary_path = artifact_dir / 'summary.txt'
        if run.status not in {'queued', 'preparing', 'running', 'stopping'} and summary_path.is_file():
            summary = summary_path.read_text(encoding='utf-8', errors='replace')[-24000:]
        return jsonify({
            'events': chunk,
            'offset': next_offset,
            'has_more': bool(events_path.is_file() and next_offset < events_path.stat().st_size),
            'stderr_tail': stderr_tail,
            'summary': summary,
            'phase': run.phase,
            'status': run.status,
        })

    @app.route('/api/admin/feedback/executions/<int:execution_id>/diff', methods=['GET'])
    @require_admin
    def get_feedback_execution_diff(execution_id):
        run = _feedback_execution_or_404(execution_id)
        if run is None:
            return jsonify({'error': 'Execution not found'}), 404
        artifact_dir = FEEDBACK_EXECUTION_RUN_DIR / str(run.id)
        diff_path = artifact_dir / 'changes.diff'
        stat_path = artifact_dir / 'diff.stat'
        return jsonify({
            'files': run.changed_files_json if isinstance(run.changed_files_json, list) else [],
            'unified_diff': diff_path.read_text(encoding='utf-8', errors='replace') if diff_path.is_file() else '',
            'stat': stat_path.read_text(encoding='utf-8', errors='replace') if stat_path.is_file() else '',
        })

    @app.route('/api/admin/feedback/executions/<int:execution_id>/tests', methods=['GET'])
    @require_admin
    def get_feedback_execution_tests(execution_id):
        run = _feedback_execution_or_404(execution_id)
        if run is None:
            return jsonify({'error': 'Execution not found'}), 404
        return jsonify({
            'passed': run.tests_passed,
            'tests': run.tests_json if isinstance(run.tests_json, dict) else {},
        })

    @app.route('/api/admin/feedback/executions/<int:execution_id>/stop', methods=['POST'])
    @require_admin
    def stop_feedback_execution(execution_id):
        if request.headers.get('X-LabelSystem-Action') != 'controlled-feedback':
            return jsonify({'error': 'Missing controlled execution request header'}), 400
        run = _feedback_execution_or_404(execution_id)
        if run is None:
            return jsonify({'error': 'Execution not found'}), 404
        conflict = _require_execution_version(run, request.json or {})
        if conflict:
            return conflict
        if run.status not in {'queued', 'preparing', 'running'}:
            return jsonify({'error': '当前执行不能停止'}), 409
        expected_version = int((request.json or {})['expected_version'])
        claimed = (
            FeedbackExecutionRun.query
            .filter(
                FeedbackExecutionRun.id == run.id,
                FeedbackExecutionRun.version == expected_version,
                FeedbackExecutionRun.status.in_(['queued', 'preparing', 'running']),
            )
            .update({
                FeedbackExecutionRun.stop_requested: True,
                FeedbackExecutionRun.status: 'stopping',
                FeedbackExecutionRun.phase: 'stop_requested',
                FeedbackExecutionRun.version: expected_version + 1,
                FeedbackExecutionRun.updated_at: datetime.utcnow(),
            })
        )
        if claimed != 1:
            db.session.rollback()
            return jsonify({'error': '执行状态已更新，请刷新后重试'}), 409
        db.session.commit()
        run = FeedbackExecutionRun.query.get(execution_id)
        stopped = request_feedback_execution_stop(run.id)
        if not stopped and not run.process_id:
            run.status = 'stopped'
            run.phase = 'stopped_before_start'
            run.finished_at = datetime.utcnow()
            db.session.commit()
        return jsonify({'execution': _execution_to_dict(run)})

    def _require_execution_version(run, payload):
        expected = payload.get('expected_version')
        if expected is None:
            return jsonify({'error': 'expected_version is required'}), 400
        try:
            matches = int(expected) == int(run.version or 1)
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid expected_version'}), 400
        if not matches:
            return jsonify({'error': '执行状态已更新，请刷新后重试'}), 409
        return None

    @app.route('/api/admin/feedback/executions/<int:execution_id>/review/approve', methods=['POST'])
    @require_admin
    def approve_feedback_execution(execution_id):
        if request.headers.get('X-LabelSystem-Action') != 'controlled-feedback':
            return jsonify({'error': 'Missing controlled execution request header'}), 400
        run = _feedback_execution_or_404(execution_id)
        if run is None:
            return jsonify({'error': 'Execution not found'}), 404
        payload = request.json or {}
        conflict = _require_execution_version(run, payload)
        if conflict:
            return conflict
        if run.status != 'review_ready' or not run.tests_passed:
            return jsonify({'error': '候选改动尚未通过固定验证或不在待审状态'}), 409
        if _feedback_plan_hash(run.plan_snapshot_json or {}) != run.plan_hash:
            return jsonify({'error': '批准方案快照校验失败'}), 409
        expected_version = int(payload['expected_version'])
        reviewed_at = datetime.utcnow()
        claimed = FeedbackExecutionRun.query.filter_by(
            id=run.id,
            status='review_ready',
            version=expected_version,
            tests_passed=True,
        ).update({
            FeedbackExecutionRun.status: 'review_approved',
            FeedbackExecutionRun.phase: 'approved_for_merge',
            FeedbackExecutionRun.reviewed_by_id: current_user.id,
            FeedbackExecutionRun.review_note: str(payload.get('review_note') or '')[:12000],
            FeedbackExecutionRun.reviewed_at: reviewed_at,
            FeedbackExecutionRun.version: expected_version + 1,
            FeedbackExecutionRun.updated_at: reviewed_at,
        })
        if claimed != 1:
            db.session.rollback()
            return jsonify({'error': '执行状态已更新，请刷新后重试'}), 409
        db.session.commit()
        run = FeedbackExecutionRun.query.get(execution_id)
        return jsonify({'execution': _execution_to_dict(run)})

    @app.route('/api/admin/feedback/executions/<int:execution_id>/revise', methods=['POST'])
    @require_admin
    def revise_feedback_execution_plan(execution_id):
        if request.headers.get('X-LabelSystem-Action') != 'controlled-feedback':
            return jsonify({'error': 'Missing controlled execution request header'}), 400
        run = _feedback_execution_or_404(execution_id)
        if run is None:
            return jsonify({'error': 'Execution not found'}), 404
        payload = request.json or {}
        conflict = _require_execution_version(run, payload)
        if conflict:
            return conflict
        if run.status not in {'failed', 'stopped', 'review_rejected'}:
            return jsonify({'error': '当前执行不能退回方案修订'}), 409
        expected_version = int(payload['expected_version'])
        updated_at = datetime.utcnow()
        claimed = (
            FeedbackExecutionRun.query
            .filter(
                FeedbackExecutionRun.id == run.id,
                FeedbackExecutionRun.version == expected_version,
                FeedbackExecutionRun.status.in_(['failed', 'stopped', 'review_rejected']),
            )
            .update({
                FeedbackExecutionRun.phase: 'plan_revision_requested',
                FeedbackExecutionRun.version: expected_version + 1,
                FeedbackExecutionRun.updated_at: updated_at,
            })
        )
        if claimed != 1:
            db.session.rollback()
            return jsonify({'error': '执行状态已更新，请刷新后重试'}), 409
        db.session.expire_all()
        run = FeedbackExecutionRun.query.get(execution_id)
        run.work_plan.status = 'draft'
        run.work_plan.approved_by_id = None
        run.work_plan.approved_at = None
        run.work_plan.queue_note = ''
        run.work_plan.updated_at = updated_at
        run.issue.status = 'reviewing'
        run.issue.updated_at = updated_at
        db.session.commit()
        return jsonify({'execution': _execution_to_dict(run), 'work_plan': run.work_plan.to_dict()})

    @app.route('/api/admin/feedback/executions/<int:execution_id>/review/reject', methods=['POST'])
    @require_admin
    def reject_feedback_execution(execution_id):
        if request.headers.get('X-LabelSystem-Action') != 'controlled-feedback':
            return jsonify({'error': 'Missing controlled execution request header'}), 400
        run = _feedback_execution_or_404(execution_id)
        if run is None:
            return jsonify({'error': 'Execution not found'}), 404
        payload = request.json or {}
        conflict = _require_execution_version(run, payload)
        if conflict:
            return conflict
        if run.status not in {'review_ready', 'review_approved'}:
            return jsonify({'error': '当前候选不能拒绝'}), 409
        note = str(payload.get('review_note') or '').strip()
        if not note:
            return jsonify({'error': '请填写拒绝原因，供下一次执行修订'}), 400
        expected_version = int(payload['expected_version'])
        reviewed_at = datetime.utcnow()
        claimed = (
            FeedbackExecutionRun.query
            .filter(
                FeedbackExecutionRun.id == run.id,
                FeedbackExecutionRun.version == expected_version,
                FeedbackExecutionRun.status.in_(['review_ready', 'review_approved']),
            )
            .update({
                FeedbackExecutionRun.status: 'review_rejected',
                FeedbackExecutionRun.phase: 'rejected_by_human',
                FeedbackExecutionRun.reviewed_by_id: current_user.id,
                FeedbackExecutionRun.review_note: note[:12000],
                FeedbackExecutionRun.reviewed_at: reviewed_at,
                FeedbackExecutionRun.version: expected_version + 1,
                FeedbackExecutionRun.updated_at: reviewed_at,
            })
        )
        if claimed != 1:
            db.session.rollback()
            return jsonify({'error': '执行状态已更新，请刷新后重试'}), 409
        db.session.expire_all()
        run = FeedbackExecutionRun.query.get(execution_id)
        run.work_plan.status = 'draft'
        run.work_plan.approved_by_id = None
        run.work_plan.approved_at = None
        run.work_plan.queue_note = ''
        run.work_plan.updated_at = reviewed_at
        run.issue.status = 'reviewing'
        run.issue.updated_at = reviewed_at
        db.session.commit()
        return jsonify({'execution': _execution_to_dict(run)})

    @app.route('/api/admin/feedback/executions/<int:execution_id>/merge', methods=['POST'])
    @require_admin
    def merge_feedback_execution(execution_id):
        if request.headers.get('X-LabelSystem-Action') != 'controlled-feedback':
            return jsonify({'error': 'Missing controlled execution request header'}), 400
        run = _feedback_execution_or_404(execution_id)
        if run is None:
            return jsonify({'error': 'Execution not found'}), 404
        payload = request.json or {}
        conflict = _require_execution_version(run, payload)
        if conflict:
            return conflict
        if run.status != 'review_approved' or not run.tests_passed or not run.candidate_sha:
            return jsonify({'error': '候选改动尚未获得人工批准'}), 409
        if str(payload.get('candidate_sha') or '') != run.candidate_sha:
            return jsonify({'error': '请提交页面显示的完整 candidate SHA 进行二次确认'}), 400
        expected_version = int(payload['expected_version'])
        claimed_version = expected_version + 1
        claimed = FeedbackExecutionRun.query.filter_by(
            id=run.id,
            status='review_approved',
            version=expected_version,
            tests_passed=True,
        ).update({
            FeedbackExecutionRun.status: 'merging',
            FeedbackExecutionRun.phase: 'validating_merge',
            FeedbackExecutionRun.version: claimed_version,
            FeedbackExecutionRun.updated_at: datetime.utcnow(),
        })
        if claimed != 1:
            db.session.rollback()
            return jsonify({'error': '执行状态已更新，请刷新后重试'}), 409
        db.session.commit()
        run = FeedbackExecutionRun.query.get(execution_id)
        artifact_dir = FEEDBACK_EXECUTION_RUN_DIR / str(run.id)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / 'merge-intent.json').write_text(json.dumps({
            'execution_id': run.id,
            'base_sha': run.base_sha,
            'candidate_sha': run.candidate_sha,
            'diff_hash': run.diff_hash,
            'target_branch': run.target_branch,
            'requested_by_id': current_user.id,
            'requested_at': datetime.utcnow().isoformat(),
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        try:
            merged_sha = merge_candidate(run.base_sha, run.candidate_sha, run.target_branch, run.diff_hash)
        except CodexExecutionError as exc:
            failed_version = claimed_version + 1
            FeedbackExecutionRun.query.filter_by(
                id=execution_id,
                status='merging',
                version=claimed_version,
            ).update({
                FeedbackExecutionRun.status: 'review_approved',
                FeedbackExecutionRun.phase: 'merge_blocked',
                FeedbackExecutionRun.error_message: str(exc)[:12000],
                FeedbackExecutionRun.version: failed_version,
                FeedbackExecutionRun.updated_at: datetime.utcnow(),
            })
            db.session.commit()
            run = FeedbackExecutionRun.query.get(execution_id)
            return jsonify({'error': str(exc), 'execution': _execution_to_dict(run)}), 409
        db.session.expire_all()
        run = FeedbackExecutionRun.query.get(execution_id)
        if run.status != 'merging' or int(run.version or 0) != claimed_version:
            return jsonify({'error': '合并完成但审计状态发生冲突，请立即人工核对 HEAD', 'execution': _execution_to_dict(run)}), 409
        run.status = 'merged'
        run.phase = 'merged_waiting_release'
        run.merged_by_id = current_user.id
        run.merged_at = datetime.utcnow()
        run.merge_note = f'fast-forward merged at {merged_sha}'
        run.error_message = ''
        run.version = int(run.version or 1) + 1
        run.updated_at = run.merged_at
        run.work_plan.status = 'verified'
        run.work_plan.execution_note = f'候选提交 {merged_sha[:12]} 已合并；尚未发布。'
        run.issue.status = 'fixed'
        run.issue.updated_at = run.merged_at
        (artifact_dir / 'merge.json').write_text(json.dumps({
            'execution_id': run.id,
            'base_sha': run.base_sha,
            'candidate_sha': run.candidate_sha,
            'merged_sha': merged_sha,
            'target_branch': run.target_branch,
            'merged_by_id': current_user.id,
            'merged_at': run.merged_at.isoformat(),
            'release_performed': False,
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        db.session.commit()
        return jsonify({
            'execution': _execution_to_dict(run),
            'work_plan': run.work_plan.to_dict(),
            'issue': run.issue.to_dict(include_user=True),
        })

    @app.route('/api/admin/feedback/sessions', methods=['GET'])
    @require_feedback_dashboard_viewer
    def admin_feedback_sessions():
        query = FeedbackSession.query
        user_id = request.args.get('user_id', type=int)
        start = _parse_feedback_datetime(request.args.get('start'))
        end_raw = str(request.args.get('end') or '').strip()
        end = _parse_feedback_datetime(end_raw)
        if user_id:
            query = query.filter(FeedbackSession.user_id == user_id)
        if start:
            query = query.filter(FeedbackSession.created_at >= start)
        if end:
            if len(end_raw) == 10:
                query = query.filter(FeedbackSession.created_at < end + timedelta(days=1))
            else:
                query = query.filter(FeedbackSession.created_at <= end)
        limit = min(max(request.args.get('limit', default=200, type=int), 1), 500)
        records = _feedback_sessions_by_latest_user_message(query, limit)
        sessions = []
        for session_record, last_user_message_at in records:
            payload = session_record.to_dict(include_user=True)
            payload['last_user_message_at'] = (
                last_user_message_at.isoformat() if last_user_message_at else None
            )
            sessions.append(payload)
        return jsonify({'sessions': sessions})

    @app.route('/api/admin/feedback/sessions/<int:session_id>/messages', methods=['GET'])
    @require_feedback_dashboard_viewer
    def admin_feedback_session_messages(session_id):
        session_record = FeedbackSession.query.get(session_id)
        if session_record is None:
            return jsonify({'error': 'Conversation not found'}), 404
        records = (
            FeedbackMessage.query
            .filter_by(session_id=session_record.id)
            .order_by(FeedbackMessage.created_at.asc(), FeedbackMessage.id.asc())
            .limit(500)
            .all()
        )
        return jsonify({
            'session': session_record.to_dict(include_user=True),
            'messages': [item.to_dict(include_debug=True) for item in records],
            'issues': [item.to_dict(include_user=True) for item in session_record.issues],
        })

    @app.route('/api/admin/users', methods=['GET'])
    @require_admin
    def list_users_for_admin():
        users = User.query.order_by(User.is_approved.asc(), User.requested_at.desc(), User.id.asc()).all()
        return jsonify({'users': [user.to_admin_dict() for user in users]})

    @app.route('/api/admin/users/<int:user_id>/approve', methods=['POST'])
    @require_admin
    def approve_user(user_id):
        user = User.query.get(user_id)
        if user is None:
            return jsonify({'error': 'User not found'}), 404
        user.is_approved = True
        user.approved_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'user': user.to_admin_dict()})

    @app.route('/api/admin/users/<int:user_id>/reject', methods=['POST'])
    @require_admin
    def reject_user(user_id):
        user = User.query.get(user_id)
        if user is None:
            return jsonify({'error': 'User not found'}), 404
        if user.id == current_user.id:
            return jsonify({'error': 'You cannot reject your own account'}), 400
        if user.is_approved:
            return jsonify({'error': 'Approved users cannot be rejected here'}), 400
        db.session.delete(user)
        db.session.commit()
        return jsonify({'message': 'User registration request rejected'})

    @app.route('/api/admin/users/<int:user_id>/admin', methods=['POST'])
    @require_admin
    def set_user_admin(user_id):
        user = User.query.get(user_id)
        if user is None:
            return jsonify({'error': 'User not found'}), 404
        payload = request.json or {}
        make_admin = bool(payload.get('is_admin'))
        if user.id == current_user.id and not make_admin:
            return jsonify({'error': 'You cannot remove your own administrator role'}), 400
        user.is_admin = make_admin
        if make_admin:
            user.is_approved = True
            user.approved_at = user.approved_at or datetime.utcnow()
        db.session.commit()
        return jsonify({'user': user.to_admin_dict()})

    @app.route('/api/admin/users/<int:user_id>/password-reset', methods=['POST'])
    @require_admin
    def admin_reset_user_password(user_id):
        user = User.query.get(user_id)
        if user is None:
            return jsonify({'error': 'User not found'}), 404
        payload = request.json or {}
        temporary_password = str(payload.get('temporary_password') or '')
        admin_message = str(payload.get('message') or '').strip()
        if len(temporary_password) < 8:
            return jsonify({'error': 'Temporary password must be at least 8 characters'}), 400

        had_pending_request = user.password_reset_status == 'pending'
        user.set_password(temporary_password)
        user.password_reset_status = 'approved'
        user.password_reset_handled_at = datetime.utcnow()
        user.password_reset_requested_at = user.password_reset_requested_at or datetime.utcnow()
        _create_system_message(
            recipient_id=user.id,
            subject='密码已重置',
            body='\n'.join([
                '管理员已处理你的密码重置申请。',
                f'临时密码：{temporary_password}',
                '请尽快登录系统，并在“设置”页面修改为自己的新密码。',
                f'管理员备注：{admin_message}' if admin_message else '',
            ]).strip(),
            category='password_reset_approved' if had_pending_request else 'password_reset_manual',
        )
        db.session.commit()
        return jsonify({'user': user.to_admin_dict(), 'message': 'Password reset completed'})

    @app.route('/api/admin/users/<int:user_id>/password-reset/reject', methods=['POST'])
    @require_admin
    def reject_user_password_reset(user_id):
        user = User.query.get(user_id)
        if user is None:
            return jsonify({'error': 'User not found'}), 404
        payload = request.json or {}
        admin_message = str(payload.get('message') or '').strip()
        user.password_reset_status = 'rejected'
        user.password_reset_handled_at = datetime.utcnow()
        _create_system_message(
            recipient_id=user.id,
            subject='密码重置申请未通过',
            body='\n'.join([
                '管理员未通过本次密码重置申请。',
                f'管理员备注：{admin_message}' if admin_message else '如有需要，请补充说明后重新提交申请。',
            ]).strip(),
            category='password_reset_rejected',
        )
        db.session.commit()
        return jsonify({'user': user.to_admin_dict(), 'message': 'Password reset rejected'})

    @app.route('/api/admin/evaluations/export', methods=['GET'])
    @require_admin
    def export_evaluations():
        dataset = str(request.args.get('dataset') or '').strip()
        rater_id_raw = request.args.get('rater_id')

        query = db.session.query(EvaluationResult, User.username).outerjoin(User, EvaluationResult.rater_id == User.id)
        if dataset:
            query = query.filter(EvaluationResult.dataset.in_(_dataset_aliases(dataset)))
        if rater_id_raw not in (None, ''):
            try:
                query = query.filter(EvaluationResult.rater_id == int(rater_id_raw))
            except (TypeError, ValueError):
                return jsonify({'error': 'Invalid rater_id'}), 400

        rows = query.order_by(
            EvaluationResult.dataset.asc(),
            EvaluationResult.case_id.asc(),
            EvaluationResult.report_version.asc(),
            EvaluationResult.rater_id.asc(),
            EvaluationResult.created_at.asc(),
        ).all()

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            'dataset',
            'case_id',
            'report_version',
            'rater_id',
            'rater_username',
            'score_coverage',
            'score_consistency',
            'score_hallucination',
            'dimension_scores_json',
            'comment',
            'created_at',
        ])
        for eval_result, username in rows:
            writer.writerow([
                eval_result.dataset,
                eval_result.case_id,
                eval_result.report_version or 'AI_V1',
                eval_result.rater_id,
                username or '',
                eval_result.score_coverage if eval_result.score_coverage is not None else '',
                eval_result.score_consistency if eval_result.score_consistency is not None else '',
                eval_result.score_hallucination if eval_result.score_hallucination is not None else '',
                json.dumps(eval_result.dimension_scores or {}, ensure_ascii=False, sort_keys=True),
                eval_result.comment or '',
                _iso_datetime(eval_result.created_at) or '',
            ])

        file_name = 'evaluation_results.csv' if not dataset else f'evaluation_results_{_canonical_dataset(dataset)}.csv'
        response = make_response(buffer.getvalue())
        response.headers['Content-Type'] = 'text/csv; charset=utf-8'
        response.headers['Content-Disposition'] = f'attachment; filename=\"{file_name}\"'
        return response

    def _evaluation_export_dimension_columns():
        return OrderedDict([
            ('structured_standardization', '1.结构化规范性'),
            ('content_completeness', '2.内容完整性'),
            ('professionalism', '3.专业性'),
            ('clarity', '4.表达清晰度'),
            ('quantitative_accuracy', '5.定量与测量准确性'),
            ('imaging_fact_accuracy', '6.影像事实准确性'),
            ('clinical_relevance', '7.临床相关性'),
            ('description_conclusion_consistency', '8.结论与描述一致性'),
            ('main_conclusion_accuracy', '9.主要结论准确性'),
            ('replaceability', '10.与原始报告一致/可替代性'),
        ])

    def _evaluation_export_column_names():
        return [
            '病例库',
            '病例序号',
            '病例ID',
            '评分人员',
            'AI版本',
            '原始报告',
            'AI报告',
            '覆盖度(兼容列)',
            '一致性(兼容列)',
            '幻觉风险(兼容列)',
            *_evaluation_export_dimension_columns().values(),
            '修改意见/备注',
            '保存时间',
        ]

    def _normalize_eval_export_cases(dataset, submitted_cases=None):
        eval_root = current_app.config['EVAL_ROOT']
        if submitted_cases:
            cases = []
            for item in submitted_cases:
                if not isinstance(item, dict):
                    continue
                case_dataset = str(item.get('dataset') or dataset or '').strip()
                case_id = str(item.get('case_id') or item.get('caseId') or item.get('id') or '').strip()
                if not case_dataset or not case_id:
                    continue
                cases.append({
                    'dataset': case_dataset,
                    'id': case_id,
                    'anon_label': item.get('anon_label') or item.get('anonLabel') or '',
                    'display_dataset': _base_dataset_name(case_dataset),
                })
            return cases
        return _list_eval_cases_payload(eval_root, dataset_filter=dataset)

    def _build_eval_export_dataframe(cases, *, effective_rater_id=None, effective_rater_name='', report_version='AI_LATEST', scored_only=False, progress_cb=None):
        dimension_columns = _evaluation_export_dimension_columns()
        rows = []
        total_cases = len(cases or [])
        for index, item in enumerate(cases or []):
            payload = _build_eval_case_export_payload(
                item.get('dataset'),
                item.get('id'),
                effective_rater_id=effective_rater_id,
                requested_report_version=report_version,
            )
            if not isinstance(payload, dict):
                if progress_cb:
                    progress_cb(index + 1, total_cases, item)
                continue

            saved = payload.get('saved_evaluation') or {}
            dimension_scores = saved.get('dimension_scores') or {}
            has_saved_content = bool(saved) and _evaluation_has_content(
                score_coverage=saved.get('score_coverage'),
                score_consistency=saved.get('score_consistency'),
                score_hallucination=saved.get('score_hallucination'),
                dimension_scores=dimension_scores,
                comment=saved.get('comment') or '',
            )
            if scored_only and not has_saved_content:
                if progress_cb:
                    progress_cb(index + 1, total_cases, item)
                continue

            rows.append(OrderedDict([
                ('病例库', payload.get('resolved_dataset') or item.get('display_dataset') or item.get('dataset') or ''),
                ('病例序号', item.get('anon_label') or item.get('report_set_order') or ''),
                ('病例ID', payload.get('id') or item.get('id') or ''),
                ('评分人员', saved.get('rater') or effective_rater_name),
                ('AI版本', ((payload.get('report_source') or {}).get('report_version') or report_version)),
                ('原始报告', payload.get('standard_report_text') or ''),
                ('AI报告', ((payload.get('report') or {}).get('text') or '')),
                ('覆盖度(兼容列)', saved.get('score_coverage')),
                ('一致性(兼容列)', saved.get('score_consistency')),
                ('幻觉风险(兼容列)', saved.get('score_hallucination')),
                *[(column_title, dimension_scores.get(column_key)) for column_key, column_title in dimension_columns.items()],
                ('修改意见/备注', saved.get('comment') or ''),
                ('保存时间', saved.get('created_at') or ''),
            ]))
            if progress_cb:
                progress_cb(index + 1, total_cases, item)

        df = pd.DataFrame(rows, columns=_evaluation_export_column_names())
        return df, {
            'requested_cases': total_cases,
            'exported_rows': len(rows),
            'skipped_rows': max(total_cases - len(rows), 0),
        }

    def _write_eval_export_workbook(df, *, dataset, target):
        sheet_name = (_canonical_dataset(dataset) or 'report_eval')[:31]
        with pd.ExcelWriter(target, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name=sheet_name)
            worksheet = writer.sheets[sheet_name]
            worksheet.freeze_panes = 'A2'
            for column_cells in worksheet.columns:
                header = str(column_cells[0].value or '')
                max_width = 16
                if header in {'原始报告', 'AI报告', '修改意见/备注'}:
                    max_width = 48
                elif header in {'病例ID', '评分人员', 'AI版本', '病例库'}:
                    max_width = 24
                worksheet.column_dimensions[column_cells[0].column_letter].width = max_width

    def _eval_export_job_payload(job):
        payload = {
            'job_id': job.get('job_id'),
            'status': job.get('status'),
            'dataset': job.get('dataset'),
            'report_version': job.get('report_version'),
            'scored_only': bool(job.get('scored_only')),
            'created_at': job.get('created_at'),
            'started_at': job.get('started_at'),
            'finished_at': job.get('finished_at'),
            'requested_cases': int(job.get('requested_cases') or 0),
            'processed_cases': int(job.get('processed_cases') or 0),
            'exported_rows': int(job.get('exported_rows') or 0),
            'error': job.get('error'),
            'file_name': job.get('file_name'),
        }
        if job.get('status') == 'completed':
            payload['download_url'] = f"/api/eval/export-jobs/{job.get('job_id')}/download"
        return payload

    def _run_eval_export_job(app_obj, job_id, *, dataset, cases, effective_rater_id, effective_rater_name, report_version, scored_only, output_path):
        with app_obj.app_context():
            with eval_export_jobs_lock:
                job = eval_export_jobs.get(job_id)
                if not job:
                    return
                job['status'] = 'running'
                job['started_at'] = _iso_utc_now()

            def _progress(processed, total, item):
                with eval_export_jobs_lock:
                    job = eval_export_jobs.get(job_id)
                    if not job:
                        return
                    job['processed_cases'] = int(processed)
                    job['requested_cases'] = int(total)
                    job['current_case_id'] = item.get('id') if isinstance(item, dict) else None

            try:
                EVAL_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
                df, summary = _build_eval_export_dataframe(
                    cases,
                    effective_rater_id=effective_rater_id,
                    effective_rater_name=effective_rater_name,
                    report_version=report_version,
                    scored_only=scored_only,
                    progress_cb=_progress,
                )
                _write_eval_export_workbook(df, dataset=dataset or (cases[0].get('dataset') if cases else ''), target=output_path)
                with eval_export_jobs_lock:
                    job = eval_export_jobs.get(job_id)
                    if not job:
                        return
                    job['status'] = 'completed'
                    job['finished_at'] = _iso_utc_now()
                    job['processed_cases'] = int(summary.get('requested_cases') or 0)
                    job['requested_cases'] = int(summary.get('requested_cases') or 0)
                    job['exported_rows'] = int(summary.get('exported_rows') or 0)
                    job['file_path'] = str(output_path)
            except Exception as exc:
                current_app.logger.exception('Evaluation export job failed: %s', exc)
                with eval_export_jobs_lock:
                    job = eval_export_jobs.get(job_id)
                    if not job:
                        return
                    job['status'] = 'failed'
                    job['finished_at'] = _iso_utc_now()
                    job['error'] = str(exc)

    @app.route('/api/eval/export', methods=['GET', 'POST'])
    @login_required
    def export_eval_cases_excel():
        payload = request.get_json(silent=True) or {}
        dataset = str(payload.get('dataset') or request.args.get('dataset') or '').strip()
        report_version = _normalize_report_version_request(
            payload.get('report_version') or request.args.get('report_version') or 'AI_LATEST',
            default='AI_LATEST',
        )
        scored_only_raw = payload.get('scored_only')
        if scored_only_raw is None:
            scored_only_raw = request.args.get('scored_only')
        scored_only = str(scored_only_raw).strip().lower() in {'1', 'true', 'yes', 'scored'} if scored_only_raw is not None else False
        submitted_cases = payload.get('cases') if isinstance(payload.get('cases'), list) else None
        cases = _normalize_eval_export_cases(dataset, submitted_cases=submitted_cases)
        effective_rater = _effective_rater_user(payload)
        effective_rater_id = int(effective_rater.id) if effective_rater is not None else None
        effective_rater_name = effective_rater.username if effective_rater is not None else ''
        df, summary = _build_eval_export_dataframe(
            cases,
            effective_rater_id=effective_rater_id,
            effective_rater_name=effective_rater_name,
            report_version=report_version,
            scored_only=scored_only,
        )

        buffer = io.BytesIO()
        _write_eval_export_workbook(df, dataset=dataset or (cases[0].get('dataset') if cases else ''), target=buffer)
        buffer.seek(0)
        file_dataset = _canonical_dataset(dataset or (cases[0].get('dataset') if cases else '')) or 'all'
        file_user = re.sub(r'[^0-9A-Za-z._-]+', '_', effective_rater_name or getattr(current_user, 'username', '') or 'user')
        file_suffix = 'scored' if scored_only else 'all'
        file_name = f'evaluation_export_{file_dataset}_{file_user}_{file_suffix}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.xlsx'
        response = send_file(
            buffer,
            as_attachment=True,
            download_name=file_name,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response.headers['X-Exported-Rows'] = str(summary.get('exported_rows') or 0)
        return response

    @app.route('/api/eval/export-jobs', methods=['POST'])
    @login_required
    def create_eval_export_job():
        payload = request.get_json(silent=True) or {}
        dataset = str(payload.get('dataset') or '').strip()
        report_version = _normalize_report_version_request(payload.get('report_version') or 'AI_LATEST', default='AI_LATEST')
        scored_only = bool(payload.get('scored_only'))
        submitted_cases = payload.get('cases') if isinstance(payload.get('cases'), list) else None
        cases = _normalize_eval_export_cases(dataset, submitted_cases=submitted_cases)
        effective_rater = _effective_rater_user(payload)
        effective_rater_id = int(effective_rater.id) if effective_rater is not None else None
        effective_rater_name = effective_rater.username if effective_rater is not None else ''
        file_dataset = _canonical_dataset(dataset or (cases[0].get('dataset') if cases else '')) or 'all'
        file_user = re.sub(r'[^0-9A-Za-z._-]+', '_', effective_rater_name or getattr(current_user, 'username', '') or 'user')
        file_suffix = 'scored' if scored_only else 'all'
        job_id = uuid.uuid4().hex
        file_name = f'evaluation_export_{file_dataset}_{file_user}_{file_suffix}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.xlsx'
        output_path = EVAL_EXPORT_DIR / f'{job_id}.xlsx'

        with eval_export_jobs_lock:
            eval_export_jobs[job_id] = {
                'job_id': job_id,
                'status': 'queued',
                'created_at': _iso_utc_now(),
                'started_at': None,
                'finished_at': None,
                'dataset': dataset,
                'report_version': report_version,
                'scored_only': scored_only,
                'requested_cases': len(cases),
                'processed_cases': 0,
                'exported_rows': 0,
                'error': None,
                'file_path': None,
                'file_name': file_name,
                'request_user_id': int(current_user.id),
            }

        Thread(
            target=_run_eval_export_job,
            args=(current_app._get_current_object(), job_id),
            kwargs={
                'dataset': dataset,
                'cases': cases,
                'effective_rater_id': effective_rater_id,
                'effective_rater_name': effective_rater_name,
                'report_version': report_version,
                'scored_only': scored_only,
                'output_path': output_path,
            },
            daemon=True,
        ).start()
        with eval_export_jobs_lock:
            return jsonify(_eval_export_job_payload(eval_export_jobs[job_id]))

    @app.route('/api/eval/export-jobs/<job_id>', methods=['GET'])
    @login_required
    def get_eval_export_job(job_id):
        with eval_export_jobs_lock:
            job = eval_export_jobs.get(job_id)
            if not job:
                return jsonify({'error': 'Export job not found'}), 404
            if int(job.get('request_user_id') or 0) != int(current_user.id):
                return jsonify({'error': 'Access denied'}), 403
            return jsonify(_eval_export_job_payload(job))

    @app.route('/api/eval/export-jobs/<job_id>/download', methods=['GET'])
    @login_required
    def download_eval_export_job(job_id):
        with eval_export_jobs_lock:
            job = eval_export_jobs.get(job_id)
            if not job:
                return jsonify({'error': 'Export job not found'}), 404
            if int(job.get('request_user_id') or 0) != int(current_user.id):
                return jsonify({'error': 'Access denied'}), 403
            if job.get('status') != 'completed' or not job.get('file_path'):
                return jsonify({'error': 'Export job is not ready'}), 409
            file_path = str(job.get('file_path'))
            file_name = str(job.get('file_name') or 'evaluation_export.xlsx')
        if not os.path.exists(file_path):
            return jsonify({'error': 'Export file not found'}), 404
        return send_file(
            file_path,
            as_attachment=True,
            download_name=file_name,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )


    @app.route('/api/admin/assignment-presets', methods=['GET'])
    @require_admin
    def list_assignment_presets():
        return jsonify({'presets': _assignment_case_library_presets()})


    @app.route('/api/admin/dataset-access', methods=['GET', 'PUT'])
    @require_admin
    def manage_dataset_access():
        if request.method == 'GET':
            return jsonify(_dataset_access_overview())

        payload = request.get_json(silent=True) or {}
        namespace = str(payload.get('namespace') or 'functional').strip()
        dataset = str(payload.get('dataset') or '').strip()
        if not dataset:
            return jsonify({'error': 'Missing dataset'}), 400
        if 'user_ids' not in payload:
            return jsonify({'error': 'Missing user_ids'}), 400
        expected_revision = str(payload.get('expected_revision') or '').strip()
        if not expected_revision:
            return jsonify({'error': 'Missing expected_revision'}), 400
        if _configured_dataset_access_definition(namespace, dataset) is None:
            return jsonify({'error': '数据集不存在或不支持整库权限'}), 404

        with dataset_access_update_lock:
            current_revision = _dataset_access_revision(namespace, dataset)
            if expected_revision != current_revision:
                return jsonify({
                    'error': '权限已被其他管理员修改，页面已过期，请刷新后重试。',
                    'current_revision': current_revision,
                }), 409
            try:
                previous_user_ids = _active_dataset_access_user_ids(namespace, dataset)
                selected_user_ids = _replace_dataset_access_grants(
                    namespace,
                    dataset,
                    payload.get('user_ids'),
                    current_user.id,
                )
                selected_user_id_set = set(selected_user_ids)
                audit_events = _append_dataset_access_audit(
                    namespace,
                    dataset,
                    added_user_ids=selected_user_id_set - previous_user_ids,
                    removed_user_ids=previous_user_ids - selected_user_id_set,
                    actor=current_user,
                    request_ip=request.remote_addr,
                )
                audit_batch_id = audit_events[0].batch_id if audit_events else None
                db.session.commit()
            except (ValueError, LookupError) as exc:
                db.session.rollback()
                return jsonify({'error': str(exc)}), 400
            except Exception:
                db.session.rollback()
                raise

            try:
                _invalidate_admin_monitor_cache()
            except Exception as exc:
                current_app.logger.warning('Failed to invalidate admin monitor cache: %s', exc)

        return jsonify({
            **_dataset_access_overview(),
            'updated': {
                'namespace': namespace,
                'dataset': dataset,
                'user_ids': selected_user_ids,
                'audit_event_count': len(audit_events),
                'audit_batch_id': audit_batch_id,
            },
        })


    @app.route('/api/admin/assignment-library-cases', methods=['GET'])
    @require_admin
    def list_assignment_library_cases():
        preset_id = str(request.args.get('preset_id') or '').strip()
        preset = _assignment_preset_by_id(preset_id)
        if preset is None:
            return jsonify({'error': '病例库不存在'}), 404
        search = str(request.args.get('search') or '').strip().casefold()
        try:
            page = max(1, int(request.args.get('page') or 1))
            page_size = min(max(10, int(request.args.get('page_size') or 50)), 200)
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid pagination'}), 400
        details = _assignment_details_for_preset(preset)
        if search:
            details = [
                item for item in details
                if any(search in alias for alias in _assignment_case_aliases(item))
            ]
        total = len(details)
        start = (page - 1) * page_size
        return jsonify({
            'preset': preset,
            'items': details[start:start + page_size],
            'total': total,
            'page': page,
            'page_size': page_size,
        })


    @app.route('/api/admin/assignment-selection/resolve', methods=['POST'])
    @require_admin
    def resolve_assignment_selection():
        payload = request.json or {}
        preset_id = str(payload.get('preset_id') or '').strip()
        preset = _assignment_preset_by_id(preset_id)
        if preset is None:
            return jsonify({'error': '病例库不存在'}), 404
        selection_mode = str(payload.get('selection_mode') or 'order').strip()
        selection = payload.get('selection')
        try:
            case_ids, case_details, warnings = _resolve_assignment_preset_selection(
                preset,
                selection,
                selection_mode,
            )
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        return jsonify({
            'preset': preset,
            'case_ids': case_ids,
            'case_details': case_details,
            'selected_count': len(case_ids),
            'warnings': warnings,
        })


    @app.route('/api/admin/assignment-presets/km-report100/add-cases', methods=['POST'])
    @require_admin
    def add_km_report100_cases():
        payload = request.json or {}
        target_count = payload.get('target_count')
        explicit_case_ids = payload.get('case_ids')
        list_path = _assignment_report100_list_path()
        if list_path is None:
            return jsonify({'error': 'CMR_ALL_REPORT100_CASE_LIST is not configured'}), 500
        current_cases = []
        if list_path.exists():
            current_cases = [
                line.strip()
                for line in list_path.read_text(encoding='utf-8', errors='ignore').splitlines()
                if line.strip()
            ]
        seen = set(current_cases)
        added = []

        requested_cases = []
        if isinstance(explicit_case_ids, list):
            requested_cases = [str(item).strip() for item in explicit_case_ids if str(item).strip()]
        elif isinstance(explicit_case_ids, str):
            requested_cases = [item.strip() for item in re.split(r'[\n,;]+', explicit_case_ids) if item.strip()]

        for case_id in requested_cases:
            if case_id and case_id not in seen:
                current_cases.append(case_id)
                seen.add(case_id)
                added.append(case_id)

        if target_count is not None:
            try:
                target_count = max(int(target_count), len(current_cases))
            except (TypeError, ValueError):
                return jsonify({'error': 'Invalid target_count'}), 400
            for row in _assignment_candidate_rows():
                case_id = row['case_id']
                if case_id in seen:
                    continue
                current_cases.append(case_id)
                seen.add(case_id)
                added.append(case_id)
                if len(current_cases) >= target_count:
                    break

        list_path.parent.mkdir(parents=True, exist_ok=True)
        list_path.write_text('\n'.join(current_cases) + ('\n' if current_cases else ''), encoding='utf-8')
        case_name_path = Path(current_app.root_path).parent / 'tmp' / 'km_replacement_strict2025_latest_correctroot_case_names.txt'
        if case_name_path.exists():
            case_name_path.write_text('\n'.join(current_cases) + ('\n' if current_cases else ''), encoding='utf-8')

        return jsonify({
            'total_count': len(current_cases),
            'added_count': len(added),
            'added_case_ids': added,
            'preset': _assignment_case_library_presets()[0] if _assignment_case_library_presets() else None,
        })

    @app.route('/api/admin/assignments', methods=['GET'])
    @require_admin
    def list_case_assignments():
        query = CaseAssignment.query.filter_by(active=True)
        namespace = request.args.get('namespace')
        dataset = request.args.get('dataset')
        case_id = request.args.get('case_id')
        raw_case_ids = request.args.get('case_ids')
        case_ids = []
        if raw_case_ids:
            case_ids = [
                item.strip()
                for item in re.split(r'[\n,，;；、]+', raw_case_ids)
                if item.strip()
            ]
        if namespace:
            query = query.filter_by(namespace=namespace)
        if dataset is not None:
            query = query.filter_by(dataset=dataset)
        if case_ids:
            case_names = [Path(item).name for item in case_ids if Path(item).name]
            case_filters = [
                CaseAssignment.case_id.in_(case_ids),
                CaseAssignment.case_id.in_(case_names),
            ]
            case_filters.extend(CaseAssignment.case_id.like(f'%/{case_name}') for case_name in case_names)
            query = query.filter(db.or_(*case_filters))
        if case_id:
            query = query.filter(CaseAssignment.case_id.ilike(f"%{case_id}%"))
        limit = max(1000, len(case_ids) * 5) if case_ids else 1000
        assignments = query.order_by(CaseAssignment.created_at.desc()).limit(limit).all()
        users = User.query.filter_by(is_approved=True).order_by(User.username.asc()).all()
        assignment_map = {}
        for item in assignments:
            assignment_map.setdefault(item.case_id, []).append(item.to_dict())
        return jsonify({
            'assignments': [item.to_dict() for item in assignments],
            'assignment_map': assignment_map,
            'users': [user.to_admin_dict() for user in users],
        })

    @app.route('/api/admin/assignments', methods=['POST'])
    @require_admin
    def create_case_assignments():
        payload = request.json or {}
        namespace = str(payload.get('namespace') or 'functional').strip()
        dataset = str(payload.get('dataset') or '').strip()
        case_id = str(payload.get('case_id') or '').strip()
        raw_case_ids = payload.get('case_ids')
        user_ids = payload.get('user_ids') or []
        distribute = bool(payload.get('distribute'))
        replace_existing = bool(payload.get('replace_existing'))
        if namespace not in {'functional', 'segmentation', 'annotation', 'experiment'}:
            return jsonify({'error': 'Invalid namespace'}), 400
        case_ids = []
        if isinstance(raw_case_ids, list):
            case_ids.extend(str(item).strip() for item in raw_case_ids)
        elif isinstance(raw_case_ids, str):
            case_ids.extend(item.strip() for item in re.split(r'[\n,，;；、]+', raw_case_ids))
        if case_id:
            case_ids.insert(0, case_id)
        case_ids = [item for item in dict.fromkeys(case_ids) if item]
        if not case_ids:
            return jsonify({'error': 'Missing case_id'}), 400
        if not isinstance(user_ids, list) or not user_ids:
            return jsonify({'error': 'Please select at least one user'}), 400

        created = []
        skipped_users = []
        target_users = []
        for user_id in user_ids:
            user = User.query.get(int(user_id))
            if user is None or not user.is_approved:
                skipped_users.append(user_id)
                continue
            target_users.append(user)
        pairs = []
        if distribute:
            for index, current_case_id in enumerate(case_ids):
                if target_users:
                    pairs.append((current_case_id, target_users[index % len(target_users)]))
        else:
            for current_case_id in case_ids:
                for user in target_users:
                    pairs.append((current_case_id, user))

        if replace_existing:
            for current_case_id in case_ids:
                for assignment in CaseAssignment.query.filter_by(
                    namespace=namespace,
                    dataset=dataset,
                    case_id=current_case_id,
                    active=True,
                ).all():
                    assignment.active = False

        for current_case_id, user in pairs:
            now = datetime.utcnow()
            assignment = CaseAssignment.query.filter_by(
                namespace=namespace,
                dataset=dataset,
                case_id=current_case_id,
                user_id=user.id,
            ).first()
            if assignment:
                assignment.active = True
                assignment.created_by_id = current_user.id
                assignment.created_at = now
            else:
                assignment = CaseAssignment(
                    namespace=namespace,
                    dataset=dataset,
                    case_id=current_case_id,
                    user_id=user.id,
                    created_by_id=current_user.id,
                    created_at=now,
                )
                db.session.add(assignment)
            created.append(assignment)
        db.session.commit()
        return jsonify({
            'assignments': [item.to_dict() for item in created],
            'created_count': len(created),
            'case_count': len(case_ids),
            'user_count': len(target_users),
            'distribute': distribute,
            'replace_existing': replace_existing,
            'skipped_users': skipped_users,
        })


    @app.route('/api/admin/assignments/clear', methods=['POST'])
    @require_admin
    def clear_case_assignments():
        payload = request.json or {}
        namespace = str(payload.get('namespace') or 'functional').strip()
        dataset = str(payload.get('dataset') or '').strip()
        raw_case_ids = payload.get('case_ids')
        if namespace not in {'functional', 'segmentation', 'annotation', 'experiment'}:
            return jsonify({'error': 'Invalid namespace'}), 400

        case_ids = []
        if isinstance(raw_case_ids, list):
            case_ids.extend(str(item).strip() for item in raw_case_ids)
        elif isinstance(raw_case_ids, str):
            case_ids.extend(item.strip() for item in re.split(r'[\n,，;；、]+', raw_case_ids))
        case_ids = [item for item in dict.fromkeys(case_ids) if item]
        if not case_ids:
            return jsonify({'error': 'Missing case_ids'}), 400

        cleared = {}
        for current_case_id in case_ids:
            case_name = Path(current_case_id).name
            query = CaseAssignment.query.filter_by(
                namespace=namespace,
                dataset=dataset,
                active=True,
            )
            query = query.filter(db.or_(
                CaseAssignment.case_id == current_case_id,
                CaseAssignment.case_id == case_name,
                CaseAssignment.case_id.like(f'%/{case_name}'),
            ))
            for assignment in query.all():
                assignment.active = False
                cleared[assignment.id] = assignment

        db.session.commit()
        return jsonify({
            'cleared_count': len(cleared),
            'case_count': len(case_ids),
            'namespace': namespace,
            'dataset': dataset,
        })


    @app.route('/api/admin/assignments/clear-user', methods=['POST'])
    @require_admin
    def clear_user_case_assignments():
        payload = request.json or {}
        namespace = str(payload.get('namespace') or 'functional').strip()
        dataset = str(payload.get('dataset') or '').strip()
        raw_case_ids = payload.get('case_ids')
        user_id = payload.get('user_id')
        if namespace not in {'functional', 'segmentation', 'annotation', 'experiment'}:
            return jsonify({'error': 'Invalid namespace'}), 400
        if not user_id:
            return jsonify({'error': 'Missing user_id'}), 400
        try:
            user = User.query.get(int(user_id))
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid user_id'}), 400
        if user is None or not user.is_approved:
            return jsonify({'error': 'User not found or not approved'}), 400

        case_ids = []
        if isinstance(raw_case_ids, list):
            case_ids.extend(str(item).strip() for item in raw_case_ids)
        elif isinstance(raw_case_ids, str):
            case_ids.extend(item.strip() for item in re.split(r'[\n,，;；、]+', raw_case_ids))
        case_ids = [item for item in dict.fromkeys(case_ids) if item]
        if not case_ids:
            return jsonify({'error': 'Missing case_ids'}), 400

        cleared = {}
        for current_case_id in case_ids:
            case_name = Path(current_case_id).name
            query = CaseAssignment.query.filter_by(
                namespace=namespace,
                dataset=dataset,
                user_id=user.id,
                active=True,
            )
            query = query.filter(db.or_(
                CaseAssignment.case_id == current_case_id,
                CaseAssignment.case_id == case_name,
                CaseAssignment.case_id.like(f'%/{case_name}'),
            ))
            for assignment in query.all():
                assignment.active = False
                cleared[assignment.id] = assignment

        db.session.commit()
        return jsonify({
            'cleared_count': len(cleared),
            'case_count': len(case_ids),
            'namespace': namespace,
            'dataset': dataset,
            'user_id': user.id,
            'username': user.username,
        })


    @app.route('/api/admin/assignments/assign-selection', methods=['POST'])
    @require_admin
    def assign_selected_cases_to_user():
        payload = request.json or {}
        namespace = str(payload.get('namespace') or 'functional').strip()
        dataset = str(payload.get('dataset') or '').strip()
        user_id = payload.get('user_id')
        ordered_case_ids = payload.get('ordered_case_ids') or []
        selection = payload.get('selection') or payload.get('case_ranges') or payload.get('case_indices')
        replace_existing = payload.get('replace_existing', True) is not False

        if namespace not in {'functional', 'segmentation', 'annotation', 'experiment'}:
            return jsonify({'error': 'Invalid namespace'}), 400
        if not user_id:
            return jsonify({'error': 'Missing user_id'}), 400
        try:
            user = User.query.get(int(user_id))
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid user_id'}), 400
        if user is None or not user.is_approved:
            return jsonify({'error': 'User not found or not approved'}), 400

        try:
            case_ids = _parse_assignment_ordered_case_selection(selection, ordered_case_ids)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

        if replace_existing:
            for current_case_id in case_ids:
                for assignment in CaseAssignment.query.filter_by(
                    namespace=namespace,
                    dataset=dataset,
                    case_id=current_case_id,
                    active=True,
                ).all():
                    assignment.active = False

        created = []
        for current_case_id in case_ids:
            now = datetime.utcnow()
            assignment = CaseAssignment.query.filter_by(
                namespace=namespace,
                dataset=dataset,
                case_id=current_case_id,
                user_id=user.id,
            ).first()
            if assignment:
                assignment.active = True
                assignment.created_by_id = current_user.id
                assignment.created_at = now
            else:
                assignment = CaseAssignment(
                    namespace=namespace,
                    dataset=dataset,
                    case_id=current_case_id,
                    user_id=user.id,
                    created_by_id=current_user.id,
                    created_at=now,
                )
                db.session.add(assignment)
            created.append(assignment)

        db.session.commit()
        return jsonify({
            'assignments': [item.to_dict() for item in created],
            'assigned_count': len(created),
            'case_ids': case_ids,
            'user_id': user.id,
            'username': user.username,
            'replace_existing': replace_existing,
        })


    @app.route('/api/admin/assignments/reassign-case', methods=['POST'])
    @require_admin
    def reassign_case_assignment():
        payload = request.json or {}
        namespace = str(payload.get('namespace') or 'functional').strip()
        dataset = str(payload.get('dataset') or '').strip()
        case_id = str(payload.get('case_id') or '').strip()
        user_id = payload.get('user_id')
        if namespace not in {'functional', 'segmentation', 'annotation', 'experiment'}:
            return jsonify({'error': 'Invalid namespace'}), 400
        if not case_id:
            return jsonify({'error': 'Missing case_id'}), 400
        if not user_id:
            return jsonify({'error': 'Missing user_id'}), 400
        user = User.query.get(int(user_id))
        if user is None or not user.is_approved:
            return jsonify({'error': 'User not found or not approved'}), 400

        existing_assignments = CaseAssignment.query.filter_by(
            namespace=namespace,
            dataset=dataset,
            case_id=case_id,
            active=True,
        ).all()
        for assignment in existing_assignments:
            assignment.active = False

        now = datetime.utcnow()
        assignment = CaseAssignment.query.filter_by(
            namespace=namespace,
            dataset=dataset,
            case_id=case_id,
            user_id=user.id,
        ).first()
        if assignment:
            assignment.active = True
            assignment.created_by_id = current_user.id
            assignment.created_at = now
        else:
            assignment = CaseAssignment(
                namespace=namespace,
                dataset=dataset,
                case_id=case_id,
                user_id=user.id,
                created_by_id=current_user.id,
                created_at=now,
            )
            db.session.add(assignment)
        db.session.commit()
        return jsonify({'assignment': assignment.to_dict()})

    @app.route('/api/admin/assignments/<int:assignment_id>', methods=['DELETE'])
    @require_admin
    def delete_case_assignment(assignment_id):
        assignment = CaseAssignment.query.get(assignment_id)
        if assignment is None:
            return jsonify({'error': 'Assignment not found'}), 404
        assignment.active = False
        db.session.commit()
        return jsonify({'message': 'Assignment removed'})

    @app.route('/api/admin/media-logs', methods=['GET'])
    @require_admin
    def list_media_logs():
        limit = min(int(request.args.get('limit', 100)), 500)
        logs = MediaAccessLog.query.order_by(MediaAccessLog.created_at.desc()).limit(limit).all()
        return jsonify({'logs': [item.to_dict() for item in logs]})

    @app.route('/api/admin/llm-gateway', methods=['GET', 'POST'])
    @require_admin
    def save_llm_gateway_config():
        if request.method == 'GET':
            return jsonify({'config': _llm_gateway_monitor_payload()})
        payload = request.json or {}
        current_config = _load_llm_gateway_config()
        next_config = dict(current_config)
        if 'enabled' in payload:
            next_config['enabled'] = bool(payload.get('enabled'))
        if 'api_base' in payload:
            next_config['api_base'] = str(payload.get('api_base') or '').strip()
        if 'model' in payload:
            next_config['model'] = str(payload.get('model') or DEFAULT_LLM_GATEWAY_CONFIG['model']).strip()
        if 'temperature' in payload:
            try:
                next_config['temperature'] = float(payload.get('temperature') or 0)
            except (TypeError, ValueError):
                next_config['temperature'] = 0
        if 'max_tokens' in payload:
            try:
                next_config['max_tokens'] = int(payload.get('max_tokens') or DEFAULT_LLM_GATEWAY_CONFIG['max_tokens'])
            except (TypeError, ValueError):
                next_config['max_tokens'] = DEFAULT_LLM_GATEWAY_CONFIG['max_tokens']
        if 'metric_definitions' in payload and isinstance(payload.get('metric_definitions'), list):
            next_config['metric_definitions'] = payload.get('metric_definitions')
        if 'prompt_system_template' in payload:
            next_config['prompt_system_template'] = str(payload.get('prompt_system_template') or '').strip()
        if 'prompt_user_template' in payload:
            next_config['prompt_user_template'] = str(payload.get('prompt_user_template') or '').strip()
        if 'prompt_extra_instructions' in payload:
            next_config['prompt_extra_instructions'] = str(payload.get('prompt_extra_instructions') or '').strip()
        api_key = payload.get('api_key')
        if api_key is not None:
            api_key_text = str(api_key).strip()
            if api_key_text:
                next_config['api_key'] = api_key_text
        saved = _save_llm_gateway_config(next_config)
        try:
            _mine_metric_suggestions(
                current_app.config.get('EVAL_ROOT'),
                configured_keys=[item['key'] for item in saved.get('metric_definitions') or []],
            )
        except Exception as exc:
            current_app.logger.warning('Failed to refresh metric suggestions after save: %s', exc)
        return jsonify({'config': _llm_gateway_monitor_payload(), 'saved': bool(saved)})

    @app.route('/api/admin/llm-gateway/models/sync', methods=['POST'])
    @require_admin
    def sync_llm_gateway_models():
        payload = request.json or {}
        current_config = _load_llm_gateway_config()
        api_base = str(payload.get('api_base') or current_config.get('api_base') or '').strip()
        try:
            cache_payload = _refresh_llm_gateway_model_cache(api_base)
            return jsonify({'models': cache_payload})
        except Exception as exc:
            return jsonify({'error': f'同步模型列表失败: {exc}'}), 502

    @app.route('/api/admin/llm-gateway/metric-suggestions/refresh', methods=['POST'])
    @require_admin
    def refresh_llm_metric_suggestions():
        current_config = _load_llm_gateway_config()
        try:
            payload = _mine_metric_suggestions(
                current_app.config.get('EVAL_ROOT'),
                configured_keys=[item['key'] for item in current_config.get('metric_definitions') or []],
            )
            return jsonify({'suggestions': payload})
        except Exception as exc:
            return jsonify({'error': f'刷新指标建议失败: {exc}'}), 500

    @app.route('/api/admin/llm-gateway/test', methods=['POST'])
    @require_admin
    def test_llm_gateway_config():
        payload = request.json or {}
        override = {}
        if 'enabled' in payload:
            override['enabled'] = bool(payload.get('enabled'))
        if 'api_base' in payload:
            override['api_base'] = str(payload.get('api_base') or '').strip() or None
        if 'api_key' in payload:
            override['api_key'] = str(payload.get('api_key') or '').strip() or None
        if 'model' in payload:
            override['model'] = str(payload.get('model') or '').strip() or None
        if 'temperature' in payload:
            override['temperature'] = payload.get('temperature')
        if 'max_tokens' in payload:
            override['max_tokens'] = payload.get('max_tokens')
        result = _run_llm_gateway_health_check(override or None, persist_result=bool(payload.get('persist')))
        return jsonify({'result': result})

    @app.route('/api/admin/monitor', methods=['GET'])
    @require_admin
    def admin_monitor():
        # Authentication has already completed. Do not retain that request's
        # connection while another monitor refresh is running.
        db.session.remove()
        with admin_monitor_refresh_lock:
            now = time.monotonic()
            cached_payload = admin_monitor_cache.get('payload')
            cache_age = now - float(admin_monitor_cache.get('generated_monotonic') or 0.0)
            if cached_payload is not None and cache_age < ADMIN_MONITOR_CACHE_TTL_SECONDS:
                return jsonify(cached_payload)

            data_root = current_app.config['DATA_ROOT']
            eval_root = current_app.config['EVAL_ROOT']
            functional_root = current_app.config['FUNCTIONAL_DATA_ROOT']
            db_path = current_app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '', 1)

            users_payload = {
                'total': User.query.count(),
                'pending': User.query.filter_by(is_approved=False).count(),
                'approved': User.query.filter_by(is_approved=True).count(),
                'admins': User.query.filter_by(is_admin=True).count(),
                'workloads': _user_workloads(),
            }
            cvi_payload = {
                'total': CviCaseCatalog.query.count(),
                'imported': CviCaseCatalog.query.filter(CviCaseCatalog.cvi_study_id.isnot(None)).count(),
                'dicom_cases': CviCaseCatalog.query.filter_by(has_dicom=True).count(),
            }
            table_counts = _database_table_counts()
            annotations_payload = _annotation_overview()
            security_payload = _security_overview()

            # The remaining work can scan large directory trees and invoke
            # nvidia-smi. Release SQLite before doing that slower I/O.
            db.session.remove()
            payload = {
                'system': _system_snapshot(),
                'users': users_payload,
                'data': {
                    'roots': [
                        {
                            'key': 'segmentation',
                            'label': '原始标注数据目录',
                            'path': data_root,
                            **_count_case_tree(data_root, mode='flat'),
                            'disk': _safe_disk_usage(data_root),
                        },
                        {
                            'key': 'functional',
                            'label': 'MRIAgent 数据目录',
                            'path': functional_root,
                            **_count_case_tree(functional_root, mode='two_level'),
                            'disk': _safe_disk_usage(functional_root),
                        },
                        {
                            'key': 'eval',
                            'label': '报告/评估输出目录',
                            'path': eval_root,
                            **_count_case_tree(eval_root, mode='two_level'),
                            'disk': _safe_disk_usage(eval_root),
                        },
                    ],
                    'cvi_catalog': cvi_payload,
                    'database': {
                        'path': db_path,
                        'size_bytes': os.path.getsize(db_path) if os.path.exists(db_path) else 0,
                        'tables': table_counts,
                    },
                    'dataset_mappings': _dataset_monitor_overview(data_root, functional_root, eval_root),
                },
                'annotations': annotations_payload,
                'security': security_payload,
                'llm_gateway': _llm_gateway_monitor_payload(),
            }
            admin_monitor_cache['generated_monotonic'] = time.monotonic()
            admin_monitor_cache['payload'] = payload
            return jsonify(payload)

    @app.route('/api/annotations/<sample_id>/<sequence>', methods=['POST'])
    def save_annotations(sample_id, sequence):
        data_root = current_app.config['DATA_ROOT']
        seq_path = os.path.join(data_root, sample_id, sequence)
        
        if not os.path.exists(seq_path):
            return jsonify({'error': 'Sequence not found'}), 404
            
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        try:
            # Save to DB
            rater_id = current_user.id if current_user.is_authenticated else None
            # Try to find existing record
            existing = SegmentationAnnotation.query.filter_by(sample_id=sample_id, sequence=sequence, rater_id=rater_id).first()
            if existing:
                existing.tool_state = data
            else:
                existing = SegmentationAnnotation(sample_id=sample_id, sequence=sequence, rater_id=rater_id, tool_state=data)
                db.session.add(existing)
            db.session.commit()
            
            # Optional: also save to file for legacy compatibility
            try:
                save_path = os.path.join(seq_path, 'annotations.json')
                with open(save_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            except Exception as e:
                # Non-critical
                current_app.logger.warning(f"File save fallback failed: {e}")
            
            return jsonify({'status': 'success', 'id': existing.id})
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500

    @app.route('/api/annotations/<sample_id>/<sequence>', methods=['GET'])
    def get_annotations(sample_id, sequence):
        data_root = current_app.config['DATA_ROOT']
        seq_path = os.path.join(data_root, sample_id, sequence)
        if not os.path.exists(seq_path):
            return jsonify({'error': 'Sequence not found'}), 404
        
        try:
            rater_id = current_user.id if current_user.is_authenticated else None
            existing = SegmentationAnnotation.query.filter_by(sample_id=sample_id, sequence=sequence, rater_id=rater_id).first()
            if existing:
                return jsonify(existing.tool_state or {})
        except Exception as e:
            current_app.logger.warning(f"DB read failed: {e}")
        
        # Fallback to file, and import to DB if present
        path = os.path.join(seq_path, 'annotations.json')
        if not os.path.exists(path):
            return jsonify({})
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Import into DB if not exists
            try:
                rater_id = current_user.id if current_user.is_authenticated else None
                rec = SegmentationAnnotation.query.filter_by(sample_id=sample_id, sequence=sequence, rater_id=rater_id).first()
                if not rec:
                    rec = SegmentationAnnotation(sample_id=sample_id, sequence=sequence, rater_id=rater_id, tool_state=data)
                    db.session.add(rec)
                    db.session.commit()
            except Exception as e:
                db.session.rollback()
                current_app.logger.warning(f"DB import failed: {e}")
            return jsonify(data)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/sam/predict', methods=['POST'])
    def sam_predict():
        data = request.json
        if not data:
            return jsonify({'error': 'No data'}), 400
            
        dataset = data.get('dataset')
        case_id = data.get('case_id')
        filename = data.get('filename')
        box = data.get('box') # [x, y, w, h] normalized 0-1
        point = data.get('point') # [x, y] normalized 0-1
        
        if not all([dataset, case_id, filename]) or (not box and not point):
            return jsonify({'error': 'Missing parameters'}), 400
            
        data_root = current_app.config['FUNCTIONAL_DATA_ROOT']
        image_path = os.path.join(data_root, dataset, case_id, filename)
        
        if not os.path.exists(image_path):
             return jsonify({'error': f'Image not found: {image_path}'}), 404
             
        try:
            # Load Image
            img_np = None
            if image_path.endswith('.dcm') or image_path.endswith('.IMA'):
                ds = pydicom.dcmread(image_path)
                pixel_array = ds.pixel_array
                if pixel_array.max() > 0:
                    pixel_array = pixel_array - pixel_array.min()
                    pixel_array = (pixel_array / pixel_array.max()) * 255.0
                img_np = pixel_array.astype(np.uint8)
            else:
                img_pil = Image.open(image_path).convert('L')
                img_np = np.array(img_pil)

            h, w = img_np.shape[:2]
            
            # Prepare SAM inputs
            input_box = None
            input_point = None
            input_label = None

            if box:
                # Parse Box
                bx, by, bw, bh = box
                x1 = int(bx * w)
                y1 = int(by * h)
                w_px = int(bw * w)
                h_px = int(bh * h)
                
                # Clamp
                x1 = max(0, x1)
                y1 = max(0, y1)
                w_px = min(w - x1, w_px)
                h_px = min(h - y1, h_px)
                
                # SAM box format: [x1, y1, x2, y2]
                input_box = np.array([x1, y1, x1 + w_px, y1 + h_px])
            
            if point:
                px = int(point[0] * w)
                py = int(point[1] * h)
                input_point = np.array([[px, py]])
                input_label = np.array([1])

            # Real SAM Inference
            predictor = get_sam_predictor()
            if predictor:
                # SAM expects RGB
                img_rgb = cv2.cvtColor(img_np, cv2.COLOR_GRAY2RGB)
                predictor.set_image(img_rgb)
                
                masks, _, _ = predictor.predict(
                    point_coords=input_point,
                    point_labels=input_label,
                    box=input_box[None, :] if input_box is not None else None,
                    multimask_output=False,
                )
                # masks[0] is boolean, convert to 255 for visualization
                mask = masks[0].astype(np.uint8) * 255
            else:
                # Fallback to mock if SAM fails to load
                print("SAM predictor not available, using fallback")
                mask = np.zeros((h, w), dtype=np.uint8)
                
                if input_box is not None:
                    x1, y1, x2, y2 = input_box
                    w_px = x2 - x1
                    h_px = y2 - y1
                    center = (x1 + w_px // 2, y1 + h_px // 2)
                    axes = (w_px // 2, h_px // 2)
                    cv2.ellipse(mask, center, axes, 0, 0, 360, 255, -1)
                elif input_point is not None:
                     cv2.circle(mask, (input_point[0][0], input_point[0][1]), 20, 255, -1)
            
            # Convert Mask to Base64 PNG
            mask_rgba = np.zeros((h, w, 4), dtype=np.uint8)
            # Red color for mask, alpha=128
            mask_rgba[mask > 0] = [255, 0, 0, 128] 
            
            mask_img = Image.fromarray(mask_rgba)
            buff = io.BytesIO()
            mask_img.save(buff, format="PNG")
            img_str = base64.b64encode(buff.getvalue()).decode("utf-8")
            
            return jsonify({
                'status': 'success', 
                'mask': f"data:image/png;base64,{img_str}"
            })
            
        except Exception as e:
            print(f"SAM Error: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/samples', methods=['GET'])
    def get_samples():
        data_root = current_app.config['DATA_ROOT']
        try:
            samples = [d for d in os.listdir(data_root) if os.path.isdir(os.path.join(data_root, d))]
            samples.sort()
            result = []
            for s in samples:
                status = 'pending'
                status_path = os.path.join(data_root, s, 'status.json')
                if os.path.exists(status_path):
                    try:
                        with open(status_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            st = data.get('status')
                            if st in ('completed', 'in_progress', 'pending'):
                                status = st
                    except:
                        pass
                result.append({'id': s, 'status': status})
            return jsonify(result)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/samples/<sample_id>', methods=['GET'])
    def get_sample_details(sample_id):
        data_root = current_app.config['DATA_ROOT']
        sample_path = os.path.join(data_root, sample_id)
        
        if not os.path.exists(sample_path):
            return jsonify({'error': 'Sample not found'}), 404
            
        sequences = []
        for item in os.listdir(sample_path):
            item_path = os.path.join(sample_path, item)
            if os.path.isdir(item_path):
                # Count DICOMs
                dicoms = [f for f in os.listdir(item_path) if f.endswith('.dcm') or f.endswith('.IMA')]
                sequences.append({
                    'name': item,
                    'count': len(dicoms)
                })
        
        return jsonify({'id': sample_id, 'sequences': sequences})

    @app.route('/api/samples/<sample_id>/<sequence>/files', methods=['GET'])
    def get_sequence_files(sample_id, sequence):
        data_root = current_app.config['DATA_ROOT']
        seq_path = os.path.join(data_root, sample_id, sequence)
        
        if not os.path.exists(seq_path):
            return jsonify({'error': 'Sequence not found'}), 404
            
        files = [f for f in os.listdir(seq_path) if f.endswith('.dcm') or f.endswith('.IMA')]
        
        file_data = []
        for f in files:
            try:
                ds = pydicom.dcmread(os.path.join(seq_path, f), stop_before_pixels=True)
                file_data.append({
                    'filename': f,
                    'InstanceNumber': int(getattr(ds, 'InstanceNumber', 0)),
                    'SliceLocation': float(getattr(ds, 'SliceLocation', 0.0)),
                    'TriggerTime': float(getattr(ds, 'TriggerTime', 0.0)) if hasattr(ds, 'TriggerTime') else 0.0
                })
            except:
                file_data.append({'filename': f, 'InstanceNumber': 0, 'SliceLocation': 0, 'TriggerTime': 0})

        file_data.sort(key=lambda x: x['InstanceNumber'])
        return jsonify(file_data)

    @app.route('/api/samples/<sample_id>/status', methods=['POST'])
    def set_sample_status(sample_id):
        data_root = current_app.config['DATA_ROOT']
        sample_path = os.path.join(data_root, sample_id)
        if not os.path.exists(sample_path):
            return jsonify({'error': 'Sample not found'}), 404
        
        payload = request.json or {}
        status = payload.get('status')
        allowed = {'in_progress', 'completed', 'pending'}
        if status not in allowed:
            return jsonify({'error': 'Invalid status'}), 400
        
        status_path = os.path.join(sample_path, 'status.json')
        record = {
            'status': status,
            'updated_at': datetime.utcnow().isoformat() + 'Z'
        }
        try:
            # Merge with existing file if present
            if os.path.exists(status_path):
                try:
                    with open(status_path, 'r', encoding='utf-8') as f:
                        old = json.load(f)
                    old.update(record)
                    record = old
                except:
                    pass
            with open(status_path, 'w', encoding='utf-8') as f:
                json.dump(record, f, indent=2, ensure_ascii=False)
            return jsonify({'status': 'ok'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/dicom/<sample_id>/<sequence>/<filename>', methods=['GET'])
    def get_dicom(sample_id, sequence, filename):
        guard = _guard_media_access('dicom', namespace='segmentation', dataset='', case_id=sample_id, path=f'{sequence}/{filename}')
        if guard:
            return guard
        data_root = current_app.config['DATA_ROOT']
        try:
            file_path = _resolve_under(data_root, sample_id, sequence, filename)
        except ValueError:
            return jsonify({'error': 'Access denied'}), 403
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
            
        try:
            response = send_file(
                _anonymized_dicom_bytes(file_path),
                mimetype='application/dicom',
                download_name='viewer-frame.dcm',
            )
            _log_media_access('dicom', 'ok', namespace='segmentation', dataset='', case_id=sample_id, path=f'{sequence}/{filename}')
            return _secure_media_response(response, inline_filename='viewer-frame.dcm')
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/dicom/thumbnail/<sample_id>/<sequence>/<filename>', methods=['GET'])
    def get_thumbnail(sample_id, sequence, filename):
        guard = _guard_media_access('thumbnail', namespace='segmentation', dataset='', case_id=sample_id, path=f'{sequence}/{filename}')
        if guard:
            return guard
        data_root = current_app.config['DATA_ROOT']
        try:
            file_path = _resolve_under(data_root, sample_id, sequence, filename)
        except ValueError:
            return jsonify({'error': 'Access denied'}), 403
        
        try:
            ds = pydicom.dcmread(file_path)
            if 'PixelData' not in ds:
                return jsonify({'error': 'No pixel data'}), 400
            
            pixel_array = ds.pixel_array
            
            if pixel_array.max() > 0:
                pixel_array = pixel_array - pixel_array.min()
                pixel_array = (pixel_array / pixel_array.max()) * 255.0
            
            pixel_array = pixel_array.astype(np.uint8)
            img = Image.fromarray(pixel_array)
            
            _log_media_access('thumbnail', 'ok', namespace='segmentation', dataset='', case_id=sample_id, path=f'{sequence}/{filename}')
            return _watermarked_png_response(img, 'thumbnail.png')
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # ---------------------------------------------------------
    # Structure Assessment Routes
    # ---------------------------------------------------------

    @app.route('/api/structure/cases/<path:case_full_id>', methods=['GET'])
    @login_required
    def get_structure_case_detail(case_full_id):
        # Decode case full id (dataset/case_id)
        try:
            dataset, case_id = case_full_id.split('/', 1)
        except ValueError:
            return jsonify({'error': 'Invalid case ID format'}), 400
            
        user_id = _effective_rater_id()
        
        # Check if assessment exists
        assessment = _latest_assessment_for_aliases(
            StructureAssessment,
            dataset,
            case_id,
            user_id,
        )
        
        return jsonify({
            'assessment': assessment.to_dict() if assessment else None
        })

    @app.route('/api/structure/save', methods=['POST'])
    @login_required
    def save_structure_assessment():
        data = request.json
        dataset = data.get('dataset')
        case_id = data.get('case_id')
        
        if not dataset or not case_id:
            return jsonify({'error': 'Missing dataset or case_id'}), 400
            
        user_id = _effective_rater_id(data)
        
        # Check existing
        assessment = _latest_assessment_for_aliases(
            StructureAssessment,
            dataset,
            case_id,
            user_id,
        )
        
        if not assessment:
            assessment = StructureAssessment(
                dataset=dataset,
                case_id=case_id,
                rater_id=user_id
            )
            db.session.add(assessment)
            
        # Update fields
        answers = data.get('answers', {})
        
        # Helper to safely parse boolean
        def parse_bool(val):
            if val is None: return None
            if isinstance(val, bool): return val
            if isinstance(val, str):
                return val.lower() == 'true'
            return bool(val)

        # Helper to safely parse float
        def parse_float(val):
            if val in [None, '', 'null']: return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        # Helper to safely parse string and strip
        def parse_str(val):
            if val in [None, '', 'null']: return None
            return str(val).strip()

        assessment.lv_wall_thickness = parse_str(answers.get('lv_wall_thickness'))
        assessment.lv_thickened_type = parse_str(answers.get('lv_thickened_type'))
        assessment.lv_thickened_location = parse_str(answers.get('lv_thickened_location'))
        assessment.lv_thickened_max_thickness = parse_float(answers.get('lv_thickened_max_thickness'))
        assessment.lv_thinned_type = parse_str(answers.get('lv_thinned_type'))
        assessment.lv_thinned_location = parse_str(answers.get('lv_thinned_location'))
        assessment.lv_thinned_max_thickness = parse_float(answers.get('lv_thinned_max_thickness'))
        
        assessment.lv_increased_trabeculation = parse_bool(answers.get('lv_increased_trabeculation'))
        assessment.lv_outflow_obstruction = parse_bool(answers.get('lv_outflow_obstruction'))
        
        # Myocardial Motion
        assessment.lv_wall_motion = parse_str(answers.get('lv_wall_motion'))
        assessment.lv_enhanced_type = parse_str(answers.get('lv_enhanced_type'))
        assessment.lv_enhanced_location = parse_str(answers.get('lv_enhanced_location'))
        assessment.lv_reduced_type = parse_str(answers.get('lv_reduced_type'))
        assessment.lv_reduced_location = parse_str(answers.get('lv_reduced_location'))
        assessment.lv_paradoxical_location = parse_str(answers.get('lv_paradoxical_location'))
        assessment.lv_aneurysm = parse_str(answers.get('lv_aneurysm'))
        
        # Valvular
        assessment.valvular_stenosis = answers.get('valvular_stenosis') # JSON, keep as is
        assessment.mitral_regurgitation = parse_str(answers.get('mitral_regurgitation'))
        assessment.tricuspid_regurgitation = parse_str(answers.get('tricuspid_regurgitation'))
        assessment.aortic_regurgitation = parse_str(answers.get('aortic_regurgitation'))
        
        assessment.created_at = datetime.utcnow()
        
        try:
            db.session.commit()
            return jsonify({
                'status': 'success',
                'message': 'Structure assessment saved successfully',
                'id': assessment.id
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500

    # ---------------------------------------------------------
    # Evaluation Routes/ Diagnosis Scoring Routes
    # ---------------------------------------------------------


    def _configured_eval_report_case_ids(base_dataset='CMR_ALL'):
        configured = current_app.config.get('CMR_ALL_REPORT100_CASE_LIST') if base_dataset == 'CMR_ALL' else None
        if not configured:
            return None
        path = Path(str(configured)).expanduser()
        if not path.exists():
            return None
        return [line.strip() for line in path.read_text(encoding='utf-8', errors='ignore').splitlines() if line.strip()]

    EVAL_ANALYTICS_DEFAULT_RATERS = [
        'lixingxing',
        'wanglujing',
        '宋豫皎',
    ]

    EVAL_ANALYTICS_DIMENSIONS = [
        {'key': 'structured_standardization', 'title': '结构化规范性', 'short_label': '结构化'},
        {'key': 'content_completeness', 'title': '内容完整性', 'short_label': '完整性'},
        {'key': 'professionalism', 'title': '专业性', 'short_label': '专业性'},
        {'key': 'clarity', 'title': '表达清晰度', 'short_label': '清晰度'},
        {'key': 'quantitative_accuracy', 'title': '定量与测量准确性', 'short_label': '定量'},
        {'key': 'imaging_fact_accuracy', 'title': '影像事实准确性', 'short_label': '事实'},
        {'key': 'clinical_relevance', 'title': '临床相关性', 'short_label': '临床'},
        {'key': 'description_conclusion_consistency', 'title': '结论与描述一致性', 'short_label': '一致性'},
        {'key': 'main_conclusion_accuracy', 'title': '主要结论准确性', 'short_label': '主结论'},
        {'key': 'replaceability', 'title': '一致性/可替代性', 'short_label': '可替代'},
    ]

    def _parse_eval_analytics_raters():
        raw = str(request.args.get('raters') or '').strip()
        if not raw:
            return list(EVAL_ANALYTICS_DEFAULT_RATERS)
        raters = []
        for item in raw.split(','):
            username = item.strip()
            if username and username not in raters:
                raters.append(username)
        return raters or list(EVAL_ANALYTICS_DEFAULT_RATERS)

    def _eval_analytics_library_label(library):
        return {
            'CMR_ALL_150': '昆医附二院报告评分150例',
            'CMR_ALL': '昆医附二院',
            'CMR_Chendu': '成都中心',
            'CMR_SCS': '四川省人民医院',
            'CMR_YA': '延安医院',
            'ALL': '全部中心',
        }.get(str(library or '').strip().upper(), str(library or '').strip() or '全部中心')

    def _evaluation_matches_library(library, dataset, case_id, configured_case_names):
        normalized_library = str(library or 'CMR_ALL_150').strip().upper()
        base_dataset = _base_dataset_name(dataset)
        case_name = _normalized_case_id(case_id)
        if normalized_library == 'ALL':
            return True
        if normalized_library == 'CMR_ALL_150':
            return base_dataset == 'CMR_ALL' and case_name in configured_case_names
        return base_dataset == normalized_library

    def _coerce_dimension_score_value(value):
        if value in [None, '', 'null']:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return numeric if math.isfinite(numeric) else None

    def _build_eval_analytics_payload(library, requested_raters):
        configured_case_names = {
            Path(case_id).name
            for case_id in (_configured_eval_report_case_ids('CMR_ALL') or [])
        }
        library_target = len(configured_case_names) if str(library or '').strip().upper() == 'CMR_ALL_150' else None

        users = User.query.filter(User.username.in_(requested_raters)).all() if requested_raters else []
        users_by_name = {user.username: user for user in users}
        user_ids = {user.id: user.username for user in users}

        stats_by_name = {}
        for username in requested_raters:
            user = users_by_name.get(username)
            stats_by_name[username] = {
                'username': username,
                'is_admin': bool(getattr(user, 'is_admin', False)) if user else False,
                'scored_rows': 0,
                'scored_case_keys': set(),
                'overall_sum': 0.0,
                'overall_count': 0,
                'last_activity': None,
                'dimension_totals': {
                    dimension['key']: {'sum': 0.0, 'count': 0}
                    for dimension in EVAL_ANALYTICS_DIMENSIONS
                },
            }

        case_coverage = {}
        if user_ids:
            rows = EvaluationResult.query.filter(EvaluationResult.rater_id.in_(sorted(user_ids.keys()))).all()
        else:
            rows = []

        for row in rows:
            username = user_ids.get(row.rater_id)
            if not username:
                continue
            if not _evaluation_matches_library(library, row.dataset, row.case_id, configured_case_names):
                continue
            stats = stats_by_name[username]
            case_key = (_base_dataset_name(row.dataset), _normalized_case_id(row.case_id))
            stats['scored_rows'] += 1
            stats['scored_case_keys'].add(case_key)
            case_coverage.setdefault(case_key, set()).add(username)

            created_at = getattr(row, 'created_at', None)
            if created_at and (stats['last_activity'] is None or created_at > stats['last_activity']):
                stats['last_activity'] = created_at

            scores = row.dimension_scores or {}
            if isinstance(scores, str):
                try:
                    scores = json.loads(scores)
                except Exception:
                    scores = {}
            if not isinstance(scores, dict):
                scores = {}

            for dimension in EVAL_ANALYTICS_DIMENSIONS:
                value = _coerce_dimension_score_value(scores.get(dimension['key']))
                if value is None:
                    continue
                stats['dimension_totals'][dimension['key']]['sum'] += value
                stats['dimension_totals'][dimension['key']]['count'] += 1
                stats['overall_sum'] += value
                stats['overall_count'] += 1

        rater_payload = []
        latest_activity = None
        for username in requested_raters:
            stats = stats_by_name[username]
            dimension_avgs = {}
            for dimension in EVAL_ANALYTICS_DIMENSIONS:
                totals = stats['dimension_totals'][dimension['key']]
                dimension_avgs[dimension['key']] = (
                    round(totals['sum'] / totals['count'], 3)
                    if totals['count']
                    else None
                )
            overall_avg = round(stats['overall_sum'] / stats['overall_count'], 3) if stats['overall_count'] else None
            scored_cases = len(stats['scored_case_keys'])
            completion_rate = round((scored_cases / library_target) * 100, 1) if library_target else None
            if stats['last_activity'] and (latest_activity is None or stats['last_activity'] > latest_activity):
                latest_activity = stats['last_activity']
            rater_payload.append({
                'username': username,
                'is_admin': stats['is_admin'],
                'scored_rows': stats['scored_rows'],
                'scored_cases': scored_cases,
                'completion_rate': completion_rate,
                'avg_overall': overall_avg,
                'last_activity': stats['last_activity'].isoformat() if stats['last_activity'] else None,
                'dimension_avgs': dimension_avgs,
            })

        dimension_payload = []
        for dimension in EVAL_ANALYTICS_DIMENSIONS:
            user_avgs = {
                item['username']: item['dimension_avgs'].get(dimension['key'])
                for item in rater_payload
            }
            available_values = [value for value in user_avgs.values() if value is not None]
            dimension_payload.append({
                **dimension,
                'avg': round(sum(available_values) / len(available_values), 3) if available_values else None,
                'min': round(min(available_values), 3) if available_values else None,
                'max': round(max(available_values), 3) if available_values else None,
                'spread': round(max(available_values) - min(available_values), 3) if len(available_values) >= 2 else 0.0,
                'user_avgs': user_avgs,
            })

        overlap_histogram = []
        for rater_count in range(1, len(requested_raters) + 1):
            overlap_histogram.append({
                'rater_count': rater_count,
                'case_count': sum(1 for names in case_coverage.values() if len(names) == rater_count),
            })

        return {
            'library': str(library or 'CMR_ALL_150').strip() or 'CMR_ALL_150',
            'library_label': _eval_analytics_library_label(library),
            'target_case_count': library_target,
            'latest_activity': latest_activity.isoformat() if latest_activity else None,
            'rater_count': len(requested_raters),
            'union_case_count': len(case_coverage),
            'fully_scored_case_count': sum(1 for names in case_coverage.values() if len(names) == len(requested_raters)),
            'overlap_histogram': overlap_histogram,
            'dimensions': dimension_payload,
            'raters': rater_payload,
        }

    def _eval_case_folder_candidates(case_id):
        candidates = [case_id]
        name = Path(case_id).name
        if name and name not in candidates:
            candidates.append(name)
        return candidates

    def _find_eval_case_dir(eval_root, folder_list, case_id):
        for dataset in folder_list:
            dataset_path = Path(eval_root) / dataset
            if not dataset_path.is_dir():
                continue
            for candidate in _eval_case_folder_candidates(case_id):
                case_path = dataset_path / candidate
                if case_path.is_dir():
                    return dataset, candidate, str(case_path)
        return None, None, None

    def _is_configured_eval_report_case(dataset, case_id):
        configured_case_ids = _configured_eval_report_case_ids(_base_dataset_name(dataset)) or []
        case_name = Path(str(case_id or '')).name
        configured_names = {Path(item).name for item in configured_case_ids}
        return str(case_id or '') in configured_case_ids or case_name in configured_names

    def _resolve_eval_report_case_dir(eval_root, dataset, case_id):
        case_candidates = _eval_case_folder_candidates(case_id)
        dataset_candidates = _dataset_storage_candidates(dataset)
        if _is_configured_eval_report_case(dataset, case_id):
            base = _base_dataset_name(dataset)
            preferred = [f'new_{base}', base]
            dataset_candidates = preferred + [item for item in dataset_candidates if item not in preferred]
        for dataset_candidate in dataset_candidates:
            for case_candidate in case_candidates:
                case_path = Path(eval_root) / dataset_candidate / case_candidate
                if case_path.is_dir():
                    return str(case_path), dataset_candidate, case_candidate
        return os.path.join(eval_root, str(dataset or ''), case_candidates[0]), str(dataset or ''), case_candidates[0]

    def _find_agent_input_sequence_dir(wrapper_root, sequence_name):
        if not wrapper_root.exists():
            return None
        exact = wrapper_root / sequence_name
        if exact.exists():
            return exact
        candidates = sorted([item for item in wrapper_root.glob(f'{sequence_name}*') if item.is_dir()], key=lambda item: item.name.lower())
        return candidates[0] if candidates else None

    def _load_raw_agent_case_source(case_id):
        manifest_path = Path('/home/Larry/code/Ziqiu/LabelSystem/tmp/km_report150_raw_agent_cases.json')
        if not manifest_path.exists():
            return None
        try:
            items = json.loads(manifest_path.read_text(encoding='utf-8'))
        except Exception:
            return None
        case_name = Path(str(case_id or '')).name
        for item in items:
            if item.get('case') == case_name or Path(str(item.get('configured') or '')).name == case_name:
                return item
        return None

    def _find_raw_sequence_dir(raw_case_dir, sequence_name):
        raw_case_path = Path(raw_case_dir) if raw_case_dir else None
        if not raw_case_path or not raw_case_path.exists():
            return None
        exact = raw_case_path / sequence_name
        if exact.exists():
            return exact
        candidates = sorted([item for item in raw_case_path.glob(f'{sequence_name}*') if item.is_dir()], key=lambda item: item.name.lower())
        return candidates[0] if candidates else None

    def _selection_range_from_sequence_dir_name(name):
        match = re.match(r"^(?:4CH|SAX|LGE)=(\d+)-(\d+)$", str(name or '').strip(), flags=re.IGNORECASE)
        if not match:
            return None
        start = int(match.group(1))
        end = int(match.group(2))
        if start <= 0 or end < start:
            return None
        return start, end

    def _count_selected_dicom_files(sequence_path):
        if not sequence_path or not Path(sequence_path).exists():
            return 0, None, 0
        files = sorted([item for item in Path(sequence_path).rglob('*.dcm') if item.is_file()], key=lambda item: str(item).lower())
        total = len(files)
        selected_range = _selection_range_from_sequence_dir_name(Path(sequence_path).name)
        if selected_range is None:
            return total, None, total
        start, end = selected_range
        return len(files[start - 1:end]), {'start': start, 'end': end}, total

    AI_REPORT_OUTPUT_ROOT = Path('/home/Larry/code/Ziqiu/MRIAgent/src/output')
    AI_REPORT_VERSION_DIR_PATTERN = re.compile(r'^(AI_V\d+)_report150$', re.IGNORECASE)

    def _report_version_rank(version):
        match = re.fullmatch(r'AI_V(\d+)', str(version or '').strip().upper())
        return int(match.group(1)) if match else 0

    def _sort_report_versions(versions, *, reverse=False):
        normalized = {str(version).strip().upper() for version in versions if str(version or '').strip()}
        return sorted(normalized, key=_report_version_rank, reverse=reverse)

    def _normalize_report_version_request(value, *, default='AI_LATEST'):
        requested = str(value or default or '').strip().upper()
        if requested in {'LATEST', 'NEWEST', 'DEFAULT'}:
            return 'AI_LATEST'
        if re.fullmatch(r'AI_V\d+', requested):
            return requested
        return default

    def _collect_generated_report_versions(case_id, dataset='CMR_ALL'):
        versions = {}
        case_name = Path(str(case_id)).name
        if not AI_REPORT_OUTPUT_ROOT.exists():
            return versions
        for output_dir in AI_REPORT_OUTPUT_ROOT.iterdir():
            if not output_dir.is_dir():
                continue
            match = AI_REPORT_VERSION_DIR_PATTERN.fullmatch(output_dir.name)
            if not match:
                continue
            version = match.group(1).upper()
            report_path = output_dir / dataset / case_name / 'report.json'
            if report_path.exists():
                versions[version] = report_path
        return {
            version: versions[version]
            for version in _sort_report_versions(versions.keys(), reverse=True)
        }

    def _ai_v2_case_dir(case_id):
        return Path('/home/Larry/code/Ziqiu/MRIAgent/src/output/AI_V2_report150') / 'CMR_ALL' / Path(str(case_id)).name

    def _ai_v2_report_path(case_id):
        report_path = _ai_v2_case_dir(case_id) / 'report.json'
        return str(report_path) if report_path.exists() else None

    def _resolve_saved_evaluation_report_version(case_id, requested_report_version):
        requested_report_version = _normalize_report_version_request(requested_report_version, default='AI_V1')
        if requested_report_version == 'AI_LATEST':
            generated_report_versions = _collect_generated_report_versions(case_id, dataset='CMR_ALL')
            return next(iter(generated_report_versions), None) or 'AI_V1'
        return requested_report_version

    def _list_eval_cases_payload(eval_root, dataset_filter=None):
        datasets = sorted([d for d in os.listdir(eval_root) if os.path.isdir(os.path.join(eval_root, d))])
        dataset_groups = {}
        for dataset in datasets:
            base_name = dataset.replace('new_', '', 1) if dataset.startswith('new_') else dataset
            dataset_groups.setdefault(base_name, []).append(dataset)

        normalized_filter = _base_dataset_name(dataset_filter)
        cases = []
        for base_name, folder_list in dataset_groups.items():
            if normalized_filter and _base_dataset_name(base_name) != normalized_filter:
                continue

            folder_list.sort(key=lambda item: item.startswith('new_'), reverse=True)
            configured_case_ids = _configured_eval_report_case_ids(base_name)

            if configured_case_ids is not None:
                for index, configured_case_id in enumerate(configured_case_ids):
                    dataset, actual_case_id, case_path = _find_eval_case_dir(eval_root, folder_list, configured_case_id)
                    if not case_path:
                        continue
                    std_path = os.path.join(case_path, 'report.json')
                    ai_v2_path = _ai_v2_report_path(configured_case_id)
                    has_report = os.path.exists(std_path) or bool(ai_v2_path)
                    cases.append({
                        'id': actual_case_id,
                        'dataset': dataset,
                        'full_id': f"{dataset}/{actual_case_id}",
                        'has_report': has_report,
                        'display_dataset': base_name,
                        'report_set': True,
                        'report_set_order': index + 1,
                        'configured_case_id': configured_case_id,
                        'anon_label': f"病例{index + 1:03d}",
                        'has_ai_v2_report': bool(ai_v2_path),
                    })
                continue

            group_cases = {}
            for dataset in folder_list:
                dataset_path = os.path.join(eval_root, dataset)
                if not os.path.isdir(dataset_path):
                    continue
                for case in os.listdir(dataset_path):
                    if case in group_cases:
                        continue
                    case_path = os.path.join(dataset_path, case)
                    if not os.path.isdir(case_path):
                        continue
                    std_path = os.path.join(case_path, 'report.json')
                    group_cases[case] = {
                        'id': case,
                        'dataset': dataset,
                        'full_id': f"{dataset}/{case}",
                        'has_report': os.path.exists(std_path),
                        'display_dataset': base_name,
                    }
            cases.extend(group_cases.values())

        cases.sort(key=lambda item: (0 if item.get('report_set') else 1, item.get('report_set_order') or 0, item['dataset'], item['id']))
        return cases

    @app.route('/api/eval/cases', methods=['GET'])
    def get_eval_cases():
        eval_root = current_app.config['EVAL_ROOT']
        if not os.path.exists(eval_root):
            return jsonify({'error': f'Eval root not found: {eval_root}'}), 404

        try:
            cases = _list_eval_cases_payload(eval_root, dataset_filter=request.args.get('dataset'))
            return jsonify(cases)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/eval/analytics', methods=['GET'])
    @login_required
    def get_eval_analytics():
        try:
            library = request.args.get('library', 'CMR_ALL_150')
            requested_raters = _parse_eval_analytics_raters()
            payload = _build_eval_analytics_payload(library, requested_raters)
            return jsonify(payload)
        except Exception as e:
            current_app.logger.exception('Failed to build evaluation analytics payload: %s', e)
            return jsonify({'error': str(e)}), 500


    def _load_eval_case_media(eval_root, dataset, case_id, case_path):
        keyframes = {
            '4CH': {},
            'SAX': {}
        }

        keyframes_root = os.path.join(case_path, 'key_frames')
        has_overlays = False
        if os.path.exists(keyframes_root):
            for vt in ['4CH', 'SAX']:
                if os.path.exists(os.path.join(keyframes_root, vt, 'overlays')):
                    has_overlays = True
                    break

        if not has_overlays:
            for candidate in _dataset_storage_candidates(dataset):
                candidate_root = os.path.join(eval_root, candidate, case_id, 'key_frames')
                if not os.path.exists(candidate_root):
                    continue
                for vt in ['4CH', 'SAX']:
                    if os.path.exists(os.path.join(candidate_root, vt, 'overlays')):
                        keyframes_root = candidate_root
                        has_overlays = True
                        break
                if has_overlays:
                    break

        for view_type in ['4CH', 'SAX']:
            overlays_path = os.path.join(keyframes_root, view_type, 'overlays')
            if not os.path.exists(overlays_path):
                continue
            phases = [d for d in os.listdir(overlays_path) if os.path.isdir(os.path.join(overlays_path, d))]
            phases.sort()
            for phase in phases:
                phase_path = os.path.join(overlays_path, phase)
                files = [f for f in os.listdir(phase_path) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
                files.sort()
                keyframes[view_type][phase] = files

        previews = {
            '4CH': None,
            'SAX': None,
            'LGE': None,
        }
        for candidate in _dataset_storage_candidates(dataset):
            previews_root = os.path.join(eval_root, candidate, case_id, 'previews')
            if not os.path.exists(previews_root):
                continue
            for view_type, filename in [('4CH', '4CH.png'), ('SAX', 'SAX.png'), ('LGE', 'LGE.png')]:
                if previews[view_type]:
                    continue
                preview_path = os.path.join(previews_root, filename)
                if os.path.exists(preview_path):
                    previews[view_type] = filename

        return {
            'keyframes': keyframes,
            'previews': previews,
        }


    def _build_eval_case_detail_payload(dataset, case_id, *, effective_rater_id=None, include_media=False, include_quantitative=True):
        eval_root = current_app.config['EVAL_ROOT']
        case_path, resolved_dataset, resolved_case_id = _resolve_eval_report_case_dir(eval_root, dataset, case_id)
        
        if not os.path.exists(case_path):
            return jsonify({'error': 'Case not found'}), 404
            
        # Read report.json or report_pro.json.
        # For the configured CMR_ALL 150 report set, prefer freshly generated Agent output report.json.
        pro_path = os.path.join(case_path, 'report_pro.json')
        std_path = os.path.join(case_path, 'report.json')
        is_configured_report_set_case = _is_configured_eval_report_case(dataset, case_id)
        requested_report_version = _normalize_report_version_request(
            request.args.get('report_version') or request.args.get('ai_version') or 'AI_LATEST',
            default='AI_LATEST',
        )

        generated_report_versions = _collect_generated_report_versions(case_id, dataset='CMR_ALL')
        ai_v2_case_dir = _ai_v2_case_dir(case_id)
        ai_v2_path = ai_v2_case_dir / 'report.json'
        ai_v2_available = bool(ai_v2_path.exists())
        latest_generated_version = next(iter(generated_report_versions), None)

        v1_report_path = None
        if is_configured_report_set_case and os.path.exists(std_path):
            v1_report_path = std_path
        elif os.path.exists(pro_path):
            v1_report_path = pro_path
        elif os.path.exists(std_path):
            v1_report_path = std_path

        report_path = v1_report_path
        report_version = 'AI_V1'
        if requested_report_version == 'AI_LATEST':
            if latest_generated_version:
                report_version = latest_generated_version
                report_path = str(generated_report_versions[latest_generated_version])
        elif requested_report_version == 'AI_V1':
            report_version = 'AI_V1'
            report_path = v1_report_path
        elif requested_report_version in generated_report_versions:
            report_version = requested_report_version
            report_path = str(generated_report_versions[requested_report_version])
        else:
            report_version = 'AI_V1'
            report_path = v1_report_path

        available_report_versions = ['AI_V1'] if v1_report_path else []
        available_report_versions.extend(_sort_report_versions(generated_report_versions.keys()))
        if not available_report_versions:
            available_report_versions = ['AI_V1']

        latest_report_version = latest_generated_version or 'AI_V1'

        report_source = {
            'selected_report_file': os.path.basename(report_path) if report_path else None,
            'selected_report_path': report_path,
            'selected_report_mtime': datetime.fromtimestamp(os.path.getmtime(report_path)).isoformat() if report_path and os.path.exists(report_path) else None,
            'is_new_agent_report': bool(report_path and os.path.basename(report_path) == 'report.json'),
            'report_version': report_version,
            'requested_report_version': requested_report_version,
            'latest_report_version': latest_report_version,
            'available_report_versions': available_report_versions,
            'ai_v2_available': ai_v2_available,
            'ai_v2_report_path': str(ai_v2_path),
            'version_report_paths': {
                'AI_V1': v1_report_path,
                **{version: str(path) for version, path in generated_report_versions.items()},
            },
            'output_case_dir': case_path,
            'ai_v2_output_case_dir': str(ai_v2_case_dir),
            'resolved_dataset': resolved_dataset,
            'configured_report_set_case': bool(is_configured_report_set_case),
            'input_manifest_path': os.path.join(case_path, 'input_data_manifest.csv'),
            'input_manifest_exists': os.path.exists(os.path.join(case_path, 'input_data_manifest.csv')),
            'workflow_log_path': os.path.join(case_path, 'workflow.log'),
            'workflow_log_exists': os.path.exists(os.path.join(case_path, 'workflow.log')),
            'raw_sequence_paths': {},
            'manifest_summary': {},
            'warnings': [],
        }

        raw_source = _load_raw_agent_case_source(case_id)
        if raw_source:
            raw_case_dir = raw_source.get('source_case_dir') or str(Path(raw_source.get('input_root', '')) / Path(str(case_id)).name)
            report_source['agent_input_case_dir'] = raw_case_dir
            report_source['raw_agent_input_root'] = raw_source.get('input_root')
            for sequence_name in ['4CH', 'SAX', 'LGE']:
                sequence_path = _find_raw_sequence_dir(raw_case_dir, sequence_name)
                file_count, selected_range, total_count = _count_selected_dicom_files(sequence_path)
                report_source['raw_sequence_paths'][sequence_name] = {
                    'wrapper_path': None,
                    'raw_path': str(sequence_path) if sequence_path else None,
                    'dicom_count': file_count,
                    'dicom_total_count': total_count,
                    'selection_range': selected_range,
                    'exists': bool(sequence_path and sequence_path.exists()),
                    'sequence_dir_name': sequence_path.name if sequence_path else None,
                }
                if not sequence_path or file_count <= 0:
                    report_source['warnings'].append(f'{sequence_name} 原始DICOM为空或不存在')
        else:
            wrapper_root = Path('/home/Larry/code/Ziqiu/MRIAgent/data/CMR_ALL_report150_all_wrapped') / Path(str(case_id)).name
            if wrapper_root.exists():
                report_source['agent_input_case_dir'] = str(wrapper_root)
                for sequence_name in ['4CH', 'SAX', 'LGE']:
                    sequence_path = _find_agent_input_sequence_dir(wrapper_root, sequence_name)
                    file_count, selected_range, total_count = _count_selected_dicom_files(sequence_path)
                    report_source['raw_sequence_paths'][sequence_name] = {
                        'wrapper_path': str(sequence_path) if sequence_path else None,
                        'raw_path': os.path.realpath(sequence_path) if sequence_path and sequence_path.exists() else None,
                        'dicom_count': file_count,
                        'dicom_total_count': total_count,
                        'selection_range': selected_range,
                        'exists': bool(sequence_path and sequence_path.exists()),
                        'sequence_dir_name': sequence_path.name if sequence_path else None,
                    }
                    if not sequence_path or file_count <= 0:
                        report_source['warnings'].append(f'{sequence_name} 原始DICOM为空或不存在')

        selected_generated_case_dir = generated_report_versions.get(report_version)
        if selected_generated_case_dir is not None:
            selected_generated_case_dir = selected_generated_case_dir.parent
            report_source['output_case_dir'] = str(selected_generated_case_dir)
            context_path = selected_generated_case_dir / 'case_context.json'
            summary_path = selected_generated_case_dir / 'run_summary.json'
            if context_path.exists():
                report_source['case_context_path'] = str(context_path)
            if summary_path.exists():
                report_source['run_summary_path'] = str(summary_path)
            report_source['input_manifest_path'] = str(selected_generated_case_dir / 'cardiac_function_stage' / Path(str(case_id)).name / 'input_data_manifest.csv')
            report_source['input_manifest_exists'] = os.path.exists(report_source['input_manifest_path'])

        if requested_report_version not in {'AI_V1', 'AI_LATEST'} and requested_report_version not in generated_report_versions:
            report_source['warnings'].append(f'已请求 {requested_report_version}，但该病例尚未生成 {requested_report_version} report.json，当前回退显示 {report_version}')

        manifest_path = report_source['input_manifest_path']
        if os.path.exists(manifest_path):
            try:
                manifest_df = pd.read_csv(manifest_path)
                sequence_counts = manifest_df['Sequence'].value_counts().to_dict() if 'Sequence' in manifest_df.columns else {}
                patient_ids = sorted({str(item) for item in manifest_df.get('PatientID', pd.Series(dtype=str)).dropna().unique().tolist()})
                report_source['manifest_summary'] = {
                    'rows': int(len(manifest_df)),
                    'sequence_counts': {str(k): int(v) for k, v in sequence_counts.items()},
                    'patient_ids': patient_ids[:5],
                    'patient_id_count': len(patient_ids),
                }
                expected_patient_id = Path(str(case_id)).name
                if patient_ids and expected_patient_id not in patient_ids:
                    report_source['warnings'].append(f'input_data_manifest PatientID 与当前病例不一致: {patient_ids[:3]}')
            except Exception as exc:
                report_source['warnings'].append(f'input_data_manifest 读取失败: {exc}')

        if report_path and os.path.basename(report_path) != 'report.json':
            report_source['warnings'].append('当前显示的不是新补跑 report.json，而是历史 report_pro.json')
            
        report_data = {}
        if report_path:
            try:
                with open(report_path, 'r', encoding='utf-8') as f:
                    report_data = json.load(f)
                if isinstance(report_data, dict) and not report_data.get('text'):
                    report_text_path = os.path.join(os.path.dirname(report_path), 'report_text.md')
                    if os.path.exists(report_text_path):
                        with open(report_text_path, 'r', encoding='utf-8') as tf:
                            report_data['text'] = tf.read()
                        report_source['report_text_path'] = report_text_path
            except Exception as e:
                print(f"Error reading report: {e}")
                report_data = {"error": "Failed to read report"}
        
        # Read metrics.json (if exists)
        metrics_path = os.path.join(case_path, 'metrics.json')
        metrics_data = {}
        if os.path.exists(metrics_path):
            try:
                with open(metrics_path, 'r', encoding='utf-8') as f:
                    metrics_data = json.load(f)
            except:
                pass
        ai_metrics, ai_metric_units = _extract_ai_metrics_from_metrics_json(metrics_data)
    
        media_payload = _load_eval_case_media(eval_root, dataset, case_id, case_path) if include_media else {
            'keyframes': None,
            'previews': None,
        }
    
        # Load Standard Report Values (Gold Standard)
        standard_report_payload = _build_standard_report_payload()
        report_metrics_std = {}
        
        try:
            chart_root = '/home/Larry/code/Ziqiu/MRIAgent/case_check/results_chart'
            target_dataset = _base_dataset_name(dataset)
            
            comp_path = None
            p1 = os.path.join(chart_root, target_dataset, f"{case_id}_comparison.md")
            p2 = os.path.join(chart_root, target_dataset, f"{case_id}_comparison.txt")
            
            if os.path.exists(p1): comp_path = p1
            elif os.path.exists(p2): comp_path = p2
            
            if comp_path:
                with open(comp_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    for line in lines:
                        if '|' in line and 'AI报告值' not in line and '---' not in line:
                            parts = [p.strip() for p in line.split('|')]
                            clean_parts = [p for p in parts if p]
                            
                            if len(clean_parts) >= 4:
                                metric_name = clean_parts[1]
                                report_val_str = clean_parts[3]
                                
                                if report_val_str not in ['N/A', 'nan', '-', '']:
                                    report_metrics_std[metric_name] = report_val_str
        except Exception as e:
            print(f"Error loading standard report: {e}")
    
        # Load Diagnosis from Classification CSV
        ground_truth_diagnosis = None
        try:
            csv_path = '/home/Larry/code/Ziqiu/MRIAgent/case_check/classification_result_check/results_pro.csv'
            if os.path.exists(csv_path):
                # Read CSV
                df = pd.read_csv(csv_path)
                # Filter by dataset
                subset = df[df['Dataset'] == target_dataset].copy()
                # Match ID
                # ID in CSV might be int or string, convert to string for safe comparison
                subset['ID_str'] = subset['ID'].astype(str)
                
                # Check if any ID is contained in case_id
                # This is a bit inefficient if subset is large, but acceptable here
                match_row = None
                for _, row in subset.iterrows():
                    if row['ID_str'] in case_id:
                        match_row = row
                        break
                
                if match_row is not None:
                    ground_truth_diagnosis = match_row['GroundTruth']
        except Exception as e:
            print(f"Error loading classification CSV: {e}")
    
        # Construct Standard Report Text
        excel_report = build_raw_report_from_excel(dataset, case_id)
    
        if excel_report:
            standard_report_payload = {
                **excel_report,
                'markdown': excel_report.get('markdown') or '',
            }
        else:
            description_sections = []
            conclusion_sections = []
            if ground_truth_diagnosis:
                conclusion_sections.append({
                    'title': '诊断结论',
                    'text': str(ground_truth_diagnosis),
                })
    
            if report_metrics_std:
                sections = {
                    "左心室功能": ["LVEF", "LVEDV", "LVESV", "SV", "LVEDD", "IVS", "LVPW", "RWT", "SI", "LV/RV ratio"],
                    "右心室功能": ["RVEF", "RVEDV", "RVESV", "RVEDD"],
                    "心房功能": ["LAV", "RAV", "LA_SI", "LA_LR", "RA_SI", "RA_LR"]
                }
                
                for section, keys in sections.items():
                    section_lines = []
                    for key in keys:
                        if key in report_metrics_std:
                            val = report_metrics_std[key]
                            section_lines.append(f"- **{key}**: {val}")
                    
                    if section_lines:
                        description_sections.append({
                            'title': section,
                            'text': "\n".join(section_lines),
                        })
    
            if description_sections or conclusion_sections:
                standard_report_payload = _build_standard_report_payload(
                    source='generated',
                    description_sections=description_sections,
                    conclusion_sections=conclusion_sections,
                )
            else:
                standard_report_payload = _build_standard_report_payload(
                    source='generated',
                    description_sections=[],
                    conclusion_sections=[],
                    extra_sections=[{
                        'title': '状态',
                        'text': '未找到标准报告数据。',
                    }],
                )
    
        report_metrics = dict(report_metrics_std)
        standard_report_markdown = standard_report_payload.get('markdown') or ''
        ai_report_text = report_data.get('text', '') if isinstance(report_data, dict) else ''
        quantitative_accuracy = None
        if include_quantitative:
            llm_gateway = _load_llm_gateway_config()
            quantitative_trace = {}
            if llm_gateway.get('enabled'):
                try:
                    llm_report_metrics, _, llm_report_trace = _extract_quantitative_metrics_with_llm(
                        standard_report_markdown,
                        dataset=dataset,
                        case_id=case_id,
                        source_label='standard-report',
                    )
                    if llm_report_trace:
                        quantitative_trace['standard_report'] = llm_report_trace
                    if llm_report_metrics:
                        report_metrics = llm_report_metrics
                except Exception as exc:
                    current_app.logger.warning('LLM standard metric extraction failed for %s/%s: %s', dataset, case_id, exc)
                try:
                    llm_ai_metrics, llm_ai_units, llm_ai_trace = _extract_quantitative_metrics_with_llm(
                        ai_report_text,
                        dataset=dataset,
                        case_id=case_id,
                        source_label='ai-report',
                    )
                    if llm_ai_trace:
                        quantitative_trace['ai_report'] = llm_ai_trace
                    if llm_ai_metrics:
                        ai_metrics = llm_ai_metrics
                        ai_metric_units = llm_ai_units
                except Exception as exc:
                    current_app.logger.warning('LLM AI metric extraction failed for %s/%s: %s', dataset, case_id, exc)

            quantitative_accuracy = _build_quantitative_accuracy_summary(
                report_metrics,
                ai_metrics,
                ai_metric_units,
                llm_gateway.get('metric_definitions'),
                quantitative_trace,
            )

        # Get latest evaluation result from DB
        eval_result = _latest_assessment_for_aliases(
            EvaluationResult,
            dataset,
            case_id,
            effective_rater_id if effective_rater_id is not None else _effective_rater_id(),
            report_version=report_version,
        )
        saved_evaluation = eval_result.to_dict() if eval_result else None

        return {
            'id': case_id,
            'dataset': dataset,
            'resolved_dataset': resolved_dataset,
            'report': report_data,
            'report_source': report_source,
            'metrics': metrics_data,
            'keyframes': media_payload['keyframes'],
            'previews': media_payload['previews'],
            'saved_evaluation': saved_evaluation,
            'report_metrics': report_metrics,
            'ai_metrics': ai_metrics,
            'quantitative_accuracy': quantitative_accuracy,
            'standard_report_text': standard_report_payload.get('markdown') or '',
            'standard_report_sections': standard_report_payload,
        }
    
    @app.route('/api/eval/cases/<dataset>/<case_id>', methods=['GET'])
    def get_eval_case_detail(dataset, case_id):
        include_media = str(request.args.get('include_media') or '').strip().lower() in {'1', 'true', 'yes'}
        include_quantitative = str(request.args.get('include_quantitative') or '').strip().lower() in {'1', 'true', 'yes'}
        payload = _build_eval_case_detail_payload(dataset, case_id, include_media=include_media, include_quantitative=include_quantitative)
        if isinstance(payload, tuple):
            return payload
        return jsonify(payload)

    @app.route('/api/eval/cases/<dataset>/<case_id>/media', methods=['GET'])
    def get_eval_case_media(dataset, case_id):
        eval_root = current_app.config['EVAL_ROOT']
        case_path, _, _ = _resolve_eval_report_case_dir(eval_root, dataset, case_id)
        if not os.path.exists(case_path):
            return jsonify({'error': 'Case not found'}), 404
        return jsonify(_load_eval_case_media(eval_root, dataset, case_id, case_path))

    @app.route('/api/eval/cases/<dataset>/<case_id>/quantitative', methods=['GET'])
    def get_eval_case_quantitative(dataset, case_id):
        try:
            payload = _build_eval_case_detail_payload(dataset, case_id, include_media=False, include_quantitative=True)
            if isinstance(payload, tuple):
                return payload
            return jsonify({
                'id': payload.get('id'),
                'dataset': payload.get('dataset'),
                'report_metrics': payload.get('report_metrics'),
                'ai_metrics': payload.get('ai_metrics'),
                'quantitative_accuracy': payload.get('quantitative_accuracy'),
            })
        except Exception as exc:
            current_app.logger.exception('Failed to build quantitative payload for %s/%s: %s', dataset, case_id, exc)
            return jsonify({'error': f'定量对比生成失败: {exc}'}), 500

    def _build_eval_case_export_payload(dataset, case_id, *, effective_rater_id=None, requested_report_version='AI_LATEST'):
        eval_root = current_app.config['EVAL_ROOT']
        case_path, resolved_dataset, _ = _resolve_eval_report_case_dir(eval_root, dataset, case_id)
        if not os.path.exists(case_path):
            return None

        pro_path = os.path.join(case_path, 'report_pro.json')
        std_path = os.path.join(case_path, 'report.json')
        is_configured_report_set_case = _is_configured_eval_report_case(dataset, case_id)
        requested_report_version = _normalize_report_version_request(requested_report_version, default='AI_LATEST')

        generated_report_versions = _collect_generated_report_versions(case_id, dataset='CMR_ALL')
        latest_generated_version = next(iter(generated_report_versions), None)

        v1_report_path = None
        if is_configured_report_set_case and os.path.exists(std_path):
            v1_report_path = std_path
        elif os.path.exists(pro_path):
            v1_report_path = pro_path
        elif os.path.exists(std_path):
            v1_report_path = std_path

        report_path = v1_report_path
        report_version = 'AI_V1'
        if requested_report_version == 'AI_LATEST':
            if latest_generated_version:
                report_version = latest_generated_version
                report_path = str(generated_report_versions[latest_generated_version])
        elif requested_report_version == 'AI_V1':
            report_version = 'AI_V1'
            report_path = v1_report_path
        elif requested_report_version in generated_report_versions:
            report_version = requested_report_version
            report_path = str(generated_report_versions[requested_report_version])

        report_data = {}
        if report_path:
            try:
                with open(report_path, 'r', encoding='utf-8') as f:
                    report_data = json.load(f)
                if isinstance(report_data, dict) and not report_data.get('text'):
                    report_text_path = os.path.join(os.path.dirname(report_path), 'report_text.md')
                    if os.path.exists(report_text_path):
                        with open(report_text_path, 'r', encoding='utf-8') as tf:
                            report_data['text'] = tf.read()
            except Exception:
                report_data = {}

        excel_report = build_raw_report_from_excel(dataset, case_id) or {}
        eval_result = _latest_assessment_for_aliases(
            EvaluationResult,
            dataset,
            case_id,
            effective_rater_id if effective_rater_id is not None else _effective_rater_id(),
            report_version=report_version,
        )

        return {
            'id': case_id,
            'resolved_dataset': resolved_dataset,
            'report': report_data,
            'report_source': {
                'report_version': report_version,
            },
            'saved_evaluation': eval_result.to_dict() if eval_result else None,
            'standard_report_text': excel_report.get('markdown') or '',
        }

    def _run_eval_prewarm(app_obj, cases):
        with app_obj.app_context():
            with eval_prewarm_lock:
                eval_prewarm_status.update({
                    'running': True,
                    'started_at': _iso_utc_now(),
                    'finished_at': None,
                    'total': len(cases),
                    'processed': 0,
                    'cache_hits': 0,
                    'cache_misses': 0,
                    'errors': [],
                })
            for item in cases:
                dataset = str(item.get('dataset') or '').strip()
                case_id = str(item.get('case_id') or item.get('id') or '').strip()
                if not dataset or not case_id:
                    continue
                try:
                    payload = _build_eval_case_detail_payload(dataset, case_id)
                    if isinstance(payload, tuple):
                        raise RuntimeError('case detail unavailable')
                    trace = ((payload.get('quantitative_accuracy') or {}).get('trace') or {})
                    all_hit = bool(trace) and all(
                        bool(trace_item.get('cache_hit'))
                        for trace_item in trace.values()
                        if isinstance(trace_item, dict)
                    )
                    with eval_prewarm_lock:
                        eval_prewarm_status['processed'] += 1
                        if all_hit:
                            eval_prewarm_status['cache_hits'] += 1
                        else:
                            eval_prewarm_status['cache_misses'] += 1
                except Exception as exc:
                    with eval_prewarm_lock:
                        eval_prewarm_status['processed'] += 1
                        eval_prewarm_status['errors'].append({
                            'dataset': dataset,
                            'case_id': case_id,
                            'error': str(exc)[:300],
                        })
            with eval_prewarm_lock:
                eval_prewarm_status['running'] = False
                eval_prewarm_status['finished_at'] = _iso_utc_now()

    @app.route('/api/eval/prewarm', methods=['POST'])
    @login_required
    def prewarm_eval_llm_metrics():
        payload = request.get_json(silent=True) or {}
        cases = payload.get('cases') if isinstance(payload, dict) else []
        if not isinstance(cases, list) or not cases:
            return jsonify({'error': 'No cases provided'}), 400
        cases = cases[:int(payload.get('limit') or 100)]
        with eval_prewarm_lock:
            if eval_prewarm_status.get('running'):
                return jsonify({'status': 'already-running', **eval_prewarm_status})
            eval_prewarm_status.update({
                'running': True,
                'started_at': _iso_utc_now(),
                'finished_at': None,
                'total': len(cases),
                'processed': 0,
                'cache_hits': 0,
                'cache_misses': 0,
                'errors': [],
            })
        Thread(target=_run_eval_prewarm, args=(current_app._get_current_object(), cases), daemon=True).start()
        return jsonify({'status': 'started', **eval_prewarm_status})

    @app.route('/api/eval/prewarm/status', methods=['GET'])
    @login_required
    def eval_prewarm_status_view():
        with eval_prewarm_lock:
            return jsonify(dict(eval_prewarm_status))

    @app.route('/api/eval/cases/<dataset>/<case_id>/keyframes/<path:subpath>', methods=['GET'])
    def get_eval_keyframe(dataset, case_id, subpath):
        guard = _guard_media_access('eval-keyframe', namespace='functional', dataset=dataset, case_id=case_id, path=subpath)
        if guard:
            return guard
        # Serve any file under key_frames using subpath
        eval_root = current_app.config['EVAL_ROOT']
        file_path = None
        for candidate in _dataset_storage_candidates(dataset):
            try:
                candidate_path = _resolve_under(eval_root, candidate, case_id, 'key_frames', subpath)
            except ValueError:
                return jsonify({'error': 'Access denied'}), 403
            if os.path.exists(candidate_path):
                file_path = candidate_path
                break

        if not file_path or not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
            
        _log_media_access('eval-keyframe', 'ok', namespace='functional', dataset=dataset, case_id=case_id, path=subpath)
        return _watermarked_file_response(file_path, os.path.basename(file_path))

    @app.route('/api/eval/cases/<dataset>/<case_id>/previews/<path:filename>', methods=['GET'])
    def get_eval_preview(dataset, case_id, filename):
        guard = _guard_media_access('eval-preview', namespace='functional', dataset=dataset, case_id=case_id, path=filename)
        if guard:
            return guard

        eval_root = current_app.config['EVAL_ROOT']
        file_path = None
        for candidate in _dataset_storage_candidates(dataset):
            try:
                candidate_path = _resolve_under(eval_root, candidate, case_id, 'previews', filename)
            except ValueError:
                return jsonify({'error': 'Access denied'}), 403
            if os.path.exists(candidate_path):
                file_path = candidate_path
                break

        if not file_path or not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404

        _log_media_access('eval-preview', 'ok', namespace='functional', dataset=dataset, case_id=case_id, path=filename)
        return _watermarked_file_response(file_path, os.path.basename(file_path))

    @app.route('/api/eval/cases/<dataset>/<case_id>/score', methods=['POST'])
    @login_required
    def save_eval_score(dataset, case_id):
        # eval_root = current_app.config['EVAL_ROOT']
        # case_path = os.path.join(eval_root, dataset, case_id)
        
        # if not os.path.exists(case_path):
        #     return jsonify({'error': 'Case not found'}), 404
            
        data = request.json
        if not data:
             return jsonify({'error': 'No data provided'}), 400
             
        # New Likert fields
        score_coverage = data.get('score_coverage')
        score_consistency = data.get('score_consistency')
        score_hallucination = data.get('score_hallucination')
        dimension_scores = data.get('dimension_scores') or {}
        report_version = _resolve_saved_evaluation_report_version(
            case_id,
            data.get('report_version') or data.get('ai_version') or 'AI_V1',
        )
        
        comment = data.get('comment', '')
        has_dimension_scores = isinstance(dimension_scores, dict) and any(
            value not in [None, '', 0] for value in dimension_scores.values()
        )

        if has_dimension_scores:
            def _coerce_dimension_score(value):
                if value in [None, '']:
                    return None
                return int(value)

            dimension_scores = {
                str(key): _coerce_dimension_score(value)
                for key, value in dimension_scores.items()
            }

            # Keep legacy fields populated for compatibility with old exports/statistics.
            score_coverage = dimension_scores.get('content_completeness', score_coverage)
            score_consistency = dimension_scores.get('description_conclusion_consistency', score_consistency)
            score_hallucination = dimension_scores.get('imaging_fact_accuracy', score_hallucination)

        try:
            effective_rater_id = _effective_rater_id(data)
            # Check for existing evaluation result
            eval_result = _latest_assessment_for_aliases(
                EvaluationResult,
                dataset,
                case_id,
                effective_rater_id,
                report_version=report_version,
            )
            if not _evaluation_has_content(
                score_coverage=score_coverage,
                score_consistency=score_consistency,
                score_hallucination=score_hallucination,
                dimension_scores=dimension_scores,
                comment=comment,
            ):
                return jsonify({'error': 'At least one score or comment is required'}), 400

            if eval_result:
                # Update existing
                eval_result.report_version = report_version
                if score_coverage is not None: eval_result.score_coverage = int(score_coverage)
                if score_consistency is not None: eval_result.score_consistency = int(score_consistency)
                if score_hallucination is not None: eval_result.score_hallucination = int(score_hallucination)
                eval_result.dimension_scores = dimension_scores if isinstance(dimension_scores, dict) else {}
                eval_result.comment = comment
                eval_result.created_at = datetime.utcnow()
            else:
                # Create new evaluation result in DB
                eval_result = EvaluationResult(
                    dataset=dataset,
                    case_id=case_id,
                    report_version=report_version,
                    score=0.0, # Provide default for deprecated NOT NULL field
                    score_coverage=int(score_coverage) if score_coverage is not None else None,
                    score_consistency=int(score_consistency) if score_consistency is not None else None,
                    score_hallucination=int(score_hallucination) if score_hallucination is not None else None,
                    dimension_scores=dimension_scores if has_dimension_scores else {},
                    comment=comment,
                    rater_id=effective_rater_id
                )
                db.session.add(eval_result)
            
            db.session.commit()
            
            return jsonify({'status': 'success', 'id': eval_result.id, 'saved_evaluation': eval_result.to_dict()})
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500

    # ---------------------------------------------------------
    # Experiment Results Routes
    # ---------------------------------------------------------

    MAIN_RESULTS_DIR = '/home/Larry/code/Ziqiu/MRIAgent/case_check/charts/01151544/'
    ADJUSTED_RESULTS_DIR = '/home/Larry/code/Ziqiu/MRIAgent/case_check/charts/adjusted_0115/'

    @app.route('/api/experiment/results', methods=['GET'])
    def get_experiment_results():
        measurements = {}

        # Helper to check for images in a directory
        def get_images_in_dir(path, meas_name):
            types = []
            suffixes = ['BlandAltman', 'ScatterReg', 'Violin', 'Boxplot']
            for suffix in suffixes:
                filename = f"{meas_name}_{suffix}.png"
                if os.path.exists(os.path.join(path, filename)):
                    types.append(suffix)
            return types

        # Scan Main Directory
        if os.path.exists(MAIN_RESULTS_DIR):
            for item in os.listdir(MAIN_RESULTS_DIR):
                path = os.path.join(MAIN_RESULTS_DIR, item)
                if os.path.isdir(path):
                    images = get_images_in_dir(path, item)
                    if images:
                        measurements[item] = {
                            'name': item,
                            'source': 'main',
                            'images': images
                        }

        # Scan Adjusted Directory (Override)
        if os.path.exists(ADJUSTED_RESULTS_DIR):
            for item in os.listdir(ADJUSTED_RESULTS_DIR):
                path = os.path.join(ADJUSTED_RESULTS_DIR, item)
                if os.path.isdir(path):
                    images = get_images_in_dir(path, item)
                    if images:
                        measurements[item] = {
                            'name': item,
                            'source': 'adjusted',
                            'images': images
                        }

        # Convert to list and sort
        result_list = sorted(measurements.values(), key=lambda x: x['name'])
        return jsonify(result_list)

    @app.route('/api/experiment/image/<measurement>/<image_type>', methods=['GET'])
    def get_experiment_image(measurement, image_type):
        guard = _guard_media_access('experiment-image', namespace='experiment', dataset='', case_id=measurement, path=image_type)
        if guard:
            return guard
        viewer_user_id = int(current_user.id) if current_user.is_authenticated else None
        viewer_username = str(current_user.username or 'viewer') if current_user.is_authenticated else 'viewer'
        watermark_text = _watermark_text(viewer_username)
        # image_type example: 'BlandAltman'
        # Filename format: {measurement}_{image_type}.png

        filename = f"{measurement}_{image_type}.png"
        
        # Check adjusted first
        adjusted_path = os.path.join(ADJUSTED_RESULTS_DIR, measurement, filename)
        if os.path.exists(adjusted_path):
            _log_media_access('experiment-image', 'ok', namespace='experiment', dataset='', case_id=measurement, path=image_type)
            db.session.remove()
            return _watermarked_file_response(
                adjusted_path,
                filename,
                watermark_text=watermark_text,
                viewer_user_id=viewer_user_id,
            )
            
        # Check main
        main_path = os.path.join(MAIN_RESULTS_DIR, measurement, filename)
        if os.path.exists(main_path):
            _log_media_access('experiment-image', 'ok', namespace='experiment', dataset='', case_id=measurement, path=image_type)
            db.session.remove()
            return _watermarked_file_response(
                main_path,
                filename,
                watermark_text=watermark_text,
                viewer_user_id=viewer_user_id,
            )

        return jsonify({'error': 'Image not found'}), 404

    @app.route('/api/experiment/stats', methods=['GET'])
    def get_experiment_stats():
        stats_path = '/home/Larry/code/Ziqiu/MRIAgent/case_check/charts/cardiac_metrics_statistics2.xlsx'
        
        if not os.path.exists(stats_path):
            return jsonify({'error': 'Stats file not found'}), 404
            
        try:
            df = pd.read_excel(stats_path)
            # Replace NaN with None (which becomes null in JSON) or empty string
            df = df.where(pd.notnull(df), None)
            
            # Convert to list of dicts
            data = df.to_dict(orient='records')
            columns = df.columns.tolist()
            
            return jsonify({
                'columns': columns,
                'data': data
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/stats/completion', methods=['GET'])
    @login_required
    def get_completion_stats():
        func_root = current_app.config['FUNCTIONAL_DATA_ROOT']
        user_id = current_user.id
        
        # 1. Get all cases
        all_cases = []
        if os.path.exists(func_root):
            for dataset in os.listdir(func_root):
                dataset_path = os.path.join(func_root, dataset)
                if os.path.isdir(dataset_path):
                    for case in os.listdir(dataset_path):
                        case_path = os.path.join(dataset_path, case)
                        if os.path.isdir(case_path):
                            all_cases.append(f"{dataset}/{case}")
        
        # 2. Get completed cases from DB
        functional_done = {f"{a.dataset}/{a.case_id}" for a in FunctionalAssessment.query.filter_by(rater_id=user_id).all()}
        lesion_done = {f"{a.dataset}/{a.case_id}" for a in LGEAnalysis.query.filter_by(rater_id=user_id).all()}
        analysis_done = {f"{a.dataset}/{a.case_id}" for a in ImageAnalysis.query.filter_by(rater_id=user_id).all()}
        eval_done = {f"{a.dataset}/{a.case_id}" for a in EvaluationResult.query.filter_by(rater_id=user_id).all()}
        structure_done = {f"{a.dataset}/{a.case_id}" for a in StructureAssessment.query.filter_by(rater_id=user_id).all()}

        # 3. Build response
        def get_module_data(done_set):
            completed = sorted(list(done_set))
            incomplete = sorted([c for c in all_cases if c not in done_set])
            return {
                "completed": completed,
                "incomplete": incomplete,
                "total": len(all_cases),
                "completed_count": len(completed),
                "incomplete_count": len(incomplete)
            }

        return jsonify({
            "functional": get_module_data(functional_done),
            "lesion": get_module_data(lesion_done),
            "analysis": get_module_data(analysis_done),
            "evaluation": get_module_data(eval_done),
            "structure": get_module_data(structure_done)
        })

    # ---------------------------------------------------------
    # Functional Assessment Routes
    # ---------------------------------------------------------
    
    @app.route('/api/functional/cases', methods=['GET'])
    @login_required
    def get_functional_cases():
        # Use EVAL_ROOT as the source for case list
        func_root = current_app.config['EVAL_ROOT']
        if not os.path.exists(func_root):
             return jsonify({'error': 'Eval root not found'}), 404
             
        cases = []
        try:
            # Get completion status from DB
            user_id = current_user.id
            
            # Note: DB stores dataset as provided in API. 
            # If we serve 'new_CMR_ALL' as 'CMR_ALL', we need to align DB records.
            # But here we return 'dataset' as the actual folder name (e.g. 'new_CMR_ALL').
            # So DB records should match that.
            # However, if user previously labeled 'CMR_ALL/001' and now we show 'new_CMR_ALL/001',
            # the status might be lost unless we handle it.
            # For now, let's assume 'new_' is a new entry or user accepts re-labeling if ID changed.
            # OR, we can check both in DB.
            
            functional_done = {f"{a.dataset}/{a.case_id}" for a in FunctionalAssessment.query.filter_by(rater_id=user_id).all()}
            
            lge_analyses = LGEAnalysis.query.filter_by(rater_id=user_id).all()
            lesion_done = {f"{a.dataset}/{a.case_id}" for a in lge_analyses}
            
            # The dataset from DB might have 'new_' prefix, need to match full_id logic
            hidden_counts = {}
            for a in lge_analyses:
                if a.hidden_images and isinstance(a.hidden_images, list):
                    hidden_counts[f"{a.dataset}/{a.case_id}"] = len(a.hidden_images)
            
            analysis_done = {f"{a.dataset}/{a.case_id}" for a in ImageAnalysis.query.filter_by(rater_id=user_id).all()}
            eval_done = {f"{a.dataset}/{a.case_id}" for a in EvaluationResult.query.filter_by(rater_id=user_id).all()}
            structure_done = {f"{a.dataset}/{a.case_id}" for a in StructureAssessment.query.filter_by(rater_id=user_id).all()}

            # Grouping logic similar to get_eval_cases
            datasets = sorted(os.listdir(func_root))
            
            # Allowlist for datasets
            allowed_datasets = {
                'CMR_ALL', 'CMR_Chendu', 'CMR_SCS', 'CMR_YA',
                'new_CMR_ALL', 'new_CMR_Chendu', 'new_CMR_SCS', 'new_CMR_YA'
            }
            datasets = [d for d in datasets if d in allowed_datasets]
            
            dataset_groups = {}
            for d in datasets:
                base_name = d
                if base_name.startswith('new_'):
                    base_name = base_name.replace('new_', '', 1)
                if base_name not in dataset_groups:
                    dataset_groups[base_name] = []
                dataset_groups[base_name].append(d)

            for base_name, folder_list in dataset_groups.items():
                folder_list.sort(key=lambda x: x.startswith('new_'), reverse=True)
                
                group_cases = {}
                for dataset in folder_list:
                    dataset_path = os.path.join(func_root, dataset)
                    if os.path.isdir(dataset_path):
                        for case in os.listdir(dataset_path):
                            if case in group_cases: continue
                            
                            case_path = os.path.join(dataset_path, case)
                            if os.path.isdir(case_path):
                                full_id = f"{dataset}/{case}"
                                
                                # Check for report
                                pro_path = os.path.join(case_path, 'report_pro.json')
                                std_path = os.path.join(case_path, 'report.json')
                                has_report = os.path.exists(pro_path) or os.path.exists(std_path)

                                group_cases[case] = {
                                    'id': case,
                                    'dataset': dataset,
                                    'full_id': full_id,
                                    'status': {
                                        'functional': full_id in functional_done,
                                        'lge': full_id in lesion_done,
                                        'analysis': full_id in analysis_done,
                                        'evaluation': full_id in eval_done,
                                        'structure': full_id in structure_done
                                    },
                                    'hidden_count': hidden_counts.get(full_id, 0),
                                    'has_report': has_report,
                                    'display_dataset': base_name
                                }
                cases.extend(group_cases.values())
            
            cases.sort(key=lambda x: (x['dataset'], x['id']))
            return jsonify(cases)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/functional/cases/<dataset>/<case_id>', methods=['GET'])
    @login_required
    def get_functional_case_detail(dataset, case_id):
        assignment_guard = _guard_case_assignment('functional', dataset, case_id)
        if assignment_guard:
            return assignment_guard
        resolved_case_path = _resolve_assessment_case_path(dataset, case_id)
        if resolved_case_path is None:
            return jsonify({'error': '当前病例影像目录不可用，请刷新病例库或联系管理员。'}), 404
        case_path = str(resolved_case_path)
            
        # Find images
        images = {
            'SAX': [],
            '4CH': [],
            'LGE': []
        }
        
        # Metadata storage
        metadata = {
            'SAX': {'pixel_spacing': None},
            '4CH': {'pixel_spacing': None},
            'LGE': {'pixel_spacing': None}
        }
        
        # Helper to find DICOMs and filter by suffix if directory name contains "="
        def find_dicoms(path, dir_name):
            if not os.path.exists(path): return []
            files = sorted([f for f in os.listdir(path) if f.lower().endswith(('.dcm', '.ima'))])
            
            # Check for range in directory name, e.g., "LGE=13-17"
            if '=' in dir_name:
                try:
                    range_str = dir_name.split('=')[1]
                    start_idx, end_idx = map(int, range_str.split('-'))
                    # Filter files: extract numeric part from filename, e.g., IMG-0055-00013.dcm -> 13
                    filtered_files = []
                    for f in files:
                        import re
                        # Extract the last sequence of digits before the extension
                        match = re.search(r'(\d+)\.(dcm|ima)$', f, re.IGNORECASE)
                        if match:
                            file_idx = int(match.group(1))
                            if start_idx <= file_idx <= end_idx:
                                filtered_files.append(f)
                        else:
                            # If we can't parse the number, just include it to be safe
                            filtered_files.append(f)
                    return filtered_files
                except Exception as e:
                    print(f"Error parsing range from {dir_name}: {e}")
                    return files
            return files

        # Scan subdirectories
        for item in os.listdir(case_path):
            item_path = os.path.join(case_path, item)
            if os.path.isdir(item_path):
                item_upper = item.upper()
                target_key = None
                if 'SAX' in item_upper:
                    target_key = 'SAX'
                elif '4CH' in item_upper:
                    target_key = '4CH'
                elif 'LGE' in item_upper: 
                    target_key = 'LGE'
                
                if target_key:
                    files = find_dicoms(item_path, item)
                    if files:
                        # Add images
                        for f in files:
                            images[target_key].append(f"{item}/{f}")
                        
                        # Extract metadata if not already set for this key
                        if metadata[target_key]['pixel_spacing'] is None:
                            try:
                                first_file = os.path.join(item_path, files[0])
                                ds = pydicom.dcmread(first_file, stop_before_pixels=True)
                                if 'PixelSpacing' in ds:
                                    # DICOM PixelSpacing is [RowSpacing (Y), ColSpacing (X)]
                                    metadata[target_key]['pixel_spacing'] = [float(x) for x in ds.PixelSpacing]
                            except Exception as e:
                                print(f"Error reading metadata from {item}: {e}")

        # Check for saved assessment
        assessment = _latest_assessment_for_aliases(
            FunctionalAssessment,
            dataset,
            case_id,
            _effective_rater_id(),
        )
        
        saved_data = assessment.to_dict() if assessment else None

        # Load Report and AI Metrics for Quantitative Assessment
        eval_root = current_app.config.get('EVAL_ROOT', '')
        sequence_phase_labels = _build_sequence_phase_labels(case_path, dataset, case_id, images, eval_root)
        report_metrics = {}
        ai_metrics = {}
        ai_metric_units = {}
        
        if eval_root:
             # Look for report in eval_root/dataset/case_id
             # Try multiple possible paths because 'dataset' might not match folder name exactly
             # e.g. dataset='CMR_ALL' but folder is 'new_CMR_ALL'
             
             possible_paths = [
                 os.path.join(eval_root, dataset, case_id),
                 os.path.join(eval_root, f"new_{dataset}", case_id),
                 os.path.join(eval_root, dataset.replace("new_", ""), case_id)
             ]
             
             case_eval_path = None
             for p in possible_paths:
                 if os.path.exists(p):
                     case_eval_path = p
                     break
             
             if case_eval_path:
                 report_path = os.path.join(case_eval_path, 'report.json')
                 metrics_path = os.path.join(case_eval_path, 'metrics.json')
                 
                 # Debug: Print found paths
                 print(f"Loading report from: {report_path}")
                 print(f"Loading metrics from: {metrics_path}")
                 
                 if os.path.exists(report_path):
                     try:
                         with open(report_path, 'r', encoding='utf-8') as f:
                             raw_report = json.load(f)
                             text = raw_report.get('text', '')
                             if text:
                                 parser = ReportParser()
                                 report_metrics = parser.parse(text)
                     except Exception as e:
                         print(f"Error parsing report for {case_id}: {e}")
                
                 if os.path.exists(metrics_path):
                     try:
                         with open(metrics_path, 'r', encoding='utf-8') as f:
                             raw_ai = json.load(f)
                             
                             # Extract only flat metrics for frontend display
                             # Priority 1: requested_metrics (list of {name, value, unit})
                             if isinstance(raw_ai, dict) and 'requested_metrics' in raw_ai and isinstance(raw_ai['requested_metrics'], list):
                                 for m in raw_ai['requested_metrics']:
                                     if isinstance(m, dict) and 'name' in m and 'value' in m:
                                         val = m['value']
                                         # Ensure value is primitive (number or string) or null
                                         if val is not None and not isinstance(val, (dict, list)):
                                             ai_metrics[m['name']] = val
                                         if m.get('unit') is not None:
                                             ai_metric_units[m['name']] = m.get('unit')
                                             
                             # Priority 2: Flatten raw_measurements if needed (optional)
                             # For now, let's stick to requested_metrics as it aligns with report.
                             
                             # Also try to load raw measurements if requested_metrics is missing or empty
                             if not ai_metrics and 'raw_measurements' in raw_ai:
                                 # Basic flattening for common metrics if available
                                 rm = raw_ai['raw_measurements']
                                 if 'sax_metrics' in rm and 'lv' in rm['sax_metrics']:
                                     lv = rm['sax_metrics']['lv']
                                     if 'EF_percent' in lv: ai_metrics['LVEF'] = lv['EF_percent']
                                     if 'EDV_ml' in lv: ai_metrics['LVEDV'] = lv['EDV_ml']
                                     if 'ESV_ml' in lv: ai_metrics['LVESV'] = lv['ESV_ml']
                                     if 'SV_ml' in lv: ai_metrics['SV'] = lv['SV_ml']
                                 if 'sax_metrics' in rm and 'rv' in rm['sax_metrics']:
                                     rv = rm['sax_metrics']['rv']
                                     if 'EF_percent' in rv: ai_metrics['RVEF'] = rv['EF_percent']
                                     if 'EDV_ml' in rv: ai_metrics['RVEDV'] = rv['EDV_ml']
                                     if 'ESV_ml' in rv: ai_metrics['RVESV'] = rv['ESV_ml']
                                 if 'sax_metrics' in rm and 'structure' in rm['sax_metrics']:
                                     st = rm['sax_metrics']['structure']
                                     if 'ivs_thickness_mm' in st: ai_metrics['IVS'] = st['ivs_thickness_mm']
                                     if 'lvpw_thickness_mm' in st: ai_metrics['LVPW'] = st['lvpw_thickness_mm']
                                 if 'four_ch_metrics' in rm:
                                     fc = rm['four_ch_metrics']
                                     if 'LA_volume_ml' in fc: ai_metrics['LAV'] = fc['LA_volume_ml']
                                     if 'RA_volume_ml' in fc: ai_metrics['RAV'] = fc['RA_volume_ml']
                             
                     except Exception as e:
                         print(f"Error loading AI metrics: {e}")

        # ---------------------------------------------------------
        # Load AI Metrics from Comparison MD/TXT (Override)
        # ---------------------------------------------------------
        try:
            chart_root = '/home/Larry/code/Ziqiu/MRIAgent/case_check/results_chart'
            # Strip 'new_' prefix if present for dataset lookup
            target_dataset = _base_dataset_name(dataset)
            
            # Construct path
            comp_path = None
            p1 = os.path.join(chart_root, target_dataset, f"{case_id}_comparison.md")
            p2 = os.path.join(chart_root, target_dataset, f"{case_id}_comparison.txt")
            
            if os.path.exists(p1): comp_path = p1
            elif os.path.exists(p2): comp_path = p2
            
            if comp_path:
                print(f"Loading comparison metrics from: {comp_path}")
                with open(comp_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    for line in lines:
                        if '|' in line and 'AI报告值' not in line and '---' not in line:
                            parts = [p.strip() for p in line.split('|')]
                            # Expected: ['', '类别', '指标', 'AI报告值', '金标准值', '']
                            # Some lines might not have leading/trailing |, so be flexible
                            # If split by |, we expect at least 4 parts if no outer pipes, or 6 if outer pipes.
                            # Let's handle both cases by filtering empty strings
                            clean_parts = [p for p in parts if p]
                            
                            if len(clean_parts) >= 3:
                                # Assuming order: Category, Metric, AI Value, Gold Standard
                                # clean_parts[0] = Category
                                # clean_parts[1] = Metric
                                # clean_parts[2] = AI Value
                                metric_name = clean_parts[1]
                                ai_val_str = clean_parts[2]
                                
                                # Clean AI value
                                if ai_val_str in ['N/A', 'nan', '-', '']:
                                    ai_metrics[metric_name] = None
                                else:
                                    val_clean = ai_val_str.replace('mL', '').replace('mm', '').replace('%', '').strip()
                                    try:
                                        val_float = float(val_clean)
                                        ai_metrics[metric_name] = val_float
                                    except ValueError:
                                        pass
                                
                                # Clean Report value (Gold Standard) if available
                                if len(clean_parts) >= 4:
                                    report_val_str = clean_parts[3]
                                    if report_val_str in ['N/A', 'nan', '-', '']:
                                        report_metrics[metric_name] = None
                                    else:
                                        val_clean_rep = report_val_str.replace('mL', '').replace('mm', '').replace('%', '').strip()
                                        try:
                                            val_float_rep = float(val_clean_rep)
                                            report_metrics[metric_name] = val_float_rep
                                        except ValueError:
                                            pass
        except Exception as e:
            print(f"Error loading comparison MD: {e}")

        quantitative_accuracy = _build_quantitative_accuracy_summary(
            report_metrics,
            ai_metrics,
            ai_metric_units,
            _load_llm_gateway_config().get('metric_definitions'),
        )

        return jsonify({
            'id': case_id,
            'dataset': dataset,
            'images': images,
            'metadata': metadata,
            'phase_labels': sequence_phase_labels,
            'assessment': saved_data,
            'report_metrics': report_metrics,
            'ai_metrics': ai_metrics,
            'quantitative_accuracy': quantitative_accuracy
        })

    @app.route('/api/functional/images/<dataset>/<case_id>/<path:subpath>', methods=['GET'])
    def get_functional_image(dataset, case_id, subpath):
        guard = _guard_media_access('functional-image', namespace='functional', dataset=dataset, case_id=case_id, path=subpath)
        if guard:
            return guard
        case_path = _resolve_assessment_case_path(dataset, case_id)
        if case_path is None:
            return jsonify({'error': 'File not found'}), 404
        try:
            file_path = _resolve_under(str(case_path), subpath)
        except ValueError:
            return jsonify({'error': 'Access denied'}), 403

        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404

        cache_key = _functional_image_cache_key(file_path)
        cached_body = _functional_image_cache_get(cache_key)
        if cached_body is not None:
            _log_media_access('functional-image', 'ok', namespace='functional', dataset=dataset, case_id=case_id, path=subpath)
            response = _cached_png_response(cached_body, 'viewer-image.png')
            response.headers['X-LabelSystem-Image-Cache'] = 'HIT'
            return response

        try:
            ds = pydicom.dcmread(file_path)
            pixel_array = ds.pixel_array
            
            # Normalize
            if pixel_array.max() > 0:
                pixel_array = pixel_array - pixel_array.min()
                pixel_array = (pixel_array / pixel_array.max()) * 255.0
            
            pixel_array = pixel_array.astype(np.uint8)
            img = Image.fromarray(pixel_array)

            png_body = _watermarked_png_bytes(img)
            _functional_image_cache_put(cache_key, png_body)
            _log_media_access('functional-image', 'ok', namespace='functional', dataset=dataset, case_id=case_id, path=subpath)
            response = _cached_png_response(png_body, 'viewer-image.png')
            response.headers['X-LabelSystem-Image-Cache'] = 'MISS'
            return response
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/functional/cases/<dataset>/<case_id>/assessment', methods=['POST'])
    @login_required
    def save_functional_assessment(dataset, case_id):
        assignment_guard = _guard_case_assignment('functional', dataset, case_id)
        if assignment_guard:
            return assignment_guard
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400
            
        try:
            effective_rater_id = _effective_rater_id(data)
            # Check if assessment already exists for this case and user
            assessment = _latest_assessment_for_aliases(
                FunctionalAssessment,
                dataset,
                case_id,
                effective_rater_id,
            )
            
            if assessment:
                # Update existing
                assessment.created_at = datetime.utcnow() # Update timestamp
                assessment.metrics_data = data.get('metrics_data') # New JSON field
                
                # LV
                assessment.lv_lvedv_increased = data.get('lv_lvedv_increased')
                assessment.lv_lvesv_increased = data.get('lv_lvesv_increased')
                assessment.lv_lvef_decreased = data.get('lv_lvef_decreased')
                assessment.lv_sv_decreased = data.get('lv_sv_decreased')
                assessment.lv_lvedd_enlarged = data.get('lv_lvedd_enlarged')
                assessment.lv_ivs_thickened = data.get('lv_ivs_thickened')
                assessment.lv_lvpw_thickened = data.get('lv_lvpw_thickened')
                assessment.lv_rwt_increased = data.get('lv_rwt_increased')
                assessment.lv_si_increased = data.get('lv_si_increased')
                
                # RV
                assessment.rv_rvedv_increased = data.get('rv_rvedv_increased')
                assessment.rv_rvesv_increased = data.get('rv_rvesv_increased')
                assessment.rv_rvef_decreased = data.get('rv_rvef_decreased')
                assessment.rv_rvedd_enlarged = data.get('rv_rvedd_enlarged')
                assessment.rv_si_increased = data.get('rv_si_increased')
                
                # Ratio
                assessment.ratio_lvrv_increased = data.get('ratio_lvrv_increased')
                
                # Atrial
                assessment.la_lav_increased = data.get('la_lav_increased')
                assessment.ra_rav_increased = data.get('ra_rav_increased')
                assessment.la_si_increased = data.get('la_si_increased')
                assessment.ra_si_increased = data.get('ra_si_increased')
                assessment.la_lr_increased = data.get('la_lr_increased')
                assessment.ra_lr_increased = data.get('ra_lr_increased')
            else:
                # Create new
                assessment = FunctionalAssessment(
                    dataset=dataset,
                    case_id=case_id,
                    rater_id=effective_rater_id,
                    metrics_data=data.get('metrics_data'),
                    
                    # LV
                    lv_lvedv_increased=data.get('lv_lvedv_increased'),
                    lv_lvesv_increased=data.get('lv_lvesv_increased'),
                    lv_lvef_decreased=data.get('lv_lvef_decreased'),
                    lv_sv_decreased=data.get('lv_sv_decreased'),
                    lv_lvedd_enlarged=data.get('lv_lvedd_enlarged'),
                    lv_ivs_thickened=data.get('lv_ivs_thickened'),
                    lv_lvpw_thickened=data.get('lv_lvpw_thickened'),
                    lv_rwt_increased=data.get('lv_rwt_increased'),
                    lv_si_increased=data.get('lv_si_increased'),
                    
                    # RV
                    rv_rvedv_increased=data.get('rv_rvedv_increased'),
                    rv_rvesv_increased=data.get('rv_rvesv_increased'),
                    rv_rvef_decreased=data.get('rv_rvef_decreased'),
                    rv_rvedd_enlarged=data.get('rv_rvedd_enlarged'),
                    rv_si_increased=data.get('rv_si_increased'),
                    
                    # Ratio
                    ratio_lvrv_increased=data.get('ratio_lvrv_increased'),
                    
                    # Atrial
                    la_lav_increased=data.get('la_lav_increased'),
                    ra_rav_increased=data.get('ra_rav_increased'),
                    la_si_increased=data.get('la_si_increased'),
                    ra_si_increased=data.get('ra_si_increased'),
                    la_lr_increased=data.get('la_lr_increased'),
                    ra_lr_increased=data.get('ra_lr_increased')
                )
                db.session.add(assessment)
            
            db.session.commit()
            
            return jsonify({'status': 'success', 'id': assessment.id})
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500

    # ---------------------------------------------------------
    # Lesion Detection / LGE Analysis Routes
    # ---------------------------------------------------------

    @app.route('/api/lge/cases', methods=['GET'])
    def get_lge_cases():
        # Reuse functional cases as they are from the same source
        return get_functional_cases()

    @app.route('/api/lge/cases/<dataset>/<case_id>', methods=['GET'])
    def get_lge_case_detail(dataset, case_id):
        return get_lge_case_detail_impl(dataset, case_id, LGEAnalysis)

    def get_lge_case_detail_impl(dataset, case_id, model_class):
        assignment_guard = _guard_case_assignment('functional', dataset, case_id)
        if assignment_guard:
            return assignment_guard
        resolved_case_path = _resolve_assessment_case_path(dataset, case_id)
        if resolved_case_path is None:
            return jsonify({'error': '当前病例影像目录不可用，请刷新病例库或联系管理员。'}), 404
        case_path = str(resolved_case_path)
            
        # Find images - Only LGE
        images = {
            'LGE': []
        }
        
        # Helper to find DICOMs
        def find_dicoms(path, dir_name):
            if not os.path.exists(path): return []
            files = sorted([f for f in os.listdir(path) if f.lower().endswith(('.dcm', '.ima'))])
            
            if '=' in dir_name:
                try:
                    range_str = dir_name.split('=')[1]
                    start_idx, end_idx = map(int, range_str.split('-'))
                    filtered_files = []
                    for f in files:
                        import re
                        match = re.search(r'(\d+)\.(dcm|ima)$', f, re.IGNORECASE)
                        if match:
                            file_idx = int(match.group(1))
                            if start_idx <= file_idx <= end_idx:
                                filtered_files.append(f)
                        else:
                            filtered_files.append(f)
                    return filtered_files
                except Exception as e:
                    print(f"Error parsing range from {dir_name}: {e}")
                    return files
            return files

        # Scan subdirectories
        for item in os.listdir(case_path):
            item_path = os.path.join(case_path, item)
            if os.path.isdir(item_path):
                if 'LGE' in item: # Handle LGE=3-10 etc.
                    files = find_dicoms(item_path, item)
                    for f in files:
                        images['LGE'].append(f"{item}/{f}")

        # Check for saved assessment
        assessment = _latest_assessment_for_aliases(
            LGEAnalysis,
            dataset,
            case_id,
            _effective_rater_id(),
        )
        saved_data = assessment.to_dict() if assessment else None


        if assessment and assessment.hidden_images:
            images['LGE'] = [img for img in images['LGE'] if img not in assessment.hidden_images]

        return jsonify({
            'id': case_id,
            'dataset': dataset,
            'images': images,
            'assessment': saved_data
        })

    @app.route('/api/lge/cases/<dataset>/<case_id>/assessment', methods=['POST'])
    @login_required
    def save_lge_assessment(dataset, case_id):
        assignment_guard = _guard_case_assignment('functional', dataset, case_id)
        if assignment_guard:
            return assignment_guard
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400
            
        try:
            effective_rater_id = _effective_rater_id(data)
            # Check if assessment already exists
            assessment = _latest_assessment_for_aliases(
                LGEAnalysis,
                dataset,
                case_id,
                effective_rater_id,
            )
            
            if assessment:
                # Update
                assessment.created_at = datetime.utcnow()
                assessment.lv_enhancement = data.get('lv_enhancement')
                assessment.lv_enhancement_boxes = data.get('lv_enhancement_boxes', assessment.lv_enhancement_boxes)
                assessment.lv_enhancement_anterior_insertion = data.get('lv_enhancement_anterior_insertion')
                assessment.lv_enhancement_posterior_insertion = data.get('lv_enhancement_posterior_insertion')
                assessment.lv_distribution_pattern = data.get('lv_distribution_pattern')
                assessment.lv_transmurality = data.get('lv_transmurality')
                assessment.lv_mvo = data.get('lv_mvo')
                assessment.rv_enhancement = data.get('rv_enhancement')
                assessment.rv_enhancement_location = data.get('rv_enhancement_location')
                assessment.rv_enhancement_boxes = data.get('rv_enhancement_boxes', assessment.rv_enhancement_boxes)
                assessment.pericardial_enhancement = data.get('pericardial_enhancement')
                assessment.pericardial_enhancement_boxes = data.get('pericardial_enhancement_boxes', assessment.pericardial_enhancement_boxes)
                assessment.hidden_images = data.get('hidden_images', assessment.hidden_images)
            else:
                # Create new
                assessment = LGEAnalysis(
                    dataset=dataset,
                    case_id=case_id,
                    rater_id=effective_rater_id,
                    lv_enhancement=data.get('lv_enhancement'),
                    lv_enhancement_boxes=data.get('lv_enhancement_boxes', []),
                    lv_enhancement_anterior_insertion=data.get('lv_enhancement_anterior_insertion'),
                    lv_enhancement_posterior_insertion=data.get('lv_enhancement_posterior_insertion'),
                    lv_distribution_pattern=data.get('lv_distribution_pattern'),
                    lv_transmurality=data.get('lv_transmurality'),
                    lv_mvo=data.get('lv_mvo'),
                    rv_enhancement=data.get('rv_enhancement'),
                    rv_enhancement_location=data.get('rv_enhancement_location'),
                    rv_enhancement_boxes=data.get('rv_enhancement_boxes', []),
                    pericardial_enhancement=data.get('pericardial_enhancement'),
                    pericardial_enhancement_boxes=data.get('pericardial_enhancement_boxes', []),
                    hidden_images=data.get('hidden_images', [])
                )
                db.session.add(assessment)
            
            db.session.commit()
            
            return jsonify({'status': 'success', 'id': assessment.id})
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500

    # ---------------------------------------------------------
    # Image Analysis Routes
    # ---------------------------------------------------------

    @app.route('/api/analysis/cases', methods=['GET'])
    def get_analysis_cases():
        return get_functional_cases()

    @app.route('/api/analysis/cases/<dataset>/<case_id>', methods=['GET'])
    def get_analysis_case_detail(dataset, case_id):
        return get_analysis_case_detail_impl(dataset, case_id, ImageAnalysis)

    def get_analysis_case_detail_impl(dataset, case_id, model_class):
        eval_root = current_app.config.get('EVAL_ROOT', '')
        assignment_guard = _guard_case_assignment('functional', dataset, case_id)
        if assignment_guard:
            return assignment_guard
        resolved_case_path = _resolve_assessment_case_path(dataset, case_id)
        if resolved_case_path is None:
            return jsonify({'error': '当前病例影像目录不可用，请刷新病例库或联系管理员。'}), 404
        case_path = str(resolved_case_path)
            
        # Find images - LGE, SAX, 4CH
        images = {
            'LGE': [],
            'SAX': [],
            '4CH': []
        }
        
        # Helper to find DICOMs and filter by suffix if directory name contains "="
        def find_dicoms(path, dir_name):
            if not os.path.exists(path): return []
            files = sorted([f for f in os.listdir(path) if f.lower().endswith(('.dcm', '.ima'))])
            
            # Check for range in directory name, e.g., "LGE=13-17"
            if '=' in dir_name:
                try:
                    range_str = dir_name.split('=')[1]
                    start_idx, end_idx = map(int, range_str.split('-'))
                    # Filter files: extract numeric part from filename, e.g., IMG-0055-00013.dcm -> 13
                    filtered_files = []
                    for f in files:
                        import re
                        # Extract the last sequence of digits before the extension
                        match = re.search(r'(\d+)\.(dcm|ima)$', f, re.IGNORECASE)
                        if match:
                            file_idx = int(match.group(1))
                            if start_idx <= file_idx <= end_idx:
                                filtered_files.append(f)
                        else:
                            filtered_files.append(f)
                    return filtered_files
                except Exception as e:
                    print(f"Error parsing range from {dir_name}: {e}")
                    return files
            return files

        for item in os.listdir(case_path):
            item_path = os.path.join(case_path, item)
            if os.path.isdir(item_path):
                item_upper = item.upper()
                if 'LGE' in item_upper:
                    files = find_dicoms(item_path, item)
                    for f in files:
                        images['LGE'].append(f"{item}/{f}")
                elif 'SAX' in item_upper:
                    files = find_dicoms(item_path, item)
                    for f in files:
                        images['SAX'].append(f"{item}/{f}")
                elif '4CH' in item_upper:
                    files = find_dicoms(item_path, item)
                    for f in files:
                        images['4CH'].append(f"{item}/{f}")

        # Check for saved assessment
        assessment = _latest_assessment_for_aliases(
            model_class,
            dataset,
            case_id,
            _effective_rater_id(),
        )
        saved_data = assessment.to_dict() if assessment else None
        sequence_phase_labels = _build_sequence_phase_labels(case_path, dataset, case_id, images, eval_root)

        return jsonify({
            'id': case_id,
            'dataset': dataset,
            'images': images,
            'phase_labels': sequence_phase_labels,
            'assessment': saved_data
        })

    @app.route('/api/analysis/cases/<dataset>/<case_id>/assessment', methods=['POST'])
    @login_required
    def save_analysis_assessment(dataset, case_id):
        assignment_guard = _guard_case_assignment('functional', dataset, case_id)
        if assignment_guard:
            return assignment_guard
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400
            
        try:
            effective_rater_id = _effective_rater_id(data)
            assessment = _latest_assessment_for_aliases(
                ImageAnalysis,
                dataset,
                case_id,
                effective_rater_id,
            )
            
            if assessment:
                assessment.created_at = datetime.utcnow()
                assessment.overall_quality = data.get('overall_quality')
                assessment.has_artifacts = data.get('has_artifacts')
                assessment.artifact_severity = data.get('artifact_severity')
                assessment.has_banding_artifact = data.get('has_banding_artifact')
                assessment.has_motion_artifact = data.get('has_motion_artifact')
                assessment.has_aliasing_artifact = data.get('has_aliasing_artifact')
                assessment.has_susceptibility_artifact = data.get('has_susceptibility_artifact')
                assessment.artifact_boxes = data.get('artifact_boxes')
            else:
                assessment = ImageAnalysis(
                    dataset=dataset,
                    case_id=case_id,
                    rater_id=effective_rater_id,
                    overall_quality=data.get('overall_quality'),
                    has_artifacts=data.get('has_artifacts'),
                    artifact_severity=data.get('artifact_severity'),
                    has_banding_artifact=data.get('has_banding_artifact'),
                    has_motion_artifact=data.get('has_motion_artifact'),
                    has_aliasing_artifact=data.get('has_aliasing_artifact'),
                    has_susceptibility_artifact=data.get('has_susceptibility_artifact'),
                    artifact_boxes=data.get('artifact_boxes')
                )
                db.session.add(assessment)
            
            db.session.commit()
            
            return jsonify({'status': 'success', 'id': assessment.id})
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500

    # ---------------------------------------------------------
    # Other Findings Routes
    # ---------------------------------------------------------

    @app.route('/api/other-findings/cases', methods=['GET'])
    @login_required
    def get_other_findings_cases():
        func_root = current_app.config['FUNCTIONAL_DATA_ROOT']
        if not os.path.exists(func_root):
             return jsonify({'error': 'Functional data root not found'}), 404
             
        cases = []
        try:
            user_id = current_user.id
            
            # Get completion status for OtherFindings
            other_findings_done = {f"{a.dataset}/{a.case_id}" for a in OtherFindings.query.filter_by(rater_id=user_id).all()}

            for dataset in os.listdir(func_root):
                dataset_path = os.path.join(func_root, dataset)
                if os.path.isdir(dataset_path):
                    for case in os.listdir(dataset_path):
                        case_path = os.path.join(dataset_path, case)
                        if os.path.isdir(case_path):
                            full_id = f"{dataset}/{case}"
                            cases.append({
                                'id': case,
                                'dataset': dataset,
                                'full_id': full_id,
                                'status': {
                                    'other_findings': full_id in other_findings_done
                                }
                            })
            
            cases.sort(key=lambda x: (x['dataset'], x['id']))
            return jsonify(cases)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/other-findings/cases/<dataset>/<case_id>', methods=['GET'])
    @login_required
    def get_other_findings_case_detail(dataset, case_id):
        assignment_guard = _guard_case_assignment('functional', dataset, case_id)
        if assignment_guard:
            return assignment_guard
        resolved_case_path = _resolve_assessment_case_path(dataset, case_id)
        if resolved_case_path is None:
            return jsonify({'error': '当前病例影像目录不可用，请刷新病例库或联系管理员。'}), 404
        case_path = str(resolved_case_path)
            
        # Find images - All types (SAX, 4CH, LGE)
        images = {
            'SAX': [],
            '4CH': [],
            'LGE': []
        }
        
        metadata = {
            'SAX': {'pixel_spacing': None},
            '4CH': {'pixel_spacing': None},
            'LGE': {'pixel_spacing': None}
        }
        
        def find_dicoms(path, dir_name):
            if not os.path.exists(path): return []
            files = sorted([f for f in os.listdir(path) if f.lower().endswith(('.dcm', '.ima'))])
            
            if '=' in dir_name:
                try:
                    range_str = dir_name.split('=')[1]
                    start_idx, end_idx = map(int, range_str.split('-'))
                    filtered_files = []
                    for f in files:
                        import re
                        match = re.search(r'(\d+)\.(dcm|ima)$', f, re.IGNORECASE)
                        if match:
                            file_idx = int(match.group(1))
                            if start_idx <= file_idx <= end_idx:
                                filtered_files.append(f)
                        else:
                            filtered_files.append(f)
                    return filtered_files
                except Exception as e:
                    print(f"Error parsing range from {dir_name}: {e}")
                    return files
            return files

        for item in os.listdir(case_path):
            item_path = os.path.join(case_path, item)
            if os.path.isdir(item_path):
                item_upper = item.upper()
                target_key = None
                if 'SAX' in item_upper:
                    target_key = 'SAX'
                elif '4CH' in item_upper:
                    target_key = '4CH'
                elif 'LGE' in item_upper: 
                    target_key = 'LGE'
                
                if target_key:
                    files = find_dicoms(item_path, item)
                    if files:
                        for f in files:
                            images[target_key].append(f"{item}/{f}")
                        
                        if metadata[target_key]['pixel_spacing'] is None:
                            try:
                                first_file = os.path.join(item_path, files[0])
                                ds = pydicom.dcmread(first_file, stop_before_pixels=True)
                                if 'PixelSpacing' in ds:
                                    metadata[target_key]['pixel_spacing'] = [float(x) for x in ds.PixelSpacing]
                            except:
                                pass

        # Check for saved assessment
        assessment = _latest_assessment_for_aliases(
            OtherFindings,
            dataset,
            case_id,
            _effective_rater_id(),
        )
        saved_data = assessment.to_dict() if assessment else None

        return jsonify({
            'id': case_id,
            'dataset': dataset,
            'images': images,
            'metadata': metadata,
            'assessment': saved_data
        })

    @app.route('/api/other-findings/cases/<dataset>/<case_id>/assessment', methods=['POST'])
    @login_required
    def save_other_findings_assessment(dataset, case_id):
        assignment_guard = _guard_case_assignment('functional', dataset, case_id)
        if assignment_guard:
            return assignment_guard
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400
            
        def to_bool(val):
            if isinstance(val, bool):
                return val
            if isinstance(val, str):
                return val.lower() == 'true'
            return None

        try:
            effective_rater_id = _effective_rater_id(data)
            assessment = _latest_assessment_for_aliases(
                OtherFindings,
                dataset,
                case_id,
                effective_rater_id,
            )
            
            if assessment:
                assessment.created_at = datetime.utcnow()
                assessment.fat_infiltration_location = data.get('fat_infiltration_location')
                assessment.thrombus_present = to_bool(data.get('thrombus_present'))
                assessment.thrombus_location = data.get('thrombus_location')
                assessment.thrombus_size = data.get('thrombus_size')
                assessment.thrombus_mobility = data.get('thrombus_mobility')
                assessment.pericardial_effusion = data.get('pericardial_effusion')
                assessment.pleural_effusion = data.get('pleural_effusion')
                assessment.other_findings_desc = data.get('other_findings_desc')
            else:
                assessment = OtherFindings(
                    dataset=dataset,
                    case_id=case_id,
                    rater_id=effective_rater_id,
                    fat_infiltration_location=data.get('fat_infiltration_location'),
                    thrombus_present=to_bool(data.get('thrombus_present')),
                    thrombus_location=data.get('thrombus_location'),
                    thrombus_size=data.get('thrombus_size'),
                    thrombus_mobility=data.get('thrombus_mobility'),
                    pericardial_effusion=data.get('pericardial_effusion'),
                    pleural_effusion=data.get('pleural_effusion'),
                    other_findings_desc=data.get('other_findings_desc')
                )
                db.session.add(assessment)
            
            db.session.commit()
            return jsonify({'status': 'success', 'id': assessment.id})
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500

    # ---------------------------------------------------------
    # Diagnosis Pipeline Routes

    # ---------------------------------------------------------
    # Cardiac Annotation Routes
    from models import CardiacAnnotation

    @app.route('/api/cardiac_annotations/<sample_id>/<sequence>', methods=['GET'])
    @login_required
    def get_cardiac_annotation(sample_id, sequence):
        try:
            annotation = CardiacAnnotation.query.filter_by(
                sample_id=sample_id,
                sequence=sequence
            ).order_by(CardiacAnnotation.updated_at.desc()).first()
            
            if annotation:
                return jsonify({'status': 'success', 'data': annotation.to_dict()})
            else:
                return jsonify({'status': 'not_found', 'message': 'No annotation found'}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/cardiac_annotations/<sample_id>/<sequence>', methods=['POST'])
    @login_required
    def save_cardiac_annotation(sample_id, sequence):
        data = request.json
        if not data or 'annotations_data' not in data:
            return jsonify({'error': 'Invalid data'}), 400
            
        try:
            annotation = CardiacAnnotation.query.filter_by(
                sample_id=sample_id,
                sequence=sequence,
                rater_id=current_user.id
            ).first()
            
            from datetime import datetime
            if annotation:
                annotation.annotations_data = data['annotations_data']
                annotation.updated_at = datetime.utcnow()
            else:
                annotation = CardiacAnnotation(
                    sample_id=sample_id,
                    sequence=sequence,
                    rater_id=effective_rater_id,
                    annotations_data=data['annotations_data']
                )
                db.session.add(annotation)
                
            db.session.commit()
            return jsonify({'status': 'success', 'id': annotation.id})
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500
