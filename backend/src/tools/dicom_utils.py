from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np
import pydicom
import SimpleITK as sitk
from PIL import Image

from config.settings import MAX_TIMEPOINTS_PER_SEQUENCE, PNG_PREVIEW_SIZE, TEMP_DIR


@dataclass
class TimepointSeries:
    trigger_time: float
    file_paths: List[Path] = field(default_factory=list)
    nifti_path: Optional[Path] = None
    phase_label: Optional[str] = None  # 例如 "ED" / "ES"


class DicomSeriesProcessor:
    """
    针对单个序列（例如SAX）提供：
    - 预览PNG
    - 转换整个序列为4D NIfTI（时间+空间）
    - 提取时间帧信息
    """

    def __init__(self, series_dir: Path):
        self.series_dir = Path(series_dir)
        if not self.series_dir.is_dir():
            raise FileNotFoundError(f"序列目录不存在: {series_dir}")
        self._dicom_files = sorted(self.series_dir.glob("*.dcm"))
        if not self._dicom_files:
            raise ValueError(f"{series_dir} 未找到DICOM文件")

        self._first_ds = pydicom.dcmread(str(self._dicom_files[0]), stop_before_pixels=True)
        self._trigger_times: Optional[List[float]] = None

    def export_preview_png(self, output_path: Path) -> Path:
        ds = pydicom.dcmread(str(self._dicom_files[0]))
        array = ds.pixel_array.astype(np.float32)
        slope = float(getattr(ds, "RescaleSlope", 1.0))
        intercept = float(getattr(ds, "RescaleIntercept", 0.0))
        array = array * slope + intercept

        min_val = np.percentile(array, 1)
        max_val = np.percentile(array, 99)
        array = np.clip((array - min_val) / (max_val - min_val + 1e-7), 0.0, 1.0)
        image = Image.fromarray((array * 255).astype(np.uint8))
        image = image.resize(PNG_PREVIEW_SIZE, Image.BILINEAR)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path)
        return output_path

    def convert_all_timepoints_to_nifti(self, output_dir: Path) -> List[TimepointSeries]:
        """
        将所有时间点转换为独立的3D NIfTI文件
        
        参数:
            output_dir: 输出目录
        
        返回:
            TimepointSeries列表，每个包含对应的NIfTI路径
        """
        timepoints = self.split_by_trigger_time()
        output_dir.mkdir(parents=True, exist_ok=True)
        
        for tp in timepoints:
            nifti_filename = f"tt{int(tp.trigger_time):04d}.nii.gz"
            nifti_path = output_dir / nifti_filename
            
            if not nifti_path.exists():
                self.convert_timepoint_to_nifti(tp, nifti_path)
            
            tp.nifti_path = nifti_path
        
        return timepoints
    
    def get_trigger_times(self) -> List[float]:
        """获取所有触发时间"""
        if self._trigger_times is None:
            groups: Dict[float, int] = {}
            for path in self._dicom_files:
                ds = pydicom.dcmread(str(path), stop_before_pixels=True)
                trigger = float(getattr(ds, "TriggerTime", 0.0))
                groups[trigger] = groups.get(trigger, 0) + 1
            self._trigger_times = sorted(groups.keys())
        return self._trigger_times
    
    def split_by_trigger_time(self) -> List[TimepointSeries]:
        """
        按触发时间分组（保留用于向后兼容）
        """
        groups: Dict[float, List[Path]] = {}
        for path in self._dicom_files:
            ds = pydicom.dcmread(str(path), stop_before_pixels=True)
            trigger = float(getattr(ds, "TriggerTime", 0.0))
            groups.setdefault(trigger, []).append(path)

        items = [
            TimepointSeries(trigger_time=trigger, file_paths=sorted(files, key=self._extract_instance))
            for trigger, files in sorted(groups.items(), key=lambda kv: kv[0])
        ]
        if len(items) > MAX_TIMEPOINTS_PER_SEQUENCE:
            items = items[:MAX_TIMEPOINTS_PER_SEQUENCE]
        return items

    def convert_timepoint_to_nifti(self, timepoint: TimepointSeries, output_path: Path) -> Path:
        """转换单个时间点为3D NIfTI"""
        reader = sitk.ImageSeriesReader()
        reader.SetFileNames([str(p) for p in timepoint.file_paths])
        image = reader.Execute()
        sitk.WriteImage(image, str(output_path))
        timepoint.nifti_path = output_path
        return output_path

    @staticmethod
    def _extract_instance(path: Path) -> int:
        try:
            ds = pydicom.dcmread(str(path), stop_before_pixels=True)
            return int(getattr(ds, "InstanceNumber", 0))
        except Exception:
            return 0

