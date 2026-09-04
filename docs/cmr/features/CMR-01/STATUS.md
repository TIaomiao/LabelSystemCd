# CMR-01 shared foundation status

<!-- cmr-status
{"schema_version":"cmr.session-status.v1","session_id":"CMR-01","feature":"Shared result contract and quality foundation","state":"technically_verified","owner_role":"builder","branch":"feat/cmr-01-result-contract","worktree_id":"cmr-01-result-contract","issue":null,"pr":"#2","head_commit":"748767c","updated_at":"2026-09-04T11:09:22+08:00","data_scope":"synthetic","depends_on":[],"implemented":["canonical JSON Schema result envelope v1","schema-driven backend parse validation serialization and stale checks","generated frontend TypeScript contract boundary with drift check","synthetic scalar dimensionless artifact and negative fixtures","proposed ADR-002 and CMR-01 specification evidence","rebased onto reviewed baseline cmr-m0-governance-merged-20260904 at 3c6f21f","branch pushed to origin","GitHub PR #2 已建立并进入架构与工程评审"],"demo_only":[],"not_done":["architecture acceptance of ADR-002","frontend TypeScript compiler execution","downstream module adapters","legacy migration","database persistence","production integration","physician review"],"tests":[{"name":"CMR contract tests (21)","result":"passed"},{"name":"CMR governance regressions (7)","result":"passed"},{"name":"generated type drift check","result":"passed"},{"name":"Python compile boundary","result":"passed"},{"name":"git diff check","result":"passed"},{"name":"apps/web Node tests (17)","result":"passed"},{"name":"apps/web TypeScript typecheck","result":"blocked"}],"physician_review":{"state":"not_scheduled","cases":[]},"blockers":["apps/web TypeScript typecheck 因前端依赖未安装而找不到 tsc","ADR-002 尚待架构评审"],"next_action":"在 PR #2 完成 ADR-002 架构评审并检查 GitHub CI","evidence_refs":["contracts/cmr/result-envelope.schema.json","docs/cmr/decisions/ADR-002-result-contract-v1.md","docs/cmr/features/CMR-01/ACCEPTANCE.md"]}
cmr-status -->

## Summary

Technically verified on `feat/cmr-01-result-contract` at rebased verification
commit `748767c` with 28
Python tests, the generated-type drift check and 17 Node tests. The
contract uses synthetic data only and does not connect to a database, clinical
algorithm, legacy runtime, production API route or deployment. The TypeScript
compiler check remains blocked because `tsc` is not installed in this worktree;
Node and npm themselves are available.

## State separation

- Implemented: canonical schema, backend boundary, generated frontend types,
  stale detection, synthetic fixtures and repository tests.
- Demo only: none.
- Not done: architecture acceptance, TypeScript compiler evidence, downstream
  adoption, persistence, production integration and physician review.

PR #2 已建立。当前主线是在该 PR 完成 ADR-002 架构评审并检查 GitHub
CI；状态仍为 `technically_verified`，医生复核尚未安排。
