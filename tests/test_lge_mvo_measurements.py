import contextlib

import numpy as np

from apps.api.services import measurements


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
