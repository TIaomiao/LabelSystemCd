# CMR-01 acceptance evidence

## Automated contract checks

- [ ] valid synthetic scalar result with unit, sources, multi-slice/multi-phase
  selectors, ROI/geometry, algorithm, quality and unreviewed state;
- [ ] valid dimensionless result uses UCUM `1`;
- [ ] valid non-scalar artifact reference and multi-series aggregation;
- [ ] schema -> backend parse -> serialize -> parse round-trip;
- [ ] generated frontend declarations exactly match the canonical schema;
- [ ] missing unit/source/coordinate frame/algorithm version/review rejected;
- [ ] invalid quality enum and unnamespaced extension rejected;
- [ ] unknown major version rejected;
- [ ] unavailable states cannot hide an unexplained null value;
- [ ] changed contour/ROI version is detected as stale;
- [ ] changed result fingerprint invalidates a previous review.

## Repository checks

- [ ] `python3 -m unittest tests.cmr.test_result_contract`
- [ ] existing CMR governance tests
- [ ] Python compile boundary
- [ ] frontend typecheck/test, if dependencies are available
- [ ] `git diff --check`
- [ ] tracked CMR sensitive-artifact/signature scan
- [ ] dashboard generation and `--check`, if a repository command exists

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
