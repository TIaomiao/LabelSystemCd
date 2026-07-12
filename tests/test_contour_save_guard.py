import unittest

from apps.api.services import inference
from _unittest_compat import run_with_monkeypatch


def _contour(points):
    return {
        "closed": True,
        "points": [{"x": x, "y": y} for x, y in points],
    }


def test_manual_empty_frames_preserves_existing_frames_and_saves_metadata(monkeypatch):
    existing = {
        "series_id": 85,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "phase_labels": {},
        "settings": {},
        "frames": {
            "8:0": {
                "include": True,
                "endo": {
                    "closed": False,
                    "points": [{"x": 1, "y": 2}, {"x": 3, "y": 4}],
                },
            }
        },
    }
    empty_payload = {
        "series_id": 85,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {"ed_es_detection_method": "heuristic-lv-area"},
        "phase_labels": {"ed": 0, "es": 10},
        "frames": {},
    }
    upserts = []
    recomputes = []

    monkeypatch.setattr(inference, "fetch_contours", lambda series_id, module: existing)
    monkeypatch.setattr(inference, "_upsert_contours", lambda *args: upserts.append(args))
    monkeypatch.setattr(inference, "recompute_measurements_for_module", lambda *args: recomputes.append(args))

    result = inference.save_contours(85, "function", empty_payload, action_origin="manual")

    assert result["frames"] == existing["frames"]
    assert result["settings"]["ed_es_detection_method"] == "heuristic-lv-area"
    assert result["phase_labels"]["ed"] == 0
    assert result["phase_labels"]["es"] == 10
    assert len(upserts) == 1
    assert recomputes == [(85, "function")]


def test_manual_empty_frames_can_create_initial_empty_record(monkeypatch):
    empty_payload = {
        "series_id": 85,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "frames": {},
    }
    upserts = []
    recomputes = []

    monkeypatch.setattr(inference, "fetch_contours", lambda series_id, module: None)
    monkeypatch.setattr(inference, "_upsert_contours", lambda *args: upserts.append(args))
    monkeypatch.setattr(inference, "recompute_measurements_for_module", lambda *args: recomputes.append(args))

    result = inference.save_contours(85, "function", empty_payload, action_origin="manual")

    assert result["frames"] == {}
    assert len(upserts) == 1
    assert recomputes == [(85, "function")]


def test_manual_empty_frames_can_explicitly_clear_existing_frames(monkeypatch):
    existing = {
        "series_id": 85,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {},
        "phase_labels": {},
        "frames": {
            "0:0": {
                "include": True,
                "rv": _contour([(1, 1), (4, 1), (4, 4), (1, 4)]),
            }
        },
    }
    clear_payload = {
        "series_id": 85,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {"allow_empty_frames_overwrite": True},
        "phase_labels": {},
        "frames": {},
    }
    upserts = []
    recomputes = []

    monkeypatch.setattr(inference, "fetch_contours", lambda series_id, module: existing)
    monkeypatch.setattr(inference, "_upsert_contours", lambda *args: upserts.append(args))
    monkeypatch.setattr(inference, "recompute_measurements_for_module", lambda *args: recomputes.append(args))

    result = inference.save_contours(85, "function", clear_payload, action_origin="manual")

    assert result["frames"] == {}
    assert "allow_empty_frames_overwrite" not in result["settings"]
    assert len(upserts) == 1
    assert recomputes == [(85, "function")]


def test_manual_phase_labels_override_auto_labels(monkeypatch):
    existing = {
        "series_id": 85,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {
            "ed_es_detection_method": "heuristic-lv-area",
            "ed_es_detection_scores": [{"phase_index": 1, "score": 1.0}],
            "auto_phase_labels": {"ed": 1, "es": 9, "lv_ed": 1, "lv_es": 9},
        },
        "phase_labels": {"ed": 1, "es": 9, "lv_ed": 1, "lv_es": 9},
        "frames": {},
    }
    incoming = {
        "series_id": 85,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {
            "ed_es_detection_method": "heuristic-lv-area",
            "ed_es_detection_scores": [{"phase_index": 1, "score": 1.0}],
        },
        "phase_labels": {"ed": 3, "es": 7, "lv_ed": 3, "lv_es": 7},
        "frames": {},
    }
    upserts = []

    monkeypatch.setattr(inference, "fetch_contours", lambda series_id, module: existing)
    monkeypatch.setattr(inference, "_upsert_contours", lambda *args: upserts.append(args))
    monkeypatch.setattr(inference, "recompute_measurements_for_module", lambda *args: None)

    result = inference.save_contours(85, "function", incoming, action_origin="manual")

    assert result["phase_labels"]["ed"] == 3
    assert result["phase_labels"]["es"] == 7
    assert result["settings"]["manual_phase_labels"]["ed"] == 3
    assert result["settings"]["auto_phase_labels"]["ed"] == 1
    assert len(upserts) == 1


def test_auto_phase_labels_used_when_no_manual_labels(monkeypatch):
    existing = {
        "series_id": 85,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {
            "ed_es_detection_method": "heuristic-lv-area",
            "ed_es_detection_scores": [{"phase_index": 1, "score": 1.0}],
            "manual_phase_labels": {"ed": 3, "es": 7},
            "auto_phase_labels": {"ed": 1, "es": 9},
        },
        "phase_labels": {"ed": 3, "es": 7},
        "frames": {},
    }
    incoming = {
        "series_id": 85,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {
            "ed_es_detection_method": "heuristic-lv-area-v2",
            "ed_es_detection_scores": [{"phase_index": 2, "score": 2.0}],
        },
        "phase_labels": {"ed": 2, "es": 8},
        "frames": {},
    }
    upserts = []

    monkeypatch.setattr(inference, "fetch_contours", lambda series_id, module: existing)
    monkeypatch.setattr(inference, "_upsert_contours", lambda *args: upserts.append(args))
    monkeypatch.setattr(inference, "recompute_measurements_for_module", lambda *args: None)

    result = inference.save_contours(85, "function", incoming, action_origin="manual")

    assert result["phase_labels"]["ed"] == 3
    assert result["phase_labels"]["es"] == 7
    assert result["settings"]["auto_phase_labels"]["ed"] == 2
    assert result["settings"]["auto_phase_labels"]["es"] == 8
    assert len(upserts) == 1


def test_auto_phase_labels_do_not_replace_existing_manual_labels(monkeypatch):
    existing = {
        "series_id": 85,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {
            "ed_es_detection_method": "heuristic-lv-area",
            "ed_es_detection_scores": [{"phase_index": 1, "score": 1.0}],
            "manual_phase_labels": {"ed": 3, "es": 7},
            "auto_phase_labels": {"ed": 1, "es": 9},
        },
        "phase_labels": {"ed": 3, "es": 7},
        "frames": {},
    }
    incoming = {
        "series_id": 85,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {
            "ed_es_detection_method": "heuristic-lv-area",
            "ed_es_detection_scores": [{"phase_index": 1, "score": 1.0}],
        },
        "phase_labels": {"ed": 1, "es": 9},
        "frames": {},
    }
    upserts = []

    monkeypatch.setattr(inference, "fetch_contours", lambda series_id, module: existing)
    monkeypatch.setattr(inference, "_upsert_contours", lambda *args: upserts.append(args))
    monkeypatch.setattr(inference, "recompute_measurements_for_module", lambda *args: None)

    result = inference.save_contours(85, "function", incoming, action_origin="manual")

    assert result["phase_labels"]["ed"] == 3
    assert result["phase_labels"]["es"] == 7
    assert result["settings"]["manual_phase_labels"]["ed"] == 3
    assert result["settings"]["auto_phase_labels"]["ed"] == 1
    assert len(upserts) == 1


def test_self_intersecting_closed_contour_is_rejected(monkeypatch):
    payload = {
        "series_id": 85,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {},
        "phase_labels": {},
        "frames": {
            "0:0": {
                "include": True,
                "fat": {
                    "closed": True,
                    "points": [
                        {"x": 1, "y": 1},
                        {"x": 8, "y": 8},
                        {"x": 1, "y": 8},
                        {"x": 8, "y": 1},
                    ],
                },
            }
        },
    }
    upserts = []
    recomputes = []

    monkeypatch.setattr(inference, "fetch_contours", lambda series_id, module: None)
    monkeypatch.setattr(inference, "_upsert_contours", lambda *args: upserts.append(args))
    monkeypatch.setattr(inference, "recompute_measurements_for_module", lambda *args: recomputes.append(args))

    try:
        inference.save_contours(85, "function", payload, action_origin="manual")
    except ValueError as exc:
        assert "自交" in str(exc)
    else:
        raise AssertionError("Expected self-intersecting contour to be rejected")

    assert upserts == []
    assert recomputes == []


def test_self_intersecting_ventricular_epi_is_rejected(monkeypatch):
    payload = {
        "series_id": 86,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {},
        "phase_labels": {},
        "frames": {
            "0:0": {
                "include": True,
                "ventricular_epi": {
                    "closed": True,
                    "points": [
                        {"x": 1, "y": 1},
                        {"x": 8, "y": 8},
                        {"x": 1, "y": 8},
                        {"x": 8, "y": 1},
                    ],
                },
            }
        },
    }
    upserts = []
    recomputes = []

    monkeypatch.setattr(inference, "fetch_contours", lambda series_id, module: None)
    monkeypatch.setattr(inference, "_upsert_contours", lambda *args: upserts.append(args))
    monkeypatch.setattr(inference, "recompute_measurements_for_module", lambda *args: recomputes.append(args))

    try:
        inference.save_contours(86, "function", payload, action_origin="manual")
    except ValueError as exc:
        assert "ventricular_epi" in str(exc)
        assert "自交" in str(exc)
    else:
        raise AssertionError("Expected self-intersecting ventricular_epi to be rejected")

    assert upserts == []
    assert recomputes == []


def test_multiple_exclude_regions_are_saved_and_mirrored_to_legacy_exclude(monkeypatch):
    regions = [
        _contour([(1, 1), (3, 1), (3, 3), (1, 3)]),
        _contour([(6, 6), (8, 6), (8, 8), (6, 8)]),
    ]
    payload = {
        "series_id": 87,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {},
        "phase_labels": {},
        "frames": {
            "0:0": {
                "include": True,
                "exclude_regions": regions,
            }
        },
    }
    upserts = []

    monkeypatch.setattr(inference, "fetch_contours", lambda series_id, module: None)
    monkeypatch.setattr(inference, "_upsert_contours", lambda *args: upserts.append(args))
    monkeypatch.setattr(inference, "recompute_measurements_for_module", lambda *args: None)

    result = inference.save_contours(87, "function", payload, action_origin="manual")

    frame = result["frames"]["0:0"]
    assert frame["exclude_regions"] == regions
    assert frame["exclude"] == regions[-1]
    assert len(upserts) == 1


def test_self_intersecting_exclude_region_is_rejected(monkeypatch):
    payload = {
        "series_id": 88,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {},
        "phase_labels": {},
        "frames": {
            "0:0": {
                "include": True,
                "exclude_regions": [
                    _contour([(1, 1), (8, 8), (1, 8), (8, 1)]),
                ],
            }
        },
    }
    upserts = []
    recomputes = []

    monkeypatch.setattr(inference, "fetch_contours", lambda series_id, module: None)
    monkeypatch.setattr(inference, "_upsert_contours", lambda *args: upserts.append(args))
    monkeypatch.setattr(inference, "recompute_measurements_for_module", lambda *args: recomputes.append(args))

    try:
        inference.save_contours(88, "function", payload, action_origin="manual")
    except ValueError as exc:
        assert "exclude_regions[0]" in str(exc)
        assert "自交" in str(exc)
    else:
        raise AssertionError("Expected self-intersecting exclude region to be rejected")

    assert upserts == []
    assert recomputes == []


def test_legacy_manual_save_preserves_existing_exclude_regions(monkeypatch):
    existing_regions = [
        _contour([(1, 1), (3, 1), (3, 3), (1, 3)]),
        _contour([(6, 6), (8, 6), (8, 8), (6, 8)]),
    ]
    existing = {
        "series_id": 89,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {},
        "phase_labels": {},
        "frames": {
            "0:0": {
                "include": True,
                "exclude": existing_regions[0],
                "exclude_regions": existing_regions,
            }
        },
    }
    incoming = {
        "series_id": 89,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {},
        "phase_labels": {},
        "frames": {
            "0:0": {
                "include": True,
                "exclude": None,
                "endo": _contour([(4, 4), (5, 4), (5, 5), (4, 5)]),
            }
        },
    }

    monkeypatch.setattr(inference, "fetch_contours", lambda series_id, module: existing)
    monkeypatch.setattr(inference, "_upsert_contours", lambda *args: None)
    monkeypatch.setattr(inference, "recompute_measurements_for_module", lambda *args: None)

    result = inference.save_contours(89, "function", incoming, action_origin="manual")

    frame = result["frames"]["0:0"]
    assert frame["exclude_regions"] == existing_regions
    assert frame["exclude"] == existing_regions[-1]
    assert frame["endo"] == incoming["frames"]["0:0"]["endo"]


def test_non_manual_payload_preserves_existing_exclude_regions():
    existing_regions = [
        _contour([(1, 1), (3, 1), (3, 3), (1, 3)]),
        _contour([(6, 6), (8, 6), (8, 8), (6, 8)]),
    ]
    existing = {
        "series_id": 91,
        "module": "function",
        "frames": {
            "0:0": {
                "include": True,
                "exclude": existing_regions[-1],
                "exclude_regions": existing_regions,
            }
        },
    }
    incoming = {
        "series_id": 91,
        "module": "function",
        "frames": {
            "0:0": {
                "include": True,
                "exclude": None,
                "endo": _contour([(4, 4), (5, 4), (5, 5), (4, 5)]),
            }
        },
    }

    result = inference._preserve_exclude_regions_for_legacy_save(existing, incoming)

    frame = result["frames"]["0:0"]
    assert frame["exclude_regions"] == existing_regions
    assert frame["exclude"] == existing_regions[-1]
    assert frame["endo"] == incoming["frames"]["0:0"]["endo"]


def test_explicit_empty_exclude_regions_clears_existing_regions(monkeypatch):
    existing_regions = [
        _contour([(1, 1), (3, 1), (3, 3), (1, 3)]),
        _contour([(6, 6), (8, 6), (8, 8), (6, 8)]),
    ]
    existing = {
        "series_id": 90,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {},
        "phase_labels": {},
        "frames": {
            "0:0": {
                "include": True,
                "exclude": existing_regions[0],
                "exclude_regions": existing_regions,
            }
        },
    }
    incoming = {
        "series_id": 90,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {},
        "phase_labels": {},
        "frames": {
            "0:0": {
                "include": True,
                "exclude": None,
                "exclude_regions": [],
            }
        },
    }

    monkeypatch.setattr(inference, "fetch_contours", lambda series_id, module: existing)
    monkeypatch.setattr(inference, "_upsert_contours", lambda *args: None)
    monkeypatch.setattr(inference, "recompute_measurements_for_module", lambda *args: None)

    result = inference.save_contours(90, "function", incoming, action_origin="manual")

    frame = result["frames"]["0:0"]
    assert frame["exclude_regions"] == []
    assert frame["exclude"] is None


def test_legacy_propagation_payload_without_frame_meta_is_marked_propagate():
    payload = {
        "series_id": 91,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {
            "backend": "edgetam+hybrid",
            "propagation": {"method": "hybrid"},
            "propagation_axes": ["phase", "slice"],
        },
        "phase_labels": {},
        "frames": {
            "0:0": {"include": True, "endo": _contour([(1, 1), (4, 1), (4, 4), (1, 4)])},
            "0:1": {"include": True, "endo": _contour([(2, 2), (5, 2), (5, 5), (2, 5)])},
        },
    }

    normalized = inference._normalize_contour_payload(payload, series_id=91, module="function")

    assert normalized["frame_meta"]["0:0"]["origin"] == "propagate"
    assert normalized["frame_meta"]["0:0"]["origin_label"] == "传播补全"
    assert normalized["frame_meta"]["0:1"]["origin"] == "propagate"


def test_plain_manual_payload_without_frame_meta_stays_manual():
    payload = {
        "series_id": 92,
        "module": "function",
        "coordinate_space": "pixel",
        "source": "manual",
        "settings": {},
        "phase_labels": {},
        "frames": {
            "0:0": {"include": True, "endo": _contour([(1, 1), (4, 1), (4, 4), (1, 4)])},
        },
    }

    normalized = inference._normalize_contour_payload(payload, series_id=92, module="function")

    assert normalized["frame_meta"]["0:0"]["origin"] == "manual"
    assert normalized["frame_meta"]["0:0"]["origin_label"] == "人工"


def test_annotation_summary_counts_real_4ch_contour_frames():
    rows = [
        {
            "study_id": 12,
            "series_id": 34,
            "role": "cine_lax_4ch",
            "module": "function",
            "updated_at": "2026-07-12T10:00:00Z",
            "payload_json": inference.dumps(
                {
                    "frames": {
                        "0:9": {"include": True, "endo": _contour([(1, 1), (4, 1), (4, 4), (1, 4)])},
                        "0:24": {"include": True, "epi": _contour([(0, 0), (5, 0), (5, 5), (0, 5)])},
                    }
                }
            ),
        }
    ]

    summary = inference._summarize_study_annotation_rows(rows, [12])["12"]

    assert summary["is_annotated"] is True
    assert summary["annotated_frame_count"] == 2
    assert summary["annotated_series_count"] == 1
    assert summary["completed_modules"] == ["function_4ch"]


def test_annotation_summary_ignores_empty_frames():
    rows = [
        {
            "study_id": 13,
            "series_id": 35,
            "role": "cine_lax_4ch",
            "module": "function",
            "updated_at": "2026-07-12T10:00:00Z",
            "payload_json": inference.dumps({"frames": {"0:9": {"include": True}}}),
        }
    ]

    summary = inference._summarize_study_annotation_rows(rows, [13])["13"]

    assert summary["is_annotated"] is False
    assert summary["annotated_frame_count"] == 0
    assert summary["completed_modules"] == []


class ContourSaveGuardTests(unittest.TestCase):
    def test_manual_empty_frames_preserves_existing_frames_and_saves_metadata(self):
        run_with_monkeypatch(self, test_manual_empty_frames_preserves_existing_frames_and_saves_metadata)

    def test_manual_empty_frames_can_create_initial_empty_record(self):
        run_with_monkeypatch(self, test_manual_empty_frames_can_create_initial_empty_record)

    def test_manual_empty_frames_can_explicitly_clear_existing_frames(self):
        run_with_monkeypatch(self, test_manual_empty_frames_can_explicitly_clear_existing_frames)

    def test_manual_phase_labels_override_auto_labels(self):
        run_with_monkeypatch(self, test_manual_phase_labels_override_auto_labels)

    def test_auto_phase_labels_used_when_no_manual_labels(self):
        run_with_monkeypatch(self, test_auto_phase_labels_used_when_no_manual_labels)

    def test_auto_phase_labels_do_not_replace_existing_manual_labels(self):
        run_with_monkeypatch(self, test_auto_phase_labels_do_not_replace_existing_manual_labels)

    def test_self_intersecting_closed_contour_is_rejected(self):
        run_with_monkeypatch(self, test_self_intersecting_closed_contour_is_rejected)

    def test_self_intersecting_ventricular_epi_is_rejected(self):
        run_with_monkeypatch(self, test_self_intersecting_ventricular_epi_is_rejected)

    def test_multiple_exclude_regions_are_saved_and_mirrored_to_legacy_exclude(self):
        run_with_monkeypatch(self, test_multiple_exclude_regions_are_saved_and_mirrored_to_legacy_exclude)

    def test_self_intersecting_exclude_region_is_rejected(self):
        run_with_monkeypatch(self, test_self_intersecting_exclude_region_is_rejected)

    def test_legacy_manual_save_preserves_existing_exclude_regions(self):
        run_with_monkeypatch(self, test_legacy_manual_save_preserves_existing_exclude_regions)

    def test_non_manual_payload_preserves_existing_exclude_regions(self):
        test_non_manual_payload_preserves_existing_exclude_regions()

    def test_explicit_empty_exclude_regions_clears_existing_regions(self):
        run_with_monkeypatch(self, test_explicit_empty_exclude_regions_clears_existing_regions)

    def test_legacy_propagation_payload_without_frame_meta_is_marked_propagate(self):
        test_legacy_propagation_payload_without_frame_meta_is_marked_propagate()

    def test_plain_manual_payload_without_frame_meta_stays_manual(self):
        test_plain_manual_payload_without_frame_meta_stays_manual()

    def test_annotation_summary_counts_real_4ch_contour_frames(self):
        test_annotation_summary_counts_real_4ch_contour_frames()

    def test_annotation_summary_ignores_empty_frames(self):
        test_annotation_summary_ignores_empty_frames()
