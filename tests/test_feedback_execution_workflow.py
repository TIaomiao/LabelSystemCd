import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask


BACKEND_DIR = Path(__file__).resolve().parents[1] / 'backend'
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import routes
from codex_feedback_executor import CodexExecutionError
from extensions import db
from models import FeedbackCodexRun, FeedbackExecutionRun, FeedbackIssue, FeedbackSession, FeedbackWorkPlan, User


class FeedbackExecutionWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            SQLALCHEMY_DATABASE_URI='sqlite://',
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            SECRET_KEY='feedback-execution-test',
        )
        db.init_app(self.app)
        with self.app.app_context():
            db.create_all()
            user = User(username='admin', is_approved=True, is_admin=True)
            db.session.add(user)
            db.session.flush()
            session = FeedbackSession(user_id=user.id, title='feedback')
            db.session.add(session)
            db.session.flush()
            self.user_id = user.id
            self.session_id = session.id
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _issue_and_plan(self, proposal):
        issue = FeedbackIssue(
            session_id=self.session_id,
            reporter_id=self.user_id,
            category='bug',
            title='test issue',
            status='planned',
        )
        db.session.add(issue)
        db.session.flush()
        plan = FeedbackWorkPlan(
            issue_id=issue.id,
            status='approved',
            proposal_json=proposal,
            approved_by_id=self.user_id,
            approved_at=datetime.utcnow(),
        )
        db.session.add(plan)
        db.session.commit()
        return issue, plan

    def test_dirty_investigation_can_never_enter_execution(self):
        with self.app.app_context():
            issue, plan = self._issue_and_plan({
                'base_sha': 'a' * 40,
                'branch': 'main',
                'dirty_worktree': True,
                'allowed_paths': ['frontend/src/App.tsx'],
            })
            with self.assertRaisesRegex(CodexExecutionError, '未提交改动'):
                routes._queue_feedback_execution(issue, plan, self.user_id)
            self.assertEqual(FeedbackExecutionRun.query.count(), 0)

    def test_issue_serialization_includes_reporter_and_latest_investigation(self):
        with self.app.app_context():
            issue = FeedbackIssue(
                session_id=self.session_id,
                reporter_id=self.user_id,
                category='bug',
                title='serialization issue',
            )
            db.session.add(issue)
            db.session.flush()
            run = FeedbackCodexRun(
                issue_id=issue.id,
                initiated_by_id=self.user_id,
                status='completed',
                phase='investigation',
                base_sha='a' * 40,
            )
            db.session.add(run)
            db.session.commit()

            payload = issue.to_dict(include_user=True)

            self.assertEqual(payload['reporter_username'], 'admin')
            self.assertEqual(payload['codex_investigation']['id'], run.id)
            self.assertNotIn('worktree_path', payload)

    def test_queue_freezes_plan_snapshot_and_starts_one_worker(self):
        with self.app.app_context():
            issue, plan = self._issue_and_plan({
                'base_sha': 'b' * 40,
                'branch': 'main',
                'dirty_worktree': False,
                'allowed_paths': ['frontend/src/App.tsx'],
                'codex_brief': 'approved task',
            })
            fake_thread = MagicMock()
            with patch.object(routes, 'validate_clean_execution_base', return_value='b' * 40), patch.object(routes, 'Thread', return_value=fake_thread):
                run, created = routes._queue_feedback_execution(issue, plan, self.user_id)
            self.assertTrue(created)
            self.assertEqual(run.status, 'queued')
            self.assertEqual(run.plan_snapshot_json['proposal']['codex_brief'], 'approved task')
            self.assertEqual(len(run.plan_hash), 64)
            self.assertEqual(plan.status, 'queued')
            fake_thread.start.assert_called_once_with()

            again, created_again = routes._queue_feedback_execution(issue, plan, self.user_id)
            self.assertFalse(created_again)
            self.assertEqual(again.id, run.id)
            self.assertEqual(FeedbackExecutionRun.query.count(), 1)


if __name__ == '__main__':
    unittest.main()
