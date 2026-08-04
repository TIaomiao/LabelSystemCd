import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from sqlalchemy.exc import DatabaseError


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import cvi_workstation
import routes
from extensions import db
from models import CaseAssignment, CviCaseCatalog, DatasetAccessAudit, DatasetAccessGrant, User


class DatasetAccessManagementTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config.update(
            SQLALCHEMY_DATABASE_URI="sqlite://",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            SECRET_KEY="dataset-access-test",
            DATA_ROOT="/missing-annotation-root",
            FUNCTIONAL_DATA_ROOT="/missing-functional-root",
            EVAL_ROOT="/missing-eval-root",
            CMR_ALL_REPORT100_CASE_LIST="/missing-report-list",
            CVI_LIBRARY_MULTICENTER_ROOTS=[
                {"dataset": "CMR_ALL", "label": "系统共享库", "path": "/tmp"},
                {
                    "dataset": "PRIVATE_A",
                    "label": "真实私有数据集",
                    "path": "/tmp",
                    "private_by_assignment": True,
                },
                {"dataset": "SHARED_A", "label": "真实共享数据集", "path": "/tmp"},
                {"dataset": "EMPTY_A", "label": "空数据集", "path": "/tmp"},
            ],
        )
        db.init_app(cls.app)
        routes.register_routes(cls.app)
        cvi_workstation.register_cvi_workstation_routes(cls.app)

        with cls.app.app_context():
            db.create_all()
            admin = User(username="dataset-admin", is_approved=True, is_admin=True)
            all_current = User(username="all-current-user", is_approved=True, is_admin=False)
            partial = User(username="partial-user", is_approved=True, is_admin=False)
            other = User(username="other-user", is_approved=True, is_admin=False)
            pending = User(username="pending-user", is_approved=False, is_admin=False)
            db.session.add_all([admin, all_current, partial, other, pending])
            db.session.flush()
            cls.admin_id = admin.id
            cls.all_current_id = all_current.id
            cls.partial_id = partial.id
            cls.other_id = other.id
            cls.pending_id = pending.id

            db.session.add_all([
                CviCaseCatalog(
                    source="functional",
                    dataset="PRIVATE_A",
                    case_id="private-1",
                    full_id="PRIVATE_A/private-1",
                    path="/private-a/private-1",
                    has_dicom=True,
                    cvi_study_id=101,
                ),
                CviCaseCatalog(
                    source="functional",
                    dataset="PRIVATE_A",
                    case_id="private-2",
                    full_id="PRIVATE_A/private-2",
                    path="/private-a/private-2",
                    has_dicom=True,
                    cvi_study_id=102,
                ),
                CviCaseCatalog(
                    source="functional",
                    dataset="SHARED_A",
                    case_id="shared-1",
                    full_id="SHARED_A/shared-1",
                    path="/shared-a/shared-1",
                    has_dicom=True,
                    cvi_study_id=201,
                ),
            ])
            db.session.add_all([
                CaseAssignment(
                    namespace="functional",
                    dataset="PRIVATE_A",
                    case_id=case_id,
                    user_id=all_current.id,
                    active=True,
                )
                for case_id in ("private-1", "private-2")
            ])
            db.session.add(CaseAssignment(
                namespace="functional",
                dataset="PRIVATE_A",
                case_id="private-1",
                user_id=partial.id,
                active=True,
            ))
            db.session.commit()

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()
            db.drop_all()

    def setUp(self):
        with self.app.app_context():
            db.session.remove()
            DatasetAccessAudit.__table__.drop(db.engine, checkfirst=True)
            DatasetAccessAudit.__table__.create(db.engine)
            DatasetAccessGrant.query.delete()
            db.session.commit()
        with cvi_workstation.CVI_SERIES_STUDY_CACHE_LOCK:
            cvi_workstation.CVI_SERIES_STUDY_CACHE.clear()

    def _actor(self, user_id, *, is_admin=False, username=None):
        return SimpleNamespace(
            id=user_id,
            username=username or f"actor-{user_id}",
            is_authenticated=True,
            is_admin=is_admin,
        )

    def _call_dataset_access_view(self, method="GET", json=None):
        request_json = dict(json) if isinstance(json, dict) else json
        with self.app.app_context():
            if (
                method == "PUT"
                and isinstance(request_json, dict)
                and "expected_revision" not in request_json
                and routes._configured_dataset_access_definition(
                    request_json.get("namespace") or "functional",
                    request_json.get("dataset"),
                ) is not None
            ):
                request_json["expected_revision"] = routes._dataset_access_revision(
                    request_json.get("namespace") or "functional",
                    request_json.get("dataset"),
                )
        view = self.app.view_functions["manage_dataset_access"]
        while hasattr(view, "__wrapped__"):
            view = view.__wrapped__
        actor = self._actor(self.admin_id, is_admin=True, username="dataset-admin")
        with self.app.app_context(), self.app.test_request_context(
            "/api/admin/dataset-access",
            method=method,
            json=request_json,
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        ):
            with patch.object(routes, "current_user", actor):
                return self.app.make_response(view())

    def _call_protected_dataset_access_view(self, actor, method="GET", json=None):
        view = self.app.view_functions["manage_dataset_access"]
        with self.app.app_context(), self.app.test_request_context(
            "/api/admin/dataset-access",
            method=method,
            json=json,
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        ):
            with patch.object(routes, "current_user", actor):
                with patch("flask_login.utils.current_user", actor):
                    return self.app.make_response(view())

    def _call_cvi_import(self, actor, case_id="private-2"):
        with self.app.app_context(), self.app.test_request_context(
            "/api/cvi-library/cases/1/import",
            method="POST",
            json={},
        ):
            case = CviCaseCatalog.query.filter_by(
                source="functional",
                dataset="PRIVATE_A",
                case_id=case_id,
            ).one()
            view = self.app.view_functions["cvi_library_import"]
            while hasattr(view, "__wrapped__"):
                view = view.__wrapped__
            with patch.object(cvi_workstation, "current_user", actor):
                with patch.object(
                    cvi_workstation,
                    "_resolve_dicom_case_path",
                    return_value=Path(case.path),
                ) as resolve_path:
                    with patch.object(
                        cvi_workstation,
                        "_sequence_summary",
                        return_value=([], 1, True),
                    ):
                        with patch.object(cvi_workstation, "_verify_cvi_study", return_value=True):
                            response = self.app.make_response(view(case.id))
        return response, resolve_path.called

    def test_overview_uses_real_dataset_identity_and_separates_assignment_scope(self):
        with self.app.app_context():
            payload = routes._dataset_access_overview()

        datasets = {item["dataset"]: item for item in payload["datasets"]}
        self.assertEqual(set(datasets), {"CMR_ALL", "PRIVATE_A", "SHARED_A", "EMPTY_A"})
        private = datasets["PRIVATE_A"]
        self.assertEqual(private["label"], "真实私有数据集")
        self.assertTrue(private["private_by_assignment"])
        self.assertEqual(private["catalog_count"], 2)
        self.assertNotIn("专属", private["label"])

        access = {item["user_id"]: item for item in private["user_access"]}
        self.assertEqual(access[self.all_current_id]["access_scope"], "all_current")
        self.assertFalse(access[self.all_current_id]["future_cases_included"])
        self.assertEqual(access[self.partial_id]["access_scope"], "partial")
        self.assertEqual(access[self.other_id]["access_scope"], "none")

        shared_all = datasets["CMR_ALL"]
        self.assertTrue(shared_all["system_shared"])
        self.assertFalse(shared_all["grant_supported"])
        self.assertTrue(all(item["access_scope"] == "system_shared" for item in shared_all["user_access"]))

    def test_replace_grants_is_true_dataset_access_and_keeps_case_tasks(self):
        response = self._call_dataset_access_view(
            method="PUT",
            json={
                "namespace": "functional",
                "dataset": "PRIVATE_A",
                "user_ids": [self.partial_id, self.other_id, self.other_id],
            },
        )
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            grants = DatasetAccessGrant.query.filter_by(
                namespace="functional",
                dataset="PRIVATE_A",
                active=True,
            ).order_by(DatasetAccessGrant.user_id).all()
            self.assertEqual([item.user_id for item in grants], sorted([self.partial_id, self.other_id]))
            audits = DatasetAccessAudit.query.order_by(DatasetAccessAudit.id.asc()).all()
            self.assertEqual(len(audits), 2)
            self.assertEqual({item.action for item in audits}, {"grant"})
            self.assertEqual({item.target_user_id for item in audits}, {self.partial_id, self.other_id})
            self.assertEqual(len({item.batch_id for item in audits}), 1)
            self.assertEqual({item.actor_username for item in audits}, {"dataset-admin"})
            self.assertEqual({item.request_ip for item in audits}, {"127.0.0.1"})
            self.assertEqual({item.release_version for item in audits}, {routes.LABELSYSTEM_RELEASE_VERSION})
            self.assertEqual(
                CaseAssignment.query.filter_by(
                    namespace="functional",
                    dataset="PRIVATE_A",
                    user_id=self.partial_id,
                    active=True,
                ).count(),
                1,
            )

            payload = routes._dataset_access_overview()
            private = next(item for item in payload["datasets"] if item["dataset"] == "PRIVATE_A")
            access = {item["user_id"]: item for item in private["user_access"]}
            self.assertEqual(access[self.partial_id]["access_scope"], "dataset")
            self.assertTrue(access[self.partial_id]["future_cases_included"])
            self.assertEqual(access[self.partial_id]["effective_case_count"], 2)

    def test_revoking_dataset_grant_leaves_partial_case_access_explicit(self):
        with self.app.app_context():
            routes._replace_dataset_access_grants(
                "functional",
                "PRIVATE_A",
                [self.partial_id],
                self.admin_id,
            )
            db.session.commit()

        response = self._call_dataset_access_view(
            method="PUT",
            json={"namespace": "functional", "dataset": "PRIVATE_A", "user_ids": []},
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            grant = DatasetAccessGrant.query.filter_by(
                namespace="functional",
                dataset="PRIVATE_A",
                user_id=self.partial_id,
            ).one()
            self.assertFalse(grant.active)
            payload = routes._dataset_access_overview()
            private = next(item for item in payload["datasets"] if item["dataset"] == "PRIVATE_A")
            access = {item["user_id"]: item for item in private["user_access"]}
            self.assertEqual(access[self.partial_id]["access_scope"], "partial")

    def test_empty_dataset_can_be_granted_and_future_case_is_automatically_allowed(self):
        with self.app.app_context():
            routes._replace_dataset_access_grants(
                "functional",
                "EMPTY_A",
                [self.other_id],
                self.admin_id,
            )
            db.session.commit()

        actor = self._actor(self.other_id)
        with self.app.app_context(), self.app.test_request_context("/"):
            with patch.object(cvi_workstation, "current_user", actor):
                self.assertTrue(
                    cvi_workstation._user_can_access_case(
                        "functional",
                        "EMPTY_A",
                        "future-case-not-yet-in-catalog",
                    )
                )
            with patch.object(routes, "current_user", actor):
                self.assertTrue(
                    routes._user_can_access_case(
                        "functional",
                        "EMPTY_A",
                        "future-case-not-yet-in-catalog",
                    )
                )

    def test_private_study_object_guard_accepts_dataset_grant_and_rejects_other_user(self):
        with self.app.app_context():
            routes._replace_dataset_access_grants(
                "functional",
                "PRIVATE_A",
                [self.other_id],
                self.admin_id,
            )
            db.session.commit()

        with self.app.app_context(), self.app.test_request_context("/"):
            with patch.object(cvi_workstation, "current_user", self._actor(self.other_id)):
                self.assertIsNone(cvi_workstation._authorize_cvi_study(101))
            with patch.object(cvi_workstation, "current_user", self._actor(self.partial_id)):
                # partial-user owns private-1 through an exact case assignment
                self.assertIsNone(cvi_workstation._authorize_cvi_study(101))
            with patch.object(cvi_workstation, "current_user", self._actor(self.all_current_id + 1000)):
                response = cvi_workstation._authorize_cvi_study(101)
                self.assertIsNotNone(response)
                self.assertEqual(response.status_code, 403)

    def test_library_labels_distinguish_dataset_grant_from_case_assignment_view(self):
        with self.app.app_context():
            routes._replace_dataset_access_grants(
                "functional",
                "PRIVATE_A",
                [self.other_id],
                self.admin_id,
            )
            db.session.commit()

        with self.app.app_context(), self.app.test_request_context("/"):
            with patch.object(cvi_workstation, "current_user", self._actor(self.other_id)):
                granted = next(
                    item
                    for item in cvi_workstation._cvi_library_options()
                    if item["value"] == "functional::PRIVATE_A::granted"
                )
            with patch.object(cvi_workstation, "current_user", self._actor(self.partial_id)):
                assigned = next(
                    item
                    for item in cvi_workstation._cvi_library_options()
                    if item["value"] == "functional::PRIVATE_A::assigned"
                )

        self.assertEqual(granted["label"], "真实私有数据集 · 整库权限")
        self.assertNotIn("case_ids", granted)
        self.assertEqual(granted["kind"], "dataset_access")
        self.assertEqual(assigned["label"], "真实私有数据集 · 已分配病例（1例）")
        self.assertEqual(assigned["case_ids"], ["private-1"])
        self.assertNotIn("专属", assigned["label"])

    def test_invalid_targets_and_system_shared_dataset_are_rejected_without_mutation(self):
        invalid_payloads = (
            {"namespace": "functional", "dataset": "MISSING", "user_ids": [self.other_id]},
            {"namespace": "functional", "dataset": "PRIVATE_A", "user_ids": [True]},
            {"namespace": "functional", "dataset": "PRIVATE_A", "user_ids": [1.5]},
            {"namespace": "functional", "dataset": "PRIVATE_A", "user_ids": [self.pending_id]},
            {"namespace": "functional", "dataset": "PRIVATE_A", "user_ids": [self.admin_id]},
            {"namespace": "functional", "dataset": "CMR_ALL", "user_ids": [self.other_id]},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self._call_dataset_access_view(method="PUT", json=payload)
                self.assertIn(response.status_code, {400, 404})

        with self.app.app_context():
            self.assertEqual(DatasetAccessGrant.query.filter_by(active=True).count(), 0)
            self.assertEqual(DatasetAccessAudit.query.count(), 0)

    def test_non_admin_cannot_read_or_replace_dataset_grants(self):
        created = self._call_dataset_access_view(
            method="PUT",
            json={
                "namespace": "functional",
                "dataset": "PRIVATE_A",
                "user_ids": [self.other_id],
            },
        )
        self.assertEqual(created.status_code, 200)
        actor = self._actor(self.partial_id, is_admin=False)
        for method, payload in (
            ("GET", None),
            (
                "PUT",
                {
                    "namespace": "functional",
                    "dataset": "PRIVATE_A",
                    "user_ids": [],
                },
            ),
        ):
            with self.subTest(method=method):
                response = self._call_protected_dataset_access_view(actor, method=method, json=payload)
                self.assertEqual(response.status_code, 403)

        with self.app.app_context():
            self.assertEqual(DatasetAccessGrant.query.filter_by(active=True).count(), 1)
            self.assertEqual(DatasetAccessAudit.query.count(), 1)

    def test_dataset_grant_authorizes_private_catalog_import_without_case_task(self):
        actor = self._actor(self.other_id)
        response, resolved = self._call_cvi_import(actor)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(resolved)

        with self.app.app_context():
            routes._replace_dataset_access_grants(
                "functional",
                "PRIVATE_A",
                [self.other_id],
                self.admin_id,
            )
            db.session.commit()

        response, resolved = self._call_cvi_import(actor)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(resolved)

    def test_dataset_grant_covers_private_study_series_measurement_and_report_objects(self):
        with self.app.app_context():
            routes._replace_dataset_access_grants(
                "functional",
                "PRIVATE_A",
                [self.other_id],
                self.admin_id,
            )
            db.session.commit()

        actor = self._actor(self.other_id)
        denied_actor = self._actor(self.other_id + 1000)
        direct_paths = (
            "studies/101",
            "reports/101",
            "exports/101.csv",
            "exports/101.pdf",
        )
        with self.app.app_context():
            for path in direct_paths:
                with self.subTest(path=path, actor="granted"):
                    with self.app.test_request_context(f"/cvi-api/{path}"):
                        with patch.object(cvi_workstation, "current_user", actor):
                            self.assertIsNone(cvi_workstation._authorize_cvi_proxy_request(path))
                with self.subTest(path=path, actor="denied"):
                    with self.app.test_request_context(f"/cvi-api/{path}"):
                        with patch.object(cvi_workstation, "current_user", denied_actor):
                            response = cvi_workstation._authorize_cvi_proxy_request(path)
                            self.assertIsNotNone(response)
                            self.assertEqual(response.status_code, 403)

            with patch.object(
                cvi_workstation,
                "_json_request",
                return_value=(200, {"study_id": 101}),
            ):
                for path, method, payload in (
                    ("series/991/image", "GET", None),
                    ("contours/991/curvature", "POST", None),
                    ("measurements/curvature-preview", "POST", {"series_id": 991}),
                ):
                    with self.subTest(path=path):
                        with self.app.test_request_context(
                            f"/cvi-api/{path}",
                            method=method,
                            json=payload,
                        ):
                            with patch.object(cvi_workstation, "current_user", actor):
                                self.assertIsNone(cvi_workstation._authorize_cvi_proxy_request(path))

    def test_shared_study_access_keeps_legacy_authenticated_behavior(self):
        actor = self._actor(self.other_id)
        with self.app.app_context(), self.app.test_request_context("/"):
            with patch.object(routes, "current_user", actor):
                self.assertTrue(routes._user_can_access_case("functional", "SHARED_A", "shared-1"))
            with patch.object(cvi_workstation, "current_user", actor):
                self.assertIsNone(cvi_workstation._authorize_cvi_study(201))

    def test_mixed_replace_records_only_real_deltas_in_one_batch(self):
        first = self._call_dataset_access_view(
            method="PUT",
            json={
                "namespace": "functional",
                "dataset": "PRIVATE_A",
                "user_ids": [self.partial_id, self.all_current_id],
            },
        )
        self.assertEqual(first.status_code, 200)

        second = self._call_dataset_access_view(
            method="PUT",
            json={
                "namespace": "functional",
                "dataset": "PRIVATE_A",
                "user_ids": [self.partial_id, self.other_id],
            },
        )
        self.assertEqual(second.status_code, 200)
        updated = second.get_json()["updated"]
        self.assertEqual(updated["audit_event_count"], 2)
        self.assertTrue(updated["audit_batch_id"])

        with self.app.app_context():
            events = DatasetAccessAudit.query.filter_by(batch_id=updated["audit_batch_id"]).all()
            self.assertEqual(
                {(item.target_user_id, item.action) for item in events},
                {(self.other_id, "grant"), (self.all_current_id, "revoke")},
            )
            self.assertEqual(len({item.created_at for item in events}), 1)
            self.assertEqual(len({item.batch_id for item in events}), 1)

    def test_noop_replace_writes_no_audit_and_keeps_revision(self):
        first = self._call_dataset_access_view(
            method="PUT",
            json={
                "namespace": "functional",
                "dataset": "PRIVATE_A",
                "user_ids": [self.other_id],
            },
        )
        self.assertEqual(first.status_code, 200)
        with self.app.app_context():
            revision_before = routes._dataset_access_revision("functional", "PRIVATE_A")
            audit_count_before = DatasetAccessAudit.query.count()
            grant = DatasetAccessGrant.query.filter_by(
                namespace="functional",
                dataset="PRIVATE_A",
                user_id=self.other_id,
            ).one()
            updated_at_before = grant.updated_at
            created_by_before = grant.created_by_id

        second = self._call_dataset_access_view(
            method="PUT",
            json={
                "namespace": "functional",
                "dataset": "PRIVATE_A",
                "user_ids": [self.other_id, self.other_id],
            },
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json()["updated"]["audit_event_count"], 0)
        self.assertIsNone(second.get_json()["updated"]["audit_batch_id"])
        with self.app.app_context():
            self.assertEqual(DatasetAccessAudit.query.count(), audit_count_before)
            self.assertEqual(routes._dataset_access_revision("functional", "PRIVATE_A"), revision_before)
            grant = DatasetAccessGrant.query.filter_by(
                namespace="functional",
                dataset="PRIVATE_A",
                user_id=self.other_id,
            ).one()
            self.assertEqual(grant.updated_at, updated_at_before)
            self.assertEqual(grant.created_by_id, created_by_before)

    def test_stale_revision_is_rejected_without_state_or_audit_change(self):
        with self.app.app_context():
            stale_revision = routes._dataset_access_revision("functional", "PRIVATE_A")
        first = self._call_dataset_access_view(
            method="PUT",
            json={
                "namespace": "functional",
                "dataset": "PRIVATE_A",
                "user_ids": [self.partial_id],
                "expected_revision": stale_revision,
            },
        )
        self.assertEqual(first.status_code, 200)
        response = self._call_dataset_access_view(
            method="PUT",
            json={
                "namespace": "functional",
                "dataset": "PRIVATE_A",
                "user_ids": [self.other_id],
                "expected_revision": stale_revision,
            },
        )
        self.assertEqual(response.status_code, 409)
        with self.app.app_context():
            self.assertEqual(
                _active_grant_user_ids("functional", "PRIVATE_A"),
                {self.partial_id},
            )
            self.assertEqual(DatasetAccessAudit.query.count(), 1)

    def test_audit_failure_rolls_back_grant_state(self):
        with patch.object(
            routes,
            "_append_dataset_access_audit",
            side_effect=RuntimeError("audit unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                self._call_dataset_access_view(
                    method="PUT",
                    json={
                        "namespace": "functional",
                        "dataset": "PRIVATE_A",
                        "user_ids": [self.other_id],
                    },
                )
        with self.app.app_context():
            self.assertEqual(DatasetAccessGrant.query.filter_by(active=True).count(), 0)
            self.assertEqual(DatasetAccessAudit.query.count(), 0)

    def test_grant_revoke_regrant_history_is_append_only_and_stably_sorted(self):
        for selected_ids in ([self.other_id], [], [self.other_id]):
            response = self._call_dataset_access_view(
                method="PUT",
                json={
                    "namespace": "functional",
                    "dataset": "PRIVATE_A",
                    "user_ids": selected_ids,
                },
            )
            self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            ascending = DatasetAccessAudit.query.order_by(DatasetAccessAudit.id.asc()).all()
            self.assertEqual([item.action for item in ascending], ["grant", "revoke", "grant"])
            self.assertEqual(len({item.batch_id for item in ascending}), 3)
            self.assertEqual(
                DatasetAccessGrant.query.filter_by(
                    namespace="functional",
                    dataset="PRIVATE_A",
                    user_id=self.other_id,
                    active=True,
                ).count(),
                1,
            )
            overview = routes._dataset_access_overview()
            self.assertEqual(
                [item["id"] for item in overview["recent_audit"]],
                sorted((item.id for item in ascending), reverse=True),
            )

    def test_database_rejects_audit_update_and_delete(self):
        response = self._call_dataset_access_view(
            method="PUT",
            json={
                "namespace": "functional",
                "dataset": "PRIVATE_A",
                "user_ids": [self.other_id],
            },
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            event = DatasetAccessAudit.query.one()
            event.target_username = "tampered"
            with self.assertRaises(DatabaseError):
                db.session.commit()
            db.session.rollback()
            event = DatasetAccessAudit.query.one()
            original_username = event.target_username
            db.session.delete(event)
            with self.assertRaises(DatabaseError):
                db.session.commit()
            db.session.rollback()
            persisted = DatasetAccessAudit.query.one()
            self.assertEqual(persisted.target_username, original_username)

    def test_audit_preserves_actor_target_and_dataset_label_snapshots(self):
        response = self._call_dataset_access_view(
            method="PUT",
            json={
                "namespace": "functional",
                "dataset": "PRIVATE_A",
                "user_ids": [self.other_id],
            },
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            admin = db.session.get(User, self.admin_id)
            target = db.session.get(User, self.other_id)
            original_admin_username = admin.username
            original_target_username = target.username
            try:
                admin.username = "renamed-admin"
                target.username = "renamed-target"
                self.app.config["CVI_LIBRARY_MULTICENTER_ROOTS"][1]["label"] = "已改名数据集"
                db.session.commit()
                event = DatasetAccessAudit.query.one()
                self.assertEqual(event.actor_username, "dataset-admin")
                self.assertEqual(event.target_username, original_target_username)
                self.assertEqual(event.dataset_label, "真实私有数据集")
            finally:
                admin.username = original_admin_username
                target.username = original_target_username
                self.app.config["CVI_LIBRARY_MULTICENTER_ROOTS"][1]["label"] = "真实私有数据集"
                db.session.commit()


def _active_grant_user_ids(namespace, dataset):
    return {
        int(item.user_id)
        for item in DatasetAccessGrant.query.filter_by(
            namespace=namespace,
            dataset=dataset,
            active=True,
        ).all()
    }


if __name__ == "__main__":
    unittest.main()
