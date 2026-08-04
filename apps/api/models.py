from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


SeriesRole = Literal[
    "cine_sax",
    "cine_lax_2ch",
    "cine_lax_3ch",
    "cine_lax_4ch",
    "lge_sax",
    "lge_lax",
    "unknown",
]
ModuleName = Literal["function", "lge"]
ReportStatus = Literal["草稿", "定稿"]


class Point2D(BaseModel):
    x: float
    y: float
    patient: Optional[List[float]] = None


class CurvaturePoint2D(Point2D):
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)


class CurvatureLandmarks(BaseModel):
    slice_index: Optional[int] = Field(default=None, ge=0)
    phase_index: Optional[int] = Field(default=None, ge=0)
    j1: Optional[CurvaturePoint2D] = None
    j2: Optional[CurvaturePoint2D] = None
    m1: Optional[CurvaturePoint2D] = None
    m2: Optional[CurvaturePoint2D] = None
    method: Literal["manual_four_point"] = "manual_four_point"


class CurvatureUpdateRequest(BaseModel):
    landmarks: Optional[CurvatureLandmarks]


class PolygonContour(BaseModel):
    points: List[Point2D] = Field(default_factory=list)
    closed: bool = True


class FrameContour(BaseModel):
    include: bool = True
    la: Optional[PolygonContour] = None
    ra: Optional[PolygonContour] = None
    endo: Optional[PolygonContour] = None
    epi: Optional[PolygonContour] = None
    ventricular_epi: Optional[PolygonContour] = None
    rv: Optional[PolygonContour] = None
    fat: Optional[PolygonContour] = None
    fat_outer: Optional[PolygonContour] = None
    remote: Optional[PolygonContour] = None
    enhanced: Optional[PolygonContour] = None
    exclude: Optional[PolygonContour] = None
    exclude_regions: Optional[List[PolygonContour]] = None
    mvo: Optional[PolygonContour] = None


class PhaseLabels(BaseModel):
    ed: Optional[int] = None
    es: Optional[int] = None
    lv_ed: Optional[int] = None
    lv_es: Optional[int] = None
    rv_ed: Optional[int] = None
    rv_es: Optional[int] = None
    la_max: Optional[int] = None
    la_pre_a: Optional[int] = None
    la_min: Optional[int] = None
    ra_max: Optional[int] = None
    ra_pre_a: Optional[int] = None
    ra_min: Optional[int] = None


class ContourSet(BaseModel):
    series_id: int
    module: ModuleName
    coordinate_space: Literal["pixel"] = "pixel"
    source: str = "manual"
    settings: dict = Field(default_factory=dict)
    annotation_meta: dict = Field(default_factory=dict)
    frame_meta: Dict[str, dict] = Field(default_factory=dict)
    phase_labels: PhaseLabels = Field(default_factory=PhaseLabels)
    curvature_landmarks: Optional[CurvatureLandmarks] = None
    frames: Dict[str, FrameContour] = Field(default_factory=dict)


class FrameRef(BaseModel):
    id: int
    slice_index: int
    phase_index: int
    instance_number: Optional[int] = None
    trigger_time: Optional[float] = None
    file_path: str
    image_position: List[float] = Field(default_factory=list)
    image_orientation: List[float] = Field(default_factory=list)
    pixel_spacing: List[float] = Field(default_factory=list)


class SeriesSummary(BaseModel):
    id: int
    study_id: int
    description: str
    role: SeriesRole
    rows: int
    cols: int
    file_count: int
    slice_count: int
    phase_count: int
    pixel_spacing: List[float]
    slice_thickness: float
    orientation: Optional[str] = None
    folder_path: str
    has_predictions: bool = False
    default_slice: int = 0
    default_phase: int = 0
    frames: List[FrameRef] = Field(default_factory=list)
    latest_measurement: Optional[dict] = None


class ReportDraft(BaseModel):
    study_id: int
    status: ReportStatus = "草稿"
    findings: str = ""
    summary: str = ""
    payload: dict = Field(default_factory=dict)


class StudyDetail(BaseModel):
    id: int
    study_uid: str
    patient_name: str
    patient_id: str
    patient_sex: str = ""
    patient_age: str = ""
    study_date: str
    accession_number: str
    source_path: str
    default_sample_path: str
    series: list[SeriesSummary]
    report: ReportDraft


class ImportStudyRequest(BaseModel):
    path: str


class RoleUpdateRequest(BaseModel):
    role: SeriesRole


class InferJobRequest(BaseModel):
    series_id: int
    module: ModuleName
    adapter: str = "model"


class PromptSegmentationRequest(BaseModel):
    module: ModuleName
    slice_index: int
    phase_index: int
    contour_key: Literal["la", "ra", "endo", "epi", "ventricular_epi", "rv", "fat", "fat_outer", "remote", "enhanced", "exclude", "mvo"]
    prompt_mode: Literal["box", "brush"]
    box: Optional[List[float]] = None
    brush_points: List[Point2D] = Field(default_factory=list)
    brush_radius: float = 8.0


class ModelFrameSegmentationRequest(BaseModel):
    module: ModuleName
    slice_index: int
    phase_index: int
    contour_key: Literal["la", "ra", "endo", "epi", "rv"]


class NeighborPropagationRequest(BaseModel):
    module: ModuleName
    source_slice_index: int
    source_phase_index: int
    target_slice_index: int
    target_phase_index: int
    method: Optional[Literal["optical_flow", "phase_correlation", "hybrid", "rigid", "affine"]] = None
    contrast_boost: Optional[bool] = None
    flow_attachment: Optional[float] = None
    flow_tightness: Optional[float] = None
    smooth_radius: Optional[int] = None
    min_area: Optional[int] = None
    shape_prior: Optional[bool] = None
    prior_strength: Optional[float] = None


class JobStatus(BaseModel):
    id: int
    status: str
    module: ModuleName
    adapter: str
    progress: float = 0.0
    progress_current: int = 0
    progress_total: int = 0
    message: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None


class MeasurementRequest(BaseModel):
    series_id: int
    threshold_method: Optional[Literal["nsd", "fwhm"]] = None
    sd_multiplier: float = 5.0
    grey_zone: bool = False


class CurvaturePreviewRequest(BaseModel):
    series_id: int
    landmarks: CurvatureLandmarks


class FatThresholdPreviewRequest(BaseModel):
    series_id: int
    slice_index: int
    phase_index: int
    lower: float = 0.0
    upper: float = 255.0


class LgeThresholdPreviewRequest(BaseModel):
    series_id: int
    slice_index: int
    threshold_method: Literal["nsd", "fwhm"] = "nsd"
    sd_multiplier: float = 5.0
    grey_zone: bool = False


class PhaseDetectionResult(BaseModel):
    series_id: int
    ed_phase: int
    es_phase: int
    method: str
    phase_scores: List[dict] = Field(default_factory=list)
    phase_labels: Dict[str, int] = Field(default_factory=dict)


class ReportUpdateRequest(BaseModel):
    status: ReportStatus = "草稿"
    findings: str = ""
    summary: str = ""
    payload: dict = Field(default_factory=dict)


class DirectoryEntry(BaseModel):
    name: str
    path: str
    has_dicom: bool = False


class DirectoryListing(BaseModel):
    current_path: str
    parent_path: Optional[str] = None
    directories: List[DirectoryEntry] = Field(default_factory=list)
    default_sample_path: str = ""
