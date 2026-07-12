from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from skimage.measure import find_contours, label

from ..config import (
    EDGETAM_CHECKPOINT_PATH,
    EDGETAM_CONFIG_PATH,
    EDGETAM_PROMPT_HELPER_SCRIPT,
    MODEL_GPU_ID,
    MODEL_PYTHON_PATH,
    MODEL_RUN_DIR,
    MODEL_TIMEOUT_SECONDS,
    build_edgetam_env,
)
from ..db import loads
from ..models import PromptSegmentationRequest
from .dicom_indexer import get_frame_row, get_series_row
from .inference import fetch_contours, save_contours
from .measurements import ensure_render


def _frame_key(slice_index: int, phase_index: int) -> str:
    return f"{slice_index}:{phase_index}"


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


def _mask_to_polygon(mask: np.ndarray, frame: dict) -> dict | None:
    if mask.sum() < 20:
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


def _largest_component(mask: np.ndarray) -> np.ndarray:
    labels = label(mask.astype(np.uint8), connectivity=1)
    if labels.max() <= 1:
        return mask
    best_component = None
    best_size = -1
    for component_index in range(1, labels.max() + 1):
        component = labels == component_index
        size = int(component.sum())
        if size > best_size:
            best_size = size
            best_component = component
    return best_component.astype(bool) if best_component is not None else mask


def _refine_box_mask(mask: np.ndarray, box: list[float]) -> np.ndarray:
    if mask.sum() <= 0:
        return mask
    x1, y1, x2, y2 = [float(value) for value in box]
    margin = max(8, int(round(max(abs(x2 - x1), abs(y2 - y1)) * 0.2)))
    rows, cols = mask.shape
    left = max(0, int(np.floor(min(x1, x2) - margin)))
    right = min(cols, int(np.ceil(max(x1, x2) + margin)))
    top = max(0, int(np.floor(min(y1, y2) - margin)))
    bottom = min(rows, int(np.ceil(max(y1, y2) + margin)))

    restricted = np.zeros_like(mask, dtype=bool)
    restricted[top:bottom, left:right] = mask[top:bottom, left:right] > 0
    if restricted.sum() <= 0:
        restricted = mask > 0

    labels = label(restricted.astype(np.uint8), connectivity=1)
    if labels.max() <= 1:
        return restricted.astype(np.uint8)

    box_mask = np.zeros_like(mask, dtype=bool)
    box_mask[max(0, int(np.floor(min(y1, y2)))):min(rows, int(np.ceil(max(y1, y2)))), max(0, int(np.floor(min(x1, x2)))):min(cols, int(np.ceil(max(x1, x2))))] = True
    center_x = (x1 + x2) / 2.0
    center_y = (y1 + y2) / 2.0
    best_component = None
    best_score = -1.0
    for component_index in range(1, labels.max() + 1):
        component = labels == component_index
        overlap = float((component & box_mask).sum())
        if overlap <= 0:
            continue
        ys, xs = np.where(component)
        centroid_x = float(xs.mean()) if xs.size else center_x
        centroid_y = float(ys.mean()) if ys.size else center_y
        distance_penalty = np.hypot(centroid_x - center_x, centroid_y - center_y)
        score = overlap - distance_penalty * 0.35
        if score > best_score:
            best_score = score
            best_component = component
    if best_component is None:
        return _largest_component(restricted.astype(bool)).astype(np.uint8)
    return best_component.astype(np.uint8)


def _seed_mask_from_brush(mask_shape: tuple[int, int], brush_points: list[dict], brush_radius: float) -> np.ndarray:
    rows, cols = mask_shape
    seed_mask = np.zeros((rows, cols), dtype=bool)
    if rows <= 0 or cols <= 0 or not brush_points:
        return seed_mask
    radius = max(2, int(round(brush_radius)))
    yy, xx = np.ogrid[:rows, :cols]
    for point in brush_points:
        px = float(point["x"])
        py = float(point["y"])
        seed_mask |= (xx - px) ** 2 + (yy - py) ** 2 <= radius ** 2
    return seed_mask


def _select_component_overlapping_seed(mask: np.ndarray, seed_mask: np.ndarray) -> np.ndarray:
    if mask.sum() <= 0:
        return mask
    labels = label((mask > 0).astype(np.uint8), connectivity=1)
    if labels.max() <= 1:
        return (mask > 0).astype(np.uint8)
    best_component = None
    best_score = -1.0
    for component_index in range(1, labels.max() + 1):
        component = labels == component_index
        overlap = float((component & seed_mask).sum())
        size = float(component.sum())
        score = overlap * 10.0 + min(size, 5000.0) * 0.001
        if score > best_score:
            best_score = score
            best_component = component
    return best_component.astype(np.uint8) if best_component is not None else _largest_component(mask > 0).astype(np.uint8)


def _refine_brush_mask(mask: np.ndarray, brush_points: list[dict], brush_radius: float) -> np.ndarray:
    if mask.sum() <= 0 or not brush_points:
        return mask
    seed_mask = _seed_mask_from_brush(mask.shape, brush_points, brush_radius)
    return _select_component_overlapping_seed(mask, seed_mask)


def _render_brush_mask(frame: dict, brush_points: list[dict], brush_radius: float, output_path: Path) -> Path:
    rows = int(loads(frame.get("metadata_json"), {}).get("rows") or 0)
    cols = int(loads(frame.get("metadata_json"), {}).get("cols") or 0)
    if rows <= 0 or cols <= 0:
        raise ValueError("当前帧缺少图像尺寸，无法生成涂色提示。")
    image = Image.new("L", (cols, rows), 0)
    draw = ImageDraw.Draw(image)
    radius = max(1, int(round(brush_radius)))
    if len(brush_points) == 1:
        point = brush_points[0]
        draw.ellipse((point["x"] - radius, point["y"] - radius, point["x"] + radius, point["y"] + radius), fill=255)
    else:
        path = [(float(point["x"]), float(point["y"])) for point in brush_points]
        draw.line(path, fill=255, width=max(2, radius * 2), joint="curve")
        for point in path:
            draw.ellipse((point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius), fill=255)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path


def _frame_dimensions(frame: dict) -> tuple[int, int]:
    metadata = loads(frame.get("metadata_json"), {})
    rows = int(metadata.get("rows") or 0)
    cols = int(metadata.get("cols") or 0)
    return rows, cols


def _clamp_box_to_frame(box: list[float], frame: dict) -> list[float]:
    rows, cols = _frame_dimensions(frame)
    if rows <= 0 or cols <= 0:
        return [float(value) for value in box]
    x1, y1, x2, y2 = [float(value) for value in box]
    left = float(np.clip(min(x1, x2), 0, cols))
    right = float(np.clip(max(x1, x2), 0, cols))
    top = float(np.clip(min(y1, y2), 0, rows))
    bottom = float(np.clip(max(y1, y2), 0, rows))
    return [left, top, right, bottom]


def _write_prompt_debug(run_dir: Path, payload: dict) -> None:
    try:
        (run_dir / "prompt-debug.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _write_prompt_logs(run_dir: Path, stdout: str, stderr: str) -> None:
    try:
        (run_dir / "prompt.stdout.log").write_text(stdout or "", encoding="utf-8")
        (run_dir / "prompt.stderr.log").write_text(stderr or "", encoding="utf-8")
    except Exception:
        pass


def _normalize_edgetam_error(message: str) -> str:
    normalized = (message or "").strip()
    if "No module named 'sam2'" in normalized:
        return "EdgeTAM 运行环境缺少 sam2 依赖，请检查第三方仓库和 Python 环境。"
    if "No module named 'torch'" in normalized:
        return "EdgeTAM 运行环境缺少 torch 依赖，请检查模型 Python 环境。"
    if "No module named 'hydra'" in normalized or "No module named 'omegaconf'" in normalized:
        return "EdgeTAM 运行环境缺少配置依赖，请检查 hydra/omegaconf 安装。"
    return normalized or "EdgeTAM prompt failed"


def _run_prompt_helper(*, series_id: int, image_path: Path, prompt: PromptSegmentationRequest, run_dir: Path) -> np.ndarray:
    if not MODEL_PYTHON_PATH.exists():
        raise RuntimeError(f"未找到 cvi-seg Python 环境: {MODEL_PYTHON_PATH}，无法运行 EdgeTAM prompt 分割。")
    if not EDGETAM_PROMPT_HELPER_SCRIPT.exists():
        raise RuntimeError("未找到 EdgeTAM prompt helper 脚本。")
    if not EDGETAM_CONFIG_PATH.exists() or not EDGETAM_CHECKPOINT_PATH.exists():
        raise RuntimeError("未找到 EdgeTAM 配置或 checkpoint。")

    output_path = run_dir / "prompt-mask.npz"
    command = [
        str(MODEL_PYTHON_PATH),
        str(EDGETAM_PROMPT_HELPER_SCRIPT),
        "--image",
        str(image_path),
        "--mode",
        prompt.prompt_mode,
        "--config",
        str(EDGETAM_CONFIG_PATH),
        "--checkpoint",
        str(EDGETAM_CHECKPOINT_PATH),
        "--output",
        str(output_path),
        "--gpu-id",
        str(MODEL_GPU_ID),
    ]

    if prompt.prompt_mode == "box":
        if not prompt.box or len(prompt.box) != 4:
            raise ValueError("框选 + SAM 需要提供有效的 box。")
        command.extend(["--box", ",".join(str(float(value)) for value in prompt.box)])
    else:
        if not prompt.brush_points:
            raise ValueError("涂色 + SAM 需要提供 brush points。")
        mask_path = _render_brush_mask(
            get_frame_row(series_id, prompt.slice_index, prompt.phase_index),
            [point.model_dump() for point in prompt.brush_points],
            prompt.brush_radius,
            run_dir / "brush-mask.png",
        )
        command.extend(["--mask", str(mask_path)])

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=MODEL_TIMEOUT_SECONDS,
        check=False,
        env=build_edgetam_env(),
    )
    _write_prompt_logs(run_dir, completed.stdout, completed.stderr)
    if completed.returncode != 0:
        message = _normalize_edgetam_error(completed.stderr or completed.stdout or "EdgeTAM prompt failed")
        raise RuntimeError(f"EdgeTAM prompt 分割失败: {message}")
    if not output_path.exists():
        raise RuntimeError(f"EdgeTAM prompt 未生成输出: {completed.stdout.strip()}")
    with np.load(output_path) as payload:
        return payload["mask"].astype(np.uint8)


def apply_prompt_segmentation(series_id: int, prompt: PromptSegmentationRequest, actor: dict | None = None) -> dict:
    series = get_series_row(series_id)
    frame = get_frame_row(series_id, prompt.slice_index, prompt.phase_index)
    render_path = ensure_render(frame, series_id)
    run_dir = MODEL_RUN_DIR / f"prompt-{series_id}-{prompt.module}-{prompt.slice_index:03d}-{prompt.phase_index:03d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    if prompt.prompt_mode == "box" and prompt.box:
        prompt = prompt.model_copy(update={"box": _clamp_box_to_frame(prompt.box, frame)})

    mask = _run_prompt_helper(series_id=series_id, image_path=render_path, prompt=prompt, run_dir=run_dir)
    raw_mask_sum = int(mask.sum())
    component_count = int(label((mask > 0).astype(np.uint8), connectivity=1).max()) if raw_mask_sum > 0 else 0
    if prompt.prompt_mode == "box" and prompt.box:
        mask = _refine_box_mask(mask, prompt.box)
    elif prompt.prompt_mode == "brush" and prompt.brush_points:
        mask = _refine_brush_mask(mask, [point.model_dump() for point in prompt.brush_points], prompt.brush_radius)
    refined_mask_sum = int(mask.sum())
    _write_prompt_debug(
        run_dir,
        {
            "series_id": series_id,
            "module": prompt.module,
            "slice_index": prompt.slice_index,
            "phase_index": prompt.phase_index,
            "contour_key": prompt.contour_key,
            "prompt_mode": prompt.prompt_mode,
            "box": prompt.box,
            "brush_points": len(prompt.brush_points),
            "raw_mask_sum": raw_mask_sum,
            "refined_mask_sum": refined_mask_sum,
            "raw_component_count": component_count,
            "image_path": str(render_path),
        },
    )
    contour = _mask_to_polygon(mask, frame)
    if contour is None:
        raise RuntimeError(
            f"当前提示没有生成可用轮廓。raw={raw_mask_sum}, refined={refined_mask_sum}，"
            "请稍微扩大框选或改用涂色 + SAM。"
        )

    existing = fetch_contours(series_id, prompt.module) or {
        "series_id": series_id,
        "module": prompt.module,
        "coordinate_space": "pixel",
        "source": "manual+prompt",
        "settings": {},
        "phase_labels": {},
        "frames": {},
    }
    frame_key = _frame_key(prompt.slice_index, 0 if prompt.module == "lge" else prompt.phase_index)
    frame_payload = dict(existing["frames"].get(frame_key) or {"include": True})
    if prompt.contour_key == "exclude":
        raw_regions = frame_payload.get("exclude_regions")
        if isinstance(raw_regions, list):
            regions = [region for region in raw_regions if isinstance(region, dict) and region.get("points")]
        elif isinstance(frame_payload.get("exclude"), dict) and frame_payload["exclude"].get("points"):
            regions = [frame_payload["exclude"]]
        else:
            regions = []
        regions.append(contour)
        frame_payload["exclude_regions"] = regions
        frame_payload["exclude"] = regions[0] if regions else None
    else:
        frame_payload[prompt.contour_key] = contour
    frame_payload.setdefault("fat", None)
    frame_payload.setdefault("fat_outer", None)
    frame_payload.setdefault("ventricular_epi", None)
    existing["frames"][frame_key] = frame_payload
    existing["source"] = "manual+edgetam-prompt"
    existing.setdefault("settings", {})
    existing["settings"]["last_prompt_mode"] = prompt.prompt_mode
    return save_contours(
        series_id,
        prompt.module,
        existing,
        actor=actor,
        action_origin="prompt",
        source_frame_key=frame_key,
    )
