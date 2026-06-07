from __future__ import annotations

import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import numpy as np
from PIL import Image
from skimage.draw import ellipse, polygon2mask
from skimage.exposure import equalize_adapthist, rescale_intensity
from skimage.measure import find_contours
from skimage.morphology import binary_closing, binary_opening, disk, remove_small_objects
from skimage.registration import optical_flow_tvl1, phase_cross_correlation
from skimage.transform import AffineTransform, warp

from ..config import (
    EDGETAM_CHECKPOINT_PATH,
    EDGETAM_CONFIG_PATH,
    EDGETAM_HELPER_SCRIPT,
    MODEL_GPU_ID,
    MODEL_GPU_IDS,
    MODEL_PYTHON_PATH,
    MODEL_RUN_DIR,
    MODEL_TIMEOUT_SECONDS,
    build_edgetam_env,
)
from ..db import loads
from .job_control import JobPaused, ProgressCallback, ShouldPauseCallback
from .dicom_indexer import read_frame_pixels


class PropagationError(RuntimeError):
    pass


FUNCTION_PROPAGATION_KEYS = ("endo", "epi", "rv", "fat", "la", "ra")
LGE_PROPAGATION_KEYS = ("endo", "epi", "remote", "enhanced", "exclude", "mvo")
FUNCTION_OBJECT_MAP = {1: "endo", 2: "epi", 3: "rv", 4: "fat", 5: "la", 6: "ra"}
LGE_OBJECT_MAP = {1: "endo", 2: "epi", 3: "remote", 4: "enhanced", 5: "exclude", 6: "mvo"}

PROPAGATION_METHODS = {"optical_flow", "phase_correlation", "hybrid", "rigid", "affine"}
DEFAULT_PROPAGATION_SETTINGS = {
    "method": "hybrid",
    "contrast_boost": True,
    "flow_attachment": 10.0,
    "flow_tightness": 0.25,
    "smooth_radius": 1,
    "min_area": 24,
    "shape_prior": False,
    "prior_strength": 0.45,
}


def _frame_key(slice_index: int, phase_index: int) -> str:
    return f"{slice_index}:{phase_index}"


def _pixel_to_patient(frame: dict, x: float, y: float) -> list[float]:
    metadata = loads(frame.get("metadata_json"), {})
    image_position = loads(frame.get("image_position_json"), [0.0, 0.0, 0.0])
    orientation = metadata.get("image_orientation", [1.0, 0.0, 0.0, 0.0, 1.0, 0.0])
    pixel_spacing = metadata.get("pixel_spacing", [1.0, 1.0])
    row_dir = np.array(orientation[:3], dtype=float)
    col_dir = np.array(orientation[3:6], dtype=float)
    origin = np.array(image_position, dtype=float)
    point = origin + col_dir * float(pixel_spacing[0]) * x + row_dir * float(pixel_spacing[1]) * y
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


def _mask_to_polygon(mask: np.ndarray | None, frame: dict) -> dict | None:
    if mask is None or int(mask.sum()) < 24:
        return None
    contours = find_contours(mask.astype(float), 0.5)
    if not contours:
        return None
    contour = _sample_contour_points(max(contours, key=len))
    points = []
    for y, x in contour:
        sx = round(float(x), 2)
        sy = round(float(y), 2)
        points.append({"x": sx, "y": sy, "patient": _pixel_to_patient(frame, sx, sy)})
    if len(points) < 3:
        return None
    return {"points": points, "closed": True}


def _contour_to_mask(contour: dict | None, shape: tuple[int, int]) -> np.ndarray | None:
    if not contour:
        return None
    points = contour.get("points") or []
    if len(points) < 3:
        return None
    polygon = np.array([[float(point["y"]), float(point["x"])] for point in points], dtype=float)
    mask = polygon2mask(shape, polygon)
    mask = binary_closing(mask, disk(1))
    mask = binary_opening(mask, disk(1))
    mask = remove_small_objects(mask.astype(bool), 16)
    return mask.astype(bool)


def _frame_shape(frame: dict) -> tuple[int, int]:
    metadata = loads(frame.get("metadata_json"), {})
    rows = int(metadata.get("rows") or 0)
    cols = int(metadata.get("cols") or 0)
    if rows <= 0 or cols <= 0:
        pixels = read_frame_pixels(frame)
        rows, cols = pixels.shape[:2]
    return rows, cols


def _module_keys(module: str) -> tuple[str, ...]:
    return FUNCTION_PROPAGATION_KEYS if module == "function" else LGE_PROPAGATION_KEYS


def _module_object_map(module: str) -> dict[int, str]:
    return FUNCTION_OBJECT_MAP if module == "function" else LGE_OBJECT_MAP


def _contour_has_points(contour: dict | None) -> bool:
    if not isinstance(contour, dict):
        return False
    points = contour.get("points")
    return isinstance(points, list) and len(points) >= 3


def _frame_has_any_contours(frame_payload: dict | None, module: str) -> bool:
    if not frame_payload:
        return False
    return any(_contour_has_points(frame_payload.get(key)) for key in _module_keys(module))


def _frame_to_masks(frame_payload: dict | None, frame: dict, module: str) -> dict[str, np.ndarray]:
    if not frame_payload:
        return {}
    shape = _frame_shape(frame)
    masks: dict[str, np.ndarray] = {}
    for key in _module_keys(module):
        mask = _contour_to_mask(frame_payload.get(key), shape)
        if mask is not None and int(mask.sum()) > 0:
            masks[key] = mask
    if "endo" in masks and "epi" in masks:
        masks["epi"] = masks["epi"] | masks["endo"]
    return masks


def _sanitize_mask(mask: np.ndarray, *, smooth_radius: int = 1, min_area: int = 24) -> np.ndarray | None:
    cleaned = mask.astype(bool)
    radius = max(0, int(smooth_radius))
    if radius > 0:
        kernel = disk(radius)
        cleaned = binary_closing(cleaned, kernel)
        cleaned = binary_opening(cleaned, kernel)
    cleaned = remove_small_objects(cleaned, max(1, int(min_area)))
    if int(cleaned.sum()) <= 0:
        return None
    return cleaned.astype(bool)


def _normalize_propagation_image(image: np.ndarray, *, contrast_boost: bool) -> np.ndarray:
    normalized = image.astype(np.float32) / 255.0
    low, high = np.percentile(normalized, [2, 98])
    if np.isfinite(low) and np.isfinite(high) and high > low:
        normalized = rescale_intensity(normalized, in_range=(low, high))
    if contrast_boost:
        normalized = equalize_adapthist(normalized, clip_limit=0.018)
    return normalized.astype(np.float32)


def _shift_image(image: np.ndarray, row_shift: float, col_shift: float, *, order: int) -> np.ndarray:
    transform = AffineTransform(translation=(float(col_shift), float(row_shift)))
    shifted = warp(
        image,
        inverse_map=transform.inverse,
        order=order,
        preserve_range=True,
        mode="edge",
    )
    return shifted.astype(image.dtype, copy=False)


def _shift_masks(
    source_masks: dict[str, np.ndarray],
    row_shift: float,
    col_shift: float,
    *,
    smooth_radius: int,
    min_area: int,
) -> dict[str, np.ndarray]:
    shifted: dict[str, np.ndarray] = {}
    for key, mask in source_masks.items():
        warped = _shift_image(mask.astype(np.float32), row_shift, col_shift, order=0)
        cleaned = _sanitize_mask(warped >= 0.5, smooth_radius=smooth_radius, min_area=min_area)
        if cleaned is not None:
            shifted[key] = cleaned
    return shifted


def _largest_region_mask(mask: np.ndarray) -> np.ndarray | None:
    labeled = label(mask.astype(bool))
    regions = regionprops(labeled)
    if not regions:
        return None
    region = max(regions, key=lambda item: item.area)
    return labeled == region.label


def _target_central_region(image: np.ndarray, source_mask: np.ndarray | None = None) -> np.ndarray | None:
    normalized = image.astype(np.float32) / 255.0
    height, width = normalized.shape
    crop = normalized[height // 5 : height * 4 // 5, width // 5 : width * 4 // 5]
    if crop.size == 0:
        return None
    threshold = max(float(np.quantile(crop, 0.72)), float(np.mean(crop) + np.std(crop) * 0.25))
    mask = normalized >= threshold
    mask = binary_opening(mask, disk(2))
    mask = binary_closing(mask, disk(3))
    mask = remove_small_objects(mask.astype(bool), 64)
    labeled = label(mask)
    regions = regionprops(labeled)
    if not regions:
        return None
    if source_mask is not None and int(source_mask.sum()) > 0:
        source_region = regionprops(label(source_mask.astype(bool)))
        source_centroid = np.array(source_region[0].centroid) if source_region else np.array([height / 2.0, width / 2.0])
    else:
        source_centroid = np.array([height / 2.0, width / 2.0])
    chosen = min(
        regions,
        key=lambda region: (
            np.linalg.norm(np.array(region.centroid) - source_centroid),
            -region.area,
        ),
    )
    return labeled == chosen.label


def _union_source_mask(source_masks: dict[str, np.ndarray]) -> np.ndarray | None:
    if not source_masks:
        return None
    union_mask = None
    for key in ("epi", "endo", "la", "ra", "rv", "fat", "remote", "enhanced", "exclude", "mvo"):
        mask = source_masks.get(key)
        if mask is None or int(mask.sum()) <= 0:
            continue
        union_mask = mask.astype(bool) if union_mask is None else (union_mask | mask.astype(bool))
    if union_mask is None or int(union_mask.sum()) <= 0:
        return None
    return _largest_region_mask(union_mask)


def _estimate_geometric_transform(
    source_masks: dict[str, np.ndarray],
    target_image: np.ndarray,
    *,
    allow_scale: bool,
) -> AffineTransform | None:
    source_union = _union_source_mask(source_masks)
    if source_union is None:
        return None
    target_union = _target_central_region(target_image, source_union)
    if target_union is None:
        return None
    source_regions = regionprops(label(source_union.astype(bool)))
    target_regions = regionprops(label(target_union.astype(bool)))
    if not source_regions or not target_regions:
        return None
    source_region = source_regions[0]
    target_region = target_regions[0]
    source_center = np.array([float(source_region.centroid[1]), float(source_region.centroid[0])], dtype=np.float32)
    target_center = np.array([float(target_region.centroid[1]), float(target_region.centroid[0])], dtype=np.float32)
    rotation = float(target_region.orientation - source_region.orientation)
    if allow_scale:
        source_major = max(float(source_region.major_axis_length), 1.0)
        source_minor = max(float(source_region.minor_axis_length), 1.0)
        target_major = max(float(target_region.major_axis_length), 1.0)
        target_minor = max(float(target_region.minor_axis_length), 1.0)
        scale_x = float(np.clip(target_major / source_major, 0.7, 1.35))
        scale_y = float(np.clip(target_minor / source_minor, 0.7, 1.35))
        scale = (scale_x, scale_y)
    else:
        scale = (1.0, 1.0)
    transform = AffineTransform(scale=scale, rotation=rotation, translation=(0.0, 0.0))
    matrix = transform.params.copy()
    source_h = np.array([source_center[0], source_center[1], 1.0], dtype=np.float32)
    transformed_source = matrix @ source_h
    matrix[0, 2] = float(target_center[0] - transformed_source[0])
    matrix[1, 2] = float(target_center[1] - transformed_source[1])
    return AffineTransform(matrix=matrix)


def _warp_masks_with_transform(
    source_masks: dict[str, np.ndarray],
    transform: AffineTransform,
    *,
    smooth_radius: int,
    min_area: int,
) -> dict[str, np.ndarray]:
    warped_masks: dict[str, np.ndarray] = {}
    for key, mask in source_masks.items():
        warped = warp(
            mask.astype(np.float32),
            inverse_map=transform.inverse,
            order=0,
            preserve_range=True,
            mode="edge",
        )
        cleaned = _sanitize_mask(warped >= 0.5, smooth_radius=smooth_radius, min_area=min_area)
        if cleaned is not None:
            warped_masks[key] = cleaned
    if "endo" in warped_masks and "epi" in warped_masks:
        warped_masks["epi"] = warped_masks["epi"] | warped_masks["endo"]
    return warped_masks


def _ellipse_regularized_mask(mask: np.ndarray, *, strength: float) -> np.ndarray:
    if int(mask.sum()) <= 0:
        return mask
    regions = regionprops(label(mask.astype(bool)))
    if not regions:
        return mask
    region = max(regions, key=lambda item: item.area)
    rr, cc = ellipse(
        float(region.centroid[0]),
        float(region.centroid[1]),
        max(float(region.minor_axis_length) * 0.5, 1.0),
        max(float(region.major_axis_length) * 0.5, 1.0),
        shape=mask.shape,
        rotation=float(-region.orientation),
    )
    ellipse_mask = np.zeros(mask.shape, dtype=bool)
    ellipse_mask[rr, cc] = True
    if strength >= 0.75:
        return ellipse_mask
    if strength >= 0.45:
        return ellipse_mask | mask
    return mask | binary_closing(ellipse_mask & binary_closing(mask, disk(1)), disk(1))


def _apply_shape_prior(
    masks: dict[str, np.ndarray],
    *,
    strength: float,
    smooth_radius: int,
    min_area: int,
) -> dict[str, np.ndarray]:
    if not masks:
        return {}
    constrained: dict[str, np.ndarray] = {}
    ellipse_keys = {"endo", "epi", "la", "ra", "fat"}
    for key, mask in masks.items():
        next_mask = mask.astype(bool)
        if key in ellipse_keys:
            next_mask = _ellipse_regularized_mask(next_mask, strength=strength)
        cleaned = _sanitize_mask(next_mask, smooth_radius=smooth_radius, min_area=min_area)
        if cleaned is not None:
            constrained[key] = cleaned
    if "endo" in constrained:
        dilation_radius = max(1, int(round(1 + strength * 3)))
        constrained["endo"] = binary_closing(constrained["endo"], disk(dilation_radius))
        constrained["endo"] = remove_small_objects(constrained["endo"], max(8, min_area // 2))
    if "endo" in constrained and "epi" in constrained:
        constrained["epi"] = binary_closing(constrained["epi"] | constrained["endo"], disk(max(1, smooth_radius)))
        constrained["epi"] = remove_small_objects(constrained["epi"], min_area)
    if "rv" in constrained:
        constrained["rv"] = binary_closing(constrained["rv"], disk(max(1, smooth_radius)))
    return {key: value.astype(bool) for key, value in constrained.items() if int(value.sum()) > 0}


def _resolve_propagation_settings(
    contour_set: dict | None,
    overrides: dict | None = None,
) -> dict[str, float | int | bool | str]:
    resolved = dict(DEFAULT_PROPAGATION_SETTINGS)
    settings = (contour_set or {}).get("settings") or {}
    propagation_settings = settings.get("propagation") or {}
    if isinstance(propagation_settings, dict):
        resolved.update(propagation_settings)
    if overrides:
        resolved.update({key: value for key, value in overrides.items() if value is not None})
    method = str(resolved.get("method") or DEFAULT_PROPAGATION_SETTINGS["method"]).strip().lower()
    resolved["method"] = method if method in PROPAGATION_METHODS else DEFAULT_PROPAGATION_SETTINGS["method"]
    resolved["contrast_boost"] = bool(resolved.get("contrast_boost", DEFAULT_PROPAGATION_SETTINGS["contrast_boost"]))
    resolved["flow_attachment"] = float(np.clip(float(resolved.get("flow_attachment", 10.0)), 1.0, 30.0))
    resolved["flow_tightness"] = float(np.clip(float(resolved.get("flow_tightness", 0.25)), 0.02, 1.0))
    resolved["smooth_radius"] = int(np.clip(int(resolved.get("smooth_radius", 1)), 0, 5))
    resolved["min_area"] = int(np.clip(int(resolved.get("min_area", 24)), 4, 2048))
    resolved["shape_prior"] = bool(resolved.get("shape_prior", DEFAULT_PROPAGATION_SETTINGS["shape_prior"]))
    resolved["prior_strength"] = float(np.clip(float(resolved.get("prior_strength", 0.45)), 0.0, 1.0))
    return resolved


def _propagate_masks_between_frames(
    source_masks: dict[str, np.ndarray],
    source_image: np.ndarray,
    target_image: np.ndarray,
    *,
    settings: dict[str, float | int | bool | str] | None = None,
) -> dict[str, np.ndarray]:
    if not source_masks:
        return {}
    propagation_settings = dict(DEFAULT_PROPAGATION_SETTINGS)
    if settings:
        propagation_settings.update(settings)
    method = str(propagation_settings["method"])
    smooth_radius = int(propagation_settings["smooth_radius"])
    min_area = int(propagation_settings["min_area"])
    contrast_boost = bool(propagation_settings["contrast_boost"])
    shape_prior = bool(propagation_settings.get("shape_prior"))
    prior_strength = float(propagation_settings.get("prior_strength", 0.45))
    reference = _normalize_propagation_image(target_image, contrast_boost=contrast_boost)
    moving = _normalize_propagation_image(source_image, contrast_boost=contrast_boost)
    propagated_masks = source_masks

    if method in {"rigid", "affine"}:
        transform = _estimate_geometric_transform(
            source_masks,
            target_image,
            allow_scale=method == "affine",
        )
        if transform is not None:
            propagated_masks = _warp_masks_with_transform(
                source_masks,
                transform,
                smooth_radius=smooth_radius,
                min_area=min_area,
            )
        if shape_prior:
            propagated_masks = _apply_shape_prior(
                propagated_masks,
                strength=prior_strength,
                smooth_radius=smooth_radius,
                min_area=min_area,
            )
        return propagated_masks

    if method in {"phase_correlation", "hybrid"}:
        try:
            shift, _, _ = phase_cross_correlation(reference, moving, upsample_factor=10)
        except Exception:
            shift = np.array([0.0, 0.0], dtype=np.float32)
        row_shift = float(shift[0]) if np.isfinite(shift[0]) else 0.0
        col_shift = float(shift[1]) if np.isfinite(shift[1]) else 0.0
        if abs(row_shift) > 0.01 or abs(col_shift) > 0.01:
            shifted = _shift_masks(
                source_masks,
                row_shift,
                col_shift,
                smooth_radius=smooth_radius,
                min_area=min_area,
            )
            if shifted:
                propagated_masks = shifted
                moving = _shift_image(moving, row_shift, col_shift, order=1)
        if method == "phase_correlation":
            if "endo" in propagated_masks and "epi" in propagated_masks:
                propagated_masks["epi"] = propagated_masks["epi"] | propagated_masks["endo"]
            if shape_prior:
                propagated_masks = _apply_shape_prior(
                    propagated_masks,
                    strength=prior_strength,
                    smooth_radius=smooth_radius,
                    min_area=min_area,
                )
            return propagated_masks

    flow = optical_flow_tvl1(
        reference,
        moving,
        attachment=float(propagation_settings["flow_attachment"]),
        tightness=float(propagation_settings["flow_tightness"]),
    )
    row_coords, col_coords = np.meshgrid(
        np.arange(reference.shape[0], dtype=np.float32),
        np.arange(reference.shape[1], dtype=np.float32),
        indexing="ij",
    )
    sample_coords = np.array([row_coords + flow[0], col_coords + flow[1]])
    propagated: dict[str, np.ndarray] = {}
    for key, mask in propagated_masks.items():
        warped = warp(
            mask.astype(np.float32),
            sample_coords,
            order=0,
            preserve_range=True,
            mode="edge",
        )
        cleaned = _sanitize_mask(warped >= 0.5, smooth_radius=smooth_radius, min_area=min_area)
        if cleaned is not None:
            propagated[key] = cleaned
    if "endo" in propagated and "epi" in propagated:
        propagated["epi"] = propagated["epi"] | propagated["endo"]
    if shape_prior:
        propagated = _apply_shape_prior(
            propagated,
            strength=prior_strength,
            smooth_radius=smooth_radius,
            min_area=min_area,
        )
    return propagated


def _merge_frame_payload(existing: dict | None, propagated_masks: dict[str, np.ndarray], frame: dict, module: str) -> dict | None:
    next_payload = deepcopy(existing) if existing else {"include": True}
    changed = False
    for key in _module_keys(module):
        if key in propagated_masks:
            polygon = _mask_to_polygon(propagated_masks[key], frame)
            if polygon is not None:
                next_payload[key] = polygon
                changed = True
        else:
            next_payload.setdefault(key, None)
    next_payload.setdefault("include", True)
    return next_payload if changed or _frame_has_any_contours(next_payload, module) else None


def _ordered_phase_indices(frames: list[dict], slice_index: int) -> list[int]:
    return sorted({int(frame["phase_index"]) for frame in frames if int(frame["slice_index"]) == slice_index})


def _ordered_slice_indices(frames: list[dict], phase_index: int) -> list[int]:
    return sorted({int(frame["slice_index"]) for frame in frames if int(frame["phase_index"]) == phase_index})


def _validate_inputs(module: str, contour_set: dict | None) -> None:
    if not contour_set or not contour_set.get("frames"):
        raise PropagationError("请先保存手工轮廓，再执行传播补全。")
    if module not in {"function", "lge"}:
        raise PropagationError(f"传播补全暂不支持模块: {module}")
    if module == "function" and not any(_frame_has_any_contours(payload, module) for payload in contour_set.get("frames", {}).values()):
        raise PropagationError("请先准备至少一帧有效轮廓，再执行传播补全。")


def _edgetam_available() -> bool:
    return MODEL_PYTHON_PATH.exists() and EDGETAM_HELPER_SCRIPT.exists() and EDGETAM_CONFIG_PATH.exists() and EDGETAM_CHECKPOINT_PATH.exists()


def _resolve_gpu_ids() -> list[str]:
    raw_values = [value.strip() for value in MODEL_GPU_IDS.split(",") if value.strip()]
    if raw_values:
        return raw_values
    return [MODEL_GPU_ID]


def _write_manifest(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_progress(progress_files: list[Path]) -> int:
    done = 0
    for progress_file in progress_files:
        if not progress_file.exists():
            continue
        try:
            payload = json.loads(progress_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        done += int(payload.get("done") or 0)
    return done


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=8)


def _save_frame_image(frame: dict, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(read_frame_pixels(frame)).save(destination)


def _save_mask(mask: np.ndarray, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((mask.astype(np.uint8) * 255)).save(destination)


def _run_edgetam_chunk(
    *,
    manifest_path: Path,
    progress_file: Path,
    gpu_id: str,
    should_pause: ShouldPauseCallback | None,
) -> list[dict]:
    gpu_raw = gpu_id.strip().lower()
    command = [
        str(MODEL_PYTHON_PATH),
        str(EDGETAM_HELPER_SCRIPT),
        "--manifest",
        str(manifest_path),
        "--config",
        str(EDGETAM_CONFIG_PATH),
        "--checkpoint",
        str(EDGETAM_CHECKPOINT_PATH),
    ]
    if gpu_raw:
        command.extend(["--gpu-id", gpu_id])
    command.extend(["--progress-file", str(progress_file)])
    stdout_path = progress_file.with_suffix(".stdout.log")
    stderr_path = progress_file.with_suffix(".stderr.log")
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open("w", encoding="utf-8") as stderr_file:
        process = subprocess.Popen(
            command,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            env=build_edgetam_env(),
        )
        start_time = time.monotonic()
        while process.poll() is None:
            if should_pause and should_pause():
                _terminate_process(process)
                raise JobPaused("传播补全已暂停，EdgeTAM 进程已停止。")
            if time.monotonic() - start_time > MODEL_TIMEOUT_SECONDS:
                _terminate_process(process)
                raise PropagationError("EdgeTAM 传播超时。")
            time.sleep(0.5)

    stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
    stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
    completed = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "EdgeTAM execution failed").strip()
        if "No module named 'sam2'" in message:
            message = "EdgeTAM 运行环境缺少 sam2 依赖，请检查第三方仓库和 Python 环境。"
        elif "No module named 'torch'" in message:
            message = "EdgeTAM 运行环境缺少 torch 依赖，请检查模型 Python 环境。"
        elif "No module named 'hydra'" in message or "No module named 'omegaconf'" in message:
            message = "EdgeTAM 运行环境缺少配置依赖，请检查 hydra/omegaconf 安装。"
        raise PropagationError(f"EdgeTAM 传播失败: {message}")
    stdout_lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not stdout_lines:
        raise PropagationError("EdgeTAM 没有返回有效结果。")
    try:
        payload = json.loads(stdout_lines[-1])
    except json.JSONDecodeError as exc:
        raise PropagationError(f"EdgeTAM 返回内容不可解析: {completed.stdout.strip() or exc}") from exc
    return list(payload.get("items", []))


def _run_edgetam(
    *,
    manifest_path: Path,
    progress: ProgressCallback | None,
    should_pause: ShouldPauseCallback | None,
) -> list[dict]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = list(manifest.get("items", []))
    if not items:
        return []

    gpu_ids = _resolve_gpu_ids()
    workers = max(1, min(len(gpu_ids), len(items)))
    chunks: list[list[dict]] = [[] for _ in range(workers)]
    for index, item in enumerate(items):
        chunks[index % workers].append(item)

    manifests: list[Path] = []
    progress_files: list[Path] = []
    for index, chunk in enumerate(chunks):
        chunk_manifest = manifest_path.parent / "manifests" / f"edgetam-chunk-{index:02d}.json"
        _write_manifest(chunk_manifest, chunk)
        manifests.append(chunk_manifest)
        progress_files.append(manifest_path.parent / "progress" / f"edgetam-chunk-{index:02d}.json")

    if progress:
        progress(0, len(items), f"EdgeTAM 并行启动 {workers} 个进程，GPU: {', '.join(gpu_ids[:workers])}")

    outputs: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(
                _run_edgetam_chunk,
                manifest_path=manifests[index],
                progress_file=progress_files[index],
                gpu_id=gpu_ids[index],
                should_pause=should_pause,
            ): index
            for index in range(workers)
        }
        while future_map:
            if should_pause and should_pause():
                for future in future_map:
                    future.cancel()
                raise JobPaused("传播补全已暂停。")
            done_count = _read_progress(progress_files)
            if progress:
                progress(done_count, len(items), f"EdgeTAM 传播中：已完成 {done_count}/{len(items)} 个切片")
            finished = [future for future in future_map if future.done()]
            for future in finished:
                outputs.extend(future.result())
                future_map.pop(future)
            if future_map:
                time.sleep(0.6)

    if progress:
        progress(len(items), len(items), "EdgeTAM 传播完成，正在合并轮廓")
    return sorted(outputs, key=lambda item: int(item.get("slice_index") or 0))


def _build_edgetam_manifest(
    *,
    run_dir: Path,
    frames: list[dict],
    frame_lookup: dict[tuple[int, int], dict],
    contour_set: dict,
    module: str,
) -> tuple[Path, set[str]]:
    items = []
    seeded_keys: set[str] = set()
    object_map = _module_object_map(module)
    slice_indices = sorted({int(frame["slice_index"]) for frame in frames})
    for slice_index in slice_indices:
        phase_indices = _ordered_phase_indices(frames, slice_index)
        if len(phase_indices) < 2:
            continue
        slice_dir = run_dir / f"slice-{slice_index:03d}"
        video_dir = slice_dir / "frames"
        output_dir = slice_dir / "outputs"
        seeds = []
        for ordered_phase_index, phase_index in enumerate(phase_indices):
            frame = frame_lookup.get((slice_index, phase_index))
            if frame is None:
                continue
            _save_frame_image(frame, video_dir / f"{ordered_phase_index:04d}.jpg")
            key = _frame_key(slice_index, phase_index)
            frame_payload = contour_set.get("frames", {}).get(key)
            if not _frame_has_any_contours(frame_payload, module):
                continue
            masks = _frame_to_masks(frame_payload, frame, module)
            if not masks:
                continue
            seeded_keys.add(key)
            for object_id, contour_key in object_map.items():
                mask = masks.get(contour_key)
                if mask is None:
                    continue
                mask_path = slice_dir / "seeds" / f"frame-{ordered_phase_index:04d}-obj-{object_id}.png"
                _save_mask(mask, mask_path)
                seeds.append(
                    {
                        "frame_index": ordered_phase_index,
                        "object_id": object_id,
                        "mask_path": str(mask_path),
                    }
                )
        if seeds:
            items.append(
                {
                    "slice_index": slice_index,
                    "phase_indices": phase_indices,
                    "video_dir": str(video_dir),
                    "output_dir": str(output_dir),
                    "seeds": seeds,
                }
            )
    manifest_path = run_dir / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path, seeded_keys


def _load_edgetam_outputs(
    *,
    outputs: list[dict],
    frame_lookup: dict[tuple[int, int], dict],
    result_frames: dict[str, dict],
    module: str,
    protected_keys: set[str],
) -> set[str]:
    generated_keys: set[str] = set()
    reverse_object_map = _module_object_map(module)
    for item in outputs:
        slice_index = int(item["slice_index"])
        phase_indices = [int(value) for value in item.get("phase_indices", [])]
        for output_path in item.get("outputs", []):
            path = Path(str(output_path))
            if not path.exists():
                continue
            frame_number = int(path.stem.split("-")[-1])
            if frame_number < 0 or frame_number >= len(phase_indices):
                continue
            phase_index = phase_indices[frame_number]
            frame = frame_lookup.get((slice_index, phase_index))
            if frame is None:
                continue
            frame_key = _frame_key(slice_index, phase_index)
            if frame_key in protected_keys:
                continue
            data = np.load(path)
            masks: dict[str, np.ndarray] = {}
            for object_id, contour_key in reverse_object_map.items():
                array_key = f"obj_{object_id}"
                if array_key not in data:
                    continue
                cleaned = _sanitize_mask(data[array_key] > 0)
                if cleaned is not None:
                    masks[contour_key] = cleaned
            if not masks:
                continue
            merged = _merge_frame_payload(result_frames.get(frame_key), masks, frame, module)
            if merged is not None:
                result_frames[frame_key] = merged
                generated_keys.add(frame_key)
    return generated_keys


def _apply_optical_flow_fill(
    *,
    frames: list[dict],
    frame_lookup: dict[tuple[int, int], dict],
    result_frames: dict[str, dict],
    module: str,
    propagation_settings: dict[str, float | int | bool | str],
    progress: ProgressCallback | None = None,
    should_pause: ShouldPauseCallback | None = None,
) -> None:
    pixel_cache: dict[int, np.ndarray] = {}

    def ensure_not_paused() -> None:
        if should_pause and should_pause():
            raise JobPaused("传播补全已暂停。")

    def get_pixels(frame: dict) -> np.ndarray:
        frame_id = int(frame["id"])
        if frame_id not in pixel_cache:
            pixel_cache[frame_id] = read_frame_pixels(frame)
        return pixel_cache[frame_id]

    def propagate_along_time() -> None:
        slice_indices = sorted({int(frame["slice_index"]) for frame in frames})
        for processed, slice_index in enumerate(slice_indices, start=1):
            ensure_not_paused()
            phase_indices = _ordered_phase_indices(frames, slice_index)
            if len(phase_indices) < 2:
                continue
            known_masks: dict[int, dict[str, np.ndarray]] = {}
            for phase_index in phase_indices:
                key = _frame_key(slice_index, phase_index)
                frame_payload = result_frames.get(key)
                if not _frame_has_any_contours(frame_payload, module):
                    continue
                frame = frame_lookup.get((slice_index, phase_index))
                if frame is None:
                    continue
                masks = _frame_to_masks(frame_payload, frame, module)
                if masks:
                    known_masks[phase_index] = masks
            if not known_masks:
                continue
            for index in range(1, len(phase_indices)):
                previous_phase = phase_indices[index - 1]
                current_phase = phase_indices[index]
                current_key = _frame_key(slice_index, current_phase)
                if current_key in result_frames and _frame_has_any_contours(result_frames.get(current_key), module):
                    continue
                if previous_phase not in known_masks:
                    continue
                source_frame = frame_lookup.get((slice_index, previous_phase))
                target_frame = frame_lookup.get((slice_index, current_phase))
                if source_frame is None or target_frame is None:
                    continue
                propagated = _propagate_masks_between_frames(
                    known_masks[previous_phase],
                    get_pixels(source_frame),
                    get_pixels(target_frame),
                    settings=propagation_settings,
                )
                if propagated:
                    known_masks[current_phase] = propagated
                    merged = _merge_frame_payload(result_frames.get(current_key), propagated, target_frame, module)
                    if merged is not None:
                        result_frames[current_key] = merged

            for index in range(len(phase_indices) - 2, -1, -1):
                current_phase = phase_indices[index]
                next_phase = phase_indices[index + 1]
                current_key = _frame_key(slice_index, current_phase)
                if current_key in result_frames and _frame_has_any_contours(result_frames.get(current_key), module):
                    continue
                if next_phase not in known_masks:
                    continue
                source_frame = frame_lookup.get((slice_index, next_phase))
                target_frame = frame_lookup.get((slice_index, current_phase))
                if source_frame is None or target_frame is None:
                    continue
                propagated = _propagate_masks_between_frames(
                    known_masks[next_phase],
                    get_pixels(source_frame),
                    get_pixels(target_frame),
                    settings=propagation_settings,
                )
                if propagated:
                    known_masks[current_phase] = propagated
                    merged = _merge_frame_payload(result_frames.get(current_key), propagated, target_frame, module)
                    if merged is not None:
                        result_frames[current_key] = merged
            if progress:
                progress(processed, max(len(slice_indices), 1), f"光流按时相补全：{processed}/{len(slice_indices)} 层")

    def propagate_along_slices() -> None:
        phase_indices = sorted({int(frame["phase_index"]) for frame in frames})
        for processed, phase_index in enumerate(phase_indices, start=1):
            ensure_not_paused()
            slice_indices = _ordered_slice_indices(frames, phase_index)
            if len(slice_indices) < 2:
                continue
            known_masks: dict[int, dict[str, np.ndarray]] = {}
            for slice_index in slice_indices:
                key = _frame_key(slice_index, phase_index)
                frame_payload = result_frames.get(key)
                if not _frame_has_any_contours(frame_payload, module):
                    continue
                frame = frame_lookup.get((slice_index, phase_index))
                if frame is None:
                    continue
                masks = _frame_to_masks(frame_payload, frame, module)
                if masks:
                    known_masks[slice_index] = masks
            if not known_masks:
                continue

            for index in range(1, len(slice_indices)):
                previous_slice = slice_indices[index - 1]
                current_slice = slice_indices[index]
                current_key = _frame_key(current_slice, phase_index)
                if current_key in result_frames and _frame_has_any_contours(result_frames.get(current_key), module):
                    continue
                if previous_slice not in known_masks:
                    continue
                source_frame = frame_lookup.get((previous_slice, phase_index))
                target_frame = frame_lookup.get((current_slice, phase_index))
                if source_frame is None or target_frame is None:
                    continue
                propagated = _propagate_masks_between_frames(
                    known_masks[previous_slice],
                    get_pixels(source_frame),
                    get_pixels(target_frame),
                    settings=propagation_settings,
                )
                if propagated:
                    known_masks[current_slice] = propagated
                    merged = _merge_frame_payload(result_frames.get(current_key), propagated, target_frame, module)
                    if merged is not None:
                        result_frames[current_key] = merged
            if progress:
                progress(processed, max(len(phase_indices), 1), f"光流按层面补全：{processed}/{len(phase_indices)} 相")

            for index in range(len(slice_indices) - 2, -1, -1):
                current_slice = slice_indices[index]
                next_slice = slice_indices[index + 1]
                current_key = _frame_key(current_slice, phase_index)
                if current_key in result_frames and _frame_has_any_contours(result_frames.get(current_key), module):
                    continue
                if next_slice not in known_masks:
                    continue
                source_frame = frame_lookup.get((next_slice, phase_index))
                target_frame = frame_lookup.get((current_slice, phase_index))
                if source_frame is None or target_frame is None:
                    continue
                propagated = _propagate_masks_between_frames(
                    known_masks[next_slice],
                    get_pixels(source_frame),
                    get_pixels(target_frame),
                    settings=propagation_settings,
                )
                if propagated:
                    known_masks[current_slice] = propagated
                    merged = _merge_frame_payload(result_frames.get(current_key), propagated, target_frame, module)
                    if merged is not None:
                        result_frames[current_key] = merged

    propagate_along_time()
    propagate_along_slices()
    propagate_along_time()


def run_propagation_inference(
    *,
    series: dict,
    frames: list[dict],
    module: str,
    contour_set: dict | None,
    progress: ProgressCallback | None = None,
    should_pause: ShouldPauseCallback | None = None,
) -> dict:
    _validate_inputs(module, contour_set)
    frame_lookup = {(int(frame["slice_index"]), int(frame["phase_index"])): frame for frame in frames}
    if not frame_lookup:
        raise PropagationError("当前序列没有可传播的帧。")
    if should_pause and should_pause():
        raise JobPaused("传播补全已暂停。")

    result_frames = deepcopy(contour_set.get("frames", {}))
    protected_keys = {key for key, payload in result_frames.items() if _frame_has_any_contours(payload, module)}
    propagation_settings = _resolve_propagation_settings(contour_set)
    backend = str(propagation_settings["method"])
    used_seed_count = len(protected_keys)
    run_dir = MODEL_RUN_DIR / f"propagation-{series['id']}-{module}-{uuid4().hex[:8]}"

    if _edgetam_available():
        try:
            manifest_path, _seeded_keys = _build_edgetam_manifest(
                run_dir=run_dir,
                frames=frames,
                frame_lookup=frame_lookup,
                contour_set=contour_set or {},
                module=module,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("items"):
                outputs = _run_edgetam(
                    manifest_path=manifest_path,
                    progress=progress,
                    should_pause=should_pause,
                )
                generated = _load_edgetam_outputs(
                    outputs=outputs,
                    frame_lookup=frame_lookup,
                    result_frames=result_frames,
                    module=module,
                    protected_keys=protected_keys,
                )
                if generated:
                    backend = f"edgetam+{propagation_settings['method']}"
        except JobPaused:
            raise
        except Exception:
            backend = str(propagation_settings["method"])

    _apply_optical_flow_fill(
        frames=frames,
        frame_lookup=frame_lookup,
        result_frames=result_frames,
        module=module,
        propagation_settings=propagation_settings,
        progress=progress,
        should_pause=should_pause,
    )

    generated_frames = {
        key: payload
        for key, payload in result_frames.items()
        if _frame_has_any_contours(payload, module)
    }
    if not generated_frames:
        raise PropagationError("传播补全没有生成有效轮廓，请先确认 ED/ES 勾画是否完整。")

    settings = deepcopy(contour_set.get("settings", {}))
    settings.update(
        {
            "backend": backend,
            "edgetam_available": _edgetam_available(),
            "propagation_axes": ["phase", "slice"],
            "seed_frame_count": used_seed_count,
            "propagation": propagation_settings,
        }
    )

    return {
        "series_id": int(series["id"]),
        "module": module,
        "coordinate_space": contour_set.get("coordinate_space", "pixel"),
        "source": f"{backend}-propagation",
        "settings": settings,
        "phase_labels": contour_set.get("phase_labels", {}),
        "frames": generated_frames,
    }


def propagate_neighbor_contours(
    *,
    series: dict,
    frames: list[dict],
    module: str,
    contour_set: dict | None,
    source_slice_index: int,
    source_phase_index: int,
    target_slice_index: int,
    target_phase_index: int,
    propagation_overrides: dict | None = None,
) -> dict:
    _validate_inputs(module, contour_set)
    if source_slice_index == target_slice_index and source_phase_index == target_phase_index:
        raise PropagationError("源帧和目标帧不能相同。")

    frame_lookup = {(int(frame["slice_index"]), int(frame["phase_index"])): frame for frame in frames}
    source_frame = frame_lookup.get((source_slice_index, source_phase_index))
    target_frame = frame_lookup.get((target_slice_index, target_phase_index))
    if source_frame is None:
        raise PropagationError("源帧不存在，无法执行相邻传播。")
    if target_frame is None:
        raise PropagationError("目标帧不存在，无法执行相邻传播。")

    source_key = _frame_key(source_slice_index, source_phase_index)
    target_key = _frame_key(target_slice_index, target_phase_index)
    source_payload = contour_set.get("frames", {}).get(source_key)
    if not _frame_has_any_contours(source_payload, module):
        raise PropagationError("当前帧还没有有效轮廓，请先勾画或保存当前帧。")

    source_masks = _frame_to_masks(source_payload, source_frame, module)
    if not source_masks:
        raise PropagationError("当前帧轮廓无法转换为传播种子。")

    propagation_settings = _resolve_propagation_settings(contour_set, propagation_overrides)
    propagated = _propagate_masks_between_frames(
        source_masks,
        read_frame_pixels(source_frame),
        read_frame_pixels(target_frame),
        settings=propagation_settings,
    )
    if not propagated:
        raise PropagationError("相邻传播没有生成有效轮廓，请检查当前帧勾画质量。")

    result_frames = deepcopy(contour_set.get("frames", {}))
    merged = _merge_frame_payload(result_frames.get(target_key), propagated, target_frame, module)
    if merged is None:
        raise PropagationError("目标帧没有生成可保存的轮廓。")
    result_frames[target_key] = merged

    settings = deepcopy(contour_set.get("settings", {}))
    settings.update(
        {
            "backend": f"{propagation_settings['method']}-local",
            "propagation": propagation_settings,
            "neighbor_propagation": {
                "source_slice_index": int(source_slice_index),
                "source_phase_index": int(source_phase_index),
                "target_slice_index": int(target_slice_index),
                "target_phase_index": int(target_phase_index),
            },
        }
    )

    return {
        "series_id": int(series["id"]),
        "module": module,
        "coordinate_space": contour_set.get("coordinate_space", "pixel"),
        "source": f"{propagation_settings['method']}-neighbor-propagation",
        "settings": settings,
        "phase_labels": contour_set.get("phase_labels", {}),
        "frames": result_frames,
    }
