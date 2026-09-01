import json
import tempfile
import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/cmr"))
import render_status_board  # noqa: E402


class StatusBoardTest(unittest.TestCase):
    def test_current_statuses_parse_and_render(self):
        statuses = render_status_board.collect_statuses(ROOT)
        self.assertGreaterEqual(len(statuses), 1)
        self.assertEqual(statuses[0]["session_id"], "CMR-00")
        rendered = render_status_board.render_html(statuses)
        self.assertIn("CMR Session", rendered)
        self.assertIn("f52a53d", rendered)
        self.assertNotIn("/home/", rendered)
        self.assertNotIn("C:\\\\", rendered)

    def test_malformed_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status_dir = root / "docs/cmr/features/CMR-01"
            status_dir.mkdir(parents=True)
            payload = {
                "schema_version": "cmr.session-status.v1", "session_id": "CMR-01",
                "feature": "x", "state": "not_a_state", "owner_role": "builder",
                "branch": "x", "head_commit": "abcdef0", "updated_at": "2026-09-01T00:00:00+08:00",
                "data_scope": "none", "implemented": [], "demo_only": [], "not_done": [],
                "tests": [], "physician_review": {"state": "not_scheduled", "cases": []},
                "blockers": [], "next_action": "x", "evidence_refs": []
            }
            status_dir.joinpath("STATUS.md").write_text(
                "<!-- cmr-status\n" + json.dumps(payload) + "\ncmr-status -->\n", encoding="utf-8"
            )
            with self.assertRaises(render_status_board.StatusError):
                render_status_board.collect_statuses(root)

    def test_render_check_detects_stale_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status_dir = root / "docs/cmr/features/CMR-01"
            status_dir.mkdir(parents=True)
            source = (ROOT / "docs/cmr/features/CMR-00/STATUS.md").read_text(encoding="utf-8")
            status_dir.joinpath("STATUS.md").write_text(source.replace("CMR-00", "CMR-01").replace("f52a53d", "abcdef0"), encoding="utf-8")
            output = root / "board.html"
            output.write_text("stale", encoding="utf-8")
            with self.assertRaises(SystemExit):
                render_status_board.render_board(root, output, check=True)
            statuses = render_status_board.collect_statuses(root)
            self.assertNotEqual(output.read_text(encoding="utf-8"), render_status_board.render_html(statuses))


if __name__ == "__main__":
    unittest.main()
