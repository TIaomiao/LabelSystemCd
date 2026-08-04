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


def test_lge_recompute_counts_mvo_as_scar(monkeypatch):
    series_id = 42
    contours = {
        "series_id": series_id,
        "module": "lge",
        "settings": {"threshold_method": "nsd", "sd_multiplier": 5.0},
        "frames": {
            "0:0": {
                "include": True,
                "epi": _contour([(1, 1), (8, 1), (8, 8), (1, 8)]),
                "endo": _contour([(6, 6), (7, 6), (7, 7), (6, 7)]),
                "remote": _contour([(1, 1), (3, 1), (3, 3), (1, 3)]),
                "mvo": _contour([(4, 2), (5, 2), (5, 3), (4, 3)]),
            }
        },
    }
    image = np.zeros((10, 10), dtype=np.float32)
    image[1:4, 1:4] = np.array(
        [
            [90, 96, 100],
            [104, 108, 112],
            [120, 150, 200],
        ],
        dtype=np.float32,
    )

    class FakeConn:
        def execute(self, query, params=()):
            if "SELECT * FROM series" in query:
                return self
            raise AssertionError(f"Unexpected query: {query}")

        def fetchone(self):
            return {
                "id": series_id,
                "rows": 10,
                "cols": 10,
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
    monkeypatch.setattr(measurements, "get_frame_row", lambda *_args: {"id": 1})
    monkeypatch.setattr(measurements, "read_frame_pixels", lambda _frame: image)
    monkeypatch.setattr(measurements, "_save_measurement", lambda _series_id, _module, payload: payload)
    monkeypatch.setattr(measurements, "_update_lge_generated_contours", lambda *_args: None)

    result = measurements.recompute_lge(series_id)

    metrics = result["metrics"]
    assert metrics["mvo_volume_ml"] > 0
    assert metrics["scar_volume_ml"] == metrics["mvo_volume_ml"]
    assert metrics["scar_mass_g"] == metrics["mvo_mass_g"]
    assert metrics["scar_percent_myocardium"] == metrics["mvo_percent_myocardium"]
    masks = measurements._frame_masks(contours["frames"]["0:0"], 10, 10)
    myocardium = masks["epi"] & ~masks["endo"]
    remote_pixels = image[masks["remote"] & myocardium]
    baseline = remote_pixels[remote_pixels <= np.median(remote_pixels)]
    expected_threshold = float(baseline.mean()) + 5.0 * float(baseline.std())
    assert result["per_slice"][0]["threshold"] == round(expected_threshold, 2)


def test_lge_fwhm_uses_half_enhanced_seed_max(monkeypatch):
    series_id = 44
    contours = {
        "series_id": series_id,
        "module": "lge",
        "settings": {"threshold_method": "fwhm"},
        "frames": {
            "0:0": {
                "include": True,
                "epi": _contour([(1, 1), (10, 1), (10, 10), (1, 10)]),
                "endo": _contour([(5, 5), (6, 5), (6, 6), (5, 6)]),
                "enhanced": _contour([(2, 2), (5, 2), (5, 5), (2, 5)]),
            }
        },
    }
    image = np.full((12, 12), 40, dtype=np.float32)
    image[2:6, 2:6] = 200

    class FakeConn:
        def execute(self, query, params=()):
            if "SELECT * FROM series" in query:
                return self
            raise AssertionError(f"Unexpected query: {query}")

        def fetchone(self):
            return {
                "id": series_id,
                "rows": 12,
                "cols": 12,
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
    monkeypatch.setattr(measurements, "get_frame_row", lambda *_args: {"id": 1})
    monkeypatch.setattr(measurements, "read_frame_pixels", lambda _frame: image)
    monkeypatch.setattr(measurements, "_save_measurement", lambda _series_id, _module, payload: payload)
    monkeypatch.setattr(measurements, "_update_lge_generated_contours", lambda *_args: None)

    result = measurements.recompute_lge(series_id, "fwhm")

    assert result["metrics"]["threshold_method"] == "fwhm"
    assert result["per_slice"][0]["threshold"] == 100.0
    assert result["metrics"]["scar_volume_ml"] > 0


def test_lge_threshold_preview_returns_scar_and_grey_zone_masks(monkeypatch):
    series_id = 45
    contours = {
        "series_id": series_id,
        "module": "lge",
        "settings": {},
        "frames": {
            "0:0": {
                "include": True,
                "epi": _contour([(1, 1), (10, 1), (10, 10), (1, 10)]),
                "endo": _contour([(5, 5), (6, 5), (6, 6), (5, 6)]),
                "enhanced": _contour([(2, 2), (5, 2), (5, 5), (2, 5)]),
            }
        },
    }
    image = np.full((12, 12), 40, dtype=np.float32)
    image[2:6, 2:6] = 200
    image[7:9, 2:4] = 80

    class FakeConn:
        def execute(self, query, params=()):
            if "SELECT * FROM series" in query:
                return self
            raise AssertionError(f"Unexpected query: {query}")

        def fetchone(self):
            return {
                "id": series_id,
                "rows": 12,
                "cols": 12,
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
    monkeypatch.setattr(measurements, "get_frame_row", lambda *_args: {"id": 1})
    monkeypatch.setattr(measurements, "read_frame_pixels", lambda _frame: image)

    result = measurements.compute_lge_threshold_preview(series_id, 0, "fwhm", 5.0, True)

    assert result["threshold_method"] == "fwhm"
    assert result["threshold"] == 100.0
    assert result["stats"]["scar"]["pixel_count"] > 0
    assert result["stats"]["grey_zone"]["pixel_count"] > 0
    assert result["masks"]["scar"]["runs"]
    assert result["masks"]["grey_zone"]["runs"]


def test_lge_exclude_regions_are_union_mask(monkeypatch):
    series_id = 43
    contours = {
        "series_id": series_id,
        "module": "lge",
        "settings": {"threshold_method": "nsd", "sd_multiplier": 5.0},
        "frames": {
            "0:0": {
                "include": True,
                "epi": _contour([(1, 1), (10, 1), (10, 10), (1, 10)]),
                "endo": _contour([(5, 5), (6, 5), (6, 6), (5, 6)]),
                "remote": _contour([(2, 2), (3, 2), (3, 3), (2, 3)]),
                "exclude": None,
                "exclude_regions": [
                    _contour([(2, 6), (4, 6), (4, 8), (2, 8)]),
                    _contour([(7, 2), (9, 2), (9, 4), (7, 4)]),
                ],
            }
        },
    }
    image = np.zeros((12, 12), dtype=np.float32)

    class FakeConn:
        def execute(self, query, params=()):
            if "SELECT * FROM series" in query:
                return self
            raise AssertionError(f"Unexpected query: {query}")

        def fetchone(self):
            return {
                "id": series_id,
                "rows": 12,
                "cols": 12,
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
    monkeypatch.setattr(measurements, "get_frame_row", lambda *_args: {"id": 1})
    monkeypatch.setattr(measurements, "read_frame_pixels", lambda _frame: image)
    monkeypatch.setattr(measurements, "_save_measurement", lambda _series_id, _module, payload: payload)
    monkeypatch.setattr(measurements, "_update_lge_generated_contours", lambda *_args: None)

    result = measurements.recompute_lge(series_id)

    masks = measurements._frame_masks(contours["frames"]["0:0"], 12, 12)
    expected_exclude = masks["exclude"] & (masks["epi"] & ~masks["endo"])
    assert int(expected_exclude.sum()) > 0
    assert result["per_slice"][0]["exclude_volume_ml"] == round(float(expected_exclude.sum()) * 0.01, 2)
    assert result["metrics"]["exclude_volume_ml"] == round(float(expected_exclude.sum()) * 0.01, 2)


class LgeMvoMeasurementTests(unittest.TestCase):
    def test_lge_recompute_counts_mvo_as_scar(self):
        run_with_monkeypatch(self, test_lge_recompute_counts_mvo_as_scar)

    def test_lge_exclude_regions_are_union_mask(self):
        run_with_monkeypatch(self, test_lge_exclude_regions_are_union_mask)

    def test_lge_fwhm_uses_half_enhanced_seed_max(self):
        run_with_monkeypatch(self, test_lge_fwhm_uses_half_enhanced_seed_max)

    def test_lge_threshold_preview_returns_scar_and_grey_zone_masks(self):
        run_with_monkeypatch(self, test_lge_threshold_preview_returns_scar_and_grey_zone_masks)
