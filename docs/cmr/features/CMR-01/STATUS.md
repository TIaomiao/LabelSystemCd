# CMR-01 shared foundation status

<!-- cmr-status
{"schema_version":"cmr.session-status.v1","session_id":"CMR-01","feature":"Shared result contract and quality foundation","state":"planned","owner_role":"builder","branch":"feat/cmr-01-result-contract","worktree_id":"cmr-01-result-contract","issue":null,"pr":null,"head_commit":"f52a53d","updated_at":"2026-09-02T00:00:00+08:00","data_scope":"synthetic","depends_on":["CMR-00 governance PR not yet merged to main"],"implemented":[],"demo_only":[],"not_done":["canonical schema technical verification","architecture acceptance of ADR-002","downstream module adapters","legacy migration","database persistence","production integration"],"tests":[{"name":"CMR-01 contract tests","result":"not_run"}],"physician_review":{"state":"not_scheduled","cases":[]},"blockers":["CMR-00 governance branch is not merged to main"],"next_action":"Run the complete synthetic contract and repository verification matrix","evidence_refs":["contracts/cmr/result-envelope.schema.json","docs/cmr/decisions/ADR-002-result-contract-v1.md","docs/cmr/features/CMR-01/ACCEPTANCE.md"]}
cmr-status -->

## Summary

Implementation is isolated on `feat/cmr-01-result-contract`. The initial
contract uses synthetic data only and does not connect to a database, clinical
algorithm, legacy runtime, production API route or deployment.

## State separation

- Implemented: pending verification.
- Demo only: none.
- Not done: architecture acceptance, downstream adoption, persistence,
  production integration and physician review.

The highest allowed state in this task is `technically_verified`.
