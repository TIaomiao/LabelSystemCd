#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
RUNTIME_DIR="${LABELSYSTEM_DEMO_RUNTIME_DIR:-${ROOT_DIR}/.labelsystem-demo}"
CASE_ROOT="${LABELSYSTEM_DEMO_CASE_ROOT:-${RUNTIME_DIR}/cases}"
BACKEND_PORT="${LABELSYSTEM_DEMO_BACKEND_PORT:-15000}"
CVI_PORT="${LABELSYSTEM_DEMO_CVI_PORT:-18010}"
WEB_PORT="${LABELSYSTEM_DEMO_WEB_PORT:-15173}"
BACKEND_PYTHON="${LABELSYSTEM_PYTHON:-$(command -v python)}"
API_PYTHON="${ROOT_DIR}/.venvs/cvi-api/bin/python"

if [[ ! -x "${API_PYTHON}" ]]; then
  echo "CVI API environment is missing: ${API_PYTHON}" >&2
  exit 1
fi
if [[ ! -d "${ROOT_DIR}/frontend/dist" ]]; then
  echo "Frontend build is missing. Run: cd frontend && npm run build" >&2
  exit 1
fi

mkdir -p \
  "${CASE_ROOT}" \
  "${RUNTIME_DIR}/eval" \
  "${RUNTIME_DIR}/functional" \
  "${RUNTIME_DIR}/cvi-workspace" \
  "${RUNTIME_DIR}/logs"

SECRET_FILE="${RUNTIME_DIR}/secret_key"
if [[ ! -s "${SECRET_FILE}" ]]; then
  "${BACKEND_PYTHON}" -c 'import secrets; print(secrets.token_urlsafe(48))' >"${SECRET_FILE}"
  chmod 600 "${SECRET_FILE}"
fi

export LABELSYSTEM_SECRET_KEY="$(<"${SECRET_FILE}")"
export LABELSYSTEM_DB_PATH="${RUNTIME_DIR}/labelsystem.db"
export LABELSYSTEM_DATA_ROOT="${CASE_ROOT}"
export LABELSYSTEM_DEMO_CASE_ROOT="${CASE_ROOT}"
export LABELSYSTEM_EVAL_ROOT="${RUNTIME_DIR}/eval"
export LABELSYSTEM_FUNCTIONAL_DATA_ROOT="${RUNTIME_DIR}/functional"
export LABELSYSTEM_PORT="${BACKEND_PORT}"
export LABELSYSTEM_CORS_ORIGINS="http://127.0.0.1:${WEB_PORT},http://localhost:${WEB_PORT}"
export CVI_WORKSPACE_DIR="${RUNTIME_DIR}/cvi-workspace"
export CVI_DEFAULT_SAMPLE_PATH="${CASE_ROOT}"
export CVI_API_HOST="127.0.0.1"
export CVI_API_PORT="${CVI_PORT}"
export CVI_API_BASE="http://127.0.0.1:${CVI_PORT}"
export LABELSYSTEM_BACKEND_ORIGIN="http://127.0.0.1:${BACKEND_PORT}"

pids=()
cleanup() {
  for pid in "${pids[@]:-}"; do
    kill "${pid}" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

cd "${ROOT_DIR}"
"${BACKEND_PYTHON}" backend/app.py >"${RUNTIME_DIR}/logs/backend.log" 2>&1 &
pids+=("$!")
"${ROOT_DIR}/deployment/linux/start_api.sh" >"${RUNTIME_DIR}/logs/cvi-api.log" 2>&1 &
pids+=("$!")
PORT="${WEB_PORT}" HOST="127.0.0.1" \
  "${BACKEND_PYTHON}" frontend/serve_prod.py >"${RUNTIME_DIR}/logs/web.log" 2>&1 &
pids+=("$!")

echo "LabelSystem demo is starting with isolated runtime state."
echo "Web:      http://127.0.0.1:${WEB_PORT}"
echo "Backend:  http://127.0.0.1:${BACKEND_PORT}"
echo "CVI API:  http://127.0.0.1:${CVI_PORT}"
echo "Cases:    ${CASE_ROOT}"
echo "Runtime:  ${RUNTIME_DIR}"
echo "Press Ctrl-C to stop all three demo processes."

wait -n "${pids[@]}"
echo "A demo process exited; stopping the remaining processes." >&2
exit 1
