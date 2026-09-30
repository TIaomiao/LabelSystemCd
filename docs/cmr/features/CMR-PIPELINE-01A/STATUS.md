# CMR-PIPELINE-01A DICOM 上传与 Intake 状态

<!-- cmr-status
{
  "schema_version": "cmr.session-status.v1",
  "session_id": "CMR-PIPELINE-01A",
  "feature": "DICOM upload, resumable intake and series manifest",
  "state": "planned",
  "owner_role": "builder",
  "branch": "not-created",
  "worktree_id": null,
  "issue": null,
  "pr": null,
  "head_commit": "0000000",
  "updated_at": "2026-09-30T00:00:00+08:00",
  "data_scope": "none",
  "depends_on": ["CMR-01 result/manifest contract decision"],
  "implemented": [],
  "demo_only": [],
  "not_done": [
    "apps/api upload route verification",
    "upload session and resumable transfer contract",
    "secure staging and archive extraction",
    "DICOM header indexing and Series manifest",
    "persistent task state",
    "frontend progress display",
    "server integration verification"
  ],
  "tests": [
    {"name": "planned acceptance suite", "result": "not_run"}
  ],
  "physician_review": {"state": "not_scheduled", "cases": []},
  "blockers": [
    "Cloud planning Issue has not been created",
    "Target apps/api upload and storage boundaries require server verification",
    "MRIAgent ownership and clean development baseline remain separate concerns"
  ],
  "next_action": "Turn the execution packet into a private GitHub Issue, then run the server intake gate in a clean worktree",
  "evidence_refs": [
    "features/CMR-PIPELINE-01A/CLOUD_PLANNING_BRIEF.md",
    "features/CMR-PIPELINE-01A/CONTEXT_PACKET.md",
    "PIPELINE_INTEGRATION_PLAN.md",
    "SERIES_MANIFEST_INPUT_SPEC.md",
    "docs/cmr/CLOUD_CODEX_WORKFLOW.md",
    "docs/cmr/SESSION_PLAYBOOK.md"
  ]
}
cmr-status -->

## 当前摘要

CMR-PIPELINE-01A 处于规划阶段。当前执行包固定上传、暂存、校验、Intake 和 Series manifest 范围，尚未创建 Issue、branch、worktree 或 PR。

## 已知边界

- 术析页面已观察到文件夹选择入口，但其前端行为不能证明 `apps/api` 已具备同样能力；
- DeepSeek 的旧 showcase 链路证据用于迁移参考，不等于目标架构已经实现；
- 本任务不读取病例、DICOM、数据库、日志或凭据。
