import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask


sys.path.insert(0, "backend")

from cvi_workstation import (
    _case_display_identity,
    _catalog_payload,
    _configured_functional_datasets,
    _iter_case_dirs,
    _looks_like_dicom,
    _manifest_search_matches,
    _refresh_case_catalog,
    _sequence_summary,
)
from extensions import db
from models import CviCaseCatalog


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


def test_case_search_aliases_keep_existing_case_ids_and_filter_unauthorized_rows(tmp_path):
    root = tmp_path / "renji"
    first_case = root / "existing-case-a"
    second_case = root / "existing-case-b"
    first_case.mkdir(parents=True)
    second_case.mkdir(parents=True)
    alias_manifest = tmp_path / "renji_case_aliases.csv"
    with alias_manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["case_id", "registration_number", "accession_number", "patient_id", "study_date"],
        )
        writer.writeheader()
        writer.writerow({
            "case_id": "existing-case-a",
            "registration_number": "REG-A",
            "accession_number": "ACC-A",
            "patient_id": "PID-A",
            "study_date": "2026-01-01",
        })
        writer.writerow({
            "case_id": "existing-case-b",
            "registration_number": "REG-B",
            "accession_number": "ACC-B",
            "patient_id": "PID-B",
            "study_date": "2026-01-02",
        })

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["DATA_ROOT"] = str(tmp_path / "missing")
    app.config["CVI_LIBRARY_MULTICENTER_ROOTS"] = [{
        "dataset": "CMR_RenJi_MI",
        "label": "RenJi MI",
        "path": str(root),
        "case_dir_contains_dicoms": True,
        "case_search_alias_manifest": str(alias_manifest),
        "primary_id_field": "registration_number",
        "primary_id_label": "登记号",
    }]
    db.init_app(app)

    with app.app_context():
        db.create_all()
        rows = list(_iter_case_dirs("functional", ["CMR_RenJi_MI"]))
        assert [(dataset, case_id) for _, dataset, case_id, _ in rows] == [
            ("CMR_RenJi_MI", "existing-case-a"),
            ("CMR_RenJi_MI", "existing-case-b"),
        ]
        db.session.add_all([
            CviCaseCatalog(
                source="functional",
                dataset="CMR_RenJi_MI",
                case_id="existing-case-a",
                full_id="CMR_RenJi_MI/existing-case-a",
                path=str(first_case),
            ),
            CviCaseCatalog(
                source="functional",
                dataset="CMR_RenJi_MI",
                case_id="existing-case-b",
                full_id="CMR_RenJi_MI/existing-case-b",
                path=str(second_case),
            ),
        ])
        db.session.commit()

        assert _manifest_search_matches(["CMR_RenJi_MI"], "REG-A") == {
            "CMR_RenJi_MI": {"existing-case-a"}
        }
        assert _manifest_search_matches(["CMR_RenJi_MI"], "ACC-B") == {
            "CMR_RenJi_MI": {"existing-case-b"}
        }
        assert _case_display_identity("CMR_RenJi_MI", "existing-case-a") == {
            "primary_id_label": "登记号",
            "primary_id": "REG-A",
        }
        selection = {
            "query_source": "functional",
            "dataset_filters": ["CMR_RenJi_MI"],
            "case_ids": None,
        }
        with patch("cvi_workstation._user_can_access_case", side_effect=lambda _, __, case_id: case_id == "existing-case-a"), \
                patch("cvi_workstation._cvi_library_options", return_value=[]):
            payload = _catalog_payload(selection, "REG", 20)
        assert [item["case_id"] for item in payload["items"]] == ["existing-case-a"]


class CatalogShapeTest(unittest.TestCase):
    def test_numeric_series_directory_stays_inside_private_top_level_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "pah-test"
            series = root / "PAH-5" / "901029"
            series.mkdir(parents=True)
            (series / "1_0.dcm").touch()
            (root / "PAH-5" / "StudyInfo.dat").touch()

            app = Flask(__name__)
            app.config["DATA_ROOT"] = str(tmp_path / "missing")
            app.config["CVI_LIBRARY_MULTICENTER_ROOTS"] = [
                {
                    "dataset": "CMR_SCS_PAH_TEST",
                    "label": "PAH curvature acceptance",
                    "path": str(root),
                    "case_dir_contains_dicoms": True,
                    "private_by_assignment": True,
                }
            ]

            with app.app_context():
                rows = list(_iter_case_dirs("functional", ["CMR_SCS_PAH_TEST"]))
                configured = _configured_functional_datasets()

            self.assertEqual(
                [(dataset, case_id, path.name) for _, dataset, case_id, path in rows],
                [("CMR_SCS_PAH_TEST", "PAH-5", "PAH-5")],
            )
            self.assertTrue(configured[0]["private_by_assignment"])
            sequences, dicom_count, has_dicom = _sequence_summary(root / "PAH-5")
            self.assertEqual(sequences, [{"name": "901029", "dicom_count": 1}])
            self.assertEqual(dicom_count, 1)
            self.assertTrue(has_dicom)

    def test_numbered_pah_cases_keep_split_sax_series_inside_each_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "first-sax-category"
            (root / "001" / "601").mkdir(parents=True)
            (root / "001" / "601" / "1_0.dcm").touch()
            (root / "014" / "14").mkdir(parents=True)
            (root / "014" / "15").mkdir(parents=True)
            (root / "014" / "14" / "1_0.dcm").touch()
            (root / "014" / "15" / "1_0.dcm").touch()

            app = Flask(__name__)
            app.config["DATA_ROOT"] = str(tmp_path / "missing")
            app.config["CVI_LIBRARY_MULTICENTER_ROOTS"] = [
                {
                    "dataset": "CMR_SCS_PAH_1",
                    "label": "SCS PAH first SAX category",
                    "path": str(root),
                    "case_dir_contains_dicoms": True,
                    "private_by_assignment": True,
                }
            ]

            with app.app_context():
                rows = list(_iter_case_dirs("functional", ["CMR_SCS_PAH_1"]))
                configured = _configured_functional_datasets()

            self.assertEqual(
                [(dataset, case_id, path.name) for _, dataset, case_id, path in rows],
                [
                    ("CMR_SCS_PAH_1", "001", "001"),
                    ("CMR_SCS_PAH_1", "014", "014"),
                ],
            )
            self.assertTrue(configured[0]["private_by_assignment"])
            sequences, dicom_count, has_dicom = _sequence_summary(root / "014")
            self.assertEqual(
                sequences,
                [
                    {"name": "14", "dicom_count": 1},
                    {"name": "15", "dicom_count": 1},
                ],
            )
            self.assertEqual(dicom_count, 2)
            self.assertTrue(has_dicom)


class CatalogRefreshTest(unittest.TestCase):
    def test_catalog_refresh_scans_then_replaces_stale_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "center"
            sequence = root / "case-new" / "SAX"
            sequence.mkdir(parents=True)
            (sequence / "frame-001.dcm").touch()

            app = Flask(__name__)
            app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
            app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
            app.config["DATA_ROOT"] = str(tmp_path / "missing-annotation")
            app.config["CVI_LIBRARY_MULTICENTER_ROOTS"] = [
                {"dataset": "CENTER_A", "label": "Center A", "path": str(root)}
            ]
            db.init_app(app)

            with app.app_context():
                db.create_all()
                db.session.add(CviCaseCatalog(
                    source="functional",
                    dataset="CENTER_A",
                    case_id="case-stale",
                    full_id="CENTER_A/case-stale",
                    path=str(root / "case-stale"),
                ))
                db.session.commit()

                self.assertEqual(_refresh_case_catalog("functional", ["CENTER_A"]), 1)
                rows = CviCaseCatalog.query.order_by(CviCaseCatalog.case_id).all()

                self.assertEqual([row.case_id for row in rows], ["case-new"])
                self.assertEqual(rows[0].dicom_count, 1)
                self.assertTrue(rows[0].has_dicom)
