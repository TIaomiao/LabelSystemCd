from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .measurements.geometry import (
    _geometric_chamber_measurements,
    _get_representative_sax_slices,
    _line_dict,
    _posterior_wall_thickness,
    _principal_axis_diameter,
    _render_measurement_figure,
    _septum_thickness,
)
from .measurements.volume import (
    load_nifti as _load_nifti,
    volume_from_mask as _volume_from_mask,
    volume_from_mask_simpson as _volume_from_mask_simpson,
)

# 标签约定
SAX_LABELS = {
    "RV": 1,
    "MYO": 2,
    "LV": 3,
}

FOUR_CH_LABELS = {
    "LA": 420,
    "LV": 500,
    "MYO": 205,
    "RA": 550,
    "RV": 600,
}


@dataclass
class SaxMeasurementResult:
    lv_volume_ml: float
    rv_volume_ml: float
    lv_inner_diameter_mm: float
    rv_inner_diameter_mm: float
    ivs_thickness_mm: float
    lvpw_thickness_mm: float
    visualization_paths: List[Path]


@dataclass
class AtrialVolumeResult:
    la_volume_ml: float
    ra_volume_ml: float


def measure_sax_metrics(seg_path: Path, viz_dir: Optional[Path] = None) -> SaxMeasurementResult:
    volume, spacing, spacing_xy, slice_idx, lv_slice, rv_slice, myo_slice = _get_representative_sax_slices(seg_path)

    lv_volume_ml = _volume_from_mask_simpson(volume == SAX_LABELS["LV"], spacing, "LV", seg_path, "SAX")
    rv_volume_ml = _volume_from_mask_simpson(volume == SAX_LABELS["RV"], spacing, "RV", seg_path, "SAX")

    (
        lv_diameter,
        lv_line,
        rv_diameter,
        rv_line,
        ivs_thickness,
        ivs_line,
        lvpw_thickness,
        lvpw_line,
    ) = _geometric_chamber_measurements(
        lv_slice=lv_slice,
        rv_slice=rv_slice,
        myo_slice=myo_slice,
        spacing_xy=spacing_xy,
    )

    if lv_diameter == 0.0 or rv_diameter == 0.0:
        lv_diameter_pca, lv_line_pca = _principal_axis_diameter(lv_slice, spacing_xy)
        rv_diameter_pca, rv_line_pca = _principal_axis_diameter(rv_slice, spacing_xy)
        if lv_diameter == 0.0:
            lv_diameter = lv_diameter_pca
            lv_line = lv_line_pca
        if rv_diameter == 0.0:
            rv_diameter = rv_diameter_pca
            rv_line = rv_line_pca
    if ivs_thickness == 0.0 or lvpw_thickness == 0.0:
        fallback_ivs, fallback_ivs_line = _septum_thickness(lv_slice, rv_slice, myo_slice, spacing_xy)
        fallback_lvpw, fallback_lvpw_line = _posterior_wall_thickness(lv_slice, rv_slice, myo_slice, spacing_xy)
        if ivs_thickness == 0.0:
            ivs_thickness = fallback_ivs
            ivs_line = fallback_ivs_line
        if lvpw_thickness == 0.0:
            lvpw_thickness = fallback_lvpw
            lvpw_line = fallback_lvpw_line

    visualization_paths: List[Path] = []
    if viz_dir is not None:
        viz_path = viz_dir / f"{seg_path.stem}_slice{slice_idx:02d}.png"
        viz_path.parent.mkdir(parents=True, exist_ok=True)
        _render_measurement_figure(
            output_path=viz_path,
            lv_slice=lv_slice,
            rv_slice=rv_slice,
            myo_slice=myo_slice,
            lines=[
                _line_dict("LV inner diameter", "#00FFFF", lv_line, lv_diameter),
                _line_dict("RV inner diameter", "#FFD700", rv_line, rv_diameter),
                _line_dict("IVS thickness", "#FF6F61", ivs_line, ivs_thickness),
                _line_dict("LVPW thickness", "#FFA500", lvpw_line, lvpw_thickness),
            ],
        )
        visualization_paths.append(viz_path)

    return SaxMeasurementResult(
        lv_volume_ml=lv_volume_ml,
        rv_volume_ml=rv_volume_ml,
        lv_inner_diameter_mm=lv_diameter,
        rv_inner_diameter_mm=rv_diameter,
        ivs_thickness_mm=ivs_thickness,
        lvpw_thickness_mm=lvpw_thickness,
        visualization_paths=visualization_paths,
    )


def measure_atrial_volumes(
    seg_path: Path,
    la_label: int = FOUR_CH_LABELS["LA"],
    ra_label: int = FOUR_CH_LABELS["RA"],
) -> AtrialVolumeResult:
    volume, spacing = _load_nifti(seg_path)
    la_volume = _volume_from_mask_simpson(volume == la_label, spacing, "LA", seg_path, "4CH")
    ra_volume = _volume_from_mask_simpson(volume == ra_label, spacing, "RA", seg_path, "4CH")
    return AtrialVolumeResult(la_volume_ml=la_volume, ra_volume_ml=ra_volume)


def compute_label_volume_ml(seg_path: Path, label_id: int) -> float:
    volume, spacing = _load_nifti(seg_path)
    return _volume_from_mask(volume == label_id, spacing)


def compute_multiple_volumes(seg_path: Path, label_map: Dict[str, int]) -> Dict[str, float]:
    volume, spacing = _load_nifti(seg_path)
    return {name: _volume_from_mask(volume == label, spacing) for name, label in label_map.items()}


def calculate_lv_volume(seg_path: Path, label: int = SAX_LABELS["LV"]) -> float:
    data, spacing = _load_nifti(seg_path)
    return _volume_from_mask_simpson(data == label, spacing, "LV", seg_path, "SAX")


def calculate_rv_volume(seg_path: Path, label: int = SAX_LABELS["RV"]) -> float:
    data, spacing = _load_nifti(seg_path)
    return _volume_from_mask_simpson(data == label, spacing, "RV", seg_path, "SAX")


def calculate_la_volume(seg_path: Path, label: int = FOUR_CH_LABELS["LA"]) -> float:
    data, spacing = _load_nifti(seg_path)
    return _volume_from_mask_simpson(data == label, spacing, "LA", seg_path, "4CH")


def calculate_ra_volume(seg_path: Path, label: int = FOUR_CH_LABELS["RA"]) -> float:
    data, spacing = _load_nifti(seg_path)
    return _volume_from_mask_simpson(data == label, spacing, "RA", seg_path, "4CH")


def calculate_lv_inner_diameter(seg_path: Path) -> float:
    _, _, spacing_xy, _, lv_slice, _, _ = _get_representative_sax_slices(seg_path)
    diameter, _ = _principal_axis_diameter(lv_slice, spacing_xy)
    return float(diameter)


def calculate_rv_inner_diameter(seg_path: Path) -> float:
    _, _, spacing_xy, _, _, rv_slice, _ = _get_representative_sax_slices(seg_path)
    diameter, _ = _principal_axis_diameter(rv_slice, spacing_xy)
    return float(diameter)


def calculate_ivs_thickness(seg_path: Path) -> float:
    _, _, spacing_xy, _, lv_slice, rv_slice, myo_slice = _get_representative_sax_slices(seg_path)
    thickness, _ = _septum_thickness(lv_slice, rv_slice, myo_slice, spacing_xy)
    return float(thickness)


def calculate_lvpw_thickness(seg_path: Path) -> float:
    _, _, spacing_xy, _, lv_slice, rv_slice, myo_slice = _get_representative_sax_slices(seg_path)
    thickness, _ = _posterior_wall_thickness(lv_slice, rv_slice, myo_slice, spacing_xy)
    return float(thickness)


def calculate_lvef(ed_volume_ml: float, es_volume_ml: float) -> float:
    if ed_volume_ml <= 1e-6:
        return 0.0
    stroke = calculate_stroke_volume(ed_volume_ml, es_volume_ml)
    return float(stroke / ed_volume_ml * 100.0)


def calculate_rvef(ed_volume_ml: float, es_volume_ml: float) -> float:
    if ed_volume_ml <= 1e-6:
        return 0.0
    stroke = calculate_stroke_volume(ed_volume_ml, es_volume_ml)
    return float(stroke / ed_volume_ml * 100.0)


def calculate_stroke_volume(ed_volume_ml: float, es_volume_ml: float) -> float:
    return float(max(ed_volume_ml - es_volume_ml, 0.0))


def calculate_relative_wall_thickness(
    lvpw_thickness_mm: float,
    lv_inner_diameter_mm: float,
) -> float:
    if lv_inner_diameter_mm <= 1e-6:
        return 0.0
    return float((2.0 * lvpw_thickness_mm) / lv_inner_diameter_mm)


def calculate_lv_sphericity_index(
    lv_volume_ml: float,
    lv_inner_diameter_mm: float,
) -> float:
    if lv_inner_diameter_mm <= 1e-6:
        return 0.0
    radius_mm = lv_inner_diameter_mm / 2.0
    sphere_volume_mm3 = (4.0 / 3.0) * math.pi * (radius_mm ** 3)
    sphere_volume_ml = sphere_volume_mm3 / 1000.0
    if sphere_volume_ml <= 1e-6:
        return 0.0
    return float(lv_volume_ml / sphere_volume_ml)


def calculate_lv_rv_volume_ratio(lv_volume_ml: float, rv_volume_ml: float) -> float:
    if rv_volume_ml <= 1e-6:
        return 0.0
    return float(lv_volume_ml / rv_volume_ml)

