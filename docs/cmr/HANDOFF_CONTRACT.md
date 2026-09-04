# Cloud planning to Codex execution contract

This contract keeps cloud planning context and repository execution context connected without treating chat history as engineering truth.

## Sources of truth

1. Repository code, contracts, tests and accepted ADRs define the implemented system.
2. One private GitHub issue per feature is the active planning and decision queue.
3. The feature `STATUS.md` and pull request contain execution evidence.
4. Cloud chat transcripts are supporting discussion only.

When sources disagree, Codex must report the conflict. It must not silently change a clinical definition, shared contract or production boundary to match a planning chat.

## Cloud-to-repository handoff

Cloud ChatGPT produces the sections in `.github/ISSUE_TEMPLATE/cmr_feature_plan.md`. Every factual claim must cite a repository path, accepted decision or named reviewer confirmation. Anything else belongs under `Assumptions Codex must verify`.

The issue must contain no patient data, DICOM, runtime database content, logs, credentials, model weights or unpublished clinical material outside the approved planning scope.

## Codex intake gate

Before implementation, Codex must:

1. Read the repository and nested `AGENTS.md` files for the target path.
2. Confirm the baseline branch/tag, clean worktree and current issue/PR state.
3. Recheck every cloud-planning assumption against tracked source or ask for a decision.
4. Classify shared contract, clinical definition, data, deployment and resource risks.
5. Create or register the feature worktree and branch in `SESSION_REGISTRY.md`.
6. Define tests, rollback and physician acceptance before changing feature behavior.

## Execution return contract

The pull request and feature status must report:

- task ID and planning issue;
- implemented, demo-only and not-done scope;
- changed contracts and modules;
- tests actually run and their results;
- data scope and whether any sample was synthetic or approved de-identified data;
- known failures, quality limits and strongest counterexample;
- physician review state;
- rollback path and the single next action.

No UI screenshot, successful command or plausible number alone upgrades a feature to `doctor_reviewed` or `accepted`.

## Context lifecycle

- Planning changes stay in the issue until accepted.
- Stable clinical/product contracts move into `docs/cmr/features/`.
- Architecture decisions affecting multiple modules move into an ADR.
- Execution evidence moves into `STATUS.md`, tests and the PR.
- Closed issues and merged PRs remain the audit trail; do not copy full chat transcripts into the repository.
