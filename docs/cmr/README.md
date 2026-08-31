# CMR product program

This directory governs modular development of CMR Workstation product capabilities.

## Scope

- Shared CMR geometry, registration, contour, measurement, provenance and quality contracts.
- Cine function, cine strain, T1 Mapping, LGE/T2, perfusion and 4D Flow modules.
- Technical verification, physician review and controlled integration.

Routine production maintenance belongs to ordinary workstation issues. Lung-cancer EHR governance remains isolated under its own `zian_workspace/ehr_pipeline` rules.

## Read order

1. `ARCHITECTURE.md`
2. Relevant accepted decisions under `decisions/`
3. `ROADMAP.md`
4. `HANDOFF_CONTRACT.md`
5. `GIT_WORKFLOW.md`
6. `SESSION_REGISTRY.md`
7. The selected feature specification and status

Current repository decision:

- `decisions/ADR-001-repository-boundary.md`: keep CMR product runtime code in
  the LabelSystem monorepo for M0 and define the conditions for reconsidering a
  split.

Cloud planning sessions should also use `CLOUD_PROJECT_INSTRUCTIONS.md`. Active plans live in one private GitHub issue per feature; accepted contracts and execution evidence live in this repository and its pull requests.

Chat history is not the source of truth. Update these files at each handoff.
