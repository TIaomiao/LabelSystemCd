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
- [ ] frontend typecheck/test: blocked because the server shell has no `npm`
- [x] `git diff --check`
- [x] tracked CMR sensitive-artifact/signature scan
- [ ] dashboard generation and `--check`: blocked because no repository command exists

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
