from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

from flask import abort, jsonify, request, send_file
from flask_login import login_required


REPO_ROOT = Path("/home/Larry/code/Ziqiu/MRIAgent")
DEFAULT_RUN_ROOT = REPO_ROOT / "results" / "cardiac_function_km_report150_raw_20260428"
COMPARISON_ROOT = REPO_ROOT / "case_check" / "results_chart"
KNOWN_RUN_ROOTS = [
    REPO_ROOT / "results" / "cardiac_function_km_report150_raw_20260428",
    REPO_ROOT / "results" / "cardiac_function_phase20_slice_qc_bsa",
    REPO_ROOT / "results" / "cardiac_function_phase20_slice_qc_archived_20260422_231108",
    REPO_ROOT / "results" / "cardiac_function_phase20_slice_qc",
    REPO_ROOT / "validation_runs" / "cardiac_function_smoke8",
]
DISCOVERY_PARENTS = [
    REPO_ROOT / "results",
    REPO_ROOT / "validation_runs",
]
REPORT_METRICS = {
    "LVEDV",
    "LVESV",
    "LVEF",
    "SV",
    "RVEDV",
    "RVESV",
    "RVEF",
    "LVEDD",
    "RVEDD",
    "LAV",
    "RAV",
    "LA_SI",
    "LA_LR",
    "RA_SI",
    "RA_LR",
    "IVS",
    "LVPW",
    "RWT",
    "SI",
    "LV/RV ratio",
}


def _resolve_output_root(run_root: Path) -> Path:
    direct_output = run_root / "outputs"
    if direct_output.is_dir():
        return direct_output
    return run_root


def _count_cases(output_root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not output_root.is_dir():
        return counts

    for center_dir in sorted(item for item in output_root.iterdir() if item.is_dir()):
        count = sum(
            1
            for case_dir in center_dir.iterdir()
            if case_dir.is_dir() and (case_dir / "metrics.json").exists()
        )
        if count:
            counts[center_dir.name] = count
    return counts


def _discover_runs() -> list[dict]:
    candidates: list[Path] = []
    env_root = os.environ.get("FUNCTION_QC_RUN_ROOT")
    if env_root:
        candidates.append(Path(env_root).expanduser().resolve())
    candidates.extend(path.expanduser().resolve() for path in KNOWN_RUN_ROOTS)
    for parent in DISCOVERY_PARENTS:
        if not parent.is_dir():
            continue
        for child in parent.iterdir():
            if child.is_dir():
                candidates.append(child.expanduser().resolve())

    seen: set[str] = set()
    runs: list[dict] = []
    for run_root in candidates:
        key = str(run_root)
        if key in seen:
            continue
        seen.add(key)
        output_root = _resolve_output_root(run_root)
        center_counts = _count_cases(output_root)
        total_cases = sum(center_counts.values())
        if total_cases <= 0:
            continue
        runs.append(
            {
                "runRoot": key,
                "outputRoot": str(output_root),
                "label": str(run_root.relative_to(REPO_ROOT)) if run_root.is_relative_to(REPO_ROOT) else key,
                "centerCounts": center_counts,
                "totalCases": total_cases,
                "centerCount": len(center_counts),
                "mtime": run_root.stat().st_mtime if run_root.exists() else 0.0,
            }
        )
    return runs


def _select_run(run_root_arg: str | None) -> dict | None:
    runs = _discover_runs()
    if not runs:
        return None

    if run_root_arg:
        requested = str(Path(run_root_arg).expanduser().resolve())
        for item in runs:
            if item["runRoot"] == requested:
                return item

    env_root = os.environ.get("FUNCTION_QC_RUN_ROOT")
    if env_root:
        requested = str(Path(env_root).expanduser().resolve())
        for item in runs:
            if item["runRoot"] == requested:
                return item

    default_root = str(DEFAULT_RUN_ROOT.expanduser().resolve())
    for item in runs:
        if item["runRoot"] == default_root:
            return item

    return max(
        runs,
        key=lambda item: (item["totalCases"], item["centerCount"], item["mtime"]),
    )


def _round_metric(value, digits: int = 2):
    if isinstance(value, (int, float)):
        return round(float(value), digits)
    return None


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compute_bsa(height_cm, weight_kg) -> float | None:
    height = _safe_float(height_cm)
    weight = _safe_float(weight_kg)
    if height is None or weight is None or height <= 0 or weight <= 0:
        return None
    return ((height * weight) / 3600.0) ** 0.5


def _index_volume(value_ml, bsa_m2) -> float | None:
    volume = _safe_float(value_ml)
    bsa = _safe_float(bsa_m2)
    if volume is None or bsa is None or bsa <= 1e-6:
        return None
    return volume / bsa


def _parse_numeric_value(value: str) -> float | None:
    if value.strip() in {"N/A", "NA", "nan", "-", ""}:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _ef_flag(name: str, value):
    if not isinstance(value, (int, float)):
        return f"{name}:missing"
    if value < 30:
        return f"{name}:low"
    if value > 80:
        return f"{name}:high"
    return None


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _comparison_path(center: str, patient_id: str) -> Path | None:
    dataset = center.replace("new_", "", 1) if center.startswith("new_") else center
    for suffix in (".md", ".txt"):
        path = COMPARISON_ROOT / dataset / f"{patient_id}_comparison{suffix}"
        if path.exists():
            return path
    return None


def _load_report_truth(center: str, patient_id: str) -> dict:
    path = _comparison_path(center, patient_id)
    metrics: dict[str, dict] = {}
    if path is None:
        return {"sourcePath": None, "metrics": metrics}

    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return {"sourcePath": str(path), "metrics": metrics}

    for line in lines:
        if "|" not in line or "AI报告值" in line or "---" in line:
            continue
        parts = [part.strip() for part in line.split("|")]
        clean_parts = [part for part in parts if part]
        if len(clean_parts) < 4:
            continue
        metric_name = clean_parts[1]
        if metric_name not in REPORT_METRICS:
            continue
        raw_value = clean_parts[3]
        metrics[metric_name] = {
            "raw": raw_value,
            "value": _round_metric(_parse_numeric_value(raw_value)),
        }

    return {"sourcePath": str(path), "metrics": metrics}


def _safe_relative(path: Path, output_root: Path) -> str | None:
    root = output_root.resolve()
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        return None


def _list_pngs(path: Path, output_root: Path) -> list[str]:
    if not path.is_dir():
        return []
    files = []
    for item in sorted(path.iterdir()):
        if item.is_file() and item.suffix.lower() == ".png":
            rel = _safe_relative(item, output_root)
            if rel:
                files.append(rel)
    return files


def _first_pngs_by_subdir(path: Path, output_root: Path) -> list[dict]:
    if not path.is_dir():
        return []
    samples = []
    for item in sorted(path.iterdir()):
        if not item.is_dir() or not item.name.endswith("_pngs"):
            continue
        pngs = _list_pngs(item, output_root)
        if not pngs:
            continue
        samples.append(
            {
                "name": item.name,
                "image": pngs[len(pngs) // 2],
                "count": len(pngs),
            }
        )
    return samples


def _load_summary_cases(run_root: Path, output_root: Path) -> list[dict]:
    summary = _read_json(run_root / "smoke_summary.json")
    if isinstance(summary, list):
        return summary

    if not output_root.is_dir():
        return []

    cases = []
    for center_dir in sorted(item for item in output_root.iterdir() if item.is_dir()):
        for case_dir in sorted(item for item in center_dir.iterdir() if item.is_dir()):
            cases.append(
                {
                    "center": center_dir.name,
                    "patient_id": case_dir.name,
                    "returncode": 0,
                    "elapsed_seconds": 0,
                    "output_dir": str(case_dir),
                    "metrics_exists": (case_dir / "metrics.json").exists(),
                    "workflow_exists": (case_dir / "workflow.log").exists(),
                }
            )
    return cases


def _phase_slice_images(case_dir: Path, seg_path, output_root: Path) -> list[str]:
    if not isinstance(seg_path, str):
        return []
    seg_name = Path(seg_path).name.replace(".nii.gz", ".nii_pngs")
    return _list_pngs(case_dir / "segmentations" / "SAX" / seg_name, output_root)


def _rv_volume_from_seg(seg_path) -> float | None:
    if not isinstance(seg_path, str):
        return None
    try:
        import nibabel as nib
        import numpy as np

        img = nib.load(seg_path)
        data = np.asarray(img.dataobj)
        voxel_volume_ml = float(np.prod(img.header.get_zooms()) / 1000.0)
        return float(np.count_nonzero(data == 1) * voxel_volume_ml)
    except Exception:
        return None


def _ef_percent(edv: float | None, esv: float | None) -> float | None:
    if edv is None or esv is None or edv <= 0:
        return None
    return (edv - esv) / edv * 100.0


def _phase_result(label: str, ed_phase: dict | None, es_phase: dict | None, *, method: str, candidate_count: int, min_slices: int | None = None) -> dict:
    ed_lv = _safe_float((ed_phase or {}).get("lv_volume_ml"))
    es_lv = _safe_float((es_phase or {}).get("lv_volume_ml"))
    ed_rv = _safe_float((ed_phase or {}).get("rv_volume_ml"))
    es_rv = _safe_float((es_phase or {}).get("rv_volume_ml"))
    return {
        "label": label,
        "method": method,
        "candidateCount": candidate_count,
        "minSlices": min_slices,
        "edTrigger": _round_metric(_safe_float((ed_phase or {}).get("raw_trigger"))),
        "esTrigger": _round_metric(_safe_float((es_phase or {}).get("raw_trigger"))),
        "LVEDV": _round_metric(ed_lv),
        "LVESV": _round_metric(es_lv),
        "LVEF": _round_metric(_ef_percent(ed_lv, es_lv)),
        "RVEDV": _round_metric(ed_rv),
        "RVESV": _round_metric(es_rv),
        "RVEF": _round_metric(_ef_percent(ed_rv, es_rv)),
    }


def _truth_phase_result(report_truth: dict) -> dict:
    truth = report_truth.get("metrics") or {}

    def value(key: str):
        return (truth.get(key) or {}).get("value")

    def raw(key: str):
        return (truth.get(key) or {}).get("raw")

    return {
        "label": "报告真实值",
        "method": "results_chart comparison gold-standard",
        "candidateCount": 0,
        "minSlices": None,
        "edTrigger": None,
        "esTrigger": None,
        "LVEDV": value("LVEDV"),
        "LVESV": value("LVESV"),
        "LVEF": value("LVEF"),
        "RVEDV": value("RVEDV"),
        "RVESV": value("RVESV"),
        "RVEF": value("RVEF"),
        "rawValues": {
            "LVEDV": raw("LVEDV"),
            "LVESV": raw("LVESV"),
            "LVEF": raw("LVEF"),
            "RVEDV": raw("RVEDV"),
            "RVESV": raw("RVESV"),
            "RVEF": raw("RVEF"),
        },
    }


def _build_phase_comparison(case_dir: Path, sax: dict, report_truth: dict, output_root: Path) -> dict:
    phases = []
    for phase in sax.get("all_phases") or []:
        lv_volume = _safe_float(phase.get("lv_volume_ml"))
        trigger = _safe_float(phase.get("raw_trigger"))
        if lv_volume is None or trigger is None:
            continue
        seg_path = phase.get("seg_path")
        slice_count = len(_phase_slice_images(case_dir, seg_path, output_root))
        phases.append(
            {
                **phase,
                "lv_volume_ml": lv_volume,
                "raw_trigger": trigger,
                "slice_count": slice_count,
                "rv_volume_ml": _rv_volume_from_seg(seg_path),
            }
        )

    lv = sax.get("lv") or {}
    rv = sax.get("rv") or {}
    assignments = sax.get("phase_assignments") or {}
    current = {
        "label": "当前流程",
        "method": "pipeline-selected",
        "candidateCount": len(phases),
        "minSlices": None,
        "edTrigger": _round_metric(assignments.get("ED_trigger")),
        "esTrigger": _round_metric(assignments.get("ES_trigger")),
        "LVEDV": _round_metric(lv.get("EDV_ml")),
        "LVESV": _round_metric(lv.get("ESV_ml")),
        "LVEF": _round_metric(lv.get("EF_percent")),
        "RVEDV": _round_metric(rv.get("EDV_ml")),
        "RVESV": _round_metric(rv.get("ESV_ml")),
        "RVEF": _round_metric(rv.get("EF_percent")),
    }

    if len(phases) < 2:
        return {"truth": _truth_phase_result(report_truth), "current": current, "labelsystemRaw": None, "labelsystemQc": None}

    raw_ed = max(phases, key=lambda item: item["lv_volume_ml"])
    raw_es = min(phases, key=lambda item: item["lv_volume_ml"])
    raw_result = _phase_result(
        "LabelSystem裸规则",
        raw_ed,
        raw_es,
        method="contour-volume:max-min",
        candidate_count=len(phases),
    )

    max_slices = max(int(item.get("slice_count") or 0) for item in phases)
    min_slices = max(3, math.ceil(max_slices * 0.75)) if max_slices else 0
    qc_candidates = [item for item in phases if int(item.get("slice_count") or 0) >= min_slices]
    if len(qc_candidates) < 2:
        qc_candidates = phases
        min_slices = None

    qc_ed = max(qc_candidates, key=lambda item: item["lv_volume_ml"])
    qc_es = min(qc_candidates, key=lambda item: item["lv_volume_ml"])
    qc_result = _phase_result(
        "LabelSystem+层数QC",
        qc_ed,
        qc_es,
        method="contour-volume:max-min + slice-completeness>=75%",
        candidate_count=len(qc_candidates),
        min_slices=min_slices,
    )

    return {
        "truth": _truth_phase_result(report_truth),
        "current": current,
        "labelsystemRaw": raw_result,
        "labelsystemQc": qc_result,
    }


def _build_case_detail(center: str, patient_id: str, output_root: Path, run_meta: dict | None) -> dict:
    case_dir = output_root / center / patient_id
    metrics = _read_json(case_dir / "metrics.json") or {}
    report_truth = _load_report_truth(center, patient_id)
    patient_info = _read_json(case_dir / "patient_info.json")
    raw = metrics.get("raw_measurements") or {}
    sax = raw.get("sax_metrics") or {}
    four_ch = raw.get("four_ch_metrics") or {}
    phases = sax.get("all_phases") or []
    phase_assignments = sax.get("phase_assignments") or {}
    ed_trigger = phase_assignments.get("ED_trigger")
    es_trigger = phase_assignments.get("ES_trigger")

    ed_phase = next(
        (
            phase
            for phase in phases
            if phase.get("raw_trigger") == ed_trigger or phase.get("phase_name") == "ED"
        ),
        None,
    )
    es_phase = next(
        (
            phase
            for phase in phases
            if phase.get("raw_trigger") == es_trigger or phase.get("phase_name") == "ES"
        ),
        None,
    )

    preview_paths = {
        "sax": _safe_relative(case_dir / "previews" / "SAX.png", output_root),
        "fourCh": _safe_relative(case_dir / "previews" / "4CH.png", output_root),
        "lge": _safe_relative(case_dir / "previews" / "LGE.png", output_root),
    }

    normalized_phases = []
    for phase in phases:
        try:
            normalized_phases.append(
                {
                    "trigger": float(phase.get("raw_trigger")),
                    "lvVolume": float(phase.get("lv_volume_ml")),
                    "lvDiameter": _round_metric(phase.get("lv_diameter_mm")),
                    "role": phase.get("phase_name") or "",
                }
            )
        except (TypeError, ValueError):
            continue
    normalized_phases.sort(key=lambda item: item["trigger"])
    body_size = (sax.get("body_size") or {})
    indexed = (sax.get("indexed_metrics") or {})
    height_cm = _safe_float((patient_info or {}).get("height_cm")) or _safe_float(body_size.get("height_cm"))
    weight_kg = _safe_float((patient_info or {}).get("weight_kg")) or _safe_float(body_size.get("weight_kg"))
    bsa_m2 = _safe_float(body_size.get("BSA_m2")) or _compute_bsa(height_cm, weight_kg)
    lv = sax.get("lv") or {}
    rv = sax.get("rv") or {}
    four_ch_lav = four_ch.get("LA_volume_ml")
    four_ch_rav = four_ch.get("RA_volume_ml")

    return {
        "center": center,
        "runRoot": run_meta["runRoot"] if run_meta else None,
        "patientId": patient_id,
        "patientInfo": patient_info,
        "bodyMetrics": {
            "height_cm": _round_metric(height_cm),
            "weight_kg": _round_metric(weight_kg),
            "BSA": _round_metric(bsa_m2, 4),
        },
        "metrics": {
            "LVEF": _round_metric(lv.get("EF_percent")),
            "RVEF": _round_metric(rv.get("EF_percent")),
            "LVEDV": _round_metric(lv.get("EDV_ml")),
            "LVESV": _round_metric(lv.get("ESV_ml")),
            "LVEDVi": _round_metric(indexed.get("LVEDVi_ml_per_m2") or _index_volume(lv.get("EDV_ml"), bsa_m2)),
            "LVESVi": _round_metric(indexed.get("LVESVi_ml_per_m2") or _index_volume(lv.get("ESV_ml"), bsa_m2)),
            "SVi": _round_metric(indexed.get("SVi_ml_per_m2") or _index_volume(lv.get("SV_ml"), bsa_m2)),
            "RVEDV": _round_metric(rv.get("EDV_ml")),
            "RVESV": _round_metric(rv.get("ESV_ml")),
            "RVEDVi": _round_metric(indexed.get("RVEDVi_ml_per_m2") or _index_volume(rv.get("EDV_ml"), bsa_m2)),
            "RVESVi": _round_metric(indexed.get("RVESVi_ml_per_m2") or _index_volume(rv.get("ESV_ml"), bsa_m2)),
            "RVSVi": _round_metric(indexed.get("RVSVi_ml_per_m2") or _index_volume(rv.get("SV_ml"), bsa_m2)),
            "LVEDD": _round_metric((sax.get("structure") or {}).get("lv_inner_diameter_mm")),
            "RVEDD": _round_metric((sax.get("structure") or {}).get("rv_inner_diameter_mm")),
            "LAV": _round_metric(four_ch_lav),
            "RAV": _round_metric(four_ch_rav),
            "LAVi": _round_metric(_index_volume(four_ch_lav, bsa_m2)),
            "RAVi": _round_metric(_index_volume(four_ch_rav, bsa_m2)),
        },
        "phaseAssignments": {
            "saxED": ed_trigger,
            "saxES": es_trigger,
            "fourChED": four_ch.get("ED_trigger"),
            "fourChES": four_ch.get("ES_trigger"),
        },
        "reportTruth": report_truth,
        "phaseComparison": _build_phase_comparison(case_dir, sax, report_truth, output_root),
        "phases": normalized_phases,
        "warnings": metrics.get("warnings") or [],
        "images": {
            "previews": preview_paths,
            "saxEdMeasurement": _list_pngs(case_dir / "measurements" / "SAX_ED", output_root),
            "fourChMeasurement": _list_pngs(case_dir / "measurements" / "4CH_ES", output_root),
            "saxEdSlices": _phase_slice_images(case_dir, ed_phase.get("seg_path") if ed_phase else None, output_root),
            "saxEsSlices": _phase_slice_images(case_dir, es_phase.get("seg_path") if es_phase else None, output_root),
            "saxPhaseSamples": _first_pngs_by_subdir(case_dir / "segmentations" / "SAX", output_root),
        },
    }


def register_function_qc_routes(app) -> None:
    @app.route("/api/function-qc", methods=["GET"])
    @login_required
    def function_qc_index():
        run_meta = _select_run((request.args.get("runRoot") or "").strip() or None)
        if run_meta is None:
            return jsonify(
                {
                    "runRoot": None,
                    "outputRoot": None,
                    "total": 0,
                    "centers": [],
                    "centerCounts": {},
                    "availableRuns": [],
                    "cases": [],
                }
            )
        run_root = Path(run_meta["runRoot"])
        output_root = Path(run_meta["outputRoot"])
        center = (request.args.get("center") or "").strip()
        patient_id = (request.args.get("patientId") or "").strip()
        if center and patient_id:
            return jsonify(_build_case_detail(center, patient_id, output_root, run_meta))

        cases = []
        for item in _load_summary_cases(run_root, output_root):
            flags = [
                flag
                for flag in (
                    _ef_flag("LVEF", item.get("LVEF")),
                    _ef_flag("RVEF", item.get("RVEF")),
                )
                if flag
            ]
            cases.append(
                {
                    **item,
                    "LVEF": _round_metric(item.get("LVEF")),
                    "RVEF": _round_metric(item.get("RVEF")),
                    "LVEDV": _round_metric(item.get("LVEDV")),
                    "LVESV": _round_metric(item.get("LVESV")),
                    "LAV": _round_metric(item.get("LAV")),
                    "RAV": _round_metric(item.get("RAV")),
                    "status": "pass"
                    if item.get("returncode") == 0 and item.get("metrics_exists") and item.get("workflow_exists")
                    else "fail",
                    "flags": flags,
                }
            )

        return jsonify(
            {
                "runRoot": run_meta["runRoot"],
                "runLabel": run_meta["label"],
                "outputRoot": run_meta["outputRoot"],
                "total": len(cases),
                "centers": sorted({item["center"] for item in cases}),
                "centerCounts": run_meta["centerCounts"],
                "availableRuns": _discover_runs(),
                "cases": cases,
            }
        )

    @app.route("/api/function-qc/file", methods=["GET"])
    @login_required
    def function_qc_file():
        run_meta = _select_run((request.args.get("runRoot") or "").strip() or None)
        if run_meta is None:
            abort(404, "Run not found")
        rel_path = (request.args.get("path") or "").strip()
        if not rel_path:
            abort(400, "Missing path")
        output_root = Path(run_meta["outputRoot"]).resolve()
        target = (output_root / rel_path).resolve()
        try:
            target.relative_to(output_root)
        except ValueError:
            abort(403, "Invalid path")
        if not target.is_file():
            abort(404, "File not found")
        return send_file(target)
