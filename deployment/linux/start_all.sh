#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
LOG_DIR="${ROOT_DIR}/.cvi-workspace/logs"
mkdir -p "${LOG_DIR}"

"${ROOT_DIR}/deployment/linux/start_api.sh" >"${LOG_DIR}/api.log" 2>&1 &
API_PID=$!
"${ROOT_DIR}/deployment/linux/start_web.sh" >"${LOG_DIR}/web.log" 2>&1 &
WEB_PID=$!

echo "API PID: ${API_PID}"
echo "WEB PID: ${WEB_PID}"
echo "API : http://127.0.0.1:8010"
echo "WEB : http://127.0.0.1:5174"
echo "Logs: ${LOG_DIR}"

wait
