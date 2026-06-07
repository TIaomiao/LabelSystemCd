from __future__ import annotations

import argparse
import json
import os

# 配置 HuggingFace 镜像源（解决网络连接问题）
# 方法1: 设置环境变量
if "HF_ENDPOINT" not in os.environ:
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# 方法2: 配置 huggingface_hub（如果已安装）
try:
    from huggingface_hub import configure_hf_hub
    configure_hf_hub(endpoint="https://hf-mirror.com")
except (ImportError, Exception):
    pass  # 如果配置失败，继续使用默认设置

from pipelines.diagnosis_pipeline import DiagnosisPipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="多序列心脏MRI诊断系统")
    parser.add_argument(
        "--patient-id",
        default="0004335617",
        help="需要处理的患者ID（对应dataset_cut_mri下的目录）",
    )
    parser.add_argument(
        "--prompt",
        default=None,
        help="可选的诊断提示（如果不提供，从patient_info.json读取）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pipeline = DiagnosisPipeline()
    # 调用改造后的 run() 方法，支持 custom_prompt 参数
    result = pipeline.run(args.patient_id, custom_prompt=args.prompt)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

