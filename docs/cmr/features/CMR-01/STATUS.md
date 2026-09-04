# CMR-01 共享结果契约与质量底座状态

<!-- cmr-status
{"schema_version":"cmr.session-status.v1","session_id":"CMR-01","feature":"共享结果契约与质量底座","state":"technically_verified","owner_role":"builder","branch":"feat/cmr-01-result-contract","worktree_id":"cmr-01-result-contract","issue":null,"pr":"#2","head_commit":"00cd6c0","updated_at":"2026-09-04T11:24:28+08:00","data_scope":"synthetic","depends_on":[],"implemented":["canonical JSON Schema result envelope v1","schema-driven backend parse validation serialization and stale checks","generated frontend TypeScript contract boundary with drift check","synthetic scalar dimensionless artifact and negative fixtures","proposed ADR-002 and CMR-01 specification evidence","rebased onto reviewed baseline cmr-m0-governance-merged-20260904 at 3c6f21f","branch pushed to origin","GitHub PR #2 已建立并进入架构与工程评审","backend-authoritative v1 fingerprint profile with golden vector","verified input_fingerprint and closed declared lineage"],"demo_only":[],"not_done":["architecture acceptance of ADR-002","downstream module adapters","legacy migration","database persistence","production integration","physician review"],"tests":[{"name":"CMR contract tests (24)","result":"passed"},{"name":"CMR governance regressions (7)","result":"passed"},{"name":"generated type drift check","result":"passed"},{"name":"Python compile boundary","result":"passed"},{"name":"git diff check","result":"passed"},{"name":"apps/web Node tests (17)","result":"passed"},{"name":"apps/web TypeScript 5.9.3 typecheck","result":"passed"}],"physician_review":{"state":"not_scheduled","cases":[]},"blockers":["ADR-002 尚待授权架构评审者接受","GitHub PR #2 CI 尚待核验"],"next_action":"核验 PR #2 GitHub CI，并由授权架构评审者接受或退回 ADR-002","evidence_refs":["contracts/cmr/result-envelope.schema.json","docs/cmr/decisions/ADR-002-result-contract-v1.md","docs/cmr/features/CMR-01/ACCEPTANCE.md"]}
cmr-status -->

## 摘要

- 已实现：公共 JSON Schema、后端校验/序列化/stale 检测、前端生成类型、后端权威指纹、输入指纹校验、封闭 lineage、合成夹具和契约测试。
- 已验证：31 项 Python 测试、生成类型漂移检查、Python 编译边界、diff 检查、17 项 Node 测试和 TypeScript 5.9.3 typecheck。
- 未完成：ADR-002 授权架构接受、下游接入、持久化、生产集成和医生复核。
- 数据范围：仅合成 opaque identifier；没有病例、DICOM、数据库或生产操作。

PR #2 已建立；当前主线是核验 GitHub CI，并由授权架构评审者接受或退回 ADR-002。
功能交付状态仍为 `technically_verified`；对话是否正在运行由独立的 Codex 对话快照展示，不改变本状态。
