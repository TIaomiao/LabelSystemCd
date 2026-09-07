from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import EnhancedMRImageStorage, ExplicitVRLittleEndian, generate_uid

from apps.api import db
from apps.api.services.dicom_indexer import (
    import_study,
    infer_role,
    list_frame_rows,
    normalize_series_role,
    read_frame_pixels,
)


def _functional_group(slice_index: int, phase_index: int, frame_index: int) -> Dataset:
    group = Dataset()

    position = Dataset()
    position.ImagePositionPatient = [0.0, 0.0, float(slice_index * 8)]
    group.PlanePositionSequence = Sequence([position])

    orientation = Dataset()
    orientation.ImageOrientationPatient = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    group.PlaneOrientationSequence = Sequence([orientation])

    measures = Dataset()
    measures.PixelSpacing = [1.5, 1.5]
    measures.SliceThickness = 8.0
    group.PixelMeasuresSequence = Sequence([measures])

    cardiac = Dataset()
    cardiac.NominalCardiacTriggerDelayTime = float(phase_index * 40)
    group.CardiacSynchronizationSequence = Sequence([cardiac])

    content = Dataset()
    content.TemporalPositionIndex = phase_index + 1
    content.FrameAcquisitionNumber = frame_index + 1
    group.FrameContentSequence = Sequence([content])

    transform = Dataset()
    transform.RescaleSlope = 1.0
    transform.RescaleIntercept = 0.0
    group.PixelValueTransformationSequence = Sequence([transform])
    return group


def _write_enhanced_mr(
    path: Path,
    *,
    study_uid: str | None = None,
    series_uid: str | None = None,
    description: str = "B-TFE_M2D_SA",
) -> None:
    file_meta = FileMetaDataset()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.MediaStorageSOPClassUID = EnhancedMRImageStorage
    file_meta.MediaStorageSOPInstanceUID = generate_uid()

    dataset = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    dataset.is_little_endian = True
    dataset.is_implicit_VR = False
    dataset.SOPClassUID = EnhancedMRImageStorage
    dataset.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    dataset.StudyInstanceUID = study_uid or generate_uid()
    dataset.SeriesInstanceUID = series_uid or generate_uid()
    dataset.PatientID = "TEST-ENHANCED-MR"
    dataset.StudyDate = "20260907"
    dataset.SeriesDescription = description
    dataset.ProtocolName = "SURVEY"
    dataset.ImageType = ["ORIGINAL", "PRIMARY", "M_FFE", "M", "FFE"]
    dataset.ScanningSequence = "GR"
    dataset.SequenceVariant = "SK"
    dataset.MRAcquisitionType = "2D"
    dataset.SeriesNumber = 1
    dataset.InstanceNumber = 1
    dataset.Rows = 8
    dataset.Columns = 8
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.BitsAllocated = 16
    dataset.BitsStored = 16
    dataset.HighBit = 15
    dataset.PixelRepresentation = 0
    dataset.NumberOfFrames = 6

    frames = []
    groups = []
    for slice_index in range(2):
        for phase_index in range(3):
            frame_index = slice_index * 3 + phase_index
            pixels = np.arange(64, dtype=np.uint16).reshape(8, 8)
            pixels = np.roll(pixels, frame_index, axis=1)
            frames.append(pixels)
            groups.append(_functional_group(slice_index, phase_index, frame_index))
    dataset.PerFrameFunctionalGroupsSequence = Sequence(groups)
    dataset.SharedFunctionalGroupsSequence = Sequence([Dataset()])
    dataset.PixelData = np.stack(frames).tobytes()
    pydicom.dcmwrite(str(path), dataset, write_like_original=False)


class EnhancedMrImportTest(unittest.TestCase):
    def test_explicit_cine_description_wins_over_stale_survey_protocol(self):
        kwargs = {"protocol_name": "SURVEY"}
        self.assertEqual(
            infer_role(Path("DICOM"), "B-TFE_M2D_SA", 18, 30, **kwargs),
            "cine_sax",
        )
        self.assertEqual(
            normalize_series_role(
                Path("DICOM"),
                "B-TFE_4CH",
                "unknown",
                1,
                30,
                **kwargs,
            ),
            "cine_lax_4ch",
        )

    def test_import_expands_geometry_phase_and_pixels(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "study"
            source.mkdir()
            _write_enhanced_mr(source / "enhanced.dcm")

            with patch.object(db, "DB_PATH", tmp_path / "cvi.db"):
                study_id = import_study(str(source))
                conn = sqlite3.connect(db.DB_PATH)
                conn.row_factory = sqlite3.Row
                series = conn.execute(
                    "SELECT * FROM series WHERE study_id = ?", (study_id,)
                ).fetchone()
                self.assertEqual(series["role"], "cine_sax")
                self.assertEqual(series["file_count"], 6)
                self.assertEqual(series["slice_count"], 2)
                self.assertEqual(series["phase_count"], 3)
                conn.close()

                rows = list_frame_rows(series["id"])
                self.assertEqual(len(rows), 6)
                self.assertEqual(
                    [(row["slice_index"], row["phase_index"]) for row in rows],
                    [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)],
                )
                first = read_frame_pixels(rows[0])
                last = read_frame_pixels(rows[-1])
                self.assertEqual(first.shape, (8, 8))
                self.assertEqual(last.shape, (8, 8))
                self.assertFalse(np.array_equal(first, last))

    def test_reimport_does_not_restore_unknown_over_newly_detected_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "study"
            source.mkdir()
            _write_enhanced_mr(source / "enhanced.dcm")

            with patch.object(db, "DB_PATH", tmp_path / "cvi.db"):
                first_study_id = import_study(str(source))
                conn = sqlite3.connect(db.DB_PATH)
                conn.execute(
                    "UPDATE series SET role = 'unknown' WHERE study_id = ?",
                    (first_study_id,),
                )
                conn.commit()
                conn.close()

                second_study_id = import_study(str(source))
                conn = sqlite3.connect(db.DB_PATH)
                role = conn.execute(
                    "SELECT role FROM series WHERE study_id = ?", (second_study_id,)
                ).fetchone()[0]
                conn.close()
                self.assertEqual(role, "cine_sax")

    def test_separate_enhanced_acquisitions_with_same_description_do_not_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "study"
            source.mkdir()
            study_uid = generate_uid()
            _write_enhanced_mr(
                source / "first.dcm",
                study_uid=study_uid,
                series_uid=generate_uid(),
                description="PSIR_10min",
            )
            _write_enhanced_mr(
                source / "second.dcm",
                study_uid=study_uid,
                series_uid=generate_uid(),
                description="PSIR_10min",
            )

            with patch.object(db, "DB_PATH", tmp_path / "cvi.db"):
                study_id = import_study(str(source))
                conn = sqlite3.connect(db.DB_PATH)
                rows = conn.execute(
                    "SELECT file_count, slice_count, phase_count FROM series WHERE study_id = ?",
                    (study_id,),
                ).fetchall()
                conn.close()
                self.assertEqual(rows, [(6, 2, 3), (6, 2, 3)])


if __name__ == "__main__":
    unittest.main()
