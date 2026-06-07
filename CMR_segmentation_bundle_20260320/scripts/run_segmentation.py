from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from cmr_segmentation_bundle import (
    FourChSegmentationRunner,
    NnUNetSegmentationRunner,
    get_default_paths,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run CMR segmentation inference.")
    parser.add_argument(
        "--sequence",
        required=True,
        choices=["sax", "lge", "4ch"],
        help="Segmentation sequence type.",
    )
    parser.add_argument("--input", required=True, type=Path, help="Input NIfTI path.")
    parser.add_argument("--output-dir", required=True, type=Path, help="Output directory.")
    parser.add_argument("--gpu-id", type=int, default=None, help="GPU id. Defaults to 0 if CUDA is available.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    paths = get_default_paths()

    if args.sequence in {"sax", "lge"}:
        runner = NnUNetSegmentationRunner()
        output_path = runner.run(
            image_path=args.input,
            model_dir=paths.sax_lge_model_dir,
            output_dir=args.output_dir,
            gpu_id=args.gpu_id,
        )
    else:
        runner = FourChSegmentationRunner(gpu_id=args.gpu_id)
        output_path = runner.run(input_path=args.input, output_dir=args.output_dir)

    print(f"Segmentation saved to: {output_path}")


if __name__ == "__main__":
    main()
