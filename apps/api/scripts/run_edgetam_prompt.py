from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

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
    parser = argparse.ArgumentParser(description="Run EdgeTAM prompt segmentation on a single frame.")
    parser.add_argument("--image", required=True)
    parser.add_argument("--mode", choices=["box", "brush"], required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--box", default="")
    parser.add_argument("--mask", default="")
    parser.add_argument("--gpu-id", default="0")
    parser.add_argument("--device", default="")
    return parser.parse_args()


def resolve_device(raw_device: str, gpu_id: str) -> str:
    if raw_device:
      return raw_device
    if torch.cuda.is_available() and gpu_id.lower() != "cpu":
      return f"cuda:{gpu_id}"
    return "cpu"


def main() -> int:
    args = parse_args()
    device = resolve_device(args.device, args.gpu_id)
    predictor = build_sam2_video_predictor(normalize_config_name(args.config), str(Path(args.checkpoint)), device=device)

    with tempfile.TemporaryDirectory(prefix="edgetam-prompt-") as temp_dir:
        frame_dir = Path(temp_dir) / "frames"
        frame_dir.mkdir(parents=True, exist_ok=True)
        frame_path = frame_dir / "0.jpg"
        Image.open(args.image).convert("RGB").save(frame_path, quality=95)

        state = predictor.init_state(
            str(frame_dir),
            offload_video_to_cpu=True,
            offload_state_to_cpu=False,
            async_loading_frames=False,
        )

        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16, enabled=device.startswith("cuda")):
            if args.mode == "box":
                if not args.box:
                    raise ValueError("Box prompt requires --box")
                box = np.array([float(value) for value in args.box.split(",")], dtype=np.float32)
                center = np.array([[(box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0]], dtype=np.float32)
                labels = np.array([1], dtype=np.int32)
                _frame_index, _object_ids, masks = predictor.add_new_points_or_box(
                    state,
                    frame_idx=0,
                    obj_id=1,
                    points=center,
                    labels=labels,
                    box=box,
                    clear_old_points=True,
                )
            else:
                if not args.mask:
                    raise ValueError("Brush prompt requires --mask")
                mask = np.array(Image.open(args.mask).convert("L")) > 0
                _frame_index, _object_ids, masks = predictor.add_new_mask(
                    state,
                    frame_idx=0,
                    obj_id=1,
                    mask=mask,
                )

        final_mask = (masks[0, 0] > 0).detach().cpu().numpy().astype(np.uint8)
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(output_path, mask=final_mask)
        print(json.dumps({"output": str(output_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
