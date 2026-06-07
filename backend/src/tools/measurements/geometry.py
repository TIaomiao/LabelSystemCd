from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

import numpy as np

from .volume import load_nifti

__all__ = [
    "_geometric_chamber_measurements",
    "_measure_diameter_from_septum",
    "_measure_wall_thickness_at_point",
    "_septum_thickness",
    "_posterior_wall_thickness",
    "_render_measurement_figure",
    "_get_representative_sax_slices",
    "_principal_axis_diameter",
]


def _geometric_chamber_measurements(
    lv_slice: np.ndarray,
    rv_slice: np.ndarray,
    myo_slice: np.ndarray,
    spacing_xy: Tuple[float, float],
) -> Tuple[
    float,
    Optional[Tuple[np.ndarray, np.ndarray]],
    float,
    Optional[Tuple[np.ndarray, np.ndarray]],
    float,
    Optional[Tuple[np.ndarray, np.ndarray]],
    float,
    Optional[Tuple[np.ndarray, np.ndarray]],
]:
    lv_centroid = _centroid(lv_slice)
    rv_centroid = _centroid(rv_slice)
    if (
        lv_centroid is None
        or rv_centroid is None
        or not np.any(myo_slice)
    ):
        return 0.0, None, 0.0, None, 0.0, None, 0.0, None

    direction_lr = _normalize(rv_centroid - lv_centroid)
    if direction_lr is None:
        return 0.0, None, 0.0, None, 0.0, None, 0.0, None

    # 室间隔：从LV质心向RV方向，穿过LV腔体后与心肌的交点
    septum_point = _find_septum_on_centroid_line(
        lv_slice=lv_slice,
        myo_slice=myo_slice,
        origin=lv_centroid,
        direction=direction_lr,
    )
    # 左室后壁：从LV质心向反方向（远离RV），穿过LV腔体后与心肌的交点
    posterior_point = _find_septum_on_centroid_line(
        lv_slice=lv_slice,
        myo_slice=myo_slice,
        origin=lv_centroid,
        direction=-direction_lr,
    )
    if septum_point is None or posterior_point is None:
        return 0.0, None, 0.0, None, 0.0, None, 0.0, None

    lv_diameter, lv_line = _measure_diameter_from_septum(
        chamber_slice=lv_slice,
        spacing_xy=spacing_xy,
        septum_px=septum_point,
        centroid_px=lv_centroid,
    )
    rv_diameter, rv_line = _measure_diameter_from_septum(
        chamber_slice=rv_slice,
        spacing_xy=spacing_xy,
        septum_px=septum_point,
        centroid_px=rv_centroid,
    )

    # 室间隔厚度：沿LV质心→室间隔的径向方向测量心肌厚度
    ivs_thickness, ivs_line = _measure_radial_wall_thickness(
        myo_slice=myo_slice,
        spacing_xy=spacing_xy,
        wall_point=septum_point,
        center_point=lv_centroid,
    )
    # 左室后壁厚度：沿LV质心→后壁的径向方向测量心肌厚度
    lvpw_thickness, lvpw_line = _measure_radial_wall_thickness(
        myo_slice=myo_slice,
        spacing_xy=spacing_xy,
        wall_point=posterior_point,
        center_point=lv_centroid,
    )

    return (
        lv_diameter,
        lv_line,
        rv_diameter,
        rv_line,
        ivs_thickness,
        ivs_line,
        lvpw_thickness,
        lvpw_line,
    )


def _measure_diameter_from_septum(
    chamber_slice: np.ndarray,
    spacing_xy: Tuple[float, float],
    septum_px: np.ndarray,
    centroid_px: np.ndarray,
) -> Tuple[float, Optional[Tuple[np.ndarray, np.ndarray]]]:
    direction = _normalize(centroid_px - septum_px)
    if direction is None:
        return 0.0, None
    length, boundary = _ray_to_boundary(
        mask=chamber_slice,
        spacing_xy=spacing_xy,
        start_px=septum_px,
        direction=direction,
    )
    if length == 0.0 or boundary is None:
        return 0.0, None
    return length, (septum_px.copy(), boundary)


def _measure_radial_wall_thickness(
    myo_slice: np.ndarray,
    spacing_xy: Tuple[float, float],
    wall_point: np.ndarray,
    center_point: np.ndarray,
) -> Tuple[float, Optional[Tuple[np.ndarray, np.ndarray]]]:
    """
    测量心肌在指定点的径向厚度（从内壁到外壁）。
    参考 measure_cardiac_chambers.py 的 wall_thickness_line 函数。
    
    参数：
        myo_slice: 心肌掩膜
        spacing_xy: 像素间距
        wall_point: 心肌上的测量点（室间隔或后壁）
        center_point: 心腔质心（用于确定径向方向）
    
    返回：
        厚度(mm), (内壁点, 外壁点)
    """
    # 径向方向（像素空间）：从质心指向测量点
    radial_direction_px = wall_point - center_point
    radial_direction_px = _normalize(radial_direction_px)
    if radial_direction_px is None:
        return 0.0, None
    
    # 转换为mm空间的方向向量（用于正确计算距离）
    radial_direction_mm = np.array(
        [
            radial_direction_px[0] * spacing_xy[0],
            radial_direction_px[1] * spacing_xy[1],
        ],
        dtype=np.float64,
    )
    radial_direction_mm = _normalize(radial_direction_mm)
    if radial_direction_mm is None:
        return 0.0, None
    
    # 确保测量点在心肌上
    start = _snap_to_mask(wall_point, myo_slice)
    if start is None:
        return 0.0, None
    
    # 从测量点出发，沿径向方向向外找到心肌外壁
    outer_wall = _march_until_exit(myo_slice, start, radial_direction_px)
    
    # 从测量点出发，沿径向方向向内找到心肌内壁
    inner_wall = _march_until_exit(myo_slice, start, -radial_direction_px)
    
    if inner_wall is None or outer_wall is None:
        return 0.0, None
    
    # 计算内外壁之间的距离（在mm空间）
    inner_mm = np.array([inner_wall[0] * spacing_xy[0], inner_wall[1] * spacing_xy[1]])
    outer_mm = np.array([outer_wall[0] * spacing_xy[0], outer_wall[1] * spacing_xy[1]])
    thickness = float(np.linalg.norm(outer_mm - inner_mm))
    
    return thickness, (inner_wall, outer_wall)


def _measure_wall_thickness_at_point(
    myo_slice: np.ndarray,
    spacing_xy: Tuple[float, float],
    anchor_px: np.ndarray,
    wall_direction: np.ndarray,
) -> Tuple[float, Optional[Tuple[np.ndarray, np.ndarray]]]:
    perpendicular = np.array([-wall_direction[1], wall_direction[0]], dtype=np.float64)
    return _measure_wall_thickness(
        myo_slice=myo_slice,
        spacing_xy=spacing_xy,
        start_px=anchor_px,
        direction_px=perpendicular,
    )


def _septum_thickness(
    lv_slice: np.ndarray,
    rv_slice: np.ndarray,
    myo_slice: np.ndarray,
    spacing_xy: Tuple[float, float],
) -> Tuple[float, Optional[Tuple[np.ndarray, np.ndarray]]]:
    lv_centroid = _centroid(lv_slice)
    rv_centroid = _centroid(rv_slice)
    if lv_centroid is None or rv_centroid is None:
        return 0.0, None
    direction = _normalize(rv_centroid - lv_centroid)
    if direction is None:
        return 0.0, None
    start = _find_myocardium_contact(lv_centroid, direction, myo_slice)
    anchor = start if start is not None else lv_centroid
    start = _snap_to_mask(anchor, myo_slice)
    return _measure_wall_thickness(myo_slice, spacing_xy, start, direction)


def _posterior_wall_thickness(
    lv_slice: np.ndarray,
    rv_slice: np.ndarray,
    myo_slice: np.ndarray,
    spacing_xy: Tuple[float, float],
) -> Tuple[float, Optional[Tuple[np.ndarray, np.ndarray]]]:
    lv_centroid = _centroid(lv_slice)
    rv_centroid = _centroid(rv_slice)
    if lv_centroid is None or rv_centroid is None:
        return 0.0, None
    direction = _normalize(lv_centroid - rv_centroid)
    if direction is None:
        return 0.0, None
    start = _find_myocardium_contact(lv_centroid, direction, myo_slice)
    anchor = start if start is not None else lv_centroid
    start = _snap_to_mask(anchor, myo_slice)
    return _measure_wall_thickness(myo_slice, spacing_xy, start, direction)


def _measure_wall_thickness(
    myo_slice: np.ndarray,
    spacing_xy: Tuple[float, float],
    start_px: Optional[np.ndarray],
    direction_px: Optional[np.ndarray],
) -> Tuple[float, Optional[Tuple[np.ndarray, np.ndarray]]]:
    if start_px is None or direction_px is None:
        return 0.0, None
    direction = _normalize(direction_px)
    if direction is None:
        return 0.0, None
    start = _snap_to_mask(start_px, myo_slice)
    if start is None:
        return 0.0, None
    inner = _march_until_exit(myo_slice, start, -direction)
    outer = _march_until_exit(myo_slice, start, direction)
    if inner is None or outer is None:
        return 0.0, None
    length = _distance_mm(inner, outer, spacing_xy)
    return float(length), (inner, outer)


def _ray_to_boundary(
    mask: np.ndarray,
    spacing_xy: Tuple[float, float],
    start_px: np.ndarray,
    direction: np.ndarray,
    step: float = 0.25,
) -> Tuple[float, Optional[np.ndarray]]:
    direction = _normalize(direction)
    if direction is None:
        return 0.0, None
    pos = start_px.astype(np.float64)
    entry = None
    max_iters = int((mask.shape[0] + mask.shape[1]) * 8)
    for _ in range(max_iters):
        pos = pos + direction * step
        if _point_in_mask(pos, mask):
            entry = pos.copy()
            break
    if entry is None:
        return 0.0, None
    boundary = _march_until_exit(mask, entry, direction)
    if boundary is None:
        return 0.0, None
    length = _distance_mm(start_px, boundary, spacing_xy)
    return float(length), boundary


def _find_septum_on_centroid_line(
    lv_slice: np.ndarray,
    myo_slice: np.ndarray,
    origin: np.ndarray,
    direction: np.ndarray,
) -> Optional[np.ndarray]:
    """
    从LV质心出发，沿指定方向找到与心肌的交界点（室间隔或后壁）。
    流程：
    1. 从质心出发
    2. 先穿过LV腔体（确保离开LV）
    3. 找到首个心肌像素
    """
    direction = _normalize(direction)
    if direction is None:
        return None
    
    pos = origin.astype(np.float64)
    step = 0.25
    max_iters = int((lv_slice.shape[0] + lv_slice.shape[1]) * 8)
    
    # 阶段1：从质心出发，确保离开LV腔体
    left_lv = False
    for _ in range(max_iters):
        pos = pos + direction * step
        r = int(round(pos[0]))
        c = int(round(pos[1]))
        if r < 0 or c < 0 or r >= lv_slice.shape[0] or c >= lv_slice.shape[1]:
            return None
        
        # 如果在LV内，标记为已在LV中
        if lv_slice[r, c]:
            continue
        else:
            # 已经离开LV
            left_lv = True
            break
    
    if not left_lv:
        return None
    
    # 阶段2：离开LV后，寻找首个心肌像素
    for _ in range(max_iters):
        r = int(round(pos[0]))
        c = int(round(pos[1]))
        if r < 0 or c < 0 or r >= myo_slice.shape[0] or c >= myo_slice.shape[1]:
            return None
        
        if myo_slice[r, c]:
            # 找到心肌，这就是室间隔/后壁位置
            return pos.copy()
        
        pos = pos + direction * step
    
    return None


def _intersect_centroid_line_with_myo(
    origin: np.ndarray,
    direction: np.ndarray,
    myo_slice: np.ndarray,
) -> Optional[np.ndarray]:
    """
    从质心出发沿指定方向寻找与心肌的交界点。
    关键：先确保离开起点区域，然后找到首个心肌像素。
    """
    direction = _normalize(direction)
    if direction is None:
        return None
    pos = origin.astype(np.float64)
    step = 0.25
    max_iters = int((myo_slice.shape[0] + myo_slice.shape[1]) * 4)
    
    # 先前进一小段距离，确保离开质心附近可能存在的心肌
    for _ in range(20):
        pos = pos + direction * step
        r = int(round(pos[0]))
        c = int(round(pos[1]))
        if r < 0 or c < 0 or r >= myo_slice.shape[0] or c >= myo_slice.shape[1]:
            return None
    
    # 然后寻找首个心肌像素
    for _ in range(max_iters):
        pos = pos + direction * step
        r = int(round(pos[0]))
        c = int(round(pos[1]))
        if r < 0 or c < 0 or r >= myo_slice.shape[0] or c >= myo_slice.shape[1]:
            return None
        if myo_slice[r, c]:
            return pos.copy()
    return None


def _principal_axis_diameter(mask_2d: np.ndarray, spacing_xy: Tuple[float, float]):
    coords = np.column_stack(np.nonzero(mask_2d))
    if coords.shape[0] < 2:
        return 0.0, None
    centroid = coords.mean(axis=0)
    centered = coords - centroid
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    direction = vh[0]
    projections = coords @ direction
    start = coords[np.argmin(projections)]
    end = coords[np.argmax(projections)]
    length_mm = _distance_mm(start, end, spacing_xy)
    return float(length_mm), (start, end)


def _get_representative_sax_slices(
    seg_path: Path,
) -> Tuple[np.ndarray, Tuple[float, float, float], Tuple[float, float], int, np.ndarray, np.ndarray, np.ndarray]:
    volume, spacing = load_nifti(seg_path)
    from ..measurement_tools import SAX_LABELS  # lazy import to avoid cycle

    slice_idx = _select_representative_slice(volume == SAX_LABELS["LV"])
    lv_slice = volume[:, :, slice_idx] == SAX_LABELS["LV"]
    rv_slice = volume[:, :, slice_idx] == SAX_LABELS["RV"]
    myo_slice = volume[:, :, slice_idx] == SAX_LABELS["MYO"]
    spacing_xy = (spacing[0], spacing[1])
    return volume, spacing, spacing_xy, slice_idx, lv_slice, rv_slice, myo_slice


def _render_measurement_figure(
    output_path: Path,
    lv_slice: np.ndarray,
    rv_slice: np.ndarray,
    myo_slice: np.ndarray,
    lines: Sequence[Dict[str, Optional[np.ndarray]]],
) -> None:
    try:
        import matplotlib.pyplot as plt
        from matplotlib import colors as mpl_colors
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("缺少matplotlib，无法生成测量可视化") from exc

    base = np.zeros(lv_slice.shape, dtype=np.uint8)
    base[rv_slice] = 1
    base[lv_slice] = 2
    base[myo_slice] = 3

    cmap = mpl_colors.ListedColormap(
        ["#000000", "#5555FF", "#FFFFFF", "#AAAAAA"]
    )

    fig, ax = plt.subplots(figsize=(4, 4), dpi=150)
    ax.imshow(base, cmap=cmap, interpolation="nearest", origin="upper")

    for line in lines:
        start = line.get("start")
        end = line.get("end")
        if start is None or end is None:
            continue
        xs = [start[1], end[1]]
        ys = [start[0], end[0]]
        ax.plot(xs, ys, color=line["color"], linewidth=2)
        mid_x = (xs[0] + xs[1]) / 2.0
        mid_y = (ys[0] + ys[1]) / 2.0
        ax.text(
            mid_x,
            mid_y,
            f"{line['label']} {line['length']:.1f} mm",
            color=line["color"],
            fontsize=7,
            ha="center",
            va="center",
            bbox=dict(facecolor="black", alpha=0.4, pad=1, edgecolor="none"),
        )

    ax.set_axis_off()
    fig.tight_layout(pad=0)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


def _line_dict(label: str, color: str, line: Optional[Tuple[np.ndarray, np.ndarray]], length: float):
    if line is None:
        return {"label": label, "color": color, "start": None, "end": None, "length": length}
    start, end = line
    return {
        "label": label,
        "color": color,
        "start": start,
        "end": end,
        "length": length,
    }


def _select_representative_slice(mask_3d: np.ndarray) -> int:
    areas = mask_3d.sum(axis=(0, 1))
    if not np.any(areas):
        return 0
    return int(np.argmax(areas))


def _centroid(mask: np.ndarray) -> Optional[np.ndarray]:
    coords = np.column_stack(np.nonzero(mask))
    if coords.size == 0:
        return None
    return coords.mean(axis=0)


def _normalize(vec: np.ndarray) -> Optional[np.ndarray]:
    norm = float(np.linalg.norm(vec))
    if norm < 1e-6:
        return None
    return vec / norm


def _snap_to_mask(candidate: Optional[np.ndarray], mask: np.ndarray) -> Optional[np.ndarray]:
    coords = np.column_stack(np.nonzero(mask))
    if coords.size == 0:
        return None
    if candidate is None:
        return coords.mean(axis=0)
    dists = np.linalg.norm(coords - candidate, axis=1)
    return coords[int(np.argmin(dists))].astype(np.float64)


def _point_in_mask(point: np.ndarray, mask: np.ndarray) -> bool:
    r = int(round(point[0]))
    c = int(round(point[1]))
    if r < 0 or c < 0 or r >= mask.shape[0] or c >= mask.shape[1]:
        return False
    return bool(mask[r, c])


def _find_myocardium_contact(
    origin: np.ndarray,
    direction: np.ndarray,
    myo_slice: np.ndarray,
) -> Optional[np.ndarray]:
    step = 0.5
    direction = _normalize(direction)
    if direction is None:
        return None
    pos = origin.astype(np.float64)
    max_iters = int(np.linalg.norm(myo_slice.shape) * 2)
    for _ in range(max_iters):
        pos += direction * step
        r = int(round(pos[0]))
        c = int(round(pos[1]))
        if r < 0 or c < 0 or r >= myo_slice.shape[0] or c >= myo_slice.shape[1]:
            return None
        if myo_slice[r, c]:
            return pos.copy()
    return None


def _march_until_exit(mask: np.ndarray, start: np.ndarray, direction: np.ndarray) -> Optional[np.ndarray]:
    direction = _normalize(direction)
    if direction is None:
        return None
    pos = start.astype(np.float64)
    last_inside = None
    step = 0.25
    max_iters = int((mask.shape[0] + mask.shape[1]) * 8)
    for _ in range(max_iters):
        pos = pos + direction * step
        r, c = int(round(pos[0])), int(round(pos[1]))
        if r < 0 or c < 0 or r >= mask.shape[0] or c >= mask.shape[1]:
            return last_inside
        if mask[r, c]:
            last_inside = pos.copy()
        elif last_inside is not None:
            return last_inside
    return last_inside


def _distance_mm(pt_a: np.ndarray, pt_b: np.ndarray, spacing_xy: Tuple[float, float]) -> float:
    delta = (pt_b - pt_a) * np.array(spacing_xy)
    return float(np.linalg.norm(delta))

