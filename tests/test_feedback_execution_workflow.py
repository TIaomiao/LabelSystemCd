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
from feedback_recovery import recover_interrupted_feedback_investigations
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

    def test_baseline_status_distinguishes_current_clean_head_from_dirty_investigation(self):
        with self.app.app_context():
            _issue, plan = self._issue_and_plan({
                'base_sha': 'a' * 40,
                'branch': 'main',
                'dirty_worktree': True,
                'allowed_paths': ['frontend/src/App.tsx'],
            })
            with patch.object(routes, 'repository_snapshot', return_value={
                'base_sha': 'b' * 40,
                'branch': 'main',
                'dirty': False,
                'tracked_changes': [],
            }):
                status = routes._feedback_plan_baseline_status(plan)

            self.assertTrue(status['current_clean'])
            self.assertFalse(status['executable'])
            self.assertEqual(status['reason'], 'investigation_was_dirty')
            self.assertEqual(status['plan_base_sha'], 'a' * 40)
            self.assertEqual(status['current_base_sha'], 'b' * 40)

    def test_baseline_status_accepts_plan_bound_to_current_clean_head(self):
        with self.app.app_context():
            _issue, plan = self._issue_and_plan({
                'base_sha': 'c' * 40,
                'branch': 'main',
                'dirty_worktree': False,
                'allowed_paths': ['frontend/src/App.tsx'],
            })
            with patch.object(routes, 'repository_snapshot', return_value={
                'base_sha': 'c' * 40,
                'branch': 'main',
                'dirty': False,
                'tracked_changes': [],
            }):
                status = routes._feedback_plan_baseline_status(plan)

            self.assertTrue(status['executable'])
            self.assertEqual(status['reason'], 'ready')

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

    def test_restart_recovery_fails_closed_for_active_investigations(self):
        with self.app.app_context():
            issue = FeedbackIssue(
                session_id=self.session_id,
                reporter_id=self.user_id,
                category='bug',
                title='interrupted investigation',
            )
            db.session.add(issue)
            db.session.flush()
            pending = FeedbackCodexRun(issue_id=issue.id, status='pending', phase='investigation')
            running = FeedbackCodexRun(issue_id=issue.id, status='running', phase='investigation')
            completed = FeedbackCodexRun(issue_id=issue.id, status='completed', phase='investigation')
            db.session.add_all([pending, running, completed])
            db.session.commit()

            with db.engine.begin() as connection:
                recovered = recover_interrupted_feedback_investigations(connection)
            db.session.expire_all()

            self.assertEqual(recovered, 2)
            self.assertEqual(pending.status, 'failed')
            self.assertEqual(pending.phase, 'interrupted_by_restart')
            self.assertIsNotNone(running.finished_at)
            self.assertEqual(completed.status, 'completed')

    def test_plan_review_history_is_ordered_and_excludes_current_run(self):
        with self.app.app_context():
            issue = FeedbackIssue(
                session_id=self.session_id,
                reporter_id=self.user_id,
                category='bug',
                title='continued review',
            )
            db.session.add(issue)
            db.session.flush()
            first = FeedbackCodexRun(
                issue_id=issue.id,
                initiated_by_id=self.user_id,
                status='completed',
                phase='investigation',
                revision_note='先检查前端刷新',
                result_json={'investigation_summary': '第一轮'},
            )
            failed = FeedbackCodexRun(
                issue_id=issue.id,
                initiated_by_id=self.user_id,
                status='failed',
                phase='investigation',
                revision_note='失败轮次',
            )
            current = FeedbackCodexRun(
                issue_id=issue.id,
                initiated_by_id=self.user_id,
                status='pending',
                phase='investigation',
                revision_note='不要改 importer',
            )
            db.session.add_all([first, failed, current])
            db.session.commit()

            visible = routes._feedback_codex_history(issue.id)
            prompt_history = routes._feedback_codex_prompt_history(issue.id, current.id)

            self.assertEqual([item.id for item in visible], [first.id, failed.id, current.id])
            self.assertEqual(len(prompt_history), 1)
            self.assertEqual(prompt_history[0]['administrator_message'], '先检查前端刷新')
            self.assertEqual(prompt_history[0]['assistant_result']['investigation_summary'], '第一轮')

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
