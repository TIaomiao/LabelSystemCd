
"""
报告生成器 - 从JSON报告生成HTML，支持LLM调用和缓存
"""

import json
import sys
from pathlib import Path
from typing import Optional, Dict, Any


class ReportHTMLGenerator:
    """
    报告HTML生成器，从JSON报告生成HTML
    支持缓存机制（如果HTML已存在则直接返回）
    """

    def __init__(self):
        """初始化报告生成器"""
        # 确保能导入 DeepSeek 相关模块
        base_dir = Path(__file__).resolve().parent.parent
        src_dir = base_dir / "src"
        if str(src_dir) not in sys.path:
            sys.path.insert(0, str(src_dir))

    def generate_html_from_json(
        self,
        json_report_path: Path,
        html_output_path: Path
    ) -> str:
        """
        从JSON报告生成HTML
        """
        # 检查缓存
        if html_output_path.exists():
            with open(html_output_path, "r", encoding="utf-8") as f:
                return f.read()

        # 读取JSON报告
        if not json_report_path.exists():
            raise FileNotFoundError(f"JSON report not found: {json_report_path}")

        with open(json_report_path, "r", encoding="utf-8") as f:
            report_data = json.load(f)

        # 调用LLM生成HTML
        html_content = self._call_llm_to_generate_html(report_data)

        # 保存到本地
        html_output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(html_output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return html_content

    def get_html_or_generate(
        self,
        json_report_path: Path,
        html_output_path: Path
    ) -> str:
        """
        获取或生成HTML
        """
        try:
            return self.generate_html_from_json(json_report_path, html_output_path)
        except Exception as e:
            # 如果生成失败，返回一个简单的错误页面
            return self._generate_error_html(str(e))

    def _call_llm_to_generate_html(self, report_data: Dict[str, Any]) -> str:
        """
        调用LLM API生成HTML
        """
        try:
            from llm_api.deepseek_api import DeepSeekAPI

            api = DeepSeekAPI()

            # 构建提示
            prompt = self._build_html_generation_prompt(report_data)

            # 调用LLM
            html_content = api.call(prompt)

            # 提取HTML内容（如果LLM返回的是包装的文本）
            html_content = self._extract_html_from_response(html_content)

            return html_content

        except ImportError:
            # 如果找不到DeepSeek模块，使用默认HTML模板
            return self._generate_default_html(report_data)
        except Exception as e:
            # 如果LLM调用失败，使用默认HTML模板
            print(f"Warning: LLM generation failed: {e}")
            return self._generate_default_html(report_data)

    def _build_html_generation_prompt(self, report_data: Dict[str, Any]) -> str:
        """
        构建HTML生成提示
        """
        report_json = json.dumps(report_data, ensure_ascii=False, indent=2)

        prompt = f"""你是一个医学报告HTML生成专家。请根据以下JSON格式的心脏MRI诊断报告数据，生成一份专业、美观的HTML医学报告。

报告数据：
```json
{report_json}
```

要求：
1. 生成完整的HTML5文档（包含<!DOCTYPE html>等）
2. 使用现代CSS样式，确保响应式设计
3. 包含以下部分：
   - 标题和基本患者信息
   - 诊断计划摘要
   - 详细的分析结果
   - 测量指标（如果有）
   - 临床建议
4. 使用表格展示结构化数据
5. 使用清晰的排版和颜色突出重点
6. 包含页脚和日期信息
7. 适配打印（@media print）

请直接生成HTML代码，不需要其他说明。"""

        return prompt

    def _extract_html_from_response(self, response: str) -> str:
        """
        从LLM响应中提取HTML内容
        """
        # 如果响应是被代码块包装的，提取出来
        if "```html" in response:
            start = response.find("```html") + len("```html")
            end = response.find("```", start)
            if end > start:
                return response[start:end].strip()

        if "```" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            if end > start:
                return response[start:end].strip()

        return response

    def _generate_default_html(self, report_data: Dict[str, Any]) -> str:
        """
        生成默认的HTML模板（当LLM不可用时）
        """
        # 提取关键信息
        plan = report_data.get("plan", {})
        diagnosis_plan = plan.get("diagnosis_plan", {})

        title = diagnosis_plan.get("clinical_question", "心脏MRI诊断报告")
        report_json_str = json.dumps(report_data, ensure_ascii=False, indent=2)

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>心脏MRI诊断报告</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: #333;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
            background-color: white;
            padding: 40px;
            box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
        }}
        .header {{
            border-bottom: 3px solid #0066cc;
            padding-bottom: 20px;
            margin-bottom: 30px;
        }}
        h1 {{
            color: #0066cc;
            font-size: 28px;
            margin-bottom: 10px;
        }}
        h2 {{
            color: #0066cc;
            font-size: 20px;
            margin-top: 30px;
            margin-bottom: 15px;
            border-left: 4px solid #0066cc;
            padding-left: 10px;
        }}
        .info-box {{
            background-color: #f9f9f9;
            border-left: 4px solid #0066cc;
            padding: 15px;
            margin-bottom: 20px;
        }}
        .info-row {{
            display: flex;
            justify-content: space-between;
            margin-bottom: 10px;
        }}
        .info-label {{
            font-weight: bold;
            color: #0066cc;
            min-width: 150px;
        }}
        .info-value {{
            color: #666;
            flex: 1;
        }}
        pre {{
            background-color: #f4f4f4;
            border: 1px solid #ddd;
            border-radius: 4px;
            padding: 15px;
            overflow-x: auto;
            font-size: 12px;
            line-height: 1.4;
            margin: 20px 0;
        }}
        .footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            text-align: center;
            color: #999;
            font-size: 12px;
        }}
        @media print {{
            body {{
                background-color: white;
            }}
            .container {{
                box-shadow: none;
                padding: 0;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>心脏MRI诊断报告</h1>
            <p>自动生成的诊断报告</p>
        </div>

        <div class="info-box">
            <div class="info-row">
                <span class="info-label">临床问题：</span>
                <span class="info-value">{title}</span>
            </div>
        </div>

        <h2>诊断数据</h2>
        <pre>{report_json_str}</pre>

        <div class="footer">
            <p>本报告为系统自动生成，仅供参考。</p>
            <p>生成于 <span id="timestamp"></span></p>
        </div>
    </div>

    <script>
        document.getElementById('timestamp').textContent = new Date().toLocaleString('zh-CN');
    </script>
</body>
</html>"""

        return html

    def _generate_error_html(self, error_message: str) -> str:
        """
        生成错误页面HTML
        """
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>报告生成错误</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            color: #333;
            background-color: #f5f5f5;
        }}
        .error-container {{
            max-width: 600px;
            margin: 50px auto;
            background-color: white;
            padding: 30px;
            border-radius: 4px;
            border-left: 4px solid #d32f2f;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }}
        h1 {{
            color: #d32f2f;
            margin-bottom: 20px;
        }}
        p {{
            color: #666;
            line-height: 1.6;
        }}
        .error-details {{
            background-color: #f9f9f9;
            border: 1px solid #ddd;
            padding: 15px;
            border-radius: 4px;
            font-family: monospace;
            margin-top: 20px;
            font-size: 12px;
            color: #d32f2f;
        }}
    </style>
</head>
<body>
    <div class="error-container">
        <h1>报告生成错误</h1>
        <p>抱歉，无法生成HTML报告。</p>
        <div class="error-details">
            {{error_message}}
        </div>
        <p style="margin-top: 20px; font-size: 12px; color: #999;">请稍后重试或联系技术支持。</p>
    </div>
</body>
</html>"""

        return html
