#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from ai_v2_config import AiV2Config, load_config
from report_formatter import apply_numeric_report


def _import_pipeline(config: AiV2Config):
    if str(config.agent_source_dir) not in sys.path:
        sys.path.insert(0, str(config.agent_source_dir))
    import full_agent_pipeline as pipeline  # noqa: PLC0415

    pipeline.MRIAGENT_ENV_STATE = Path("/tmp/nonexistent_mriagent_conda_state.json")
    return pipeline


def _apply_api_env(config: AiV2Config) -> None:
    os.environ.update(config.runner_env)


def run_single_case(
    *,
    center: str,
    patient_id: str,
    mode: str,
    output_root: Path | None = None,
    model: str | None = None,
    prompt_profile: str | None = None,
    gpu: int | None = None,
    reuse_metrics: bool = True,
    reuse_plan: bool = True,
    config: AiV2Config | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    _apply_api_env(config)
    pipeline = _import_pipeline(config)

    runner = pipeline.IntegratedEvidenceReportPipeline(
        model=model or config.model,
        output_root=output_root or config.single_case_output_root,
        gpu_id=config.gpu if gpu is None else gpu,
        prompt_profile=prompt_profile or config.prompt_profile,
    )
    if mode == "precompute":
        return runner.run_precompute(center, patient_id, reuse_metrics=reuse_metrics)
    if mode == "llm":
        summary = runner.run_llm_stage(center, patient_id, reuse_plan=reuse_plan)
        apply_numeric_report((output_root or config.single_case_output_root) / center / patient_id)
        return summary
    if mode == "full":
        summary = runner.run(center, patient_id, reuse_metrics=reuse_metrics)
        apply_numeric_report((output_root or config.single_case_output_root) / center / patient_id)
        return summary
    raise ValueError(f"Unsupported mode: {mode}")


def parse_args() -> argparse.Namespace:
    config = load_config()
    parser = argparse.ArgumentParser(description="Run one AI_V2 nlp_metric Agent case with clean LabelSystem defaults.")
    parser.add_argument("--center", default=config.center)
    parser.add_argument("--patient-id", required=True)
    parser.add_argument("--mode", choices=["full", "precompute", "llm"], default="full")
    parser.add_argument("--output-root", type=Path, default=config.single_case_output_root)
    parser.add_argument("--model", default=config.model)
    parser.add_argument("--prompt-profile", default=config.prompt_profile)
    parser.add_argument("--gpu", type=int, default=config.gpu)
    parser.add_argument("--no-reuse-metrics", action="store_true")
    parser.add_argument("--no-reuse-plan", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_single_case(
        center=args.center,
        patient_id=args.patient_id,
        mode=args.mode,
        output_root=args.output_root,
        model=args.model,
        prompt_profile=args.prompt_profile,
        gpu=args.gpu,
        reuse_metrics=not args.no_reuse_metrics,
        reuse_plan=not args.no_reuse_plan,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
