from __future__ import annotations

import json
import logging
import math
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image
from skimage.filters import gaussian, threshold_otsu
from skimage.measure import find_contours, label, regionprops
from skimage.morphology import binary_closing, binary_opening, dilation, disk, remove_small_objects

from ..db import dumps, get_conn, loads, utcnow
from .dicom_indexer import get_frame_row, get_series_row, list_frame_rows, read_frame_pixels
from .job_control import JobPaused, ProgressCallback, ShouldPauseCallback
from .measurements import recompute_measurements_for_module
from .model_runner import run_model_inference
from .propagation_runner import run_propagation_inference


logger = logging.getLogger(__name__)


CONTOUR_VALIDATION_KEYS = (
    "la",
    "ra",
    "endo",
    "epi",
    "ventricular_epi",
    "rv",
    "fat",
    "fat_outer",
    "remote",
    "enhanced",
    "exclude",
    "mvo",
)
EXCLUDE_REGIONS_KEY = "exclude_regions"


@dataclass
class SeriesContext:
    series: dict
    frames: list[dict]


class InferenceAdapter(Protocol):
    name: str

    def run(
        self,
        context: SeriesContext,
        module: str,
        *,
        progress: ProgressCallback | None = None,
        should_pause: ShouldPauseCallback | None = None,
    ) -> dict:
        ...


class ModelAdapter:
    name = "model"

    def run(
        self,
        context: SeriesContext,
        module: str,
        *,
        progress: ProgressCallback | None = None,
        should_pause: ShouldPauseCallback | None = None,
    ) -> dict:
        return run_model_inference(
            series=context.series,
            frames=context.frames,
            module=module,
            progress=progress,
            should_pause=should_pause,
        )


class FastHeuristicAdapter:
    name = "fast"

    def run(
        self,
        context: SeriesContext,
        module: str,
        *,
        progress: ProgressCallback | None = None,
        should_pause: ShouldPauseCallback | None = None,
    ) -> dict:
        if module == "lge":
            raise ValueError("LGE 的快速分割目前质量不足，已禁用。请使用 AI 分割或手工勾画。")
        if should_pause and should_pause():
            raise JobPaused("快速初稿已暂停。")
        if progress:
            progress(0, 1, "正在生成快速初稿")
        return self._run_function(context)

    def _run_function(self, context: SeriesContext) -> dict:
        contour_frames = {}
        phase_totals: dict[int, float] = {}
        frames_by_slice: dict[int, list[dict]] = {}
        for frame in context.frames:
            frames_by_slice.setdefault(frame["slice_index"], []).append(frame)

        for slice_index, frames in frames_by_slice.items():
            ordered_frames = sorted(frames, key=lambda frame: frame["phase_index"])
            last_center = None
            for frame in ordered_frames:
                pixels = read_frame_pixels(frame)
                lv_mask, epi_mask, rv_mask, center = _segment_function_frame(pixels, last_center)
                if lv_mask is None or epi_mask is None or center is None:
                    continue
                last_center = center
                contour_frames[_frame_key(frame["slice_index"], frame["phase_index"])] = {
                    "include": True,
                    "endo": _mask_to_polygon(lv_mask, frame),
                    "epi": _mask_to_polygon(epi_mask, frame),
                    "ventricular_epi": None,
                    "rv": _mask_to_polygon(rv_mask, frame) if rv_mask is not None else None,
                    "fat": None,
                    "fat_outer": None,
                    "remote": None,
                    "enhanced": None,
                    "exclude": None,
                    "mvo": None,
                }
                phase_totals[frame["phase_index"]] = phase_totals.get(frame["phase_index"], 0.0) + float(lv_mask.sum())

        ed_phase = 0
        es_phase = 0
        if phase_totals:
            ed_phase = max(phase_totals.items(), key=lambda item: item[1])[0]
            es_phase = min(phase_totals.items(), key=lambda item: item[1])[0]

        return {
            "series_id": context.series["id"],
            "module": "function",
            "coordinate_space": "pixel",
            "source": "fast-heuristic",
            "settings": {"method": "otsu+morphology"},
            "phase_labels": {"ed": ed_phase, "es": es_phase},
            "frames": contour_frames,
        }

    def _run_lge(self, context: SeriesContext) -> dict:
        contour_frames = {}
        frames_by_slice: dict[int, list[dict]] = {}
        for frame in context.frames:
            frames_by_slice.setdefault(frame["slice_index"], []).append(frame)

        for frames in frames_by_slice.values():
            reference_frame = min(frames, key=lambda frame: frame["phase_index"])
            pixels = read_frame_pixels(reference_frame)
            lv_mask, epi_mask, _rv_mask, _center = _segment_function_frame(pixels, None)
            if lv_mask is None or epi_mask is None:
                continue
            contour_frames[_frame_key(reference_frame["slice_index"], reference_frame["phase_index"])] = {
                "include": True,
                "endo": _mask_to_polygon(lv_mask, reference_frame),
                "epi": _mask_to_polygon(epi_mask, reference_frame),
                "ventricular_epi": None,
                "rv": None,
                "fat": None,
                "fat_outer": None,
                "remote": None,
                "enhanced": None,
                "exclude": None,
                "mvo": None,
            }

        return {
            "series_id": context.series["id"],
            "module": "lge",
            "coordinate_space": "pixel",
            "source": "fast-heuristic",
            "settings": {"method": "otsu+morphology", "note": "仅快速生成心内膜/心外膜初稿"},
            "phase_labels": {"ed": 0, "es": 0},
            "frames": contour_frames,
        }


class PropagationAdapter:
    name = "propagate"

    def run(
        self,
        context: SeriesContext,
        module: str,
        *,
        progress: ProgressCallback | None = None,
        should_pause: ShouldPauseCallback | None = None,
    ) -> dict:
        existing = fetch_contours(int(context.series["id"]), module)
        return run_propagation_inference(
            series=context.series,
            frames=context.frames,
            module=module,
            contour_set=existing,
            progress=progress,
            should_pause=should_pause,
        )


def _frame_key(slice_index: int, phase_index: int) -> str:
    return f"{slice_index}:{phase_index}"


def _normalize_origin(source: str | None, default: str = "legacy") -> str:
    raw = (source or "").strip().lower()
    if not raw:
        return default
    if "manual" in raw and "prompt" not in raw:
        return "manual"
    if "prompt" in raw:
        return "manual_refine"
    if "neighbor" in raw or "propagat" in raw or "optical-flow" in raw:
        return "propagate"
    if "bundle" in raw or "model" in raw or "edgetam" in raw:
        return "ai"
    if "fast" in raw or "heuristic" in raw:
        return "fast"
    if "copy" in raw:
        return "copy"
    if "filesystem" in raw or "legacy" in raw:
        return "legacy"
    return default


def _origin_label(origin: str) -> str:
    labels = {
        "manual": "人工",
        "manual_refine": "人工修订",
        "ai": "AI",
        "propagate": "传播补全",
        "fast": "快速初稿",
        "copy": "复制",
        "legacy": "旧标注",
    }
    return labels.get(origin, origin or "未知")


def _payload_has_propagation_history(payload: dict) -> bool:
    source = str(payload.get("source") or "").lower()
    if "propagat" in source or "neighbor" in source or "edgetam" in source or "optical-flow" in source:
        return True
    settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
    backend = str(settings.get("backend") or "").lower()
    if "propagat" in backend or "edgetam" in backend or "optical" in backend:
        return True
    return any(
        key in settings
        for key in ("propagation", "propagation_axes", "neighbor_propagation", "seed_frame_count")
    )


def _actor_meta(actor: dict | None) -> dict:
    actor = actor or {}
    return {
        "user_id": int(actor["user_id"]) if actor.get("user_id") not in (None, "", "unknown") else None,
        "username": str(actor.get("username") or "").strip() or "未知",
        "is_admin": bool(actor.get("is_admin", False)),
    }


def _payload_signature(value: dict | None) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _contour_has_points(contour: dict | None) -> bool:
    if not isinstance(contour, dict):
        return False
    points = contour.get("points")
    return isinstance(points, list) and len(points) >= 3


def _exclude_regions_from_frame(frame_payload: dict | None) -> list[dict]:
    if not isinstance(frame_payload, dict):
        return []
    raw_regions = frame_payload.get(EXCLUDE_REGIONS_KEY)
    if isinstance(raw_regions, list):
        return [region for region in raw_regions if _contour_has_points(region)]
    legacy_exclude = frame_payload.get("exclude")
    return [legacy_exclude] if _contour_has_points(legacy_exclude) else []


def _normalize_frame_exclude_regions(frame_payload: dict) -> dict:
    normalized = dict(frame_payload)
    has_regions_field = EXCLUDE_REGIONS_KEY in normalized
    regions = _exclude_regions_from_frame(normalized)
    if has_regions_field or regions:
        normalized[EXCLUDE_REGIONS_KEY] = regions
        normalized["exclude"] = regions[-1] if regions else None
    return normalized


def _preserve_exclude_regions_for_legacy_save(existing: dict | None, incoming: dict) -> dict:
    existing_frames = existing.get("frames") if isinstance(existing, dict) else None
    incoming_frames = incoming.get("frames") if isinstance(incoming, dict) else None
    if not isinstance(existing_frames, dict) or not isinstance(incoming_frames, dict):
        return incoming

    preserved = dict(incoming)
    next_frames = dict(incoming_frames)
    for frame_key, frame_payload in incoming_frames.items():
        if not isinstance(frame_payload, dict):
            continue
        next_frame = dict(frame_payload)
        raw_regions = next_frame.get(EXCLUDE_REGIONS_KEY)
        if isinstance(raw_regions, list):
            next_frames[frame_key] = _normalize_frame_exclude_regions(next_frame)
            continue
        if _contour_has_points(next_frame.get("exclude")):
            next_frame[EXCLUDE_REGIONS_KEY] = [next_frame["exclude"]]
            next_frames[frame_key] = _normalize_frame_exclude_regions(next_frame)
            continue
        existing_regions = _exclude_regions_from_frame(existing_frames.get(frame_key))
        if existing_regions:
            next_frame[EXCLUDE_REGIONS_KEY] = existing_regions
            next_frame["exclude"] = existing_regions[-1]
        next_frames[frame_key] = next_frame

    preserved["frames"] = next_frames
    return preserved


PHASE_LABEL_SETTING_KEYS = (
    "ed",
    "es",
    "lv_ed",
    "lv_es",
    "rv_ed",
    "rv_es",
    "la_max",
    "la_pre_a",
    "la_min",
    "ra_max",
    "ra_pre_a",
    "ra_min",
)


def _normalize_phase_labels(value: dict | None) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, int] = {}
    for key in PHASE_LABEL_SETTING_KEYS:
        raw = value.get(key)
        if raw in (None, ""):
            continue
        try:
            normalized[key] = int(raw)
        except (TypeError, ValueError):
            continue
    return normalized


def _phase_label_effective(manual: dict[str, int], auto: dict[str, int]) -> dict[str, int]:
    return {**auto, **manual}


def _phase_detection_signature(settings: dict | None) -> str:
    settings = settings if isinstance(settings, dict) else {}
    detection_payload = {
        "ed_es_detection_method": settings.get("ed_es_detection_method"),
        "ed_es_detection_scores": settings.get("ed_es_detection_scores"),
    }
    return _payload_signature(detection_payload)


def _resolve_cached_phase_labels(payload: dict) -> dict:
    payload = dict(payload or {})
    settings = dict(payload.get("settings") or {})
    manual_phase_labels = _normalize_phase_labels(settings.get("manual_phase_labels"))
    auto_phase_labels = _normalize_phase_labels(settings.get("auto_phase_labels"))
    direct_phase_labels = _normalize_phase_labels(payload.get("phase_labels"))

    if not manual_phase_labels and not auto_phase_labels and direct_phase_labels:
        manual_phase_labels = dict(direct_phase_labels)

    settings["manual_phase_labels"] = manual_phase_labels
    settings["auto_phase_labels"] = auto_phase_labels
    payload["settings"] = settings
    payload["phase_labels"] = _phase_label_effective(manual_phase_labels, auto_phase_labels)
    return payload


def _prepare_phase_labels_for_save(existing: dict | None, incoming: dict) -> dict:
    incoming = dict(incoming or {})
    existing_settings = dict((existing or {}).get("settings") or {})
    incoming_settings = dict(incoming.get("settings") or {})

    manual_phase_labels = _normalize_phase_labels(
        incoming_settings.get("manual_phase_labels") or existing_settings.get("manual_phase_labels")
    )
    auto_phase_labels = _normalize_phase_labels(
        incoming_settings.get("auto_phase_labels") or existing_settings.get("auto_phase_labels")
    )
    incoming_phase_labels = _normalize_phase_labels(incoming.get("phase_labels"))
    existing_phase_labels = _normalize_phase_labels((existing or {}).get("phase_labels"))
    existing_effective_phase_labels = _phase_label_effective(manual_phase_labels, auto_phase_labels)

    detection_changed = _phase_detection_signature(incoming_settings) != _phase_detection_signature(existing_settings)
    if incoming_phase_labels:
        if detection_changed:
            auto_phase_labels = dict(incoming_phase_labels)
        elif manual_phase_labels and auto_phase_labels and incoming_phase_labels == auto_phase_labels:
            pass
        elif incoming_phase_labels != existing_phase_labels and incoming_phase_labels != existing_effective_phase_labels:
            manual_phase_labels = dict(incoming_phase_labels)

    incoming_settings["manual_phase_labels"] = manual_phase_labels
    incoming_settings["auto_phase_labels"] = auto_phase_labels
    incoming["settings"] = incoming_settings
    incoming["phase_labels"] = _phase_label_effective(manual_phase_labels, auto_phase_labels)
    return incoming


def _build_top_meta(
    payload: dict,
    *,
    stored_updated_at: str | None = None,
    actor: dict | None = None,
) -> dict:
    meta = dict(payload.get("annotation_meta") or {})
    actor_meta = _actor_meta(actor)
    origin = _normalize_origin(payload.get("source"), "legacy")
    default_time = stored_updated_at or utcnow()
    meta.setdefault("created_at", default_time)
    meta.setdefault("created_by_user_id", actor_meta["user_id"])
    meta.setdefault("created_by_username", actor_meta["username"] if actor else ("历史标注" if origin == "legacy" else "未知"))
    meta["updated_at"] = default_time
    meta["updated_by_user_id"] = actor_meta["user_id"]
    meta["updated_by_username"] = actor_meta["username"] if actor else meta.get("updated_by_username") or meta.get("created_by_username") or "未知"
    meta["origin"] = origin
    meta["origin_label"] = _origin_label(origin)
    meta["legacy"] = bool(meta.get("legacy", False) or origin == "legacy")
    return meta


def _normalize_contour_payload(
    payload: dict,
    *,
    series_id: int,
    module: str,
    stored_updated_at: str | None = None,
    actor: dict | None = None,
) -> dict:
    payload = dict(payload or {})
    payload["series_id"] = series_id
    payload["module"] = module
    payload.setdefault("coordinate_space", "pixel")
    payload.setdefault("source", "manual")
    payload.setdefault("settings", {})
    payload.setdefault("phase_labels", {})
    payload.setdefault("frames", {})
    payload = _resolve_cached_phase_labels(payload)
    top_meta = _build_top_meta(payload, stored_updated_at=stored_updated_at, actor=actor)
    payload["annotation_meta"] = top_meta
    raw_frame_meta = payload.get("frame_meta")
    has_explicit_frame_meta = isinstance(raw_frame_meta, dict) and bool(raw_frame_meta)
    frame_meta = dict(raw_frame_meta or {})
    default_frame_time = top_meta.get("updated_at") or stored_updated_at or utcnow()
    default_origin = top_meta.get("origin") or _normalize_origin(payload.get("source"), "legacy")
    infer_legacy_propagation_origin = not has_explicit_frame_meta and _payload_has_propagation_history(payload)
    if infer_legacy_propagation_origin:
        default_origin = "propagate"
    for frame_key in list(payload["frames"].keys()):
        frame_payload = payload["frames"].get(frame_key)
        if isinstance(frame_payload, dict):
            payload["frames"][frame_key] = _normalize_frame_exclude_regions(frame_payload)
        item = dict(frame_meta.get(frame_key) or {})
        item.setdefault("created_at", default_frame_time)
        item.setdefault("updated_at", default_frame_time)
        item.setdefault("created_by_user_id", top_meta.get("created_by_user_id"))
        item.setdefault("created_by_username", top_meta.get("created_by_username"))
        item.setdefault("updated_by_user_id", top_meta.get("updated_by_user_id"))
        item.setdefault("updated_by_username", top_meta.get("updated_by_username"))
        origin_source = item.get("origin") or (None if infer_legacy_propagation_origin else payload.get("source"))
        origin = _normalize_origin(origin_source, default_origin)
        item["origin"] = origin
        item["origin_label"] = _origin_label(origin)
        item["legacy"] = bool(item.get("legacy", False) or top_meta.get("legacy", False) or origin == "legacy")
        frame_meta[frame_key] = item
    payload["frame_meta"] = frame_meta
    return payload


def _merge_contour_metadata(
    existing: dict | None,
    incoming: dict,
    *,
    series_id: int,
    module: str,
    stored_updated_at: str | None = None,
    actor: dict | None = None,
    action_origin: str | None = None,
    source_frame_key: str | None = None,
) -> dict:
    normalized_existing = _normalize_contour_payload(
        existing or {},
        series_id=series_id,
        module=module,
        stored_updated_at=stored_updated_at,
        actor=None,
    ) if existing else None
    normalized_incoming = _normalize_contour_payload(
        incoming,
        series_id=series_id,
        module=module,
        stored_updated_at=stored_updated_at,
        actor=actor,
    )
    actor_meta = _actor_meta(actor)
    now = utcnow()
    payload_source_origin = _normalize_origin(action_origin or normalized_incoming.get("source"), "manual")
    existing_frames = (normalized_existing or {}).get("frames", {})
    existing_meta = (normalized_existing or {}).get("frame_meta", {})
    incoming_frame_meta = dict(normalized_incoming.get("frame_meta") or {})
    changed_origins: list[str] = []

    for frame_key, frame_payload in normalized_incoming.get("frames", {}).items():
        prev_payload = existing_frames.get(frame_key)
        prev_meta = dict(existing_meta.get(frame_key) or {})
        next_meta = dict(incoming_frame_meta.get(frame_key) or {})
        changed = _payload_signature(prev_payload) != _payload_signature(frame_payload)
        if prev_meta and not changed:
            incoming_frame_meta[frame_key] = prev_meta
            continue

        origin = payload_source_origin
        if action_origin == "manual":
            previous_origin = _normalize_origin(prev_meta.get("origin") or (normalized_existing or {}).get("source"), "manual")
            origin = "manual_refine" if prev_payload and previous_origin in {"ai", "propagate", "fast", "legacy"} else "manual"
        elif action_origin == "prompt":
            origin = "manual_refine" if prev_payload else "manual"
        changed_origins.append(origin)

        created_at = prev_meta.get("created_at") or now
        next_meta.update({
            "created_at": created_at,
            "updated_at": now,
            "created_by_user_id": prev_meta.get("created_by_user_id", actor_meta["user_id"]),
            "created_by_username": prev_meta.get("created_by_username", actor_meta["username"] if actor else "未知"),
            "updated_by_user_id": actor_meta["user_id"],
            "updated_by_username": actor_meta["username"] if actor else prev_meta.get("updated_by_username", "未知"),
            "origin": origin,
            "origin_label": _origin_label(origin),
            "legacy": bool(prev_meta.get("legacy", False) and not actor),
        })
        if source_frame_key:
            next_meta["source_frame"] = source_frame_key
        elif action_origin not in {"propagate"} and "source_frame" in next_meta:
            next_meta.pop("source_frame", None)
        incoming_frame_meta[frame_key] = next_meta

    normalized_incoming["frame_meta"] = incoming_frame_meta
    top_meta = dict(normalized_incoming.get("annotation_meta") or {})
    if normalized_existing and normalized_existing.get("annotation_meta"):
        existing_top = normalized_existing["annotation_meta"]
        top_meta["created_at"] = existing_top.get("created_at", top_meta.get("created_at"))
        top_meta["created_by_user_id"] = existing_top.get("created_by_user_id", top_meta.get("created_by_user_id"))
        top_meta["created_by_username"] = existing_top.get("created_by_username", top_meta.get("created_by_username"))
    if action_origin == "manual":
        top_origin = "manual_refine" if "manual_refine" in changed_origins else "manual"
    elif action_origin == "prompt":
        top_origin = "manual_refine"
    else:
        top_origin = payload_source_origin
    top_meta.update({
        "updated_at": now,
        "updated_by_user_id": actor_meta["user_id"],
        "updated_by_username": actor_meta["username"] if actor else top_meta.get("updated_by_username", "未知"),
        "origin": top_origin,
        "origin_label": _origin_label(top_origin),
        "legacy": bool(top_meta.get("legacy", False) and not actor),
    })
    normalized_incoming["annotation_meta"] = top_meta
    return normalized_incoming


def _pixel_to_patient(frame: dict, x: float, y: float) -> list[float]:
    metadata = loads(frame["metadata_json"], {})
    image_position = loads(frame["image_position_json"], [0.0, 0.0, 0.0])
    orientation = metadata.get("image_orientation", [1.0, 0.0, 0.0, 0.0, 1.0, 0.0])
    pixel_spacing = metadata.get("pixel_spacing", [1.0, 1.0])
    row_dir = np.array(orientation[:3], dtype=float)
    col_dir = np.array(orientation[3:6], dtype=float)
    origin = np.array(image_position, dtype=float)
    point = origin + col_dir * pixel_spacing[0] * x + row_dir * pixel_spacing[1] * y
    return [round(float(value), 3) for value in point]


def _sample_contour_points(contour: np.ndarray, max_points: int = 160) -> np.ndarray:
    if len(contour) <= 1:
        return contour
    perimeter = float(np.linalg.norm(np.roll(contour, -1, axis=0) - contour, axis=1).sum())
    target_points = int(np.clip(round(perimeter / 5.5), 28, max_points))
    if len(contour) <= target_points:
        return contour
    sample_indices = np.linspace(0, len(contour) - 1, num=target_points, dtype=int)
    sample_indices = np.unique(sample_indices)
    return contour[sample_indices]


def _mask_to_polygon(mask: np.ndarray | None, frame: dict, scale_x: float = 1.0, scale_y: float = 1.0):
    if mask is None or mask.sum() < 20:
        return None
    contours = find_contours(mask.astype(float), 0.5)
    if not contours:
        return None
    contour = _sample_contour_points(max(contours, key=len))
    points = []
    for y, x in contour:
        sx = float(x * scale_x)
        sy = float(y * scale_y)
        points.append({"x": round(sx, 2), "y": round(sy, 2), "patient": _pixel_to_patient(frame, sx, sy)})
    if len(points) < 3:
        return None
    return {"points": points, "closed": True}


def _decode_prediction_masks(image_path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rgb = np.array(Image.open(image_path).convert("RGB")).astype(np.int16)
    red = (rgb[:, :, 0] - rgb[:, :, 1] > 45) & (rgb[:, :, 0] - rgb[:, :, 2] > 45)
    green = (rgb[:, :, 1] - rgb[:, :, 0] > 45) & (rgb[:, :, 1] - rgb[:, :, 2] > 45)
    blue = (rgb[:, :, 2] - rgb[:, :, 0] > 45) & (rgb[:, :, 2] - rgb[:, :, 1] > 45)
    red = remove_small_objects(binary_closing(red, disk(1)), 6)
    green = remove_small_objects(binary_closing(green, disk(1)), 6)
    blue = remove_small_objects(binary_closing(blue, disk(1)), 6)
    return red, green, blue


def _segment_function_frame(image: np.ndarray, seed_center: tuple[float, float] | None):
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
        return None, None, None, None

    target_center = np.array([height / 2.0, width / 2.0]) if seed_center is None else np.array([seed_center[1], seed_center[0]])
    ordered = sorted(
        regions,
        key=lambda region: (
            np.linalg.norm(np.array(region.centroid) - target_center),
            -region.area,
        ),
    )
    lv_region = ordered[0]
    lv_mask = components == lv_region.label
    wall_radius = int(max(5, min(12, math.sqrt(max(lv_region.area, 1)) * 0.12)))
    epi_mask = dilation(lv_mask, disk(wall_radius))
    rv_mask = None
    for region in ordered[1:]:
        distance = np.linalg.norm(np.array(region.centroid) - np.array(lv_region.centroid))
        if region.area >= 40 and distance < max(height, width) * 0.35:
            rv_mask = components == region.label
            break
    center = (float(lv_region.centroid[1]), float(lv_region.centroid[0]))
    return lv_mask, epi_mask, rv_mask, center


class FilesystemPredictionAdapter:
    name = "filesystem"

    def run(self, context: SeriesContext, module: str) -> dict:
        if module == "lge":
            return self._run_lge(context)
        return self._run_function(context)

    def _run_lge(self, context: SeriesContext) -> dict:
        series = context.series
        prediction_dir = Path(series["folder_path"]) / "predictions"
        rows = int(series["rows"] or 1)
        cols = int(series["cols"] or 1)
        scale_x = cols / 160.0
        scale_y = rows / 160.0
        contour_frames = {}
        ordered_frames = sorted(
            context.frames,
            key=lambda frame: (frame["instance_number"] or 0, frame["slice_index"], frame["phase_index"]),
        )
        for index, frame in enumerate(ordered_frames):
            image_path = prediction_dir / f"slice_{index:03d}.png"
            if not image_path.exists():
                continue
            red, green, blue = _decode_prediction_masks(image_path)
            myocardium = red | green
            contour_frames[_frame_key(frame["slice_index"], frame["phase_index"])] = {
                "include": True,
                "endo": _mask_to_polygon(red, frame, scale_x, scale_y),
                "epi": _mask_to_polygon(myocardium, frame, scale_x, scale_y),
                "ventricular_epi": None,
                "rv": None,
                "fat": None,
                "fat_outer": None,
                "remote": _mask_to_polygon(green & ~blue, frame, scale_x, scale_y),
                "enhanced": _mask_to_polygon(blue, frame, scale_x, scale_y),
                "exclude": None,
                "mvo": None,
            }
        return {
            "series_id": series["id"],
            "module": "lge",
            "coordinate_space": "pixel",
            "source": "filesystem",
            "settings": {"threshold_method": "nsd", "sd_multiplier": 5.0, "grey_zone": False},
            "phase_labels": {"ed": 0, "es": 0},
            "frames": contour_frames,
        }

    def _run_function(self, context: SeriesContext) -> dict:
        series = context.series
        prediction_dir = Path(series["folder_path"]) / "predictions"
        contour_frames = {}
        rows = int(series["rows"] or 1)
        cols = int(series["cols"] or 1)
        scale_x = cols / 160.0
        scale_y = rows / 160.0
        slice_seed: dict[int, tuple[float, float]] = {}
        phase_totals: dict[int, float] = {}

        for slice_index in range(series["slice_count"]):
            image_path = prediction_dir / f"slice_{slice_index:03d}.png"
            if not image_path.exists():
                continue
            red, _green, _blue = _decode_prediction_masks(image_path)
            if red.sum() <= 0:
                continue
            center = tuple(np.mean(np.column_stack(np.where(red))[:, ::-1], axis=0).tolist())
            slice_seed[slice_index] = (center[0] * scale_x, center[1] * scale_y)

        frames_by_slice: dict[int, list[dict]] = {}
        for frame in context.frames:
            frames_by_slice.setdefault(frame["slice_index"], []).append(frame)

        for slice_index, frames in frames_by_slice.items():
            frames = sorted(frames, key=lambda frame: frame["phase_index"])
            seed = slice_seed.get(slice_index)
            last_center = seed
            for frame in frames:
                pixels = read_frame_pixels(frame)
                lv_mask, epi_mask, rv_mask, center = _segment_function_frame(pixels, last_center)
                if lv_mask is None or epi_mask is None or center is None:
                    continue
                last_center = center
                contour_frames[_frame_key(frame["slice_index"], frame["phase_index"])] = {
                    "include": True,
                    "endo": _mask_to_polygon(lv_mask, frame),
                    "epi": _mask_to_polygon(epi_mask, frame),
                    "ventricular_epi": None,
                    "rv": _mask_to_polygon(rv_mask, frame) if rv_mask is not None else None,
                    "fat": None,
                    "fat_outer": None,
                    "remote": None,
                    "enhanced": None,
                    "exclude": None,
                    "mvo": None,
                }
                phase_totals[frame["phase_index"]] = phase_totals.get(frame["phase_index"], 0.0) + float(lv_mask.sum())

        ed_phase = 0
        es_phase = 0
        if phase_totals:
            ed_phase = max(phase_totals.items(), key=lambda item: item[1])[0]
            es_phase = min(phase_totals.items(), key=lambda item: item[1])[0]

        return {
            "series_id": series["id"],
            "module": "function",
            "coordinate_space": "pixel",
            "source": "filesystem+heuristic",
            "settings": {"generated_from_predictions": bool(slice_seed)},
            "phase_labels": {"ed": ed_phase, "es": es_phase},
            "frames": contour_frames,
        }


def _point_xy(point: dict | None) -> tuple[float, float] | None:
    if not isinstance(point, dict):
        return None
    try:
        x = float(point["x"])
        y = float(point["y"])
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(x) or not math.isfinite(y):
        return None
    return x, y


def _contour_points(contour: dict | None) -> list[tuple[float, float]]:
    if not isinstance(contour, dict):
        return []
    points = [_point_xy(point) for point in contour.get("points") or []]
    clean = [point for point in points if point is not None]
    if len(clean) > 1 and math.hypot(clean[0][0] - clean[-1][0], clean[0][1] - clean[-1][1]) <= 1e-6:
        clean = clean[:-1]
    return clean


def _orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _point_on_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    eps: float = 1e-7,
) -> bool:
    return (
        min(start[0], end[0]) - eps <= point[0] <= max(start[0], end[0]) + eps
        and min(start[1], end[1]) - eps <= point[1] <= max(start[1], end[1]) + eps
        and abs(_orientation(start, end, point)) <= eps
    )


def _segments_intersect(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
    *,
    eps: float = 1e-7,
) -> bool:
    ab_c = _orientation(a, b, c)
    ab_d = _orientation(a, b, d)
    cd_a = _orientation(c, d, a)
    cd_b = _orientation(c, d, b)
    if ab_c * ab_d < -eps and cd_a * cd_b < -eps:
        return True
    return (
        _point_on_segment(c, a, b, eps=eps)
        or _point_on_segment(d, a, b, eps=eps)
        or _point_on_segment(a, c, d, eps=eps)
        or _point_on_segment(b, c, d, eps=eps)
    )


def _has_self_intersection(points: list[tuple[float, float]], closed: bool) -> bool:
    if not closed or len(points) < 4:
        return False
    segment_count = len(points)
    for index in range(segment_count):
        a = points[index]
        b = points[(index + 1) % segment_count]
        if math.hypot(b[0] - a[0], b[1] - a[1]) <= 1e-6:
            continue
        for other_index in range(index + 1, segment_count):
            if abs(index - other_index) <= 1:
                continue
            if index == 0 and other_index == segment_count - 1:
                continue
            c = points[other_index]
            d = points[(other_index + 1) % segment_count]
            if math.hypot(d[0] - c[0], d[1] - c[1]) <= 1e-6:
                continue
            if _segments_intersect(a, b, c, d):
                return True
    return False


def _validate_contours_for_save(payload: dict) -> None:
    """Self-intersection check downgraded to warn-only (2026-08-19).

    手绘排除区等自由笔迹很容易轻微自碰，此前这里直接 raise 导致保存被 400 拒绝，
    重算指标流程的第一步（保存）失败，指标永远不更新。自交多边形光栅化不会崩溃，
    结果按 even-odd 规则可预期，且前端有填充蒙层可供医生肉眼核对，
    因此改为记录警告并照常保存。
    """
    frames = payload.get("frames") if isinstance(payload, dict) else None
    if not isinstance(frames, dict):
        return
    for frame_key, frame_payload in frames.items():
        if not isinstance(frame_payload, dict):
            continue
        for contour_key in CONTOUR_VALIDATION_KEYS:
            if contour_key == "exclude" and isinstance(frame_payload.get(EXCLUDE_REGIONS_KEY), list):
                continue
            contour = frame_payload.get(contour_key)
            if not isinstance(contour, dict) or contour.get("closed", True) is False:
                continue
            points = _contour_points(contour)
            if _has_self_intersection(points, closed=True):
                logger.warning(
                    "Self-intersecting contour saved anyway series frame=%s contour=%s",
                    frame_key,
                    contour_key,
                )
        raw_regions = frame_payload.get(EXCLUDE_REGIONS_KEY)
        if not isinstance(raw_regions, list):
            continue
        for region_index, contour in enumerate(raw_regions):
            if not isinstance(contour, dict) or contour.get("closed", True) is False:
                continue
            points = _contour_points(contour)
            if _has_self_intersection(points, closed=True):
                logger.warning(
                    "Self-intersecting contour saved anyway frame=%s exclude_regions[%d]",
                    frame_key,
                    region_index,
                )


def _read_contours_for_update(conn, series_id: int, module: str) -> tuple[dict | None, str | None]:
    row = conn.execute(
        "SELECT payload_json, updated_at FROM contours WHERE series_id = ? AND module = ?",
        (series_id, module),
    ).fetchone()
    if row is None:
        return None, None
    payload = loads(row["payload_json"], {})
    return (payload if isinstance(payload, dict) else {}), row["updated_at"]


def _write_contours_in_transaction(
    conn,
    series_id: int,
    module: str,
    payload: dict,
    *,
    exists: bool,
) -> None:
    updated_at = utcnow()
    if exists:
        conn.execute(
            "UPDATE contours SET payload_json = ?, updated_at = ? WHERE series_id = ? AND module = ?",
            (dumps(payload), updated_at, series_id, module),
        )
    else:
        conn.execute(
            "INSERT INTO contours (series_id, module, payload_json, updated_at) VALUES (?, ?, ?, ?)",
            (series_id, module, dumps(payload), updated_at),
        )


def _upsert_contours(series_id: int, module: str, payload: dict) -> dict:
    """Persist a generic contour write without allowing it to replace manual curvature.

    The final read/merge/write deliberately happens below ``BEGIN IMMEDIATE``.  A
    legacy PUT or model job may have prepared ``payload`` from an old snapshot;
    preserving curvature before entering this transaction is therefore not
    sufficient on its own.
    """
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        latest, _stored_updated_at = _read_contours_for_update(conn, series_id, module)
        final_payload = _preserve_curvature_landmarks(latest, deepcopy(payload))
        _write_contours_in_transaction(
            conn,
            series_id,
            module,
            final_payload,
            exists=latest is not None,
        )
    return final_payload


def _preserve_axis_exclusions(existing: dict | None, payload: dict) -> dict:
    if not existing:
        return payload
    existing_settings = existing.get("settings", {}) if isinstance(existing, dict) else {}
    payload_settings = payload.setdefault("settings", {})
    if not isinstance(existing_settings, dict) or not isinstance(payload_settings, dict):
        return payload
    for key in ("excluded_slices", "excluded_phases"):
        if key not in payload_settings and isinstance(existing_settings.get(key), list):
            payload_settings[key] = existing_settings[key]
    return payload


def _preserve_fat_threshold_settings(existing: dict | None, payload: dict) -> dict:
    if not isinstance(existing, dict) or not isinstance(payload, dict):
        return payload
    existing_settings = existing.get("settings")
    payload_settings = payload.setdefault("settings", {})
    if not isinstance(existing_settings, dict) or not isinstance(payload_settings, dict):
        return payload
    for key in ("fat_threshold", "left_atrial_function"):
        if key not in payload_settings and isinstance(existing_settings.get(key), dict):
            payload_settings[key] = existing_settings[key]
    return payload


def _preserve_curvature_landmarks(
    existing: dict | None,
    payload: dict,
) -> dict:
    """Keep manual four-point input writable only through the dedicated endpoint."""
    if not isinstance(payload, dict):
        return payload
    payload = dict(payload)
    if isinstance(existing, dict) and "curvature_landmarks" in existing:
        payload["curvature_landmarks"] = deepcopy(existing.get("curvature_landmarks"))
    else:
        payload.pop("curvature_landmarks", None)
    return payload


_ALLOW_EMPTY_FRAMES_OVERWRITE_FLAG = "allow_empty_frames_overwrite"


def _allows_empty_frames_overwrite(incoming: dict) -> bool:
    settings = incoming.get("settings") if isinstance(incoming, dict) else None
    return isinstance(settings, dict) and settings.get(_ALLOW_EMPTY_FRAMES_OVERWRITE_FLAG) is True


def _strip_transient_save_flags(payload: dict) -> dict:
    settings = payload.get("settings") if isinstance(payload, dict) else None
    if not isinstance(settings, dict) or _ALLOW_EMPTY_FRAMES_OVERWRITE_FLAG not in settings:
        return payload
    cleaned = dict(payload)
    cleaned_settings = dict(settings)
    cleaned_settings.pop(_ALLOW_EMPTY_FRAMES_OVERWRITE_FLAG, None)
    cleaned["settings"] = cleaned_settings
    return cleaned


def _is_empty_frames_overwrite(existing: dict | None, incoming: dict, action_origin: str | None) -> bool:
    if action_origin not in {None, "manual"}:
        return False
    if _allows_empty_frames_overwrite(incoming):
        return False
    existing_frames = existing.get("frames") if isinstance(existing, dict) else None
    incoming_frames = incoming.get("frames") if isinstance(incoming, dict) else None
    return bool(existing_frames) and isinstance(incoming_frames, dict) and not incoming_frames


def _preserve_existing_frames_for_empty_manual_save(existing: dict | None, incoming: dict, action_origin: str | None) -> dict:
    if not _is_empty_frames_overwrite(existing, incoming, action_origin):
        return incoming
    preserved = dict(incoming)
    preserved["frames"] = dict(existing.get("frames") or {})
    if existing.get("frame_meta") and not preserved.get("frame_meta"):
        preserved["frame_meta"] = dict(existing.get("frame_meta") or {})
    return preserved


def _contour_frame_summary(payload: dict) -> tuple[int, int]:
    frames = payload.get("frames") if isinstance(payload, dict) else None
    if not isinstance(frames, dict):
        return 0, 0
    point_total = 0
    for frame_payload in frames.values():
        if not isinstance(frame_payload, dict):
            continue
        for contour_payload in frame_payload.values():
            if isinstance(contour_payload, list):
                for item in contour_payload:
                    if isinstance(item, dict) and isinstance(item.get("points"), list):
                        point_total += len(item["points"])
                continue
            if isinstance(contour_payload, dict) and isinstance(contour_payload.get("points"), list):
                point_total += len(contour_payload["points"])
    return len(frames), point_total


def create_job(series_id: int, module: str, adapter: str, actor: dict | None = None) -> int:
    series = get_series_row(series_id)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO jobs (job_type, study_id, series_id, module, status, adapter, request_json, result_json, error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "inference",
                series["study_id"],
                series_id,
                module,
                "queued",
                adapter,
                dumps({"series_id": series_id, "module": module, "actor": actor or {}}),
                None,
                None,
                utcnow(),
                utcnow(),
            ),
        )
        return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def _update_job_progress(job_id: int, current: int, total: int, message: str | None = None) -> None:
    current = max(0, int(current))
    total = max(0, int(total))
    with get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET progress_current = ?, progress_total = ?, message = ?, updated_at = ? WHERE id = ?",
            (current, total, message, utcnow(), job_id),
        )


def _job_should_pause(job_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return row is None or row["status"] in {"pausing", "paused"}


def pause_job(job_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        if row["status"] in {"queued", "running"}:
            conn.execute(
                "UPDATE jobs SET status = ?, message = ?, updated_at = ? WHERE id = ?",
                ("pausing", "正在停止后台任务...", utcnow(), job_id),
            )
        elif row["status"] == "pausing":
            pass
        else:
            conn.execute(
                "UPDATE jobs SET message = ?, updated_at = ? WHERE id = ?",
                ("任务已经结束，无法暂停。", utcnow(), job_id),
            )
    return fetch_job(job_id)


def run_job(job_id: int) -> None:
    with get_conn() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if job is None:
            raise KeyError(job_id)
        if job["status"] in {"pausing", "paused"}:
            conn.execute(
                "UPDATE jobs SET status = ?, message = ?, updated_at = ? WHERE id = ?",
                ("paused", "任务已暂停，未启动模型。", utcnow(), job_id),
            )
            return
        conn.execute(
            "UPDATE jobs SET status = ?, progress_current = ?, progress_total = ?, message = ?, updated_at = ? WHERE id = ?",
            ("running", 0, 0, "任务已启动", utcnow(), job_id),
        )

    job_dict = {key: job[key] for key in job.keys()}
    request_payload = loads(job_dict.get("request_json"), {}) or {}
    actor = request_payload.get("actor") if isinstance(request_payload, dict) else None
    context = SeriesContext(series=get_series_row(job_dict["series_id"]), frames=list_frame_rows(job_dict["series_id"]))
    adapters: dict[str, InferenceAdapter] = {
        "model": ModelAdapter(),
        "fast": FastHeuristicAdapter(),
        "propagate": PropagationAdapter(),
    }

    try:
        adapter = adapters[job_dict["adapter"]]
        payload = adapter.run(
            context,
            job_dict["module"],
            progress=lambda current, total, message=None: _update_job_progress(job_id, current, total, message),
            should_pause=lambda: _job_should_pause(job_id),
        )
        existing_contours = fetch_contours(job_dict["series_id"], job_dict["module"])
        payload = _preserve_axis_exclusions(existing_contours, payload)
        payload = _preserve_fat_threshold_settings(existing_contours, payload)
        payload = _preserve_exclude_regions_for_legacy_save(existing_contours, payload)
        payload = _preserve_curvature_landmarks(existing_contours, payload)
        if _job_should_pause(job_id):
            raise JobPaused("任务已暂停。")
        payload = _merge_contour_metadata(
            existing_contours,
            payload,
            series_id=job_dict["series_id"],
            module=job_dict["module"],
            actor=actor,
            action_origin=job_dict["adapter"],
        )
        _validate_contours_for_save(payload)
        stored_payload = _upsert_contours(job_dict["series_id"], job_dict["module"], payload)
        if isinstance(stored_payload, dict):
            payload = stored_payload
        recompute_measurements_for_module(job_dict["series_id"], job_dict["module"])
        with get_conn() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, result_json = ?, progress_current = ?, progress_total = ?, message = ?, updated_at = ? WHERE id = ?",
                ("completed", dumps(payload), 1, 1, "完成", utcnow(), job_id),
            )
    except JobPaused as exc:
        with get_conn() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, error = ?, message = ?, updated_at = ? WHERE id = ?",
                ("paused", None, str(exc) or "任务已暂停，未写入本次自动结果。", utcnow(), job_id),
            )
    except Exception as exc:  # pragma: no cover
        with get_conn() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, error = ?, message = ?, updated_at = ? WHERE id = ?",
                ("failed", str(exc), str(exc), utcnow(), job_id),
            )


def fetch_job(job_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return {
            "id": row["id"],
            "status": row["status"],
            "module": row["module"],
            "adapter": row["adapter"],
            "progress": 1.0 if row["status"] == "completed" else (
                min(0.99, max(0.0, float(row["progress_current"] or 0) / float(row["progress_total"] or 1)))
                if row["progress_total"]
                else 0.0
            ),
            "progress_current": row["progress_current"] or 0,
            "progress_total": row["progress_total"] or 0,
            "message": row["message"],
            "result": loads(row["result_json"], None),
            "error": row["error"],
        }


def fetch_contours(series_id: int, module: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT payload_json, updated_at FROM contours WHERE series_id = ? AND module = ?",
            (series_id, module),
        ).fetchone()
        if row is None:
            return None
        return _normalize_contour_payload(
            loads(row["payload_json"], {}),
            series_id=series_id,
            module=module,
            stored_updated_at=row["updated_at"],
            actor=None,
        )


def _frame_has_annotation(frame_payload: dict | None) -> bool:
    if not isinstance(frame_payload, dict):
        return False
    if any(_contour_has_points(frame_payload.get(key)) for key in CONTOUR_VALIDATION_KEYS):
        return True
    return bool(_exclude_regions_from_frame(frame_payload))


def _annotation_module_key(role: str, module: str) -> str:
    if module == "function" and role == "cine_lax_4ch":
        return "function_4ch"
    if module == "function" and role == "cine_lax_2ch":
        return "function_2ch"
    if module == "function" and role == "cine_lax_3ch":
        return "function_3ch"
    if module == "function":
        return "function_sax"
    return module


def _summarize_study_annotation_rows(rows: list, study_ids: list[int]) -> dict[str, dict]:
    summaries = {
        str(study_id): {
            "is_annotated": False,
            "completed_modules": [],
            "completed_count": 0,
            "annotated_series_count": 0,
            "annotated_frame_count": 0,
            "latest_annotation_at": None,
        }
        for study_id in study_ids
    }
    annotated_series: dict[str, set[int]] = {str(study_id): set() for study_id in study_ids}
    completed_modules: dict[str, set[str]] = {str(study_id): set() for study_id in study_ids}

    for row in rows:
        study_key = str(int(row["study_id"]))
        summary = summaries.setdefault(
            study_key,
            {
                "is_annotated": False,
                "completed_modules": [],
                "completed_count": 0,
                "annotated_series_count": 0,
                "annotated_frame_count": 0,
                "latest_annotation_at": None,
            },
        )
        payload = loads(row["payload_json"], {})
        frames = payload.get("frames") if isinstance(payload, dict) else None
        if not isinstance(frames, dict):
            continue
        annotated_frames = sum(1 for frame_payload in frames.values() if _frame_has_annotation(frame_payload))
        if annotated_frames <= 0:
            continue
        summary["annotated_frame_count"] += annotated_frames
        annotated_series.setdefault(study_key, set()).add(int(row["series_id"]))
        completed_modules.setdefault(study_key, set()).add(
            _annotation_module_key(str(row["role"] or "unknown"), str(row["module"] or ""))
        )
        updated_at = row["updated_at"]
        if updated_at and (not summary["latest_annotation_at"] or updated_at > summary["latest_annotation_at"]):
            summary["latest_annotation_at"] = updated_at

    for study_key, summary in summaries.items():
        modules = sorted(completed_modules.get(study_key, set()))
        summary["completed_modules"] = modules
        summary["completed_count"] = len(modules)
        summary["annotated_series_count"] = len(annotated_series.get(study_key, set()))
        summary["is_annotated"] = summary["annotated_frame_count"] > 0
    return summaries


def fetch_study_annotation_summaries(study_ids: list[int]) -> dict[str, dict]:
    normalized_ids = sorted({int(study_id) for study_id in study_ids if int(study_id) > 0})
    if not normalized_ids:
        return {}
    placeholders = ",".join("?" for _ in normalized_ids)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT s.study_id, s.id AS series_id, s.role, c.module, c.payload_json, c.updated_at
            FROM contours c
            JOIN series s ON s.id = c.series_id
            WHERE s.study_id IN ({placeholders})
            """,
            normalized_ids,
        ).fetchall()
    return _summarize_study_annotation_rows(rows, normalized_ids)

def save_contours(
    series_id: int,
    module: str,
    payload: dict,
    *,
    actor: dict | None = None,
    action_origin: str | None = "manual",
    source_frame_key: str | None = None,
    recompute: bool = True,
) -> dict:
    if module != "function" and isinstance(payload, dict) and payload.get("curvature_landmarks") is not None:
        raise ValueError("室间隔/游离壁曲率四点只能保存到 function 模块。")
    existing = fetch_contours(series_id, module)
    frame_count, point_total = _contour_frame_summary(payload)
    logger.warning(
        "Saving contours series_id=%s module=%s action_origin=%s frames=%s points=%s",
        series_id,
        module,
        action_origin,
        frame_count,
        point_total,
    )
    if _is_empty_frames_overwrite(existing, payload, action_origin):
        logger.warning(
            "Preserving existing frames for empty manual contour save series_id=%s module=%s",
            series_id,
            module,
        )
        payload = _preserve_existing_frames_for_empty_manual_save(existing, payload, action_origin)
    payload = _preserve_curvature_landmarks(existing, payload)
    payload = _preserve_fat_threshold_settings(existing, payload)
    payload = _strip_transient_save_flags(payload)
    payload = _preserve_exclude_regions_for_legacy_save(existing, payload)
    _validate_contours_for_save(payload)
    payload = _prepare_phase_labels_for_save(existing, payload)
    merged = _merge_contour_metadata(
        existing,
        payload,
        series_id=series_id,
        module=module,
        actor=actor,
        action_origin=action_origin,
        source_frame_key=source_frame_key,
    )
    stored_payload = _upsert_contours(series_id, module, merged)
    if isinstance(stored_payload, dict):
        merged = stored_payload
    if recompute:
        recompute_measurements_for_module(series_id, module)
    return merged


def _save_curvature_landmarks_atomic(
    series_id: int,
    landmarks: dict | None,
    *,
    actor: dict | None = None,
) -> dict:
    """Replace only curvature landmarks while holding the SQLite write lock."""
    module = "function"
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        latest, stored_updated_at = _read_contours_for_update(conn, series_id, module)
        payload = deepcopy(latest) if isinstance(latest, dict) else {
            "series_id": series_id,
            "module": module,
            "coordinate_space": "pixel",
            "source": "manual",
            "settings": {},
            "annotation_meta": {},
            "frame_meta": {},
            "phase_labels": {},
            "frames": {},
        }
        payload["curvature_landmarks"] = deepcopy(landmarks)
        merged = _merge_contour_metadata(
            latest,
            payload,
            series_id=series_id,
            module=module,
            stored_updated_at=stored_updated_at,
            actor=actor,
            action_origin="manual",
        )
        _write_contours_in_transaction(
            conn,
            series_id,
            module,
            merged,
            exists=latest is not None,
        )
    return merged


def save_curvature_landmarks(
    series_id: int,
    landmarks: dict | None,
    *,
    actor: dict | None = None,
    recompute: bool = True,
) -> dict:
    """Update only the manual function curvature landmarks for a SAX cine series."""
    series = get_series_row(series_id)
    if str(series.get("role") or "unknown") != "cine_sax":
        raise ValueError("室间隔/游离壁曲率四点只能保存到 cine_sax 序列。")

    result = _save_curvature_landmarks_atomic(
        series_id,
        landmarks,
        actor=actor,
    )
    if recompute:
        recompute_measurements_for_module(series_id, "function")
    return result
