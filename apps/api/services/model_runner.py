from __future__ import annotations

import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import nibabel as nib
import numpy as np
from skimage.measure import find_contours
from skimage.transform import resize

from ..config import MODEL_BUNDLE_DIR, MODEL_CASE_BATCH_SIZE, MODEL_GPU_IDS, MODEL_HELPER_SCRIPT, MODEL_PYTHON_PATH, MODEL_RUN_DIR, MODEL_TIMEOUT_SECONDS
from ..db import loads
from .gpu_monitor import estimate_safe_case_batch_size, get_gpu_status, gpu_has_safe_capacity, sort_gpus_by_headroom
from .job_control import JobPaused, ProgressCallback, ShouldPauseCallback
from .dicom_indexer import read_frame_pixels


class ModelIntegrationPendingError(RuntimeError):
    pass


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


def _validate_environment() -> None:
    if not MODEL_BUNDLE_DIR.exists():
        raise ModelIntegrationPendingError(f"未找到分割 bundle: {MODEL_BUNDLE_DIR}")
    if not MODEL_HELPER_SCRIPT.exists():
        raise ModelIntegrationPendingError(f"未找到模型批处理脚本: {MODEL_HELPER_SCRIPT}")
    if not MODEL_PYTHON_PATH.exists():
        raise ModelIntegrationPendingError(
            f"未找到分割模型 Python 环境: {MODEL_PYTHON_PATH}。请确认环境已创建，或设置 CVI_SEG_PYTHON 指向正确的 Python。"
        )


def _resolve_sequence(series: dict, module: str) -> str:
    role = str(series.get("role") or "")
    if module == "function":
        if role == "cine_lax_4ch":
            return "4ch"
        if role not in {"cine_sax", "unknown"}:
            raise ModelIntegrationPendingError(f"Function 只支持 SAX cine 或 4CH cine 序列，当前角色为: {role or 'unknown'}")
        return "sax"
    if module == "lge":
        if role not in {"lge_sax", "lge_lax", "unknown"}:
            raise ModelIntegrationPendingError(f"Tissue|LGE 只支持 LGE 序列，当前角色为: {role or 'unknown'}")
        return "lge"
    raise ModelIntegrationPendingError(f"暂不支持的模块: {module}")


def _group_phase_frames(series: dict, frames: list[dict]) -> dict[int, list[dict]]:
    phase_indices = sorted({int(frame["phase_index"]) for frame in frames})
    if not phase_indices:
        raise ModelIntegrationPendingError("当前序列没有可用帧，无法运行自动分割。")

    by_slice: dict[int, list[dict]] = {}
    for frame in frames:
        by_slice.setdefault(int(frame["slice_index"]), []).append(frame)
    for bucket in by_slice.values():
        bucket.sort(key=lambda item: int(item["phase_index"]))

    resolved: dict[int, list[dict]] = {}
    total_slices = int(series.get("slice_count") or 0)
    for phase_index in phase_indices:
        phase_frames: list[dict] = []
        for slice_index in range(total_slices):
            candidates = by_slice.get(slice_index, [])
            if not candidates:
                continue
            exact = next((item for item in candidates if int(item["phase_index"]) == phase_index), None)
            chosen = exact or min(candidates, key=lambda item: abs(int(item["phase_index"]) - phase_index))
            phase_frames.append({**chosen, "phase_index": phase_index})
        if phase_frames:
            resolved[phase_index] = phase_frames
    if not resolved:
        raise ModelIntegrationPendingError("当前序列无法整理出可推理的 3D 体数据。")
    return resolved


def _build_affine(series: dict) -> np.ndarray:
    spacing_x = float(series.get("pixel_spacing_x") or 1.0)
    spacing_y = float(series.get("pixel_spacing_y") or 1.0)
    slice_thickness = float(series.get("slice_thickness") or 8.0)
    return np.array(
        [
            [spacing_x, 0.0, 0.0, 0.0],
            [0.0, spacing_y, 0.0, 0.0],
            [0.0, 0.0, slice_thickness, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
        dtype=float,
    )


def _write_phase_nifti(series: dict, phase_frames: list[dict], output_path: Path) -> None:
    volume = [read_frame_pixels(frame).astype(np.float32) / 255.0 for frame in phase_frames]
    stack = np.stack(volume, axis=2).astype(np.float32)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(stack, _build_affine(series)), str(output_path))


def _resolve_gpu_ids() -> list[int | None]:
    raw_values = [value.strip().lower() for value in MODEL_GPU_IDS.split(",") if value.strip()]
    if not raw_values:
        return [0]
    if any(value == "cpu" for value in raw_values):
        return [None]
    return [int(value) for value in raw_values]


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


def _run_bundle_chunk(
    *,
    manifest_path: Path,
    progress_file: Path,
    gpu_id: int | None,
    case_batch_size: int,
    should_pause: ShouldPauseCallback | None,
) -> list[dict]:
    command = [
        str(MODEL_PYTHON_PATH),
        str(MODEL_HELPER_SCRIPT),
        "--bundle-dir",
        str(MODEL_BUNDLE_DIR),
        "--manifest",
        str(manifest_path),
    ]
    if gpu_id is not None:
        command.extend(["--gpu-id", str(gpu_id)])
    command.extend(["--progress-file", str(progress_file)])
    command.extend(["--case-batch-size", str(case_batch_size)])

    stdout_path = progress_file.with_suffix(".stdout.log")
    stderr_path = progress_file.with_suffix(".stderr.log")
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open("w", encoding="utf-8") as stderr_file:
        process = subprocess.Popen(
            command,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
        )
        start_time = time.monotonic()
        while process.poll() is None:
            if should_pause and should_pause():
                _terminate_process(process)
                raise JobPaused("自动分割已暂停，后台模型进程已停止。")
            if time.monotonic() - start_time > MODEL_TIMEOUT_SECONDS:
                _terminate_process(process)
                raise ModelIntegrationPendingError("自动分割执行超时。")
            time.sleep(0.5)

    stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
    stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
    completed = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "bundle execution failed").strip()
        raise ModelIntegrationPendingError(f"自动分割执行失败: {message}")
    stdout_lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    json_payload = stdout_lines[-1] if stdout_lines else ""
    try:
        payload = json.loads(json_payload)
    except json.JSONDecodeError as exc:
        raise ModelIntegrationPendingError(f"自动分割返回内容不可解析: {completed.stdout.strip() or exc}") from exc
    return list(payload.get("items", []))


def _run_bundle_parallel(
    *,
    run_dir: Path,
    manifest_items: list[dict],
    progress: ProgressCallback | None,
    should_pause: ShouldPauseCallback | None,
) -> list[dict]:
    if not manifest_items:
        return []
    configured_gpu_ids = _resolve_gpu_ids()
    gpu_ids = [gpu_id for gpu_id in sort_gpus_by_headroom(configured_gpu_ids) if gpu_has_safe_capacity(gpu_id)]
    if not gpu_ids:
        gpu_ids = sort_gpus_by_headroom(configured_gpu_ids)[:1]
    workers = max(1, min(len(gpu_ids), len(manifest_items)))
    chunks: list[list[dict]] = [[] for _ in range(workers)]
    for index, item in enumerate(manifest_items):
        chunks[index % workers].append(item)

    manifests: list[Path] = []
    progress_files: list[Path] = []
    for index, chunk in enumerate(chunks):
        manifest_path = run_dir / "manifests" / f"chunk-{index:02d}.json"
        _write_manifest(manifest_path, chunk)
        manifests.append(manifest_path)
        progress_files.append(run_dir / "progress" / f"chunk-{index:02d}.json")

    batch_sizes = [
        estimate_safe_case_batch_size(gpu_ids[index], len(chunks[index]))
        for index in range(workers)
    ]

    if progress:
        gpu_plan = ", ".join(
            f"{'CPU' if gpu_ids[index] is None else 'GPU ' + str(gpu_ids[index])}: batch {batch_sizes[index]}"
            for index in range(workers)
        )
        progress(0, len(manifest_items), f"并行启动 {workers} 个模型进程，{gpu_plan}")

    outputs: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(
                _run_bundle_chunk,
                manifest_path=manifests[index],
                progress_file=progress_files[index],
                gpu_id=gpu_ids[index],
                case_batch_size=batch_sizes[index],
                should_pause=should_pause,
            ): index
            for index in range(workers)
        }
        while future_map:
            if should_pause and should_pause():
                for future in future_map:
                    future.cancel()
                raise JobPaused("自动分割已暂停。")
            done_count = _read_progress(progress_files)
            if progress:
                gpu_status = get_gpu_status()
                busy = [
                    f"GPU {gpu['index']} {gpu['memory_used_mb']}/{gpu['memory_total_mb']}MB {gpu['utilization_gpu']:.0f}%"
                    for gpu in gpu_status.get("gpus", [])
                    if gpu["index"] in {value for value in gpu_ids if value is not None}
                ]
                suffix = "；" + "，".join(busy) if busy else ""
                progress(done_count, len(manifest_items), f"AI 分割中：已完成 {done_count}/{len(manifest_items)} 个时相{suffix}")
            finished = [future for future in future_map if future.done()]
            for future in finished:
                outputs.extend(future.result())
                future_map.pop(future)
            if future_map:
                time.sleep(0.6)

    if progress:
        progress(len(manifest_items), len(manifest_items), "AI 分割完成，正在转换轮廓")
    return sorted(outputs, key=lambda item: int(item.get("phase_index") or 0))


def _load_label_slices(mask_path: Path) -> list[np.ndarray]:
    data = np.rint(np.asarray(nib.load(str(mask_path)).get_fdata())).astype(np.int16)
    if data.ndim == 2:
        data = data[:, :, np.newaxis]
    if data.ndim != 3:
        raise ModelIntegrationPendingError(f"分割输出维度不受支持: {data.shape}")
    return [data[:, :, index] for index in range(data.shape[2])]


def _frame_shape(frame: dict) -> tuple[int, int]:
    metadata = loads(frame.get("metadata_json"), {})
    rows = int(metadata.get("rows") or 0)
    cols = int(metadata.get("cols") or 0)
    if rows <= 0 or cols <= 0:
        pixels = read_frame_pixels(frame)
        rows, cols = pixels.shape[:2]
    return rows, cols


def _fit_label_map_to_frame(label_map: np.ndarray, frame: dict) -> np.ndarray:
    target_rows, target_cols = _frame_shape(frame)
    if label_map.shape == (target_rows, target_cols):
        return label_map
    resized = resize(
        label_map.astype(np.float32),
        (target_rows, target_cols),
        order=0,
        preserve_range=True,
        anti_aliasing=False,
    )
    return np.rint(resized).astype(np.int16)


def _contours_from_labels(label_map: np.ndarray, frame: dict, module: str) -> dict | None:
    label_map = _fit_label_map_to_frame(label_map, frame)
    la = _mask_to_polygon(label_map == 420, frame)
    lv_4ch = _mask_to_polygon(label_map == 500, frame)
    ra = _mask_to_polygon(label_map == 550, frame)
    rv_4ch = _mask_to_polygon(label_map == 600, frame)
    if any([la, lv_4ch, ra, rv_4ch]):
        return {
            "include": True,
            "la": la,
            "ra": ra,
            "endo": lv_4ch,
            "epi": None,
            "rv": rv_4ch,
            "remote": None,
            "enhanced": None,
            "exclude": None,
            "mvo": None,
        }

    rv_mask = label_map == 1
    myo_mask = label_map == 2
    lv_mask = label_map == 3
    endo = _mask_to_polygon(lv_mask, frame)
    epi = _mask_to_polygon(lv_mask | myo_mask, frame)
    rv = _mask_to_polygon(rv_mask, frame) if module == "function" else None
    if not any([endo, epi, rv]):
        return None
    return {
        "include": True,
        "endo": endo,
        "epi": epi,
        "rv": rv,
        "remote": None,
        "enhanced": None,
        "exclude": None,
        "mvo": None,
    }


def run_model_inference(
    *,
    series: dict,
    frames: list[dict],
    module: str,
    progress: ProgressCallback | None = None,
    should_pause: ShouldPauseCallback | None = None,
) -> dict:
    _validate_environment()
    sequence = _resolve_sequence(series, module)
    phase_map = _group_phase_frames(series, frames)
    run_dir = MODEL_RUN_DIR / f"series-{series['id']}-{module}-{uuid4().hex[:8]}"
    input_dir = run_dir / "inputs"
    output_dir = run_dir / "outputs"
    manifest_items = []

    if progress:
        progress(0, len(phase_map), f"正在准备 {len(phase_map)} 个时相的模型输入")
    for phase_index, phase_frames in phase_map.items():
        if should_pause and should_pause():
            raise JobPaused("自动分割已暂停。")
        input_path = input_dir / f"phase-{phase_index:03d}.nii.gz"
        _write_phase_nifti(series, phase_frames, input_path)
        manifest_items.append(
            {
                "sequence": sequence,
                "phase_index": phase_index,
                "input": str(input_path),
                "output_dir": str(output_dir / f"phase-{phase_index:03d}"),
            }
        )

    manifest_path = run_dir / "manifest.json"
    _write_manifest(manifest_path, manifest_items)

    outputs = _run_bundle_parallel(
        run_dir=run_dir,
        manifest_items=manifest_items,
        progress=progress,
        should_pause=should_pause,
    )
    contour_frames: dict[str, dict] = {}
    phase_totals: dict[int, int] = {}

    if progress:
        progress(len(manifest_items), len(manifest_items) + len(outputs), "正在从分割结果生成轮廓")
    for item in outputs:
        if should_pause and should_pause():
            raise JobPaused("自动分割已暂停。")
        phase_index = int(item["phase_index"])
        phase_frames = phase_map.get(phase_index, [])
        label_slices = _load_label_slices(Path(str(item["output"])))
        if len(label_slices) != len(phase_frames):
            raise ModelIntegrationPendingError(
                f"分割输出切片数与输入不一致: phase {phase_index}, input={len(phase_frames)}, output={len(label_slices)}"
            )
        lv_total = 0
        for frame, label_map in zip(phase_frames, label_slices):
            contour_payload = _contours_from_labels(label_map, frame, module)
            if contour_payload is not None:
                contour_frames[_frame_key(int(frame["slice_index"]), int(frame["phase_index"]))] = contour_payload
            lv_total += int((label_map == 3).sum())
        phase_totals[phase_index] = lv_total
        if progress:
            progress(
                len(manifest_items) + len(phase_totals),
                len(manifest_items) + len(outputs),
                f"正在生成轮廓：{len(phase_totals)}/{len(outputs)}",
            )

    ed_phase = 0
    es_phase = 0
    if module == "function" and phase_totals:
        ed_phase = max(phase_totals.items(), key=lambda item: item[1])[0]
        es_phase = min(phase_totals.items(), key=lambda item: item[1])[0]

    return {
        "series_id": int(series["id"]),
        "module": module,
        "coordinate_space": "pixel",
        "source": f"bundle:{MODEL_BUNDLE_DIR.name}",
        "settings": {
            "sequence": sequence,
            "bundle_dir": str(MODEL_BUNDLE_DIR),
            "python_path": str(MODEL_PYTHON_PATH),
            "phase_count": len(phase_map),
        },
        "phase_labels": {"ed": ed_phase, "es": es_phase},
        "frames": contour_frames,
    }
