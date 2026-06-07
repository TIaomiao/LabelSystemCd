from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CORE_METRICS = [
    ("LVEDV", "左室舒张末容积", "mL"),
    ("LVESV", "左室收缩末容积", "mL"),
    ("LVEF", "左室射血分数", "%"),
    ("SV", "左室每搏量", "mL"),
    ("RVEDV", "右室舒张末容积", "mL"),
    ("RVESV", "右室收缩末容积", "mL"),
    ("RVEF", "右室射血分数", "%"),
    ("LVEDD", "左室舒张末内径", "mm"),
    ("RVEDD", "右室舒张末内径", "mm"),
    ("IVS", "室间隔厚度", "mm"),
    ("LVPW", "左室后壁厚度", "mm"),
    ("RWT", "相对室壁厚度", ""),
    ("SI", "左室球形指数", ""),
    ("LV/RV ratio", "左/右室容积比", ""),
    ("LAV", "左房容积", "mL"),
    ("RAV", "右房容积", "mL"),
    ("LA_SI", "左房上下径", "mm"),
    ("LA_LR", "左房左右径", "mm"),
    ("RA_SI", "右房上下径", "mm"),
    ("RA_LR", "右房左右径", "mm"),
]

STATUS_ZH = {
    "normal": "正常",
    "low": "偏低",
    "high": "偏高",
    "missing": "缺失",
    "unknown": "未知",
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)):
        if abs(float(value)) >= 100:
            return f"{float(value):.1f}".rstrip("0").rstrip(".")
        return f"{float(value):.{digits}f}".rstrip("0").rstrip(".")
    return str(value)


def _value_with_unit(item: dict[str, Any] | None, default_unit: str = "") -> str:
    item = item or {}
    value = item.get("value")
    if value is None:
        return "未获得"
    unit = item.get("unit") or default_unit
    return f"{_fmt(value)}{unit}"


def _status_text(item: dict[str, Any] | None) -> str:
    item = item or {}
    return STATUS_ZH.get(str(item.get("status") or "unknown"), str(item.get("status") or "未知"))


def _abnormal_phrase(metrics: dict[str, dict[str, Any]], names: list[str]) -> str:
    parts = []
    for name in names:
        item = metrics.get(name) or {}
        status = item.get("status")
        if status in {"high", "low"}:
            parts.append(f"{name} {_value_with_unit(item)}（{_status_text(item)}）")
    return "；".join(parts) if parts else "未见明确异常"


def _metric_lookup(evidence_input: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("name")): item
        for item in evidence_input.get("quantitative_facts", []) or []
        if isinstance(item, dict) and item.get("name")
    }


def _metric_line(item: dict[str, Any] | None, name: str, label: str, default_unit: str) -> str:
    item = item or {}
    value = item.get("value")
    unit = item.get("unit") or default_unit
    status = STATUS_ZH.get(str(item.get("status") or "unknown"), str(item.get("status") or "未知"))
    ref_low = item.get("reference_lower")
    ref_high = item.get("reference_upper")
    ref = ""
    if ref_low is not None or ref_high is not None:
        ref = f"，参考范围 {_fmt(ref_low)}–{_fmt(ref_high)}{unit}"
    return f"- **{name}（{label}）**：{_fmt(value)}{unit}（{status}{ref}）"


def _section_summary(report: dict[str, Any], key: str) -> str:
    value = report.get(key) or {}
    if isinstance(value, dict):
        return str(value.get("summary") or "")
    return str(value or "")


def _lge_lines(evidence_input: dict[str, Any]) -> list[str]:
    lge = evidence_input.get("lge_summary") or {}
    tissue_facts = evidence_input.get("tissue_facts") or []
    lines = [
        f"- **LGE结论**：{lge.get('consensus') or '—'}（confidence={lge.get('confidence') or '—'}）",
        f"- **whole-view有效票数**：{lge.get('whole_view_valid_votes', '—')}；invalid={lge.get('whole_view_invalid_votes', '—')}",
        f"- **grid votes**：positive={lge.get('grid_positive_cells', '—')}，negative={lge.get('grid_negative_cells', '—')}，invalid={lge.get('grid_invalid_cells', '—')}",
        f"- **原因**：{lge.get('reason') or '—'}",
    ]
    for fact in tissue_facts:
        if isinstance(fact, dict):
            lines.append(f"- **{fact.get('name') or 'tissue'}**：{fact.get('description') or fact.get('clinical_meaning') or '—'}")
    return lines


def render_numeric_report(case_dir: Path) -> str:
    report_path = case_dir / "report.json"
    evidence_input_path = case_dir / "evidence_input.json"
    evidence_path = case_dir / "evidence.json"
    report = _load_json(report_path) if report_path.exists() else {}
    evidence_input = _load_json(evidence_input_path) if evidence_input_path.exists() else {}
    evidence = _load_json(evidence_path) if evidence_path.exists() else {}
    metrics = _metric_lookup(evidence_input)
    patient_info = evidence_input.get("patient_info") or {}
    evidence_summary = evidence.get("evidence_summary") or {}
    diagnosis = report.get("diagnosis") or {}

    lines: list[str] = [
        "# 心脏MRI结构化报告（AI_V2）",
        "",
        "## 基本信息",
        f"- **PatientID**：{patient_info.get('patient_id') or case_dir.name}",
        f"- **年龄/性别**：{patient_info.get('age') or '—'} / {patient_info.get('sex') or '—'}",
        f"- **身高/体重**：{patient_info.get('height_cm') or '—'} cm / {patient_info.get('weight_kg') or '—'} kg",
        "",
        "## 1. 心脏结构",
        "### （1）心腔大小",
        f"- 左心室舒张末期内径 **LVEDD**：{_value_with_unit(metrics.get('LVEDD'), 'mm')}（{_status_text(metrics.get('LVEDD'))}；模板参考：男42.0–57.3mm，女39.0–53.6mm）",
        f"- 左心房径线 **LA_SI/LA_LR**：{_value_with_unit(metrics.get('LA_SI'), 'mm')} / {_value_with_unit(metrics.get('LA_LR'), 'mm')}（{_status_text(metrics.get('LA_SI'))}/{_status_text(metrics.get('LA_LR'))}）",
        f"- 右心室舒张末期内径 **RVEDD**：{_value_with_unit(metrics.get('RVEDD'), 'mm')}（{_status_text(metrics.get('RVEDD'))}；模板参考：男19.8–33.84mm，女18.72–36.63mm）",
        f"- 右心房径线 **RA_SI/RA_LR**：{_value_with_unit(metrics.get('RA_SI'), 'mm')} / {_value_with_unit(metrics.get('RA_LR'), 'mm')}（{_status_text(metrics.get('RA_SI'))}/{_status_text(metrics.get('RA_LR'))}）",
        f"- 心腔大小证据：{_abnormal_phrase(metrics, ['LVEDV', 'LVESV', 'RVEDV', 'RVESV', 'LAV', 'RAV'])}",
        "",
        "### （2）左心室LV心肌厚度",
        f"- 室间隔 **IVS**：{_value_with_unit(metrics.get('IVS'), 'mm')}（{_status_text(metrics.get('IVS'))}）",
        f"- 左室后壁 **LVPW**：{_value_with_unit(metrics.get('LVPW'), 'mm')}（{_status_text(metrics.get('LVPW'))}）",
        f"- 相对室壁厚度 **RWT**：{_value_with_unit(metrics.get('RWT'))}（{_status_text(metrics.get('RWT'))}）",
        f"- 结构判断：{_section_summary(report, 'structure') or evidence_summary.get('structure') or '—'}",
        "",
        "## 2. 心脏运动及功能",
        "### （1）心肌运动",
        f"- LV室壁运动/泵功能：{_section_summary(report, 'function') or evidence_summary.get('function') or '—'}",
        "",
        "### （2）心脏功能",
        "#### 1）左心室",
        f"- **LVEF**：{_value_with_unit(metrics.get('LVEF'), '%')}（{_status_text(metrics.get('LVEF'))}；模板参考：男52.1–70.1%，女54.0–72.4%）",
        f"- **LVEDV**：{_value_with_unit(metrics.get('LVEDV'), 'mL')}（{_status_text(metrics.get('LVEDV'))}；模板参考：男92.9–193.3mL，女78.3–153.7mL）",
        f"- **LVESV**：{_value_with_unit(metrics.get('LVESV'), 'mL')}（{_status_text(metrics.get('LVESV'))}；模板参考：男30.7–79.9mL，女24.3–61.3mL）",
        f"- **SV**：{_value_with_unit(metrics.get('SV'), 'mL')}（{_status_text(metrics.get('SV'))}）",
        "",
        "#### 2）右心室",
        f"- **RVEF**：{_value_with_unit(metrics.get('RVEF'), '%')}（{_status_text(metrics.get('RVEF'))}；模板参考：男51.8–69.9%，女54.1–72.3%）",
        f"- **RVEDV**：{_value_with_unit(metrics.get('RVEDV'), 'mL')}（{_status_text(metrics.get('RVEDV'))}；模板参考：男92.0–201.8mL，女74.7–153.0mL）",
        f"- **RVESV**：{_value_with_unit(metrics.get('RVESV'), 'mL')}（{_status_text(metrics.get('RVESV'))}；模板参考：男31.2–84.1mL，女23.4–60.6mL）",
        "",
        "### （3）瓣膜形态及功能",
        "- 当前自动流程未提供可靠瓣膜狭窄/返流定量证据；如临床关注瓣膜病变，建议结合原始电影序列人工复核。",
        "",
        "## 3. 延迟强化 LGE",
        *_lge_lines(evidence_input),
        f"- 组织特征判断：{_section_summary(report, 'tissue') or evidence_summary.get('tissue') or '—'}",
        "",
        "## 4. 其他影像所见",
        "- 当前自动流程未输出明确心肌内脂肪浸润、血栓、心包积液或胸腔积液证据；如原始图像可见相关征象，需人工补充。",
        "",
        "## 5. 证据融合与诊断推理",
    ]
    for item in evidence.get("diagnostic_hypotheses", []) or []:
        if isinstance(item, dict):
            lines.append(f"- **{item.get('label') or item.get('name') or 'hypothesis'}**（confidence={item.get('confidence') or '—'}）：{item.get('rationale') or item.get('reason') or '—'}")

    lines.extend([
        "",
        "## 6. 诊断结论",
        diagnosis.get("summary") or _section_summary(report, "diagnosis") or "—",
    ])
    for item in diagnosis.get("primary_diagnosis", []) or []:
        if isinstance(item, dict):
            lines.append(f"- **主要诊断**：{item.get('label') or '—'}（confidence={item.get('confidence') or '—'}）— {item.get('rationale') or '—'}")
    differentials = diagnosis.get("differential", []) or []
    if differentials:
        lines.extend(["", "## 7. 鉴别诊断"])
        for item in differentials:
            if isinstance(item, dict):
                lines.append(f"- **{item.get('label') or '—'}**（confidence={item.get('confidence') or '—'}）：{item.get('rationale') or '—'}")

    follow_up = report.get("follow_up") or []
    if follow_up:
        lines.extend(["", "## 8. 建议"])
        for item in follow_up:
            if isinstance(item, dict):
                lines.append(f"- {item.get('recommendation') or '—'}：{item.get('reason') or '—'}")

    return "\n".join(lines).strip() + "\n"


def apply_numeric_report(case_dir: Path) -> Path:
    text = render_numeric_report(case_dir)
    text_path = case_dir / "report_text.md"
    text_path.write_text(text, encoding="utf-8")
    report_path = case_dir / "report.json"
    if report_path.exists():
        report = _load_json(report_path)
        report["text"] = text
        report["report_format"] = "labelsystem_numeric_v1"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return text_path
