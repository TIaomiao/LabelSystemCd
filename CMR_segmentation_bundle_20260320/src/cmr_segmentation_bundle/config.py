from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BundlePaths:
    bundle_root: Path
    src_dir: Path
    models_dir: Path
    sax_lge_model_dir: Path
    four_ch_model_path: Path
    nnunet_raw_dir: Path
    nnunet_preprocessed_dir: Path
    nnunet_results_dir: Path


def get_default_paths() -> BundlePaths:
    bundle_root = Path(__file__).resolve().parents[2]
    models_dir = bundle_root / "models"
    return BundlePaths(
        bundle_root=bundle_root,
        src_dir=bundle_root / "src",
        models_dir=models_dir,
        sax_lge_model_dir=models_dir / "sax_lge" / "nnUNetTrainer__nnUNetPlans__3d_fullres",
        four_ch_model_path=models_dir / "4ch" / "best_model.pth",
        nnunet_raw_dir=models_dir / "nnUNet_raw_data",
        nnunet_preprocessed_dir=models_dir / "nnUNet_preprocessed",
        nnunet_results_dir=models_dir,
    )


def apply_nnunet_env(paths: BundlePaths | None = None) -> dict[str, str]:
    paths = paths or get_default_paths()
    env = {
        "nnUNet_raw": str(paths.nnunet_raw_dir),
        "nnUNet_preprocessed": str(paths.nnunet_preprocessed_dir),
        "nnUNet_results": str(paths.nnunet_results_dir),
    }
    os.environ.setdefault("nnUNet_raw", env["nnUNet_raw"])
    os.environ.setdefault("nnUNet_preprocessed", env["nnUNet_preprocessed"])
    os.environ.setdefault("nnUNet_results", env["nnUNet_results"])
    return env
