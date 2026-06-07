#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
API_VENV="${ROOT_DIR}/.venvs/cvi-api"

PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "Creating API virtual environment: ${API_VENV}"
"${PYTHON_BIN}" -m venv "${API_VENV}"
"${API_VENV}/bin/python" -m pip install --upgrade pip setuptools wheel
"${API_VENV}/bin/python" -m pip install -r "${ROOT_DIR}/apps/api/requirements.txt"

echo ""
echo "Runtime install complete."
echo "API Python: ${API_VENV}/bin/python"
echo "SEG Python: set by deployment/linux/set_cvi_env.sh"
