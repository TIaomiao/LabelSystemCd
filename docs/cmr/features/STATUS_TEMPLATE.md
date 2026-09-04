# CMR 功能 Session 状态

本文件是跨平台交接入口。任何云端 GPT、DeepSeek、Kimi 或 Codex 都先读这里的机器区块，再读本功能的 `SPEC.md`、`CLINICAL_CONTRACT.md` 和 `ACCEPTANCE.md`。机器区块不得写患者、DICOM、数据库、日志、凭据、模型权重或服务器绝对路径。

<!-- cmr-status
{
  "schema_version": "cmr.session-status.v1",
  "session_id": "CMR-XX",
  "feature": "功能名称",
  "state": "planned",
  "owner_role": "builder",
  "branch": "feat/cmr-...",
  "worktree_id": "cmr-...",
  "issue": null,
  "pr": null,
  "head_commit": "0000000",
  "updated_at": "2026-09-01T00:00:00+08:00",
  "data_scope": "none",
  "depends_on": [],
  "implemented": [],
  "demo_only": [],
  "not_done": ["尚未开始"],
  "tests": [{"name": "未运行", "result": "not_run"}],
  "physician_review": {"state": "not_scheduled", "cases": []},
  "blockers": [],
  "next_action": "填写本功能的临床契约和验收条件",
  "evidence_refs": ["docs/cmr/features/CMR-XX/SPEC.md"],
  "formal_gates": [],
  "historical_evidence": []
}
cmr-status -->

## 本轮摘要

- 完成：
- 未完成：
- 已知反例/失败边界：
- 需要决定：
