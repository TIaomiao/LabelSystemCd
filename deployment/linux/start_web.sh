#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
API_PYTHON="${ROOT_DIR}/.venvs/cvi-api/bin/python"
DIST_DIR="${ROOT_DIR}/apps/web/dist"

if [[ ! -x "${API_PYTHON}" ]]; then
  echo "API virtual environment not found. Run deployment/linux/install_runtime.sh first." >&2
  exit 1
fi
if [[ ! -d "${DIST_DIR}" ]]; then
  echo "Web dist directory not found: ${DIST_DIR}" >&2
  exit 1
fi

cd "${DIST_DIR}"
exec "${API_PYTHON}" -m http.server 5174 --bind 0.0.0.0
