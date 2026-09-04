# CMR session registry

| ID | Feature | State | Branch/worktree | Last verified commit | Physician review |
|---|---|---|---|---|---|
| CMR-00 | Program control and integration | technically_verified | PR #1 merged；Cockpit PR #3 open | merge `3c6f21f`与父提交已在服务器核验；基线tag `cmr-m0-governance-merged-20260904`已推送；PR #3等待CI与工程评审 | not applicable |
| CMR-01 | Shared foundation | technically_verified | PR #2 open from `feat/cmr-01-result-contract` / worktree `cmr-01-result-contract` | rebased verification commit `748767c`：28项Python、生成类型、compile、diff与17项Node测试通过；TypeScript编译因缺少tsc阻塞；ADR-002与CI待评审 | not scheduled |
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
- The builder reported on 2026-09-04 that the current `f52a53d` checks passed
  2/2 and senior engineering confirmation completed. PR #1 merged as
  `3c6f21f`; the server verified the merge object and pushed baseline tag
  `cmr-m0-governance-merged-20260904`.
- The push credential used for this PR was verified directly on the transfer
  account with `ssh -T git@github.com`, which authenticated as `LarryUESTC`.
  Commit author/committer identity is separately configured as `Codex-Backup`.
- The `TIaomiao` server SSH key was created and manually authenticated on
  2026-09-02. It is passphrase-protected, so unattended push remains disabled
  until the builder unlocks it interactively. Consistent `user.name`/`user.email`
  remains an M0.1 identity-governance task.
- Cockpit verification passed 12 tests plus both generated-artifact checks and
  has a verified recovery bundle. Remote branch `feat/cmr-session-cockpit-mvp`
  is published and PR #3 is open.
