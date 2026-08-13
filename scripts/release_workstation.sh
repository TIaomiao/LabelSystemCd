#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: scripts/release_workstation.sh vYYYY.MM.DD-N" >&2
}

tag="${1:-}"
if [[ ! "$tag" =~ ^v[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]+$ ]]; then
  usage
  exit 2
fi

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Refusing release: worktree is not clean." >&2
  exit 1
fi
if [[ "$(git branch --show-current)" != "main" ]]; then
  echo "Refusing release: current branch is not main." >&2
  exit 1
fi
if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
  echo "Refusing release: tag $tag already exists." >&2
  exit 1
fi

expected_version="$(sed -n "s/.*WORKSTATION_VERSION = '\([^']*\)'.*/\1/p" frontend/src/utils/workstationMeta.ts | head -n 1)"
if [[ "$expected_version" != "$tag" ]]; then
  echo "Refusing release: WORKSTATION_VERSION is $expected_version, expected $tag." >&2
  exit 1
fi

npm --prefix apps/web run build
npm --prefix frontend run build
PYTHONPATH=tests .venvs/cvi-api/bin/python -m unittest \
  tests.test_tissue_lge_primary \
  tests.test_dicom_split_sax_import \
  tests.test_lge_mvo_measurements

git tag -a "$tag" -m "CMR Workstation $tag"
git push origin main
git push origin "$tag"

echo "Released $(git rev-parse --short HEAD) as $tag."
