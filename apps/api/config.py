import os
import shutil
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_DIR = PROJECT_ROOT / ".cvi-workspace"
DB_PATH = WORKSPACE_DIR / "cvi.db"
RENDER_DIR = WORKSPACE_DIR / "renders"
EXPORT_DIR = WORKSPACE_DIR / "exports"
MODEL_RUN_DIR = WORKSPACE_DIR / "model_runs"
DEFAULT_SAMPLE_PATH = PROJECT_ROOT / "0001517610_20250108_cha li ya"
DEFAULT_BUNDLE_DIR = PROJECT_ROOT / "CMR_segmentation_bundle_20260320"
if os.name == "nt":
    DEFAULT_MODEL_PYTHON = Path(r"C:\ProgramData\anaconda3\envs\cvi-seg\python.exe")
else:
    DEFAULT_MODEL_PYTHON = PROJECT_ROOT / ".venvs" / "cvi-seg" / "bin" / "python"
    if not DEFAULT_MODEL_PYTHON.exists():
        for candidate in (
            Path.home() / "miniconda3" / "bin" / "python3",
            Path(shutil.which("python3") or ""),
            Path(sys.executable),
        ):
            if str(candidate) and candidate.exists():
                DEFAULT_MODEL_PYTHON = candidate
                break
MODEL_BUNDLE_DIR = Path(os.environ.get("CVI_SEG_BUNDLE_DIR", str(DEFAULT_BUNDLE_DIR))).expanduser()
MODEL_PYTHON_PATH = Path(os.environ.get("CVI_SEG_PYTHON", str(DEFAULT_MODEL_PYTHON))).expanduser()
MODEL_HELPER_SCRIPT = PROJECT_ROOT / "apps" / "api" / "scripts" / "run_bundle_batch.py"
MODEL_GPU_ID = os.environ.get("CVI_SEG_GPU_ID", "0")
MODEL_GPU_IDS = os.environ.get("CVI_SEG_GPU_IDS", MODEL_GPU_ID)
MODEL_CASE_BATCH_SIZE = int(os.environ.get("CVI_SEG_CASE_BATCH_SIZE", "4"))
MODEL_CASE_BATCH_MIN = int(os.environ.get("CVI_SEG_CASE_BATCH_MIN", "1"))
MODEL_CASE_BATCH_MAX = int(os.environ.get("CVI_SEG_CASE_BATCH_MAX", str(MODEL_CASE_BATCH_SIZE)))
MODEL_DYNAMIC_BATCH = os.environ.get("CVI_SEG_DYNAMIC_BATCH", "1").strip().lower() not in {"0", "false", "no", "off"}
MODEL_GPU_TARGET_UTILIZATION = float(os.environ.get("CVI_SEG_GPU_TARGET_UTILIZATION", "0.85"))
MODEL_GPU_RESERVE_MB = int(os.environ.get("CVI_SEG_GPU_RESERVE_MB", "2048"))
MODEL_GPU_MODEL_OVERHEAD_MB = int(os.environ.get("CVI_SEG_GPU_MODEL_OVERHEAD_MB", "1500"))
MODEL_GPU_CASE_MEMORY_MB = int(os.environ.get("CVI_SEG_GPU_CASE_MEMORY_MB", "1200"))
GPU_MONITOR_INTERVAL_SECONDS = float(os.environ.get("CVI_GPU_MONITOR_INTERVAL_SECONDS", "5"))
MODEL_TIMEOUT_SECONDS = int(os.environ.get("CVI_SEG_TIMEOUT_SECONDS", "1800"))
EDGETAM_REPO_DIR = Path(os.environ.get("CVI_EDGETAM_REPO_DIR", str(PROJECT_ROOT / "third_party" / "EdgeTAM"))).expanduser()
EDGETAM_CHECKPOINT_PATH = Path(
    os.environ.get("CVI_EDGETAM_CHECKPOINT", str(EDGETAM_REPO_DIR / "checkpoints" / "edgetam.pt"))
).expanduser()
EDGETAM_CONFIG_PATH = Path(
    os.environ.get("CVI_EDGETAM_CONFIG", str(EDGETAM_REPO_DIR / "sam2" / "configs" / "edgetam.yaml"))
).expanduser()
EDGETAM_HELPER_SCRIPT = PROJECT_ROOT / "apps" / "api" / "scripts" / "run_edgetam_propagation.py"
EDGETAM_PROMPT_HELPER_SCRIPT = PROJECT_ROOT / "apps" / "api" / "scripts" / "run_edgetam_prompt.py"


def ensure_runtime_dirs() -> None:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_RUN_DIR.mkdir(parents=True, exist_ok=True)


def build_edgetam_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base_env or os.environ)
    pythonpath_parts: list[str] = []
    repo_path = str(EDGETAM_REPO_DIR)
    if repo_path:
        pythonpath_parts.append(repo_path)
    existing_pythonpath = env.get("PYTHONPATH", "")
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    return env
