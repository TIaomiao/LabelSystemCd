#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: scripts/rollback_workstation.sh <release-tag> [--push]" >&2
  echo "Creates a new rollback commit; it never rewrites Git history or touches runtime data." >&2
}

tag="${1:-}"
push_after=false
if [[ "${2:-}" == "--push" ]]; then
  push_after=true
elif [[ -n "${2:-}" ]]; then
  usage
  exit 2
fi

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

if [[ -z "$tag" ]] || ! git rev-parse -q --verify "refs/tags/$tag^{commit}" >/dev/null; then
  echo "Unknown release tag: $tag" >&2
  exit 2
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo "Refusing rollback: worktree is not clean." >&2
  exit 1
fi
if [[ "$(git branch --show-current)" != "main" ]]; then
  echo "Refusing rollback: current branch is not main." >&2
  exit 1
fi

current_head="$(git rev-parse HEAD)"
target_head="$(git rev-parse "$tag^{commit}")"
echo "Current: $current_head"
echo "Target:  $target_head ($tag)"

tracked_paths=(apps backend frontend tests scripts docs .github)
git restore --source="$tag" --staged --worktree -- "${tracked_paths[@]}"

if git diff --cached --quiet; then
  echo "No tracked workstation changes are required for $tag."
  exit 0
fi

git commit -m "revert: restore workstation source to $tag"

if $push_after; then
  git push origin main
fi

echo "Rollback commit created. Deploy it through the normal verified installation workflow."
