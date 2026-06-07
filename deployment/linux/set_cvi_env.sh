#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"

export CVI_SEG_BUNDLE_DIR="${CVI_SEG_BUNDLE_DIR:-${ROOT_DIR}/CMR_segmentation_bundle_20260320}"
if [[ -z "${CVI_SEG_PYTHON:-}" ]]; then
  if [[ -x "${ROOT_DIR}/.venvs/cvi-seg/bin/python" ]]; then
    export CVI_SEG_PYTHON="${ROOT_DIR}/.venvs/cvi-seg/bin/python"
  elif [[ -x "${HOME}/miniconda3/bin/python3" ]]; then
    export CVI_SEG_PYTHON="${HOME}/miniconda3/bin/python3"
  elif command -v python3 >/dev/null 2>&1; then
    export CVI_SEG_PYTHON="$(command -v python3)"
  else
    export CVI_SEG_PYTHON="$(command -v python)"
  fi
fi
export CVI_SEG_GPU_ID="${CVI_SEG_GPU_ID:-0}"
export CVI_SEG_GPU_IDS="${CVI_SEG_GPU_IDS:-0,1,2,3}"
export CVI_SEG_CASE_BATCH_SIZE="${CVI_SEG_CASE_BATCH_SIZE:-4}"
export CVI_SEG_CASE_BATCH_MIN="${CVI_SEG_CASE_BATCH_MIN:-1}"
export CVI_SEG_CASE_BATCH_MAX="${CVI_SEG_CASE_BATCH_MAX:-8}"
export CVI_SEG_DYNAMIC_BATCH="${CVI_SEG_DYNAMIC_BATCH:-1}"
export CVI_SEG_GPU_TARGET_UTILIZATION="${CVI_SEG_GPU_TARGET_UTILIZATION:-0.85}"
export CVI_SEG_GPU_RESERVE_MB="${CVI_SEG_GPU_RESERVE_MB:-2048}"
export CVI_SEG_GPU_MODEL_OVERHEAD_MB="${CVI_SEG_GPU_MODEL_OVERHEAD_MB:-1500}"
export CVI_SEG_GPU_CASE_MEMORY_MB="${CVI_SEG_GPU_CASE_MEMORY_MB:-1200}"
export CVI_GPU_MONITOR_INTERVAL_SECONDS="${CVI_GPU_MONITOR_INTERVAL_SECONDS:-5}"
export CVI_SEG_TIMEOUT_SECONDS="${CVI_SEG_TIMEOUT_SECONDS:-1800}"

export CVI_EDGETAM_REPO_DIR="${CVI_EDGETAM_REPO_DIR:-${ROOT_DIR}/third_party/EdgeTAM}"
export CVI_EDGETAM_CHECKPOINT="${CVI_EDGETAM_CHECKPOINT:-${ROOT_DIR}/third_party/EdgeTAM/checkpoints/edgetam.pt}"
export CVI_EDGETAM_CONFIG="${CVI_EDGETAM_CONFIG:-${ROOT_DIR}/third_party/EdgeTAM/sam2/configs/edgetam.yaml}"

export PYTHONPATH="${ROOT_DIR}:${CVI_EDGETAM_REPO_DIR}:${PYTHONPATH:-}"

echo "CVI runtime env loaded from ${ROOT_DIR}"
