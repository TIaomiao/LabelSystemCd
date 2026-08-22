from __future__ import annotations

import csv
import math
from io import StringIO
from pathlib import Path

import numpy as np
import pydicom
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from skimage.draw import polygon2mask
from skimage.feature import graycomatrix, graycoprops
from skimage.measure import find_contours, label, regionprops
from skimage.morphology import binary_closing, binary_opening, disk, remove_small_objects
from skimage.registration import optical_flow_tvl1, phase_cross_correlation
from skimage.transform import warp

from ..config import EXPORT_DIR, RENDER_DIR
from ..db import dumps, get_conn, loads, utcnow
from .curvature import compute_curvature_from_landmarks
from .dicom_indexer import fetch_study_detail, get_frame_row, list_frame_rows, read_frame_pixels


def _frame_key(slice_index: int, phase_index: int) -> str:
    return f"{slice_index}:{phase_index}"


def _polygon_to_mask(contour: dict | None, rows: int, cols: int) -> np.ndarray:
    if not contour or not contour.get("points"):
        return np.zeros((rows, cols), dtype=bool)
    points = contour["points"]
    if len(points) < 3:
        return np.zeros((rows, cols), dtype=bool)
    polygon = np.array([(point["y"], point["x"]) for point in points], dtype=float)
    polygon[:, 0] = np.clip(polygon[:, 0], 0, rows - 1)
    polygon[:, 1] = np.clip(polygon[:, 1], 0, cols - 1)
    return polygon2mask((rows, cols), polygon)


def _exclude_to_mask(frame_payload: dict, rows: int, cols: int) -> np.ndarray:
    raw_regions = frame_payload.get("exclude_regions") if isinstance(frame_payload, dict) else None
    if isinstance(raw_regions, list):
        mask = np.zeros((rows, cols), dtype=bool)
        for contour in raw_regions:
            mask |= _polygon_to_mask(contour, rows, cols)
        return mask
    return _polygon_to_mask(frame_payload.get("exclude"), rows, cols)


def _frame_masks(frame_payload: dict, rows: int, cols: int) -> dict[str, np.ndarray]:
    return {
        "la": _polygon_to_mask(frame_payload.get("la"), rows, cols),
        "ra": _polygon_to_mask(frame_payload.get("ra"), rows, cols),
        "endo": _polygon_to_mask(frame_payload.get("endo"), rows, cols),
        "epi": _polygon_to_mask(frame_payload.get("epi"), rows, cols),
        "ventricular_epi": _polygon_to_mask(frame_payload.get("ventricular_epi"), rows, cols),
        "rv": _polygon_to_mask(frame_payload.get("rv"), rows, cols),
        "fat": _polygon_to_mask(frame_payload.get("fat"), rows, cols),
        "fat_outer": _polygon_to_mask(frame_payload.get("fat_outer"), rows, cols),
        "remote": _polygon_to_mask(frame_payload.get("remote"), rows, cols),
        "enhanced": _polygon_to_mask(frame_payload.get("enhanced"), rows, cols),
        "exclude": _exclude_to_mask(frame_payload, rows, cols),
        "mvo": _polygon_to_mask(frame_payload.get("mvo"), rows, cols),
    }


def _function_fat_masks(masks: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray, str, list[str]]:
    exclude = masks["exclude"]
    if int(masks["fat_outer"].sum()) > 0:
        inner_key = ""
        method = ""
        if int(masks["ventricular_epi"].sum()) > 0:
            inner_key = "ventricular_epi"
            method = "fat_outer_minus_ventricular_epi"
        elif int(masks["epi"].sum()) > 0:
            inner_key = "epi"
            method = "fat_outer_minus_epi"

        if inner_key:
            raw_fat = masks["fat_outer"] & ~masks[inner_key]
            exclude_mask = raw_fat & exclude
            source_keys = ["fat_outer", inner_key]
            if int(exclude_mask.sum()) > 0:
                source_keys.append("exclude")
            return raw_fat & ~exclude_mask, exclude_mask, method, source_keys

    raw_fat = masks["fat"]
    exclude_mask = raw_fat & exclude
    source_keys = ["fat"]
    if int(exclude_mask.sum()) > 0:
        source_keys.append("exclude")
    return raw_fat & ~exclude_mask, exclude_mask, "legacy_fat_roi", source_keys


def _fat_threshold_for_frame(contours: dict, frame_key: str) -> dict[str, float] | None:
    settings = contours.get("settings", {}) if isinstance(contours, dict) else {}
    threshold = settings.get("fat_threshold", {}) if isinstance(settings, dict) else {}
    if not isinstance(threshold, dict) or not threshold.get("enabled", False):
        return None
    frames = threshold.get("frames", {})
    frame_settings = frames.get(frame_key) if isinstance(frames, dict) else None
    if not isinstance(frame_settings, dict) or not frame_settings.get("enabled", True):
        return None
    try:
        lower = float(frame_settings.get("lower", 0.0))
        upper = float(frame_settings.get("upper", 255.0))
    except (TypeError, ValueError):
        return None
    return _normalize_fat_threshold_range(lower, upper)


def _normalize_fat_threshold_range(lower: float, upper: float) -> dict[str, float] | None:
    if not np.isfinite(lower) or not np.isfinite(upper):
        return None
    normalized_lower = float(np.clip(lower, 0.0, 255.0))
    normalized_upper = float(np.clip(upper, 0.0, 255.0))
    if normalized_lower > normalized_upper:
        normalized_lower, normalized_upper = normalized_upper, normalized_lower
    return {"lower": normalized_lower, "upper": normalized_upper}


def _apply_fat_intensity_threshold(
    fat_mask: np.ndarray,
    manual_exclude_mask: np.ndarray,
    image: np.ndarray,
    threshold: dict[str, float] | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    candidate_mask = fat_mask | manual_exclude_mask
    if threshold is None or image.shape[:2] != candidate_mask.shape:
        return fat_mask, manual_exclude_mask, np.zeros_like(candidate_mask), candidate_mask

    intensity_mask = (image >= threshold["lower"]) & (image <= threshold["upper"])
    threshold_exclude_mask = candidate_mask & ~intensity_mask
    effective_manual_exclude_mask = manual_exclude_mask & intensity_mask
    final_fat_mask = candidate_mask & intensity_mask & ~manual_exclude_mask
    return final_fat_mask, effective_manual_exclude_mask, threshold_exclude_mask, candidate_mask


def _mask_to_rle(mask: np.ndarray) -> dict:
    flat = np.asarray(mask, dtype=np.uint8).reshape(-1)
    padded = np.pad(flat, (1, 1), mode="constant")
    changes = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1)
    return {
        "encoding": "row_major_runs",
        "rows": int(mask.shape[0]),
        "cols": int(mask.shape[1]),
        "runs": [[int(start), int(end - start)] for start, end in zip(starts, ends)],
    }


def compute_fat_threshold_preview(
    series_id: int,
    slice_index: int,
    phase_index: int,
    lower: float,
    upper: float,
) -> dict:
    with get_conn() as conn:
        series = conn.execute("SELECT * FROM series WHERE id = ?", (series_id,)).fetchone()
    if series is None:
        raise KeyError(series_id)

    contours = _fetch_contours(series_id, "function") or {"frames": {}}
    frame_key = _frame_key(slice_index, phase_index)
    frame_payload = contours.get("frames", {}).get(frame_key) or {}
    rows = int(_row_value(series, "rows", 1) or 1)
    cols = int(_row_value(series, "cols", 1) or 1)
    spacing_x = float(_row_value(series, "pixel_spacing_x", 1.0) or 1.0)
    spacing_y = float(_row_value(series, "pixel_spacing_y", 1.0) or 1.0)
    pixel_area = spacing_x * spacing_y
    frame = get_frame_row(series_id, int(slice_index), int(phase_index))
    image = read_frame_pixels(frame).astype(np.float32)
    masks = _frame_masks(frame_payload, rows, cols)
    fat_mask, manual_exclude_mask, method, source_keys = _function_fat_masks(masks)
    threshold = _normalize_fat_threshold_range(float(lower), float(upper))
    if threshold is None:
        threshold = {"lower": 0.0, "upper": 255.0}
    final_mask, effective_manual_exclude, threshold_exclude, candidate_mask = _apply_fat_intensity_threshold(
        fat_mask,
        manual_exclude_mask,
        image,
        threshold,
    )

    candidate_values = image[candidate_mask]
    histogram_counts, histogram_edges = np.histogram(candidate_values, bins=64, range=(0.0, 256.0))

    def mask_stats(mask: np.ndarray) -> dict[str, float | int]:
        pixels = int(mask.sum())
        return {"pixel_count": pixels, "area_mm2": _round_float(pixels * pixel_area, 4)}

    return {
        "series_id": int(series_id),
        "slice_index": int(slice_index),
        "phase_index": int(phase_index),
        "frame_key": frame_key,
        "range": threshold,
        "method": f"{method}_intensity_range",
        "source_contours": source_keys,
        "histogram": {
            "counts": [int(value) for value in histogram_counts],
            "bin_edges": [_round_float(float(value), 4) for value in histogram_edges],
        },
        "stats": {
            "candidate": mask_stats(candidate_mask),
            "retained": mask_stats(final_mask),
            "threshold_excluded": mask_stats(threshold_exclude),
            "manual_excluded": mask_stats(effective_manual_exclude),
        },
        "masks": {
            "candidate": _mask_to_rle(candidate_mask),
            "retained": _mask_to_rle(final_mask),
            "threshold_excluded": _mask_to_rle(threshold_exclude),
            "manual_excluded": _mask_to_rle(effective_manual_exclude),
        },
    }


def _mask_to_polygon(mask: np.ndarray) -> dict | None:
    if int(mask.sum()) <= 0:
        return None
    contours = find_contours(mask.astype(float), 0.5)
    if not contours:
        return None
    contour = max(contours, key=len)
    if len(contour) < 3:
        return None
    return {
        "points": [
            {"x": float(np.clip(point[1], 0, mask.shape[1] - 1)), "y": float(np.clip(point[0], 0, mask.shape[0] - 1))}
            for point in contour[:: max(1, len(contour) // 240)]
        ],
        "closed": True,
    }


def _merge_mask_polygons(existing: dict | None, generated: dict | None) -> dict | None:
    return existing if existing and existing.get("points") else generated


def _update_lge_generated_contours(series_id: int, contours: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE contours SET payload_json = ?, updated_at = ? WHERE series_id = ? AND module = 'lge'",
            (dumps(contours), utcnow(), series_id),
        )


def _fetch_contours(series_id: int, module: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT payload_json FROM contours WHERE series_id = ? AND module = ?",
            (series_id, module),
        ).fetchone()
    if row is None:
        return None
    return loads(row["payload_json"], {})


def _excluded_axis_indices(contours: dict, key: str) -> set[int]:
    settings = contours.get("settings", {}) if isinstance(contours, dict) else {}
    raw_values = settings.get(key, []) if isinstance(settings, dict) else []
    values: set[int] = set()
    if not isinstance(raw_values, list):
        return values
    for value in raw_values:
        try:
            values.add(int(value))
        except (TypeError, ValueError):
            continue
    return values


def _is_frame_excluded(contours: dict, slice_index: int, phase_index: int) -> bool:
    excluded_slices = _excluded_axis_indices(contours, "excluded_slices")
    excluded_phases = _excluded_axis_indices(contours, "excluded_phases")
    return int(slice_index) in excluded_slices or int(phase_index) in excluded_phases


def _round_float(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _row_value(row, key: str, default=None):
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        getter = getattr(row, "get", None)
        if callable(getter):
            value = getter(key, default)
        else:
            value = default
    return default if value is None else value


def _histogram_entropy(values: np.ndarray, bins: int = 64) -> float | None:
    if values.size <= 0:
        return None
    values = values.astype(np.float32)
    value_min = float(values.min())
    value_max = float(values.max())
    if value_max <= value_min:
        return 0.0
    hist, _ = np.histogram(values, bins=min(bins, max(8, int(np.sqrt(values.size)) + 1)), range=(value_min, value_max))
    total = float(hist.sum())
    if total <= 0:
        return None
    probs = hist.astype(np.float64) / total
    probs = probs[probs > 0]
    if probs.size <= 0:
        return 0.0
    return float(-(probs * np.log2(probs)).sum())


def _first_order_statistics(values: np.ndarray) -> dict[str, float | None]:
    if values.size <= 0:
        return {}
    values = values.astype(np.float32)
    mean = float(values.mean())
    std = float(values.std())
    centered = values - mean
    skewness = float(np.mean(centered ** 3) / (std ** 3)) if std > 1e-6 else 0.0
    kurtosis = float(np.mean(centered ** 4) / (std ** 4) - 3.0) if std > 1e-6 else 0.0
    energy = float(np.mean(values ** 2))
    return {
        "intensity_mean": _round_float(mean),
        "intensity_std": _round_float(std),
        "intensity_min": _round_float(float(values.min())),
        "intensity_p10": _round_float(float(np.percentile(values, 10))),
        "intensity_p25": _round_float(float(np.percentile(values, 25))),
        "intensity_median": _round_float(float(np.median(values))),
        "intensity_p75": _round_float(float(np.percentile(values, 75))),
        "intensity_p90": _round_float(float(np.percentile(values, 90))),
        "intensity_max": _round_float(float(values.max())),
        "intensity_range": _round_float(float(values.max() - values.min())),
        "intensity_cv": _round_float(std / mean, 6) if abs(mean) > 1e-6 else None,
        "intensity_skewness": _round_float(skewness, 6),
        "intensity_kurtosis": _round_float(kurtosis, 6),
        "intensity_energy": _round_float(energy, 6),
        "intensity_entropy": _round_float(_histogram_entropy(values), 6),
    }


def _mask_perimeter_mm(mask: np.ndarray, spacing_y: float, spacing_x: float) -> float | None:
    if int(mask.sum()) <= 0:
        return None
    contours = find_contours(mask.astype(float), 0.5)
    if not contours:
        return None
    total = 0.0
    for contour in contours:
        if len(contour) < 2:
            continue
        closed = np.vstack([contour, contour[:1]])
        deltas = np.diff(closed, axis=0)
        dy = deltas[:, 0] * spacing_y
        dx = deltas[:, 1] * spacing_x
        total += float(np.sqrt(dy ** 2 + dx ** 2).sum())
    return total


def _shape_statistics(mask: np.ndarray, pixel_area: float, spacing_y: float, spacing_x: float) -> dict[str, float | None]:
    if int(mask.sum()) <= 0:
        return {}
    component_count = int(label(mask.astype(np.uint8), connectivity=1).max())
    labels = label(mask.astype(np.uint8), connectivity=1)
    props = regionprops(labels)
    if not props:
        return {
            "component_count": component_count,
            "perimeter_mm": _round_float(_mask_perimeter_mm(mask, spacing_y, spacing_x), 4),
        }
    largest = max(props, key=lambda prop: prop.area)
    area_mm2 = float(mask.sum()) * pixel_area
    perimeter_mm = _mask_perimeter_mm(mask, spacing_y, spacing_x)
    circularity = (4.0 * math.pi * area_mm2 / (perimeter_mm ** 2)) if perimeter_mm and perimeter_mm > 1e-6 else None
    compactness = ((perimeter_mm ** 2) / (4.0 * math.pi * area_mm2)) if perimeter_mm and area_mm2 > 1e-6 else None
    spacing_mean = (float(spacing_x) + float(spacing_y)) / 2.0
    bbox_area_mm2 = float((largest.bbox[2] - largest.bbox[0]) * (largest.bbox[3] - largest.bbox[1])) * pixel_area
    return {
        "component_count": component_count,
        "perimeter_mm": _round_float(perimeter_mm, 4),
        "circularity": _round_float(circularity, 6),
        "compactness": _round_float(compactness, 6),
        "eccentricity": _round_float(float(largest.eccentricity), 6),
        "solidity": _round_float(float(largest.solidity), 6),
        "extent": _round_float(float(largest.extent), 6),
        "major_axis_length_mm": _round_float(float(largest.major_axis_length) * spacing_mean, 4),
        "minor_axis_length_mm": _round_float(float(largest.minor_axis_length) * spacing_mean, 4),
        "bbox_area_mm2": _round_float(bbox_area_mm2, 4),
    }


def _largest_mask_major_axis_mm(mask: np.ndarray, spacing_y: float, spacing_x: float) -> float | None:
    if int(mask.sum()) <= 0:
        return None
    labels = label(mask.astype(np.uint8), connectivity=1)
    props = regionprops(labels)
    if not props:
        return None
    largest = max(props, key=lambda prop: prop.area)
    spacing_mean = (float(spacing_x) + float(spacing_y)) / 2.0
    return float(largest.major_axis_length) * spacing_mean


def _mask_principal_axis_extent_mm(mask: np.ndarray, spacing_y: float, spacing_x: float) -> float | None:
    """Estimate a region's long-axis extent in physical coordinates."""
    if int(mask.sum()) <= 1:
        return None
    labels = label(mask.astype(np.uint8), connectivity=1)
    props = regionprops(labels)
    if not props:
        return None
    largest = max(props, key=lambda prop: prop.area)
    coordinates = np.argwhere(labels == largest.label)
    if len(coordinates) <= 1:
        return None

    physical = np.column_stack(
        (
            coordinates[:, 1].astype(np.float64) * float(spacing_x),
            coordinates[:, 0].astype(np.float64) * float(spacing_y),
        )
    )
    centered = physical - physical.mean(axis=0, keepdims=True)
    covariance = np.cov(centered, rowvar=False)
    if covariance.shape != (2, 2) or not np.all(np.isfinite(covariance)):
        return None
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    principal_axis = eigenvectors[:, int(np.argmax(eigenvalues))]
    projections = centered @ principal_axis
    if projections.size <= 1 or not np.all(np.isfinite(projections)):
        return None

    # Pixel centres omit half a pixel at each end. Add one projected pixel width
    # so the extent better represents the mask boundary rather than centre span.
    projected_pixel_width = (
        abs(float(principal_axis[0])) * float(spacing_x)
        + abs(float(principal_axis[1])) * float(spacing_y)
    )
    extent = float(projections.max() - projections.min()) + projected_pixel_width
    return extent if extent > 1e-6 else None


def _left_atrial_phase_geometry(
    selected_frame_data: dict[tuple[int, int], tuple[np.ndarray, dict[str, np.ndarray]]],
    phase_index: int,
    *,
    pixel_area: float,
    spacing_y: float,
    spacing_x: float,
) -> dict[str, float | int | None] | None:
    candidates: list[dict[str, float | int | None]] = []
    for (slice_index, current_phase), (_image, masks) in selected_frame_data.items():
        if current_phase != phase_index:
            continue
        la_mask = masks.get("la")
        if la_mask is None:
            continue
        pixel_count = int(la_mask.sum())
        if pixel_count <= 0:
            continue
        area_mm2 = float(pixel_count) * pixel_area
        long_axis_mm = _mask_principal_axis_extent_mm(la_mask, spacing_y, spacing_x)
        volume_ml = (
            0.85 * area_mm2 * area_mm2 / long_axis_mm / 1000.0
            if long_axis_mm is not None and long_axis_mm > 1e-6
            else None
        )
        candidates.append(
            {
                "slice_index": int(slice_index),
                "pixel_count": pixel_count,
                "area_mm2": _round_float(area_mm2, 4),
                "perimeter_mm": _round_float(_mask_perimeter_mm(la_mask, spacing_y, spacing_x), 4),
                "long_axis_proxy_mm": _round_float(long_axis_mm, 4),
                "volume_proxy_ml": _round_float(volume_ml, 4),
            }
        )
    if not candidates:
        return None
    return max(candidates, key=lambda item: int(item["pixel_count"] or 0))


def _compute_left_atrial_strain_proxy(
    curve: list[dict],
    phase_selection: dict,
    *,
    total_phase_count: int,
) -> dict:
    by_phase = {int(item["phase_index"]): item for item in curve}
    min_phase = phase_selection.get("la_min")
    max_phase = phase_selection.get("la_max")
    pre_a_phase = phase_selection.get("la_pre_a")
    reference_perimeter = by_phase.get(min_phase, {}).get("perimeter_mm")
    reference_perimeter = (
        float(reference_perimeter)
        if isinstance(reference_perimeter, (int, float)) and float(reference_perimeter) > 1e-6
        else None
    )

    strain_curve = []
    for item in curve:
        perimeter = item.get("perimeter_mm")
        strain = _strain_percent(
            float(perimeter) if isinstance(perimeter, (int, float)) else None,
            reference_perimeter,
        )
        strain_curve.append(
            {
                "phase_index": int(item["phase_index"]),
                "time_ms": item.get("time_ms"),
                "slice_index": item.get("slice_index"),
                "perimeter_mm": perimeter,
                "longitudinal_strain_proxy_percent": _round_float(strain, 4),
            }
        )

    reservoir = _metric_at_phase(strain_curve, max_phase, "longitudinal_strain_proxy_percent") if max_phase is not None else None
    pre_a_strain = _metric_at_phase(strain_curve, pre_a_phase, "longitudinal_strain_proxy_percent") if pre_a_phase is not None else None
    conduit = reservoir - pre_a_strain if reservoir is not None and pre_a_strain is not None else None
    contractile = pre_a_strain if pre_a_strain is not None else None
    if conduit is not None and conduit < -1e-6:
        conduit = None
    if reservoir is not None and reservoir < -1e-6:
        reservoir = None
    if contractile is not None and contractile < -1e-6:
        contractile = None

    missing = []
    if reference_perimeter is None:
        missing.append("la_min_perimeter")
    if max_phase is None:
        missing.append("la_max")
    if pre_a_phase is None:
        missing.append("la_pre_a")
    if len(curve) < max(int(total_phase_count), 0):
        missing.append("full_cycle_la_contours")

    return {
        "method": "la_endocardial_contour_perimeter_change_proxy",
        "reference_phase": min_phase,
        "reference": "la_min",
        "formula": "(perimeter_phase - perimeter_la_min) / perimeter_la_min * 100",
        "summary": {
            "reservoir_strain_proxy_percent": _round_float(reservoir, 4),
            "conduit_strain_proxy_percent": _round_float(conduit, 4),
            "contractile_strain_proxy_percent": _round_float(contractile, 4),
            "pre_a_strain_proxy_percent": _round_float(pre_a_strain, 4),
        },
        "curve": strain_curve,
        "quality": {
            "status": "complete" if reservoir is not None and conduit is not None and contractile is not None else ("partial" if reservoir is not None else "unavailable"),
            "usable_phase_count": sum(
                1 for item in strain_curve if isinstance(item.get("longitudinal_strain_proxy_percent"), (int, float))
            ),
            "total_phase_count": max(int(total_phase_count), 0),
            "material_point_tracking": False,
            "missing": missing,
        },
    }


def _compute_left_atrial_function(
    selected_frame_data: dict[tuple[int, int], tuple[np.ndarray, dict[str, np.ndarray]]],
    *,
    role: str,
    phase_labels: dict,
    total_phase_count: int,
    pixel_area: float,
    spacing_y: float,
    spacing_x: float,
    phase_times_ms: dict[int, float | None] | None = None,
) -> dict | None:
    role = str(role or "unknown")
    if role not in {"cine_lax_2ch", "cine_lax_4ch"}:
        return None

    annotated_phases = sorted(
        {
            int(phase_index)
            for (_slice_index, phase_index), (_image, masks) in selected_frame_data.items()
            if masks.get("la") is not None and int(masks["la"].sum()) > 0
        }
    )
    curve = []
    for phase_index in annotated_phases:
        geometry = _left_atrial_phase_geometry(
            selected_frame_data,
            phase_index,
            pixel_area=pixel_area,
            spacing_y=spacing_y,
            spacing_x=spacing_x,
        )
        if geometry is None:
            continue
        curve.append(
            {
                "phase_index": phase_index,
                "time_ms": _round_float((phase_times_ms or {}).get(phase_index), 4),
                **geometry,
            }
        )

    by_phase = {int(item["phase_index"]): item for item in curve}

    def saved_phase(label_name: str) -> int | None:
        raw_value = phase_labels.get(label_name) if isinstance(phase_labels, dict) else None
        if isinstance(raw_value, bool):
            return None
        try:
            phase_index = int(raw_value)
        except (TypeError, ValueError):
            return None
        return phase_index if phase_index in by_phase else None

    def phase_score(item: dict) -> float:
        volume = item.get("volume_proxy_ml")
        if isinstance(volume, (int, float)):
            return float(volume)
        return float(item.get("area_mm2") or 0.0)

    max_phase = saved_phase("la_max")
    min_phase = saved_phase("la_min")
    pre_a_phase = saved_phase("la_pre_a")
    phase_sources = {
        "max": "saved_phase_label" if max_phase is not None else None,
        "pre_a": "saved_phase_label" if pre_a_phase is not None else None,
        "min": "saved_phase_label" if min_phase is not None else None,
    }
    if len(curve) >= 2:
        if max_phase is None:
            max_phase = int(max(curve, key=phase_score)["phase_index"])
            phase_sources["max"] = "derived_from_annotated_la_curve"
        if min_phase is None:
            min_phase = int(min(curve, key=phase_score)["phase_index"])
            phase_sources["min"] = "derived_from_annotated_la_curve"

    def volume_at(phase_index: int | None) -> float | None:
        if phase_index is None:
            return None
        value = by_phase.get(phase_index, {}).get("volume_proxy_ml")
        return float(value) if isinstance(value, (int, float)) else None

    max_volume = volume_at(max_phase)
    pre_a_volume = volume_at(pre_a_phase)
    min_volume = volume_at(min_phase)
    distinct_max_min = max_phase is not None and min_phase is not None and max_phase != min_phase

    def ordered_difference(upper: float | None, lower: float | None) -> float | None:
        if upper is None or lower is None:
            return None
        difference = float(upper) - float(lower)
        return difference if difference >= -1e-6 else None

    def fraction(numerator: float | None, denominator: float | None) -> float | None:
        if numerator is None or denominator is None or abs(float(denominator)) <= 1e-6:
            return None
        return float(numerator) / float(denominator) * 100.0

    total_emptying_volume = ordered_difference(max_volume, min_volume) if distinct_max_min else None
    passive_emptying_volume = ordered_difference(max_volume, pre_a_volume)
    active_emptying_volume = ordered_difference(pre_a_volume, min_volume)
    summary = {
        "lav_max_ml": _round_float(max_volume, 4),
        "lav_pre_a_ml": _round_float(pre_a_volume, 4),
        "lav_min_ml": _round_float(min_volume, 4),
        "total_emptying_volume_ml": _round_float(total_emptying_volume, 4),
        "total_emptying_fraction_percent": _round_float(fraction(total_emptying_volume, max_volume), 4),
        "passive_emptying_volume_ml": _round_float(passive_emptying_volume, 4),
        "passive_emptying_fraction_percent": _round_float(fraction(passive_emptying_volume, max_volume), 4),
        "active_emptying_volume_ml": _round_float(active_emptying_volume, 4),
        "active_emptying_fraction_percent": _round_float(fraction(active_emptying_volume, pre_a_volume), 4),
    }

    missing: list[str] = []
    if not curve:
        missing.append("la_contours")
    if max_phase is None:
        missing.append("la_max")
    if pre_a_phase is None:
        missing.append("la_pre_a")
    if min_phase is None:
        missing.append("la_min")
    if max_phase is not None and min_phase is not None and max_phase == min_phase:
        missing.append("distinct_la_max_min")
    volume_order_checks = {
        "max_ge_min": None if max_volume is None or min_volume is None else max_volume >= min_volume - 1e-6,
        "max_ge_pre_a": None if max_volume is None or pre_a_volume is None else max_volume >= pre_a_volume - 1e-6,
        "pre_a_ge_min": None if pre_a_volume is None or min_volume is None else pre_a_volume >= min_volume - 1e-6,
    }
    completed_order_checks = [value for value in volume_order_checks.values() if value is not None]
    volume_order_valid = all(completed_order_checks) if completed_order_checks else None
    if volume_order_valid is False:
        missing.append("la_volume_order")
    full_cycle_complete = total_phase_count > 0 and len(curve) >= total_phase_count
    if not full_cycle_complete:
        missing.append("full_cycle_la_contours")

    has_total_function = summary["total_emptying_fraction_percent"] is not None
    has_three_phase_function = (
        has_total_function
        and summary["passive_emptying_fraction_percent"] is not None
        and summary["active_emptying_fraction_percent"] is not None
    )
    if volume_order_valid is False:
        status = "invalid_volume_order"
    elif not curve:
        status = "unavailable"
    elif has_three_phase_function:
        status = "key_phases_complete"
    elif has_total_function:
        status = "max_min_complete"
    else:
        status = "partial"

    phase_selection = {
        "la_max": max_phase,
        "la_pre_a": pre_a_phase,
        "la_min": min_phase,
        "sources": phase_sources,
    }
    strain_proxy = _compute_left_atrial_strain_proxy(
        curve,
        phase_selection,
        total_phase_count=total_phase_count,
    )
    return {
        "method": "single_plane_area_length_proxy",
        "formula": "0.85 * area_mm2^2 / long_axis_proxy_mm / 1000",
        "role": role,
        "landmark_source": "la_mask_principal_axis_extent_proxy",
        "phase_selection": phase_selection,
        "summary": summary,
        "curve": curve,
        "strain_proxy": strain_proxy,
        "quality": {
            "status": status,
            "annotated_phase_count": len(curve),
            "total_phase_count": max(int(total_phase_count), 0),
            "full_cycle_complete": full_cycle_complete,
            "volume_order_valid": volume_order_valid,
            "volume_order_checks": volume_order_checks,
            "missing": missing,
            "biplane": False,
            "bsa_indexed": False,
        },
    }


def _left_atrial_indexing_settings(contours: dict) -> dict:
    settings = contours.get("settings", {}) if isinstance(contours, dict) else {}
    config = settings.get("left_atrial_function", {}) if isinstance(settings, dict) else {}
    raw_bsa = config.get("bsa_m2") if isinstance(config, dict) else None
    try:
        bsa_m2 = float(raw_bsa)
    except (TypeError, ValueError):
        bsa_m2 = None
    if bsa_m2 is None or not np.isfinite(bsa_m2) or not 0.5 <= bsa_m2 <= 3.5:
        bsa_m2 = None
    return {
        "bsa_m2": _round_float(bsa_m2, 4),
        "bsa_source": "manual" if bsa_m2 is not None else None,
        "status": "ready" if bsa_m2 is not None else "missing_bsa",
    }


def _left_atrial_curve_item(function_payload: dict | None, phase_label: str) -> dict | None:
    if not isinstance(function_payload, dict):
        return None
    phase = function_payload.get("phase_selection", {}).get(phase_label)
    if phase is None:
        return None
    for item in function_payload.get("curve", []):
        if item.get("phase_index") == phase:
            return item
    return None


def _compute_biplane_left_atrial_function(
    four_ch: dict,
    two_ch: dict | None,
    *,
    four_ch_series_id: int,
    two_ch_series_id: int | None,
    indexing: dict,
) -> dict:
    base = {
        "method": "biplane_area_length",
        "formula": "0.85 * area_4ch_mm2 * area_2ch_mm2 / min(long_axis_4ch_mm, long_axis_2ch_mm) / 1000",
        "source_series": {
            "cine_lax_4ch": int(four_ch_series_id),
            "cine_lax_2ch": int(two_ch_series_id) if two_ch_series_id is not None else None,
        },
        "indexing": indexing,
    }
    if not isinstance(two_ch, dict) or not two_ch.get("curve"):
        return {
            **base,
            "status": "missing_2ch",
            "summary": {},
            "phase_measurements": [],
            "quality": {"missing": ["cine_lax_2ch_contours"]},
        }

    phase_measurements = []
    missing = []
    for label_name in ("la_max", "la_pre_a", "la_min"):
        four_item = _left_atrial_curve_item(four_ch, label_name)
        two_item = _left_atrial_curve_item(two_ch, label_name)
        match_method = "semantic_phase_label"
        if two_item is None and four_item is not None:
            four_time = four_item.get("time_ms")
            timed_candidates = [
                item
                for item in two_ch.get("curve", [])
                if isinstance(item.get("time_ms"), (int, float)) and isinstance(four_time, (int, float))
            ]
            if timed_candidates:
                candidate = min(timed_candidates, key=lambda item: abs(float(item["time_ms"]) - float(four_time)))
                ordered_times = sorted(float(item["time_ms"]) for item in timed_candidates)
                intervals = [
                    current - previous
                    for previous, current in zip(ordered_times, ordered_times[1:])
                    if current - previous > 1e-6
                ]
                tolerance = max(20.0, float(np.median(intervals)) * 0.75) if intervals else 20.0
                if abs(float(candidate["time_ms"]) - float(four_time)) <= tolerance:
                    two_item = candidate
                    match_method = "nearest_trigger_time"
            else:
                same_index = [
                    item for item in two_ch.get("curve", [])
                    if item.get("phase_index") == four_item.get("phase_index")
                ]
                if same_index:
                    two_item = same_index[0]
                    match_method = "same_phase_index"
        if four_item is None or two_item is None:
            missing.append(label_name)
            continue
        area_4ch = four_item.get("area_mm2")
        area_2ch = two_item.get("area_mm2")
        long_axis_4ch = four_item.get("long_axis_proxy_mm")
        long_axis_2ch = two_item.get("long_axis_proxy_mm")
        if not all(isinstance(value, (int, float)) and float(value) > 1e-6 for value in (area_4ch, area_2ch, long_axis_4ch, long_axis_2ch)):
            missing.append(f"{label_name}_geometry")
            continue
        limiting_long_axis = min(float(long_axis_4ch), float(long_axis_2ch))
        volume_ml = 0.85 * float(area_4ch) * float(area_2ch) / limiting_long_axis / 1000.0
        bsa_m2 = indexing.get("bsa_m2")
        volume_index_ml_m2 = volume_ml / float(bsa_m2) if isinstance(bsa_m2, (int, float)) and bsa_m2 > 1e-6 else None
        phase_measurements.append(
            {
                "phase_label": label_name,
                "four_ch_phase": four_item.get("phase_index"),
                "two_ch_phase": two_item.get("phase_index"),
                "phase_match_method": match_method,
                "area_4ch_mm2": _round_float(float(area_4ch), 4),
                "area_2ch_mm2": _round_float(float(area_2ch), 4),
                "long_axis_4ch_mm": _round_float(float(long_axis_4ch), 4),
                "long_axis_2ch_mm": _round_float(float(long_axis_2ch), 4),
                "limiting_long_axis_mm": _round_float(limiting_long_axis, 4),
                "volume_ml": _round_float(volume_ml, 4),
                "volume_index_ml_m2": _round_float(volume_index_ml_m2, 4),
            }
        )

    by_label = {item["phase_label"]: item for item in phase_measurements}
    max_volume = by_label.get("la_max", {}).get("volume_ml")
    pre_a_volume = by_label.get("la_pre_a", {}).get("volume_ml")
    min_volume = by_label.get("la_min", {}).get("volume_ml")

    def ordered_difference(upper, lower):
        if not isinstance(upper, (int, float)) or not isinstance(lower, (int, float)):
            return None
        value = float(upper) - float(lower)
        return value if value >= -1e-6 else None

    def fraction(numerator, denominator):
        if numerator is None or not isinstance(denominator, (int, float)) or abs(float(denominator)) <= 1e-6:
            return None
        return float(numerator) / float(denominator) * 100.0

    total_volume = ordered_difference(max_volume, min_volume)
    passive_volume = ordered_difference(max_volume, pre_a_volume)
    active_volume = ordered_difference(pre_a_volume, min_volume)
    volume_order_valid = all(
        value is None or value >= -1e-6
        for value in (
            (float(max_volume) - float(min_volume)) if isinstance(max_volume, (int, float)) and isinstance(min_volume, (int, float)) else None,
            (float(max_volume) - float(pre_a_volume)) if isinstance(max_volume, (int, float)) and isinstance(pre_a_volume, (int, float)) else None,
            (float(pre_a_volume) - float(min_volume)) if isinstance(pre_a_volume, (int, float)) and isinstance(min_volume, (int, float)) else None,
        )
    )
    if not volume_order_valid:
        missing.append("la_volume_order")

    summary = {
        "lav_max_ml": _round_float(max_volume, 4),
        "lav_pre_a_ml": _round_float(pre_a_volume, 4),
        "lav_min_ml": _round_float(min_volume, 4),
        "lavi_max_ml_m2": by_label.get("la_max", {}).get("volume_index_ml_m2"),
        "lavi_pre_a_ml_m2": by_label.get("la_pre_a", {}).get("volume_index_ml_m2"),
        "lavi_min_ml_m2": by_label.get("la_min", {}).get("volume_index_ml_m2"),
        "total_emptying_volume_ml": _round_float(total_volume, 4),
        "total_emptying_fraction_percent": _round_float(fraction(total_volume, max_volume), 4),
        "passive_emptying_volume_ml": _round_float(passive_volume, 4),
        "passive_emptying_fraction_percent": _round_float(fraction(passive_volume, max_volume), 4),
        "active_emptying_volume_ml": _round_float(active_volume, 4),
        "active_emptying_fraction_percent": _round_float(fraction(active_volume, pre_a_volume), 4),
    }
    if not volume_order_valid:
        for key in (
            "total_emptying_volume_ml", "total_emptying_fraction_percent",
            "passive_emptying_volume_ml", "passive_emptying_fraction_percent",
            "active_emptying_volume_ml", "active_emptying_fraction_percent",
        ):
            summary[key] = None

    has_max_min = summary["lav_max_ml"] is not None and summary["lav_min_ml"] is not None
    has_three_phases = has_max_min and summary["lav_pre_a_ml"] is not None
    status = "invalid_volume_order" if not volume_order_valid else ("key_phases_complete" if has_three_phases else ("max_min_complete" if has_max_min else "partial"))
    return {
        **base,
        "status": status,
        "summary": summary,
        "phase_measurements": phase_measurements,
        "quality": {
            "missing": list(dict.fromkeys(missing)),
            "volume_order_valid": volume_order_valid,
            "bsa_indexed": indexing.get("status") == "ready",
        },
    }


def _load_left_atrial_function_for_series(series) -> tuple[dict | None, dict]:
    series_id = int(_row_value(series, "id", 0) or 0)
    contours = _fetch_contours(series_id, "function") or {"frames": {}}
    rows = int(_row_value(series, "rows", 1) or 1)
    cols = int(_row_value(series, "cols", 1) or 1)
    spacing_x = float(_row_value(series, "pixel_spacing_x", 1.0) or 1.0)
    spacing_y = float(_row_value(series, "pixel_spacing_y", 1.0) or 1.0)
    frames = list_frame_rows(series_id)
    empty_image = np.zeros((rows, cols), dtype=np.float32)
    selected_frame_data = {}
    phase_trigger_times: dict[int, list[float]] = {}
    for frame in frames:
        slice_index = int(frame["slice_index"])
        phase_index = int(frame["phase_index"])
        frame_payload = contours.get("frames", {}).get(_frame_key(slice_index, phase_index))
        if not frame_payload or not frame_payload.get("include", True):
            continue
        if _is_frame_excluded(contours, slice_index, phase_index):
            continue
        masks = _frame_masks(frame_payload, rows, cols)
        if int(masks["la"].sum()) <= 0:
            continue
        selected_frame_data[(slice_index, phase_index)] = (empty_image, {"la": masks["la"]})
        trigger_time = _row_value(frame, "trigger_time", None)
        if trigger_time is not None:
            try:
                phase_trigger_times.setdefault(phase_index, []).append(float(trigger_time))
            except (TypeError, ValueError):
                pass
    phase_times_ms = {
        phase: (sum(values) / len(values) if values else None)
        for phase, values in phase_trigger_times.items()
    }
    function_payload = _compute_left_atrial_function(
        selected_frame_data,
        role=str(_row_value(series, "role", "unknown")),
        phase_labels=contours.get("phase_labels", {}),
        total_phase_count=int(_row_value(series, "phase_count", 0) or 0),
        pixel_area=spacing_x * spacing_y,
        spacing_y=spacing_y,
        spacing_x=spacing_x,
        phase_times_ms=phase_times_ms,
    )
    return function_payload, contours


def _compute_left_atrial_biplane_for_series(series, contours: dict, four_ch: dict) -> dict:
    series_id = int(_row_value(series, "id", 0) or 0)
    indexing = _left_atrial_indexing_settings(contours)
    study_id = _row_value(series, "study_id", None)
    if study_id is None:
        return _compute_biplane_left_atrial_function(
            four_ch,
            None,
            four_ch_series_id=series_id,
            two_ch_series_id=None,
            indexing=indexing,
        )
    with get_conn() as conn:
        two_ch_series = conn.execute(
            "SELECT * FROM series WHERE study_id = ? AND role = 'cine_lax_2ch' AND id != ? ORDER BY id LIMIT 1",
            (int(study_id), series_id),
        ).fetchone()
    if two_ch_series is None:
        return _compute_biplane_left_atrial_function(
            four_ch,
            None,
            four_ch_series_id=series_id,
            two_ch_series_id=None,
            indexing=indexing,
        )
    two_ch_function, _two_ch_contours = _load_left_atrial_function_for_series(two_ch_series)
    return _compute_biplane_left_atrial_function(
        four_ch,
        two_ch_function,
        four_ch_series_id=series_id,
        two_ch_series_id=int(two_ch_series["id"]),
        indexing=indexing,
    )


def _phase_lv_geometry(
    selected_frame_data: dict[tuple[int, int], tuple[np.ndarray, dict[str, np.ndarray]]],
    phase_index: int,
    *,
    pixel_area: float,
    spacing_y: float,
    spacing_x: float,
) -> dict[str, float | int | None]:
    endo_area_mm2 = 0.0
    epi_area_mm2 = 0.0
    endo_perimeter_mm = 0.0
    long_axis_values: list[float] = []
    endo_frame_count = 0
    epi_frame_count = 0

    for (_slice_index, current_phase), (_image, masks) in selected_frame_data.items():
        if current_phase != phase_index:
            continue
        endo = masks.get("endo")
        if endo is not None and int(endo.sum()) > 0:
            endo_frame_count += 1
            endo_area_mm2 += float(endo.sum()) * pixel_area
            perimeter = _mask_perimeter_mm(endo, spacing_y, spacing_x)
            if perimeter:
                endo_perimeter_mm += float(perimeter)
            long_axis = _largest_mask_major_axis_mm(endo, spacing_y, spacing_x)
            if long_axis:
                long_axis_values.append(float(long_axis))

        epi = masks.get("epi")
        if epi is not None and int(epi.sum()) > 0:
            epi_frame_count += 1
            epi_area_mm2 += float(epi.sum()) * pixel_area

    wall_area_mm2 = max(epi_area_mm2 - endo_area_mm2, 0.0) if epi_frame_count and endo_frame_count else None
    wall_thickness_proxy_mm = (wall_area_mm2 / endo_perimeter_mm) if wall_area_mm2 is not None and endo_perimeter_mm > 1e-6 else None

    return {
        "endo_frame_count": endo_frame_count,
        "epi_frame_count": epi_frame_count,
        "endo_area_mm2": _round_float(endo_area_mm2, 4) if endo_frame_count else None,
        "epi_area_mm2": _round_float(epi_area_mm2, 4) if epi_frame_count else None,
        "endo_perimeter_mm": _round_float(endo_perimeter_mm, 4) if endo_perimeter_mm > 1e-6 else None,
        "wall_thickness_proxy_mm": _round_float(wall_thickness_proxy_mm, 4),
        "long_axis_proxy_mm": _round_float(max(long_axis_values), 4) if long_axis_values else None,
    }


def _strain_percent(value: float | None, reference: float | None) -> float | None:
    if value is None or reference is None or abs(reference) <= 1e-6:
        return None
    return ((float(value) - float(reference)) / float(reference)) * 100.0


def _metric_at_phase(curve: list[dict], phase_index: int, key: str) -> float | None:
    for item in curve:
        if item.get("phase_index") == phase_index:
            value = item.get(key)
            return float(value) if isinstance(value, (int, float)) else None
    return None


def _compute_lv_2d_strain_proxy(
    selected_frame_data: dict[tuple[int, int], tuple[np.ndarray, dict[str, np.ndarray]]],
    phase_indices: list[int],
    *,
    role: str,
    ed_phase: int,
    es_phase: int,
    pixel_area: float,
    spacing_y: float,
    spacing_x: float,
    phase_times_ms: dict[int, float | None] | None = None,
) -> dict:
    geometries = {
        phase: _phase_lv_geometry(
            selected_frame_data,
            phase,
            pixel_area=pixel_area,
            spacing_y=spacing_y,
            spacing_x=spacing_x,
        )
        for phase in phase_indices
    }
    ed_geometry = geometries.get(ed_phase, {})
    role = str(role or "unknown")
    compute_sax = role in {"cine_sax", "unknown"}
    compute_lax = role in {"cine_lax_4ch", "cine_lax_2ch", "cine_lax_3ch", "unknown"}
    ed_perimeter = ed_geometry.get("endo_perimeter_mm") if compute_sax else None
    ed_thickness = ed_geometry.get("wall_thickness_proxy_mm") if compute_sax else None
    ed_long_axis = ed_geometry.get("long_axis_proxy_mm") if compute_lax else None

    curve = []
    usable_phase_count = 0
    for phase in phase_indices:
        geometry = geometries.get(phase, {})
        gcs = _strain_percent(geometry.get("endo_perimeter_mm"), ed_perimeter)
        grs = _strain_percent(geometry.get("wall_thickness_proxy_mm"), ed_thickness)
        gls = _strain_percent(geometry.get("long_axis_proxy_mm"), ed_long_axis)
        if any(value is not None for value in (gcs, grs, gls)):
            usable_phase_count += 1
        curve.append(
            {
                "phase_index": phase,
                "time_ms": _round_float((phase_times_ms or {}).get(phase), 4),
                "gcs_proxy_percent": _round_float(gcs, 4),
                "grs_proxy_percent": _round_float(grs, 4),
                "gls_proxy_percent": _round_float(gls, 4),
                "geometry": geometry,
            }
        )

    def values_for(key: str) -> list[float]:
        values: list[float] = []
        for item in curve:
            value = item.get(key)
            if isinstance(value, (int, float)):
                values.append(float(value))
        return values

    gcs_values = values_for("gcs_proxy_percent")
    grs_values = values_for("grs_proxy_percent")
    gls_values = values_for("gls_proxy_percent")
    summary = {
        "gcs_peak_percent": _round_float(min(gcs_values), 4) if gcs_values else None,
        "gcs_es_percent": _round_float(_metric_at_phase(curve, es_phase, "gcs_proxy_percent"), 4),
        "grs_peak_percent": _round_float(max(grs_values), 4) if grs_values else None,
        "grs_es_percent": _round_float(_metric_at_phase(curve, es_phase, "grs_proxy_percent"), 4),
        "gls_peak_percent": _round_float(min(gls_values), 4) if gls_values else None,
        "gls_es_percent": _round_float(_metric_at_phase(curve, es_phase, "gls_proxy_percent"), 4),
    }

    missing: list[str] = []
    if compute_sax and ed_perimeter is None:
        missing.append("ed_endo_perimeter")
    if compute_sax and ed_thickness is None:
        missing.append("ed_epi_or_wall_thickness")
    if compute_lax and ed_long_axis is None:
        missing.append("ed_long_axis")
    if len(phase_indices) < 2:
        missing.append("multi_phase")

    quality = {
        "usable_phase_count": usable_phase_count,
        "total_phase_count": len(phase_indices),
        "missing_reference": missing,
        "clinical_grade": False,
        "notes": [
            "Experimental 2D geometry proxy based on manual contours.",
            "Not feature-tracking or clinical-grade myocardial strain.",
        ],
    }
    return {
        "method": "experimental_2d_geometry_proxy",
        "role": role,
        "ed_phase": ed_phase,
        "es_phase": es_phase,
        "summary": summary,
        "curve": curve,
        "quality": quality,
    }


def _normalize_tracking_image(image: np.ndarray) -> np.ndarray:
    normalized = image.astype(np.float32)
    finite = normalized[np.isfinite(normalized)]
    if finite.size <= 0:
        return np.zeros_like(normalized, dtype=np.float32)
    low, high = np.percentile(finite, [2, 98])
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        low = float(finite.min())
        high = float(finite.max())
    if high <= low:
        return np.zeros_like(normalized, dtype=np.float32)
    normalized = np.clip((normalized - low) / (high - low), 0.0, 1.0)
    return normalized.astype(np.float32)


def _shift_image_for_tracking(image: np.ndarray, row_shift: float, col_shift: float, *, order: int) -> np.ndarray:
    rows, cols = image.shape[:2]
    row_coords, col_coords = np.meshgrid(
        np.arange(rows, dtype=np.float32),
        np.arange(cols, dtype=np.float32),
        indexing="ij",
    )
    sample_coords = np.array([row_coords - float(row_shift), col_coords - float(col_shift)])
    return warp(image, sample_coords, order=order, preserve_range=True, mode="edge").astype(image.dtype, copy=False)


def _prepare_tvl1_tracking(
    source_image: np.ndarray,
    target_image: np.ndarray,
) -> dict | None:
    reference = _normalize_tracking_image(target_image)
    moving = _normalize_tracking_image(source_image)
    phase_shift_row = 0.0
    phase_shift_col = 0.0
    if float(reference.max() - reference.min()) > 1e-6 and float(moving.max() - moving.min()) > 1e-6:
        try:
            shift, _, _ = phase_cross_correlation(reference, moving, upsample_factor=10)
            if np.isfinite(shift[0]) and np.isfinite(shift[1]):
                phase_shift_row = float(shift[0])
                phase_shift_col = float(shift[1])
                if abs(phase_shift_row) > 0.01 or abs(phase_shift_col) > 0.01:
                    moving = _shift_image_for_tracking(moving, phase_shift_row, phase_shift_col, order=1)
        except Exception:
            pass

    try:
        flow = optical_flow_tvl1(reference, moving, attachment=10.0, tightness=0.25)
    except Exception:
        return None

    row_coords, col_coords = np.meshgrid(
        np.arange(reference.shape[0], dtype=np.float32),
        np.arange(reference.shape[1], dtype=np.float32),
        indexing="ij",
    )
    sample_coords = np.array([row_coords + flow[0], col_coords + flow[1]])
    return {
        "flow": flow,
        "sample_coords": sample_coords,
        "phase_shift_row_px": phase_shift_row,
        "phase_shift_col_px": phase_shift_col,
    }


def _warp_mask_with_tracking_field(
    source_mask: np.ndarray,
    tracking_field: dict,
) -> tuple[np.ndarray, dict[str, float | None]]:
    phase_shift_row = float(tracking_field.get("phase_shift_row_px") or 0.0)
    phase_shift_col = float(tracking_field.get("phase_shift_col_px") or 0.0)
    if abs(phase_shift_row) > 0.01 or abs(phase_shift_col) > 0.01:
        source_mask = _shift_image_for_tracking(
            source_mask.astype(np.float32),
            phase_shift_row,
            phase_shift_col,
            order=0,
        ) >= 0.5

    warped = warp(
        source_mask.astype(np.float32),
        tracking_field["sample_coords"],
        order=0,
        preserve_range=True,
        mode="edge",
    ) >= 0.5
    warped = binary_closing(warped, disk(1))
    warped = binary_opening(warped, disk(1))
    warped = remove_small_objects(warped.astype(bool), 8)

    flow = tracking_field["flow"]
    flow_mag = np.sqrt(np.square(flow[0]) + np.square(flow[1]))
    mask_for_flow = source_mask.astype(bool)
    mean_flow = float(flow_mag[mask_for_flow].mean()) if int(mask_for_flow.sum()) > 0 else None
    return warped.astype(bool), {
        "phase_shift_row_px": _round_float(phase_shift_row, 4),
        "phase_shift_col_px": _round_float(phase_shift_col, 4),
        "mean_flow_px": _round_float(mean_flow, 4),
    }


def _warp_mask_with_tvl1(
    source_mask: np.ndarray,
    source_image: np.ndarray,
    target_image: np.ndarray,
) -> tuple[np.ndarray | None, dict[str, float | None]]:
    """Compatibility wrapper for callers that track one mask at a time."""
    tracking_field = _prepare_tvl1_tracking(source_image, target_image)
    if tracking_field is None:
        return None, {
            "phase_shift_row_px": None,
            "phase_shift_col_px": None,
            "mean_flow_px": None,
        }
    return _warp_mask_with_tracking_field(source_mask, tracking_field)


def _mask_dice(mask_a: np.ndarray, mask_b: np.ndarray) -> float | None:
    area_a = int(mask_a.sum())
    area_b = int(mask_b.sum())
    if area_a <= 0 and area_b <= 0:
        return None
    denom = area_a + area_b
    if denom <= 0:
        return None
    return (2.0 * float((mask_a & mask_b).sum())) / float(denom)


def _mask_boundary_points(mask: np.ndarray) -> np.ndarray:
    contours = find_contours(mask.astype(float), 0.5)
    if not contours:
        return np.empty((0, 2), dtype=np.float32)
    contour = max(contours, key=len)
    if len(contour) > 160:
        indices = np.linspace(0, len(contour) - 1, num=160, dtype=int)
        contour = contour[indices]
    return np.asarray(contour, dtype=np.float32)


def _mean_boundary_distance_mm(
    predicted_mask: np.ndarray,
    target_mask: np.ndarray,
    *,
    spacing_y: float,
    spacing_x: float,
) -> float | None:
    predicted_points = _mask_boundary_points(predicted_mask)
    target_points = _mask_boundary_points(target_mask)
    if len(predicted_points) == 0 or len(target_points) == 0:
        return None
    scale = np.array([float(spacing_y), float(spacing_x)], dtype=np.float32)
    predicted_mm = predicted_points * scale
    target_mm = target_points * scale
    distances = []
    chunk_size = 64
    for start in range(0, len(predicted_mm), chunk_size):
        chunk = predicted_mm[start : start + chunk_size]
        diff = chunk[:, None, :] - target_mm[None, :, :]
        distances.append(np.sqrt(np.sum(np.square(diff), axis=2)).min(axis=1))
    if not distances:
        return None
    return float(np.concatenate(distances).mean())


def _compute_lv_tracking_validation(
    selected_frame_data: dict[tuple[int, int], tuple[np.ndarray, dict[str, np.ndarray]]],
    *,
    role: str,
    spacing_y: float,
    spacing_x: float,
    eligible_frame_keys: set[tuple[int, int]] | None = None,
    max_pairs: int = 12,
) -> dict:
    contour_keys = ("endo", "epi", "myocardium", "la") if str(role or "").startswith("cine_lax_") else ("endo", "epi", "myocardium")
    candidate_pairs: list[tuple[int, int, int]] = []
    available_keys = set(selected_frame_data)
    if eligible_frame_keys is not None:
        available_keys &= eligible_frame_keys

    for slice_index in sorted({key[0] for key in available_keys}):
        phase_items = sorted(phase for current_slice, phase in available_keys if current_slice == slice_index)
        for source_phase, target_phase in zip(phase_items, phase_items[1:]):
            if target_phase != source_phase + 1:
                continue
            source_masks = selected_frame_data[(slice_index, source_phase)][1]
            target_masks = selected_frame_data[(slice_index, target_phase)][1]
            if not any(
                source_masks.get(key) is not None
                and target_masks.get(key) is not None
                and int(source_masks[key].sum()) > 0
                and int(target_masks[key].sum()) > 0
                for key in contour_keys
            ):
                continue
            candidate_pairs.append((slice_index, source_phase, target_phase))

    candidate_pair_count = len(candidate_pairs)
    truncated = max_pairs > 0 and candidate_pair_count > max_pairs
    if truncated:
        sample_indices = np.linspace(0, candidate_pair_count - 1, num=max_pairs, dtype=int)
        candidate_pairs = [candidate_pairs[index] for index in sorted(set(sample_indices.tolist()))]

    per_pair = []
    for slice_index, source_phase, target_phase in candidate_pairs:
        source_image, source_masks = selected_frame_data[(slice_index, source_phase)]
        target_image, target_masks = selected_frame_data[(slice_index, target_phase)]
        tracking_field = _prepare_tvl1_tracking(source_image, target_image)
        if tracking_field is None:
            continue
        region_results = {}
        for contour_key in contour_keys:
            source_mask = source_masks.get(contour_key)
            target_mask = target_masks.get(contour_key)
            if source_mask is None or target_mask is None or int(source_mask.sum()) <= 0 or int(target_mask.sum()) <= 0:
                continue
            predicted_mask, flow_stats = _warp_mask_with_tracking_field(source_mask, tracking_field)
            if int(predicted_mask.sum()) <= 0:
                continue
            dice = _mask_dice(predicted_mask, target_mask)
            area_delta_percent = None
            target_area = float(target_mask.sum())
            if target_area > 0:
                area_delta_percent = ((float(predicted_mask.sum()) - target_area) / target_area) * 100.0
            boundary_distance = _mean_boundary_distance_mm(
                predicted_mask,
                target_mask,
                spacing_y=spacing_y,
                spacing_x=spacing_x,
            )
            region_results[contour_key] = {
                "dice": _round_float(dice, 4),
                "area_delta_percent": _round_float(area_delta_percent, 4),
                "mean_boundary_distance_mm": _round_float(boundary_distance, 4),
                **flow_stats,
            }
        if region_results:
            per_pair.append(
                {
                    "slice_index": int(slice_index),
                    "source_phase": int(source_phase),
                    "target_phase": int(target_phase),
                    "regions": region_results,
                }
            )

    region_summary = {}
    for contour_key in contour_keys:
        dice_values = []
        boundary_values = []
        area_delta_values = []
        mean_flow_values = []
        for item in per_pair:
            metrics = item["regions"].get(contour_key)
            if not metrics:
                continue
            if isinstance(metrics.get("dice"), (int, float)):
                dice_values.append(float(metrics["dice"]))
            if isinstance(metrics.get("mean_boundary_distance_mm"), (int, float)):
                boundary_values.append(float(metrics["mean_boundary_distance_mm"]))
            if isinstance(metrics.get("area_delta_percent"), (int, float)):
                area_delta_values.append(abs(float(metrics["area_delta_percent"])))
            if isinstance(metrics.get("mean_flow_px"), (int, float)):
                mean_flow_values.append(float(metrics["mean_flow_px"]))
        if dice_values or boundary_values:
            region_summary[contour_key] = {
                "pair_count": len(dice_values),
                "mean_dice": _round_float(sum(dice_values) / len(dice_values), 4) if dice_values else None,
                "min_dice": _round_float(min(dice_values), 4) if dice_values else None,
                "mean_boundary_distance_mm": _round_float(sum(boundary_values) / len(boundary_values), 4) if boundary_values else None,
                "mean_abs_area_delta_percent": _round_float(sum(area_delta_values) / len(area_delta_values), 4) if area_delta_values else None,
                "mean_flow_px": _round_float(sum(mean_flow_values) / len(mean_flow_values), 4) if mean_flow_values else None,
            }

    return {
        "method": "experimental_tvl1_optical_flow_mask_validation",
        "status": "completed",
        "role": str(role or "unknown"),
        "clinical_grade": False,
        "pair_count": len(per_pair),
        "candidate_pair_count": candidate_pair_count,
        "max_pair_count": max_pairs,
        "truncated": truncated,
        "summary": region_summary,
        "pairs": per_pair[:80],
        "notes": [
            "Uses only adjacent phases explicitly marked as manual/manual-refine (or validated) in frame metadata.",
            "Warps each source mask with one shared phase-correlation plus TV-L1 field per phase pair.",
            "Compares the warped mask with existing target contours; this validates temporal tracking feasibility.",
            "This is not yet clinical-grade CMR feature tracking or stable material point correspondence.",
        ],
    }


def _texture_statistics(image: np.ndarray, mask: np.ndarray, levels: int = 32) -> dict[str, float | None]:
    if int(mask.sum()) < 16:
        return {}
    rows, cols = np.where(mask)
    if rows.size <= 0 or cols.size <= 0:
        return {}
    r0, r1 = int(rows.min()), int(rows.max()) + 1
    c0, c1 = int(cols.min()), int(cols.max()) + 1
    crop = image[r0:r1, c0:c1].astype(np.float32)
    crop_mask = mask[r0:r1, c0:c1]
    roi_values = crop[crop_mask]
    if roi_values.size < 16:
        return {}
    value_min = float(roi_values.min())
    value_max = float(roi_values.max())
    if value_max <= value_min:
        return {
            "texture_glcm_contrast": 0.0,
            "texture_glcm_dissimilarity": 0.0,
            "texture_glcm_homogeneity": 1.0,
            "texture_glcm_energy": 1.0,
            "texture_glcm_correlation": 1.0,
            "texture_glcm_asm": 1.0,
        }
    quantized = np.floor((crop - value_min) / (value_max - value_min + 1e-6) * (levels - 1)).astype(np.uint8)
    fill_value = int(np.floor((float(roi_values.mean()) - value_min) / (value_max - value_min + 1e-6) * (levels - 1)))
    quantized[~crop_mask] = np.clip(fill_value, 0, levels - 1)
    glcm = graycomatrix(
        quantized,
        distances=[1],
        angles=[0.0, math.pi / 4.0, math.pi / 2.0, 3.0 * math.pi / 4.0],
        levels=levels,
        symmetric=True,
        normed=True,
    )
    return {
        "texture_glcm_contrast": _round_float(float(graycoprops(glcm, "contrast").mean()), 6),
        "texture_glcm_dissimilarity": _round_float(float(graycoprops(glcm, "dissimilarity").mean()), 6),
        "texture_glcm_homogeneity": _round_float(float(graycoprops(glcm, "homogeneity").mean()), 6),
        "texture_glcm_energy": _round_float(float(graycoprops(glcm, "energy").mean()), 6),
        "texture_glcm_correlation": _round_float(float(graycoprops(glcm, "correlation").mean()), 6),
        "texture_glcm_asm": _round_float(float(graycoprops(glcm, "ASM").mean()), 6),
    }


def _extract_roi_features(
    image: np.ndarray,
    mask: np.ndarray,
    *,
    pixel_area: float,
    slice_thickness: float,
    spacing_y: float,
    spacing_x: float,
) -> dict[str, float | int | None]:
    voxel_count = int(mask.sum())
    if voxel_count <= 0:
        return {}
    values = image[mask]
    area_mm2 = float(voxel_count) * pixel_area
    volume_ml = area_mm2 * slice_thickness / 1000.0
    feature_set: dict[str, float | int | None] = {
        "voxel_count": voxel_count,
        "area_mm2": _round_float(area_mm2, 4),
        "volume_ml": _round_float(volume_ml, 4),
    }
    feature_set.update(_first_order_statistics(values))
    feature_set.update(_shape_statistics(mask, pixel_area, spacing_y, spacing_x))
    feature_set.update(_texture_statistics(image, mask))
    return feature_set


def _normalize_source_entry(source: dict | None) -> dict | None:
    if not source:
        return None
    slice_index = source.get("slice_index")
    phase_index = source.get("phase_index")
    try:
        slice_index = int(slice_index)
        phase_index = int(phase_index)
    except (TypeError, ValueError):
        return None
    contour_keys = source.get("contour_keys") or []
    normalized_keys = [str(key) for key in contour_keys if key]
    return {
        "slice_index": slice_index,
        "phase_index": phase_index,
        "contour_keys": sorted(set(normalized_keys)),
    }


def _aggregate_region_features(
    samples: list[tuple[np.ndarray, np.ndarray, dict | None]],
    *,
    pixel_area: float,
    slice_thickness: float,
    spacing_y: float,
    spacing_x: float,
) -> dict[str, float | int | None]:
    populated = [(image, mask, source) for image, mask, source in samples if int(mask.sum()) > 0]
    if not populated:
        return {}
    concatenated_values = np.concatenate([image[mask].astype(np.float32) for image, mask, _ in populated])
    total_voxels = int(sum(int(mask.sum()) for _, mask, _ in populated))
    total_area_mm2 = float(total_voxels) * pixel_area
    total_volume_ml = total_area_mm2 * slice_thickness / 1000.0
    sources_by_frame: dict[tuple[int, int], dict] = {}
    for _image, _mask, source in populated:
        normalized = _normalize_source_entry(source)
        if not normalized:
            continue
        frame_key = (normalized["slice_index"], normalized["phase_index"])
        existing = sources_by_frame.get(frame_key)
        if existing is None:
            sources_by_frame[frame_key] = normalized
        else:
            existing["contour_keys"] = sorted(set(existing["contour_keys"]) | set(normalized["contour_keys"]))
    output: dict[str, float | int | None] = {
        "frame_count": len(populated),
        "source_count": len(sources_by_frame),
        "voxel_count": total_voxels,
        "area_mm2": _round_float(total_area_mm2, 4),
        "volume_ml": _round_float(total_volume_ml, 4),
        "sources": sorted(
            sources_by_frame.values(),
            key=lambda item: (int(item["phase_index"]), int(item["slice_index"])),
        ),
    }
    output.update(_first_order_statistics(concatenated_values))

    weighted_values: dict[str, float] = {}
    weighted_weights: dict[str, float] = {}
    for image, mask, _source in populated:
        weight = float(mask.sum())
        feature_set = _extract_roi_features(
            image,
            mask,
            pixel_area=pixel_area,
            slice_thickness=slice_thickness,
            spacing_y=spacing_y,
            spacing_x=spacing_x,
        )
        for key, value in feature_set.items():
            if key in {"voxel_count", "area_mm2", "volume_ml"}:
                continue
            if isinstance(value, (int, float)) and value is not None:
                weighted_values[key] = weighted_values.get(key, 0.0) + float(value) * weight
                weighted_weights[key] = weighted_weights.get(key, 0.0) + weight

    for key, total in weighted_values.items():
        weight = weighted_weights.get(key, 0.0)
        if weight > 0:
            output[key] = _round_float(total / weight, 6)
    return output


def _lge_settings_from_contours(contours: dict) -> tuple[str, float, bool]:
    settings = contours.get("settings", {}) if isinstance(contours, dict) else {}
    method = str(settings.get("threshold_method") or "nsd")
    if method not in {"nsd", "fwhm"}:
        method = "nsd"
    try:
        sd_multiplier = float(settings.get("sd_multiplier", 5.0))
    except (TypeError, ValueError):
        sd_multiplier = 5.0
    grey_zone = bool(settings.get("grey_zone", False))
    return method, sd_multiplier, grey_zone


def _compute_lge_frame_threshold_masks(
    image: np.ndarray,
    masks: dict[str, np.ndarray],
    *,
    threshold_method: str,
    sd_multiplier: float,
    grey_zone: bool,
) -> dict:
    method = threshold_method if threshold_method in {"nsd", "fwhm"} else "nsd"
    raw_myocardium = masks["epi"] & ~masks["endo"]
    exclude_mask = masks["exclude"] & raw_myocardium
    myocardium = raw_myocardium & ~exclude_mask
    empty_mask = np.zeros_like(raw_myocardium)
    if int(myocardium.sum()) <= 0:
        return {
            "method": method,
            "raw_myocardium": raw_myocardium,
            "myocardium": myocardium,
            "exclude_mask": exclude_mask,
            "enhanced_seed": empty_mask,
            "remote_seed": empty_mask,
            "mvo_mask": empty_mask,
            "scar_mask": empty_mask,
            "grey_mask": empty_mask,
            "baseline_mean": 0.0,
            "baseline_std": 0.0,
            "threshold": 0.0,
        }

    enhanced_seed = masks["enhanced"] & myocardium
    remote_seed = (masks["remote"] & myocardium) if masks["remote"].any() else myocardium
    remote_pixels = image[remote_seed]
    if remote_pixels.size == 0:
        remote_pixels = image[myocardium]
    baseline_pixels = remote_pixels[remote_pixels <= np.median(remote_pixels)] if remote_pixels.size else np.array([0.0])
    baseline_mean = float(baseline_pixels.mean()) if baseline_pixels.size else 0.0
    baseline_std = float(baseline_pixels.std()) if baseline_pixels.size else 0.0

    if method == "fwhm":
        seed_pixels = image[enhanced_seed] if enhanced_seed.any() else image[myocardium]
        seed_max = float(seed_pixels.max()) if seed_pixels.size else float(image[myocardium].max())
        threshold = seed_max * 0.5
        scar_mask = myocardium & (image >= threshold)
        grey_mask = (
            myocardium & (image >= seed_max * 0.35) & (image < threshold)
            if grey_zone
            else empty_mask
        )
    else:
        threshold = baseline_mean + float(sd_multiplier) * baseline_std
        scar_mask = myocardium & (image >= threshold)
        scar_mask = scar_mask | enhanced_seed
        grey_mask = (
            myocardium
            & (image >= baseline_mean + 2.0 * baseline_std)
            & (image < threshold)
            if grey_zone
            else empty_mask
        )

    scar_mask = binary_opening(binary_closing(scar_mask, disk(1)), disk(1))
    scar_mask = remove_small_objects(scar_mask.astype(bool), min_size=max(6, int(0.0002 * image.shape[0] * image.shape[1])))
    scar_mask &= myocardium
    mvo_mask = masks["mvo"] & myocardium
    scar_mask = (scar_mask | mvo_mask) & myocardium
    grey_mask = grey_mask & myocardium & ~scar_mask
    return {
        "method": method,
        "raw_myocardium": raw_myocardium,
        "myocardium": myocardium,
        "exclude_mask": exclude_mask,
        "enhanced_seed": enhanced_seed,
        "remote_seed": remote_seed,
        "mvo_mask": mvo_mask,
        "scar_mask": scar_mask,
        "grey_mask": grey_mask,
        "baseline_mean": baseline_mean,
        "baseline_std": baseline_std,
        "threshold": threshold,
    }


def compute_lge_threshold_preview(
    series_id: int,
    slice_index: int,
    threshold_method: str,
    sd_multiplier: float,
    grey_zone: bool,
    phase_index: int = 0,
) -> dict:
    with get_conn() as conn:
        series = conn.execute("SELECT * FROM series WHERE id = ?", (series_id,)).fetchone()
    if series is None:
        raise KeyError(series_id)

    contours = _fetch_contours(series_id, "lge") or {"frames": {}}
    selected_phase_index = max(0, int(phase_index))
    frame_key = _frame_key(int(slice_index), selected_phase_index)
    contour_frame_key = frame_key
    frame_payload = contours.get("frames", {}).get(contour_frame_key)
    if not isinstance(frame_payload, dict) and selected_phase_index != 0:
        contour_frame_key = _frame_key(int(slice_index), 0)
        frame_payload = contours.get("frames", {}).get(contour_frame_key)
    if not isinstance(frame_payload, dict):
        raise ValueError("当前层尚未保存 LGE 轮廓。")

    rows = int(_row_value(series, "rows", 1) or 1)
    cols = int(_row_value(series, "cols", 1) or 1)
    spacing_x = float(_row_value(series, "pixel_spacing_x", 1.0) or 1.0)
    spacing_y = float(_row_value(series, "pixel_spacing_y", 1.0) or 1.0)
    pixel_area = spacing_x * spacing_y
    frame = get_frame_row(series_id, int(slice_index), selected_phase_index)
    image = read_frame_pixels(frame).astype(np.float32)
    masks = _frame_masks(frame_payload, rows, cols)
    result = _compute_lge_frame_threshold_masks(
        image,
        masks,
        threshold_method=str(threshold_method or "nsd"),
        sd_multiplier=float(sd_multiplier),
        grey_zone=bool(grey_zone),
    )
    if int(result["myocardium"].sum()) <= 0:
        raise ValueError("当前层需要有效的左室内膜和左室外膜才能预览 LGE 阈值。")

    def mask_stats(mask: np.ndarray) -> dict[str, float | int]:
        pixels = int(mask.sum())
        return {"pixel_count": pixels, "area_mm2": _round_float(pixels * pixel_area, 4)}

    return {
        "series_id": int(series_id),
        "slice_index": int(slice_index),
        "phase_index": selected_phase_index,
        "frame_key": frame_key,
        "contour_frame_key": contour_frame_key,
        "threshold_method": result["method"],
        "sd_multiplier": float(sd_multiplier),
        "grey_zone": bool(grey_zone),
        "threshold": _round_float(result["threshold"], 4),
        "remote_mean": _round_float(result["baseline_mean"], 4),
        "remote_sd": _round_float(result["baseline_std"], 4),
        "stats": {
            "myocardium": mask_stats(result["myocardium"]),
            "scar": mask_stats(result["scar_mask"]),
            "grey_zone": mask_stats(result["grey_mask"]),
            "exclude": mask_stats(result["exclude_mask"]),
        },
        "masks": {
            "scar": _mask_to_rle(result["scar_mask"]),
            "grey_zone": _mask_to_rle(result["grey_mask"]),
        },
    }


def _manual_tracking_frame_keys(contours: dict) -> set[tuple[int, int]]:
    frame_meta = contours.get("frame_meta") if isinstance(contours, dict) else None
    if not isinstance(frame_meta, dict):
        return set()

    eligible: set[tuple[int, int]] = set()
    for frame_key, metadata in frame_meta.items():
        if not isinstance(metadata, dict):
            continue
        origin = str(metadata.get("origin") or "").lower()
        if metadata.get("validated") is not True and origin not in {"manual", "manual_refine"}:
            continue
        try:
            slice_text, phase_text = str(frame_key).split(":", 1)
            eligible.add((int(slice_text), int(phase_text)))
        except (TypeError, ValueError):
            continue
    return eligible


def _tracking_validation_not_run(role: str) -> dict:
    return {
        "method": "on_demand_tracking_preview",
        "status": "not_run",
        "role": str(role or "unknown"),
        "clinical_grade": False,
        "pair_count": None,
        "candidate_pair_count": None,
        "summary": {},
        "pairs": [],
        "notes": [
            "Tracking validation is intentionally excluded from routine contour-save recomputation.",
            "Run the dedicated tracking preview to evaluate adjacent manually confirmed phases.",
        ],
    }


def _save_measurement(series_id: int, module: str, payload: dict) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM measurements WHERE series_id = ? AND module = ?",
            (series_id, module),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE measurements SET payload_json = ?, updated_at = ? WHERE series_id = ? AND module = ?",
                (dumps(payload), utcnow(), series_id, module),
            )
        else:
            conn.execute(
                "INSERT INTO measurements (series_id, module, payload_json, updated_at) VALUES (?, ?, ?, ?)",
                (series_id, module, dumps(payload), utcnow()),
            )
    return payload


def _dicom_pixel_spacing_xy(frame: dict) -> tuple[float, float] | None:
    file_path = _row_value(frame, "file_path", None)
    if not isinstance(file_path, (str, Path)) or not str(file_path).strip():
        return None
    try:
        dataset = pydicom.dcmread(
            str(file_path),
            stop_before_pixels=True,
            force=True,
            specific_tags=["PixelSpacing"],
        )
        spacing = getattr(dataset, "PixelSpacing", None)
        if spacing is None or len(spacing) < 2:
            return None
        spacing_y = float(spacing[0])
        spacing_x = float(spacing[1])
    except Exception:
        return None
    if not all(math.isfinite(value) and value > 0 for value in (spacing_x, spacing_y)):
        return None
    return spacing_x, spacing_y


def _curvature_spacing_inputs(series, frames: list[dict], landmarks: dict | None) -> tuple[object, object, str]:
    spacing_x = _row_value(series, "pixel_spacing_x", None)
    spacing_y = _row_value(series, "pixel_spacing_y", None)
    provenance = "series_index_metadata_unverified"
    if not isinstance(landmarks, dict):
        return spacing_x, spacing_y, provenance
    slice_index = landmarks.get("slice_index")
    phase_index = landmarks.get("phase_index")
    if not isinstance(slice_index, int) or isinstance(slice_index, bool):
        return spacing_x, spacing_y, provenance
    if not isinstance(phase_index, int) or isinstance(phase_index, bool):
        return spacing_x, spacing_y, provenance
    selected_frame = next(
        (
            frame
            for frame in frames
            if int(frame["slice_index"]) == slice_index and int(frame["phase_index"]) == phase_index
        ),
        None,
    )
    if selected_frame is None:
        return spacing_x, spacing_y, provenance
    dicom_spacing = _dicom_pixel_spacing_xy(selected_frame)
    if dicom_spacing is not None:
        return dicom_spacing[0], dicom_spacing[1], "selected_frame_dicom_header"
    raw_metadata = _row_value(selected_frame, "metadata_json", None)
    metadata = raw_metadata if isinstance(raw_metadata, dict) else loads(raw_metadata, {})
    frame_spacing = metadata.get("pixel_spacing") if isinstance(metadata, dict) else None
    if isinstance(frame_spacing, (list, tuple)) and len(frame_spacing) >= 2:
        return frame_spacing[0], frame_spacing[1], "selected_frame_index_metadata_unverified"
    return spacing_x, spacing_y, provenance


def compute_curvature_preview(series_id: int, landmarks: dict) -> dict:
    """Compute a non-persisted manual four-point preview for the viewer."""
    with get_conn() as conn:
        series = conn.execute("SELECT * FROM series WHERE id = ?", (series_id,)).fetchone()
    if series is None:
        raise KeyError(series_id)
    frames = list_frame_rows(series_id)
    curvature_spacing_x, curvature_spacing_y, spacing_provenance = _curvature_spacing_inputs(
        series,
        frames,
        landmarks,
    )
    result = compute_curvature_from_landmarks(
        landmarks,
        spacing_x=curvature_spacing_x,
        spacing_y=curvature_spacing_y,
        series_role=str(_row_value(series, "role", "unknown")),
        available_frame_keys={
            (int(frame["slice_index"]), int(frame["phase_index"]))
            for frame in frames
        },
        image_rows=int(series["rows"] or 1),
        image_cols=int(series["cols"] or 1),
        spacing_provenance=spacing_provenance,
    )
    return {
        "module": "curvature_preview",
        "series_id": int(series_id),
        "persisted": False,
        "curvature": result,
    }


def compute_lv_tracking_preview(series_id: int) -> dict:
    """Compute an experimental temporal tracking preview without persisting it."""
    with get_conn() as conn:
        series = conn.execute("SELECT * FROM series WHERE id = ?", (series_id,)).fetchone()
    if series is None:
        raise KeyError(series_id)

    contours = _fetch_contours(series_id, "function") or {"frames": {}}
    rows = int(series["rows"] or 1)
    cols = int(series["cols"] or 1)
    spacing_x = float(series["pixel_spacing_x"] or 1.0)
    spacing_y = float(series["pixel_spacing_y"] or 1.0)
    pixel_area = spacing_x * spacing_y
    frames = list_frame_rows(series_id)
    selected_frame_data: dict[tuple[int, int], tuple[np.ndarray, dict[str, np.ndarray]]] = {}
    phase_endo_areas: dict[int, float] = {}
    phase_la_areas: dict[int, float] = {}
    phase_trigger_times: dict[int, list[float]] = {}

    for frame in frames:
        slice_index = int(frame["slice_index"])
        phase_index = int(frame["phase_index"])
        frame_payload = contours.get("frames", {}).get(_frame_key(slice_index, phase_index))
        if not frame_payload or not frame_payload.get("include", True):
            continue
        if _is_frame_excluded(contours, slice_index, phase_index):
            continue
        masks = _frame_masks(frame_payload, rows, cols)
        endo = masks["endo"]
        epi = masks["epi"]
        la = masks["la"]
        if int(endo.sum()) <= 0 and int(epi.sum()) <= 0 and int(la.sum()) <= 0:
            continue
        image = read_frame_pixels(frame).astype(np.float32)
        selected_frame_data[(slice_index, phase_index)] = (
            image,
            {
                "endo": endo,
                "epi": epi,
                "myocardium": epi & ~endo,
                "la": la,
            },
        )
        if int(endo.sum()) > 0:
            phase_endo_areas[phase_index] = phase_endo_areas.get(phase_index, 0.0) + float(endo.sum())
        if int(la.sum()) > 0:
            phase_la_areas[phase_index] = phase_la_areas.get(phase_index, 0.0) + float(la.sum())
        trigger_time = _row_value(frame, "trigger_time", None)
        if trigger_time is not None:
            try:
                phase_trigger_times.setdefault(phase_index, []).append(float(trigger_time))
            except (TypeError, ValueError):
                pass

    phase_indices = sorted(set(phase_endo_areas) | set(phase_la_areas))
    phase_labels = contours.get("phase_labels") if isinstance(contours.get("phase_labels"), dict) else {}
    auto_ed_phase = max(phase_endo_areas, key=phase_endo_areas.get) if phase_endo_areas else 0
    auto_es_phase = min(phase_endo_areas, key=phase_endo_areas.get) if phase_endo_areas else 0
    requested_ed = phase_labels.get("lv_ed", phase_labels.get("ed"))
    requested_es = phase_labels.get("lv_es", phase_labels.get("es"))
    ed_phase = int(requested_ed) if requested_ed in phase_endo_areas else int(auto_ed_phase)
    es_phase = int(requested_es) if requested_es in phase_endo_areas else int(auto_es_phase)
    phase_times_ms = {
        phase: (sum(values) / len(values) if values else None)
        for phase, values in phase_trigger_times.items()
    }
    role = str(_row_value(series, "role", "unknown"))
    strain_proxy = _compute_lv_2d_strain_proxy(
        selected_frame_data,
        phase_indices,
        role=role,
        ed_phase=ed_phase,
        es_phase=es_phase,
        pixel_area=pixel_area,
        spacing_y=spacing_y,
        spacing_x=spacing_x,
        phase_times_ms=phase_times_ms,
    )
    left_atrial_function = _compute_left_atrial_function(
        selected_frame_data,
        role=role,
        phase_labels=phase_labels,
        total_phase_count=int(_row_value(series, "phase_count", len(phase_indices)) or len(phase_indices)),
        pixel_area=pixel_area,
        spacing_y=spacing_y,
        spacing_x=spacing_x,
        phase_times_ms=phase_times_ms,
    )
    if left_atrial_function is not None:
        left_atrial_function["indexing"] = _left_atrial_indexing_settings(contours)
    tracking_validation = _compute_lv_tracking_validation(
        selected_frame_data,
        role=role,
        spacing_y=spacing_y,
        spacing_x=spacing_x,
        eligible_frame_keys=_manual_tracking_frame_keys(contours),
    )
    return {
        "module": "tracking_preview",
        "series_id": series_id,
        "role": role,
        "persisted": False,
        "metrics": {
            "ed_phase": ed_phase,
            "es_phase": es_phase,
            "usable_phase_count": len(phase_indices),
            "tracking_pair_count": tracking_validation.get("pair_count", 0),
            "la_tracking_pair_count": tracking_validation.get("summary", {}).get("la", {}).get("pair_count", 0),
        },
        "research": {
            "strain_proxy": strain_proxy,
            "tracking_validation": tracking_validation,
            **({"left_atrial_function": left_atrial_function} if left_atrial_function is not None else {}),
        },
    }


def recompute_function(series_id: int) -> dict:
    with get_conn() as conn:
        series = conn.execute("SELECT * FROM series WHERE id = ?", (series_id,)).fetchone()
    if series is None:
        raise KeyError(series_id)
    contours = _fetch_contours(series_id, "function") or {"frames": {}}
    rows = int(series["rows"] or 1)
    cols = int(series["cols"] or 1)
    spacing_x = float(series["pixel_spacing_x"] or 1.0)
    spacing_y = float(series["pixel_spacing_y"] or 1.0)
    pixel_area = spacing_x * spacing_y
    slice_thickness = float(series["slice_thickness"] or 8.0)
    frames = list_frame_rows(series_id)
    curvature_spacing_x, curvature_spacing_y, spacing_provenance = _curvature_spacing_inputs(
        series,
        frames,
        contours.get("curvature_landmarks"),
    )
    curvature_result = compute_curvature_from_landmarks(
        contours.get("curvature_landmarks"),
        spacing_x=curvature_spacing_x,
        spacing_y=curvature_spacing_y,
        series_role=str(_row_value(series, "role", "unknown")),
        available_frame_keys={
            (int(frame["slice_index"]), int(frame["phase_index"]))
            for frame in frames
        },
        image_rows=rows,
        image_cols=cols,
        spacing_provenance=spacing_provenance,
    )

    phase_totals: dict[int, dict[str, float]] = {}
    phase_trigger_times: dict[int, list[float]] = {}
    per_slice = []
    selected_frame_data: dict[tuple[int, int], tuple[np.ndarray, dict[str, np.ndarray]]] = {}
    selected_frame_source_keys: dict[tuple[int, int], dict[str, list[str]]] = {}
    fat_threshold_applied_frame_count = 0
    for frame in frames:
        frame_payload = contours["frames"].get(_frame_key(frame["slice_index"], frame["phase_index"]))
        if not frame_payload or not frame_payload.get("include", True):
            continue
        if _is_frame_excluded(contours, frame["slice_index"], frame["phase_index"]):
            continue
        image = read_frame_pixels(frame).astype(np.float32)
        masks = _frame_masks(frame_payload, rows, cols)
        myocardium_mask = masks["epi"] & ~masks["endo"]
        fat_mask, fat_exclude_mask, fat_method, fat_source_keys = _function_fat_masks(masks)
        frame_key = _frame_key(frame["slice_index"], frame["phase_index"])
        fat_threshold = _fat_threshold_for_frame(contours, frame_key)
        fat_mask, fat_exclude_mask, fat_threshold_exclude_mask, fat_candidate_mask = _apply_fat_intensity_threshold(
            fat_mask,
            fat_exclude_mask,
            image,
            fat_threshold,
        )
        if fat_threshold is not None:
            fat_threshold_applied_frame_count += 1
            fat_method = f"{fat_method}_intensity_range"
        endo_area = float(masks["endo"].sum()) * pixel_area
        epi_area = float(masks["epi"].sum()) * pixel_area
        rv_area = float(masks["rv"].sum()) * pixel_area
        fat_area = float(fat_mask.sum()) * pixel_area
        fat_exclude_area = float(fat_exclude_mask.sum()) * pixel_area
        fat_threshold_exclude_area = float(fat_threshold_exclude_mask.sum()) * pixel_area
        fat_candidate_area = float(fat_candidate_mask.sum()) * pixel_area
        lv_volume = endo_area * slice_thickness / 1000.0
        rv_volume = rv_area * slice_thickness / 1000.0
        myo_volume = max(epi_area - endo_area, 0.0) * slice_thickness / 1000.0
        fat_volume = fat_area * slice_thickness / 1000.0
        fat_exclude_volume = fat_exclude_area * slice_thickness / 1000.0
        fat_threshold_exclude_volume = fat_threshold_exclude_area * slice_thickness / 1000.0
        fat_candidate_volume = fat_candidate_area * slice_thickness / 1000.0
        phase_totals.setdefault(frame["phase_index"], {"lv": 0.0, "rv": 0.0, "mass": 0.0})
        phase_totals[frame["phase_index"]]["lv"] += lv_volume
        phase_totals[frame["phase_index"]]["rv"] += rv_volume
        phase_totals[frame["phase_index"]]["mass"] += myo_volume * 1.05
        trigger_time = _row_value(frame, "trigger_time", None)
        if trigger_time is not None:
            try:
                phase_trigger_times.setdefault(int(frame["phase_index"]), []).append(float(trigger_time))
            except (TypeError, ValueError):
                pass
        selected_frame_data[(frame["slice_index"], frame["phase_index"])] = (
            image,
            {
                "endo": masks["endo"],
                "epi": masks["epi"],
                "ventricular_epi": masks["ventricular_epi"],
                "myocardium": myocardium_mask,
                "rv": masks["rv"],
                "fat": fat_mask,
                "fat_exclude": fat_exclude_mask,
                "fat_threshold_exclude": fat_threshold_exclude_mask,
                "fat_candidate": fat_candidate_mask,
                "la": masks["la"],
                "ra": masks["ra"],
            },
        )
        selected_frame_source_keys[(frame["slice_index"], frame["phase_index"])] = {
            "fat": fat_source_keys,
            "fat_exclude": ["exclude"],
            "fat_threshold_exclude": fat_source_keys,
            "fat_candidate": fat_source_keys,
        }
        fat_entropy = _extract_roi_features(
            image,
            fat_mask,
            pixel_area=pixel_area,
            slice_thickness=slice_thickness,
            spacing_y=spacing_y,
            spacing_x=spacing_x,
        ).get("intensity_entropy")
        per_slice.append(
            {
                "slice_index": frame["slice_index"],
                "phase_index": frame["phase_index"],
                "lv_volume_ml": round(lv_volume, 2),
                "rv_volume_ml": round(rv_volume, 2),
                "myocardium_volume_ml": round(myo_volume, 2),
                "fat_volume_ml": round(fat_volume, 2),
                "fat_exclude_volume_ml": round(fat_exclude_volume, 2),
                "fat_threshold_exclude_volume_ml": round(fat_threshold_exclude_volume, 2),
                "fat_candidate_volume_ml": round(fat_candidate_volume, 2),
                "fat_measurement_method": fat_method,
                "fat_source_contours": fat_source_keys,
                "fat_threshold_enabled": fat_threshold is not None,
                "fat_threshold_lower": _round_float(fat_threshold.get("lower"), 2) if fat_threshold else None,
                "fat_threshold_upper": _round_float(fat_threshold.get("upper"), 2) if fat_threshold else None,
                "fat_entropy": _round_float(fat_entropy, 6),
            }
        )

    if not phase_totals:
        research = {"region_features": {}}
        if curvature_result is not None:
            research["curvature"] = curvature_result
        return _save_measurement(
            series_id,
            "function",
            {
                "module": "function",
                "series_id": series_id,
                "metrics": {},
                "phase_volumes": [],
                "per_slice": [],
                "research": research,
            },
        )

    phase_volumes = [
        {"phase_index": phase, "lv_volume_ml": round(values["lv"], 2), "rv_volume_ml": round(values["rv"], 2)}
        for phase, values in sorted(phase_totals.items())
    ]
    manual_phase_labels = contours.get("phase_labels", {})
    auto_ed_phase = max(phase_totals.items(), key=lambda item: item[1]["lv"])[0]
    auto_es_phase = min(phase_totals.items(), key=lambda item: item[1]["lv"])[0]
    ed_phase = manual_phase_labels.get("ed") if manual_phase_labels.get("ed") in phase_totals else auto_ed_phase
    es_phase = manual_phase_labels.get("es") if manual_phase_labels.get("es") in phase_totals else auto_es_phase
    rv_ed_phase = ed_phase
    rv_es_phase = es_phase
    strain_ed_phase = manual_phase_labels.get("lv_ed") if manual_phase_labels.get("lv_ed") in phase_totals else ed_phase
    strain_es_phase = manual_phase_labels.get("lv_es") if manual_phase_labels.get("lv_es") in phase_totals else es_phase
    edv = phase_totals[ed_phase]["lv"]
    esv = phase_totals[es_phase]["lv"]
    rv_edv = phase_totals[rv_ed_phase]["rv"]
    rv_esv = phase_totals[rv_es_phase]["rv"]

    region_names = (
        "endo", "epi", "ventricular_epi", "myocardium", "rv", "fat", "fat_exclude",
        "fat_threshold_exclude", "fat_candidate", "la", "ra",
    )

    region_source_keys: dict[str, list[str]] = {
        "endo": ["endo"],
        "epi": ["epi"],
        "ventricular_epi": ["ventricular_epi"],
        "myocardium": ["endo", "epi"],
        "rv": ["rv"],
        "fat": ["fat"],
        "fat_exclude": ["exclude"],
        "fat_threshold_exclude": ["fat_outer", "ventricular_epi"],
        "fat_candidate": ["fat_outer", "ventricular_epi"],
        "la": ["la"],
        "ra": ["ra"],
    }

    def collect_region_samples(target_phase: int | None = None) -> dict[str, list[tuple[np.ndarray, np.ndarray, dict]]]:
        samples = {name: [] for name in region_names}
        for (slice_index, phase_index), (image, masks) in selected_frame_data.items():
            if target_phase is not None and phase_index != target_phase:
                continue
            for name in region_names:
                mask = masks.get(name)
                if mask is not None and int(mask.sum()) > 0:
                    samples[name].append(
                        (
                            image,
                            mask,
                            {
                                "slice_index": slice_index,
                                "phase_index": phase_index,
                                "contour_keys": selected_frame_source_keys.get((slice_index, phase_index), {}).get(name) or region_source_keys.get(name, [name]),
                            },
                        )
                    )
        return samples

    research_region_features: dict[str, dict[str, dict[str, float | int | None]]] = {}
    for label_name, phase_index in (("all_frames", None), ("ed_phase", ed_phase), ("es_phase", es_phase)):
        region_samples = collect_region_samples(phase_index)
        label_payload = {}
        for region_name, samples in region_samples.items():
            summary = _aggregate_region_features(
                samples,
                pixel_area=pixel_area,
                slice_thickness=slice_thickness,
                spacing_y=spacing_y,
                spacing_x=spacing_x,
            )
            if summary:
                label_payload[region_name] = summary
        research_region_features[label_name] = label_payload

    fat_ed_features = research_region_features.get("ed_phase", {}).get("fat", {})
    fat_all_features = research_region_features.get("all_frames", {}).get("fat", {})
    fat_fallback_features = fat_ed_features or fat_all_features
    fat_exclude_ed_features = research_region_features.get("ed_phase", {}).get("fat_exclude", {})
    fat_exclude_all_features = research_region_features.get("all_frames", {}).get("fat_exclude", {})
    fat_exclude_fallback_features = fat_exclude_ed_features or fat_exclude_all_features
    fat_threshold_exclude_ed_features = research_region_features.get("ed_phase", {}).get("fat_threshold_exclude", {})
    fat_threshold_exclude_all_features = research_region_features.get("all_frames", {}).get("fat_threshold_exclude", {})
    fat_threshold_exclude_fallback_features = fat_threshold_exclude_ed_features or fat_threshold_exclude_all_features
    fat_candidate_ed_features = research_region_features.get("ed_phase", {}).get("fat_candidate", {})
    fat_candidate_all_features = research_region_features.get("all_frames", {}).get("fat_candidate", {})
    fat_candidate_fallback_features = fat_candidate_ed_features or fat_candidate_all_features
    phase_times_ms = {
        phase: (sum(values) / len(values) if values else None)
        for phase, values in phase_trigger_times.items()
    }
    series_role = str(_row_value(series, "role", "unknown"))
    left_atrial_function = _compute_left_atrial_function(
        selected_frame_data,
        role=series_role,
        phase_labels=manual_phase_labels,
        total_phase_count=int(_row_value(series, "phase_count", len(phase_totals)) or len(phase_totals)),
        pixel_area=pixel_area,
        spacing_y=spacing_y,
        spacing_x=spacing_x,
        phase_times_ms=phase_times_ms,
    )
    if left_atrial_function is not None:
        left_atrial_function["indexing"] = _left_atrial_indexing_settings(contours)
        if series_role == "cine_lax_4ch" and left_atrial_function.get("curve"):
            left_atrial_function["biplane"] = _compute_left_atrial_biplane_for_series(
                series,
                contours,
                left_atrial_function,
            )
    left_atrial_summary = left_atrial_function.get("summary", {}) if left_atrial_function else {}
    left_atrial_phases = left_atrial_function.get("phase_selection", {}) if left_atrial_function else {}
    left_atrial_quality = left_atrial_function.get("quality", {}) if left_atrial_function else {}
    left_atrial_strain = left_atrial_function.get("strain_proxy", {}) if left_atrial_function else {}
    left_atrial_strain_summary = left_atrial_strain.get("summary", {}) if left_atrial_strain else {}
    left_atrial_biplane = left_atrial_function.get("biplane", {}) if left_atrial_function else {}
    left_atrial_biplane_summary = left_atrial_biplane.get("summary", {}) if left_atrial_biplane else {}
    left_atrial_indexing = left_atrial_function.get("indexing", {}) if left_atrial_function else {}
    has_biplane_max_min = (
        left_atrial_biplane_summary.get("lav_max_ml") is not None
        and left_atrial_biplane_summary.get("lav_min_ml") is not None
    )
    left_atrial_preferred_summary = left_atrial_biplane_summary if has_biplane_max_min else left_atrial_summary
    left_atrial_preferred_method = "biplane_area_length" if has_biplane_max_min else left_atrial_function.get("method") if left_atrial_function else None
    left_atrial_metrics = {}
    if left_atrial_function is not None:
        left_atrial_metrics = {
            "la_volume_method": left_atrial_function.get("method"),
            "la_max_phase": left_atrial_phases.get("la_max"),
            "la_pre_a_phase": left_atrial_phases.get("la_pre_a"),
            "la_min_phase": left_atrial_phases.get("la_min"),
            "la_lav_max_ml": _round_float(left_atrial_summary.get("lav_max_ml"), 4),
            "la_lav_pre_a_ml": _round_float(left_atrial_summary.get("lav_pre_a_ml"), 4),
            "la_lav_min_ml": _round_float(left_atrial_summary.get("lav_min_ml"), 4),
            "la_total_emptying_volume_ml": _round_float(left_atrial_summary.get("total_emptying_volume_ml"), 4),
            "la_total_emptying_fraction_percent": _round_float(left_atrial_summary.get("total_emptying_fraction_percent"), 4),
            "la_passive_emptying_volume_ml": _round_float(left_atrial_summary.get("passive_emptying_volume_ml"), 4),
            "la_passive_emptying_fraction_percent": _round_float(left_atrial_summary.get("passive_emptying_fraction_percent"), 4),
            "la_active_emptying_volume_ml": _round_float(left_atrial_summary.get("active_emptying_volume_ml"), 4),
            "la_active_emptying_fraction_percent": _round_float(left_atrial_summary.get("active_emptying_fraction_percent"), 4),
            "la_annotated_phase_count": left_atrial_quality.get("annotated_phase_count"),
            "la_total_phase_count": left_atrial_quality.get("total_phase_count"),
            "la_full_cycle_complete": left_atrial_quality.get("full_cycle_complete"),
            "la_reservoir_strain_proxy_percent": _round_float(left_atrial_strain_summary.get("reservoir_strain_proxy_percent"), 4),
            "la_conduit_strain_proxy_percent": _round_float(left_atrial_strain_summary.get("conduit_strain_proxy_percent"), 4),
            "la_contractile_strain_proxy_percent": _round_float(left_atrial_strain_summary.get("contractile_strain_proxy_percent"), 4),
            "la_biplane_status": left_atrial_biplane.get("status"),
            "la_biplane_lav_max_ml": _round_float(left_atrial_biplane_summary.get("lav_max_ml"), 4),
            "la_biplane_lav_pre_a_ml": _round_float(left_atrial_biplane_summary.get("lav_pre_a_ml"), 4),
            "la_biplane_lav_min_ml": _round_float(left_atrial_biplane_summary.get("lav_min_ml"), 4),
            "la_biplane_lavi_max_ml_m2": _round_float(left_atrial_biplane_summary.get("lavi_max_ml_m2"), 4),
            "la_biplane_lavi_pre_a_ml_m2": _round_float(left_atrial_biplane_summary.get("lavi_pre_a_ml_m2"), 4),
            "la_biplane_lavi_min_ml_m2": _round_float(left_atrial_biplane_summary.get("lavi_min_ml_m2"), 4),
            "la_bsa_m2": _round_float(left_atrial_indexing.get("bsa_m2"), 4),
            "la_preferred_volume_method": left_atrial_preferred_method,
            "la_preferred_lav_max_ml": _round_float(left_atrial_preferred_summary.get("lav_max_ml"), 4),
            "la_preferred_lav_pre_a_ml": _round_float(left_atrial_preferred_summary.get("lav_pre_a_ml"), 4),
            "la_preferred_lav_min_ml": _round_float(left_atrial_preferred_summary.get("lav_min_ml"), 4),
        }
    strain_proxy = _compute_lv_2d_strain_proxy(
        selected_frame_data,
        sorted(phase_totals),
        role=series_role,
        ed_phase=int(strain_ed_phase),
        es_phase=int(strain_es_phase),
        pixel_area=pixel_area,
        spacing_y=spacing_y,
        spacing_x=spacing_x,
        phase_times_ms=phase_times_ms,
    )
    strain_summary = strain_proxy.get("summary", {})
    tracking_validation = _tracking_validation_not_run(series_role)
    tracking_endo: dict = {}
    tracking_epi: dict = {}
    tracking_myo: dict = {}
    payload = {
        "module": "function",
        "series_id": series_id,
        "metrics": {
            "ed_phase": ed_phase,
            "es_phase": es_phase,
            "rv_ed_phase": rv_ed_phase,
            "rv_es_phase": rv_es_phase,
            "lv_edv_ml": round(edv, 2),
            "lv_esv_ml": round(esv, 2),
            "lv_sv_ml": round(edv - esv, 2),
            "lv_ef_percent": round(((edv - esv) / edv) * 100.0, 2) if edv else None,
            "rv_edv_ml": round(rv_edv, 2) if rv_edv else None,
            "rv_esv_ml": round(rv_esv, 2) if rv_esv else None,
            "rv_sv_ml": round(rv_edv - rv_esv, 2) if rv_edv else None,
            "rv_ef_percent": round(((rv_edv - rv_esv) / rv_edv) * 100.0, 2) if rv_edv else None,
            "lv_mass_g": round(phase_totals[ed_phase]["mass"], 2),
            "epicardial_fat_volume_ml": _round_float(fat_fallback_features.get("volume_ml"), 4),
            "epicardial_fat_ed_volume_ml": _round_float(fat_ed_features.get("volume_ml"), 4),
            "epicardial_fat_all_frames_volume_ml": _round_float(fat_all_features.get("volume_ml"), 4),
            "epicardial_fat_exclude_volume_ml": _round_float(fat_exclude_fallback_features.get("volume_ml"), 4),
            "epicardial_fat_exclude_ed_volume_ml": _round_float(fat_exclude_ed_features.get("volume_ml"), 4),
            "epicardial_fat_exclude_all_frames_volume_ml": _round_float(fat_exclude_all_features.get("volume_ml"), 4),
            "epicardial_fat_threshold_exclude_volume_ml": _round_float(fat_threshold_exclude_fallback_features.get("volume_ml"), 4),
            "epicardial_fat_threshold_exclude_ed_volume_ml": _round_float(fat_threshold_exclude_ed_features.get("volume_ml"), 4),
            "epicardial_fat_threshold_exclude_all_frames_volume_ml": _round_float(fat_threshold_exclude_all_features.get("volume_ml"), 4),
            "epicardial_fat_candidate_volume_ml": _round_float(fat_candidate_fallback_features.get("volume_ml"), 4),
            "epicardial_fat_candidate_ed_volume_ml": _round_float(fat_candidate_ed_features.get("volume_ml"), 4),
            "epicardial_fat_candidate_all_frames_volume_ml": _round_float(fat_candidate_all_features.get("volume_ml"), 4),
            "epicardial_fat_threshold_applied_frame_count": fat_threshold_applied_frame_count,
            "epicardial_fat_entropy": _round_float(fat_fallback_features.get("intensity_entropy"), 6),
            "lv_2d_strain_proxy_method": strain_proxy.get("method"),
            "lv_2d_strain_proxy_clinical_grade": False,
            "lv_2d_strain_proxy_ed_phase": strain_proxy.get("ed_phase"),
            "lv_2d_strain_proxy_es_phase": strain_proxy.get("es_phase"),
            "lv_2d_gcs_proxy_peak_percent": _round_float(strain_summary.get("gcs_peak_percent"), 4),
            "lv_2d_gcs_proxy_es_percent": _round_float(strain_summary.get("gcs_es_percent"), 4),
            "lv_2d_grs_proxy_peak_percent": _round_float(strain_summary.get("grs_peak_percent"), 4),
            "lv_2d_grs_proxy_es_percent": _round_float(strain_summary.get("grs_es_percent"), 4),
            "lv_2d_gls_proxy_peak_percent": _round_float(strain_summary.get("gls_peak_percent"), 4),
            "lv_2d_gls_proxy_es_percent": _round_float(strain_summary.get("gls_es_percent"), 4),
            "lv_tracking_validation_method": tracking_validation.get("method"),
            "lv_tracking_validation_clinical_grade": False,
            "lv_tracking_validation_pair_count": tracking_validation.get("pair_count"),
            "lv_tracking_endo_mean_dice": _round_float(tracking_endo.get("mean_dice"), 4),
            "lv_tracking_epi_mean_dice": _round_float(tracking_epi.get("mean_dice"), 4),
            "lv_tracking_myocardium_mean_dice": _round_float(tracking_myo.get("mean_dice"), 4),
            "lv_tracking_endo_boundary_distance_mm": _round_float(tracking_endo.get("mean_boundary_distance_mm"), 4),
            "lv_tracking_epi_boundary_distance_mm": _round_float(tracking_epi.get("mean_boundary_distance_mm"), 4),
            "lv_tracking_myocardium_boundary_distance_mm": _round_float(tracking_myo.get("mean_boundary_distance_mm"), 4),
            **left_atrial_metrics,
        },
        "phase_volumes": phase_volumes,
        "per_slice": per_slice,
        "research": {
            "region_features": research_region_features,
            "strain_proxy": strain_proxy,
            "tracking_validation": tracking_validation,
            **({"left_atrial_function": left_atrial_function} if left_atrial_function is not None else {}),
            **({"curvature": curvature_result} if curvature_result is not None else {}),
        },
    }
    return _save_measurement(series_id, "function", payload)


def _segment_index(total_slices: int, slice_index: int, angle: np.ndarray) -> np.ndarray:
    basal_cut = max(1, int(math.ceil(total_slices / 3)))
    mid_cut = max(1, int(math.ceil(total_slices * 2 / 3)))
    if slice_index < basal_cut:
        segment_count = 6
        base_offset = 0
    elif slice_index < mid_cut:
        segment_count = 6
        base_offset = 6
    else:
        segment_count = 4
        base_offset = 12
    normalized = (angle + 2 * math.pi) % (2 * math.pi)
    return base_offset + np.floor(normalized / (2 * math.pi / segment_count)).astype(int)


def recompute_lge(
    series_id: int,
    threshold_method: str | None = None,
    sd_multiplier: float | None = None,
    grey_zone: bool | None = None,
    phase_index: int | None = None,
) -> dict:
    with get_conn() as conn:
        series = conn.execute("SELECT * FROM series WHERE id = ?", (series_id,)).fetchone()
    if series is None:
        raise KeyError(series_id)
    contours = _fetch_contours(series_id, "lge") or {"frames": {}}
    contour_method, contour_sd, contour_grey_zone = _lge_settings_from_contours(contours)
    threshold_method = threshold_method or contour_method
    sd_multiplier = float(contour_sd if sd_multiplier is None else sd_multiplier)
    grey_zone = bool(contour_grey_zone if grey_zone is None else grey_zone)
    rows = int(series["rows"] or 1)
    cols = int(series["cols"] or 1)
    spacing_x = float(series["pixel_spacing_x"] or 1.0)
    spacing_y = float(series["pixel_spacing_y"] or 1.0)
    pixel_area = spacing_x * spacing_y
    slice_thickness = float(series["slice_thickness"] or 8.0)
    total_slices = int(series["slice_count"] or 1)
    selected_phase_index = max(0, int(phase_index or 0))

    scar_volume = 0.0
    myocardium_volume = 0.0
    mvo_volume = 0.0
    grey_volume = 0.0
    exclude_volume = 0.0
    generated_enhanced_count = 0
    generated_frame_updates: dict[str, dict] = {}
    per_slice = []
    segment_scores = np.zeros(16, dtype=float)
    segment_counts = np.zeros(16, dtype=float)
    region_samples: dict[str, list[tuple[np.ndarray, np.ndarray, dict]]] = {
        "myocardium": [],
        "scar": [],
        "remote": [],
        "mvo": [],
        "grey_zone": [],
    }

    for slice_index in range(total_slices):
        frame_key = _frame_key(slice_index, selected_phase_index)
        contour_frame_key = frame_key
        frame_payload = contours["frames"].get(contour_frame_key)
        if not frame_payload and selected_phase_index != 0:
            contour_frame_key = _frame_key(slice_index, 0)
            frame_payload = contours["frames"].get(contour_frame_key)
        if not frame_payload or not frame_payload.get("include", True):
            continue
        if _is_frame_excluded(contours, slice_index, selected_phase_index):
            continue
        frame = get_frame_row(series_id, slice_index, selected_phase_index)
        image = read_frame_pixels(frame).astype(np.float32)
        masks = _frame_masks(frame_payload, rows, cols)
        frame_result = _compute_lge_frame_threshold_masks(
            image,
            masks,
            threshold_method=threshold_method,
            sd_multiplier=sd_multiplier,
            grey_zone=grey_zone,
        )
        raw_myocardium = frame_result["raw_myocardium"]
        exclude_mask = frame_result["exclude_mask"]
        myocardium = frame_result["myocardium"]
        if int(myocardium.sum()) <= 0:
            continue
        enhanced_seed = frame_result["enhanced_seed"]
        remote_seed = frame_result["remote_seed"]
        baseline_mean = frame_result["baseline_mean"]
        baseline_std = frame_result["baseline_std"]
        threshold = frame_result["threshold"]
        scar_mask = frame_result["scar_mask"]
        grey_mask = frame_result["grey_mask"]
        mvo_mask = frame_result["mvo_mask"]
        if not enhanced_seed.any() and int(scar_mask.sum()) > 0:
            generated = _mask_to_polygon(scar_mask & ~mvo_mask)
            if generated:
                generated_frame = dict(frame_payload)
                generated_frame["enhanced"] = _merge_mask_polygons(generated_frame.get("enhanced"), generated)
                generated_frame_updates[frame_key] = generated_frame
                generated_enhanced_count += 1

        scar_pixels = float(scar_mask.sum())
        myocardium_pixels = float(myocardium.sum())
        scar_volume += scar_pixels * pixel_area * slice_thickness / 1000.0
        myocardium_volume += myocardium_pixels * pixel_area * slice_thickness / 1000.0
        mvo_volume += float(mvo_mask.sum()) * pixel_area * slice_thickness / 1000.0
        grey_volume += float(grey_mask.sum()) * pixel_area * slice_thickness / 1000.0
        exclude_volume += float(exclude_mask.sum()) * pixel_area * slice_thickness / 1000.0
        region_samples["myocardium"].append((image, myocardium, {"slice_index": slice_index, "phase_index": selected_phase_index, "contour_keys": ["endo", "epi", "exclude"]}))
        if int(scar_mask.sum()) > 0:
            region_samples["scar"].append((image, scar_mask, {"slice_index": slice_index, "phase_index": selected_phase_index, "contour_keys": ["enhanced", "remote"]}))
        if int(remote_seed.sum()) > 0:
            region_samples["remote"].append((image, remote_seed, {"slice_index": slice_index, "phase_index": selected_phase_index, "contour_keys": ["remote"]}))
        if int(mvo_mask.sum()) > 0:
            region_samples["mvo"].append((image, mvo_mask, {"slice_index": slice_index, "phase_index": selected_phase_index, "contour_keys": ["mvo"]}))
        if int(grey_mask.sum()) > 0:
            region_samples["grey_zone"].append((image, grey_mask, {"slice_index": slice_index, "phase_index": selected_phase_index, "contour_keys": ["enhanced", "remote"]}))

        center_points = np.argwhere(masks["endo"])
        if center_points.size:
            center_y, center_x = center_points.mean(axis=0)
            myo_points = np.argwhere(myocardium)
            angles = np.arctan2(myo_points[:, 0] - center_y, myo_points[:, 1] - center_x)
            seg_idx = _segment_index(total_slices, slice_index, angles)
            scar_points = np.argwhere(scar_mask)
            scar_angles = np.arctan2(scar_points[:, 0] - center_y, scar_points[:, 1] - center_x)
            scar_seg_idx = _segment_index(total_slices, slice_index, scar_angles)
            for idx in seg_idx:
                if 0 <= idx < len(segment_counts):
                    segment_counts[idx] += 1
            for idx in scar_seg_idx:
                if 0 <= idx < len(segment_scores):
                    segment_scores[idx] += 1

        per_slice.append(
            {
                "slice_index": slice_index,
                "phase_index": selected_phase_index,
                "contour_frame_key": contour_frame_key,
                "scar_volume_ml": round(scar_pixels * pixel_area * slice_thickness / 1000.0, 2),
                "scar_mass_g": round(scar_pixels * pixel_area * slice_thickness / 1000.0 * 1.05, 2),
                "scar_percent": round((scar_pixels / myocardium_pixels) * 100.0, 2) if myocardium_pixels else 0.0,
                "mvo_volume_ml": round(float(mvo_mask.sum()) * pixel_area * slice_thickness / 1000.0, 2),
                "exclude_volume_ml": round(float(exclude_mask.sum()) * pixel_area * slice_thickness / 1000.0, 2),
                "remote_mean": round(baseline_mean, 3),
                "remote_sd": round(baseline_std, 3),
                "threshold": round(threshold, 2),
                "scar_entropy": _round_float(
                    _extract_roi_features(
                        image,
                        scar_mask,
                        pixel_area=pixel_area,
                        slice_thickness=slice_thickness,
                        spacing_y=spacing_y,
                        spacing_x=spacing_x,
                    ).get("intensity_entropy"),
                    6,
                ),
            }
        )

    research_regions = {}
    for region_name, samples in region_samples.items():
        summary = _aggregate_region_features(
            samples,
            pixel_area=pixel_area,
            slice_thickness=slice_thickness,
            spacing_y=spacing_y,
            spacing_x=spacing_x,
        )
        if summary:
            research_regions[region_name] = summary

    if generated_frame_updates:
        contours.setdefault("settings", {})["last_generated_enhanced_count"] = generated_enhanced_count
        contours.setdefault("settings", {})["last_generated_enhanced_at"] = utcnow()
        contours.setdefault("frames", {}).update(generated_frame_updates)
        _update_lge_generated_contours(series_id, contours)

    scar_features = research_regions.get("scar", {})
    payload = {
        "module": "lge",
        "series_id": series_id,
        "metrics": {
            "threshold_method": threshold_method,
            "sd_multiplier": sd_multiplier,
            "grey_zone": grey_zone,
            "phase_index": selected_phase_index,
            "scar_volume_ml": round(scar_volume, 2),
            "scar_mass_g": round(scar_volume * 1.05, 2),
            "scar_percent_myocardium": round((scar_volume / myocardium_volume) * 100.0, 2) if myocardium_volume else 0.0,
            "mvo_volume_ml": round(mvo_volume, 2),
            "mvo_mass_g": round(mvo_volume * 1.05, 2),
            "mvo_percent_myocardium": round((mvo_volume / myocardium_volume) * 100.0, 2) if myocardium_volume else 0.0,
            "exclude_volume_ml": round(exclude_volume, 2),
            "exclude_mass_g": round(exclude_volume * 1.05, 2),
            "grey_zone_volume_ml": round(grey_volume, 2),
            "grey_zone_mass_g": round(grey_volume * 1.05, 2),
            "grey_zone_percent": round((grey_volume / myocardium_volume) * 100.0, 2) if myocardium_volume else 0.0,
            "myocardium_volume_ml": round(myocardium_volume, 2),
            "myocardium_mass_g": round(myocardium_volume * 1.05, 2),
            "generated_enhanced_count": generated_enhanced_count,
            "lge_entropy": _round_float(scar_features.get("intensity_entropy"), 6),
        },
        "per_slice": per_slice,
        "segments": [
            round((segment_scores[index] / segment_counts[index]) * 100.0, 2) if segment_counts[index] else 0.0
            for index in range(16)
        ],
        "research": {
            "region_features": {
                "study": research_regions,
            },
        },
    }
    return _save_measurement(series_id, "lge", payload)


def recompute_measurements_for_module(series_id: int, module: str) -> dict:
    if module == "function":
        result = recompute_function(series_id)
        with get_conn() as conn:
            series = conn.execute("SELECT id, study_id, role FROM series WHERE id = ?", (series_id,)).fetchone()
            related_4ch = []
            if series is not None and series["role"] == "cine_lax_2ch":
                related_4ch = conn.execute(
                    "SELECT id FROM series WHERE study_id = ? AND role = 'cine_lax_4ch' ORDER BY id",
                    (series["study_id"],),
                ).fetchall()
        for row in related_4ch:
            if int(row["id"]) != int(series_id):
                recompute_function(int(row["id"]))
        return result
    if module == "lge":
        return recompute_lge(series_id)
    raise ValueError(f"Unsupported measurement module: {module}")


def measurement_to_csv(study_id: int) -> str:
    def flatten(prefix: str, value) -> list[tuple[str, object]]:
        if isinstance(value, dict):
            rows: list[tuple[str, object]] = []
            for key, nested in value.items():
                next_prefix = f"{prefix}.{key}" if prefix else str(key)
                rows.extend(flatten(next_prefix, nested))
            return rows
        if isinstance(value, list):
            rows: list[tuple[str, object]] = []
            for index, nested in enumerate(value):
                next_prefix = f"{prefix}[{index}]"
                rows.extend(flatten(next_prefix, nested))
            return rows
        return [(prefix, value)]

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT s.description, s.role, m.module, m.payload_json
            FROM measurements m
            JOIN series s ON s.id = m.series_id
            WHERE s.study_id = ?
            ORDER BY s.id, m.module
            """,
            (study_id,),
        ).fetchall()
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["series", "role", "module", "metric", "value"])
    for row in rows:
        payload = loads(row["payload_json"], {})
        flattened = flatten("", payload.get("metrics", {}))
        flattened.extend(flatten("research", payload.get("research", {})))
        for key, value in flattened:
            writer.writerow([row["description"], row["role"], row["module"], key, value])
    return buffer.getvalue()


def _ensure_font() -> str:
    font_name = "Helvetica"
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    if font_path.exists() and "MicrosoftYaHei" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("MicrosoftYaHei", str(font_path)))
        font_name = "MicrosoftYaHei"
    elif "MicrosoftYaHei" in pdfmetrics.getRegisteredFontNames():
        font_name = "MicrosoftYaHei"
    return font_name


def _default_render_path(series_id: int, slice_index: int, phase_index: int) -> Path:
    return RENDER_DIR / f"series-{series_id}-slice-{slice_index}-phase-{phase_index}.png"


def ensure_render(frame: dict, series_id: int) -> Path:
    path = _default_render_path(series_id, frame["slice_index"], frame["phase_index"])
    if path.exists():
        return path
    image = read_frame_pixels(frame)
    Image.fromarray(image).save(path)
    return path


def export_pdf(study_id: int, default_sample_path: str) -> Path:
    detail = fetch_study_detail(study_id, default_sample_path)
    if detail is None:
        raise KeyError(study_id)
    path = EXPORT_DIR / f"study-{study_id}.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    font_name = _ensure_font()
    c.setFont(font_name, 16)
    c.drawString(32, height - 40, "CMR 中文报告")
    c.setFont(font_name, 10)
    c.drawString(32, height - 62, f"患者: {detail['patient_name']}    Study UID: {detail['study_uid']}")
    c.drawString(32, height - 78, f"日期: {detail['study_date']}    来源: {detail['source_path']}")

    y = height - 110
    with get_conn() as conn:
        measurements = conn.execute(
            """
            SELECT s.id, s.description, s.role, m.module, m.payload_json
            FROM measurements m
            JOIN series s ON s.id = m.series_id
            WHERE s.study_id = ?
            ORDER BY s.id, m.module
            """,
            (study_id,),
        ).fetchall()

    for row in measurements:
        payload = loads(row["payload_json"], {})
        c.setFont(font_name, 12)
        c.drawString(32, y, f"{row['description']} ({row['module']})")
        y -= 16
        c.setFont(font_name, 9)
        for key, value in payload.get("metrics", {}).items():
            c.drawString(44, y, f"{key}: {value}")
            y -= 12
        frame = get_frame_row(row["id"], 0, 0)
        image_path = ensure_render(frame, row["id"])
        c.drawImage(ImageReader(str(image_path)), width - 180, y - 60, width=140, height=140, preserveAspectRatio=True, mask="auto")
        y -= 150
        if y < 120:
            c.showPage()
            c.setFont(font_name, 10)
            y = height - 40

    report = detail["report"]
    c.setFont(font_name, 12)
    c.drawString(32, y, "所见")
    y -= 18
    c.setFont(font_name, 10)
    for line in (report["findings"] or "").splitlines() or [""]:
        c.drawString(40, y, line)
        y -= 14
    y -= 8
    c.setFont(font_name, 12)
    c.drawString(32, y, "结论")
    y -= 18
    c.setFont(font_name, 10)
    for line in (report["summary"] or "").splitlines() or [""]:
        c.drawString(40, y, line)
        y -= 14

    c.save()
    return path
