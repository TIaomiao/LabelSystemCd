import csv
import sys

from flask import Flask


sys.path.insert(0, "backend")

from cvi_workstation import _case_display_identity, _iter_case_dirs, _looks_like_dicom, _manifest_search_matches


def test_deep_case_directories_use_anonymous_manifest_ids(tmp_path):
    root = tmp_path / "scs2"
    first_study = root / "batch-a" / "export-a" / "study-a"
    second_study = root / "batch-b" / "export-b" / "study-b"
    first_study.mkdir(parents=True)
    second_study.mkdir(parents=True)

    manifest = tmp_path / "study_import_queue_private.csv"
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["case_sequence", "source_relative_dir", "patient_id"])
        writer.writeheader()
        writer.writerow({"case_sequence": "SCS2-0001", "source_relative_dir": "batch-a/export-a/study-a", "patient_id": "REG-001"})
        writer.writerow({"case_sequence": "SCS2-0002", "source_relative_dir": "batch-b/export-b/study-b", "patient_id": "REG-002"})

    app = Flask(__name__)
    app.config["DATA_ROOT"] = str(tmp_path / "missing")
    app.config["CVI_LIBRARY_MULTICENTER_ROOTS"] = [
        {
            "dataset": "CMR_SCS_2",
            "label": "SCS supplemental",
            "path": str(root),
            "case_dir_depth": 3,
            "case_id_manifest": str(manifest),
            "case_id_prefix": "SCS2-",
        }
    ]

    with app.app_context():
        rows = list(_iter_case_dirs("functional", ["CMR_SCS_2"]))

    assert [(dataset, case_id) for _, dataset, case_id, _ in rows] == [
        ("CMR_SCS_2", "SCS2-0001"),
        ("CMR_SCS_2", "SCS2-0002"),
    ]
    assert [path.name for *_, path in rows] == ["study-a", "study-b"]
    assert _looks_like_dicom("image.dic") is True

    with app.app_context():
        assert _manifest_search_matches(["CMR_SCS_2"], "REG-002") == {"CMR_SCS_2": {"SCS2-0002"}}
        assert _case_display_identity("CMR_SCS_2", "SCS2-0001") == {
            "primary_id_label": "登记号",
            "primary_id": "REG-001",
        }
