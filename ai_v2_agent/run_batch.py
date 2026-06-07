#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ai_v2_config import AiV2Config, load_config
from report_formatter import apply_numeric_report


FATAL_PATTERNS = {
    "llm_credit_insufficient": ["金币余额不足", "Error code: 402"],
    "invalid_model": ["model not found or invalid", "not a valid model ID"],
}


def load_cases(cases_json: Path, *, limit: int | None = None, start_order: int = 1) -> list[dict[str, Any]]:
    items = json.loads(cases_json.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = []
    for item in items:
        order = int(item.get("order") or len(cases) + 1)
        if order < start_order:
            continue
        case_name = item.get("case") or Path(str(item.get("configured") or "")).name
        if not case_name:
            continue
        cases.append(
            {
                "order": order,
                "center": item.get("center") or "CMR_ALL",
                "patient_id": case_name,
                "source_case_dir": item.get("source_case_dir"),
                "input_root": item.get("input_root"),
            }
        )
        if limit is not None and len(cases) >= limit:
            break
    return cases


def case_output_dir(config: AiV2Config, center: str, patient_id: str) -> Path:
    return config.output_root / center / patient_id


def copy_reusable_cardiac_metrics(config: AiV2Config, center: str, patient_id: str) -> tuple[bool, str | None]:
    out_dir = case_output_dir(config, center, patient_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "metrics_cardiac_function_raw.json"
    if target.exists():
        return True, str(target)

    for root in config.function_metrics_roots:
        source = root / patient_id / "metrics.json"
        if source.exists():
            shutil.copy2(source, target)
            return True, str(source)
    return False, None


def build_item(config: AiV2Config, case: dict[str, Any], returncode: int, elapsed: float, log_path: Path) -> dict[str, Any]:
    out_dir = case_output_dir(config, case["center"], case["patient_id"])
    item = {
        "order": case["order"],
        "center": case["center"],
        "patient_id": case["patient_id"],
        "returncode": returncode,
        "elapsed_seconds": round(elapsed, 2),
        "output_dir": str(out_dir),
        "report_path": str(out_dir / "report.json"),
        "report_exists": (out_dir / "report.json").exists(),
        "evidence_exists": (out_dir / "evidence.json").exists(),
        "metrics_merged_exists": (out_dir / "metrics_merged.json").exists(),
        "metrics_raw_exists": (out_dir / "metrics_cardiac_function_raw.json").exists(),
        "log_path": str(log_path),
        "model": config.model,
        "lge_model": config.lge_model,
        "api_base": config.api_base,
    }
    if returncode != 0 and log_path.exists():
        log_tail = log_path.read_text(encoding="utf-8", errors="ignore")[-5000:]
        for reason, patterns in FATAL_PATTERNS.items():
            if any(pattern in log_tail for pattern in patterns):
                item["stop_reason"] = reason
                if reason == "llm_credit_insufficient":
                    item["returncode"] = 402
                break
    return item


def write_summary(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(sorted(items, key=lambda row: row["order"]), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def run_case(config: AiV2Config, case: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    out_dir = case_output_dir(config, case["center"], case["patient_id"])
    log_path = config.log_dir / f"ai_v2_report150_{case['order']:03d}.log"
    if (out_dir / "report.json").exists() and not force:
        return build_item(config, case, 0, 0.0, log_path)

    metrics_ok, metrics_source = copy_reusable_cardiac_metrics(config, case["center"], case["patient_id"])
    if not metrics_ok:
        log_path.write_text(f"missing cardiac function metrics for {case['patient_id']}\n", encoding="utf-8")
        item = build_item(config, case, 20, 0.0, log_path)
        item["stop_reason"] = "missing_cardiac_function_metrics"
        return item

    single_runner = config.label_root / "ai_v2_agent" / "run_single.py"
    common = [
        sys.executable,
        str(single_runner),
        "--center",
        case["center"],
        "--patient-id",
        case["patient_id"],
        "--output-root",
        str(config.output_root),
        "--gpu",
        str(config.gpu),
        "--model",
        config.model,
        "--prompt-profile",
        config.prompt_profile,
    ]
    commands = [common + ["--mode", "precompute"], common + ["--mode", "llm"]]
    config.log_dir.mkdir(parents=True, exist_ok=True)
    start = time.time()
    returncode = 0
    with log_path.open("w", encoding="utf-8") as log:
        log.write(json.dumps({"case": case, "metrics_source": metrics_source, "config": _safe_config(config)}, ensure_ascii=False, indent=2))
        log.write("\n")
        for command in commands:
            log.write("\n[cmd] " + " ".join(command) + "\n")
            log.flush()
            result = subprocess.run(command, cwd=str(config.label_root), env=config.runner_env, stdout=log, stderr=subprocess.STDOUT)
            returncode = result.returncode
            if returncode != 0:
                break
    if returncode == 0 and (out_dir / "report.json").exists():
        apply_numeric_report(out_dir)
    return build_item(config, case, returncode, time.time() - start, log_path)


def _safe_config(config: AiV2Config) -> dict[str, Any]:
    def normalize(value):
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, tuple):
            return [normalize(item) for item in value]
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        return value

    payload = asdict(config)
    payload["api_key"] = "***"
    return normalize(payload)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate AI_V2 reports for the configured 150-case CMR_ALL set.")
    parser.add_argument("--limit", type=int, default=None, help="Only run first N eligible cases.")
    parser.add_argument("--start-order", type=int, default=1, help="Start from this configured order.")
    parser.add_argument("--force", action="store_true", help="Regenerate even if report.json already exists.")
    parser.add_argument("--no-stop-on-fatal", action="store_true", help="Continue after fatal dependency/API failures.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config()
    config.output_root.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)

    previous: dict[int, dict[str, Any]] = {}
    if config.summary_path.exists():
        try:
            previous = {int(item["order"]): item for item in json.loads(config.summary_path.read_text(encoding="utf-8"))}
        except Exception:
            previous = {}

    cases = load_cases(config.cases_json, limit=args.limit, start_order=args.start_order)
    active_orders = {case["order"] for case in cases}
    for case in cases:
        print(f"[ai_v2] start {case['order']}/150 {case['patient_id']}", flush=True)
        item = run_case(config, case, force=args.force)
        previous[case["order"]] = item
        write_summary(config.summary_path, list(previous.values()))
        print(
            f"[ai_v2] done {case['order']}/150 rc={item['returncode']} "
            f"report={item['report_exists']} log={item['log_path']}",
            flush=True,
        )
        if not args.no_stop_on_fatal and item.get("stop_reason") in {"llm_credit_insufficient", "invalid_model", "missing_cardiac_function_metrics"}:
            print(f"[ai_v2] stop_reason={item['stop_reason']}", flush=True)
            raise SystemExit(int(item.get("returncode") or 1))

    failures = [
        item
        for item in previous.values()
        if item.get("order") in active_orders and (item.get("returncode") != 0 or not item.get("report_exists"))
    ]
    if failures:
        print(f"[ai_v2] failed count={len(failures)} first={failures[:3]}", flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
