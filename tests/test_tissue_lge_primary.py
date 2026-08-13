import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, generate_uid

from apps.api import db
from apps.api.services.dicom_indexer import (
    fetch_study_detail,
    import_study,
    set_tissue_lge_primary_series,
    update_series_role,
)


class TissueLgePrimaryTest(unittest.TestCase):
    def _write_lge_dicom(
        self,
        path: Path,
        *,
        study_uid: str,
        series_uid: str,
        series_number: int,
    ) -> None:
        file_meta = FileMetaDataset()
        file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        file_meta.MediaStorageSOPClassUID = MRImageStorage
        file_meta.MediaStorageSOPInstanceUID = generate_uid()
        dataset = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
        dataset.is_little_endian = True
        dataset.is_implicit_VR = False
        dataset.StudyInstanceUID = study_uid
        dataset.SeriesInstanceUID = series_uid
        dataset.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
        dataset.SOPClassUID = MRImageStorage
        dataset.PatientID = "TEST-TISSUE-LGE"
        dataset.StudyDate = "20260813"
        dataset.SeriesNumber = series_number
        dataset.InstanceNumber = 1
        dataset.SeriesDescription = f"PSIR LGE SAX {series_number}"
        dataset.ProtocolName = dataset.SeriesDescription
        dataset.ImageType = ["ORIGINAL", "PRIMARY", "M", "IR"]
        dataset.Rows = 64
        dataset.Columns = 64
        dataset.PixelSpacing = [1.5, 1.5]
        dataset.SliceThickness = 8.0
        dataset.ImagePositionPatient = [0.0, 0.0, float(series_number * 8)]
        dataset.ImageOrientationPatient = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        dataset.AcquisitionTime = f"12000{series_number}.000"
        dataset.TriggerTime = 0.0
        dataset.TemporalPositionIdentifier = 1
        FileDataset.save_as(dataset, str(path), write_like_original=False)

    def _create_study(self, database_path: Path) -> tuple[int, list[int]]:
        with patch.object(db, "DB_PATH", database_path):
            db.init_db()
            with db.get_conn() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO studies (
                      study_uid, patient_name, patient_id, study_date, accession_number,
                      source_path, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("study-1", "", "", "", "", "/test/study", db.utcnow()),
                )
                study_id = int(cursor.lastrowid)
                series_ids = []
                for index, (role, metadata) in enumerate((
                    ("lge_sax", {"source": "first", "tissue_lge_primary": True}),
                    ("lge_sax", {"source": "second"}),
                    ("lge_lax", {"source": "lax", "tissue_lge_primary": True}),
                ), start=1):
                    cursor = conn.execute(
                        """
                        INSERT INTO series (
                          study_id, series_uid, description, role, rows, cols,
                          pixel_spacing_x, pixel_spacing_y, slice_thickness, file_count,
                          slice_count, phase_count, orientation, folder_path,
                          has_predictions, metadata_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            study_id, f"series-{index}", f"LGE {index}", role, 128, 128,
                            1.0, 1.0, 8.0, 1, 1, 1, "SAX", f"/test/series-{index}",
                            0, db.dumps(metadata), db.utcnow(),
                        ),
                    )
                    series_ids.append(int(cursor.lastrowid))
                conn.execute(
                    "INSERT INTO reports (study_id, status, findings, summary, payload_json, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (study_id, "草稿", "", "", "{}", db.utcnow()),
                )
            return study_id, series_ids

    def test_selecting_second_lge_sax_is_persistent_unique_and_sorted_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            database_path = Path(tmp) / "cvi.db"
            study_id, series_ids = self._create_study(database_path)
            with patch.object(db, "DB_PATH", database_path):
                result = set_tissue_lge_primary_series(series_ids[1])
                detail = fetch_study_detail(study_id, "/test")

                self.assertEqual(result["series_id"], series_ids[1])
                self.assertEqual(result["study_id"], study_id)
                lge_sax = [item for item in detail["series"] if item["role"] == "lge_sax"]
                self.assertEqual([item["id"] for item in lge_sax], [series_ids[1], series_ids[0]])
                self.assertEqual(
                    [item["is_tissue_lge_primary"] for item in lge_sax],
                    [True, False],
                )

                conn = sqlite3.connect(database_path)
                rows = conn.execute(
                    "SELECT id, metadata_json FROM series WHERE study_id = ? ORDER BY id",
                    (study_id,),
                ).fetchall()
                conn.close()
                metadata = {row[0]: db.loads(row[1], {}) for row in rows}
                self.assertEqual(metadata[series_ids[0]], {"source": "first"})
                self.assertEqual(
                    metadata[series_ids[1]],
                    {"source": "second", "tissue_lge_primary": True},
                )
                self.assertEqual(metadata[series_ids[2]], {"source": "lax"})

    def test_non_sax_lge_cannot_be_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            database_path = Path(tmp) / "cvi.db"
            _, series_ids = self._create_study(database_path)
            with patch.object(db, "DB_PATH", database_path):
                with self.assertRaisesRegex(ValueError, "lge_sax"):
                    set_tissue_lge_primary_series(series_ids[2])
                with self.assertRaises(KeyError):
                    set_tissue_lge_primary_series(999999)

    def test_changing_primary_series_role_clears_primary_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            database_path = Path(tmp) / "cvi.db"
            _, series_ids = self._create_study(database_path)
            with patch.object(db, "DB_PATH", database_path):
                update_series_role(series_ids[0], "lge_lax")
                with db.get_conn() as conn:
                    row = conn.execute(
                        "SELECT role, metadata_json FROM series WHERE id = ?",
                        (series_ids[0],),
                    ).fetchone()
                self.assertEqual(row["role"], "lge_lax")
                self.assertEqual(db.loads(row["metadata_json"], {}), {"source": "first"})

    def test_reimport_preserves_manual_roles_and_tissue_lge_primary_by_series_uid(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            study_root = tmp_path / "study"
            study_root.mkdir()
            study_uid = generate_uid()
            first_source_series_uid = generate_uid()
            second_source_series_uid = generate_uid()
            self._write_lge_dicom(
                study_root / "first.dcm",
                study_uid=study_uid,
                series_uid=first_source_series_uid,
                series_number=1,
            )
            self._write_lge_dicom(
                study_root / "second.dcm",
                study_uid=study_uid,
                series_uid=second_source_series_uid,
                series_number=2,
            )

            database_path = tmp_path / "cvi.db"
            with patch.object(db, "DB_PATH", database_path):
                first_study_id = import_study(str(study_root))
                with db.get_conn() as conn:
                    first_rows = conn.execute(
                        "SELECT id, series_uid FROM series WHERE study_id = ?",
                        (first_study_id,),
                    ).fetchall()
                series_ids_by_uid = {row["series_uid"]: int(row["id"]) for row in first_rows}
                self.assertEqual(len(series_ids_by_uid), 2)
                first_series_uid, second_series_uid = sorted(series_ids_by_uid)
                first_series_id = series_ids_by_uid[first_series_uid]
                second_series_id = series_ids_by_uid[second_series_uid]
                update_series_role(first_series_id, "cine_lax_4ch")
                update_series_role(second_series_id, "lge_sax")
                set_tissue_lge_primary_series(second_series_id)

                second_study_id = import_study(str(study_root))
                self.assertNotEqual(first_study_id, second_study_id)
                second_detail = fetch_study_detail(second_study_id, str(study_root))
                detail_by_id = {item["id"]: item for item in second_detail["series"]}
                with db.get_conn() as conn:
                    second_rows = conn.execute(
                        "SELECT id, series_uid FROM series WHERE study_id = ?",
                        (second_study_id,),
                    ).fetchall()
                restored_ids_by_uid = {row["series_uid"]: int(row["id"]) for row in second_rows}
                restored_first = detail_by_id[restored_ids_by_uid[first_series_uid]]
                restored_second = detail_by_id[restored_ids_by_uid[second_series_uid]]
                self.assertEqual(restored_first["role"], "cine_lax_4ch")
                self.assertFalse(restored_first["is_tissue_lge_primary"])
                self.assertEqual(restored_second["role"], "lge_sax")
                self.assertTrue(restored_second["is_tissue_lge_primary"])


if __name__ == "__main__":
    unittest.main()
