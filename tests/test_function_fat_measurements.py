import contextlib
import unittest

import numpy as np

from apps.api.services import measurements
from _unittest_compat import run_with_monkeypatch


def _contour(points):
    return {
        "closed": True,
        "points": [{"x": x, "y": y} for x, y in points],
    }


def _install_measurement_fakes(monkeypatch, contours, *, frame_rows=None, rows=12, cols=12, role="cine_sax"):
    series_id = contours["series_id"]

    class FakeConn:
        def execute(self, query, params=()):
            if "SELECT * FROM series" in query:
                return self
            raise AssertionError(f"Unexpected query: {query}")

        def fetchone(self):
            return {
                "id": series_id,
                "role": role,
                "rows": rows,
                "cols": cols,
                "pixel_spacing_x": 1.0,
                "pixel_spacing_y": 1.0,
                "slice_thickness": 10.0,
                "slice_count": 1,
            }

    @contextlib.contextmanager
    def fake_get_conn():
        yield FakeConn()

    monkeypatch.setattr(measurements, "get_conn", fake_get_conn)
    monkeypatch.setattr(measurements, "_fetch_contours", lambda _series_id, _module: contours)
    if frame_rows is None:
        frame_rows = [{"id": 1, "slice_index": 0, "phase_index": 0}]
    monkeypatch.setattr(measurements, "list_frame_rows", lambda _series_id: frame_rows)
    monkeypatch.setattr(measurements, "read_frame_pixels", lambda _frame: np.zeros((rows, cols), dtype=np.float32))
    monkeypatch.setattr(measurements, "_save_measurement", lambda _series_id, _module, payload: payload)


def test_function_fat_exclude_subtracts_from_legacy_fat_roi(monkeypatch):
    series_id = 42
    contours = {
        "series_id": series_id,
        "module": "function",
        "settings": {},
        "phase_labels": {},
        "frames": {
            "0:0": {
                "include": True,
                "endo": _contour([(5, 5), (6, 5), (6, 6), (5, 6)]),
                "epi": _contour([(4, 4), (7, 4), (7, 7), (4, 7)]),
                "fat": _contour([(1, 1), (10, 1), (10, 10), (1, 10)]),
                "exclude": _contour([(4, 4), (6, 4), (6, 6), (4, 6)]),
            }
        },
    }
    _install_measurement_fakes(monkeypatch, contours)

    result = measurements.recompute_function(series_id)

    masks = measurements._frame_masks(contours["frames"]["0:0"], 12, 12)
    expected_fat = masks["fat"] & ~masks["exclude"]
    expected_exclude = masks["fat"] & masks["exclude"]
    assert result["per_slice"][0]["fat_measurement_method"] == "legacy_fat_roi"
    assert result["per_slice"][0]["fat_volume_ml"] == round(float(expected_fat.sum()) * 0.01, 2)
    assert result["per_slice"][0]["fat_exclude_volume_ml"] == round(float(expected_exclude.sum()) * 0.01, 2)
    assert result["metrics"]["epicardial_fat_volume_ml"] == round(float(expected_fat.sum()) * 0.01, 4)
    assert result["metrics"]["epicardial_fat_ed_volume_ml"] == round(float(expected_fat.sum()) * 0.01, 4)
    assert result["metrics"]["epicardial_fat_all_frames_volume_ml"] == round(float(expected_fat.sum()) * 0.01, 4)
    assert result["metrics"]["epicardial_fat_exclude_volume_ml"] == round(float(expected_exclude.sum()) * 0.01, 4)
    assert result["metrics"]["epicardial_fat_exclude_ed_volume_ml"] == round(float(expected_exclude.sum()) * 0.01, 4)
    assert result["metrics"]["epicardial_fat_exclude_all_frames_volume_ml"] == round(float(expected_exclude.sum()) * 0.01, 4)


def test_function_fat_exclude_regions_are_union_mask(monkeypatch):
    series_id = 45
    contours = {
        "series_id": series_id,
        "module": "function",
        "settings": {},
        "phase_labels": {},
        "frames": {
            "0:0": {
                "include": True,
                "endo": _contour([(5, 5), (6, 5), (6, 6), (5, 6)]),
                "epi": _contour([(4, 4), (7, 4), (7, 7), (4, 7)]),
                "fat": _contour([(1, 1), (10, 1), (10, 10), (1, 10)]),
                "exclude": None,
                "exclude_regions": [
                    _contour([(2, 2), (4, 2), (4, 4), (2, 4)]),
                    _contour([(7, 7), (9, 7), (9, 9), (7, 9)]),
                ],
            }
        },
    }
    _install_measurement_fakes(monkeypatch, contours)

    result = measurements.recompute_function(series_id)

    masks = measurements._frame_masks(contours["frames"]["0:0"], 12, 12)
    legacy_only = measurements._polygon_to_mask(contours["frames"]["0:0"]["exclude"], 12, 12)
    expected_fat = masks["fat"] & ~masks["exclude"]
    expected_exclude = masks["fat"] & masks["exclude"]
    assert int(legacy_only.sum()) == 0
    assert int(expected_exclude.sum()) > 0
    assert result["per_slice"][0]["fat_volume_ml"] == round(float(expected_fat.sum()) * 0.01, 2)
    assert result["per_slice"][0]["fat_exclude_volume_ml"] == round(float(expected_exclude.sum()) * 0.01, 2)
    assert result["metrics"]["epicardial_fat_exclude_volume_ml"] == round(float(expected_exclude.sum()) * 0.01, 4)


def test_function_fat_outer_uses_annulus_minus_epi_and_exclude(monkeypatch):
    series_id = 43
    contours = {
        "series_id": series_id,
        "module": "function",
        "settings": {},
        "phase_labels": {},
        "frames": {
            "0:0": {
                "include": True,
                "endo": _contour([(5, 5), (6, 5), (6, 6), (5, 6)]),
                "epi": _contour([(4, 4), (8, 4), (8, 8), (4, 8)]),
                "fat_outer": _contour([(1, 1), (10, 1), (10, 10), (1, 10)]),
                "exclude": _contour([(8, 8), (10, 8), (10, 10), (8, 10)]),
            }
        },
    }
    _install_measurement_fakes(monkeypatch, contours)

    result = measurements.recompute_function(series_id)

    masks = measurements._frame_masks(contours["frames"]["0:0"], 12, 12)
    raw_annulus = masks["fat_outer"] & ~masks["epi"]
    expected_fat = raw_annulus & ~masks["exclude"]
    expected_exclude = raw_annulus & masks["exclude"]
    assert result["per_slice"][0]["fat_measurement_method"] == "fat_outer_minus_epi"
    assert result["per_slice"][0]["fat_source_contours"] == ["fat_outer", "epi", "exclude"]
    assert result["per_slice"][0]["fat_volume_ml"] == round(float(expected_fat.sum()) * 0.01, 2)
    assert result["per_slice"][0]["fat_exclude_volume_ml"] == round(float(expected_exclude.sum()) * 0.01, 2)
    assert result["metrics"]["epicardial_fat_volume_ml"] == round(float(expected_fat.sum()) * 0.01, 4)
    assert result["metrics"]["epicardial_fat_ed_volume_ml"] == round(float(expected_fat.sum()) * 0.01, 4)
    assert result["metrics"]["epicardial_fat_all_frames_volume_ml"] == round(float(expected_fat.sum()) * 0.01, 4)
    assert result["metrics"]["epicardial_fat_exclude_volume_ml"] == round(float(expected_exclude.sum()) * 0.01, 4)
    assert result["metrics"]["epicardial_fat_exclude_ed_volume_ml"] == round(float(expected_exclude.sum()) * 0.01, 4)
    assert result["metrics"]["epicardial_fat_exclude_all_frames_volume_ml"] == round(float(expected_exclude.sum()) * 0.01, 4)


def test_function_fat_outer_prefers_ventricular_epi_over_epi(monkeypatch):
    series_id = 44
    contours = {
        "series_id": series_id,
        "module": "function",
        "settings": {},
        "phase_labels": {},
        "frames": {
            "0:0": {
                "include": True,
                "endo": _contour([(5, 5), (6, 5), (6, 6), (5, 6)]),
                "epi": _contour([(5, 5), (7, 5), (7, 7), (5, 7)]),
                "ventricular_epi": _contour([(3, 3), (8, 3), (8, 8), (3, 8)]),
                "fat_outer": _contour([(1, 1), (10, 1), (10, 10), (1, 10)]),
                "exclude": _contour([(8, 8), (10, 8), (10, 10), (8, 10)]),
            }
        },
    }
    _install_measurement_fakes(monkeypatch, contours)

    result = measurements.recompute_function(series_id)

    masks = measurements._frame_masks(contours["frames"]["0:0"], 12, 12)
    expected_raw = masks["fat_outer"] & ~masks["ventricular_epi"]
    old_epi_raw = masks["fat_outer"] & ~masks["epi"]
    expected_fat = expected_raw & ~masks["exclude"]
    expected_exclude = expected_raw & masks["exclude"]
    assert int(expected_raw.sum()) != int(old_epi_raw.sum())
    assert result["per_slice"][0]["fat_measurement_method"] == "fat_outer_minus_ventricular_epi"
    assert result["per_slice"][0]["fat_source_contours"] == ["fat_outer", "ventricular_epi", "exclude"]
    assert result["per_slice"][0]["fat_volume_ml"] == round(float(expected_fat.sum()) * 0.01, 2)
    assert result["per_slice"][0]["fat_exclude_volume_ml"] == round(float(expected_exclude.sum()) * 0.01, 2)
    assert result["metrics"]["epicardial_fat_volume_ml"] == round(float(expected_fat.sum()) * 0.01, 4)
    assert result["metrics"]["epicardial_fat_exclude_volume_ml"] == round(float(expected_exclude.sum()) * 0.01, 4)


def test_function_sax_outputs_experimental_2d_gcs_and_grs_proxy(monkeypatch):
    series_id = 46
    contours = {
        "series_id": series_id,
        "module": "function",
        "settings": {},
        "phase_labels": {"ed": 0, "es": 1},
        "frames": {
            "0:0": {
                "include": True,
                "endo": _contour([(5, 5), (14, 5), (14, 14), (5, 14)]),
                "epi": _contour([(3, 3), (16, 3), (16, 16), (3, 16)]),
            },
            "0:1": {
                "include": True,
                "endo": _contour([(7, 7), (12, 7), (12, 12), (7, 12)]),
                "epi": _contour([(3, 3), (16, 3), (16, 16), (3, 16)]),
            },
        },
    }
    _install_measurement_fakes(
        monkeypatch,
        contours,
        rows=24,
        cols=24,
        role="cine_sax",
        frame_rows=[
            {"id": 1, "slice_index": 0, "phase_index": 0, "trigger_time": 0.0},
            {"id": 2, "slice_index": 0, "phase_index": 1, "trigger_time": 40.0},
        ],
    )

    result = measurements.recompute_function(series_id)

    metrics = result["metrics"]
    assert metrics["lv_2d_strain_proxy_method"] == "experimental_2d_geometry_proxy"
    assert metrics["lv_2d_strain_proxy_clinical_grade"] is False
    assert metrics["lv_2d_gcs_proxy_es_percent"] < 0
    assert metrics["lv_2d_grs_proxy_es_percent"] > 0
    assert metrics["lv_2d_gls_proxy_es_percent"] is None
    strain_proxy = result["research"]["strain_proxy"]
    assert strain_proxy["role"] == "cine_sax"
    assert len(strain_proxy["curve"]) == 2
    assert strain_proxy["curve"][1]["time_ms"] == 40.0
    tracking_validation = result["research"]["tracking_validation"]
    assert tracking_validation["method"] == "on_demand_tracking_preview"
    assert tracking_validation["status"] == "not_run"
    assert tracking_validation["clinical_grade"] is False
    assert tracking_validation["pair_count"] is None


def test_function_4ch_outputs_experimental_2d_gls_proxy(monkeypatch):
    series_id = 47
    contours = {
        "series_id": series_id,
        "module": "function",
        "settings": {},
        "phase_labels": {"lv_ed": 0, "lv_es": 1},
        "frames": {
            "0:0": {
                "include": True,
                "endo": _contour([(9, 3), (14, 3), (14, 22), (9, 22)]),
                "epi": _contour([(7, 2), (16, 2), (16, 23), (7, 23)]),
            },
            "0:1": {
                "include": True,
                "endo": _contour([(9, 6), (14, 6), (14, 18), (9, 18)]),
                "epi": _contour([(7, 4), (16, 4), (16, 20), (7, 20)]),
            },
        },
    }
    _install_measurement_fakes(
        monkeypatch,
        contours,
        rows=28,
        cols=28,
        role="cine_lax_4ch",
        frame_rows=[
            {"id": 1, "slice_index": 0, "phase_index": 0, "trigger_time": 0.0},
            {"id": 2, "slice_index": 0, "phase_index": 1, "trigger_time": 35.0},
        ],
    )

    result = measurements.recompute_function(series_id)

    metrics = result["metrics"]
    assert metrics["lv_2d_strain_proxy_ed_phase"] == 0
    assert metrics["lv_2d_strain_proxy_es_phase"] == 1
    assert metrics["lv_2d_gls_proxy_es_percent"] < 0
    assert metrics["lv_2d_gcs_proxy_es_percent"] is None
    assert metrics["lv_2d_grs_proxy_es_percent"] is None
    strain_proxy = result["research"]["strain_proxy"]
    assert strain_proxy["role"] == "cine_lax_4ch"
    assert len(strain_proxy["curve"]) == 2
    tracking_validation = result["research"]["tracking_validation"]
    assert tracking_validation["role"] == "cine_lax_4ch"
    assert tracking_validation["status"] == "not_run"
    assert tracking_validation["pair_count"] is None


def test_tracking_preview_uses_current_4ch_series_without_persisting(monkeypatch):
    series_id = 48
    contours = {
        "series_id": series_id,
        "module": "function",
        "settings": {},
        "phase_labels": {"lv_ed": 0, "lv_es": 1},
        "frame_meta": {
            "0:0": {"origin": "manual"},
            "0:1": {"origin": "manual_refine"},
        },
        "frames": {
            "0:0": {
                "include": True,
                "endo": _contour([(9, 3), (14, 3), (14, 22), (9, 22)]),
                "epi": _contour([(7, 2), (16, 2), (16, 23), (7, 23)]),
            },
            "0:1": {
                "include": True,
                "endo": _contour([(9, 6), (14, 6), (14, 18), (9, 18)]),
                "epi": _contour([(7, 4), (16, 4), (16, 20), (7, 20)]),
            },
        },
    }
    _install_measurement_fakes(
        monkeypatch,
        contours,
        rows=28,
        cols=28,
        role="cine_lax_4ch",
        frame_rows=[
            {"id": 1, "slice_index": 0, "phase_index": 0, "trigger_time": 0.0},
            {"id": 2, "slice_index": 0, "phase_index": 1, "trigger_time": 35.0},
        ],
    )
    monkeypatch.setattr(
        measurements,
        "_save_measurement",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("preview must not persist")),
    )

    result = measurements.compute_lv_tracking_preview(series_id)

    assert result["module"] == "tracking_preview"
    assert result["series_id"] == series_id
    assert result["persisted"] is False
    assert result["research"]["strain_proxy"]["summary"]["gls_peak_percent"] < 0
    assert result["research"]["tracking_validation"]["pair_count"] == 1


def test_tracking_preview_ignores_nonadjacent_manual_phases(monkeypatch):
    series_id = 49
    contours = {
        "series_id": series_id,
        "module": "function",
        "settings": {},
        "phase_labels": {"lv_ed": 0, "lv_es": 2},
        "frame_meta": {
            "0:0": {"origin": "manual"},
            "0:2": {"origin": "manual"},
        },
        "frames": {
            "0:0": {
                "include": True,
                "endo": _contour([(9, 3), (14, 3), (14, 22), (9, 22)]),
                "epi": _contour([(7, 2), (16, 2), (16, 23), (7, 23)]),
            },
            "0:2": {
                "include": True,
                "endo": _contour([(9, 6), (14, 6), (14, 18), (9, 18)]),
                "epi": _contour([(7, 4), (16, 4), (16, 20), (7, 20)]),
            },
        },
    }
    _install_measurement_fakes(
        monkeypatch,
        contours,
        rows=28,
        cols=28,
        role="cine_lax_4ch",
        frame_rows=[
            {"id": 1, "slice_index": 0, "phase_index": 0, "trigger_time": 0.0},
            {"id": 2, "slice_index": 0, "phase_index": 2, "trigger_time": 70.0},
        ],
    )
    monkeypatch.setattr(
        measurements,
        "_prepare_tvl1_tracking",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("nonadjacent phases must not run optical flow")),
    )

    result = measurements.compute_lv_tracking_preview(series_id)

    tracking = result["research"]["tracking_validation"]
    assert tracking["status"] == "completed"
    assert tracking["candidate_pair_count"] == 0
    assert tracking["pair_count"] == 0


def test_tracking_reuses_one_flow_field_for_all_regions(monkeypatch):
    image = np.zeros((20, 20), dtype=np.float32)
    endo = np.zeros((20, 20), dtype=bool)
    epi = np.zeros((20, 20), dtype=bool)
    endo[7:13, 7:13] = True
    epi[5:15, 5:15] = True
    myocardium = epi & ~endo
    selected = {
        (0, 0): (image, {"endo": endo, "epi": epi, "myocardium": myocardium}),
        (0, 1): (image, {"endo": endo, "epi": epi, "myocardium": myocardium}),
    }
    prepared = []
    warped = []
    fake_field = {
        "flow": np.zeros((2, 20, 20), dtype=np.float32),
        "sample_coords": np.indices((20, 20), dtype=np.float32),
        "phase_shift_row_px": 0.0,
        "phase_shift_col_px": 0.0,
    }

    def fake_prepare(*_args):
        prepared.append(True)
        return fake_field

    def fake_warp(mask, field):
        assert field is fake_field
        warped.append(True)
        return mask.copy(), {
            "phase_shift_row_px": 0.0,
            "phase_shift_col_px": 0.0,
            "mean_flow_px": 0.0,
        }

    monkeypatch.setattr(measurements, "_prepare_tvl1_tracking", fake_prepare)
    monkeypatch.setattr(measurements, "_warp_mask_with_tracking_field", fake_warp)

    result = measurements._compute_lv_tracking_validation(
        selected,
        role="cine_lax_4ch",
        spacing_y=1.0,
        spacing_x=1.0,
        eligible_frame_keys={(0, 0), (0, 1)},
    )

    assert result["pair_count"] == 1
    assert len(prepared) == 1
    assert len(warped) == 3


class FunctionFatMeasurementTests(unittest.TestCase):
    def test_function_fat_exclude_subtracts_from_legacy_fat_roi(self):
        run_with_monkeypatch(self, test_function_fat_exclude_subtracts_from_legacy_fat_roi)

    def test_function_fat_exclude_regions_are_union_mask(self):
        run_with_monkeypatch(self, test_function_fat_exclude_regions_are_union_mask)

    def test_function_fat_outer_uses_annulus_minus_epi_and_exclude(self):
        run_with_monkeypatch(self, test_function_fat_outer_uses_annulus_minus_epi_and_exclude)

    def test_function_fat_outer_prefers_ventricular_epi_over_epi(self):
        run_with_monkeypatch(self, test_function_fat_outer_prefers_ventricular_epi_over_epi)

    def test_function_sax_outputs_experimental_2d_gcs_and_grs_proxy(self):
        run_with_monkeypatch(self, test_function_sax_outputs_experimental_2d_gcs_and_grs_proxy)

    def test_function_4ch_outputs_experimental_2d_gls_proxy(self):
        run_with_monkeypatch(self, test_function_4ch_outputs_experimental_2d_gls_proxy)

    def test_tracking_preview_uses_current_4ch_series_without_persisting(self):
        run_with_monkeypatch(self, test_tracking_preview_uses_current_4ch_series_without_persisting)

    def test_tracking_preview_ignores_nonadjacent_manual_phases(self):
        run_with_monkeypatch(self, test_tracking_preview_ignores_nonadjacent_manual_phases)

    def test_tracking_reuses_one_flow_field_for_all_regions(self):
        run_with_monkeypatch(self, test_tracking_reuses_one_flow_field_for_all_regions)
