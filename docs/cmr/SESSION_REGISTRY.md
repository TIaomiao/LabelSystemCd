# CMR session registry

| ID | Feature | State | Branch/worktree | Last verified commit | Physician review |
|---|---|---|---|---|---|
| CMR-00 | Program control and integration | technically_verified | merged PR #1 | Merge `3c6f21f` server-verified; reviewed baseline tag `cmr-m0-governance-merged-20260904` pushed | not applicable |
| CMR-01 | Shared foundation | technically_verified | PR #2 open from `feat/cmr-01-result-contract` / worktree `cmr-01-result-contract` | rebased verification commit `748767c`: 28 Python tests, generated-type check, compile boundary, diff check and 17 Node tests passed; TypeScript compiler blocked because `tsc` is unavailable; ADR-002 and CI review pending | not scheduled |
| CMR-10 | Cine function | planned | not created | none | not scheduled |
| CMR-11 | Cine strain | planned | not created | none | not scheduled |
| CMR-20 | T1 Mapping/ECV | planned | not created | none | not scheduled |
| CMR-30 | LGE/T2 | planned | not created | none | not scheduled |
| CMR-40 | Perfusion | planned | not created | none | not scheduled |
| CMR-50 | 4D Flow | planned | not created | none | not scheduled |

Each handoff must record scope, branch, worktree, baseline tag, last commit, implemented/demo-only/not-done status, tests, data scope, physician feedback, blockers and the single next action.

## CMR-00 audit notes

- The 2026-08-31 PR screenshot records `All checks have passed` with two
  successful checks at `fad0529`. The repository contains one job in each of
  the CMR Governance and Workstation workflows; both are required for this PR.
- The push credential used for this PR was verified directly on the transfer
  account with `ssh -T git@github.com`, which authenticated as `LarryUESTC`.
  Commit author/committer identity is separately configured as `Codex-Backup`.
- A personal GitHub SSH key and consistent `user.name`/`user.email` for
  `TIaomiao` remain an M0.1 identity-governance task and do not block M0 review.
