from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run bundled CMR segmentation on a batch of NIfTI volumes.")
    parser.add_argument("--bundle-dir", required=True, type=Path, help="Path to CMR_segmentation_bundle directory.")
    parser.add_argument("--manifest", required=True, type=Path, help="JSON file describing batch items.")
    parser.add_argument("--gpu-id", type=int, default=None, help="GPU id passed through to bundle runners.")
    parser.add_argument("--progress-file", type=Path, default=None, help="Optional JSON progress file updated after each item.")
    parser.add_argument(
        "--case-batch-size",
        type=int,
        default=int(os.environ.get("CVI_SEG_CASE_BATCH_SIZE", "4")),
        help="Number of SAX/LGE NIfTI cases sent to nnU-Net in one predict_from_files call.",
    )
    return parser


def write_progress(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def chunked(items: list[tuple[int, dict[str, Any]]], size: int) -> list[list[tuple[int, dict[str, Any]]]]:
    size = max(1, int(size))
    return [items[index : index + size] for index in range(0, len(items), size)]


def main() -> None:
    args = build_parser().parse_args()
    bundle_src = args.bundle_dir / "src"
    if str(bundle_src) not in sys.path:
        sys.path.insert(0, str(bundle_src))

    from cmr_segmentation_bundle import FourChSegmentationRunner, NnUNetSegmentationRunner, get_default_paths

    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    nnunet_runner: NnUNetSegmentationRunner | None = None
    fourch_runner: FourChSegmentationRunner | None = None
    paths = get_default_paths()

    items = list(payload.get("items", []))
    results: list[dict[str, object] | None] = [None] * len(items)
    write_progress(args.progress_file, {"done": 0, "total": len(items), "phase_index": None})

    done_count = 0
    nnunet_items = [
        (index, item)
        for index, item in enumerate(items)
        if str(item["sequence"]) in {"sax", "lge"}
    ]
    for batch in chunked(nnunet_items, args.case_batch_size):
        if nnunet_runner is None:
            nnunet_runner = NnUNetSegmentationRunner()
        batch_paths = [
            (Path(str(item["input"])), Path(str(item["output_dir"])))
            for _index, item in batch
        ]
        output_paths = nnunet_runner.run_batch(
            batch_paths,
            model_dir=paths.sax_lge_model_dir,
            gpu_id=args.gpu_id,
        )
        for (original_index, item), output_path in zip(batch, output_paths):
            results[original_index] = {
                "sequence": str(item["sequence"]),
                "input": str(item["input"]),
                "output": str(output_path),
                "phase_index": item.get("phase_index"),
            }
            done_count += 1
            write_progress(
                args.progress_file,
                {
                    "done": done_count,
                    "total": len(items),
                    "phase_index": item.get("phase_index"),
                },
            )

    for original_index, item in enumerate(items):
        if results[original_index] is not None:
            continue
        sequence = str(item["sequence"])
        input_path = Path(str(item["input"]))
        output_dir = Path(str(item["output_dir"]))
        output_dir.mkdir(parents=True, exist_ok=True)

        if sequence in {"sax", "lge"}:
            if nnunet_runner is None:
                nnunet_runner = NnUNetSegmentationRunner()
            output_path = nnunet_runner.run(
                image_path=input_path,
                model_dir=paths.sax_lge_model_dir,
                output_dir=output_dir,
                gpu_id=args.gpu_id,
            )
        elif sequence == "4ch":
            if fourch_runner is None:
                fourch_runner = FourChSegmentationRunner(gpu_id=args.gpu_id)
            output_path = fourch_runner.run(input_path=input_path, output_dir=output_dir)
        else:
            raise ValueError(f"Unsupported sequence: {sequence}")

        results[original_index] = {
            "sequence": sequence,
            "input": str(input_path),
            "output": str(output_path),
            "phase_index": item.get("phase_index"),
        }
        done_count += 1
        write_progress(
            args.progress_file,
            {
                "done": done_count,
                "total": len(items),
                "phase_index": item.get("phase_index"),
            },
        )

    print(json.dumps({"items": [item for item in results if item is not None]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
