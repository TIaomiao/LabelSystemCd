# CMR product program guidance

This subtree is the durable source of truth for modular CMR product development. Read `README.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `GIT_WORKFLOW.md`, and `SESSION_REGISTRY.md` before changing a feature.

- Keep product feature work separate from routine workstation maintenance and from `zian_workspace/ehr_pipeline`.
- Use one worktree and feature branch per session. Never develop in the production checkout.
- Do not read or commit patient data, DICOM, runtime databases, logs, credentials, model weights, or ignored exports.
- Use only these delivery states: `planned`, `demo_only`, `technically_verified`, `doctor_reviewed`, `accepted`.
- Every claim must distinguish implemented behavior, demo-only behavior, hypotheses, and work not yet done.
- Shared contracts, database schemas, coordinate systems, contour semantics, AHA segmentation, and reporting interfaces require an architecture decision before feature code changes.
- Each feature must define its clinical contract, prerequisites, failure behavior, provenance, quality controls, tests, rollback path, and physician acceptance plan.
