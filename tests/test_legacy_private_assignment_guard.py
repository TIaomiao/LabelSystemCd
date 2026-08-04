import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import routes
from extensions import db
from models import CaseAssignment, User


class LegacyPrivateAssignmentGuardTest(unittest.TestCase):
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
            CMR_ALL_REPORT100_CASE_LIST="/missing-report-list",
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
        routes.register_routes(cls.app)

        with cls.app.app_context():
            db.create_all()
            assigned = User(username="legacy-assigned", is_approved=True, is_admin=False)
            other = User(username="legacy-other", is_approved=True, is_admin=False)
            admin = User(username="legacy-admin", is_approved=True, is_admin=True)
            db.session.add_all([assigned, other, admin])
            db.session.flush()
            cls.assigned_user_id = assigned.id
            cls.other_user_id = other.id
            cls.admin_user_id = admin.id

            db.session.add_all([
                CaseAssignment(
                    namespace="functional",
                    dataset="PRIVATE_CENTER",
                    case_id="case-exact",
                    user_id=assigned.id,
                    active=True,
                ),
                CaseAssignment(
                    namespace="functional",
                    dataset="PRIVATE_CENTER",
                    case_id="case-other",
                    user_id=other.id,
                    active=True,
                ),
                CaseAssignment(
                    namespace="functional",
                    dataset="PRIVATE_CENTER",
                    case_id="case-inactive",
                    user_id=assigned.id,
                    active=False,
                ),
                CaseAssignment(
                    namespace="functional",
                    dataset="PRIVATE_CENTER",
                    case_id="group-b/case-01",
                    user_id=assigned.id,
                    active=True,
                ),
                CaseAssignment(
                    namespace="functional",
                    dataset="PUBLIC_CENTER",
                    case_id="public-case-other",
                    user_id=other.id,
                    active=True,
                ),
                CaseAssignment(
                    namespace="functional",
                    dataset="PUBLIC_CENTER",
                    case_id="public-group-b/case-02",
                    user_id=assigned.id,
                    active=True,
                ),
            ])
            db.session.commit()

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()
            db.drop_all()

    def _actor(self, user_id, *, is_admin=False):
        return SimpleNamespace(
            id=user_id,
            username=f"legacy-user-{user_id}",
            is_authenticated=True,
            is_admin=is_admin,
        )

    def _can_access(self, actor, dataset, case_id):
        with self.app.app_context(), self.app.test_request_context("/"):
            with patch.object(routes, "current_user", actor):
                return routes._user_can_access_case("functional", dataset, case_id)

    def _call_view(self, name, actor, *args, method="GET", json=None):
        view = self.app.view_functions[name]
        while hasattr(view, "__wrapped__"):
            view = view.__wrapped__
        with self.app.app_context(), self.app.test_request_context(
            "/",
            method=method,
            json=json,
        ):
            with patch.object(routes, "current_user", actor):
                return self.app.make_response(view(*args))

    def test_private_dataset_fails_closed_and_requires_exact_active_assignment(self):
        assigned = self._actor(self.assigned_user_id)
        self.assertFalse(self._can_access(assigned, "PRIVATE_CENTER", "case-no-assignment"))
        self.assertFalse(self._can_access(assigned, "PRIVATE_CENTER", "case-other"))
        self.assertFalse(self._can_access(assigned, "PRIVATE_CENTER", "case-inactive"))
        self.assertTrue(self._can_access(assigned, "PRIVATE_CENTER", "case-exact"))

    def test_private_hierarchical_alias_does_not_authorize_same_basename(self):
        assigned = self._actor(self.assigned_user_id)
        self.assertTrue(self._can_access(assigned, "PRIVATE_CENTER", "group-b/case-01"))
        self.assertFalse(self._can_access(assigned, "PRIVATE_CENTER", "group-a/case-01"))

    def test_admin_bypass_and_public_dataset_behavior_are_preserved(self):
        assigned = self._actor(self.assigned_user_id)
        admin = self._actor(self.admin_user_id, is_admin=True)

        self.assertTrue(self._can_access(admin, "PRIVATE_CENTER", "case-no-assignment"))
        self.assertTrue(self._can_access(assigned, "PUBLIC_CENTER", "public-unassigned"))
        self.assertFalse(self._can_access(assigned, "PUBLIC_CENTER", "public-case-other"))
        # Public datasets retain their historical basename/LIKE assignment aliases.
        self.assertTrue(self._can_access(assigned, "PUBLIC_CENTER", "public-group-a/case-02"))

    def test_old_detail_routes_stop_before_path_resolution_when_private_unassigned(self):
        assigned = self._actor(self.assigned_user_id)
        for view_name in (
            "get_functional_case_detail",
            "get_lge_case_detail",
            "get_analysis_case_detail",
        ):
            with self.subTest(view=view_name):
                with patch.object(routes, "_resolve_assessment_case_path") as resolve_path:
                    response = self._call_view(
                        view_name,
                        assigned,
                        "PRIVATE_CENTER",
                        "case-no-assignment",
                    )
                self.assertEqual(response.status_code, 403)
                resolve_path.assert_not_called()

    def test_old_detail_routes_allow_exact_assignment_admin_and_public_cases(self):
        cases = (
            (self._actor(self.assigned_user_id), "PRIVATE_CENTER", "case-exact"),
            (self._actor(self.admin_user_id, is_admin=True), "PRIVATE_CENTER", "case-no-assignment"),
            (self._actor(self.assigned_user_id), "PUBLIC_CENTER", "public-unassigned"),
        )
        for view_name in (
            "get_functional_case_detail",
            "get_lge_case_detail",
            "get_analysis_case_detail",
        ):
            for actor, dataset, case_id in cases:
                with self.subTest(
                    view=view_name,
                    actor=actor.username,
                    dataset=dataset,
                    case_id=case_id,
                ):
                    with patch.object(routes, "_resolve_assessment_case_path", return_value=None) as resolve_path:
                        response = self._call_view(
                            view_name,
                            actor,
                            dataset,
                            case_id,
                        )
                    self.assertEqual(response.status_code, 404)
                    resolve_path.assert_called_once()

    def test_legacy_assessment_writes_share_the_private_guard(self):
        assigned = self._actor(self.assigned_user_id)
        for view_name in (
            "save_functional_assessment",
            "save_lge_assessment",
            "save_analysis_assessment",
            "save_other_findings_assessment",
        ):
            with self.subTest(view=view_name):
                response = self._call_view(
                    view_name,
                    assigned,
                    "PRIVATE_CENTER",
                    "case-no-assignment",
                    method="POST",
                    json={"test": True},
                )
                self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
