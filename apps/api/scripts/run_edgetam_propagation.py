from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image
from sam2.build_sam import build_sam2_video_predictor


def normalize_config_name(raw_config: str) -> str:
    config_path = Path(raw_config)
    parts = config_path.parts
    if "sam2" in parts:
        index = len(parts) - 1 - parts[::-1].index("sam2")
        return str(Path(*parts[index + 1 :]))
    return raw_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run EdgeTAM propagation for one or more frame folders.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--gpu-id", default="0")
    parser.add_argument("--device", default="")
    parser.add_argument("--progress-file", default="")
    return parser.parse_args()


def write_progress(path: str, payload: dict[str, Any]) -> None:
    if not path:
        return
    progress_path = Path(path)
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def mask_from_path(mask_path: str) -> np.ndarray:
    mask = np.array(Image.open(mask_path).convert("L"))
    return mask > 0


def save_mask_bundle(output_dir: Path, frame_index: int, object_masks: dict[int, np.ndarray]) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {f"obj_{int(object_id)}": mask.astype(np.uint8) for object_id, mask in object_masks.items()}
    output_path = output_dir / f"frame-{frame_index:03d}.npz"
    np.savez_compressed(output_path, **payload)
    return str(output_path)


def main() -> int:
    args = parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    items = manifest.get("items", [])

    if args.device:
        device = args.device
    else:
        device = f"cuda:{args.gpu_id}" if torch.cuda.is_available() and args.gpu_id.lower() != "cpu" else "cpu"

    predictor = build_sam2_video_predictor(
        normalize_config_name(args.config),
        str(Path(args.checkpoint)),
        device=device,
    )

    results = []
    write_progress(args.progress_file, {"done": 0, "total": len(items), "slice_index": None})
    autocast_enabled = device.startswith("cuda")
    autocast_ctx = torch.autocast("cuda", dtype=torch.bfloat16) if autocast_enabled else torch.autocast("cpu", enabled=False)
    with torch.inference_mode(), autocast_ctx:
        for index, item in enumerate(items, start=1):
            state = predictor.init_state(
                item["video_dir"],
                offload_video_to_cpu=True,
                offload_state_to_cpu=False,
                async_loading_frames=False,
            )
            for seed in item.get("seeds", []):
                predictor.add_new_mask(
                    state,
                    frame_idx=int(seed["frame_index"]),
                    obj_id=int(seed["object_id"]),
                    mask=mask_from_path(seed["mask_path"]),
                )

            saved_outputs: list[str] = []
            for frame_index, object_ids, masks in predictor.propagate_in_video(state):
                object_masks: dict[int, np.ndarray] = {}
                for mask_index, object_id in enumerate(object_ids):
                    mask = masks[mask_index, 0] > 0
                    object_masks[int(object_id)] = mask.detach().cpu().numpy()
                saved_outputs.append(save_mask_bundle(Path(item["output_dir"]), int(frame_index), object_masks))

            results.append(
                {
                    "slice_index": int(item["slice_index"]),
                    "phase_indices": [int(value) for value in item["phase_indices"]],
                    "outputs": saved_outputs,
                }
            )
            write_progress(
                args.progress_file,
                {
                    "done": index,
                    "total": len(items),
                    "slice_index": int(item["slice_index"]),
                },
            )

    print(json.dumps({"items": results}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
