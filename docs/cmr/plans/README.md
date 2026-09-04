# CMR planning records

Use one private GitHub issue per active feature plan. Issues hold evolving requirements, questions and decisions; this directory only explains the workflow and should not accumulate copied chat transcripts.

## Flow

1. Cloud ChatGPT reads the connected repository sources and produces the feature planning template.
2. The builder creates or updates one GitHub issue from that template.
3. Codex verifies the issue against the repository, then creates an isolated worktree/branch.
4. Accepted contracts are committed under `docs/cmr/features/`; implementation and tests go through a pull request.
5. Codex writes execution evidence to the feature status and PR.
6. Cloud ChatGPT reviews the issue-to-PR delta and plans the next bounded task.

If the cloud GitHub connection cannot read the private repository, paste only the approved, non-sensitive source files into the ChatGPT Project. Do not upload server exports or medical data as a workaround.
