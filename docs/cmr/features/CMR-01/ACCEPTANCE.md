# CMR-01 acceptance evidence

## Automated contract checks

- [x] valid synthetic scalar result with unit, sources, multi-slice/multi-phase
  selectors, ROI/geometry, algorithm, quality and unreviewed state;
- [x] valid dimensionless result uses UCUM `1`;
- [x] valid non-scalar artifact reference and multi-series aggregation;
- [x] schema -> backend parse -> serialize -> parse round-trip;
- [x] generated frontend declarations exactly match the canonical schema;
- [x] missing unit/source/coordinate frame/algorithm version/review rejected;
- [x] invalid quality enum and unnamespaced extension rejected;
- [x] unknown major version rejected;
- [x] unavailable states cannot hide an unexplained null value;
- [x] changed contour/ROI or algorithm version is detected as stale;
- [x] changed result fingerprint invalidates a previous review.

## Repository checks

- [x] `python3 -m unittest tests.cmr.test_result_contract` (21 passed)
- [x] existing CMR governance tests (7 passed)
- [x] Python compile boundary
- [x] `npm --prefix apps/web run test` (17 passed)
- [ ] frontend typecheck: blocked because `tsc` is not installed in the
  worktree; Node and npm are available
- [x] `git diff --check`
- [x] tracked CMR sensitive-artifact/signature scan
- [ ] Cockpit status synchronization and generated-dashboard checks are owned
  by the separate `feat/cmr-session-cockpit-mvp` branch

## Evidence scope

- Cases: 0
- DICOM: 0
- Database rows: 0
- Fixtures: synthetic JSON with obvious `syn-*` identifiers
- External API calls: 0
- Deployment/service restart: none

## Physician acceptance

`not_scheduled`. No automated result, screenshot or quality disposition changes
this state.

## Rollback

Before adoption, revert the isolated CMR-01 commit/PR. After a downstream module
adopts v1, rollback must keep the v1 reader or publish a compatible successor;
deleting fields or silently treating a new major as v1 is not a valid rollback.
