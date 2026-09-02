#!/usr/bin/env python3
"""Render a sanitized Markdown context packet for external planning agents."""

from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_status_board import collect_statuses, load_task_registry  # noqa: E402


def render_packet(
    statuses: list[dict[str, Any]],
    task_registry: dict[str, Any] | None = None,
) -> str:
    lines = [
        "# CMR Session Context Packet",
        "",
        "只读交接摘要。事实来自各功能 `STATUS.md`；代码、Issue、PR和测试仍是最终证据源。",
        "本文件不包含患者、DICOM、数据库、日志、凭据、模型权重或服务器绝对路径。",
        "",
        "## 使用规则",
        "",
        "- 先读取仓库 `AGENTS.md`、`docs/cmr/README.md`、accepted ADR 和目标功能文件。",
        "- `state` 只能是 `planned`、`demo_only`、`technically_verified`、`doctor_reviewed`、`accepted`。",
        "- 技术测试通过不等于临床有效；医生验收状态必须单独确认。",
        "- 规划 agent 不声称实现，执行 agent 必须回写 STATUS.md、commit、测试和唯一下一步。",
        "",
        "## Session 总览",
        "",
        "| Session | 功能 | 状态 | 分支 | Commit | Issue/PR | 阻塞 | 下一步 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in statuses:
        blockers = "；".join(item["blockers"]) or "暂无"
        blockers = blockers.replace("|", "\\|")
        next_action = item["next_action"].replace("|", "\\|")
        lines.append(
            f"| {item['session_id']} | {item['feature']} | {item['state']} | "
            f"`{item['branch']}` | `{item['head_commit']}` | "
            f"{item.get('issue') or '—'} / {item.get('pr') or '—'} | "
            f"{blockers} | {next_action} |"
        )
    for item in statuses:
        test_summary = ";".join(
            test["name"] + "=" + test["result"] for test in item["tests"]
        ) or "暂无"
        lines.extend(
            [
                "",
                f"## {item['session_id']} · {item['feature']}",
                "",
                f"- 状态：`{item['state']}`；更新时间：`{item['updated_at']}`；数据范围：`{item['data_scope']}`",
                f"- 依赖：{', '.join(item.get('depends_on', [])) or '无'}",
                f"- 已实现：{'；'.join(item['implemented']) or '暂无'}",
                f"- 仅演示：{'；'.join(item['demo_only']) or '暂无'}",
                f"- 尚未实现：{'；'.join(item['not_done']) or '暂无'}",
                f"- 测试：{test_summary}",
                f"- 医生复核：`{item['physician_review']['state']}`",
                f"- 阻塞：{'；'.join(item['blockers']) or '暂无'}",
                f"- 唯一下一步：{item['next_action']}",
                f"- 证据索引：{', '.join(f'`{html.escape(ref)}`' for ref in item['evidence_refs']) or '暂无'}",
            ]
        )
        if item.get("formal_gates"):
            lines.extend(["", "### 当前正式门禁", ""])
            for gate in item["formal_gates"]:
                lines.append(
                    f"- {gate['label']}：`{gate['state']}`；证据提交 "
                    f"`{gate['evidence_commit']}`；新鲜度 `{gate['freshness']}`；"
                    f"核验时间 `{gate['verified_at'] or '未核验'}`；{gate['summary']}"
                )
        if item.get("historical_evidence"):
            lines.extend(["", "### 历史证据（不得沿用为当前门禁）", ""])
            for gate in item["historical_evidence"]:
                lines.append(
                    f"- {gate['label']}：`{gate['state']}`；证据提交 "
                    f"`{gate['evidence_commit']}`；核验时间 `{gate['verified_at']}`；"
                    f"{gate['summary']}"
                )
        cockpit = item.get("cockpit_delivery")
        if cockpit:
            lines.extend(
                [
                    "",
                    "### Cockpit 交付",
                    "",
                    f"- 分支：`{cockpit['branch']}`；最近验证提交：`{cockpit['verified_commit']}`",
                    f"- 测试：`{cockpit['tests']['passed']}/{cockpit['tests']['total']}`；"
                    f"生成检查：`{cockpit['render_checks']}`；bundle：`{cockpit['bundle']}`",
                    f"- 远端状态：`{cockpit['remote_state']}`；更新时间：`{cockpit['updated_at']}`",
                ]
            )
    registry = task_registry or {
        "schema_version": "cmr.codex-task-registry.v1",
        "observed_at": None,
        "tasks": [],
    }
    lines.extend(
        [
            "",
            "## 正在推进的 Codex 对话",
            "",
            f"状态快照观测时间：`{registry['observed_at'] or '未登记'}`。"
            "任务状态可能随后变化，thread ID 用于回到原对话核验。",
            "",
            "| 对话 | Session | 状态快照 | 职责 | 最后活动 | Thread ID |",
            "|---|---|---|---|---|---|",
        ]
    )
    for task in registry["tasks"]:
        title = task["title"].replace("|", "\\|")
        responsibility = task["responsibility"].replace("|", "\\|")
        lines.append(
            f"| {title} | {', '.join(task['sessions'])} | {task['state_snapshot']} | "
            f"{responsibility} | `{task['last_activity_at']}` | `{task['thread_id']}` |"
        )
    if not registry["tasks"]:
        lines.append("| 暂无 | — | — | — | — | — |")
    return "\n".join(lines) + "\n"


def render_packet_file(repo_root: Path, output: Path, check: bool = False) -> list[dict[str, Any]]:
    statuses = collect_statuses(repo_root)
    task_registry = load_task_registry(repo_root, statuses)
    rendered = render_packet(statuses, task_registry)
    if check:
        if not output.is_file() or output.read_text(encoding="utf-8") != rendered:
            raise SystemExit(f"{output}: generated context packet is stale")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"rendered {len(statuses)} sessions to {output}")
    return statuses


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    output = args.output or (repo_root / "docs/cmr/dashboard/CONTEXT_PACKET.md")
    render_packet_file(repo_root, output, check=args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
