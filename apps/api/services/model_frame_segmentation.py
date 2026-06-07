from __future__ import annotations

from .dicom_indexer import get_series_row, list_frame_rows
from .inference import fetch_contours, save_contours
from .model_runner import run_model_inference


def supported_model_contours(module: str, role: str) -> set[str]:
    if module != "function":
        return set()
    if role == "cine_lax_4ch":
        return {"la", "endo", "ra", "rv"}
    return {"endo", "epi", "rv"}


def apply_model_frame_segmentation(
    series_id: int,
    *,
    module: str,
    slice_index: int,
    phase_index: int,
    contour_key: str,
    actor: dict | None = None,
) -> dict:
    series = get_series_row(series_id)
    supported = supported_model_contours(module, str(series.get("role") or ""))
    if contour_key not in supported:
        supported_label = "、".join(sorted(supported)) if supported else "暂无"
        raise ValueError(f"当前训练模型暂不支持 {module}/{contour_key}。已支持: {supported_label}。")

    all_frames = list_frame_rows(series_id)
    target_phase = 0 if module == "lge" else int(phase_index)
    phase_frames = [frame for frame in all_frames if int(frame["phase_index"]) == target_phase]
    if not phase_frames:
        raise ValueError("当前相位没有可用于模型推理的图像。")

    model_payload = run_model_inference(series=series, frames=phase_frames, module=module)
    target_key = f"{int(slice_index)}:{target_phase}"
    target_payload = (model_payload.get("frames") or {}).get(target_key)
    contour = (target_payload or {}).get(contour_key)
    if not contour or not contour.get("points"):
        raise RuntimeError("训练模型没有在当前帧生成可用轮廓。")

    existing = fetch_contours(series_id, module) or {
        "series_id": series_id,
        "module": module,
        "coordinate_space": "pixel",
        "source": "manual+model",
        "settings": {},
        "phase_labels": {},
        "frames": {},
    }
    frame_payload = dict((existing.get("frames") or {}).get(target_key) or {"include": True})
    frame_payload[contour_key] = contour
    existing.setdefault("frames", {})[target_key] = frame_payload
    existing["source"] = "manual+model-frame"
    existing.setdefault("settings", {})
    existing["settings"]["last_model_frame_contour"] = contour_key
    return save_contours(
        series_id,
        module,
        existing,
        actor=actor,
        action_origin="model",
        source_frame_key=target_key,
    )
