# CMR session registry

| ID | Feature | State | Branch/worktree | Last verified commit | Physician review |
|---|---|---|---|---|---|
| CMR-00 | Program control and integration | technically_verified | `chore/cmr-m0-governance` / PR #1；Cockpit `feat/cmr-session-cockpit-mvp` | 当前PR头 `f52a53d`：本地6项治理检查通过，GitHub当前头CI待确认；旧头 `fad0529` 曾2/2；Cockpit `1b9780a` 12项和两项生成检查通过、未推送 | not applicable |
| CMR-01 | Shared foundation | planned | not created | none | architecture review |
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
- The current PR head is `f52a53d`. Its checks, review and merge state remain
  unverified until they are read from the authenticated GitHub page; the
  `fad0529` screenshot is historical evidence only.
- The push credential used for this PR was verified directly on the transfer
  account with `ssh -T git@github.com`, which authenticated as `LarryUESTC`.
  Commit author/committer identity is separately configured as `Codex-Backup`.
- The `TIaomiao` server SSH key was created and manually authenticated on
  2026-09-02. It is passphrase-protected, so unattended push remains disabled
  until the builder unlocks it interactively. Consistent `user.name`/`user.email`
  remains an M0.1 identity-governance task.
- Cockpit commit `1b9780a` passed 12 tests plus both generated-artifact
  checks and has a verified recovery bundle. Its remote branch and PR are not
  yet created.
