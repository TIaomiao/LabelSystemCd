#!/usr/bin/env python3
"""Render a self-contained, read-only CMR session status board."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


STATUS_START = "<!-- cmr-status"
STATUS_END = "cmr-status -->"
ALLOWED_STATES = {"planned", "demo_only", "technically_verified", "doctor_reviewed", "accepted"}
ALLOWED_SCOPES = {"none", "synthetic", "approved_deidentified"}
ALLOWED_GATE_STATES = {"passed", "failed", "pending", "blocked", "unverified", "not_applicable"}
ALLOWED_FRESHNESS = {"current", "historical", "stale", "unverified"}
ALLOWED_TASK_STATES = {"active", "idle", "not_loaded", "completed", "blocked"}
ALLOWED_COCKPIT_REMOTE_STATES = {"not_pushed", "pushed", "pr_open", "merged"}
REQUIRED_KEYS = {
    "schema_version", "session_id", "feature", "state", "owner_role", "branch",
    "head_commit", "updated_at", "data_scope", "implemented", "demo_only", "not_done",
    "tests", "physician_review", "blockers", "next_action", "evidence_refs",
}
GATE_REQUIRED_KEYS = {
    "id", "label", "state", "evidence_commit", "summary", "verified_at",
    "freshness", "source_ref",
}
TASK_REQUIRED_KEYS = {
    "thread_id", "title", "sessions", "state_snapshot", "last_activity_at",
    "responsibility",
}


class StatusError(ValueError):
    """Raised when a STATUS.md or dashboard registry is malformed."""


def parse_status(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    start = text.find(STATUS_START)
    if start < 0:
        raise StatusError(f"{path}: missing {STATUS_START}")
    payload_start = start + len(STATUS_START)
    end = text.find(STATUS_END, payload_start)
    if end < 0:
        raise StatusError(f"{path}: missing {STATUS_END}")
    raw = text[payload_start:end].strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StatusError(f"{path}: invalid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise StatusError(f"{path}: status must be a JSON object")
    missing = REQUIRED_KEYS - data.keys()
    if missing:
        raise StatusError(f"{path}: missing keys: {', '.join(sorted(missing))}")
    if data["schema_version"] != "cmr.session-status.v1":
        raise StatusError(f"{path}: unsupported schema_version")
    if data["state"] not in ALLOWED_STATES:
        raise StatusError(f"{path}: invalid state {data['state']!r}")
    if data["data_scope"] not in ALLOWED_SCOPES:
        raise StatusError(f"{path}: invalid data_scope {data['data_scope']!r}")
    if not re.fullmatch(r"CMR-\d{2}", str(data["session_id"])):
        raise StatusError(f"{path}: invalid session_id")
    if not re.fullmatch(r"[0-9a-f]{7,40}", str(data["head_commit"])):
        raise StatusError(f"{path}: invalid head_commit")
    if not isinstance(data["tests"], list) or not all(
        isinstance(item, dict) and item.get("result") in {"passed", "failed", "not_run", "blocked"}
        for item in data["tests"]
    ):
        raise StatusError(f"{path}: invalid tests")
    for collection_name in ("formal_gates", "historical_evidence"):
        collection = data.get(collection_name, [])
        if not isinstance(collection, list):
            raise StatusError(f"{path}: {collection_name} must be a list")
        for item in collection:
            if not isinstance(item, dict) or not GATE_REQUIRED_KEYS <= item.keys():
                raise StatusError(f"{path}: invalid {collection_name} item")
            if item["state"] not in ALLOWED_GATE_STATES:
                raise StatusError(f"{path}: invalid gate state {item['state']!r}")
            if item["freshness"] not in ALLOWED_FRESHNESS:
                raise StatusError(f"{path}: invalid freshness {item['freshness']!r}")
            if not re.fullmatch(r"[0-9a-f]{7,40}", str(item["evidence_commit"])):
                raise StatusError(f"{path}: invalid evidence_commit")
    cockpit = data.get("cockpit_delivery")
    if cockpit is not None:
        required = {
            "branch", "verified_commit", "tests", "render_checks", "bundle",
            "remote_state", "updated_at",
        }
        if not isinstance(cockpit, dict) or not required <= cockpit.keys():
            raise StatusError(f"{path}: invalid cockpit_delivery")
        if not re.fullmatch(r"[0-9a-f]{7,40}", str(cockpit["verified_commit"])):
            raise StatusError(f"{path}: invalid cockpit verified_commit")
        if cockpit["remote_state"] not in ALLOWED_COCKPIT_REMOTE_STATES:
            raise StatusError(f"{path}: invalid cockpit remote_state")
        tests = cockpit["tests"]
        if not isinstance(tests, dict) or not {"passed", "total", "state"} <= tests.keys():
            raise StatusError(f"{path}: invalid cockpit tests")
        if tests["state"] not in ALLOWED_GATE_STATES:
            raise StatusError(f"{path}: invalid cockpit test state")
    return data


def collect_statuses(repo_root: Path) -> list[dict[str, Any]]:
    paths = sorted((repo_root / "docs/cmr/features").glob("*/STATUS.md"))
    statuses = [parse_status(path) for path in paths]
    ids = [item["session_id"] for item in statuses]
    if len(ids) != len(set(ids)):
        raise StatusError("duplicate session_id in STATUS.md files")
    return sorted(statuses, key=lambda item: item["session_id"])


def load_task_registry(repo_root: Path, statuses: list[dict[str, Any]]) -> dict[str, Any]:
    path = repo_root / "docs/cmr/CODEX_TASK_REGISTRY.json"
    if not path.is_file():
        return {"schema_version": "cmr.codex-task-registry.v1", "observed_at": None, "tasks": []}
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StatusError(f"{path}: invalid JSON: {exc.msg}") from exc
    if not isinstance(registry, dict) or registry.get("schema_version") != "cmr.codex-task-registry.v1":
        raise StatusError(f"{path}: unsupported schema_version")
    if not isinstance(registry.get("observed_at"), str) or not isinstance(registry.get("tasks"), list):
        raise StatusError(f"{path}: invalid registry envelope")
    known_sessions = {item["session_id"] for item in statuses}
    seen_threads: set[str] = set()
    for task in registry["tasks"]:
        if not isinstance(task, dict) or not TASK_REQUIRED_KEYS <= task.keys():
            raise StatusError(f"{path}: invalid task item")
        thread_id = str(task["thread_id"])
        if not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", thread_id):
            raise StatusError(f"{path}: invalid thread_id")
        if thread_id in seen_threads:
            raise StatusError(f"{path}: duplicate thread_id")
        seen_threads.add(thread_id)
        if task["state_snapshot"] not in ALLOWED_TASK_STATES:
            raise StatusError(f"{path}: invalid task state")
        sessions = task["sessions"]
        if not isinstance(sessions, list) or not sessions or not set(sessions) <= known_sessions:
            raise StatusError(f"{path}: task references unknown session")
        serialized = json.dumps(task, ensure_ascii=False)
        if "/home/" in serialized or re.search(r"[A-Za-z]:\\\\", serialized):
            raise StatusError(f"{path}: task item contains an absolute path")
    return registry


def render_html(
    statuses: list[dict[str, Any]],
    task_registry: dict[str, Any] | None = None,
) -> str:
    status_payload = json.dumps(statuses, ensure_ascii=False, indent=2)
    task_payload = json.dumps(
        task_registry
        or {"schema_version": "cmr.codex-task-registry.v1", "observed_at": None, "tasks": []},
        ensure_ascii=False,
        indent=2,
    )
    template = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CMR Session 看板</title>
  <style>
    :root { color-scheme: light; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f4f6f8; color: #1f2937; }
    header { background: #172554; color: white; padding: 28px 5vw; }
    header h1 { margin: 0 0 8px; font-size: 28px; }
    header p { margin: 0; opacity: .82; }
    main { max-width: 1280px; margin: 24px auto; padding: 0 5vw 48px; }
    h2.section-title { margin: 28px 0 12px; font-size: 21px; }
    .summary { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 20px; }
    .pill { background: white; border: 1px solid #dbe2ea; border-radius: 12px; padding: 12px 16px; min-width: 120px; }
    .pill strong { display: block; font-size: 22px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }
    article, .panel { background: white; border: 1px solid #dbe2ea; border-radius: 14px; padding: 18px; box-shadow: 0 2px 8px rgba(15,23,42,.05); }
    article h2, .panel h3 { margin: 0 0 6px; font-size: 20px; }
    .meta { color: #64748b; font-size: 13px; margin-bottom: 14px; }
    .state, .badge { display: inline-block; border-radius: 999px; padding: 4px 9px; font-size: 12px; font-weight: 700; }
    .state { background: #dbeafe; color: #1e3a8a; }
    .badge.passed, .badge.current { background: #dcfce7; color: #166534; }
    .badge.failed, .badge.blocked { background: #fee2e2; color: #991b1b; }
    .badge.pending, .badge.unverified { background: #ffedd5; color: #9a3412; }
    .badge.historical, .badge.stale { background: #e2e8f0; color: #475569; }
    dl { display: grid; grid-template-columns: 105px 1fr; gap: 7px 10px; margin: 0; font-size: 14px; }
    dt { color: #64748b; }
    dd { margin: 0; word-break: break-word; }
    ul { margin: 6px 0 0; padding-left: 20px; }
    .blocker { color: #9a3412; }
    .gates { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 12px; margin-top: 12px; }
    .gate { border: 1px solid #dbe2ea; border-radius: 12px; padding: 13px; background: #f8fafc; }
    .gate strong { display: block; margin-bottom: 7px; }
    .gate p { margin: 8px 0 0; font-size: 13px; }
    .gate small { color: #64748b; display: block; margin-top: 6px; }
    .subsection { margin-top: 18px; padding-top: 14px; border-top: 1px solid #e2e8f0; }
    .subsection h4 { margin: 0 0 8px; }
    .task-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { text-align: left; vertical-align: top; padding: 10px; border-bottom: 1px solid #e2e8f0; }
    th { color: #475569; background: #f8fafc; }
    code { font-size: 12px; word-break: break-all; }
    footer { color: #64748b; font-size: 12px; margin-top: 24px; }
  </style>
</head>
<body>
  <header>
    <h1>CMR Session 看板</h1>
    <p>只读工程状态；区分当前门禁、历史证据和对话状态快照，不代表临床验收。</p>
  </header>
  <main>
    <section id="summary" class="summary"></section>
    <h2 class="section-title">正式门禁与证据</h2>
    <section id="gates"></section>
    <h2 class="section-title">功能交付状态（来自 STATUS.md）</h2>
    <section id="cards" class="grid"></section>
    <h2 class="section-title">Codex 对话运行状态（人工快照，不代表交付）</h2>
    <section id="tasks" class="panel"></section>
    <footer>生成自仓库内脱敏状态与人工登记的 Codex 任务快照。不要写入病例、DICOM、日志、凭据、模型信息或服务器绝对路径。</footer>
  </main>
  <script>
    const statuses = __STATUS_PAYLOAD__;
    const taskRegistry = __TASK_PAYLOAD__;
    const labels = {planned:"规划中", demo_only:"仅演示", technically_verified:"技术已验证", doctor_reviewed:"医生已复核", accepted:"已接受"};
    const stateLabels = {passed:"通过", failed:"失败", pending:"待完成", blocked:"阻塞", unverified:"待核验", not_applicable:"不适用", active:"进行中", idle:"空闲", not_loaded:"未加载", completed:"已完成"};
    const freshnessLabels = {current:"当前证据", historical:"历史证据", stale:"已过期", unverified:"未核验"};
    const remoteLabels = {not_pushed:"未推送", pushed:"已推送", pr_open:"PR 已建立", merged:"已合并"};
    const esc = (value) => String(value == null ? "" : value).replace(/[&<>"']/g, function(c) { return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; });
    const list = (items) => items.length ? "<ul>" + items.map(function(item) { return "<li>" + esc(item) + "</li>"; }).join("") + "</ul>" : "<span>暂无</span>";
    const badge = (state, label) => "<span class=\"badge " + esc(state) + "\">" + esc(label || stateLabels[state] || state) + "</span>";
    const count = (state) => statuses.filter(function(item) { return item.state === state; }).length;
    const renderGate = (gate) =>
      "<div class=\"gate\"><strong>" + esc(gate.label) + "</strong>" +
      badge(gate.state) + " " + badge(gate.freshness, freshnessLabels[gate.freshness]) +
      "<p>" + esc(gate.summary) + "</p><small>证据提交 " + esc(gate.evidence_commit) +
      " · 核验时间 " + esc(gate.verified_at || "未核验") + "</small></div>";

    document.querySelector("#summary").innerHTML =
      "<div class=\"pill\"><strong>" + statuses.length + "</strong>登记 session</div>" +
      Object.keys(labels).map(function(state) { return "<div class=\"pill\"><strong>" + count(state) + "</strong>" + labels[state] + "</div>"; }).join("");

    const gated = statuses.filter(function(item) {
      return (item.formal_gates || []).length || (item.historical_evidence || []).length || item.cockpit_delivery;
    });
    document.querySelector("#gates").innerHTML = gated.length ? gated.map(function(item) {
      const current = (item.formal_gates || []).map(renderGate).join("");
      const historical = (item.historical_evidence || []).map(renderGate).join("");
      const cockpit = item.cockpit_delivery;
      const cockpitHtml = cockpit ? "<div class=\"subsection\"><h4>Cockpit 交付</h4><div class=\"gate\"><strong>" +
        esc(cockpit.branch) + "</strong>" + badge(cockpit.tests.state, "测试 " + cockpit.tests.passed + "/" + cockpit.tests.total) +
        " " + badge(cockpit.remote_state, remoteLabels[cockpit.remote_state]) +
        "<p>最近验证提交 " + esc(cockpit.verified_commit) + "；生成检查 " + esc(cockpit.render_checks) +
        "；bundle " + esc(cockpit.bundle) + "</p><small>更新于 " + esc(cockpit.updated_at) + "</small></div></div>" : "";
      return "<div class=\"panel\"><h3>" + esc(item.session_id) + " · " + esc(item.feature) + "</h3><div class=\"gates\">" +
        current + "</div>" + (historical ? "<div class=\"subsection\"><h4>历史证据（不得沿用为当前门禁）</h4><div class=\"gates\">" + historical + "</div></div>" : "") +
        cockpitHtml + "</div>";
    }).join("") : "<div class=\"panel\">暂无正式门禁记录。</div>";

    document.querySelector("#cards").innerHTML = statuses.map(function(item) {
      return "<article><h2>" + esc(item.session_id) + " · " + esc(item.feature) + "</h2><div class=\"meta\"><span class=\"state\">" +
        esc(labels[item.state] || item.state) + "</span>　更新于 " + esc(item.updated_at) +
        "</div><dl><dt>分支</dt><dd>" + esc(item.branch) + "</dd><dt>提交</dt><dd>" + esc(item.head_commit) +
        "</dd><dt>Issue / PR</dt><dd>" + esc(item.issue || "暂无") + " / " + esc(item.pr || "暂无") +
        "</dd><dt>完成</dt><dd>" + list(item.implemented) + "</dd><dt>仅演示</dt><dd>" + list(item.demo_only) +
        "</dd><dt>未完成</dt><dd>" + list(item.not_done) + "</dd><dt>阻塞</dt><dd class=\"blocker\">" +
        list(item.blockers) + "</dd><dt>下一步</dt><dd>" + esc(item.next_action) + "</dd></dl></article>";
    }).join("");

    const tasks = taskRegistry.tasks || [];
    document.querySelector("#tasks").innerHTML = tasks.length ?
      "<div class=\"meta\">人工筛选的 CMR 产品任务快照，观测于 " + esc(taskRegistry.observed_at) +
      "；状态可能随后变化，任务 ID 用于回到原对话核验。</div><div class=\"task-wrap\"><table><thead><tr><th>对话</th><th>对应 Session</th><th>状态快照</th><th>职责</th><th>最后活动</th><th>任务 ID</th></tr></thead><tbody>" +
      tasks.map(function(task) { return "<tr><td>" + esc(task.title) + "</td><td>" + esc(task.sessions.join(", ")) +
        "</td><td>" + badge(task.state_snapshot) + "</td><td>" + esc(task.responsibility) + "</td><td>" +
        esc(task.last_activity_at) + "</td><td><code>" + esc(task.thread_id) + "</code></td></tr>"; }).join("") +
      "</tbody></table></div>" : "暂无已登记的 CMR Codex 对话。";
  </script>
</body>
</html>
"""
    return (
        template
        .replace("__STATUS_PAYLOAD__", status_payload)
        .replace("__TASK_PAYLOAD__", task_payload)
    )


def render_board(repo_root: Path, output: Path, check: bool = False) -> list[dict[str, Any]]:
    statuses = collect_statuses(repo_root)
    task_registry = load_task_registry(repo_root, statuses)
    rendered = render_html(statuses, task_registry)
    if check:
        if not output.is_file() or output.read_text(encoding="utf-8") != rendered:
            raise SystemExit(f"{output}: generated board is stale")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"rendered {len(statuses)} sessions and {len(task_registry['tasks'])} tasks to {output}")
    return statuses


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--check", action="store_true", help="fail if generated HTML differs from output")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    output = args.output or (repo_root / "docs/cmr/dashboard/index.html")
    render_board(repo_root, output, check=args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
