import contextlib
import json
import math
import sqlite3
import tempfile
import threading
import time
import unittest

import numpy as np
from pydantic import ValidationError

from apps.api.models import ContourSet, CurvatureUpdateRequest
from apps.api.services import inference, measurements
from apps.api.services.curvature import compute_curvature_from_landmarks
from apps.api.services.dicom_indexer import _pixel_spacing
from apps.api.services.inference import _preserve_curvature_landmarks
from tests._unittest_compat import run_with_monkeypatch


def _landmarks(**overrides):
    payload = {
        "slice_index": 0,
        "phase_index": 0,
        "j1": {"x": 2.0, "y": 30.0},
        "j2": {"x": 7.0, "y": 30.0},
        "m1": {"x": 4.5, "y": 40.0},
        "m2": {"x": 4.5, "y": 10.0},
        "method": "manual_four_point",
    }
    payload.update(overrides)
    return payload


def _compute(payload, **overrides):
    options = {
        "spacing_x": 2.0,
        "spacing_y": 0.5,
        "series_role": "cine_sax",
        "available_frame_keys": {(0, 0)},
        "image_rows": 64,
        "image_cols": 16,
    }
    options.update(overrides)
    return compute_curvature_from_landmarks(payload, **options)


def _create_contour_store(path, series_id, payload):
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE contours (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                series_id INTEGER NOT NULL,
                module TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(series_id, module)
            )
            """
        )
        conn.execute(
            "INSERT INTO contours (series_id, module, payload_json, updated_at) VALUES (?, ?, ?, ?)",
            (series_id, "function", json.dumps(payload), "2026-01-01T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()


def _read_stored_contours(path, series_id):
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT payload_json FROM contours WHERE series_id = ? AND module = ?",
            (series_id, "function"),
        ).fetchone()
        return json.loads(row[0])
    finally:
        conn.close()


def _patch_sqlite_store(monkeypatch, path, *, connection_opened=None):
    @contextlib.contextmanager
    def fake_get_conn():
        conn = sqlite3.connect(path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        if connection_opened is not None:
            connection_opened.set()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    monkeypatch.setattr(inference, "get_conn", fake_get_conn)


def test_curvature_landmarks_pydantic_roundtrip():
    payload = {
        "series_id": 7,
        "module": "function",
        "curvature_landmarks": _landmarks(
            j1={"x": 2.0, "y": 30.0, "patient": [1.0, 2.0, 3.0]},
            m2=None,
        ),
    }
    model = ContourSet.model_validate(payload)
    restored = ContourSet.model_validate_json(model.model_dump_json()).model_dump()

    assert restored["curvature_landmarks"]["j1"]["patient"] == [1.0, 2.0, 3.0]
    assert restored["curvature_landmarks"]["m2"] is None
    assert restored["curvature_landmarks"]["slice_index"] == 0
    assert "curvature_landmarks" in model.model_fields_set

    omitted = ContourSet.model_validate({"series_id": 7, "module": "function"})
    explicit_null = ContourSet.model_validate({"series_id": 7, "module": "function", "curvature_landmarks": None})
    assert "curvature_landmarks" not in omitted.model_fields_set
    assert "curvature_landmarks" in explicit_null.model_fields_set


def test_curvature_patch_payload_requires_landmarks_key_and_allows_null():
    with unittest.TestCase().assertRaises(ValidationError):
        CurvatureUpdateRequest.model_validate({})

    cleared = CurvatureUpdateRequest.model_validate({"landmarks": None})
    updated = CurvatureUpdateRequest.model_validate({"landmarks": _landmarks()})

    assert cleared.landmarks is None
    assert updated.landmarks is not None
    assert updated.landmarks.model_dump() == _landmarks(j1={"x": 2.0, "y": 30.0, "patient": None}, j2={"x": 7.0, "y": 30.0, "patient": None}, m1={"x": 4.5, "y": 40.0, "patient": None}, m2={"x": 4.5, "y": 10.0, "patient": None})


def test_curvature_uses_anisotropic_xy_spacing():
    result = _compute(_landmarks())

    assert result["status"] == "valid"
    assert math.isclose(result["ivs"]["radius_mm"], 5.0, rel_tol=1e-9)
    assert math.isclose(result["free_wall"]["radius_mm"], 6.25, rel_tol=1e-9)
    assert math.isclose(result["ivs"]["curvature_magnitude_mm_inv"], 0.2, rel_tol=1e-9)
    assert math.isclose(result["free_wall"]["curvature_magnitude_mm_inv"], 0.16, rel_tol=1e-9)
    assert math.isclose(result["curvature_ratio_magnitude"], 1.25, rel_tol=1e-9)
    assert result["midpoint_side_relation"] == "opposite_sides"
    assert result["signed"] is True
    assert result["septal_shape"] == "non_inverted"
    assert result["ivs"]["signed_curvature_mm_inv"] == 0.2
    assert result["signed_curvature_ratio"] == 1.25
    assert result["curvature_ratio_rc"] == 1.25
    assert result["ivs"]["circle_center_mm"] == [9.0, 15.0]
    assert result["free_wall"]["circle_center_mm"] == [9.0, 11.25]


def test_flat_septum_returns_zero_without_non_finite_json():
    result = _compute(_landmarks(m1={"x": 4.5, "y": 30.0}))

    assert result["status"] == "valid"
    assert result["qc_status"] == "warning"
    assert result["ivs"]["status"] == "flat"
    assert result["ivs"]["radius_mm"] is None
    assert result["ivs"]["curvature_magnitude_mm_inv"] == 0.0
    assert result["curvature_ratio_magnitude"] == 0.0
    assert result["curvature_ratio_rc"] == 0.0
    assert result["signed_curvature_ratio"] == 0.0
    assert result["septal_shape"] == "flat"
    assert "ivs:flat_arc" in result["qc_reasons"]
    json.dumps(result, allow_nan=False)


def test_incomplete_duplicate_and_out_of_bounds_landmarks_do_not_emit_ratio():
    incomplete = _compute(_landmarks(m1=None, m2=None))
    duplicate = _compute(_landmarks(j2={"x": 2.0, "y": 30.0}))
    outside = _compute(_landmarks(m1={"x": 20.0, "y": 40.0}))

    assert incomplete["status"] == "incomplete"
    assert incomplete["curvature_ratio_magnitude"] is None
    assert duplicate["status"] == "invalid"
    assert duplicate["curvature_ratio_magnitude"] is None
    assert outside["status"] == "invalid"
    assert outside["qc_reasons"] == ["landmark_out_of_bounds:m1"]
    json.dumps(incomplete, allow_nan=False)
    json.dumps(duplicate, allow_nan=False)
    json.dumps(outside, allow_nan=False)


def test_nonfinite_inputs_and_large_geometry_are_json_safe():
    invalid_index = _compute(_landmarks(slice_index=float("nan")))
    huge_spacing = _compute(_landmarks(), spacing_x=1e308, spacing_y=1e308, image_rows=None, image_cols=None)
    precise_ratio = compute_curvature_from_landmarks(
        {
            "slice_index": 0,
            "phase_index": 0,
            "j1": {"x": 0.0, "y": 0.0},
            "j2": {"x": 10_000_000.0, "y": 0.0},
            "m1": {"x": 5_000_000.0, "y": 20.0},
            "m2": {"x": 5_000_000.0, "y": -40.0},
        },
        spacing_x=1.0,
        spacing_y=1.0,
        series_role="cine_sax",
        available_frame_keys={(0, 0)},
    )

    assert invalid_index["slice_index"] is None
    assert invalid_index["curvature_ratio_magnitude"] is None
    assert huge_spacing["status"] == "invalid"
    assert precise_ratio["status"] == "valid"
    assert precise_ratio["ivs"]["curvature_magnitude_mm_inv"] > 0
    assert math.isclose(precise_ratio["curvature_ratio_magnitude"], 0.5, rel_tol=1e-9)
    json.dumps(invalid_index, allow_nan=False)
    json.dumps(huge_spacing, allow_nan=False)
    json.dumps(precise_ratio, allow_nan=False)

    with unittest.TestCase().assertRaises(ValidationError):
        ContourSet.model_validate({
            "series_id": 7,
            "module": "function",
            "curvature_landmarks": _landmarks(j1={"x": float("nan"), "y": 30.0}),
        })


def test_midpoint_geometry_qc_is_explicit():
    inverted = _compute(_landmarks(m1={"x": 4.5, "y": 20.0}))
    coincident = _compute(_landmarks(m2={"x": 4.5, "y": 40.0}))
    outside_projection = compute_curvature_from_landmarks(
        _landmarks(m1={"x": -2.0, "y": 40.0}),
        spacing_x=2.0,
        spacing_y=0.5,
        series_role="cine_sax",
        available_frame_keys={(0, 0)},
    )

    assert inverted["status"] == "valid"
    assert inverted["qc_status"] == "pass"
    assert inverted["septal_shape"] == "inverted"
    assert inverted["ivs"]["signed_curvature_mm_inv"] == -0.2
    assert inverted["curvature_ratio_magnitude"] == 1.25
    assert inverted["curvature_ratio_rc"] == -1.25
    assert coincident["status"] == "invalid"
    assert coincident["qc_reasons"] == ["septal_and_free_wall_midpoints_coincident"]
    assert outside_projection["status"] == "invalid"
    assert outside_projection["qc_reasons"] == ["ivs:midpoint_outside_junction_chord"]


def test_signed_curvature_is_invariant_to_junction_order_and_mirroring():
    positive = _landmarks()
    inverted = _landmarks(m1={"x": 4.5, "y": 20.0})

    def variants(payload):
        swapped = {**payload, "j1": payload["j2"], "j2": payload["j1"]}
        mirror_x = {
            **payload,
            **{key: {"x": -payload[key]["x"], "y": payload[key]["y"]} for key in ("j1", "j2", "m1", "m2")},
        }
        mirror_y = {
            **payload,
            **{key: {"x": payload[key]["x"], "y": -payload[key]["y"]} for key in ("j1", "j2", "m1", "m2")},
        }
        return (payload, swapped, mirror_x, mirror_y)

    positive_results = [
        compute_curvature_from_landmarks(
            payload,
            spacing_x=2.0,
            spacing_y=0.5,
            series_role="cine_sax",
            available_frame_keys={(0, 0)},
        )
        for payload in variants(positive)
    ]
    inverted_results = [
        compute_curvature_from_landmarks(
            payload,
            spacing_x=2.0,
            spacing_y=0.5,
            series_role="cine_sax",
            available_frame_keys={(0, 0)},
        )
        for payload in variants(inverted)
    ]

    assert {result["curvature_ratio_rc"] for result in positive_results} == {1.25}
    assert {result["septal_shape"] for result in positive_results} == {"non_inverted"}
    assert {result["curvature_ratio_rc"] for result in inverted_results} == {-1.25}
    assert {result["septal_shape"] for result in inverted_results} == {"inverted"}


def test_dicom_pixel_spacing_is_normalized_to_xy_order():
    dataset = type("Dataset", (), {"PixelSpacing": [0.5, 2.0]})()
    assert _pixel_spacing(dataset) == (2.0, 0.5)


def test_wrong_role_frame_and_spacing_are_blocked():
    wrong_role = _compute(_landmarks(), series_role="cine_lax_4ch")
    missing_frame = _compute(_landmarks(), available_frame_keys={(1, 0)})
    invalid_spacing = _compute(_landmarks(), spacing_x=0.0)

    assert wrong_role["qc_reasons"] == ["curvature_requires_cine_sax"]
    assert missing_frame["qc_reasons"] == ["selected_frame_not_found"]
    assert invalid_spacing["qc_reasons"] == ["invalid_pixel_spacing"]


def test_generic_payload_always_preserves_landmarks_even_when_explicit():
    existing = {"curvature_landmarks": _landmarks(), "frames": {}}

    preserved = _preserve_curvature_landmarks(existing, {"frames": {}})
    explicit_null = _preserve_curvature_landmarks(existing, {"frames": {}, "curvature_landmarks": None})
    explicit_replacement = _preserve_curvature_landmarks(
        existing,
        {"frames": {}, "curvature_landmarks": _landmarks(m1={"x": 4.5, "y": 20.0})},
    )
    assert preserved["curvature_landmarks"] == existing["curvature_landmarks"]
    assert explicit_null["curvature_landmarks"] == existing["curvature_landmarks"]
    assert explicit_replacement["curvature_landmarks"] == existing["curvature_landmarks"]


def test_generic_save_path_preserves_landmarks_from_stale_payloads(monkeypatch):
    existing = {
        "series_id": 93,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {},
        "phase_labels": {},
        "curvature_landmarks": _landmarks(),
        "frames": {},
    }
    saved = []
    monkeypatch.setattr(inference, "fetch_contours", lambda *_args: existing)
    monkeypatch.setattr(inference, "_upsert_contours", lambda _series_id, _module, payload: saved.append(payload))
    monkeypatch.setattr(inference, "recompute_measurements_for_module", lambda *_args: {})

    inference.save_contours(93, "function", {"series_id": 93, "module": "function", "frames": {}}, action_origin="model")
    inference.save_contours(
        93,
        "function",
        {"series_id": 93, "module": "function", "curvature_landmarks": None, "frames": {}},
        action_origin="manual",
    )
    inference.save_contours(
        93,
        "function",
        {
            "series_id": 93,
            "module": "function",
            "curvature_landmarks": _landmarks(m1={"x": 4.5, "y": 20.0}),
            "frames": {},
        },
        action_origin="manual",
    )
    inference.save_contours(
        93,
        "function",
        {"series_id": 93, "module": "function", "curvature_landmarks": None, "frames": {}},
        action_origin="model",
    )

    assert saved[0]["curvature_landmarks"] == existing["curvature_landmarks"]
    assert saved[1]["curvature_landmarks"] == existing["curvature_landmarks"]
    assert saved[2]["curvature_landmarks"] == existing["curvature_landmarks"]
    assert saved[3]["curvature_landmarks"] == existing["curvature_landmarks"]

    with unittest.TestCase().assertRaises(ValueError):
        inference.save_contours(
            93,
            "lge",
            {"series_id": 93, "module": "lge", "curvature_landmarks": _landmarks(), "frames": {}},
        )


def test_dedicated_curvature_save_preserves_existing_payload_and_recomputes(monkeypatch):
    series_id = 93
    old_landmarks = _landmarks(m1={"x": 4.5, "y": 35.0})
    new_landmarks = _landmarks(m1={"x": 4.5, "y": 20.0})
    existing = {
        "series_id": series_id,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {
            "manual_phase_labels": {"ed": 0, "es": 1},
            "auto_phase_labels": {},
            "custom_setting": {"keep": True},
        },
        "annotation_meta": {
            "created_at": "2026-01-01T00:00:00+00:00",
            "created_by_user_id": 3,
            "created_by_username": "原医生",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "updated_by_user_id": 3,
            "updated_by_username": "原医生",
            "origin": "manual",
            "origin_label": "人工",
            "legacy": False,
        },
        "frame_meta": {
            "0:0": {
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "created_by_user_id": 3,
                "created_by_username": "原医生",
                "updated_by_user_id": 3,
                "updated_by_username": "原医生",
                "origin": "manual",
                "origin_label": "人工",
                "legacy": False,
            },
        },
        "phase_labels": {"ed": 0, "es": 1},
        "curvature_landmarks": old_landmarks,
        "frames": {
            "0:0": {
                "include": True,
                "endo": {
                    "points": [
                        {"x": 1.0, "y": 1.0},
                        {"x": 4.0, "y": 1.0},
                        {"x": 2.0, "y": 4.0},
                    ],
                    "closed": True,
                },
            },
        },
    }
    original_snapshot = json.loads(json.dumps(existing))
    recomputed = []
    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/curvature.sqlite3"
        _create_contour_store(db_path, series_id, existing)
        _patch_sqlite_store(monkeypatch, db_path)
        monkeypatch.setattr(inference, "get_series_row", lambda *_args: {"id": series_id, "role": "cine_sax"})
        monkeypatch.setattr(
            inference,
            "recompute_measurements_for_module",
            lambda _series_id, module: recomputed.append((_series_id, module)),
        )

        result = inference.save_curvature_landmarks(
            series_id,
            new_landmarks,
            actor={"user_id": 8, "username": "曲率医生", "is_admin": False},
        )
        stored = _read_stored_contours(db_path, series_id)

        assert existing == original_snapshot
        assert result == stored
        assert result["curvature_landmarks"] == new_landmarks
        assert result["frames"] == existing["frames"]
        assert result["frame_meta"] == existing["frame_meta"]
        assert result["settings"] == existing["settings"]
        assert result["phase_labels"] == existing["phase_labels"]
        assert result["annotation_meta"]["created_by_username"] == "原医生"
        assert result["annotation_meta"]["updated_by_user_id"] == 8
        assert result["annotation_meta"]["updated_by_username"] == "曲率医生"
        assert recomputed == [(series_id, "function")]

        cleared = inference.save_curvature_landmarks(series_id, None, recompute=False)
        assert cleared["curvature_landmarks"] is None
        assert cleared["frames"] == existing["frames"]
        assert _read_stored_contours(db_path, series_id)["curvature_landmarks"] is None
        assert recomputed == [(series_id, "function")]


def test_dedicated_curvature_save_rejects_non_sax_series(monkeypatch):
    monkeypatch.setattr(inference, "get_series_row", lambda *_args: {"id": 93, "role": "cine_lax_4ch"})
    monkeypatch.setattr(
        inference,
        "_save_curvature_landmarks_atomic",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not save")),
    )

    with unittest.TestCase().assertRaisesRegex(ValueError, "cine_sax"):
        inference.save_curvature_landmarks(93, _landmarks())


def test_curvature_patch_does_not_revalidate_unmodified_historical_contours(monkeypatch):
    series_id = 95
    historical = {
        "series_id": series_id,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {},
        "phase_labels": {},
        "frames": {
            "0:0": {
                "endo": {
                    "closed": True,
                    "points": [
                        {"x": 0.0, "y": 0.0},
                        {"x": 4.0, "y": 4.0},
                        {"x": 0.0, "y": 4.0},
                        {"x": 4.0, "y": 0.0},
                    ],
                },
            },
        },
    }
    landmarks = _landmarks()

    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/curvature.sqlite3"
        _create_contour_store(db_path, series_id, historical)
        _patch_sqlite_store(monkeypatch, db_path)
        monkeypatch.setattr(inference, "get_series_row", lambda *_args: {"id": series_id, "role": "cine_sax"})

        result = inference.save_curvature_landmarks(series_id, landmarks, recompute=False)

        assert result["curvature_landmarks"] == landmarks
        assert result["frames"] == historical["frames"]
        assert _read_stored_contours(db_path, series_id)["frames"] == historical["frames"]


def test_legacy_put_after_curvature_patch_cannot_clear_saved_landmarks(monkeypatch):
    series_id = 93
    initial = {
        "series_id": series_id,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {"manual_phase_labels": {}, "auto_phase_labels": {}},
        "phase_labels": {},
        "curvature_landmarks": None,
        "frames": {},
    }
    stale_legacy_payload = json.loads(json.dumps(initial))
    stale_legacy_payload["frames"] = {"0:0": {"include": False}}
    new_landmarks = _landmarks(m1={"x": 4.5, "y": 20.0})

    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/curvature.sqlite3"
        _create_contour_store(db_path, series_id, initial)
        _patch_sqlite_store(monkeypatch, db_path)
        monkeypatch.setattr(inference, "get_series_row", lambda *_args: {"id": series_id, "role": "cine_sax"})
        monkeypatch.setattr(inference, "recompute_measurements_for_module", lambda *_args: {})

        generic_at_final_write = threading.Event()
        curvature_saved = threading.Event()
        original_upsert = inference._upsert_contours

        def delayed_upsert(*args):
            generic_at_final_write.set()
            if not curvature_saved.wait(3.0):
                raise AssertionError("curvature save did not complete")
            return original_upsert(*args)

        monkeypatch.setattr(inference, "_upsert_contours", delayed_upsert)
        errors = []
        results = []

        def run_stale_put():
            try:
                results.append(inference.save_contours(
                    series_id,
                    "function",
                    stale_legacy_payload,
                    action_origin="manual",
                    recompute=False,
                ))
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        put_thread = threading.Thread(target=run_stale_put)
        put_thread.start()
        assert generic_at_final_write.wait(3.0)
        inference.save_curvature_landmarks(series_id, new_landmarks, recompute=False)
        curvature_saved.set()
        put_thread.join(3.0)

        assert not put_thread.is_alive()
        assert errors == []
        assert results[0]["curvature_landmarks"] == new_landmarks
        stored = _read_stored_contours(db_path, series_id)
        assert stored["curvature_landmarks"] == new_landmarks
        assert stored["frames"] == stale_legacy_payload["frames"]


def test_curvature_patch_waits_for_concurrent_contour_commit_and_keeps_latest_frames(monkeypatch):
    series_id = 94
    initial = {
        "series_id": series_id,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {"manual_phase_labels": {}, "auto_phase_labels": {}},
        "phase_labels": {},
        "curvature_landmarks": None,
        "frames": {"0:0": {"include": True}},
    }
    concurrently_saved = json.loads(json.dumps(initial))
    concurrently_saved["frames"] = {"0:0": {"include": False}, "0:1": {"include": True}}
    new_landmarks = _landmarks(m1={"x": 4.5, "y": 22.0})

    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/curvature.sqlite3"
        _create_contour_store(db_path, series_id, initial)
        curvature_connection_opened = threading.Event()
        _patch_sqlite_store(
            monkeypatch,
            db_path,
            connection_opened=curvature_connection_opened,
        )
        monkeypatch.setattr(inference, "get_series_row", lambda *_args: {"id": series_id, "role": "cine_sax"})
        monkeypatch.setattr(inference, "recompute_measurements_for_module", lambda *_args: {})

        writer = sqlite3.connect(db_path, timeout=5.0)
        writer.execute("BEGIN IMMEDIATE")
        writer.execute(
            "UPDATE contours SET payload_json = ?, updated_at = ? WHERE series_id = ? AND module = ?",
            (json.dumps(concurrently_saved), "2026-01-02T00:00:00Z", series_id, "function"),
        )

        errors = []
        results = []

        def run_curvature_patch():
            try:
                results.append(inference.save_curvature_landmarks(
                    series_id,
                    new_landmarks,
                    recompute=False,
                ))
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        patch_thread = threading.Thread(target=run_curvature_patch)
        patch_thread.start()
        assert curvature_connection_opened.wait(3.0)
        time.sleep(0.05)
        assert patch_thread.is_alive()
        writer.commit()
        writer.close()
        patch_thread.join(3.0)

        assert not patch_thread.is_alive()
        assert errors == []
        assert results[0]["curvature_landmarks"] == new_landmarks
        assert results[0]["frames"] == concurrently_saved["frames"]
        stored = _read_stored_contours(db_path, series_id)
        assert stored["curvature_landmarks"] == new_landmarks
        assert stored["frames"] == concurrently_saved["frames"]


def test_curvature_spacing_prefers_selected_frame_dicom_header(monkeypatch):
    calls = []
    dataset = type("Dataset", (), {"PixelSpacing": [0.5, 2.0]})()

    def fake_dcmread(file_path, **kwargs):
        calls.append((file_path, kwargs))
        return dataset

    monkeypatch.setattr(measurements.pydicom, "dcmread", fake_dcmread)
    spacing_x, spacing_y, provenance = measurements._curvature_spacing_inputs(
        {"pixel_spacing_x": 1.0, "pixel_spacing_y": 1.0},
        [{
            "slice_index": 0,
            "phase_index": 0,
            "file_path": "/not-read-by-test/frame.dcm",
            "metadata_json": json.dumps({"pixel_spacing": [9.0, 8.0]}),
        }],
        _landmarks(),
    )

    assert (spacing_x, spacing_y, provenance) == (2.0, 0.5, "selected_frame_dicom_header")
    assert calls == [(
        "/not-read-by-test/frame.dcm",
        {"stop_before_pixels": True, "force": True, "specific_tags": ["PixelSpacing"]},
    )]


def test_curvature_preview_uses_selected_frame_spacing_without_persisting(monkeypatch):
    series_id = 94

    class FakeConn:
        def execute(self, query, params=()):
            return self

        def fetchone(self):
            return {
                "id": series_id,
                "role": "cine_sax",
                "rows": 64,
                "cols": 16,
                "pixel_spacing_x": 1.0,
                "pixel_spacing_y": 1.0,
            }

    @contextlib.contextmanager
    def fake_get_conn():
        yield FakeConn()

    monkeypatch.setattr(measurements, "get_conn", fake_get_conn)
    monkeypatch.setattr(
        measurements,
        "list_frame_rows",
        lambda *_args: [{
            "id": 1,
            "slice_index": 0,
            "phase_index": 0,
            "metadata_json": json.dumps({"pixel_spacing": [2.0, 0.5]}),
        }],
    )
    monkeypatch.setattr(
        measurements,
        "_save_measurement",
        lambda *_args: (_ for _ in ()).throw(AssertionError("preview must not persist")),
    )

    result = measurements.compute_curvature_preview(series_id, _landmarks())

    assert result["persisted"] is False
    assert result["curvature"]["status"] == "valid"
    assert result["curvature"]["curvature_ratio_magnitude"] == 1.25
    assert result["curvature"]["pixel_spacing_provenance"] == "selected_frame_index_metadata_unverified"
    assert result["curvature"]["qc_status"] == "warning"
    assert "pixel_spacing_provenance_unverified" in result["curvature"]["qc_reasons"]


def test_curvature_integrations_do_not_replace_invalid_spacing(monkeypatch):
    series_id = 95
    contours = {
        "series_id": series_id,
        "module": "function",
        "curvature_landmarks": _landmarks(),
        "frames": {},
    }

    class FakeConn:
        def execute(self, query, params=()):
            return self

        def fetchone(self):
            return {
                "id": series_id,
                "role": "cine_sax",
                "rows": 64,
                "cols": 16,
                "pixel_spacing_x": 0.0,
                "pixel_spacing_y": 0.0,
                "slice_thickness": 8.0,
                "slice_count": 1,
            }

    @contextlib.contextmanager
    def fake_get_conn():
        yield FakeConn()

    monkeypatch.setattr(measurements, "get_conn", fake_get_conn)
    monkeypatch.setattr(measurements, "_fetch_contours", lambda *_args: contours)
    monkeypatch.setattr(
        measurements,
        "list_frame_rows",
        lambda *_args: [{"id": 1, "slice_index": 0, "phase_index": 0}],
    )
    monkeypatch.setattr(measurements, "_save_measurement", lambda _series_id, _module, payload: payload)

    preview = measurements.compute_curvature_preview(series_id, _landmarks())
    persisted = measurements.recompute_function(series_id)

    assert preview["curvature"]["status"] == "invalid"
    assert preview["curvature"]["qc_reasons"] == ["invalid_pixel_spacing"]
    assert persisted["research"]["curvature"]["status"] == "invalid"
    assert persisted["research"]["curvature"]["qc_reasons"] == ["invalid_pixel_spacing"]


def test_curvature_does_not_change_existing_function_measurements(monkeypatch):
    series_id = 96
    base_contours = {
        "series_id": series_id,
        "module": "function",
        "settings": {},
        "phase_labels": {"ed": 0, "es": 0},
        "frames": {
            "0:0": {
                "include": True,
                "endo": {
                    "closed": True,
                    "points": [{"x": 5, "y": 25}, {"x": 10, "y": 25}, {"x": 10, "y": 35}, {"x": 5, "y": 35}],
                },
                "epi": {
                    "closed": True,
                    "points": [{"x": 3, "y": 20}, {"x": 12, "y": 20}, {"x": 12, "y": 40}, {"x": 3, "y": 40}],
                },
            },
        },
    }
    active_contours = {"value": base_contours}

    class FakeConn:
        def execute(self, query, params=()):
            return self

        def fetchone(self):
            return {
                "id": series_id,
                "role": "cine_sax",
                "rows": 64,
                "cols": 16,
                "pixel_spacing_x": 2.0,
                "pixel_spacing_y": 0.5,
                "slice_thickness": 8.0,
                "slice_count": 1,
            }

    @contextlib.contextmanager
    def fake_get_conn():
        yield FakeConn()

    monkeypatch.setattr(measurements, "get_conn", fake_get_conn)
    monkeypatch.setattr(measurements, "_fetch_contours", lambda *_args: active_contours["value"])
    monkeypatch.setattr(
        measurements,
        "list_frame_rows",
        lambda *_args: [{"id": 1, "slice_index": 0, "phase_index": 0, "trigger_time": 0.0}],
    )
    monkeypatch.setattr(
        measurements,
        "read_frame_pixels",
        lambda *_args: np.zeros((64, 16), dtype=float),
    )
    monkeypatch.setattr(measurements, "_save_measurement", lambda _series_id, _module, payload: payload)

    without_curvature = measurements.recompute_function(series_id)
    active_contours["value"] = {**base_contours, "curvature_landmarks": _landmarks()}
    with_curvature = measurements.recompute_function(series_id)
    with_research_without_curvature = dict(with_curvature["research"])
    with_research_without_curvature.pop("curvature")

    assert with_curvature["metrics"] == without_curvature["metrics"]
    assert with_curvature["phase_volumes"] == without_curvature["phase_volumes"]
    assert with_curvature["per_slice"] == without_curvature["per_slice"]
    assert with_research_without_curvature == without_curvature["research"]
    assert with_curvature["research"]["curvature"]["status"] == "valid"


def test_recompute_function_supports_landmarks_without_segmentation(monkeypatch):
    series_id = 91
    contours = {
        "series_id": series_id,
        "module": "function",
        "settings": {},
        "phase_labels": {},
        "curvature_landmarks": _landmarks(),
        "frames": {},
    }

    class FakeConn:
        def execute(self, query, params=()):
            if "SELECT * FROM series" in query:
                return self
            raise AssertionError(f"Unexpected query: {query}")

        def fetchone(self):
            return {
                "id": series_id,
                "role": "cine_sax",
                "rows": 64,
                "cols": 16,
                "pixel_spacing_x": 2.0,
                "pixel_spacing_y": 0.5,
                "slice_thickness": 8.0,
                "slice_count": 1,
            }

    @contextlib.contextmanager
    def fake_get_conn():
        yield FakeConn()

    monkeypatch.setattr(measurements, "get_conn", fake_get_conn)
    monkeypatch.setattr(measurements, "_fetch_contours", lambda *_args: contours)
    monkeypatch.setattr(
        measurements,
        "list_frame_rows",
        lambda *_args: [{"id": 1, "slice_index": 0, "phase_index": 0}],
    )
    monkeypatch.setattr(measurements, "_save_measurement", lambda _series_id, _module, payload: payload)

    result = measurements.recompute_function(series_id)

    assert result["metrics"] == {}
    assert result["phase_volumes"] == []
    assert result["per_slice"] == []
    assert result["research"]["region_features"] == {}
    assert result["research"]["curvature"]["status"] == "valid"
    assert result["research"]["curvature"]["curvature_ratio_magnitude"] == 1.25


def test_recompute_function_without_landmarks_keeps_legacy_empty_shape(monkeypatch):
    series_id = 92
    contours = {"series_id": series_id, "module": "function", "frames": {}}

    class FakeConn:
        def execute(self, query, params=()):
            return self

        def fetchone(self):
            return {
                "id": series_id,
                "role": "cine_sax",
                "rows": 16,
                "cols": 16,
                "pixel_spacing_x": 1.0,
                "pixel_spacing_y": 1.0,
                "slice_thickness": 8.0,
                "slice_count": 1,
            }

    @contextlib.contextmanager
    def fake_get_conn():
        yield FakeConn()

    monkeypatch.setattr(measurements, "get_conn", fake_get_conn)
    monkeypatch.setattr(measurements, "_fetch_contours", lambda *_args: contours)
    monkeypatch.setattr(measurements, "list_frame_rows", lambda *_args: [])
    monkeypatch.setattr(measurements, "_save_measurement", lambda _series_id, _module, payload: payload)

    result = measurements.recompute_function(series_id)

    assert result["research"] == {"region_features": {}}


class CurvatureMeasurementTests(unittest.TestCase):
    def test_curvature_landmarks_pydantic_roundtrip(self):
        test_curvature_landmarks_pydantic_roundtrip()

    def test_curvature_patch_payload_requires_landmarks_key_and_allows_null(self):
        test_curvature_patch_payload_requires_landmarks_key_and_allows_null()

    def test_curvature_uses_anisotropic_xy_spacing(self):
        test_curvature_uses_anisotropic_xy_spacing()

    def test_flat_septum_returns_zero_without_non_finite_json(self):
        test_flat_septum_returns_zero_without_non_finite_json()

    def test_incomplete_duplicate_and_out_of_bounds_landmarks_do_not_emit_ratio(self):
        test_incomplete_duplicate_and_out_of_bounds_landmarks_do_not_emit_ratio()

    def test_nonfinite_inputs_and_large_geometry_are_json_safe(self):
        test_nonfinite_inputs_and_large_geometry_are_json_safe()

    def test_midpoint_geometry_qc_is_explicit(self):
        test_midpoint_geometry_qc_is_explicit()

    def test_signed_curvature_is_invariant_to_junction_order_and_mirroring(self):
        test_signed_curvature_is_invariant_to_junction_order_and_mirroring()

    def test_dicom_pixel_spacing_is_normalized_to_xy_order(self):
        test_dicom_pixel_spacing_is_normalized_to_xy_order()

    def test_wrong_role_frame_and_spacing_are_blocked(self):
        test_wrong_role_frame_and_spacing_are_blocked()

    def test_generic_payload_always_preserves_landmarks_even_when_explicit(self):
        test_generic_payload_always_preserves_landmarks_even_when_explicit()

    def test_generic_save_path_preserves_landmarks_from_stale_payloads(self):
        run_with_monkeypatch(self, test_generic_save_path_preserves_landmarks_from_stale_payloads)

    def test_dedicated_curvature_save_preserves_existing_payload_and_recomputes(self):
        run_with_monkeypatch(self, test_dedicated_curvature_save_preserves_existing_payload_and_recomputes)

    def test_dedicated_curvature_save_rejects_non_sax_series(self):
        run_with_monkeypatch(self, test_dedicated_curvature_save_rejects_non_sax_series)

    def test_curvature_patch_does_not_revalidate_unmodified_historical_contours(self):
        run_with_monkeypatch(
            self,
            test_curvature_patch_does_not_revalidate_unmodified_historical_contours,
        )

    def test_legacy_put_after_curvature_patch_cannot_clear_saved_landmarks(self):
        run_with_monkeypatch(self, test_legacy_put_after_curvature_patch_cannot_clear_saved_landmarks)

    def test_curvature_patch_waits_for_concurrent_contour_commit_and_keeps_latest_frames(self):
        run_with_monkeypatch(
            self,
            test_curvature_patch_waits_for_concurrent_contour_commit_and_keeps_latest_frames,
        )

    def test_curvature_spacing_prefers_selected_frame_dicom_header(self):
        run_with_monkeypatch(self, test_curvature_spacing_prefers_selected_frame_dicom_header)

    def test_curvature_preview_uses_selected_frame_spacing_without_persisting(self):
        run_with_monkeypatch(self, test_curvature_preview_uses_selected_frame_spacing_without_persisting)

    def test_curvature_integrations_do_not_replace_invalid_spacing(self):
        run_with_monkeypatch(self, test_curvature_integrations_do_not_replace_invalid_spacing)

    def test_curvature_does_not_change_existing_function_measurements(self):
        run_with_monkeypatch(self, test_curvature_does_not_change_existing_function_measurements)

    def test_recompute_function_supports_landmarks_without_segmentation(self):
        run_with_monkeypatch(self, test_recompute_function_supports_landmarks_without_segmentation)

    def test_recompute_function_without_landmarks_keeps_legacy_empty_shape(self):
        run_with_monkeypatch(self, test_recompute_function_without_landmarks_keeps_legacy_empty_shape)
