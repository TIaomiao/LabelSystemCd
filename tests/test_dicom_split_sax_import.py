from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, RawDataStorage, generate_uid

from apps.api import db
from apps.api.services.dicom_indexer import (
    _image_orientation,
    _image_position,
    _pixel_spacing,
    import_study,
    infer_role,
    normalize_series_role,
)


def _write_dicom(
    path: Path,
    *,
    study_uid: str | None,
    series_uid: str,
    series_number: int,
    slice_index: int,
    phase_index: int,
    acquisition_offset_seconds: int = 0,
    sop_class_uid: str = MRImageStorage,
    include_dimensions: bool = True,
) -> None:
    file_meta = FileMetaDataset()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.MediaStorageSOPClassUID = sop_class_uid
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    dataset = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    dataset.is_little_endian = True
    dataset.is_implicit_VR = False
    if study_uid is not None:
        dataset.StudyInstanceUID = study_uid
    dataset.SeriesInstanceUID = series_uid
    dataset.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    dataset.SOPClassUID = file_meta.MediaStorageSOPClassUID
    dataset.PatientID = "TEST-SPLIT-SAX"
    dataset.StudyDate = "20260716"
    dataset.SeriesNumber = series_number
    dataset.InstanceNumber = phase_index + 1
    dataset.SeriesDescription = "cine_tf2d16_retro_iPAT_8sl"
    dataset.ProtocolName = "cine_tf2d16_retro_iPAT_8sl"
    acquisition_seconds = acquisition_offset_seconds + slice_index * 10 + phase_index / 1000
    acquisition_hour = 12 + int(acquisition_seconds // 3600)
    acquisition_remainder = acquisition_seconds % 3600
    acquisition_minute = int(acquisition_remainder // 60)
    acquisition_second = acquisition_remainder % 60
    dataset.AcquisitionTime = f"{acquisition_hour:02d}{acquisition_minute:02d}{acquisition_second:06.3f}"
    dataset.TriggerTime = float(phase_index * 40)
    dataset.TemporalPositionIdentifier = phase_index + 1
    dataset.ImagePositionPatient = [0.0, 0.0, float(slice_index * 8)]
    dataset.ImageOrientationPatient = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    if include_dimensions:
        dataset.Rows = 64
        dataset.Columns = 64
        dataset.PixelSpacing = [1.5, 1.5]
    dataset.SliceThickness = 8.0
    pydicom.dcmwrite(str(path), dataset, write_like_original=False)


class SplitSaxImportTest(unittest.TestCase):
    def test_malformed_scalar_geometry_tags_fall_back_without_crashing(self):
        dataset = type(
            "MalformedGeometryDataset",
            (),
            {
                "ImagePositionPatient": 3.5,
                "ImageOrientationPatient": 1.0,
                "PixelSpacing": 1.25,
            },
        )()
        self.assertEqual(_image_position(dataset), [0.0, 0.0, 0.0])
        self.assertEqual(_image_orientation(dataset), [1.0, 0.0, 0.0, 0.0, 1.0, 0.0])
        self.assertEqual(_pixel_spacing(dataset), (1.0, 1.0))

    def test_localizer_and_perfusion_names_do_not_claim_function_roles(self):
        self.assertEqual(infer_role(Path("define_sax"), "define_sax", 12, 2), "unknown")
        self.assertEqual(
            infer_role(Path("dynamic_tfl_sr_epat_4ch"), "dynamic_tfl_sr_epat_4ch", 1, 50),
            "unknown",
        )
        self.assertEqual(
            normalize_series_role(
                Path("dynamic_tfl_sr_epat_4ch"),
                "dynamic_tfl_sr_epat_4ch",
                "unknown",
                1,
                50,
            ),
            "unknown",
        )

    def test_four_slice_philips_sbtfe_stack_is_cine_sax_but_three_slices_are_not(self):
        kwargs = {
            "protocol_name": "sBTFE_BH",
            "image_type": "ORIGINAL PRIMARY M_FFE M FFE",
            "scanning_sequence": "GR",
            "sequence_variant": "SK",
            "mr_acquisition_type": "2D",
            "philips_slice_orientation": "CORONAL",
        }
        self.assertEqual(infer_role(Path("601"), "sBTFE_BH", 4, 25, **kwargs), "cine_sax")
        self.assertEqual(infer_role(Path("601"), "sBTFE_BH", 3, 25, **kwargs), "unknown")

    def test_import_skips_non_renderable_dicom_and_fails_cleanly_without_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch.object(db, "DB_PATH", tmp_path / "cvi.db"):
                mixed_root = tmp_path / "mixed"
                mixed_root.mkdir()
                study_uid = generate_uid()
                series_uid = generate_uid()
                _write_dicom(
                    mixed_root / "image.dcm",
                    study_uid=study_uid,
                    series_uid=series_uid,
                    series_number=1,
                    slice_index=0,
                    phase_index=0,
                )
                _write_dicom(
                    mixed_root / "raw-data.dcm",
                    study_uid=study_uid,
                    series_uid=generate_uid(),
                    series_number=2,
                    slice_index=0,
                    phase_index=0,
                    sop_class_uid=RawDataStorage,
                )
                raw_dataset = pydicom.dcmread(
                    str(mixed_root / "raw-data.dcm"), stop_before_pixels=True
                )
                self.assertEqual((int(raw_dataset.Rows), int(raw_dataset.Columns)), (64, 64))

                study_id = import_study(str(mixed_root))
                conn = sqlite3.connect(db.DB_PATH)
                self.assertEqual(
                    conn.execute(
                        """
                        SELECT COUNT(*) FROM frames
                        WHERE series_id IN (SELECT id FROM series WHERE study_id = ?)
                        """,
                        (study_id,),
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM series WHERE study_id = ?", (study_id,)).fetchone()[0],
                    1,
                )
                conn.close()

                raw_only_root = tmp_path / "raw-only"
                raw_only_root.mkdir()
                _write_dicom(
                    raw_only_root / "raw-data.dcm",
                    study_uid=generate_uid(),
                    series_uid=generate_uid(),
                    series_number=1,
                    slice_index=0,
                    phase_index=0,
                    sop_class_uid=RawDataStorage,
                )
                with self.assertRaisesRegex(ValueError, "No renderable DICOM image objects"):
                    import_study(str(raw_only_root))

    def test_missing_study_uid_uses_stable_source_scoped_identity_and_restores_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch.object(db, "DB_PATH", tmp_path / "cvi.db"):
                study_root = tmp_path / "missing-study-uid"
                study_root.mkdir()
                _write_dicom(
                    study_root / "image.dcm",
                    study_uid=None,
                    series_uid=generate_uid(),
                    series_number=1,
                    slice_index=0,
                    phase_index=0,
                )

                first_study_id = import_study(str(study_root))
                conn = sqlite3.connect(db.DB_PATH)
                first_uid = conn.execute(
                    "SELECT study_uid FROM studies WHERE id = ?", (first_study_id,)
                ).fetchone()[0]
                first_series_uid = conn.execute(
                    "SELECT series_uid FROM series WHERE study_id = ?", (first_study_id,)
                ).fetchone()[0]
                self.assertTrue(first_uid.startswith("missing-study-uid:source:"))
                conn.execute(
                    "UPDATE reports SET summary = ? WHERE study_id = ?",
                    ("retain-on-reimport", first_study_id),
                )
                conn.commit()
                conn.close()

                second_study_id = import_study(str(study_root))
                conn = sqlite3.connect(db.DB_PATH)
                row = conn.execute(
                    """
                    SELECT s.study_uid, se.series_uid, r.summary
                    FROM studies s
                    JOIN series se ON se.study_id = s.id
                    JOIN reports r ON r.study_id = s.id
                    WHERE s.id = ?
                    """,
                    (second_study_id,),
                ).fetchone()
                self.assertEqual(row, (first_uid, first_series_uid, "retain-on-reimport"))
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM studies").fetchone()[0], 1)
                conn.close()

    def test_same_dicom_uids_from_two_sources_remain_distinct_and_reimport_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch.object(db, "DB_PATH", tmp_path / "cvi.db"):
                first_root = tmp_path / "source-a"
                second_root = tmp_path / "source-b"
                first_root.mkdir()
                second_root.mkdir()
                study_uid = generate_uid()
                series_uid = generate_uid()
                for root in (first_root, second_root):
                    _write_dicom(
                        root / "image.dcm",
                        study_uid=study_uid,
                        series_uid=series_uid,
                        series_number=1,
                        slice_index=0,
                        phase_index=0,
                    )

                first_study_id = import_study(str(first_root))
                conn = sqlite3.connect(db.DB_PATH)
                conn.execute(
                    "UPDATE reports SET summary = ? WHERE study_id = ?",
                    ("source-a-state", first_study_id),
                )
                conn.commit()
                conn.close()

                second_study_id = import_study(str(second_root))
                conn = sqlite3.connect(db.DB_PATH)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT s.id, s.study_uid, s.source_path, se.series_uid, r.summary
                    FROM studies s
                    JOIN series se ON se.study_id = s.id
                    JOIN reports r ON r.study_id = s.id
                    ORDER BY s.source_path
                    """
                ).fetchall()
                self.assertEqual(len(rows), 2)
                first_row, second_row = rows
                self.assertEqual(first_row["study_uid"], study_uid)
                self.assertEqual(first_row["summary"], "source-a-state")
                self.assertEqual(second_row["summary"], "")
                self.assertNotEqual(first_row["study_uid"], second_row["study_uid"])
                self.assertNotEqual(first_row["series_uid"], second_row["series_uid"])
                second_internal_uid = second_row["study_uid"]
                second_internal_series_uid = second_row["series_uid"]
                conn.execute(
                    "UPDATE reports SET summary = ? WHERE study_id = ?",
                    ("source-b-state", second_study_id),
                )
                conn.commit()
                conn.close()

                reimported_second_id = import_study(str(second_root))
                conn = sqlite3.connect(db.DB_PATH)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT s.id, s.study_uid, s.source_path, se.series_uid, r.summary
                    FROM studies s
                    JOIN series se ON se.study_id = s.id
                    JOIN reports r ON r.study_id = s.id
                    ORDER BY s.source_path
                    """
                ).fetchall()
                self.assertEqual(len(rows), 2)
                first_row, second_row = rows
                self.assertEqual(first_row["id"], first_study_id)
                self.assertEqual(first_row["summary"], "source-a-state")
                self.assertEqual(second_row["id"], reimported_second_id)
                self.assertEqual(second_row["study_uid"], second_internal_uid)
                self.assertEqual(second_row["series_uid"], second_internal_series_uid)
                self.assertEqual(second_row["summary"], "source-b-state")
                conn.close()

                reimported_first_id = import_study(str(first_root))
                conn = sqlite3.connect(db.DB_PATH)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT s.id, s.study_uid, s.source_path, se.series_uid, r.summary
                    FROM studies s
                    JOIN series se ON se.study_id = s.id
                    JOIN reports r ON r.study_id = s.id
                    ORDER BY s.source_path
                    """
                ).fetchall()
                self.assertEqual(len(rows), 2)
                first_row, second_row = rows
                self.assertEqual(first_row["id"], reimported_first_id)
                self.assertEqual(first_row["study_uid"], study_uid)
                self.assertEqual(first_row["summary"], "source-a-state")
                self.assertEqual(second_row["study_uid"], second_internal_uid)
                self.assertEqual(second_row["series_uid"], second_internal_series_uid)
                self.assertEqual(second_row["summary"], "source-b-state")
                conn.close()

    def test_import_merges_contiguous_single_slice_cine_series_into_sax_stack(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch.object(db, "DB_PATH", tmp_path / "cvi.db"):
                study_root = tmp_path / "study"
                study_root.mkdir()
                study_uid = generate_uid()
                for slice_index in range(5):
                    series_dir = study_root / f"series-{slice_index + 1:02d}"
                    series_dir.mkdir()
                    series_uid = generate_uid()
                    for phase_index in range(20):
                        _write_dicom(
                            series_dir / f"image-{phase_index + 1:03d}.dcm",
                            study_uid=study_uid,
                            series_uid=series_uid,
                            series_number=20 + slice_index,
                            slice_index=slice_index,
                            phase_index=phase_index,
                        )

                study_id = import_study(str(study_root))

                conn = sqlite3.connect(db.DB_PATH)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT role, description, file_count, slice_count, phase_count FROM series WHERE study_id = ?",
                    (study_id,),
                ).fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual(
                    dict(rows[0]),
                    {
                        "role": "cine_sax",
                        "description": "cine_tf2d16_retro_iPAT_8sl",
                        "file_count": 100,
                        "slice_count": 5,
                        "phase_count": 20,
                    },
                )
                frame_count = conn.execute("SELECT COUNT(*) FROM frames").fetchone()[0]
                self.assertEqual(frame_count, 100)
                conn.close()

    def test_import_keeps_repeated_split_sax_acquisitions_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch.object(db, "DB_PATH", tmp_path / "cvi.db"):
                study_root = tmp_path / "study"
                study_root.mkdir()
                study_uid = generate_uid()
                for repeat in range(2):
                    for slice_index in range(5):
                        series_number = 20 + repeat * 5 + slice_index
                        series_dir = study_root / f"series-{series_number:02d}"
                        series_dir.mkdir()
                        series_uid = generate_uid()
                        for phase_index in range(20):
                            _write_dicom(
                                series_dir / f"image-{phase_index + 1:03d}.dcm",
                                study_uid=study_uid,
                                series_uid=series_uid,
                                series_number=series_number,
                                slice_index=slice_index,
                                phase_index=phase_index,
                                acquisition_offset_seconds=repeat * 600,
                            )

                study_id = import_study(str(study_root))

                conn = sqlite3.connect(db.DB_PATH)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT role, file_count, slice_count, phase_count FROM series WHERE study_id = ? ORDER BY id",
                    (study_id,),
                ).fetchall()
                self.assertEqual(
                    [dict(row) for row in rows],
                    [
                        {"role": "cine_sax", "file_count": 100, "slice_count": 5, "phase_count": 20},
                        {"role": "cine_sax", "file_count": 100, "slice_count": 5, "phase_count": 20},
                    ],
                )
                conn.close()
