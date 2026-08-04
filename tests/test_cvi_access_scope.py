import unittest
from contextlib import contextmanager
from unittest.mock import patch

from apps.api.services import access_scope


class _FakeCursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _FakeConnection:
    def __init__(self, row):
        self.row = row

    def execute(self, _query, _parameters):
        return _FakeCursor(self.row)


class CviAccessScopeTest(unittest.TestCase):
    def test_source_membership_uses_path_boundaries_not_string_prefixes(self):
        self.assertTrue(access_scope.source_path_matches_roots(
            "/clinical/private/case-1",
            ["/clinical/private"],
        ))
        self.assertFalse(access_scope.source_path_matches_roots(
            "/clinical/private-copy/case-1",
            ["/clinical/private"],
        ))
        self.assertFalse(access_scope.source_path_matches_roots("", ["/clinical/private"]))

    def test_study_membership_returns_only_boolean_scope(self):
        @contextmanager
        def fake_connection():
            yield _FakeConnection({"source_path": "/clinical/private/case-2"})

        with patch.object(access_scope, "get_conn", fake_connection):
            self.assertTrue(access_scope.study_source_matches_roots(
                17,
                ["/clinical/private"],
            ))

    def test_missing_study_is_not_treated_as_public(self):
        @contextmanager
        def fake_connection():
            yield _FakeConnection(None)

        with patch.object(access_scope, "get_conn", fake_connection):
            with self.assertRaises(KeyError):
                access_scope.study_source_matches_roots(404, ["/clinical/private"])

    def test_job_scope_returns_only_owning_series_and_study(self):
        @contextmanager
        def fake_connection():
            yield _FakeConnection({"series_id": 81, "study_id": 71})

        with patch.object(access_scope, "get_conn", fake_connection):
            self.assertEqual(
                access_scope.job_study_scope(91),
                {"series_id": 81, "study_id": 71},
            )

    def test_missing_job_scope_raises_key_error(self):
        @contextmanager
        def fake_connection():
            yield _FakeConnection(None)

        with patch.object(access_scope, "get_conn", fake_connection):
            with self.assertRaises(KeyError):
                access_scope.job_study_scope(404)


if __name__ == "__main__":
    unittest.main()
