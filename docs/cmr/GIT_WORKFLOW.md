# CMR Git workflow

## Checkout roles

- `/home/Larry/code/Ziqiu/LabelSystem`: production checkout; deployment only.
- `/home/zian/projects/LabelSystem`: clean personal clone.
- `/home/zian/worktrees/LabelSystem/<session>`: one isolated worktree per feature session.

## Required flow

1. Start from a reviewed baseline tag.
2. Create a feature branch and dedicated worktree.
3. Keep the change inside the feature boundary; propose shared changes separately.
4. Run targeted tests, `git diff --check`, contract checks and a sensitive-data scan.
5. Push the feature branch and open a PR with validation, clinical/data risk and rollback notes.
6. Merge only after CI and review.
7. Keep incomplete clinical features behind a feature flag.
8. Deploy only from a reviewed commit/tag with a release record.

Never discard an unknown dirty change to make a checkout look clean. Back up and classify it first.
