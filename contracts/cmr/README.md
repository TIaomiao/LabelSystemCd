# CMR contracts

Versioned data and API contracts shared by CMR backend modules, web features,
tests and report integration belong here.

## Canonical result contract

`result-envelope.schema.json` is the single normative source for CMR result
envelopes. Backend validation reads this file at runtime. Frontend declarations
in `apps/web/src/shared/cmr-result.generated.ts` are generated from it and are
checked byte-for-byte by the CMR contract tests.

Version 1 result and input fingerprints are created and verified by the Python
backend contract boundary. Frontend consumers treat them as opaque; native
`JSON.stringify` is not the v1 fingerprint profile. Repository golden vectors
lock the backend byte profile for non-Python integrations.

Contract versioning follows semantic versioning:

- major: incompatible meaning or shape; unknown majors fail closed;
- minor: compatible behavior within existing fields or namespaced extensions;
- patch: clarifications that do not change accepted payloads.

Version 1 keeps root fields closed. Module-specific payloads belong under a
namespaced `extensions` key, so compatible additions do not require consumers
to reinterpret the common envelope. Deprecations require documentation for at
least one minor line before removal in a new major.

Non-scalar curves, parameter maps and vector fields are immutable artifact
references in v1. The common envelope does not inline large module payloads.
Units use UCUM codes (`1` for dimensionless values and `%` for percentages).

M0 also provides `module-manifest.schema.json` for module ownership and delivery
state. A module manifest is not a result envelope.
