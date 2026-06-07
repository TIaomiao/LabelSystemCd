from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

import logging
import nibabel as nib
import numpy as np
import pydicom

from config.settings import DATA_DIR

MEASUREMENT_LOGGER = logging.getLogger("measurement")
DEFAULT_SLICE_THICKNESS_MM = 5.0

__all__ = [
    "load_nifti",
    "volume_from_mask",
    "volume_from_mask_simpson",
    "DEFAULT_SLICE_THICKNESS_MM",
    "MEASUREMENT_LOGGER",
]


def load_nifti(seg_path: Path) -> Tuple[np.ndarray, Tuple[float, float, float]]:
    img = nib.load(str(seg_path))
    data = np.asarray(img.dataobj)
    spacing = tuple(float(v) for v in img.header.get_zooms())
    return data, spacing


def volume_from_mask(mask: np.ndarray, spacing: Tuple[float, float, float]) -> float:
    voxel_volume = spacing[0] * spacing[1] * spacing[2]
    return float(mask.sum() * voxel_volume / 1000.0)


def volume_from_mask_simpson(
    mask: np.ndarray,
    spacing: Tuple[float, float, float],
    structure_name: str,
    seg_path: Optional[Path],
    sequence_hint: Optional[str],
) -> float:
    if mask.ndim != 3 or not np.any(mask):
        return 0.0
    spacing_xy = spacing[0] * spacing[1]
    sequence_name = sequence_hint or _infer_sequence_from_structure(structure_name)
    dicom_thickness = _get_dicom_slice_thickness(seg_path, sequence_name)
    spacing_z = dicom_thickness if dicom_thickness else (spacing[2] if spacing[2] > 0 else DEFAULT_SLICE_THICKNESS_MM)
    areas = mask.sum(axis=(0, 1)).astype(np.float64) * spacing_xy
    identifier = seg_path.name if seg_path else "N/A"
    MEASUREMENT_LOGGER.info(
        "[%s] 使用切片厚度 %.2f mm（来源：%s）",
        structure_name,
        spacing_z,
        "DICOM" if dicom_thickness else "NIfTI/默认",
    )
    for idx, area in enumerate(areas):
        MEASUREMENT_LOGGER.info(
            "[%s] slice %02d area = %.2f mm^2 (thickness %.2f mm, seg=%s)",
            structure_name,
            idx,
            area,
            spacing_z,
            identifier,
        )
    volume_mm3 = _simpson_integral(areas, spacing_z)
    return float(volume_mm3 / 1000.0)


def _simpson_integral(areas: np.ndarray, delta: float) -> float:
    n = areas.shape[0]
    if n == 0:
        return 0.0
    if n == 1:
        return float(areas[0] * delta)
    if n == 2:
        return float((areas[0] + areas[1]) * delta * 0.5)
    if n % 2 == 1:
        coeff = areas[0] + areas[-1]
        coeff += 4.0 * areas[1:-1:2].sum()
        coeff += 2.0 * areas[2:-2:2].sum()
        return float(coeff * delta / 3.0)
    coeff = areas[0] + areas[-2]
    coeff += 4.0 * areas[1:-2:2].sum()
    coeff += 2.0 * areas[2:-3:2].sum() if n > 3 else 0.0
    simpson_part = coeff * delta / 3.0
    trapezoid_part = (areas[-2] + areas[-1]) * delta * 0.5
    return float(simpson_part + trapezoid_part)


def _get_dicom_slice_thickness(seg_path: Optional[Path], sequence_name: Optional[str]) -> Optional[float]:
    if seg_path is None or sequence_name is None:
        return None
    try:
        seg_path_resolved = seg_path.resolve()
    except Exception:
        seg_path_resolved = seg_path
    return _cached_slice_thickness(str(seg_path_resolved), sequence_name)


@lru_cache(maxsize=256)
def _cached_slice_thickness(seg_path_str: str, sequence_name: str) -> Optional[float]:
    seg_path = Path(seg_path_str)
    dicom_dir = _infer_dicom_dir(seg_path, sequence_name)
    if dicom_dir is None:
        return None
    dcm_file = next(dicom_dir.glob("*.dcm"), None)
    if dcm_file is None:
        dcm_file = next(dicom_dir.rglob("*.dcm"), None)
    if dcm_file is None:
        return None
    try:
        ds = pydicom.dcmread(str(dcm_file), stop_before_pixels=True)
        if hasattr(ds, "SliceThickness"):
            return float(ds.SliceThickness)
        if hasattr(ds, "SpacingBetweenSlices"):
            return float(ds.SpacingBetweenSlices)
    except Exception:  # pragma: no cover
        MEASUREMENT_LOGGER.debug("读取DICOM厚度失败：%s", dcm_file)
    return None


def _infer_dicom_dir(seg_path: Path, sequence_name: str) -> Optional[Path]:
    parts = seg_path.parts
    if "output" not in parts:
        return None
    try:
        idx = parts.index("output")
        patient_id = parts[idx + 1]
    except (ValueError, IndexError):
        return None
    candidate = DATA_DIR / patient_id / sequence_name
    return candidate if candidate.is_dir() else None


def _infer_sequence_from_structure(structure_name: str) -> str:
    ventricles = {"LV", "RV", "IVS", "LVPW", "RWT", "SI", "LV/RV ratio"}
    return "SAX" if structure_name in ventricles else "4CH"

