#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export PYTHONPATH="${ROOT_DIR}/src:${PYTHONPATH:-}"
export nnUNet_raw="${ROOT_DIR}/models/nnUNet_raw_data"
export nnUNet_preprocessed="${ROOT_DIR}/models/nnUNet_preprocessed"
export nnUNet_results="${ROOT_DIR}/models"

# 可选：如果要固定 GPU，可以取消注释
# export CUDA_VISIBLE_DEVICES=0
