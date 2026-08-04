from __future__ import annotations

from collections import defaultdict

import numpy as np
from skimage.filters import gaussian, threshold_otsu
from skimage.measure import label, regionprops
from skimage.morphology import binary_closing, binary_opening, disk, remove_small_objects

from ..db import get_conn
from .dicom_indexer import list_frame_rows, read_frame_pixels
from .inference import fetch_contours
from .measurements import _frame_key, _polygon_to_mask


def _segment_lv_area(image: np.ndarray, seed_center: tuple[float, float] | None) -> tuple[float, tuple[float, float] | None]:
    norm = image.astype(np.float32) / 255.0
    blurred = gaussian(norm, sigma=1.25)
    height, width = blurred.shape
    crop = blurred[height // 4 : height * 3 // 4, width // 4 : width * 3 // 4]
    threshold = max(float(threshold_otsu(crop)), float(np.quantile(crop, 0.78)))
    mask = blurred > threshold
    mask = binary_opening(mask, disk(2))
    mask = binary_closing(mask, disk(3))
    mask = remove_small_objects(mask, 100)
    components = label(mask)
    regions = regionprops(components)
    if not regions:
        return 0.0, None

    target_center = np.array([height / 2.0, width / 2.0]) if seed_center is None else np.array([seed_center[1], seed_center[0]])
    ordered = sorted(
        regions,
        key=lambda region: (
            np.linalg.norm(np.array(region.centroid) - target_center),
            -region.area,
        ),
    )
    lv_region = ordered[0]
    center = (float(lv_region.centroid[1]), float(lv_region.centroid[0]))
    return float(lv_region.area), center


def _labels_from_ventricular_phases(ed_phase: int, es_phase: int, phase_count: int) -> dict[str, int]:
    pre_a_phase = (ed_phase - 1) % max(phase_count, 1)
    return {
        "ed": ed_phase,
        "es": es_phase,
        "lv_ed": ed_phase,
        "lv_es": es_phase,
        "rv_ed": ed_phase,
        "rv_es": es_phase,
        "la_max": es_phase,
        "la_pre_a": pre_a_phase,
        "la_min": ed_phase,
        "ra_max": es_phase,
        "ra_pre_a": pre_a_phase,
        "ra_min": ed_phase,
    }


def _phase_scores_payload(scores: dict[int, float], *, score_name: str = "score") -> list[dict]:
    return [
        {"phase_index": phase, score_name: round(score, 2)}
        for phase, score in sorted(scores.items())
    ]


def _extreme_phases(scores: dict[int, float]) -> tuple[int | None, int | None]:
    if len(scores) < 2:
        return None, None
    max_phase = max(scores.items(), key=lambda item: item[1])[0]
    min_phase = min(scores.items(), key=lambda item: item[1])[0]
    return max_phase, min_phase


def _previous_phase(phase: int, available_phases: list[int]) -> int:
    if not available_phases:
        return phase
    ordered = sorted(available_phases)
    if phase not in ordered:
        return ordered[max(0, len(ordered) - 1)]
    index = ordered.index(phase)
    return ordered[index - 1] if index > 0 else ordered[-1]


def _phase_trigger_times(frames: list[dict]) -> dict[int, float]:
    values: dict[int, list[float]] = defaultdict(list)
    for frame in frames:
        trigger_time = frame.get("trigger_time")
        if trigger_time is None:
            continue
        values[int(frame["phase_index"])].append(float(trigger_time))
    return {phase: float(np.median(times)) for phase, times in values.items() if times}


def _map_phase_by_trigger(source_phase: int, source_frames: list[dict], target_frames: list[dict]) -> int | None:
    source_times = _phase_trigger_times(source_frames)
    target_times = _phase_trigger_times(target_frames)
    if source_phase not in source_times or not target_times:
        return None
    source_time = source_times[source_phase]
    return min(target_times.items(), key=lambda item: abs(item[1] - source_time))[0]


def _median_phase_interval(phase_times: dict[int, float]) -> float | None:
    ordered = [time for _, time in sorted(phase_times.items())]
    diffs = [abs(curr - prev) for prev, curr in zip(ordered, ordered[1:]) if abs(curr - prev) > 1e-6]
    if not diffs:
        return None
    return float(np.median(diffs))


def _map_phase_by_trigger_if_aligned(source_phase: int, source_frames: list[dict], target_frames: list[dict]) -> tuple[int | None, float | None]:
    source_times = _phase_trigger_times(source_frames)
    target_times = _phase_trigger_times(target_frames)
    if source_phase not in source_times or not target_times:
        return None, None
    source_time = source_times[source_phase]
    target_phase, target_time = min(target_times.items(), key=lambda item: abs(item[1] - source_time))
    delta = abs(target_time - source_time)
    intervals = [value for value in (_median_phase_interval(source_times), _median_phase_interval(target_times)) if value is not None]
    tolerance = max(20.0, min(intervals) * 0.75) if intervals else 20.0
    if delta <= tolerance:
        return target_phase, delta
    return None, delta


def _detect_sax_function_phases(series: dict, frames: list[dict]) -> dict:
    series_id = int(series["id"])
    rows = int(series["rows"] or 1)
    cols = int(series["cols"] or 1)

    contours = fetch_contours(series_id, "function") or {"frames": {}}
    contour_phase_scores: dict[int, float] = defaultdict(float)
    for frame in frames:
        frame_payload = contours.get("frames", {}).get(_frame_key(frame["slice_index"], frame["phase_index"]))
        if not frame_payload or not frame_payload.get("include", True):
            continue
        endo = _polygon_to_mask(frame_payload.get("endo"), rows, cols)
        if endo.sum() <= 0:
            continue
        contour_phase_scores[int(frame["phase_index"])] += float(endo.sum())

    if len(contour_phase_scores) >= 2:
        ed_phase = max(contour_phase_scores.items(), key=lambda item: item[1])[0]
        es_phase = min(contour_phase_scores.items(), key=lambda item: item[1])[0]
        return {
            "series_id": series_id,
            "ed_phase": ed_phase,
            "es_phase": es_phase,
            "method": "contour-volume",
            "phase_scores": _phase_scores_payload(contour_phase_scores),
            "phase_labels": _labels_from_ventricular_phases(ed_phase, es_phase, int(series["phase_count"] or 1)),
        }

    slice_indices = sorted({int(frame["slice_index"]) for frame in frames})
    if not slice_indices:
        raise ValueError("当前序列没有可分析层位。")
    center = len(slice_indices) // 2
    window = max(3, min(5, len(slice_indices)))
    start = max(0, center - window // 2)
    selected_slices = slice_indices[start : start + window]
    heuristic_phase_scores: dict[int, float] = defaultdict(float)

    for slice_index in selected_slices:
        slice_frames = sorted(
            [frame for frame in frames if int(frame["slice_index"]) == slice_index],
            key=lambda frame: int(frame["phase_index"]),
        )
        last_center: tuple[float, float] | None = None
        for frame in slice_frames:
            area, last_center = _segment_lv_area(read_frame_pixels(frame), last_center)
            if area > 0:
                heuristic_phase_scores[int(frame["phase_index"])] += area

    if len(heuristic_phase_scores) < 2:
        raise ValueError("自动识别 ED/ES 失败，建议先做一层粗勾画或 AI 分割。")

    ed_phase = max(heuristic_phase_scores.items(), key=lambda item: item[1])[0]
    es_phase = min(heuristic_phase_scores.items(), key=lambda item: item[1])[0]
    return {
        "series_id": series_id,
        "ed_phase": ed_phase,
        "es_phase": es_phase,
        "method": "heuristic-lv-area",
        "phase_scores": _phase_scores_payload(heuristic_phase_scores),
        "phase_labels": _labels_from_ventricular_phases(ed_phase, es_phase, int(series["phase_count"] or 1)),
    }


def _detect_4ch_from_contours(series: dict, frames: list[dict]) -> tuple[dict[str, int], list[dict]]:
    rows = int(series["rows"] or 1)
    cols = int(series["cols"] or 1)
    contours = fetch_contours(int(series["id"]), "function") or {"frames": {}}
    scores: dict[str, dict[int, float]] = {
        "lv": defaultdict(float),
        "rv": defaultdict(float),
        "la": defaultdict(float),
        "ra": defaultdict(float),
    }
    for frame in frames:
        frame_payload = contours.get("frames", {}).get(_frame_key(frame["slice_index"], frame["phase_index"]))
        if not frame_payload or not frame_payload.get("include", True):
            continue
        phase = int(frame["phase_index"])
        for chamber, contour_key in (("lv", "endo"), ("rv", "rv"), ("la", "la"), ("ra", "ra")):
            mask = _polygon_to_mask(frame_payload.get(contour_key), rows, cols)
            area = float(mask.sum())
            if area > 0:
                scores[chamber][phase] += area

    phase_labels: dict[str, int] = {}
    available_phases = sorted({int(frame["phase_index"]) for frame in frames})
    for chamber in ("lv", "rv"):
        max_phase, min_phase = _extreme_phases(scores[chamber])
        if max_phase is not None and min_phase is not None:
            phase_labels[f"{chamber}_ed"] = max_phase
            phase_labels[f"{chamber}_es"] = min_phase
    for chamber in ("la", "ra"):
        max_phase, min_phase = _extreme_phases(scores[chamber])
        if max_phase is not None and min_phase is not None:
            phase_labels[f"{chamber}_max"] = max_phase
            phase_labels[f"{chamber}_min"] = min_phase
            phase_labels[f"{chamber}_pre_a"] = _previous_phase(min_phase, available_phases)

    phase_scores = []
    for chamber, chamber_scores in scores.items():
        for phase, score in sorted(chamber_scores.items()):
            phase_scores.append({"phase_index": phase, "chamber": chamber, "area": round(score, 2)})
    return phase_labels, phase_scores


def _detect_4ch_heuristic(series: dict, frames: list[dict]) -> dict[int, float]:
    phase_scores: dict[int, float] = defaultdict(float)
    by_phase = sorted(frames, key=lambda frame: int(frame["phase_index"]))
    last_center: tuple[float, float] | None = None
    for frame in by_phase:
        area, last_center = _segment_lv_area(read_frame_pixels(frame), last_center)
        if area > 0:
            phase_scores[int(frame["phase_index"])] += area
    return phase_scores


def _detect_4ch_function_phases(series: dict, frames: list[dict]) -> dict:
    series_id = int(series["id"])
    phase_count = int(series["phase_count"] or 1)
    contour_labels, contour_scores = _detect_4ch_from_contours(series, frames)

    labels: dict[str, int] = dict(contour_labels)
    method_parts: list[str] = []
    if contour_labels:
        method_parts.append("4ch-contour-volume")

    with get_conn() as conn:
        sax_series = conn.execute(
            "SELECT * FROM series WHERE study_id = ? AND role = 'cine_sax' ORDER BY id LIMIT 1",
            (series["study_id"],),
        ).fetchone()

    sax_result = None
    if sax_series is not None:
        sax_frames = list_frame_rows(int(sax_series["id"]))
        if sax_frames:
            try:
                sax_result = _detect_sax_function_phases(sax_series, sax_frames)
            except ValueError:
                sax_result = None
            if sax_result:
                mapped_ed, ed_delta = _map_phase_by_trigger_if_aligned(int(sax_result["ed_phase"]), sax_frames, frames)
                mapped_es, es_delta = _map_phase_by_trigger_if_aligned(int(sax_result["es_phase"]), sax_frames, frames)
                if mapped_ed is None and int(sax_result["ed_phase"]) < phase_count:
                    mapped_ed = int(sax_result["ed_phase"])
                if mapped_es is None and int(sax_result["es_phase"]) < phase_count:
                    mapped_es = int(sax_result["es_phase"])
                if mapped_ed is not None and mapped_es is not None:
                    labels.update({
                        "lv_ed": mapped_ed,
                        "lv_es": mapped_es,
                        "rv_ed": mapped_ed,
                        "rv_es": mapped_es,
                    })
                    method_parts.insert(0, "sax-phase-sync")
                    contour_scores.extend([
                        {"phase_index": mapped_ed, "chamber": "sax_sync_ed", "area": 0.0, "time_delta_ms": round(ed_delta or 0.0, 2)},
                        {"phase_index": mapped_es, "chamber": "sax_sync_es", "area": 0.0, "time_delta_ms": round(es_delta or 0.0, 2)},
                    ])

    if "lv_ed" not in labels or "lv_es" not in labels:
        heuristic_scores = _detect_4ch_heuristic(series, frames)
        if len(heuristic_scores) >= 2:
            lv_ed, lv_es = _extreme_phases(heuristic_scores)
            if lv_ed is not None and lv_es is not None:
                labels.setdefault("lv_ed", lv_ed)
                labels.setdefault("lv_es", lv_es)
                labels.setdefault("rv_ed", lv_ed)
                labels.setdefault("rv_es", lv_es)
                method_parts.append("4ch-heuristic-lv-area")
                contour_scores.extend({"phase_index": phase, "chamber": "lv_heuristic", "area": round(score, 2)} for phase, score in sorted(heuristic_scores.items()))

    if "lv_ed" not in labels or "lv_es" not in labels:
        raise ValueError("自动识别长轴相位失败，建议先勾画一帧左室或使用 SAX 结果。")

    base_labels = _labels_from_ventricular_phases(labels["lv_ed"], labels["lv_es"], phase_count)
    for key, value in base_labels.items():
        labels.setdefault(key, value)
    labels["ed"] = labels["lv_ed"]
    labels["es"] = labels["lv_es"]

    return {
        "series_id": series_id,
        "ed_phase": labels["lv_ed"],
        "es_phase": labels["lv_es"],
        "method": "+".join(dict.fromkeys(method_parts)) or "4ch-default",
        "phase_scores": contour_scores,
        "phase_labels": labels,
    }


def detect_function_phases(series_id: int) -> dict:
    with get_conn() as conn:
        series = conn.execute("SELECT * FROM series WHERE id = ?", (series_id,)).fetchone()
    if series is None:
        raise KeyError(series_id)

    frames = list_frame_rows(series_id)
    if not frames:
        raise ValueError("当前序列没有可分析帧。")

    if series["role"] == "cine_sax":
        return _detect_sax_function_phases(series, frames)
    if series["role"] in {"cine_lax_2ch", "cine_lax_3ch", "cine_lax_4ch"}:
        return _detect_4ch_function_phases(series, frames)
    raise ValueError("快速相位识别目前只支持 cine_sax 或 cine_lax_2ch/3ch/4ch。")
