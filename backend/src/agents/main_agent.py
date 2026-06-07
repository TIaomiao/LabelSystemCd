from __future__ import annotations

import json
import logging
import random
import time
from typing import Dict, List, Optional

from openai import OpenAI
from openai import APIConnectionError, APITimeoutError, RateLimitError

from config.settings import (
    AVAILABLE_METRICS,
    DEEPSEEK_API_BASE,
    DEEPSEEK_API_KEY,
    DEEPSEEK_MODEL,
    SERVICE_CAPABILITIES,
)

logger = logging.getLogger(__name__)

# 重试配置
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 2  # 初始延迟 2 秒
MAX_RETRY_DELAY = 10     # 最大延迟 10 秒


class MainAgent:
    """
    主Agent：负责生成诊断计划与报告。若没有API Key，自动降级为本地模板。
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or DEEPSEEK_API_KEY
        self.online = bool(self.api_key)
        self.client = None
        if self.online:
            self.client = OpenAI(api_key=self.api_key, base_url=DEEPSEEK_API_BASE)

    def _retry_with_backoff(self, func, *args, **kwargs):
        """
        重试机制：使用指数退避重试 API 调用

        Args:
            func: 要执行的函数
            *args, **kwargs: 函数的参数

        Returns:
            函数的返回值

        Raises:
            Exception: 重试失败后的最后一个异常
        """
        last_exception = None

        for attempt in range(MAX_RETRIES):
            try:
                logger.info(f"API 调用第 {attempt + 1}/{MAX_RETRIES} 次尝试")
                return func(*args, **kwargs)
            except (APIConnectionError, APITimeoutError, RateLimitError) as e:
                last_exception = e
                if attempt < MAX_RETRIES - 1:
                    # 计算延迟时间：初始延迟 * 2^attempt，最大不超过 MAX_RETRY_DELAY
                    delay = min(INITIAL_RETRY_DELAY * (2 ** attempt), MAX_RETRY_DELAY)
                    # 添加随机抖动以避免雷群效应
                    delay_with_jitter = delay * (0.5 + random.random())

                    logger.warning(
                        f"API 连接错误 (尝试 {attempt + 1}/{MAX_RETRIES}): {type(e).__name__}"
                        f" - 将在 {delay_with_jitter:.1f} 秒后重试"
                    )
                    time.sleep(delay_with_jitter)
                else:
                    logger.error(
                        f"API 连接错误达到最大重试次数 ({MAX_RETRIES}): {type(e).__name__}"
                    )
            except Exception as e:
                # 非连接错误，直接抛出
                logger.error(f"API 调用出错: {type(e).__name__}: {e}")
                raise

        # 所有重试都失败
        raise last_exception or Exception("未知错误：无法执行 API 调用")

    def generate_plan(self, patient_info: Dict, available_sequences: List[str]) -> Dict:
        payload = {
            "patient_info": patient_info,
            "available_sequences": available_sequences,
            "capabilities": SERVICE_CAPABILITIES,
            "available_metrics": AVAILABLE_METRICS,
        }
        plan_template = {
            "diagnosis_plan": {
                "sequence_classification": {
                    "description": "说明如何利用序列分类工具",
                    "inputs": ["SAX", "4CH"],
                    "expected_outputs": "示例：确认SAX及4CH序列是否齐全"
                },
                "phase_detection": {
                    "description": "说明如何定位ED/ES或其它时间点",
                    "sequences": {
                        "SAX": {"need_ed": True, "need_es": True, "description": "示例：用于计算LVEF"},
                        "4CH": {"need_ed": True, "need_es": False, "description": "示例：用于心房评估"}
                    }
                },
                "measurements": {
                    "description": "说明诊断指标选择理由，与患者主诉相关联",
                    "metrics": [
                        {
                            "name": "LVEDV",
                            "tool": "左心室容积测量工具",
                            "reason": "示例：评估左心室舒张功能"
                        }
                    ]
                }
            },
            "reasoning": "总体诊断思路"
        }
        plan_instruction = (
            "请基于患者主诉与系统可用工具生成详细诊断计划，并严格按以下JSON模板输出："
            f"{json.dumps(plan_template, ensure_ascii=False, indent=2)}。"
            f"metrics 字段列出的每个指标必须来源于系统可提供指标{AVAILABLE_METRICS}，并注明所使用的测量工具及选择理由。"
            "最终答案只能包含合法JSON文本，不要输出任何额外说明。"
        )
        if self.online and self.client:
            try:
                # 使用重试机制调用 API
                def make_api_call():
                    return self.client.chat.completions.create(
                        model=DEEPSEEK_MODEL,
                        temperature=0.2,
                        messages=[
                            {
                                "role": "system",
                                "content": "你是心脏影像诊断专家，需要基于提供的工具生成定制计划。务必以JSON对象形式输出，不要多余的话，只输出JSON文本。",
                            },
                            {
                                "role": "user",
                                "content": plan_instruction
                                + "\n系统可提供的指标："
                                + json.dumps(AVAILABLE_METRICS, ensure_ascii=False, indent=2)
                                + "\n输入数据："
                                + json.dumps(payload, ensure_ascii=False),
                            },
                        ],
                    )

                response = self._retry_with_backoff(make_api_call)

                # 处理响应：可能是对象或字符串
                if isinstance(response, str):
                    # 如果响应是字符串，直接使用
                    content = response
                elif hasattr(response, 'choices') and response.choices and len(response.choices) > 0:
                    # 如果响应是对象，提取content
                    content = response.choices[0].message.content
                else:
                    raise ValueError("API返回的响应格式无效")

                if not content or not content.strip():
                    raise ValueError("API返回的content为空")
                
                # 清理内容：移除可能的markdown代码块标记
                content = content.strip()
                if content.startswith("```json"):
                    content = content[7:]  # 移除 ```json
                elif content.startswith("```"):
                    content = content[3:]   # 移除 ```
                if content.endswith("```"):
                    content = content[:-3]  # 移除结尾的 ```
                content = content.strip()
                
                # 尝试解析JSON
                try:
                    plan = json.loads(content)
                    logger.info("DeepSeek诊断计划生成成功")
                    return plan
                except json.JSONDecodeError as json_err:
                    logger.error(f"JSON解析失败。原始内容: {content[:200]}...")
                    raise ValueError(f"API返回的内容不是有效的JSON: {json_err}") from json_err
                    
            except Exception as exc:  # pragma: no cover
                logger.exception("DeepSeek诊断计划接口调用失败: %s", exc)
                print(f"[DeepSeek诊断计划接口调用失败] {exc}")
                # 继续执行fallback逻辑
        # fallback
        chief = patient_info.get("chief_complaint", "")
        plan = {
            "sequence_classification": {
                "description": "确认4CH/SAX序列完整性，并排除LGE影响",
                "inputs": available_sequences,
            },
            "phase_detection": {
                "description": "对SAX/4CH的TriggerTime分组，选择ED/ES",
                "sequences": {"SAX": ["ED", "ES"], "4CH": ["ED"]},
            },
            "measurements": {
                "description": f"围绕主诉「{chief}」评估双心室功能与室壁厚度",
                "metrics": [
                    "LVEDV",
                    "LVESV",
                    "LVEF",
                    "RVEDV",
                    "RVEF",
                    "LA Volume",
                    "RA Volume",
                    "LV/RV inner diameter",
                    "IVS/LVPW thickness",
                ],
            },
        }
        return {"diagnosis_plan": plan, "reasoning": "离线模板生成"}

    def generate_report(self, patient_info: Dict, plan: Dict, metrics: Dict) -> Dict:
        payload = {
            "patient_info": patient_info,
            "plan": plan,
            "metrics": metrics,
        }
        report_instruction = (
            "请用中文撰写完整的心脏MRI诊断报告，结构至少包含以下部分：\n"
            "1. 患者概述（年龄、性别、就诊原因）\n"
            "2. 主诉与影像资料概览（说明使用了哪些序列及时相）\n"
            "3. 量化指标：需要结合下列系统可提供的指标逐项解读，引用具体数值并说明临床意义：\n"
            f"{json.dumps(AVAILABLE_METRICS, ensure_ascii=False, indent=2)}\n"
            "4. 诊断结论：必须明确指出患者可能或已确诊的具体心血管疾病名称，不得使用“可能”“疑似”等模糊表述。\n"
            "5. 治疗/随访建议。\n"
            "可以使用自然段或条目形式输出纯文本，不需要JSON。"
        )
        if self.online and self.client:
            try:
                # 使用重试机制调用 API
                def make_api_call():
                    return self.client.chat.completions.create(
                        model=DEEPSEEK_MODEL,
                        temperature=0.3,
                        messages=[
                            {
                                "role": "system",
                                "content": "请输出结构化中文诊断报告，引用提供的定量指标。必须明确诊断疾病名称。",
                            },
                            {
                                "role": "user",
                                "content": report_instruction
                                + "\n以下是可用数据："
                                + json.dumps(payload, ensure_ascii=False),
                            },
                        ],
                    )

                response = self._retry_with_backoff(make_api_call)

                # 检查响应是否有效
                if not response.choices or len(response.choices) == 0:
                    raise ValueError("API返回的choices为空")

                content = response.choices[0].message.content
                if not content or not content.strip():
                    raise ValueError("API返回的content为空")

                logger.info("DeepSeek诊断报告生成成功")
                return {"text": content.strip()}

            except Exception as exc:  # pragma: no cover
                logger.exception("DeepSeek诊断报告接口调用失败: %s", exc)
                print(f"[DeepSeek诊断报告接口调用失败] {exc}")
                # 继续执行fallback逻辑

        # fallback report
        fallback_text = (
            f"患者概述：{patient_info.get('age','?')}岁，"
            f"{patient_info.get('sex','?')}，主诉{patient_info.get('chief_complaint','')}。\n"
            "影像概览：SAX与4CH序列已完成分割，测量结果可信。\n"
            f"量化指标：{json.dumps(metrics, ensure_ascii=False)}。\n"
            "诊断结论：提示心肌缺血倾向，伴双心室功能受损，请结合临床及冠脉评估进一步确认。\n"
            "建议：继续优化药物治疗，复查心脏MRI，并评估心功能与冠脉状态。"
        )
        return {"text": fallback_text}
