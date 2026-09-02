# CMR-01 shared result contract specification

## Status

`technically_verified`. This state is based on synthetic contract tests only;
there is no physician or production acceptance.

## Product scope

- Goal: establish one versioned CMR result envelope for backend, frontend,
  reports and later module adapters.
- Non-goals: clinical algorithms, thresholds, normal ranges, database
  persistence, legacy migration, deployment and physician case acceptance.
- Data scope: synthetic opaque identifiers only.
- Downstream consumers: CMR-10, CMR-11, CMR-20, CMR-30, CMR-40 and CMR-50.

## Contract groups

The envelope requires:

1. contract version and result identity/fingerprint;
2. metric identity;
3. value state, scalar or artifact reference, and UCUM unit;
4. source series and multi-slice/multi-phase selectors;
5. ROI/contour context or explicit not-applicable reason;
6. geometry context with coordinate frame or explicit not-applicable reason;
7. algorithm identity/version/parameters;
8. immutable lineage and input fingerprint;
9. machine-readable quality assessment;
10. independent human review state.

## Required behavior

- Missing unit, source series, coordinate frame, algorithm version or review
  state fails validation.
- Unknown incompatible major versions fail closed.
- A range with `start > end` fails validation.
- Selectors may reference only declared source series.
- ROI references may point only to declared geometry references.
- Provenance lineage must contain the recorded algorithm, series, ROI, geometry
  and parameter-manifest versions.
- Current input versions can be compared without reading the input contents.
- Serialization and reparsing preserve every public and extension field.
- Unknown namespaced extensions are preserved but are not interpreted by the
  common layer.

## Backend boundary

`apps.api.core.measurements.parse_result` is the shared parsing entry point.
`serialize_result` provides deterministic round-trip serialization.
`validate_result_against_current_inputs` detects stale upstream references.
These functions do not calculate a clinical metric or access runtime data.

## Frontend boundary

`apps/web/src/shared/cmr-result.generated.ts` is generated from the canonical
schema. Modules import the generated declarations or wrap them with a narrow
adapter; they must not copy the envelope into a private interface.

## Extension rules

- Extension keys use a dotted lowercase namespace owned by one module.
- Extension values are objects and remain opaque to common consumers.
- New common semantics require an ADR and version review.
- Large arrays, maps and vector fields use versioned artifact references.
- A future artifact schema may define payload internals without changing the
  common envelope major version.

## Failure boundaries

- Schema validation does not establish clinical correctness.
- Staleness detection depends on immutable upstream version discipline.
- No legacy result adapter or persistence migration is included.
- No production API route or UI is connected in this task.
