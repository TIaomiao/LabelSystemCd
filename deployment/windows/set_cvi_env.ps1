$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")

$env:CVI_SEG_BUNDLE_DIR = Join-Path $Root "CMR_segmentation_bundle_20260320"
$env:CVI_SEG_PYTHON = Join-Path $Root ".venvs\cvi-seg\Scripts\python.exe"
$env:CVI_SEG_GPU_ID = "0"
$env:CVI_SEG_GPU_IDS = "0,1,2,3"
$env:CVI_SEG_CASE_BATCH_SIZE = "4"
$env:CVI_SEG_CASE_BATCH_MIN = "1"
$env:CVI_SEG_CASE_BATCH_MAX = "8"
$env:CVI_SEG_DYNAMIC_BATCH = "1"
$env:CVI_SEG_GPU_TARGET_UTILIZATION = "0.85"
$env:CVI_SEG_GPU_RESERVE_MB = "2048"
$env:CVI_SEG_GPU_MODEL_OVERHEAD_MB = "1500"
$env:CVI_SEG_GPU_CASE_MEMORY_MB = "1200"
$env:CVI_GPU_MONITOR_INTERVAL_SECONDS = "5"
$env:CVI_SEG_TIMEOUT_SECONDS = "1800"

$env:CVI_EDGETAM_REPO_DIR = Join-Path $Root "third_party\EdgeTAM"
$env:CVI_EDGETAM_CHECKPOINT = Join-Path $Root "third_party\EdgeTAM\checkpoints\edgetam.pt"
$env:CVI_EDGETAM_CONFIG = Join-Path $Root "third_party\EdgeTAM\sam2\configs\edgetam.yaml"

Write-Host "CVI runtime env loaded from $Root"
