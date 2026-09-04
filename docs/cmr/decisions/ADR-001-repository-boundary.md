# ADR-001: Keep CMR product code in the LabelSystem monorepo for M0

- Status: Accepted
- Date: 2026-08-30
- Decision owner: CMR product program

## Context

CMR product UI, API integration, case access, persistence, review and reporting
currently depend on LabelSystem. Splitting repositories before those interfaces
are stable would add access-control, release and deployment boundaries without
first reducing product coupling.

The repository can still enforce modular ownership through `apps/api/core/`,
`apps/api/modules/`, `apps/web/src/features/`, `contracts/cmr/`, `tests/cmr/`
and `docs/cmr/`.

## Decision

Keep CMR product runtime code in the LabelSystem monorepo during M0. New product
capabilities use the explicit CMR boundaries above. The new top-level
`contracts/` namespace is intentional and owns versioned cross-module schemas.

Training pipelines, experimental dependencies and model artifacts may move to
a separate private algorithm repository after their interfaces and ownership
are stable. Patient data, DICOM, runtime databases, logs, credentials and model
weights do not move through either source repository.

## Consequences

- Shared contracts and architecture decisions remain reviewable with product
  integration code.
- Feature sessions can use independent worktrees and branches without creating
  incompatible repository-level release processes.
- Legacy code is not considered migrated merely because a target module exists.
- Product and training release cycles remain coupled until the revisit criteria
  below are met.

## Revisit criteria

Re-evaluate a repository split when most of the following are true:

- CMR has an independent owner and release cadence.
- The proportion of code shared with LabelSystem is low.
- API, authentication and case-access boundaries are stable.
- Model services and the product UI can be deployed independently.
- Dataset access is provided through an approved interface rather than paths.
- Independent CI, artifact and versioning policies are operational.

Any change to this decision requires a superseding ADR.
