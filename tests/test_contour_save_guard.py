from apps.api.services import inference


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
