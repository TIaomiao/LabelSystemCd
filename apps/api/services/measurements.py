from __future__ import annotations

import csv
import math
from io import StringIO
from pathlib import Path

import numpy as np
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

from ..config import EXPORT_DIR, RENDER_DIR
from ..db import dumps, get_conn, loads, utcnow
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


def _frame_masks(frame_payload: dict, rows: int, cols: int) -> dict[str, np.ndarray]:
    return {
        "la": _polygon_to_mask(frame_payload.get("la"), rows, cols),
        "ra": _polygon_to_mask(frame_payload.get("ra"), rows, cols),
        "endo": _polygon_to_mask(frame_payload.get("endo"), rows, cols),
        "epi": _polygon_to_mask(frame_payload.get("epi"), rows, cols),
        "rv": _polygon_to_mask(frame_payload.get("rv"), rows, cols),
        "fat": _polygon_to_mask(frame_payload.get("fat"), rows, cols),
        "remote": _polygon_to_mask(frame_payload.get("remote"), rows, cols),
        "enhanced": _polygon_to_mask(frame_payload.get("enhanced"), rows, cols),
        "exclude": _polygon_to_mask(frame_payload.get("exclude"), rows, cols),
        "mvo": _polygon_to_mask(frame_payload.get("mvo"), rows, cols),
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

    phase_totals: dict[int, dict[str, float]] = {}
    per_slice = []
    selected_frame_data: dict[tuple[int, int], tuple[np.ndarray, dict[str, np.ndarray]]] = {}
    for frame in frames:
        frame_payload = contours["frames"].get(_frame_key(frame["slice_index"], frame["phase_index"]))
        if not frame_payload or not frame_payload.get("include", True):
            continue
        if _is_frame_excluded(contours, frame["slice_index"], frame["phase_index"]):
            continue
        image = read_frame_pixels(frame).astype(np.float32)
        masks = _frame_masks(frame_payload, rows, cols)
        myocardium_mask = masks["epi"] & ~masks["endo"]
        endo_area = float(masks["endo"].sum()) * pixel_area
        epi_area = float(masks["epi"].sum()) * pixel_area
        rv_area = float(masks["rv"].sum()) * pixel_area
        fat_area = float(masks["fat"].sum()) * pixel_area
        lv_volume = endo_area * slice_thickness / 1000.0
        rv_volume = rv_area * slice_thickness / 1000.0
        myo_volume = max(epi_area - endo_area, 0.0) * slice_thickness / 1000.0
        fat_volume = fat_area * slice_thickness / 1000.0
        phase_totals.setdefault(frame["phase_index"], {"lv": 0.0, "rv": 0.0, "mass": 0.0})
        phase_totals[frame["phase_index"]]["lv"] += lv_volume
        phase_totals[frame["phase_index"]]["rv"] += rv_volume
        phase_totals[frame["phase_index"]]["mass"] += myo_volume * 1.05
        selected_frame_data[(frame["slice_index"], frame["phase_index"])] = (
            image,
            {
                "endo": masks["endo"],
                "epi": masks["epi"],
                "myocardium": myocardium_mask,
                "rv": masks["rv"],
                "fat": masks["fat"],
                "la": masks["la"],
                "ra": masks["ra"],
            },
        )
        fat_entropy = _extract_roi_features(
            image,
            masks["fat"],
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
                "fat_entropy": _round_float(fat_entropy, 6),
            }
        )

    if not phase_totals:
        return _save_measurement(
            series_id,
            "function",
            {
                "module": "function",
                "series_id": series_id,
                "metrics": {},
                "phase_volumes": [],
                "per_slice": [],
                "research": {"region_features": {}},
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
    edv = phase_totals[ed_phase]["lv"]
    esv = phase_totals[es_phase]["lv"]
    rv_edv = phase_totals[rv_ed_phase]["rv"]
    rv_esv = phase_totals[rv_es_phase]["rv"]

    region_names = ("endo", "epi", "myocardium", "rv", "fat", "la", "ra")

    region_source_keys: dict[str, list[str]] = {
        "endo": ["endo"],
        "epi": ["epi"],
        "myocardium": ["endo", "epi"],
        "rv": ["rv"],
        "fat": ["fat"],
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
                                "contour_keys": region_source_keys.get(name, [name]),
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
    fat_fallback_features = fat_ed_features or research_region_features.get("all_frames", {}).get("fat", {})
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
            "epicardial_fat_entropy": _round_float(fat_fallback_features.get("intensity_entropy"), 6),
        },
        "phase_volumes": phase_volumes,
        "per_slice": per_slice,
        "research": {
            "region_features": research_region_features,
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


def recompute_lge(series_id: int, threshold_method: str | None = None, sd_multiplier: float | None = None, grey_zone: bool | None = None) -> dict:
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
        frame_payload = contours["frames"].get(_frame_key(slice_index, 0))
        if not frame_payload or not frame_payload.get("include", True):
            continue
        if _is_frame_excluded(contours, slice_index, 0):
            continue
        frame = get_frame_row(series_id, slice_index, 0)
        image = read_frame_pixels(frame).astype(np.float32)
        masks = _frame_masks(frame_payload, rows, cols)
        raw_myocardium = masks["epi"] & ~masks["endo"]
        exclude_mask = masks["exclude"] & raw_myocardium
        myocardium = raw_myocardium.copy()
        if exclude_mask.any():
            myocardium = myocardium & ~exclude_mask
        if myocardium.sum() <= 0:
            continue

        enhanced_seed = masks["enhanced"] & myocardium
        remote_seed = (masks["remote"] & myocardium) if masks["remote"].any() else myocardium
        remote_pixels = image[remote_seed]
        if remote_pixels.size == 0:
            remote_pixels = image[myocardium]
        baseline_pixels = remote_pixels[remote_pixels <= np.median(remote_pixels)] if remote_pixels.size else np.array([0.0])
        baseline_mean = float(baseline_pixels.mean()) if baseline_pixels.size else 0.0
        baseline_std = float(baseline_pixels.std()) if baseline_pixels.size else 0.0

        if threshold_method == "fwhm":
            seed_pixels = image[enhanced_seed] if enhanced_seed.any() else image[myocardium]
            seed_max = float(seed_pixels.max()) if seed_pixels.size else float(image[myocardium].max())
            threshold = seed_max * 0.5
            scar_mask = myocardium & (image >= threshold)
            grey_mask = myocardium & (image >= seed_max * 0.35) & (image < threshold) if grey_zone else np.zeros_like(myocardium)
        else:
            threshold = baseline_mean + sd_multiplier * baseline_std
            scar_mask = myocardium & (image >= threshold)
            scar_mask = scar_mask | enhanced_seed
            grey_mask = myocardium & (image >= baseline_mean + 2.0 * baseline_std) & (image < threshold) if grey_zone else np.zeros_like(myocardium)

        scar_mask = binary_opening(binary_closing(scar_mask, disk(1)), disk(1))
        scar_mask = remove_small_objects(scar_mask.astype(bool), min_size=max(6, int(0.0002 * rows * cols)))
        mvo_mask = masks["mvo"] & raw_myocardium
        scar_mask = (scar_mask | mvo_mask) & myocardium
        if not enhanced_seed.any() and int(scar_mask.sum()) > 0:
            generated = _mask_to_polygon(scar_mask & ~mvo_mask)
            if generated:
                frame_key = _frame_key(slice_index, 0)
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
        region_samples["myocardium"].append((image, myocardium, {"slice_index": slice_index, "phase_index": 0, "contour_keys": ["endo", "epi", "exclude"]}))
        if int(scar_mask.sum()) > 0:
            region_samples["scar"].append((image, scar_mask, {"slice_index": slice_index, "phase_index": 0, "contour_keys": ["enhanced", "remote"]}))
        if int(remote_seed.sum()) > 0:
            region_samples["remote"].append((image, remote_seed, {"slice_index": slice_index, "phase_index": 0, "contour_keys": ["remote"]}))
        if int(mvo_mask.sum()) > 0:
            region_samples["mvo"].append((image, mvo_mask, {"slice_index": slice_index, "phase_index": 0, "contour_keys": ["mvo"]}))
        if int(grey_mask.sum()) > 0:
            region_samples["grey_zone"].append((image, grey_mask, {"slice_index": slice_index, "phase_index": 0, "contour_keys": ["enhanced", "remote"]}))

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
                "scar_volume_ml": round(scar_pixels * pixel_area * slice_thickness / 1000.0, 2),
                "scar_mass_g": round(scar_pixels * pixel_area * slice_thickness / 1000.0 * 1.05, 2),
                "scar_percent": round((scar_pixels / myocardium_pixels) * 100.0, 2) if myocardium_pixels else 0.0,
                "mvo_volume_ml": round(float(mvo_mask.sum()) * pixel_area * slice_thickness / 1000.0, 2),
                "exclude_volume_ml": round(float(exclude_mask.sum()) * pixel_area * slice_thickness / 1000.0, 2),
                "remote_mean": round(baseline_mean, 3),
                "remote_sd": round(baseline_std, 3),
                "threshold": round(threshold, 3),
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
        return recompute_function(series_id)
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
