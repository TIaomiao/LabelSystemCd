import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from werkzeug.datastructures import MultiDict


sys.path.insert(0, "backend")

import cvi_workstation
from extensions import db
from models import CaseAssignment, CviCaseCatalog, User


class CviPrivateAssignmentGuardTest(unittest.TestCase):
    PRIVATE_STUDY_ID = 701
    PUBLIC_STUDY_ID = 702
    HIERARCHICAL_PRIVATE_STUDY_ID = 703
    UNMAPPED_PRIVATE_STUDY_ID = 704
    UNMAPPED_PUBLIC_STUDY_ID = 705
    NO_ASSIGNMENT_PRIVATE_STUDY_ID = 706
    HIERARCHICAL_PUBLIC_STUDY_ID = 707
    PRIVATE_SERIES_ID = 801
    PUBLIC_SERIES_ID = 802

    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config.update(
            SQLALCHEMY_DATABASE_URI="sqlite://",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            SECRET_KEY="test-only",
            DATA_ROOT="/missing-data-root",
            FUNCTIONAL_DATA_ROOT="/missing-functional-root",
            EVAL_ROOT="/missing-eval-root",
            CVI_LIBRARY_MULTICENTER_ROOTS=[
                {
                    "dataset": "PRIVATE_CENTER",
                    "path": "/private-root",
                    "private_by_assignment": True,
                },
                {
                    "dataset": "PUBLIC_CENTER",
                    "path": "/public-root",
                },
            ],
        )
        db.init_app(cls.app)
        cvi_workstation.register_cvi_workstation_routes(cls.app)
        with cls.app.app_context():
            db.create_all()
            assigned_user = User(username="assigned", is_approved=True, is_admin=False)
            unassigned_user = User(username="unassigned", is_approved=True, is_admin=False)
            admin_user = User(username="admin", is_approved=True, is_admin=True)
            db.session.add_all([assigned_user, unassigned_user, admin_user])
            db.session.flush()
            cls.assigned_user_id = assigned_user.id
            cls.unassigned_user_id = unassigned_user.id
            cls.admin_user_id = admin_user.id

            db.session.add_all([
                CviCaseCatalog(
                    source="functional",
                    dataset="PRIVATE_CENTER",
                    case_id="private-case",
                    full_id="PRIVATE_CENTER/private-case",
                    path="/private-case",
                    has_dicom=True,
                    cvi_study_id=cls.PRIVATE_STUDY_ID,
                ),
                CviCaseCatalog(
                    source="functional",
                    dataset="PUBLIC_CENTER",
                    case_id="public-case",
                    full_id="PUBLIC_CENTER/public-case",
                    path="/public-case",
                    has_dicom=True,
                    cvi_study_id=cls.PUBLIC_STUDY_ID,
                ),
                CviCaseCatalog(
                    source="functional",
                    dataset="PRIVATE_CENTER",
                    case_id="group-a/case-01",
                    full_id="PRIVATE_CENTER/group-a/case-01",
                    path="/private-root/group-a/case-01",
                    has_dicom=True,
                    cvi_study_id=cls.HIERARCHICAL_PRIVATE_STUDY_ID,
                ),
                CviCaseCatalog(
                    source="functional",
                    dataset="PRIVATE_CENTER",
                    case_id="no-assignment-case",
                    full_id="PRIVATE_CENTER/no-assignment-case",
                    path="/private-root/no-assignment-case",
                    has_dicom=True,
                    cvi_study_id=cls.NO_ASSIGNMENT_PRIVATE_STUDY_ID,
                ),
                CviCaseCatalog(
                    source="functional",
                    dataset="PUBLIC_CENTER",
                    case_id="public-group-a/case-02",
                    full_id="PUBLIC_CENTER/public-group-a/case-02",
                    path="/public-root/public-group-a/case-02",
                    has_dicom=True,
                    cvi_study_id=cls.HIERARCHICAL_PUBLIC_STUDY_ID,
                ),
                CaseAssignment(
                    namespace="functional",
                    dataset="PRIVATE_CENTER",
                    case_id="private-case",
                    user_id=assigned_user.id,
                    active=True,
                ),
                CaseAssignment(
                    namespace="functional",
                    dataset="PRIVATE_CENTER",
                    case_id="private-case",
                    user_id=unassigned_user.id,
                    active=False,
                ),
                CaseAssignment(
                    namespace="functional",
                    dataset="PRIVATE_CENTER",
                    case_id="group-b/case-01",
                    user_id=unassigned_user.id,
                    active=True,
                ),
                CaseAssignment(
                    namespace="functional",
                    dataset="PRIVATE_CENTER",
                    case_id="group-a/case-01",
                    user_id=assigned_user.id,
                    active=True,
                ),
                CaseAssignment(
                    namespace="functional",
                    dataset="PUBLIC_CENTER",
                    case_id="public-group-b/case-02",
                    user_id=unassigned_user.id,
                    active=True,
                ),
            ])
            db.session.commit()

    def setUp(self):
        with cvi_workstation.CVI_SERIES_STUDY_CACHE_LOCK:
            cvi_workstation.CVI_SERIES_STUDY_CACHE.clear()

    def _actor(self, user_id, *, is_admin=False):
        return SimpleNamespace(
            id=user_id,
            username=f"user-{user_id}",
            is_authenticated=True,
            is_admin=is_admin,
        )

    def _authorize(self, actor, path, *, method="GET", query_string=None, json=None):
        request_path = f"/cvi-api/{path}"
        with self.app.test_request_context(
            request_path,
            method=method,
            query_string=query_string,
            json=json,
        ):
            with patch.object(cvi_workstation, "current_user", actor):
                return cvi_workstation._authorize_cvi_proxy_request(path)

    def _catalog_case_ids(self, actor, dataset):
        selection = {
            "query_source": "functional",
            "dataset_filters": [dataset],
            "case_ids": None,
        }
        with self.app.test_request_context("/api/cvi-library/cases"):
            with patch.object(cvi_workstation, "current_user", actor):
                payload = cvi_workstation._catalog_payload(selection, "", 100)
        return {item["case_id"] for item in payload["items"]}

    def _import_catalog_case(self, actor, dataset, case_id):
        with self.app.test_request_context("/api/cvi-library/import", method="POST", json={}):
            catalog_case = CviCaseCatalog.query.filter_by(
                source="functional",
                dataset=dataset,
                case_id=case_id,
            ).one()
            view = self.app.view_functions["cvi_library_import"]
            while hasattr(view, "__wrapped__"):
                view = view.__wrapped__
            with patch.object(cvi_workstation, "current_user", actor):
                with patch.object(
                    cvi_workstation,
                    "_resolve_dicom_case_path",
                    return_value=Path(catalog_case.path),
                ) as resolve_path:
                    with patch.object(
                        cvi_workstation,
                        "_sequence_summary",
                        return_value=([], int(catalog_case.dicom_count or 0), True),
                    ):
                        with patch.object(cvi_workstation, "_verify_cvi_study", return_value=True):
                            response = self.app.make_response(view(catalog_case.id))
        return response, resolve_path.called

    def test_catalog_payload_private_cases_require_exact_active_assignment(self):
        assigned = self._actor(self.assigned_user_id)
        unassigned = self._actor(self.unassigned_user_id)
        admin = self._actor(self.admin_user_id, is_admin=True)

        self.assertEqual(
            self._catalog_case_ids(assigned, "PRIVATE_CENTER"),
            {"private-case", "group-a/case-01"},
        )
        self.assertEqual(self._catalog_case_ids(unassigned, "PRIVATE_CENTER"), set())
        self.assertEqual(
            self._catalog_case_ids(admin, "PRIVATE_CENTER"),
            {"private-case", "group-a/case-01", "no-assignment-case"},
        )

    def test_catalog_payload_keeps_public_alias_assignment_behavior(self):
        actor = self._actor(self.unassigned_user_id)
        self.assertEqual(
            self._catalog_case_ids(actor, "PUBLIC_CENTER"),
            {"public-group-a/case-02"},
        )

    def test_library_import_private_case_guard_is_fail_closed_and_exact(self):
        assigned = self._actor(self.assigned_user_id)
        unassigned = self._actor(self.unassigned_user_id)
        admin = self._actor(self.admin_user_id, is_admin=True)

        cases = (
            (unassigned, "no-assignment-case", 403, False),
            (unassigned, "private-case", 403, False),
            (assigned, "private-case", 200, True),
            (unassigned, "group-a/case-01", 403, False),
            (assigned, "group-a/case-01", 200, True),
            (admin, "no-assignment-case", 200, True),
        )
        for actor, case_id, expected_status, expected_resolved in cases:
            with self.subTest(actor=actor.username, case_id=case_id):
                response, resolved = self._import_catalog_case(
                    actor,
                    "PRIVATE_CENTER",
                    case_id,
                )
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(resolved, expected_resolved)

    def test_library_import_keeps_public_alias_assignment_behavior(self):
        actor = self._actor(self.unassigned_user_id)
        response, resolved = self._import_catalog_case(
            actor,
            "PUBLIC_CENTER",
            "public-group-a/case-02",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(resolved)

    def test_non_admin_cannot_bypass_catalog_with_filesystem_or_direct_import(self):
        actor = self._actor(self.unassigned_user_id)
        for path in ("fs/list", "fs/list/", "studies/import"):
            with self.subTest(path=path):
                response = self._authorize(actor, path, method="POST")
                self.assertIsNotNone(response)
                self.assertEqual(response.status_code, 403)

        admin = self._actor(self.admin_user_id, is_admin=True)
        self.assertIsNone(self._authorize(admin, "fs/list"))
        self.assertIsNone(self._authorize(admin, "studies/import", method="POST"))

    def test_private_study_routes_require_an_active_matching_assignment(self):
        unassigned = self._actor(self.unassigned_user_id)
        assigned = self._actor(self.assigned_user_id)
        private_paths = (
            f"studies/{self.PRIVATE_STUDY_ID}",
            f"reports/{self.PRIVATE_STUDY_ID}",
            f"exports/{self.PRIVATE_STUDY_ID}.csv",
            f"exports/{self.PRIVATE_STUDY_ID}.pdf",
        )
        for path in private_paths:
            with self.subTest(path=path, actor="unassigned"):
                response = self._authorize(unassigned, path)
                self.assertIsNotNone(response)
                self.assertEqual(response.status_code, 403)
            with self.subTest(path=path, actor="assigned"):
                self.assertIsNone(self._authorize(assigned, path))

        response = self._authorize(
            unassigned,
            "studies/annotation-summaries",
            query_string={"study_ids": f"{self.PUBLIC_STUDY_ID},{self.PRIVATE_STUDY_ID}"},
        )
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 403)

        repeated_response = self._authorize(
            unassigned,
            "studies/annotation-summaries",
            query_string=MultiDict([
                ("study_ids", str(self.PUBLIC_STUDY_ID)),
                ("study_ids", str(self.PRIVATE_STUDY_ID)),
            ]),
        )
        self.assertIsNotNone(repeated_response)
        self.assertEqual(repeated_response.status_code, 403)

    def test_public_or_unmapped_studies_keep_existing_non_admin_access(self):
        actor = self._actor(self.unassigned_user_id)
        self.assertIsNone(self._authorize(actor, f"studies/{self.PUBLIC_STUDY_ID}"))
        with patch.object(
            cvi_workstation,
            "_json_request",
            return_value=(200, {"matches": False}),
        ):
            self.assertIsNone(self._authorize(actor, f"studies/{self.UNMAPPED_PUBLIC_STUDY_ID}"))

    def test_unmapped_study_under_private_root_is_denied(self):
        actor = self._actor(self.unassigned_user_id)
        with patch.object(
            cvi_workstation,
            "_json_request",
            return_value=(200, {"matches": True}),
        ) as lookup:
            response = self._authorize(actor, f"studies/{self.UNMAPPED_PRIVATE_STUDY_ID}")
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 403)
        lookup.assert_called_once_with(
            f"/internal/studies/{self.UNMAPPED_PRIVATE_STUDY_ID}/source-membership",
            method="POST",
            payload={"roots": ["/private-root"]},
        )

    def test_hierarchical_case_requires_exact_catalog_case_assignment(self):
        actor = self._actor(self.unassigned_user_id)
        response = self._authorize(actor, f"studies/{self.HIERARCHICAL_PRIVATE_STUDY_ID}")
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 403)

    def test_series_contours_images_geometry_and_model_routes_share_cached_study_guard(self):
        actor = self._actor(self.unassigned_user_id)
        private_paths = (
            f"series/{self.PRIVATE_SERIES_ID}",
            f"series/{self.PRIVATE_SERIES_ID}/image",
            f"series/{self.PRIVATE_SERIES_ID}/geometry",
            f"series/{self.PRIVATE_SERIES_ID}/role",
            f"series/{self.PRIVATE_SERIES_ID}/prompt-segment",
            f"series/{self.PRIVATE_SERIES_ID}/model-frame-segment",
            f"series/{self.PRIVATE_SERIES_ID}/propagate-neighbor",
            f"series/{self.PRIVATE_SERIES_ID}/detect-phases",
            f"contours/{self.PRIVATE_SERIES_ID}",
            f"contours/{self.PRIVATE_SERIES_ID}/curvature",
        )
        with patch.object(
            cvi_workstation,
            "_json_request",
            return_value=(200, {"id": self.PRIVATE_SERIES_ID, "study_id": self.PRIVATE_STUDY_ID}),
        ) as lookup:
            for path in private_paths:
                with self.subTest(path=path):
                    response = self._authorize(actor, path)
                    self.assertIsNotNone(response)
                    self.assertEqual(response.status_code, 403)
            self.assertEqual(lookup.call_count, 1)

        assigned = self._actor(self.assigned_user_id)
        with patch.object(cvi_workstation, "_json_request") as lookup:
            self.assertIsNone(self._authorize(assigned, f"series/{self.PRIVATE_SERIES_ID}/image"))
            lookup.assert_not_called()

    def test_json_series_id_guard_covers_measurement_and_inference_payloads(self):
        actor = self._actor(self.unassigned_user_id)
        payload_paths = (
            "measurements/function",
            "measurements/tracking-preview",
            "measurements/curvature-preview",
            "measurements/fat-threshold-preview",
            "measurements/lge-threshold-preview",
            "measurements/lge",
            "jobs/infer",
        )
        with patch.object(
            cvi_workstation,
            "_json_request",
            return_value=(200, {"study_id": self.PRIVATE_STUDY_ID}),
        ) as lookup:
            for path in payload_paths:
                with self.subTest(path=path):
                    response = self._authorize(
                        actor,
                        path,
                        method="POST",
                        json={"series_id": self.PRIVATE_SERIES_ID},
                    )
                    self.assertIsNotNone(response)
                    self.assertEqual(response.status_code, 403)
            self.assertEqual(lookup.call_count, 1)

    def test_json_boolean_series_id_is_checked_like_upstream_integer_coercion(self):
        actor = self._actor(self.unassigned_user_id)
        with patch.object(
            cvi_workstation,
            "_json_request",
            return_value=(200, {"study_id": self.PRIVATE_STUDY_ID}),
        ) as lookup:
            response = self._authorize(
                actor,
                "measurements/curvature-preview",
                method="POST",
                json={"series_id": True},
            )
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 403)
        lookup.assert_called_once_with("/series/1")

    def test_job_status_and_pause_require_access_to_the_owning_private_study(self):
        unassigned = self._actor(self.unassigned_user_id)
        assigned = self._actor(self.assigned_user_id)
        for path, method in (("jobs/901", "GET"), ("jobs/901/pause", "POST")):
            with self.subTest(path=path, actor="unassigned"):
                with patch.object(
                    cvi_workstation,
                    "_json_request",
                    return_value=(200, {"series_id": self.PRIVATE_SERIES_ID, "study_id": self.PRIVATE_STUDY_ID}),
                ) as lookup:
                    response = self._authorize(unassigned, path, method=method)
                self.assertIsNotNone(response)
                self.assertEqual(response.status_code, 403)
                lookup.assert_called_once_with("/internal/jobs/901/scope")

            with self.subTest(path=path, actor="assigned"):
                with patch.object(
                    cvi_workstation,
                    "_json_request",
                    return_value=(200, {"series_id": self.PRIVATE_SERIES_ID, "study_id": self.PRIVATE_STUDY_ID}),
                ):
                    self.assertIsNone(self._authorize(assigned, path, method=method))

    def test_public_job_routes_keep_existing_non_admin_access(self):
        actor = self._actor(self.unassigned_user_id)
        for path, method in (("jobs/902", "GET"), ("jobs/902/pause", "POST")):
            with self.subTest(path=path):
                with patch.object(
                    cvi_workstation,
                    "_json_request",
                    return_value=(200, {"series_id": self.PUBLIC_SERIES_ID, "study_id": self.PUBLIC_STUDY_ID}),
                ):
                    self.assertIsNone(self._authorize(actor, path, method=method))

    def test_missing_or_malformed_job_scope_fails_closed(self):
        actor = self._actor(self.unassigned_user_id)
        for upstream_status, payload, expected_status in (
            (404, {"detail": "Job not found."}, 404),
            (200, {}, 502),
        ):
            with self.subTest(upstream_status=upstream_status, payload=payload):
                with patch.object(
                    cvi_workstation,
                    "_json_request",
                    return_value=(upstream_status, payload),
                ):
                    response = self._authorize(actor, "jobs/903")
                self.assertIsNotNone(response)
                self.assertEqual(response.status_code, expected_status)

    def test_non_private_series_and_admin_are_allowed(self):
        actor = self._actor(self.unassigned_user_id)
        with patch.object(
            cvi_workstation,
            "_json_request",
            return_value=(200, {"study_id": self.PUBLIC_STUDY_ID}),
        ):
            self.assertIsNone(self._authorize(actor, f"series/{self.PUBLIC_SERIES_ID}/image"))

        admin = self._actor(self.admin_user_id, is_admin=True)
        with patch.object(cvi_workstation, "_json_request") as lookup:
            self.assertIsNone(self._authorize(admin, f"series/{self.PRIVATE_SERIES_ID}/image"))
            self.assertIsNone(self._authorize(admin, "jobs/901"))
            self.assertIsNone(self._authorize(admin, "jobs/901/pause", method="POST"))
            lookup.assert_not_called()

    def test_internal_scope_endpoint_is_never_exposed_through_proxy(self):
        for actor in (
            self._actor(self.unassigned_user_id),
            self._actor(self.admin_user_id, is_admin=True),
        ):
            for path, method, payload in (
                (
                    f"internal/studies/{self.PRIVATE_STUDY_ID}/source-membership",
                    "POST",
                    {"roots": ["/"]},
                ),
                ("internal/jobs/901/scope", "GET", None),
            ):
                with self.subTest(is_admin=actor.is_admin, path=path):
                    response = self._authorize(
                        actor,
                        path,
                        method=method,
                        json=payload,
                    )
                    self.assertIsNotNone(response)
                    self.assertEqual(response.status_code, 404)

    def test_proxy_stops_before_upstream_for_an_unassigned_private_study(self):
        actor = self._actor(self.unassigned_user_id)
        path = f"studies/{self.PRIVATE_STUDY_ID}"
        with self.app.test_request_context(f"/cvi-api/{path}"):
            with patch.object(cvi_workstation, "current_user", actor):
                with patch.object(cvi_workstation.CVI_API_OPENER, "open") as upstream:
                    response = cvi_workstation._proxy_cvi_api(path)

        self.assertEqual(response.status_code, 403)
        upstream.assert_not_called()

    def test_proxy_stops_before_pause_for_an_unassigned_private_job(self):
        actor = self._actor(self.unassigned_user_id)
        path = "jobs/901/pause"
        with self.app.test_request_context(f"/cvi-api/{path}", method="POST"):
            with patch.object(cvi_workstation, "current_user", actor):
                with patch.object(
                    cvi_workstation,
                    "_json_request",
                    return_value=(200, {"series_id": self.PRIVATE_SERIES_ID, "study_id": self.PRIVATE_STUDY_ID}),
                ):
                    with patch.object(cvi_workstation.CVI_API_OPENER, "open") as upstream:
                        response = cvi_workstation._proxy_cvi_api(path)

        self.assertEqual(response.status_code, 403)
        upstream.assert_not_called()


if __name__ == "__main__":
    unittest.main()
