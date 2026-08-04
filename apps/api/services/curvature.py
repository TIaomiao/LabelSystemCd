from __future__ import annotations

import math
from typing import Any, Iterable


ALGORITHM_VERSION = "ivs_fw_three_point_signed_v1"
LANDMARK_KEYS = ("j1", "j2", "m1", "m2")
_MIN_DISTANCE_MM = 1e-6
_FLATNESS_TOLERANCE = 1e-6
_PROJECTION_TOLERANCE = 1e-6


def _round_float(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    value = float(value)
    if not math.isfinite(value):
        return None
    return round(value, digits)


def _point_xy_mm(point: Any, spacing_x: float, spacing_y: float) -> tuple[float, float] | None:
    if not isinstance(point, dict):
        return None
    try:
        x = float(point["x"])
        y = float(point["y"])
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(x) or not math.isfinite(y):
        return None
    physical_x = x * spacing_x
    physical_y = y * spacing_y
    if not math.isfinite(physical_x) or not math.isfinite(physical_y):
        return None
    return physical_x, physical_y


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _cross(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _projection_fraction(
    start: tuple[float, float],
    end: tuple[float, float],
    point: tuple[float, float],
) -> float | None:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= _MIN_DISTANCE_MM * _MIN_DISTANCE_MM:
        return None
    return ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared


def _invalid_arc(reason: str) -> dict[str, Any]:
    return {
        "status": "invalid",
        "radius_mm": None,
        "curvature_magnitude_mm_inv": None,
        "circle_center_mm": None,
        "qc_reasons": [reason],
    }


def three_point_arc_geometry(
    junction_1: tuple[float, float],
    junction_2: tuple[float, float],
    midpoint: tuple[float, float],
) -> dict[str, Any]:
    """Return unsigned three-point circle geometry without emitting NaN or infinity."""
    try:
        chord = _distance(junction_1, junction_2)
        side_1 = _distance(junction_1, midpoint)
        side_2 = _distance(junction_2, midpoint)
    except (OverflowError, ValueError):
        return _invalid_arc("non_finite_geometry")
    if not all(math.isfinite(value) for value in (chord, side_1, side_2)):
        return _invalid_arc("non_finite_geometry")
    if min(chord, side_1, side_2) <= _MIN_DISTANCE_MM:
        return _invalid_arc("duplicate_or_coincident_points")

    try:
        area_twice = _cross(junction_1, junction_2, midpoint)
        longest = max(chord, side_1, side_2)
        scale = longest * longest
    except (OverflowError, ValueError):
        return _invalid_arc("non_finite_geometry")
    if not math.isfinite(area_twice) or not math.isfinite(scale) or scale <= 0:
        return _invalid_arc("non_finite_geometry")
    normalized_area = abs(area_twice) / scale if scale > 0 else 0.0
    projection = _projection_fraction(junction_1, junction_2, midpoint)
    if projection is None or not math.isfinite(projection):
        return _invalid_arc("invalid_midpoint_projection")
    if not (-_PROJECTION_TOLERANCE <= projection <= 1.0 + _PROJECTION_TOLERANCE):
        return _invalid_arc("midpoint_outside_junction_chord")

    if normalized_area <= _FLATNESS_TOLERANCE:
        return {
            "status": "flat",
            "radius_mm": None,
            "curvature_magnitude_mm_inv": 0.0,
            "circle_center_mm": None,
            "qc_reasons": ["flat_arc"],
        }

    curvature = (2.0 * abs(area_twice)) / (chord * side_1 * side_2)
    if not math.isfinite(curvature) or curvature <= 0:
        return _invalid_arc("unstable_curvature_geometry")

    ax, ay = junction_1
    bx, by = junction_2
    cx, cy = midpoint
    denominator = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(denominator) <= _MIN_DISTANCE_MM:
        return _invalid_arc("unstable_circle_center")
    center_x = (
        (ax * ax + ay * ay) * (by - cy)
        + (bx * bx + by * by) * (cy - ay)
        + (cx * cx + cy * cy) * (ay - by)
    ) / denominator
    center_y = (
        (ax * ax + ay * ay) * (cx - bx)
        + (bx * bx + by * by) * (ax - cx)
        + (cx * cx + cy * cy) * (bx - ax)
    ) / denominator
    radius = 1.0 / curvature
    if not all(math.isfinite(value) for value in (center_x, center_y, radius)):
        return _invalid_arc("unstable_circle_geometry")

    return {
        "status": "valid",
        "radius_mm": _round_float(radius),
        "curvature_magnitude_mm_inv": _round_float(curvature, 12),
        "circle_center_mm": [_round_float(center_x), _round_float(center_y)],
        "qc_reasons": [],
    }


def _side_relation(
    junction_1: tuple[float, float],
    junction_2: tuple[float, float],
    septal_midpoint: tuple[float, float],
    free_wall_midpoint: tuple[float, float],
) -> str:
    try:
        septal_side = _cross(junction_1, junction_2, septal_midpoint)
        free_wall_side = _cross(junction_1, junction_2, free_wall_midpoint)
        chord = _distance(junction_1, junction_2)
        tolerance = max(chord * chord * _FLATNESS_TOLERANCE, _MIN_DISTANCE_MM)
    except (OverflowError, ValueError):
        return "indeterminate"
    if not all(math.isfinite(value) for value in (septal_side, free_wall_side, chord, tolerance)):
        return "indeterminate"
    if abs(septal_side) <= tolerance:
        return "septal_midpoint_on_reference_chord"
    if abs(free_wall_side) <= tolerance:
        return "free_wall_midpoint_on_reference_chord"
    return "opposite_sides" if (septal_side < 0) != (free_wall_side < 0) else "same_side"


def _base_result(raw: dict[str, Any], *, series_role: str) -> dict[str, Any]:
    slice_index = raw.get("slice_index")
    phase_index = raw.get("phase_index")
    safe_slice_index = slice_index if isinstance(slice_index, int) and not isinstance(slice_index, bool) and slice_index >= 0 else None
    safe_phase_index = phase_index if isinstance(phase_index, int) and not isinstance(phase_index, bool) and phase_index >= 0 else None
    return {
        "status": "incomplete",
        "qc_status": "pending",
        "qc_reasons": [],
        "curvature_ratio_magnitude": None,
        "curvature_ratio_rc": None,
        "clinical_grade": False,
        "method": str(raw.get("method") or "manual_four_point"),
        "algorithm_version": ALGORITHM_VERSION,
        "confirmation_status": "draft",
        "series_role": str(series_role or "unknown"),
        "slice_index": safe_slice_index,
        "phase_index": safe_phase_index,
        "signed": True,
        "sign_convention_status": "confirmed_reverse_bowing_negative",
        "sign_basis": "m1_m2_relative_to_j1_j2_chord",
        "septal_shape": None,
        "signed_curvature_ratio": None,
    }


def compute_curvature_from_landmarks(
    raw: dict[str, Any] | None,
    *,
    spacing_x: float,
    spacing_y: float,
    series_role: str,
    available_frame_keys: Iterable[tuple[int, int]] | None = None,
    image_rows: int | None = None,
    image_cols: int | None = None,
    spacing_provenance: str = "unspecified",
) -> dict[str, Any] | None:
    """Compute paper-compatible geometry with reverse septal bowing reported as negative."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return {
            "status": "invalid",
            "qc_status": "fail",
            "qc_reasons": ["curvature_landmarks_must_be_an_object"],
            "curvature_ratio_magnitude": None,
            "curvature_ratio_rc": None,
            "clinical_grade": False,
            "algorithm_version": ALGORITHM_VERSION,
            "signed": True,
            "sign_convention_status": "confirmed_reverse_bowing_negative",
            "sign_basis": "m1_m2_relative_to_j1_j2_chord",
            "septal_shape": None,
            "signed_curvature_ratio": None,
        }

    result = _base_result(raw, series_role=series_role)
    result["pixel_spacing_provenance"] = str(spacing_provenance or "unspecified")
    if series_role != "cine_sax":
        result.update(status="invalid", qc_status="fail", qc_reasons=["curvature_requires_cine_sax"])
        return result

    try:
        spacing_x = float(spacing_x)
        spacing_y = float(spacing_y)
    except (TypeError, ValueError):
        spacing_x = spacing_y = float("nan")
    if not all(math.isfinite(value) and value > 0 for value in (spacing_x, spacing_y)):
        result.update(status="invalid", qc_status="fail", qc_reasons=["invalid_pixel_spacing"])
        return result

    slice_index = raw.get("slice_index")
    phase_index = raw.get("phase_index")
    if not isinstance(slice_index, int) or isinstance(slice_index, bool) or slice_index < 0:
        result.update(status="incomplete", qc_status="pending", qc_reasons=["missing_or_invalid_slice_index"])
        return result
    if not isinstance(phase_index, int) or isinstance(phase_index, bool) or phase_index < 0:
        result.update(status="incomplete", qc_status="pending", qc_reasons=["missing_or_invalid_phase_index"])
        return result

    if available_frame_keys is not None and (slice_index, phase_index) not in set(available_frame_keys):
        result.update(status="invalid", qc_status="fail", qc_reasons=["selected_frame_not_found"])
        return result

    missing = [key for key in LANDMARK_KEYS if raw.get(key) is None]
    if missing:
        result.update(
            status="incomplete",
            qc_status="pending",
            qc_reasons=[f"missing_landmarks:{','.join(missing)}"],
        )
        return result

    landmarks_mm: dict[str, tuple[float, float]] = {}
    for key in LANDMARK_KEYS:
        raw_point = raw.get(key)
        if (
            isinstance(raw_point, dict)
            and isinstance(image_rows, int)
            and image_rows > 0
            and isinstance(image_cols, int)
            and image_cols > 0
        ):
            try:
                pixel_x = float(raw_point["x"])
                pixel_y = float(raw_point["y"])
            except (KeyError, TypeError, ValueError):
                pixel_x = pixel_y = float("nan")
            if not (0.0 <= pixel_x <= image_cols - 1 and 0.0 <= pixel_y <= image_rows - 1):
                result.update(status="invalid", qc_status="fail", qc_reasons=[f"landmark_out_of_bounds:{key}"])
                return result
        point_mm = _point_xy_mm(raw.get(key), spacing_x, spacing_y)
        if point_mm is None:
            result.update(status="invalid", qc_status="fail", qc_reasons=[f"invalid_landmark:{key}"])
            return result
        landmarks_mm[key] = point_mm

    ivs = three_point_arc_geometry(landmarks_mm["j1"], landmarks_mm["j2"], landmarks_mm["m1"])
    free_wall = three_point_arc_geometry(landmarks_mm["j1"], landmarks_mm["j2"], landmarks_mm["m2"])
    result.update({
        "pixel_spacing_mm": {"x": _round_float(spacing_x), "y": _round_float(spacing_y)},
        "landmarks_pixel": {
            key: {"x": float(raw[key]["x"]), "y": float(raw[key]["y"])}
            for key in LANDMARK_KEYS
        },
        "landmarks_mm": {
            key: {"x": _round_float(point[0]), "y": _round_float(point[1])}
            for key, point in landmarks_mm.items()
        },
        "ivs": ivs,
        "free_wall": free_wall,
        "midpoint_side_relation": _side_relation(
            landmarks_mm["j1"],
            landmarks_mm["j2"],
            landmarks_mm["m1"],
            landmarks_mm["m2"],
        ),
    })

    if _distance(landmarks_mm["m1"], landmarks_mm["m2"]) <= _MIN_DISTANCE_MM:
        result.update(
            status="invalid",
            qc_status="fail",
            qc_reasons=["septal_and_free_wall_midpoints_coincident"],
        )
        return result

    invalid_reasons = [f"ivs:{reason}" for reason in ivs["qc_reasons"] if ivs["status"] == "invalid"]
    invalid_reasons.extend(
        f"free_wall:{reason}" for reason in free_wall["qc_reasons"] if free_wall["status"] != "valid"
    )
    if invalid_reasons:
        result.update(status="invalid", qc_status="fail", qc_reasons=invalid_reasons)
        return result

    try:
        chord_length = _distance(landmarks_mm["j1"], landmarks_mm["j2"])
        ivs_curvature = (
            0.0
            if ivs["status"] == "flat"
            else (2.0 * abs(_cross(landmarks_mm["j1"], landmarks_mm["j2"], landmarks_mm["m1"])))
            / (
                chord_length
                * _distance(landmarks_mm["j1"], landmarks_mm["m1"])
                * _distance(landmarks_mm["j2"], landmarks_mm["m1"])
            )
        )
        free_wall_curvature = (
            2.0 * abs(_cross(landmarks_mm["j1"], landmarks_mm["j2"], landmarks_mm["m2"]))
        ) / (
            chord_length
            * _distance(landmarks_mm["j1"], landmarks_mm["m2"])
            * _distance(landmarks_mm["j2"], landmarks_mm["m2"])
        )
    except (OverflowError, ValueError, ZeroDivisionError):
        result.update(status="invalid", qc_status="fail", qc_reasons=["non_finite_result"])
        return result
    if not all(math.isfinite(value) for value in (ivs_curvature, free_wall_curvature)):
        result.update(status="invalid", qc_status="fail", qc_reasons=["non_finite_result"])
        return result
    if free_wall_curvature <= 0:
        result.update(status="invalid", qc_status="fail", qc_reasons=["free_wall_curvature_must_be_positive"])
        return result

    side_relation = result.get("midpoint_side_relation")
    if ivs["status"] == "flat":
        sign = 0.0
        septal_shape = "flat"
    elif side_relation == "opposite_sides":
        sign = 1.0
        septal_shape = "non_inverted"
    elif side_relation == "same_side":
        sign = -1.0
        septal_shape = "inverted"
    else:
        result.update(status="invalid", qc_status="fail", qc_reasons=["signed_shape_indeterminate"])
        return result

    ratio_magnitude = ivs_curvature / free_wall_curvature
    signed_ratio = 0.0 if sign == 0 else sign * ratio_magnitude
    signed_ivs_curvature = 0.0 if sign == 0 else sign * ivs_curvature
    ivs["signed_curvature_mm_inv"] = _round_float(signed_ivs_curvature, 12)
    warnings = [f"ivs:{reason}" for reason in ivs["qc_reasons"]]
    if "unverified" in str(spacing_provenance or "").lower():
        warnings.append("pixel_spacing_provenance_unverified")
    result.update(
        status="valid",
        qc_status="warning" if warnings else "pass",
        qc_reasons=warnings,
        septal_shape=septal_shape,
        curvature_ratio_magnitude=_round_float(ratio_magnitude, 12),
        curvature_ratio_rc=_round_float(signed_ratio, 12),
        signed_curvature_ratio=_round_float(signed_ratio, 12),
    )
    return result
