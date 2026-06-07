#!/usr/bin/env python3
"""
Clean and standardize RenJi CMR Excel/report data.

This script is intentionally smoke-first:
- deterministic cleanup always runs;
- LLM standardization is optional and limited by --limit;
- outputs JSONL so partial runs are inspectable.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app import app  # noqa: E402
from models import CviCaseCatalog  # noqa: E402
from routes import (  # noqa: E402
    _llm_gateway_client,
    _load_llm_gateway_config,
    _normalize_excel_cell,
    _read_dicom_identity,
)


@dataclass(frozen=True)
class DatasetSpec:
    dataset: str
    cohort: str
    excel_path: Path
    header_row: int
    id_cols: tuple[str, ...]
    date_cols: tuple[str, ...]
    report_description_cols: tuple[str, ...]
    report_diagnosis_cols: tuple[str, ...]
    clinical_cols: tuple[str, ...]
    numeric_cols: tuple[str, ...]
    binary_cols: tuple[str, ...]


HCM_SPEC = DatasetSpec(
    dataset="CMR_RenJi_HCM",
    cohort="HCM",
    excel_path=Path("/home/Larry/data/CMR_RenJi/仁济.xlsx"),
    header_row=1,
    id_cols=("放射编号",),
    date_cols=("检查时间", "检查时间.2"),
    report_description_cols=("核磁表现",),
    report_diagnosis_cols=("核磁诊断",),
    clinical_cols=(
        "病人姓名",
        "年龄",
        "性别",
        "入院情况（主诉）",
        "入院情况（现病史）",
        "出院诊断",
        "超声报告描述",
        "超声报告诊断",
    ),
    numeric_cols=(
        "身高cm",
        "体重kg",
        "LGE （% of LV mass）",
        "LV EDV",
        "LV ESV",
        "LV SV",
        "LV CO",
        "LVEF",
        "LV mass",
        "RV EDV",
        "RV ESV",
        "RV SV",
        "RV CO",
        "RVEF",
        "LA RS",
        "LA BS",
        "LA CS",
        "RA RS",
        "RA BS",
        "RA CS",
        "心超静息左室流出道最高压差(LVOT gradient, mm Hg)",
        "Maximal wall thickness （mm）",
    ),
    binary_cols=(
        "高血压病史",
        "冠心病病史",
        "糖尿病病史",
        "高脂血症",
        "吸烟史",
        "房颤/房扑",
        "持续性室速或室颤（1=有）",
        "肥心病家族史",
        "心源性猝死家族史（1=有）",
        "晕厥病史（可疑心律失常性晕厥）（1=有）",
        "非持续性室性心动过速（NSVT)",
        "左室流出道梗阻",
        "左室流出道梗阻（LVOT gradient≥30 mm Hg)",
        "SAM征（二尖瓣前向运动，评估HCM，（0=无，1=有）",
        "延迟强化（0无，1有）",
        "Apical aneurysm",
        "SCD",
        "SCD-events",
        "全因死亡",
        "心脏移植",
        "心衰",
        "新发房颤",
        "脑卒中",
    ),
)

MI_SPEC = DatasetSpec(
    dataset="CMR_RenJi_MI",
    cohort="MI",
    excel_path=Path("/home/Larry/data/CMR_RenJi/仁济MI.xlsx"),
    header_row=0,
    id_cols=("登记号", "patient ID"),
    date_cols=("检查时间",),
    report_description_cols=("CMR报告及诊断.1",),
    report_diagnosis_cols=("CMR报告及诊断",),
    clinical_cols=(
        "姓名",
        "性别",
        "年龄",
        "ST段抬高/非ST段抬高",
        "心电图",
        "心超描述及诊断",
        "冠脉CTA描述",
        "冠脉CTA诊断",
        "冠脉介入造影术中所见",
        "临床诊断",
    ),
    numeric_cols=(
        "身高",
        "体重",
        "体表面积",
        "BMI",
        "入院心率",
        "收缩压",
        "舒张压",
        "Killip分级（入院或出院）",
        "BNP（＞125）",
        "TNIpeak",
        "TC\n（3.49-5.18）",
        "TG\n（0.25-1.71）",
        "HDL（＞1.04）",
        "LDL\n（<3.37）\n",
        "NGSP-HbA1c（4.6-6.5%）",
        "随机血糖mmol/L",
        "肌酐",
        "eGFR估算肾小球滤过率ml/min",
        "CO,L/min",
        "CI,L/min/m*2",
        "EDV，ml",
        "ESV，ml",
        "EDVI",
        "ESVI",
        "EF,%",
        "GRS",
        "GCS",
        "GLS",
        "LAEDV",
        "LAESV",
        "LVmass",
        "LVMI",
        "LGE（g）",
        "LGE（%）",
        "罪犯血管总数",
        "累计17节段总数",
    ),
    binary_cols=(
        "恶性肿瘤",
        "脑卒中",
        "肾病",
        "糖尿病",
        "高血压",
        "高血脂",
        "COPD",
        "吸烟",
        "β受体抑制剂",
        "ACEI",
        "他汀",
        "利尿剂",
        "阿司匹林",
        "氯吡格雷",
        "胰岛素",
        "降糖药",
        "室壁瘤",
        "MVO",
        "LAD",
        "RCA",
        "LCX",
        "心尖",
        "前壁",
        "室间隔",
        "下壁",
        "侧壁",
        "中层LGE",
        "MACE(全因死亡、SCD、再发非致命MI、心衰、VA、ICD植入治疗、脑卒中发生风险预测\n0=无，1=有、严重心绞痛再入院、其他)",
        "再发非致命MI",
        "心衰",
        "其他",
    ),
)

DATASETS = {spec.dataset: spec for spec in (HCM_SPEC, MI_SPEC)}

MANUAL_EXCEL_INDEX_OVERRIDES = {
    # Doctor-confirmed RenJi HCM mappings. These two case folders have DICOM
    # headers from a different accession/study, so automatic DICOM matching
    # cannot safely identify the report row.
    ("CMR_RenJi_HCM", "20180606 zhouwei"): "200",
    ("CMR_RenJi_HCM", "20200812 he li ping"): "273",
}

PLACEHOLDER_RE = re.compile(r"^(?:nan|none|null|n/?a|--|-|/|\\\\)?$", re.IGNORECASE)
REFERENCE_PATTERNS = (
    "参考范围",
    "参考值",
    "项目名称",
    "Mosteller",
    "参考2013年ESC",
    "<35岁",
    ">=35岁",
    "＜35岁",
    "≥35岁",
)


def iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def clean_cell(value: Any) -> str:
    text = _normalize_excel_cell(value)
    if not text:
        return ""
    text = text.replace("\u00a0", " ")
    text = text.replace("；;", "；").replace("。;", "。")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip(" ;；\n\t")
    if PLACEHOLDER_RE.fullmatch(text):
        return ""
    return text


def normalize_col_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name).strip().replace("\n", " "))


def date_digits(value: Any) -> str:
    text = clean_cell(value)
    if not text:
        return ""
    parsed = pd.to_datetime(text, errors="coerce")
    if not pd.isna(parsed):
        return parsed.strftime("%Y%m%d")
    match = re.search(r"(20\d{2}|19\d{2})\D?(\d{1,2})\D?(\d{1,2})", text)
    if not match:
        return "".join(ch for ch in text if ch.isdigit())[:8]
    year, month, day = match.groups()
    return f"{year}{int(month):02d}{int(day):02d}"


def numeric_value(value: Any) -> float | None:
    text = clean_cell(value)
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def boolean_value(value: Any) -> int | str | None:
    text = clean_cell(value)
    if not text:
        return None
    if text in {"0", "0.0", "否", "无", "未见"}:
        return 0
    if text in {"1", "1.0", "是", "有"}:
        return 1
    return text


def clean_report_text(text: str) -> tuple[str, dict[str, Any]]:
    raw = clean_cell(text)
    if not raw:
        return "", {"removed_reference_lines": 0, "removed_tabular_lines": 0, "raw_length": 0, "clean_length": 0}

    lines = [line.strip() for line in raw.splitlines()]
    cleaned: list[str] = []
    removed_reference = 0
    removed_tabular = 0
    in_measurement_table = False

    for line in lines:
        if not line or PLACEHOLDER_RE.fullmatch(line):
            continue
        if "电影扫描" in line:
            in_measurement_table = False
        if "心室活动、心功能测定" in line:
            in_measurement_table = True
            removed_tabular += 1
            continue
        if in_measurement_table:
            removed_tabular += 1
            continue
        if any(pattern in line for pattern in REFERENCE_PATTERNS):
            removed_reference += 1
            continue
        tab_like_count = line.count("\t") + line.count("  ")
        numeric_tokens = re.findall(r"-?\d+(?:\.\d+)?", line)
        # Drop dense measurement/reference table rows, but keep narrative lines with numbers.
        table_metric = re.match(
            r"^(?:舒张末容积|收缩末容积|每搏|每博|射血分数|心肌质量|侧壁厚度|室间隔厚度|面积|内径|指数)",
            line,
        )
        if (tab_like_count >= 2 and len(numeric_tokens) >= 3) or (
            table_metric and len(numeric_tokens) >= 4 and ("/" in line or "-" in line or "~" in line)
        ):
            removed_tabular += 1
            continue
        line = re.sub(r"[ \t]+", " ", line)
        cleaned.append(line)

    joined = "\n".join(cleaned)
    joined = re.sub(r"\n{3,}", "\n\n", joined).strip()
    return joined, {
        "removed_reference_lines": removed_reference,
        "removed_tabular_lines": removed_tabular,
        "raw_length": len(raw),
        "clean_length": len(joined),
    }


def row_text(row: pd.Series, columns: tuple[str, ...]) -> dict[str, str]:
    result = {}
    for col in columns:
        if col not in row:
            continue
        value = clean_cell(row[col])
        if value:
            result[col] = value
    return result


def row_numeric(row: pd.Series, columns: tuple[str, ...]) -> dict[str, float]:
    result = {}
    for col in columns:
        if col not in row:
            continue
        value = numeric_value(row[col])
        if value is not None:
            result[normalize_col_name(col)] = value
    return result


def row_binary(row: pd.Series, columns: tuple[str, ...]) -> dict[str, int | str]:
    result = {}
    for col in columns:
        if col not in row:
            continue
        value = boolean_value(row[col])
        if value is not None:
            result[normalize_col_name(col)] = value
    return result


def load_excel(spec: DatasetSpec) -> pd.DataFrame:
    df = pd.read_excel(spec.excel_path, dtype=str, header=spec.header_row)
    df.columns = [str(col).strip() for col in df.columns]
    return df


def catalog_cases(dataset: str, include_unmatched: bool = False) -> list[CviCaseCatalog]:
    query = CviCaseCatalog.query.filter_by(source="functional", dataset=dataset)
    if not include_unmatched:
        query = query.filter_by(has_dicom=True)
    return query.order_by(CviCaseCatalog.case_id.asc()).all()


def row_matches_identity(row: pd.Series, identity: dict[str, str], spec: DatasetSpec) -> bool:
    accession = identity.get("accession_number") or ""
    patient_id = identity.get("patient_id") or ""
    for col in spec.id_cols:
        if col not in row:
            continue
        value = clean_cell(row[col])
        if not value:
            continue
        if accession and value == accession:
            return True
        if patient_id and value == patient_id:
            return True
    return False


def match_excel_row(df: pd.DataFrame, case: CviCaseCatalog, spec: DatasetSpec) -> tuple[pd.Series | None, dict[str, str], str]:
    identity = _read_dicom_identity(case.path)
    manual_index = MANUAL_EXCEL_INDEX_OVERRIDES.get((spec.dataset, case.case_id))
    if manual_index and "Index" in df.columns:
        index_matches = df[df["Index"].map(clean_cell) == manual_index]
        if len(index_matches) == 1:
            return index_matches.iloc[0], identity, "manual_excel_index"

    for _, row in df.iterrows():
        if row_matches_identity(row, identity, spec):
            return row, identity, "dicom_id"

    study_date = identity.get("study_date") or ""
    if study_date:
        date_matches = []
        for _, row in df.iterrows():
            for col in spec.date_cols:
                if col in row and date_digits(row[col]) == study_date:
                    date_matches.append(row)
                    break
        if len(date_matches) == 1:
            return date_matches[0], identity, "study_date_unique"
    return None, identity, "unmatched"


def build_case_packet(
    spec: DatasetSpec,
    case: CviCaseCatalog,
    row: pd.Series,
    identity: dict[str, str],
    match_strategy: str,
) -> dict[str, Any]:
    desc_parts = []
    desc_stats = {}
    for col in spec.report_description_cols:
        if col in row:
            cleaned, stats = clean_report_text(row[col])
            if cleaned:
                desc_parts.append({"source_column": col, "text": cleaned})
            desc_stats[col] = stats

    diagnosis = row_text(row, spec.report_diagnosis_cols)
    clinical = row_text(row, spec.clinical_cols)
    numeric = row_numeric(row, spec.numeric_cols)
    binary = row_binary(row, spec.binary_cols)

    identifiers = {col: clean_cell(row[col]) for col in spec.id_cols if col in row and clean_cell(row[col])}
    return {
        "dataset": spec.dataset,
        "cohort": spec.cohort,
        "case_id": case.case_id,
        "image_path": case.path,
        "dicom_count": case.dicom_count,
        "dicom_identity": identity,
        "excel_match_strategy": match_strategy,
        "excel_identifiers": identifiers,
        "cmr_description_clean": desc_parts,
        "cmr_diagnosis_clean": diagnosis,
        "clinical_context_clean": clinical,
        "numeric_fields": numeric,
        "binary_fields": binary,
        "cleaning_stats": {
            "description": desc_stats,
            "description_columns": list(spec.report_description_cols),
            "diagnosis_columns": list(spec.report_diagnosis_cols),
        },
    }


def trim_text_map(values: dict[str, str], *, per_field: int = 700, total: int = 2200) -> dict[str, str]:
    trimmed = {}
    used = 0
    for key, value in values.items():
        if used >= total:
            break
        text = str(value or "")
        if len(text) > per_field:
            text = text[:per_field] + "...[TRUNCATED]"
        remaining = total - used
        if len(text) > remaining:
            text = text[:remaining] + "...[TRUNCATED]"
        trimmed[key] = text
        used += len(text)
    return trimmed


def compact_for_llm(packet: dict[str, Any], max_text_chars: int = 2600) -> dict[str, Any]:
    description = "\n\n".join(
        f"{item['source_column']}:\n{item['text']}" for item in packet.get("cmr_description_clean", [])
    )
    if len(description) > max_text_chars:
        description = description[:max_text_chars] + "\n...[TRUNCATED]"
    numeric_fields = packet.get("numeric_fields", {})
    # Keep all numeric fields for HCM/MI-specific inference, but avoid runaway prompt size.
    if len(numeric_fields) > 45:
        numeric_fields = dict(list(numeric_fields.items())[:45])
    return {
        "dataset": packet["dataset"],
        "cohort": packet["cohort"],
        "case_id": packet["case_id"],
        "dicom_identity": {
            "study_date": (packet.get("dicom_identity") or {}).get("study_date"),
            "accession_number": (packet.get("dicom_identity") or {}).get("accession_number"),
        },
        "cmr_description": description,
        "cmr_diagnosis": packet.get("cmr_diagnosis_clean", {}),
        "clinical_context": trim_text_map(packet.get("clinical_context_clean", {})),
        "numeric_fields": numeric_fields,
        "binary_fields": packet.get("binary_fields", {}),
    }


def llm_standardize(packet: dict[str, Any]) -> dict[str, Any]:
    cfg = _load_llm_gateway_config()
    client = _llm_gateway_client(cfg)
    payload = compact_for_llm(packet)
    schema_hint = {
        "normalized_imaging_diagnoses": ["CMR/imaging diagnosis labels only"],
        "clinical_comorbidities": ["clinical non-imaging diagnoses or risk factors"],
        "primary_disease": "HCM or MI subtype if supported by evidence",
        "cmr_features": {
            "chamber_size": [],
            "hypertrophy": [],
            "wall_motion": [],
            "edema": [],
            "perfusion_defect": [],
            "lge_pattern": [],
            "mvo": None,
            "hemorrhage": None,
            "aneurysm_or_thrombus": [],
            "valve_or_pericardial_findings": [],
        },
        "quantitative_metrics": [{"name": "", "value": None, "unit": "", "source": "excel/report"}],
        "disease_specific": {
            "hcm": {
                "obstruction": None,
                "sam": None,
                "max_wall_thickness_mm": None,
                "lge_percent": None,
                "risk_markers": [],
            },
            "mi": {
                "stemi_nstemi": None,
                "culprit_vessel": [],
                "infarct_territory": [],
                "transmurality_grade": None,
                "mvo": None,
                "mace": None,
            },
        },
        "data_quality_flags": [],
        "cleaned_summary": "one concise Chinese paragraph",
    }
    messages = [
        {
            "role": "system",
            "content": (
                "你是心脏MRI数据清洗和标准化助手。只依据输入内容，不要猜测。"
                "清理模板/参考范围噪声后，将病例标准化为JSON。"
                "保留医学缩写含义：HCM=肥厚型心肌病，MI=心肌梗死，"
                "LGE=晚期钆增强，MVO=微血管阻塞，SAM=二尖瓣前叶收缩期前向运动。"
                "normalized_imaging_diagnoses只放CMR/影像诊断，不要把房颤、室速、糖尿病等临床病史放进去；"
                "这些应放入clinical_comorbidities或risk_markers。"
                "binary_fields中的0表示无/否，1表示有/是；0不要写成阳性影像发现。"
                "excel数值和报告正文数值可能来自不同测量软件/版本，除非同一字段明显自相矛盾，不要标为质量错误。"
                "data_quality_flags只记录真实缺失、矛盾、模板残留或无法判断项，不要记录PHI。"
                "输出必须是合法JSON对象，不要Markdown。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请按这个schema输出，字段可以为空但不要省略主要键：\n"
                f"{json.dumps(schema_hint, ensure_ascii=False)}\n\n"
                "病例输入：\n"
                f"{json.dumps(payload, ensure_ascii=False)}"
            ),
        },
    ]
    started = time.time()
    try:
        response = client.chat.completions.create(
            model=cfg.get("model"),
            messages=messages,
            temperature=0,
            max_tokens=1200,
            response_format={"type": "json_object"},
            timeout=45,
        )
    except Exception:
        response = client.chat.completions.create(
            model=cfg.get("model"),
            messages=messages,
            temperature=0,
            max_tokens=1200,
            timeout=45,
        )
    text = (response.choices[0].message.content or "").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        parsed = json.loads(text[start : end + 1]) if start >= 0 and end > start else {"_raw_text": text}
    return {
        "ok": True,
        "model": cfg.get("model"),
        "latency_ms": int((time.time() - started) * 1000),
        "result": parsed,
    }


def choose_cases(cases: list[CviCaseCatalog], limit: int) -> list[CviCaseCatalog]:
    if limit <= 0 or len(cases) <= limit:
        return cases
    # Spread the smoke set over the sorted cohort instead of taking only early dates.
    if limit == 1:
        return [cases[0]]
    step = (len(cases) - 1) / (limit - 1)
    indices = [round(i * step) for i in range(limit)]
    selected = []
    seen = set()
    for index in indices:
        index = min(max(index, 0), len(cases) - 1)
        if index in seen:
            continue
        seen.add(index)
        selected.append(cases[index])
    return selected


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def run(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_specs = [DATASETS[name] for name in args.dataset]
    all_cleaned: list[dict[str, Any]] = []
    all_standardized: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "generated_at": iso_now(),
        "llm_enabled": not args.no_llm,
        "datasets": {},
    }

    with app.app_context():
        for spec in selected_specs:
            df = load_excel(spec)
            cases = catalog_cases(spec.dataset, include_unmatched=args.include_no_dicom)
            cases = choose_cases(cases, args.limit)
            dataset_summary = {
                "selected_cases": len(cases),
                "matched_rows": 0,
                "missing_rows": [],
                "llm_ok": 0,
                "llm_errors": [],
            }
            for case in cases:
                row, identity, match_strategy = match_excel_row(df, case, spec)
                if row is None:
                    dataset_summary["missing_rows"].append(
                        {"case_id": case.case_id, "dicom_identity": identity}
                    )
                    continue
                packet = build_case_packet(spec, case, row, identity, match_strategy)
                all_cleaned.append(packet)
                dataset_summary["matched_rows"] += 1
                if not args.no_llm:
                    try:
                        standard = llm_standardize(packet)
                        dataset_summary["llm_ok"] += int(bool(standard.get("ok")))
                    except Exception as exc:  # keep smoke running
                        standard = {"ok": False, "error": str(exc)}
                        dataset_summary["llm_errors"].append({"case_id": case.case_id, "error": str(exc)})
                    all_standardized.append(
                        {
                            "dataset": spec.dataset,
                            "case_id": case.case_id,
                            "standardization": standard,
                        }
                    )
            summary["datasets"][spec.dataset] = dataset_summary

    write_jsonl(output_dir / "renji_cleaned_cases.jsonl", all_cleaned)
    if not args.no_llm:
        write_jsonl(output_dir / "renji_llm_standardized_cases.jsonl", all_standardized)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean and standardize RenJi CMR reports.")
    parser.add_argument(
        "--dataset",
        action="append",
        choices=sorted(DATASETS.keys()),
        default=[],
        help="Dataset to process. Can be passed multiple times. Default: both RenJi datasets.",
    )
    parser.add_argument("--limit", type=int, default=3, help="Smoke cases per dataset. <=0 means all.")
    parser.add_argument("--output-dir", default="tmp/renji_clean_smoke", help="Output directory.")
    parser.add_argument("--no-llm", action="store_true", help="Only run deterministic cleaning.")
    parser.add_argument("--include-no-dicom", action="store_true", help="Include catalog cases without DICOM.")
    args = parser.parse_args()
    if not args.dataset:
        args.dataset = sorted(DATASETS.keys())
    return args


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
