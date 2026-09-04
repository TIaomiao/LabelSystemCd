# CMR modular architecture

## Current boundaries

- `backend/` and `frontend/`: LabelSystem portal, access control, case catalog, evaluation and feedback integration.
- `apps/api/` and `apps/web/`: embedded CMR Workstation runtime.
- `apps/web/legacy-runtime/`: compatibility layer for the frozen viewer runtime; avoid placing new feature logic directly in the monolithic patch when a maintained extension is possible.
- `backend/src/`: legacy/experimental agent pipeline; no new CMR product modules without a separate decision.
- `zian_workspace/`: historical personal and sensitive artifacts; no new product source.

## Target boundaries

```text
apps/api/core/                 shared CMR foundations
apps/api/modules/<feature>/    feature backends
apps/web/src/features/         maintained feature UI extensions
contracts/cmr/                 versioned API/data contracts
tests/cmr/                     cross-module and contract tests
docs/cmr/                      program decisions and handoffs
```

M0 adds boundaries and templates only. Existing services are not moved until their behavior is covered by tests and mapped to a stable contract.

## Required result provenance

Every exported metric must be able to identify its value, unit, source series, slice/phase, source contour or ROI, algorithm version, parameters, quality flags and review status.
