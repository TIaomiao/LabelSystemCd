# CMR-01 shared foundation status

<!-- cmr-status
{"schema_version":"cmr.session-status.v1","session_id":"CMR-01","feature":"Shared result contract and quality foundation","state":"technically_verified","owner_role":"builder","branch":"feat/cmr-01-result-contract","worktree_id":"cmr-01-result-contract","issue":null,"pr":"#2","head_commit":"00cd6c0","updated_at":"2026-09-04T11:24:28+08:00","data_scope":"synthetic","depends_on":[],"implemented":["canonical JSON Schema result envelope v1","schema-driven backend parse validation serialization and stale checks","generated frontend TypeScript contract boundary with drift check","synthetic scalar dimensionless artifact and negative fixtures","proposed ADR-002 and CMR-01 specification evidence","rebased onto reviewed baseline cmr-m0-governance-merged-20260904 at 3c6f21f","branch pushed to origin","GitHub PR #2 已建立并进入架构与工程评审","backend-authoritative v1 fingerprint profile with golden vector","verified input_fingerprint and closed declared lineage"],"demo_only":[],"not_done":["architecture acceptance of ADR-002","downstream module adapters","legacy migration","database persistence","production integration","physician review"],"tests":[{"name":"CMR contract tests (24)","result":"passed"},{"name":"CMR governance regressions (7)","result":"passed"},{"name":"generated type drift check","result":"passed"},{"name":"Python compile boundary","result":"passed"},{"name":"git diff check","result":"passed"},{"name":"apps/web Node tests (17)","result":"passed"},{"name":"apps/web TypeScript 5.9.3 typecheck","result":"passed"}],"physician_review":{"state":"not_scheduled","cases":[]},"blockers":["ADR-002 尚待授权架构评审者接受","GitHub PR #2 CI 尚待核验"],"next_action":"核验 PR #2 GitHub CI，并由授权架构评审者接受或退回 ADR-002","evidence_refs":["contracts/cmr/result-envelope.schema.json","docs/cmr/decisions/ADR-002-result-contract-v1.md","docs/cmr/features/CMR-01/ACCEPTANCE.md"]}
cmr-status -->

## Summary

Technically verified on `feat/cmr-01-result-contract` at architecture-fix
commit `00cd6c0` with 31 Python tests, the generated-type drift check, 17 Node
tests and a TypeScript 5.9.3 typecheck. The
contract uses synthetic data only and does not connect to a database, clinical
algorithm, legacy runtime, production API route or deployment.

## State separation

- Implemented: canonical schema, backend boundary, generated frontend types,
  stale detection, verified input fingerprints, closed declared lineage,
  synthetic fixtures and repository tests.
- Demo only: none.
- Not done: architecture acceptance, downstream adoption, persistence,
  production integration and physician review.

PR #2 已建立。当前主线是核验 GitHub CI，并由授权架构评审者接受或退回
ADR-002；状态仍为 `technically_verified`，医生复核尚未安排。
