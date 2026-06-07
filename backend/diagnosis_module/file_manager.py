
import json
import logging
import shutil
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
from flask import current_app

logger = logging.getLogger(__name__)

class FileManager:
    """
    管理输出文件、报告和日志的读取
    """

    def __init__(self, output_base_dir: Path):
        self.output_base = output_base_dir

    def _get_patient_dir(self, patient_id: str) -> Path:
        return self.output_base / patient_id

    def list_results(self, patient_id: str) -> List[str]:
        """列出患者的所有结果文件"""
        patient_dir = self._get_patient_dir(patient_id)
        if not patient_dir.exists():
            return []
        
        files = []
        for item in patient_dir.rglob("*"):
            if item.is_file() and not item.name.startswith("."):
                rel_path = item.relative_to(patient_dir)
                files.append(str(rel_path))
        return sorted(files)

    def get_report_json(self, patient_id: str) -> Dict:
        """读取 diagnosis_report.json"""
        report_path = self._get_patient_dir(patient_id) / "diagnosis_report.json"
        if not report_path.exists():
            raise FileNotFoundError(f"Report not found for {patient_id}")
        
        with open(report_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_metrics_json(self, patient_id: str) -> Dict:
        """读取 metrics.json"""
        metrics_path = self._get_patient_dir(patient_id) / "metrics.json"
        if not metrics_path.exists():
            # 如果没有专门的 metrics.json，尝试从 report 中提取或返回空
            raise FileNotFoundError(f"Metrics not found for {patient_id}")
        
        with open(metrics_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_workflow_log(self, patient_id: str) -> str:
        """读取 workflow.log"""
        log_path = self._get_patient_dir(patient_id) / "workflow.log"
        if not log_path.exists():
            return ""
        
        with open(log_path, "r", encoding="utf-8") as f:
            return f.read()

    def save_file(self, patient_id: str, filename: str, content: bytes):
        """保存文件到结果目录"""
        target_dir = self._get_patient_dir(patient_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        
        target_path = target_dir / filename
        with open(target_path, "wb") as f:
            f.write(content)
        return target_path
