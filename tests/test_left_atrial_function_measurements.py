import contextlib
import math
import unittest
from pathlib import Path

import numpy as np

from apps.api.models import RoleUpdateRequest
from apps.api.services import measurements
from apps.api.services.dicom_indexer import infer_role, orientation_label
from tests._unittest_compat import run_with_monkeypatch


def _rectangle_mask(rows, cols, top, left, height, width):
    mask = np.zeros((rows, cols), dtype=bool)
    mask[top : top + height, left : left + width] = True
    return mask


def _selected_la_frames(phase_shapes, *, rows=32, cols=32):
    image = np.zeros((rows, cols), dtype=np.float32)
    return {
        (slice_index, phase_index): (image, {"la": _rectangle_mask(rows, cols, *shape)})
        for slice_index, phase_index, shape in phase_shapes
    }


def _contour(points):
    return {
        "closed": True,
        "points": [{"x": x, "y": y} for x, y in points],
    }


def test_left_atrial_three_phase_area_length_and_emptying_fractions():
    selected = _selected_la_frames(
        [
            (0, 0, (2, 4, 12, 8)),
            (0, 1, (3, 5, 10, 7)),
            (0, 2, (4, 6, 8, 6)),
        ]
    )

    result = measurements._compute_left_atrial_function(
        selected,
        role="cine_lax_4ch",
        phase_labels={"la_max": 0, "la_pre_a": 1, "la_min": 2},
        total_phase_count=3,
        pixel_area=2.0,
        spacing_y=2.0,
        spacing_x=1.0,
        phase_times_ms={0: 0.0, 1: 40.0, 2: 80.0},
    )

    assert result is not None
    assert result["method"] == "single_plane_area_length_proxy"
    assert result["phase_selection"] == {
        "la_max": 0,
        "la_pre_a": 1,
        "la_min": 2,
        "sources": {
            "max": "saved_phase_label",
            "pre_a": "saved_phase_label",
            "min": "saved_phase_label",
        },
    }
    assert result["quality"]["status"] == "key_phases_complete"
    assert result["quality"]["full_cycle_complete"] is True
    assert result["quality"]["volume_order_valid"] is True
    assert result["curve"][1]["time_ms"] == 40.0

    by_phase = {item["phase_index"]: item for item in result["curve"]}
    assert by_phase[0]["long_axis_proxy_mm"] == 24.0
    for phase in (0, 1, 2):
        geometry = by_phase[phase]
        expected = 0.85 * geometry["area_mm2"] ** 2 / geometry["long_axis_proxy_mm"] / 1000.0
        assert math.isclose(geometry["volume_proxy_ml"], expected, abs_tol=1e-4)

    summary = result["summary"]
    expected_total = (summary["lav_max_ml"] - summary["lav_min_ml"]) / summary["lav_max_ml"] * 100.0
    expected_passive = (summary["lav_max_ml"] - summary["lav_pre_a_ml"]) / summary["lav_max_ml"] * 100.0
    expected_active = (summary["lav_pre_a_ml"] - summary["lav_min_ml"]) / summary["lav_pre_a_ml"] * 100.0
    assert math.isclose(summary["total_emptying_fraction_percent"], expected_total, abs_tol=1e-3)
    assert math.isclose(summary["passive_emptying_fraction_percent"], expected_passive, abs_tol=1e-3)
    assert math.isclose(summary["active_emptying_fraction_percent"], expected_active, abs_tol=1e-3)
    strain = result["strain_proxy"]
    strain_summary = strain["summary"]
    assert strain["reference_phase"] == 2
    assert strain["quality"]["status"] == "complete"
    assert strain_summary["reservoir_strain_proxy_percent"] > 0
    assert strain_summary["conduit_strain_proxy_percent"] > 0
    assert strain_summary["contractile_strain_proxy_percent"] > 0
    assert math.isclose(
        strain_summary["reservoir_strain_proxy_percent"],
        strain_summary["conduit_strain_proxy_percent"] + strain_summary["contractile_strain_proxy_percent"],
        abs_tol=1e-3,
    )


def test_left_atrial_two_phase_curve_derives_extrema_without_guessing_pre_a():
    selected = _selected_la_frames(
        [
            (0, 4, (2, 4, 12, 8)),
            (0, 9, (4, 6, 8, 6)),
        ]
    )

    result = measurements._compute_left_atrial_function(
        selected,
        role="cine_lax_4ch",
        phase_labels={},
        total_phase_count=20,
        pixel_area=1.0,
        spacing_y=1.0,
        spacing_x=1.0,
    )

    assert result is not None
    assert result["phase_selection"]["la_max"] == 4
    assert result["phase_selection"]["la_min"] == 9
    assert result["phase_selection"]["la_pre_a"] is None
    assert result["phase_selection"]["sources"]["max"] == "derived_from_annotated_la_curve"
    assert result["quality"]["status"] == "max_min_complete"
    assert result["quality"]["full_cycle_complete"] is False
    assert result["summary"]["total_emptying_fraction_percent"] is not None
    assert result["summary"]["passive_emptying_fraction_percent"] is None
    assert result["summary"]["active_emptying_fraction_percent"] is None


def test_left_atrial_single_plane_measurement_is_gated_to_4ch():
    selected = _selected_la_frames([(0, 0, (2, 4, 12, 8))])

    result = measurements._compute_left_atrial_function(
        selected,
        role="cine_sax",
        phase_labels={"la_max": 0},
        total_phase_count=1,
        pixel_area=1.0,
        spacing_y=1.0,
        spacing_x=1.0,
    )

    assert result is None


def test_left_atrial_single_plane_supports_2ch_and_biplane_lavi():
    four_ch = measurements._compute_left_atrial_function(
        _selected_la_frames([
            (0, 0, (2, 4, 12, 8)),
            (0, 1, (3, 5, 10, 7)),
            (0, 2, (4, 6, 8, 6)),
        ]),
        role="cine_lax_4ch",
        phase_labels={"la_max": 0, "la_pre_a": 1, "la_min": 2},
        total_phase_count=3,
        pixel_area=1.0,
        spacing_y=1.0,
        spacing_x=1.0,
    )
    two_ch = measurements._compute_left_atrial_function(
        _selected_la_frames([
            (0, 0, (2, 4, 11, 9)),
            (0, 1, (3, 5, 9, 8)),
            (0, 2, (4, 6, 7, 7)),
        ]),
        role="cine_lax_2ch",
        phase_labels={"la_max": 0, "la_pre_a": 1, "la_min": 2},
        total_phase_count=3,
        pixel_area=1.0,
        spacing_y=1.0,
        spacing_x=1.0,
    )
    indexing = measurements._left_atrial_indexing_settings(
        {"settings": {"left_atrial_function": {"bsa_m2": 2.0}}}
    )

    result = measurements._compute_biplane_left_atrial_function(
        four_ch,
        two_ch,
        four_ch_series_id=71,
        two_ch_series_id=72,
        indexing=indexing,
    )

    assert two_ch["role"] == "cine_lax_2ch"
    assert result["status"] == "key_phases_complete"
    assert result["source_series"] == {"cine_lax_4ch": 71, "cine_lax_2ch": 72}
    max_item = next(item for item in result["phase_measurements"] if item["phase_label"] == "la_max")
    expected_max = 0.85 * max_item["area_4ch_mm2"] * max_item["area_2ch_mm2"] / max_item["limiting_long_axis_mm"] / 1000.0
    assert math.isclose(max_item["volume_ml"], expected_max, abs_tol=1e-4)
    assert math.isclose(result["summary"]["lavi_max_ml_m2"], result["summary"]["lav_max_ml"] / 2.0, abs_tol=1e-4)
    assert result["summary"]["total_emptying_fraction_percent"] > 0


def test_left_atrial_biplane_reports_missing_2ch_and_bsa_validation():
    four_ch = measurements._compute_left_atrial_function(
        _selected_la_frames([(0, 0, (2, 4, 12, 8)), (0, 1, (4, 6, 8, 6))]),
        role="cine_lax_4ch",
        phase_labels={"la_max": 0, "la_min": 1},
        total_phase_count=2,
        pixel_area=1.0,
        spacing_y=1.0,
        spacing_x=1.0,
    )
    indexing = measurements._left_atrial_indexing_settings(
        {"settings": {"left_atrial_function": {"bsa_m2": 9.0}}}
    )

    result = measurements._compute_biplane_left_atrial_function(
        four_ch,
        None,
        four_ch_series_id=81,
        two_ch_series_id=None,
        indexing=indexing,
    )

    assert indexing == {"bsa_m2": None, "bsa_source": None, "status": "missing_bsa"}
    assert result["status"] == "missing_2ch"
    assert result["quality"]["missing"] == ["cine_lax_2ch_contours"]


def test_left_atrial_tracking_validation_includes_la(monkeypatch):
    image = np.zeros((24, 24), dtype=np.float32)
    la = _rectangle_mask(24, 24, 5, 6, 10, 8)
    selected = {
        (0, 0): (image, {"la": la}),
        (0, 1): (image, {"la": la}),
    }
    fake_field = {
        "flow": np.zeros((2, 24, 24), dtype=np.float32),
        "sample_coords": np.indices((24, 24), dtype=np.float32),
        "phase_shift_row_px": 0.0,
        "phase_shift_col_px": 0.0,
    }
    monkeypatch.setattr(measurements, "_prepare_tvl1_tracking", lambda *_args: fake_field)
    monkeypatch.setattr(
        measurements,
        "_warp_mask_with_tracking_field",
        lambda mask, _field: (mask.copy(), {"phase_shift_row_px": 0.0, "phase_shift_col_px": 0.0, "mean_flow_px": 0.0}),
    )

    result = measurements._compute_lv_tracking_validation(
        selected,
        role="cine_lax_4ch",
        spacing_y=1.0,
        spacing_x=1.0,
        eligible_frame_keys={(0, 0), (0, 1)},
    )

    assert result["pair_count"] == 1
    assert result["summary"]["la"]["mean_dice"] == 1.0
    assert result["pairs"][0]["regions"]["la"]["mean_boundary_distance_mm"] == 0.0


def test_2ch_3ch_roles_are_supported_without_reclassifying_unmarked_series():
    assert RoleUpdateRequest(role="cine_lax_2ch").role == "cine_lax_2ch"
    assert RoleUpdateRequest(role="cine_lax_3ch").role == "cine_lax_3ch"
    assert infer_role(Path("cine_2ch"), "CINE 2CH", 1, 25) == "cine_lax_2ch"
    assert infer_role(Path("cine_3ch"), "CINE 3CH", 1, 25) == "cine_lax_3ch"
    assert infer_role(Path("cine_long_axis"), "CINE LONG AXIS", 1, 25) == "unknown"
    assert orientation_label("", "cine_lax_2ch") == "LAX-2CH"
    assert orientation_label("", "cine_lax_3ch") == "LAX-3CH"


def test_biplane_series_lookup_uses_related_2ch_without_reading_pixels(monkeypatch):
    four_ch = measurements._compute_left_atrial_function(
        _selected_la_frames([(0, 0, (2, 4, 12, 8)), (0, 1, (4, 6, 8, 6))]),
        role="cine_lax_4ch",
        phase_labels={"la_max": 0, "la_min": 1},
        total_phase_count=2,
        pixel_area=1.0,
        spacing_y=1.0,
        spacing_x=1.0,
    )
    two_ch = measurements._compute_left_atrial_function(
        _selected_la_frames([(0, 0, (2, 4, 11, 9)), (0, 1, (4, 6, 7, 7))]),
        role="cine_lax_2ch",
        phase_labels={"la_max": 0, "la_min": 1},
        total_phase_count=2,
        pixel_area=1.0,
        spacing_y=1.0,
        spacing_x=1.0,
    )
    two_ch_series = {"id": 92, "role": "cine_lax_2ch"}

    class FakeResult:
        def fetchone(self):
            return two_ch_series

    class FakeConn:
        def execute(self, query, params=()):
            assert "role = 'cine_lax_2ch'" in query
            assert params == (19, 91)
            return FakeResult()

    @contextlib.contextmanager
    def fake_get_conn():
        yield FakeConn()

    monkeypatch.setattr(measurements, "get_conn", fake_get_conn)
    monkeypatch.setattr(measurements, "_load_left_atrial_function_for_series", lambda _series: (two_ch, {}))

    result = measurements._compute_left_atrial_biplane_for_series(
        {"id": 91, "study_id": 19, "role": "cine_lax_4ch"},
        {"settings": {"left_atrial_function": {"bsa_m2": 1.8}}},
        four_ch,
    )

    assert result["source_series"]["cine_lax_2ch"] == 92
    assert result["status"] == "max_min_complete"
    assert result["summary"]["lavi_max_ml_m2"] is not None


def test_saving_2ch_recomputes_related_4ch_measurement(monkeypatch):
    recomputed = []

    class FakeResult:
        def __init__(self, one=None, many=None):
            self.one = one
            self.many = many or []

        def fetchone(self):
            return self.one

        def fetchall(self):
            return self.many

    class FakeConn:
        def execute(self, query, params=()):
            if "SELECT id, study_id, role FROM series" in query:
                return FakeResult(one={"id": 101, "study_id": 29, "role": "cine_lax_2ch"})
            if "role = 'cine_lax_4ch'" in query:
                return FakeResult(many=[{"id": 102}])
            raise AssertionError(query)

    @contextlib.contextmanager
    def fake_get_conn():
        yield FakeConn()

    monkeypatch.setattr(measurements, "get_conn", fake_get_conn)
    monkeypatch.setattr(
        measurements,
        "recompute_function",
        lambda series_id: recomputed.append(series_id) or {"series_id": series_id},
    )

    result = measurements.recompute_measurements_for_module(101, "function")

    assert result == {"series_id": 101}
    assert recomputed == [101, 102]


def test_left_atrial_invalid_saved_phase_order_does_not_emit_negative_fractions():
    selected = _selected_la_frames(
        [
            (0, 0, (2, 4, 12, 8)),
            (0, 1, (4, 6, 8, 6)),
        ]
    )

    result = measurements._compute_left_atrial_function(
        selected,
        role="cine_lax_4ch",
        phase_labels={"la_max": 1, "la_min": 0},
        total_phase_count=2,
        pixel_area=1.0,
        spacing_y=1.0,
        spacing_x=1.0,
    )

    assert result is not None
    assert result["quality"]["status"] == "invalid_volume_order"
    assert result["quality"]["volume_order_valid"] is False
    assert "la_volume_order" in result["quality"]["missing"]
    assert result["summary"]["lav_max_ml"] < result["summary"]["lav_min_ml"]
    assert result["summary"]["total_emptying_volume_ml"] is None
    assert result["summary"]["total_emptying_fraction_percent"] is None


def test_recompute_function_exports_left_atrial_metrics(monkeypatch):
    series_id = 62
    contours = {
        "series_id": series_id,
        "module": "function",
        "settings": {},
        "phase_labels": {"la_max": 0, "la_pre_a": 1, "la_min": 2},
        "frames": {
            "0:0": {"include": True, "la": _contour([(4, 2), (12, 2), (12, 14), (4, 14)])},
            "0:1": {"include": True, "la": _contour([(5, 3), (12, 3), (12, 13), (5, 13)])},
            "0:2": {"include": True, "la": _contour([(6, 4), (12, 4), (12, 12), (6, 12)])},
        },
    }
    frame_rows = [
        {"id": phase + 1, "slice_index": 0, "phase_index": phase, "trigger_time": phase * 40.0}
        for phase in range(3)
    ]

    class FakeConn:
        def execute(self, query, params=()):
            if "SELECT * FROM series" in query:
                return self
            raise AssertionError(f"Unexpected query: {query}")

        def fetchone(self):
            return {
                "id": series_id,
                "role": "cine_lax_4ch",
                "rows": 24,
                "cols": 24,
                "pixel_spacing_x": 1.0,
                "pixel_spacing_y": 1.0,
                "slice_thickness": 8.0,
                "slice_count": 1,
                "phase_count": 3,
            }

    @contextlib.contextmanager
    def fake_get_conn():
        yield FakeConn()

    monkeypatch.setattr(measurements, "get_conn", fake_get_conn)
    monkeypatch.setattr(measurements, "_fetch_contours", lambda *_args: contours)
    monkeypatch.setattr(measurements, "list_frame_rows", lambda *_args: frame_rows)
    monkeypatch.setattr(measurements, "read_frame_pixels", lambda *_args: np.zeros((24, 24), dtype=np.float32))
    monkeypatch.setattr(measurements, "_save_measurement", lambda _series_id, _module, payload: payload)

    result = measurements.recompute_function(series_id)

    metrics = result["metrics"]
    atrial = result["research"]["left_atrial_function"]
    assert metrics["la_volume_method"] == "single_plane_area_length_proxy"
    assert metrics["la_max_phase"] == 0
    assert metrics["la_pre_a_phase"] == 1
    assert metrics["la_min_phase"] == 2
    assert metrics["la_lav_max_ml"] == atrial["summary"]["lav_max_ml"]
    assert metrics["la_total_emptying_fraction_percent"] > 0
    assert metrics["la_passive_emptying_fraction_percent"] > 0
    assert metrics["la_active_emptying_fraction_percent"] > 0
    assert metrics["la_full_cycle_complete"] is True


class LeftAtrialFunctionMeasurementTests(unittest.TestCase):
    def test_left_atrial_three_phase_area_length_and_emptying_fractions(self):
        test_left_atrial_three_phase_area_length_and_emptying_fractions()

    def test_left_atrial_two_phase_curve_derives_extrema_without_guessing_pre_a(self):
        test_left_atrial_two_phase_curve_derives_extrema_without_guessing_pre_a()

    def test_left_atrial_single_plane_measurement_is_gated_to_4ch(self):
        test_left_atrial_single_plane_measurement_is_gated_to_4ch()

    def test_left_atrial_single_plane_supports_2ch_and_biplane_lavi(self):
        test_left_atrial_single_plane_supports_2ch_and_biplane_lavi()

    def test_left_atrial_biplane_reports_missing_2ch_and_bsa_validation(self):
        test_left_atrial_biplane_reports_missing_2ch_and_bsa_validation()

    def test_left_atrial_tracking_validation_includes_la(self):
        run_with_monkeypatch(self, test_left_atrial_tracking_validation_includes_la)

    def test_2ch_3ch_roles_are_supported_without_reclassifying_unmarked_series(self):
        test_2ch_3ch_roles_are_supported_without_reclassifying_unmarked_series()

    def test_biplane_series_lookup_uses_related_2ch_without_reading_pixels(self):
        run_with_monkeypatch(self, test_biplane_series_lookup_uses_related_2ch_without_reading_pixels)

    def test_saving_2ch_recomputes_related_4ch_measurement(self):
        run_with_monkeypatch(self, test_saving_2ch_recomputes_related_4ch_measurement)

    def test_left_atrial_invalid_saved_phase_order_does_not_emit_negative_fractions(self):
        test_left_atrial_invalid_saved_phase_order_does_not_emit_negative_fractions()

    def test_recompute_function_exports_left_atrial_metrics(self):
        run_with_monkeypatch(self, test_recompute_function_exports_left_atrial_metrics)
