from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import nibabel as nib
import numpy as np


@dataclass
class PhaseVolume:
    """单个时相的分割结果和测量指标"""
    phase_name: str
    seg_path: Path
    lv_volume_ml: float
    lv_diameter_mm: Optional[float]  # 左心室内径
    raw_trigger: float


def determine_ed_es_by_volume(phases: List[PhaseVolume]) -> Dict[str, PhaseVolume]:
    """
    根据LV体积自动判定ED/ES
    ED: 舒张末期，LV体积最大
    ES: 收缩末期，LV体积最小
    """
    if not phases:
        raise ValueError("无可用阶段用于判定ED/ES")
    ed = max(phases, key=lambda p: p.lv_volume_ml)
    es = min(phases, key=lambda p: p.lv_volume_ml)
    ed.phase_name = "ED"
    es.phase_name = "ES"
    return {"ED": ed, "ES": es}


def determine_ed_es_by_diameter(phases: List[PhaseVolume]) -> Dict[str, PhaseVolume]:
    """
    根据LV内径判定ED/ES（备用方法）
    ED: 舒张末期，LV内径最大
    ES: 收缩末期，LV内径最小
    """
    if not phases:
        raise ValueError("无可用阶段用于判定ED/ES")
    
    # 过滤掉没有内径数据的帧
    valid_phases = [p for p in phases if p.lv_diameter_mm is not None and p.lv_diameter_mm > 0]
    if not valid_phases:
        # 回退到体积方法
        return determine_ed_es_by_volume(phases)
    
    ed = max(valid_phases, key=lambda p: p.lv_diameter_mm)
    es = min(valid_phases, key=lambda p: p.lv_diameter_mm)
    ed.phase_name = "ED"
    es.phase_name = "ES"
    return {"ED": ed, "ES": es}


def determine_ed_es(phases: List[PhaseVolume], method: str = "volume") -> Dict[str, PhaseVolume]:
    """
    根据指定方法判定ED/ES
    
    参数:
        phases: 所有时相的列表
        method: 判定方法，"volume"（体积）或"diameter"（内径）
    """
    if method == "diameter":
        return determine_ed_es_by_diameter(phases)
    else:
        return determine_ed_es_by_volume(phases)


def compute_lv_volume_ml(seg_path: Path, lv_label_id: int) -> float:
    """计算左心室体积（mL）"""
    img = nib.load(str(seg_path))
    data = np.asarray(img.dataobj)
    voxel_volume = np.prod(img.header.get_zooms())
    count = np.count_nonzero(data == lv_label_id)
    return float(count * voxel_volume / 1000.0)


def compute_lv_diameter_mm(seg_path: Path) -> Optional[float]:
    """
    计算左心室内径（mm）
    使用简化的PCA方法快速估算
    """
    try:
        img = nib.load(str(seg_path))
        data = np.asarray(img.dataobj)
        spacing = img.header.get_zooms()
        
        # 找到LV面积最大的切片
        lv_label = 3
        max_area = 0
        best_slice_idx = 0
        for z in range(data.shape[2]):
            area = np.count_nonzero(data[:, :, z] == lv_label)
            if area > max_area:
                max_area = area
                best_slice_idx = z
        
        if max_area == 0:
            return None
        
        # 在该切片上计算内径
        lv_slice = data[:, :, best_slice_idx] == lv_label
        coords = np.column_stack(np.nonzero(lv_slice))
        
        if coords.shape[0] < 2:
            return None
        
        # PCA主轴
        centroid = coords.mean(axis=0)
        centered = coords - centroid
        _, _, vh = np.linalg.svd(centered, full_matrices=False)
        direction = vh[0]
        
        # 投影到主轴
        projections = coords @ direction
        diameter_px = projections.max() - projections.min()
        
        # 转换为mm
        spacing_xy = (spacing[0] + spacing[1]) / 2.0  # 平均像素间距
        diameter_mm = diameter_px * spacing_xy
        
        return float(diameter_mm)
    except Exception:
        return None

