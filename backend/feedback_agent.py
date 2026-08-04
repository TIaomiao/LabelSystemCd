from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable


PROMPT_PATH = Path(__file__).resolve().parent / 'prompts' / 'workstation_feedback_agent.md'

ALLOWED_CATEGORIES = {
    'usage_help',
    'bug',
    'feature_request',
    'data_issue',
    'ai_experience',
    'other',
}
ALLOWED_SEVERITIES = {'low', 'medium', 'high', 'critical'}
ALLOWED_CHANGE_SCOPES = {'guidance_only', 'minimal_candidate', 'needs_review', 'large_change'}
DEFAULT_HIGH_REASONING_MODEL = '[j]gpt-5.6-sol'

DEFAULT_SYSTEM_PROMPT = '''
你是 CMR 工作站内置专家，服务对象是心血管影像医生。
你的任务是解答工作站使用问题，并把真实 bug、需求、数据问题和 AI 使用体验转成可复现的工程问题。
不要诊断患者，不要提供治疗建议，不要声称执行了代码修改。
若信息不足，只追问最影响定位的一个问题。
回复使用清晰的 Markdown 段落、步骤和检查项，避免把所有内容挤成一个长段落。
输出严格 JSON，包含 reply、intent、ready_for_ticket 和 ticket。
'''.strip()


def load_system_prompt() -> str:
    try:
        content = PROMPT_PATH.read_text(encoding='utf-8').strip()
        return content or DEFAULT_SYSTEM_PROMPT
    except OSError:
        return DEFAULT_SYSTEM_PROMPT


def redact_external_text(value: Any) -> str:
    """Keep raw local history, but remove likely identifiers before an external LLM call."""
    text = str(value or '')
    text = re.sub(r'\b\d{17}[0-9Xx]\b', '[已隐藏身份证号]', text)
    text = re.sub(r'(?<!\d)1[3-9]\d{9}(?!\d)', '[已隐藏手机号]', text)
    text = re.sub(r'(?<!\d)\d{8,16}(?!\d)', '[已隐藏病例编号]', text)
    return text


def safe_page_context(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    allowed = {
        'module',
        'module_label',
        'dataset',
        'source',
        'case_catalog_id',
        'study_id',
        'workstation_path',
    }
    result: dict[str, Any] = {}
    for key in allowed:
        value = raw.get(key)
        if value is None or isinstance(value, (str, int, float, bool)):
            if value not in (None, ''):
                result[key] = value
    return result


def resolve_feedback_model(
    fallback_model: str,
    reasoning_level: str,
    *,
    standard_model: str = '',
    high_model: str = '',
) -> str:
    fallback = str(fallback_model or '').strip()
    if reasoning_level == 'high':
        return str(high_model or DEFAULT_HIGH_REASONING_MODEL).strip() or fallback
    return str(standard_model or fallback).strip()


def build_messages(
    history: Iterable[dict[str, Any]],
    *,
    page_context: dict[str, Any],
    category_hint: str = '',
) -> list[dict[str, str]]:
    context_json = json.dumps(safe_page_context(page_context), ensure_ascii=False)
    instruction = (
        f'当前页面上下文：{context_json}\n'
        f'用户主动选择的问题类型：{category_hint or "未指定"}\n'
        '请先判断这是已有功能咨询、bug、功能需求、数据问题、AI 使用体验还是其他。'
        '能用已有功能解决时给出完整、具体的操作路径和结果检查方法；'
        '真实问题达到可复现程度后再生成问题单。reply 必须使用 Markdown 分段，'
        '复杂任务优先使用小标题、编号步骤和检查项，不要输出单块密集长段落。'
    )
    messages = [
        {'role': 'system', 'content': load_system_prompt()},
        {'role': 'system', 'content': instruction},
    ]
    for item in list(history)[-18:]:
        role = str(item.get('role') or '')
        if role not in {'user', 'assistant'}:
            continue
        content = redact_external_text(item.get('content'))[:12000]
        if content:
            messages.append({'role': role, 'content': content})
    return messages


def extract_json_object(raw_text: str) -> dict[str, Any] | None:
    text = str(raw_text or '').strip()
    if not text:
        return None
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except (TypeError, ValueError):
        pass
    start = text.find('{')
    end = text.rfind('}')
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start:end + 1])
        return value if isinstance(value, dict) else None
    except (TypeError, ValueError):
        return None


def normalize_agent_result(raw_text: str) -> dict[str, Any]:
    parsed = extract_json_object(raw_text)
    if not parsed:
        return {
            'reply': str(raw_text or '').strip() or '我暂时没有生成有效回复，请重试。',
            'intent': 'other',
            'ready_for_ticket': False,
            'ticket': None,
        }

    intent = str(parsed.get('intent') or 'other').strip()
    if intent not in ALLOWED_CATEGORIES:
        intent = 'other'
    reply = str(parsed.get('reply') or '').strip()
    ticket = parsed.get('ticket') if isinstance(parsed.get('ticket'), dict) else None
    ready = bool(parsed.get('ready_for_ticket')) and ticket is not None
    if not ready:
        return {
            'reply': reply or '我还需要一点信息才能准确判断。',
            'intent': intent,
            'ready_for_ticket': False,
            'ticket': None,
        }

    severity = str(ticket.get('severity') or 'medium').strip()
    if severity not in ALLOWED_SEVERITIES:
        severity = 'medium'
    change_scope = str(ticket.get('change_scope') or 'needs_review').strip()
    if change_scope not in ALLOWED_CHANGE_SCOPES:
        change_scope = 'needs_review'
    category = str(ticket.get('category') or intent).strip()
    if category not in ALLOWED_CATEGORIES:
        category = intent

    normalized_ticket = {
        'category': category,
        'title': str(ticket.get('title') or '未命名问题').strip()[:200],
        'summary': str(ticket.get('summary') or '').strip(),
        'page': str(ticket.get('page') or '').strip()[:120],
        'operation': str(ticket.get('operation') or '').strip(),
        'expected_behavior': str(ticket.get('expected_behavior') or '').strip(),
        'actual_behavior': str(ticket.get('actual_behavior') or '').strip(),
        'impact': str(ticket.get('impact') or '').strip(),
        'severity': severity,
        'acceptance_criteria': str(ticket.get('acceptance_criteria') or '').strip(),
        'change_scope': change_scope,
    }
    return {
        'reply': reply or '我已经把这个问题整理成问题单。',
        'intent': intent,
        'ready_for_ticket': True,
        'ticket': normalized_ticket,
    }


def derive_session_title(content: str) -> str:
    title = re.sub(r'\s+', ' ', str(content or '')).strip()
    if not title:
        return '新对话'
    return title[:36] + ('...' if len(title) > 36 else '')
