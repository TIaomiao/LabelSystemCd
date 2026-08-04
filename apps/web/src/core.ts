export const POINT_KEYS = ['j1', 'j2', 'm1', 'm2'] as const;

export type PointKey = (typeof POINT_KEYS)[number];

export interface Point2D {
  x: number;
  y: number;
}

export interface CurvatureLandmarks {
  slice_index: number;
  phase_index: number;
  j1: Point2D | null;
  j2: Point2D | null;
  m1: Point2D | null;
  m2: Point2D | null;
  method: 'manual_four_point';
}

export interface SeriesFrame {
  slice_index: number;
  phase_index: number;
  pixel_spacing?: number[];
}

export interface SeriesSummary {
  id: number;
  description: string;
  role: string;
  rows: number;
  cols: number;
  slice_count: number;
  phase_count: number;
  pixel_spacing?: number[];
  frames?: SeriesFrame[];
}

export interface ContourSet {
  series_id: number;
  module: 'function' | 'lge';
  curvature_landmarks?: CurvatureLandmarks | null;
  [key: string]: unknown;
}

export interface ArcGeometry {
  status?: string;
  radius_mm?: number | null;
  curvature_magnitude_mm_inv?: number | null;
  signed_curvature_mm_inv?: number | null;
  circle_center_mm?: number[] | null;
}

export interface CurvatureResult {
  status?: string;
  qc_status?: string;
  qc_reasons?: string[];
  curvature_ratio_magnitude?: number | null;
  curvature_ratio_rc?: number | null;
  signed_curvature_ratio?: number | null;
  septal_shape?: string | null;
  pixel_spacing_mm?: { x?: number; y?: number };
  pixel_spacing_provenance?: string;
  clinical_grade?: boolean;
  confirmation_status?: string;
  ivs?: ArcGeometry;
  free_wall?: ArcGeometry;
}

export interface StudyDetail {
  id: number;
  series: SeriesSummary[];
}

export interface PreviewResponse {
  persisted: boolean;
  curvature: CurvatureResult | null;
}

export const POINT_LABELS: Record<PointKey, string> = {
  j1: 'J1 上前交界点',
  j2: 'J2 下后交界点',
  m1: 'M1 室间隔中央点',
  m2: 'M2 游离壁中央点'
};

export const parseStudyId = (pathname: string): number | null => {
  const match = pathname.match(/\/study\/(\d+)(?:\/|$)/);
  if (!match) return null;
  const value = Number(match[1]);
  return Number.isSafeInteger(value) && value > 0 ? value : null;
};

export const emptyLandmarks = (sliceIndex: number, phaseIndex: number): CurvatureLandmarks => ({
  slice_index: sliceIndex,
  phase_index: phaseIndex,
  j1: null,
  j2: null,
  m1: null,
  m2: null,
  method: 'manual_four_point'
});

export const cloneLandmarks = (value: CurvatureLandmarks | null | undefined): CurvatureLandmarks | null => {
  if (!value) return null;
  return {
    slice_index: Number(value.slice_index),
    phase_index: Number(value.phase_index),
    j1: value.j1 ? { x: Number(value.j1.x), y: Number(value.j1.y) } : null,
    j2: value.j2 ? { x: Number(value.j2.x), y: Number(value.j2.y) } : null,
    m1: value.m1 ? { x: Number(value.m1.x), y: Number(value.m1.y) } : null,
    m2: value.m2 ? { x: Number(value.m2.x), y: Number(value.m2.y) } : null,
    method: 'manual_four_point'
  };
};

const normalizedLandmarks = (value: CurvatureLandmarks | null | undefined): unknown => {
  const cloned = cloneLandmarks(value);
  if (!cloned) return null;
  return [
    cloned.slice_index,
    cloned.phase_index,
    ...POINT_KEYS.flatMap((key) => {
      const point = cloned[key];
      return point ? [point.x, point.y] : [null, null];
    })
  ];
};

export const landmarksEqual = (
  left: CurvatureLandmarks | null | undefined,
  right: CurvatureLandmarks | null | undefined
): boolean => JSON.stringify(normalizedLandmarks(left)) === JSON.stringify(normalizedLandmarks(right));

export const hasAnyPoint = (value: CurvatureLandmarks | null | undefined): boolean => (
  Boolean(value && POINT_KEYS.some((key) => value[key] != null))
);

export const hasAllPoints = (value: CurvatureLandmarks | null | undefined): value is CurvatureLandmarks => (
  Boolean(value && POINT_KEYS.every((key) => value[key] != null))
);

export const isLandmarksDraftDirty = (
  draft: CurvatureLandmarks | null | undefined,
  saved: CurvatureLandmarks | null | undefined
): boolean => {
  if (!saved && !hasAnyPoint(draft)) return false;
  return !landmarksEqual(draft, saved);
};

export const canSaveCurvatureDraft = (
  draft: CurvatureLandmarks | null | undefined,
  resultStatus: string | null | undefined,
  options: { previewLoading: boolean; saving: boolean; frameMatches: boolean }
): boolean => Boolean(
  hasAllPoints(draft)
  && resultStatus === 'valid'
  && !options.previewLoading
  && !options.saving
  && options.frameMatches
);

export const nextPointKey = (value: CurvatureLandmarks | null | undefined): PointKey => (
  POINT_KEYS.find((key) => !value?.[key]) || 'j1'
);

export const isLandmarkFrame = (
  value: CurvatureLandmarks | null | undefined,
  sliceIndex: number,
  phaseIndex: number
): boolean => Boolean(
  value
  && value.slice_index === sliceIndex
  && value.phase_index === phaseIndex
);

export const clampPoint = (point: Point2D, cols: number, rows: number): Point2D => ({
  x: Math.min(Math.max(point.x, 0), Math.max(0, cols - 1)),
  y: Math.min(Math.max(point.y, 0), Math.max(0, rows - 1))
});

export const formatMetric = (value: number | null | undefined, digits = 3): string => (
  typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—'
);

export const circleToPixelEllipse = (
  centerMm: number[] | null | undefined,
  radiusMm: number | null | undefined,
  spacing: { x: number; y: number }
): { cx: number; cy: number; rx: number; ry: number } | null => {
  if (!Array.isArray(centerMm) || centerMm.length < 2) return null;
  if (!(typeof radiusMm === 'number' && Number.isFinite(radiusMm) && radiusMm > 0)) return null;
  if (!(Number.isFinite(spacing.x) && spacing.x > 0 && Number.isFinite(spacing.y) && spacing.y > 0)) return null;
  return {
    cx: centerMm[0] / spacing.x,
    cy: centerMm[1] / spacing.y,
    rx: radiusMm / spacing.x,
    ry: radiusMm / spacing.y
  };
};

export const shapeLabel = (shape: string | null | undefined): string => {
  if (shape === 'inverted') return '反弓（负曲率）';
  if (shape === 'flat') return '完全变平';
  if (shape === 'non_inverted') return '未反弓';
  return '待计算';
};

export const qcReasonLabel = (reason: string): string => {
  if (reason.startsWith('missing_landmarks:')) return '四点尚未放置完整';
  const labels: Record<string, string> = {
    curvature_requires_cine_sax: '仅支持 SAX cine 序列',
    invalid_pixel_spacing: 'PixelSpacing 无效，不能输出毫米结果',
    pixel_spacing_provenance_unverified: 'PixelSpacing 来源未核验，当前结果仅供研发预览',
    selected_frame_not_found: '所选层面或时相不存在',
    'ivs:flat_arc': '室间隔三点近似共线，按曲率 0 处理',
    'ivs:midpoint_outside_junction_chord': 'M1 未位于 J1-J2 对应弧段中央区域',
    'free_wall:midpoint_outside_junction_chord': 'M2 未位于 J1-J2 对应弧段中央区域',
    'free_wall:flat_arc': '游离壁三点共线，无法计算 RC',
    septal_and_free_wall_midpoints_coincident: 'M1 与 M2 不能重合',
    signed_shape_indeterminate: '无法判断室间隔是否反弓'
  };
  if (labels[reason]) return labels[reason];
  if (reason.startsWith('landmark_out_of_bounds:')) return `${reason.split(':')[1].toUpperCase()} 超出图像范围`;
  if (reason.startsWith('invalid_landmark:')) return `${reason.split(':')[1].toUpperCase()} 坐标无效`;
  return reason;
};

export const escapeHtml = (value: unknown): string => String(value ?? '')
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#039;');
