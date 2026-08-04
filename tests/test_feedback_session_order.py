import unittest
from datetime import datetime
from pathlib import Path
import sys

from flask import Flask

BACKEND_DIR = Path(__file__).resolve().parents[1] / 'backend'
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from backend.routes import _feedback_sessions_by_latest_user_message
from extensions import db
from models import FeedbackMessage, FeedbackSession, User


class FeedbackSessionOrderTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(self.app)
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_automatic_codex_message_does_not_move_old_doctor_session_to_top(self):
        with self.app.app_context():
            user = User(username='doctor', is_approved=True)
            db.session.add(user)
            db.session.flush()

            old_session = FeedbackSession(
                user_id=user.id,
                title='昨天的反馈',
                created_at=datetime(2026, 7, 14, 5, 0),
                last_message_at=datetime(2026, 7, 15, 3, 0),
            )
            new_session = FeedbackSession(
                user_id=user.id,
                title='今天的反馈',
                created_at=datetime(2026, 7, 15, 1, 0),
                last_message_at=datetime(2026, 7, 15, 1, 5),
            )
            db.session.add_all([old_session, new_session])
            db.session.flush()
            db.session.add_all([
                FeedbackMessage(
                    session_id=old_session.id,
                    author_id=user.id,
                    role='user',
                    content='昨天医生反馈',
                    created_at=datetime(2026, 7, 14, 5, 0),
                ),
                FeedbackMessage(
                    session_id=old_session.id,
                    role='assistant',
                    content='今天自动完成的 Codex 调查',
                    created_at=datetime(2026, 7, 15, 3, 0),
                ),
                FeedbackMessage(
                    session_id=new_session.id,
                    author_id=user.id,
                    role='user',
                    content='今天医生反馈',
                    created_at=datetime(2026, 7, 15, 1, 0),
                ),
            ])
            db.session.commit()

            records = _feedback_sessions_by_latest_user_message(FeedbackSession.query, 10)

            self.assertEqual([record.id for record, _ in records], [new_session.id, old_session.id])
            self.assertEqual(records[0][1], datetime(2026, 7, 15, 1, 0))
            self.assertEqual(records[1][1], datetime(2026, 7, 14, 5, 0))


if __name__ == '__main__':
    unittest.main()
