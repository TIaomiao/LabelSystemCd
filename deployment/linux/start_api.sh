#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
source "${ROOT_DIR}/deployment/linux/set_cvi_env.sh"

API_PYTHON="${ROOT_DIR}/.venvs/cvi-api/bin/python"
if [[ ! -x "${API_PYTHON}" ]]; then
  echo "API virtual environment not found. Run deployment/linux/install_runtime.sh first." >&2
  exit 1
fi

cd "${ROOT_DIR}"
exec "${API_PYTHON}" -m uvicorn apps.api.main:app \
  --host "${CVI_API_HOST:-127.0.0.1}" \
  --port "${CVI_API_PORT:-8010}" \
  --app-dir .
