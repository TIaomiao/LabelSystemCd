from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np
from PIL import Image


def export_mask_pngs(nifti_path: Path) -> Path:
    image = nib.load(str(nifti_path))
    data = image.get_fdata().astype(np.int32)
    output_dir = nifti_path.parent / f"{strip_nii_suffix(nifti_path.name)}_pngs"
    output_dir.mkdir(parents=True, exist_ok=True)

    if data.ndim == 2:
        data = data[:, :, np.newaxis]

    if data.ndim < 3:
        raise ValueError(f"Unsupported mask ndim: {data.ndim}")

    scale_factor = 1
    max_value = int(data.max()) if data.size else 0
    if 0 < max_value <= 3:
        scale_factor = 255 // 3

    for index in range(data.shape[2]):
        slice_data = np.rot90(data[:, :, index])
        visible = (slice_data * scale_factor).clip(0, 255).astype(np.uint8)
        Image.fromarray(visible).save(output_dir / f"slice_{index:03d}.png")

    return output_dir


def strip_nii_suffix(filename: str) -> str:
    if filename.endswith(".nii.gz"):
        return filename[:-7]
    if filename.endswith(".nii"):
        return filename[:-4]
    return Path(filename).stem
