#!/usr/bin/env python3
"""Render a self-contained, read-only CMR session status board."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any


STATUS_START = "<!-- cmr-status"
STATUS_END = "cmr-status -->"
ALLOWED_STATES = {"planned", "demo_only", "technically_verified", "doctor_reviewed", "accepted"}
ALLOWED_SCOPES = {"none", "synthetic", "approved_deidentified"}
REQUIRED_KEYS = {
    "schema_version", "session_id", "feature", "state", "owner_role", "branch",
    "head_commit", "updated_at", "data_scope", "implemented", "demo_only", "not_done",
    "tests", "physician_review", "blockers", "next_action", "evidence_refs",
}


class StatusError(ValueError):
    """Raised when a STATUS.md machine block is malformed."""


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
    return data


def collect_statuses(repo_root: Path) -> list[dict[str, Any]]:
    paths = sorted((repo_root / "docs/cmr/features").glob("*/STATUS.md"))
    statuses = [parse_status(path) for path in paths]
    ids = [item["session_id"] for item in statuses]
    if len(ids) != len(set(ids)):
        raise StatusError("duplicate session_id in STATUS.md files")
    return sorted(statuses, key=lambda item: item["session_id"])


def render_html(statuses: list[dict[str, Any]]) -> str:
    payload = json.dumps(statuses, ensure_ascii=False, indent=2)
    title = "CMR Session 看板"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{ color-scheme: light; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }}
    body {{ margin: 0; background: #f4f6f8; color: #1f2937; }}
    header {{ background: #172554; color: white; padding: 28px 5vw; }}
    header h1 {{ margin: 0 0 8px; font-size: 28px; }}
    header p {{ margin: 0; opacity: .82; }}
    main {{ max-width: 1280px; margin: 24px auto; padding: 0 5vw 48px; }}
    .summary {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 20px; }}
    .pill {{ background: white; border: 1px solid #dbe2ea; border-radius: 12px; padding: 12px 16px; min-width: 120px; }}
    .pill strong {{ display: block; font-size: 22px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }}
    article {{ background: white; border: 1px solid #dbe2ea; border-radius: 14px; padding: 18px; box-shadow: 0 2px 8px rgba(15,23,42,.05); }}
    article h2 {{ margin: 0 0 6px; font-size: 20px; }}
    .meta {{ color: #64748b; font-size: 13px; margin-bottom: 14px; }}
    .state {{ display: inline-block; border-radius: 999px; padding: 4px 9px; background: #dbeafe; color: #1e3a8a; font-size: 12px; font-weight: 700; }}
    dl {{ display: grid; grid-template-columns: 105px 1fr; gap: 7px 10px; margin: 0; font-size: 14px; }}
    dt {{ color: #64748b; }} dd {{ margin: 0; word-break: break-word; }}
    ul {{ margin: 6px 0 0; padding-left: 20px; }}
    .blocker {{ color: #9a3412; }}
    footer {{ color: #64748b; font-size: 12px; margin-top: 24px; }}
  </style>
</head>
<body>
  <header><h1>{title}</h1><p>只读工程状态；事实来自各功能 STATUS.md，不代表临床验收。</p></header>
  <main><section id="summary" class="summary"></section><section id="cards" class="grid"></section><footer>生成自仓库内脱敏状态文件。不要把病例、DICOM、日志、凭据或模型信息写入状态。</footer></main>
  <script>
    const statuses = {payload};
    const labels = {{planned:'规划中', demo_only:'仅演示', technically_verified:'技术已验证', doctor_reviewed:'医生已复核', accepted:'已接受'}};
    const esc = (value) => String(value).replace(/[&<>\"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}}[c]));
    const list = (items) => items.length ? '<ul>' + items.map(item => '<li>' + esc(item) + '</li>').join('') + '</ul>' : '<span>暂无</span>';
    const count = (state) => statuses.filter(item => item.state === state).length;
    document.querySelector('#summary').innerHTML = '<div class="pill"><strong>' + statuses.length + '</strong>登记 session</div>' + Object.keys(labels).map(state => '<div class="pill"><strong>' + count(state) + '</strong>' + labels[state] + '</div>').join('');
    document.querySelector('#cards').innerHTML = statuses.map(item => '<article><h2>' + esc(item.session_id) + ' · ' + esc(item.feature) + '</h2><div class="meta"><span class="state">' + esc(labels[item.state] || item.state) + '</span>　更新于 ' + esc(item.updated_at) + '</div><dl><dt>分支</dt><dd>' + esc(item.branch) + '</dd><dt>提交</dt><dd>' + esc(item.head_commit) + '</dd><dt>Issue / PR</dt><dd>' + esc(item.issue || '暂无') + ' / ' + esc(item.pr || '暂无') + '</dd><dt>完成</dt><dd>' + list(item.implemented) + '</dd><dt>仅演示</dt><dd>' + list(item.demo_only) + '</dd><dt>未完成</dt><dd>' + list(item.not_done) + '</dd><dt>阻塞</dt><dd class="blocker">' + list(item.blockers) + '</dd><dt>下一步</dt><dd>' + esc(item.next_action) + '</dd></dl></article>').join('');
  </script>
</body>
</html>
"""


def render_board(repo_root: Path, output: Path, check: bool = False) -> list[dict[str, Any]]:
    statuses = collect_statuses(repo_root)
    rendered = render_html(statuses)
    if check:
        if not output.is_file() or output.read_text(encoding="utf-8") != rendered:
            raise SystemExit(f"{output}: generated board is stale")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"rendered {len(statuses)} sessions to {output}")
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
