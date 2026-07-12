import csv
import tempfile
import unittest
from pathlib import Path

from flask import Flask

from backend.hospital_browser.routes import (
    _count_dirs_at_depth,
    _manifest_case_count,
    generate_inventory_data,
)
from backend.routes import (
    _assignment_dataset_library_presets,
    _parse_assignment_ordered_case_selection,
    _resolve_assignment_identifier_selection,
)
from extensions import db
from models import CviCaseCatalog


class AssignmentSelectionTest(unittest.TestCase):
    def test_order_selection_supports_ranges_and_keeps_library_order(self):
        ordered = ['case-a', 'case-b', 'case-c', 'case-d', 'case-e']

        selected = _parse_assignment_ordered_case_selection('1, 3-4, 2', ordered)

        self.assertEqual(selected, ['case-a', 'case-c', 'case-d', 'case-b'])

    def test_identifier_selection_accepts_registration_and_case_id(self):
        details = [
            {
                'case_id': 'internal-a',
                'anon_label': '病例001',
                'primary_id': 'REG-A',
                'public_case_code': 'REG-A_20260101',
            },
            {
                'case_id': 'internal-b',
                'anon_label': '病例002',
                'primary_id': 'REG-B',
                'public_case_code': 'REG-B_20260102',
            },
        ]

        selected, warnings = _resolve_assignment_identifier_selection('REG-A\ninternal-b', details)

        self.assertEqual(selected, ['internal-a', 'internal-b'])
        self.assertEqual(warnings, [])

    def test_repeated_registration_selects_all_studies_with_warning(self):
        details = [
            {'case_id': 'study-a', 'primary_id': 'REG-A'},
            {'case_id': 'study-b', 'primary_id': 'REG-A'},
        ]

        selected, warnings = _resolve_assignment_identifier_selection('REG-A', details)

        self.assertEqual(selected, ['study-a', 'study-b'])
        self.assertEqual(len(warnings), 1)
        self.assertIn('多次检查', warnings[0])


class AssignmentLibraryPresetTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        self.app.config['CVI_LIBRARY_MULTICENTER_ROOTS'] = [
            {'dataset': 'CENTER_A', 'label': '中心 A', 'path': '/not-used'},
            {'dataset': 'CENTER_B', 'label': '中心 B', 'path': '/not-used'},
        ]
        db.init_app(self.app)
        with self.app.app_context():
            db.create_all()
            db.session.add_all([
                CviCaseCatalog(
                    source='functional', dataset='CENTER_A', case_id='case-1',
                    full_id='functional/CENTER_A/case-1', path='/tmp/case-1', has_dicom=True,
                ),
                CviCaseCatalog(
                    source='functional', dataset='CENTER_A', case_id='case-2',
                    full_id='functional/CENTER_A/case-2', path='/tmp/case-2', has_dicom=False,
                ),
            ])
            db.session.commit()

    def test_all_configured_centers_are_listed_with_assignable_counts(self):
        with self.app.app_context():
            presets = _assignment_dataset_library_presets()

        self.assertEqual([item['dataset'] for item in presets], ['CENTER_A', 'CENTER_B'])
        self.assertEqual(presets[0]['case_count'], 1)
        self.assertEqual(presets[1]['case_count'], 0)


class HospitalInventoryCountTest(unittest.TestCase):
    def test_directory_depth_count_uses_configured_study_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'group-a' / 'subject-a' / 'study-1').mkdir(parents=True)
            (root / 'group-a' / 'subject-a' / 'study-2').mkdir(parents=True)
            (root / 'group-b' / 'subject-b' / 'study-3').mkdir(parents=True)

            self.assertEqual(_count_dirs_at_depth(str(root), 1), 2)
            self.assertEqual(_count_dirs_at_depth(str(root), 3), 3)

    def test_manifest_count_requires_sequence_and_relative_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / 'manifest.csv'
            with manifest.open('w', encoding='utf-8', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=['case_sequence', 'source_relative_dir'])
                writer.writeheader()
                writer.writerow({'case_sequence': '1', 'source_relative_dir': 'a/b/c'})
                writer.writerow({'case_sequence': '2', 'source_relative_dir': 'a/b/d'})
                writer.writerow({'case_sequence': '', 'source_relative_dir': 'a/b/e'})

            self.assertEqual(_manifest_case_count(str(manifest)), 2)

    def test_inventory_separates_raw_catalog_and_imported_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'case-a').mkdir()
            (root / 'case-b').mkdir()
            app = Flask(__name__)
            app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
            app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
            app.config['CVI_LIBRARY_MULTICENTER_ROOTS'] = [
                {'dataset': 'CENTER_C', 'label': '中心 C', 'path': str(root)},
            ]
            db.init_app(app)
            with app.app_context():
                db.create_all()
                db.session.add_all([
                    CviCaseCatalog(
                        source='functional', dataset='CENTER_C', case_id='case-a',
                        full_id='functional/CENTER_C/case-a', path=str(root / 'case-a'),
                        has_dicom=True, cvi_study_id=10,
                    ),
                    CviCaseCatalog(
                        source='functional', dataset='CENTER_C', case_id='case-b',
                        full_id='functional/CENTER_C/case-b', path=str(root / 'case-b'),
                        has_dicom=True,
                    ),
                ])
                db.session.commit()

                payload = generate_inventory_data()

            item = payload['items'][0]
            self.assertEqual(item['raw_candidate_count'], 2)
            self.assertEqual(item['catalog_count'], 2)
            self.assertEqual(item['imported_count'], 1)
            self.assertEqual(item['classification_status'], 'pending')


if __name__ == '__main__':
    unittest.main()
