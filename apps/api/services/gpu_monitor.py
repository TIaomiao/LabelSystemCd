from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any

from ..config import (
    GPU_MONITOR_INTERVAL_SECONDS,
    MODEL_CASE_BATCH_MAX,
    MODEL_CASE_BATCH_MIN,
    MODEL_CASE_BATCH_SIZE,
    MODEL_DYNAMIC_BATCH,
    MODEL_GPU_CASE_MEMORY_MB,
    MODEL_GPU_MODEL_OVERHEAD_MB,
    MODEL_GPU_RESERVE_MB,
    MODEL_GPU_TARGET_UTILIZATION,
)


@dataclass
class GpuSnapshot:
    index: int
    name: str
    utilization_gpu: float
    utilization_memory: float
    memory_total_mb: int
    memory_used_mb: int
    memory_free_mb: int
    temperature_c: int | None
    sampled_at: float


class GpuMonitor:
    def __init__(self, interval_seconds: float) -> None:
        self.interval_seconds = max(1.0, float(interval_seconds))
        self._snapshots: list[GpuSnapshot] = []
        self._last_error: str | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.sample_once()
        self._thread = threading.Thread(target=self._loop, name="cvi-gpu-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.sample_once()

    def sample_once(self) -> None:
        command = [
            "nvidia-smi",
            "--query-gpu=index,name,utilization.gpu,utilization.memory,memory.total,memory.used,memory.free,temperature.gpu",
            "--format=csv,noheader,nounits",
        ]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
            if completed.returncode != 0:
                raise RuntimeError((completed.stderr or completed.stdout or "nvidia-smi failed").strip())
            sampled_at = time.time()
            snapshots: list[GpuSnapshot] = []
            for line in completed.stdout.splitlines():
                parts = [part.strip() for part in line.split(",")]
                if len(parts) < 8:
                    continue
                snapshots.append(
                    GpuSnapshot(
                        index=int(parts[0]),
                        name=parts[1],
                        utilization_gpu=float(parts[2]),
                        utilization_memory=float(parts[3]),
                        memory_total_mb=int(float(parts[4])),
                        memory_used_mb=int(float(parts[5])),
                        memory_free_mb=int(float(parts[6])),
                        temperature_c=int(float(parts[7])) if parts[7] else None,
                        sampled_at=sampled_at,
                    )
                )
            with self._lock:
                self._snapshots = snapshots
                self._last_error = None
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)

    def snapshots(self, refresh_if_empty: bool = True) -> list[GpuSnapshot]:
        if refresh_if_empty:
            with self._lock:
                is_empty = not self._snapshots
            if is_empty:
                self.sample_once()
        with self._lock:
            return list(self._snapshots)

    def status(self) -> dict[str, Any]:
        snapshots = self.snapshots()
        with self._lock:
            error = self._last_error
        return {
            "available": bool(snapshots),
            "error": error,
            "interval_seconds": self.interval_seconds,
            "dynamic_batch": {
                "enabled": MODEL_DYNAMIC_BATCH,
                "target_utilization": MODEL_GPU_TARGET_UTILIZATION,
                "reserve_mb": MODEL_GPU_RESERVE_MB,
                "model_overhead_mb": MODEL_GPU_MODEL_OVERHEAD_MB,
                "case_memory_mb": MODEL_GPU_CASE_MEMORY_MB,
                "batch_min": MODEL_CASE_BATCH_MIN,
                "batch_default": MODEL_CASE_BATCH_SIZE,
                "batch_max": MODEL_CASE_BATCH_MAX,
            },
            "gpus": [asdict(snapshot) for snapshot in snapshots],
        }


gpu_monitor = GpuMonitor(GPU_MONITOR_INTERVAL_SECONDS)


def get_gpu_status() -> dict[str, Any]:
    return gpu_monitor.status()


def estimate_safe_case_batch_size(gpu_id: int | None, pending_items: int) -> int:
    if not MODEL_DYNAMIC_BATCH or gpu_id is None:
        return max(MODEL_CASE_BATCH_MIN, min(MODEL_CASE_BATCH_SIZE, MODEL_CASE_BATCH_MAX, max(1, pending_items)))

    snapshots = {snapshot.index: snapshot for snapshot in gpu_monitor.snapshots() or []}
    snapshot = snapshots.get(int(gpu_id))
    if snapshot is None:
        return max(MODEL_CASE_BATCH_MIN, min(MODEL_CASE_BATCH_SIZE, MODEL_CASE_BATCH_MAX, max(1, pending_items)))

    target_used_mb = int(snapshot.memory_total_mb * MODEL_GPU_TARGET_UTILIZATION)
    usable_for_cases = target_used_mb - snapshot.memory_used_mb - MODEL_GPU_RESERVE_MB - MODEL_GPU_MODEL_OVERHEAD_MB
    estimated = usable_for_cases // max(1, MODEL_GPU_CASE_MEMORY_MB)
    safe_batch = max(MODEL_CASE_BATCH_MIN, min(int(estimated), MODEL_CASE_BATCH_MAX, max(1, pending_items)))
    return safe_batch


def gpu_has_safe_capacity(gpu_id: int | None) -> bool:
    if gpu_id is None or not MODEL_DYNAMIC_BATCH:
        return True
    snapshots = {snapshot.index: snapshot for snapshot in gpu_monitor.snapshots() or []}
    snapshot = snapshots.get(int(gpu_id))
    if snapshot is None:
        return True
    target_used_mb = int(snapshot.memory_total_mb * MODEL_GPU_TARGET_UTILIZATION)
    usable_for_cases = target_used_mb - snapshot.memory_used_mb - MODEL_GPU_RESERVE_MB - MODEL_GPU_MODEL_OVERHEAD_MB
    return usable_for_cases >= MODEL_GPU_CASE_MEMORY_MB * max(1, MODEL_CASE_BATCH_MIN)


def sort_gpus_by_headroom(gpu_ids: list[int | None]) -> list[int | None]:
    snapshots = {snapshot.index: snapshot for snapshot in gpu_monitor.snapshots() or []}

    def headroom(gpu_id: int | None) -> int:
        if gpu_id is None:
            return 0
        snapshot = snapshots.get(int(gpu_id))
        if snapshot is None:
            return 0
        target_used_mb = int(snapshot.memory_total_mb * MODEL_GPU_TARGET_UTILIZATION)
        return target_used_mb - snapshot.memory_used_mb

    return sorted(gpu_ids, key=headroom, reverse=True)
