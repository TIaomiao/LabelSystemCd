# CMR-01 shared foundation status

<!-- cmr-status
{"schema_version":"cmr.session-status.v1","session_id":"CMR-01","feature":"Shared result contract and quality foundation","state":"technically_verified","owner_role":"builder","branch":"feat/cmr-01-result-contract","worktree_id":"cmr-01-result-contract","issue":null,"pr":null,"head_commit":"1a73726","updated_at":"2026-09-02T11:48:03+08:00","data_scope":"synthetic","depends_on":["CMR-00 governance PR not yet merged to main"],"implemented":["canonical JSON Schema result envelope v1","schema-driven backend parse validation serialization and stale checks","generated frontend TypeScript contract boundary with drift check","synthetic scalar dimensionless artifact and negative fixtures","proposed ADR-002 and CMR-01 specification evidence"],"demo_only":[],"not_done":["architecture acceptance of ADR-002","frontend compiler and node test execution","downstream module adapters","legacy migration","database persistence","production integration","physician review"],"tests":[{"name":"CMR contract tests (21)","result":"passed"},{"name":"CMR governance regressions (7)","result":"passed"},{"name":"generated type drift check","result":"passed"},{"name":"Python compile boundary","result":"passed"},{"name":"git diff check","result":"passed"},{"name":"frontend typecheck and tests","result":"blocked"},{"name":"dashboard generation and check","result":"blocked"}],"physician_review":{"state":"not_scheduled","cases":[]},"blockers":["CMR-00 governance branch is not merged to main","server shell has no npm for frontend compiler and test execution","repository has no CMR dashboard generation/check command"],"next_action":"Open the CMR-01 pull request for architecture and engineering review","evidence_refs":["contracts/cmr/result-envelope.schema.json","docs/cmr/decisions/ADR-002-result-contract-v1.md","docs/cmr/features/CMR-01/ACCEPTANCE.md"]}
cmr-status -->

## Summary

Technically verified on `feat/cmr-01-result-contract` with 28 Python tests. The
contract uses synthetic data only and does not connect to a database, clinical
algorithm, legacy runtime, production API route or deployment. Frontend npm
checks and dashboard checks remain blocked as recorded above.

## State separation

- Implemented: canonical schema, backend boundary, generated frontend types,
  stale detection, synthetic fixtures and repository tests.
- Demo only: none.
- Not done: architecture acceptance, downstream adoption, persistence,
  production integration and physician review.

The state is `technically_verified`; physician review remains not scheduled.
