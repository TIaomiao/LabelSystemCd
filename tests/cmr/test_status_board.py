import json
import tempfile
import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/cmr"))
import render_status_board  # noqa: E402
import render_context_packet  # noqa: E402


class StatusBoardTest(unittest.TestCase):
    def test_current_statuses_parse_and_render(self):
        statuses = render_status_board.collect_statuses(ROOT)
        task_registry = render_status_board.load_task_registry(ROOT, statuses)
        self.assertGreaterEqual(len(statuses), 1)
        self.assertEqual(statuses[0]["session_id"], "CMR-00")
        rendered = render_status_board.render_html(statuses, task_registry)
        self.assertIn("CMR Session", rendered)
        self.assertIn("f52a53d", rendered)
        self.assertIn("PR #1 当前头 Checks", rendered)
        self.assertIn("历史证据（不得沿用为当前门禁）", rendered)
        self.assertIn("Cockpit 交付", rendered)
        self.assertIn("PR #3", rendered)
        self.assertIn("CMR-00 · 总控与集成", rendered)
        self.assertIn("建立 CMR 结果公共契约", rendered)
        self.assertIn('<div class=\\"subsection\\">', rendered)
        self.assertNotIn('"<div class="subsection">', rendered)
        self.assertNotIn("/home/", rendered)
        self.assertNotIn("C:\\\\", rendered)

    def test_context_packet_is_model_readable_and_sanitized(self):
        statuses = render_status_board.collect_statuses(ROOT)
        task_registry = render_status_board.load_task_registry(ROOT, statuses)
        packet = render_context_packet.render_packet(statuses, task_registry)
        self.assertIn("CMR-00", packet)
        self.assertIn("唯一下一步", packet)
        self.assertIn("当前正式门禁", packet)
        self.assertIn("历史证据（不得沿用为当前门禁）", packet)
        self.assertIn("正在推进的 Codex 对话", packet)
        self.assertNotIn("/home/", packet)
        self.assertNotIn("C:\\\\", packet)

    def test_task_registry_is_curated_to_cmr_product_threads(self):
        statuses = render_status_board.collect_statuses(ROOT)
        registry = render_status_board.load_task_registry(ROOT, statuses)
        self.assertEqual(len(registry["tasks"]), 3)
        self.assertEqual(
            {task["sessions"][0] for task in registry["tasks"]},
            {"CMR-00", "CMR-01"},
        )
        active_tasks = [task for task in registry["tasks"] if task["state_snapshot"] == "active"]
        self.assertEqual(len(active_tasks), 1)
        self.assertEqual(active_tasks[0]["sessions"], ["CMR-01"])
        serialized = json.dumps(registry, ensure_ascii=False)
        self.assertNotIn("EHR", serialized)
        self.assertNotIn("Workstation 修理", serialized)

    def test_task_registry_rejects_unknown_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "docs/cmr/CODEX_TASK_REGISTRY.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "cmr.codex-task-registry.v1",
                        "observed_at": "2026-09-02T11:33:38+08:00",
                        "tasks": [
                            {
                                "thread_id": "01a051e9-5dcf-7ea3-80ad-ddce1ae5260a",
                                "title": "x",
                                "sessions": ["CMR-99"],
                                "state_snapshot": "active",
                                "last_activity_at": "2026-09-02T11:29:58+08:00",
                                "responsibility": "x",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(render_status_board.StatusError):
                render_status_board.load_task_registry(
                    root,
                    [{"session_id": "CMR-00"}],
                )

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
            self.assertNotEqual(
                output.read_text(encoding="utf-8"),
                render_status_board.render_html(statuses),
            )


if __name__ == "__main__":
    unittest.main()
