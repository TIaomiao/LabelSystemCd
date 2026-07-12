from __future__ import annotations

import urllib.parse
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response
from PIL import Image

from .config import DEFAULT_SAMPLE_PATH, ensure_runtime_dirs
from .db import init_db, loads
from .models import ContourSet, DirectoryListing, ImportStudyRequest, InferJobRequest, JobStatus, MeasurementRequest, ModelFrameSegmentationRequest, NeighborPropagationRequest, PhaseDetectionResult, PromptSegmentationRequest, ReportDraft, ReportUpdateRequest, RoleUpdateRequest, StudyDetail
from .services.dicom_indexer import fetch_study_detail, get_frame_row, get_series_row, import_study, list_directories, list_frame_rows, read_frame_pixels, repair_series_roles, update_series_role
from .services.inference import create_job, fetch_contours, fetch_job, fetch_study_annotation_summaries, pause_job, run_job, save_contours
from .services.measurements import compute_lv_tracking_preview, ensure_render, export_pdf, measurement_to_csv, recompute_function, recompute_lge
from .services.model_frame_segmentation import apply_model_frame_segmentation
from .services.gpu_monitor import get_gpu_status, gpu_monitor
from .services.phase_detection import detect_function_phases
from .services.propagation_runner import PropagationError, propagate_neighbor_contours
from .services.prompt_segmentation import apply_prompt_segmentation
from .services.reporting import get_report, save_report


ensure_runtime_dirs()
init_db()
repair_series_roles()

app = FastAPI(title="CMR Workstation API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    gpu_monitor.start()


@app.on_event("shutdown")
def shutdown() -> None:
    gpu_monitor.stop()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _request_actor(request: Request) -> dict | None:
    user_id = request.headers.get("X-LabelSystem-User-Id")
    raw_username = request.headers.get("X-LabelSystem-Username")
    username = urllib.parse.unquote(raw_username) if raw_username else raw_username
    if not user_id and not username:
        return None
    actor: dict = {
        "username": username or "未知",
        "is_admin": request.headers.get("X-LabelSystem-Is-Admin") == "1",
    }
    try:
        actor["user_id"] = int(user_id) if user_id not in (None, "") else None
    except ValueError:
        actor["user_id"] = None
    return actor


@app.get("/gpu/status")
def gpu_status() -> dict:
    return get_gpu_status()


@app.get("/fs/list", response_model=DirectoryListing)
def fs_list(path: Optional[str] = None) -> dict:
    try:
        return list_directories(path, str(DEFAULT_SAMPLE_PATH.parent))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Selected folder does not exist.")


@app.post("/studies/import", response_model=StudyDetail)
def import_study_endpoint(payload: ImportStudyRequest) -> dict:
    try:
        study_id = import_study(payload.path or str(DEFAULT_SAMPLE_PATH))
        detail = fetch_study_detail(study_id, str(DEFAULT_SAMPLE_PATH))
        if detail is None:
            raise HTTPException(status_code=500, detail="Study import succeeded but result could not be loaded.")
        return detail
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Selected folder does not exist.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/studies/annotation-summaries")
def get_study_annotation_summaries(study_ids: str = Query(...)) -> dict:
    try:
        parsed_ids = [int(value) for value in study_ids.split(",") if value.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="study_ids must be comma-separated integers.")
    if len(parsed_ids) > 1000:
        raise HTTPException(status_code=400, detail="Too many study_ids.")
    return {"items": fetch_study_annotation_summaries(parsed_ids)}


@app.get("/studies/{study_id}", response_model=StudyDetail)
def get_study(study_id: int) -> dict:
    detail = fetch_study_detail(study_id, str(DEFAULT_SAMPLE_PATH))
    if detail is None:
        raise HTTPException(status_code=404, detail="Study not found.")
    return detail


@app.post("/series/{series_id}/role")
def update_role(series_id: int, payload: RoleUpdateRequest) -> dict:
    try:
        update_series_role(series_id, payload.role)
        return {"series_id": series_id, "role": payload.role}
    except KeyError:
        raise HTTPException(status_code=404, detail="Series not found.")


@app.post("/jobs/infer", response_model=JobStatus)
def infer(payload: InferJobRequest, background_tasks: BackgroundTasks, request: Request) -> dict:
    try:
        job_id = create_job(payload.series_id, payload.module, payload.adapter, actor=_request_actor(request))
    except KeyError:
        raise HTTPException(status_code=404, detail="Series not found.")
    background_tasks.add_task(run_job, job_id)
    return fetch_job(job_id)


@app.get("/jobs/{job_id}", response_model=JobStatus)
def job(job_id: int) -> dict:
    try:
        return fetch_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found.")


@app.post("/jobs/{job_id}/pause", response_model=JobStatus)
def pause_job_endpoint(job_id: int) -> dict:
    try:
        return pause_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found.")


@app.get("/contours/{series_id}", response_model=Optional[ContourSet])
def get_contours(series_id: int, module: str = Query(..., pattern="^(function|lge)$")) -> dict | None:
    return fetch_contours(series_id, module)


@app.put("/contours/{series_id}", response_model=ContourSet)
def put_contours(series_id: int, payload: ContourSet, request: Request) -> dict:
    try:
        return save_contours(series_id, payload.module, payload.model_dump(), actor=_request_actor(request), action_origin="manual")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/series/{series_id}/prompt-segment", response_model=ContourSet)
def prompt_segment(series_id: int, payload: PromptSegmentationRequest, request: Request) -> dict:
    try:
        return apply_prompt_segmentation(series_id, payload, actor=_request_actor(request))
    except KeyError:
        raise HTTPException(status_code=404, detail="Series or frame not found.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/series/{series_id}/model-frame-segment", response_model=ContourSet)
def model_frame_segment(series_id: int, payload: ModelFrameSegmentationRequest, request: Request) -> dict:
    try:
        return apply_model_frame_segmentation(
            series_id,
            module=payload.module,
            slice_index=payload.slice_index,
            phase_index=payload.phase_index,
            contour_key=payload.contour_key,
            actor=_request_actor(request),
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Series or frame not found.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/series/{series_id}/propagate-neighbor", response_model=ContourSet)
def propagate_neighbor_endpoint(series_id: int, payload: NeighborPropagationRequest, request: Request) -> dict:
    try:
        series = get_series_row(series_id)
        frames = list_frame_rows(series_id)
        contour_set = fetch_contours(series_id, payload.module)
        propagated = propagate_neighbor_contours(
            series=series,
            frames=frames,
            module=payload.module,
            contour_set=contour_set,
            source_slice_index=payload.source_slice_index,
            source_phase_index=payload.source_phase_index,
            target_slice_index=payload.target_slice_index,
            target_phase_index=payload.target_phase_index,
            propagation_overrides=payload.model_dump(
                include={
                    "method",
                    "contrast_boost",
                    "flow_attachment",
                    "flow_tightness",
                    "smooth_radius",
                    "min_area",
                    "shape_prior",
                    "prior_strength",
                },
                exclude_none=True,
            ),
        )
        return save_contours(
            series_id,
            payload.module,
            propagated,
            actor=_request_actor(request),
            action_origin="propagate",
            source_frame_key=f"{payload.source_slice_index}:{payload.source_phase_index}",
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Series not found.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PropagationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/measurements/function")
def recompute_function_endpoint(payload: MeasurementRequest) -> dict:
    try:
        return recompute_function(payload.series_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Series not found.")


@app.post("/measurements/tracking-preview")
def tracking_preview_endpoint(payload: MeasurementRequest) -> dict:
    try:
        return compute_lv_tracking_preview(payload.series_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Series not found.")


@app.post("/series/{series_id}/detect-phases", response_model=PhaseDetectionResult)
def detect_phases(series_id: int) -> dict:
    try:
        return detect_function_phases(series_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Series not found.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/measurements/lge")
def recompute_lge_endpoint(payload: MeasurementRequest) -> dict:
    try:
        return recompute_lge(payload.series_id, payload.threshold_method or "nsd", payload.sd_multiplier, payload.grey_zone)
    except KeyError:
        raise HTTPException(status_code=404, detail="Series not found.")


@app.get("/reports/{study_id}", response_model=ReportDraft)
def report(study_id: int) -> dict:
    try:
        return get_report(study_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Report not found.")


@app.put("/reports/{study_id}", response_model=ReportDraft)
def update_report(study_id: int, payload: ReportUpdateRequest) -> dict:
    return save_report(study_id, payload.model_dump())


@app.get("/exports/{study_id}.csv")
def export_csv(study_id: int) -> PlainTextResponse:
    return PlainTextResponse(measurement_to_csv(study_id), media_type="text/csv; charset=utf-8")


@app.get("/exports/{study_id}.pdf")
def export_pdf_endpoint(study_id: int) -> FileResponse:
    path = export_pdf(study_id, str(DEFAULT_SAMPLE_PATH))
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.get("/series/{series_id}/image")
def image(series_id: int, slice_index: int = 0, phase_index: int = 0) -> Response:
    try:
        frame = get_frame_row(series_id, slice_index, phase_index)
    except KeyError:
        raise HTTPException(status_code=404, detail="Frame not found.")
    output_path = ensure_render(frame, series_id)
    if output_path.exists():
        return FileResponse(
            output_path,
            media_type="image/png",
            headers={
                "Cache-Control": "no-store, private, max-age=0",
                "X-Content-Type-Options": "nosniff",
                "X-Robots-Tag": "noindex, noarchive, nosnippet",
                "Content-Disposition": 'inline; filename="viewer-image.png"',
            },
        )
    pixels = read_frame_pixels(frame)
    image = Image.fromarray(pixels)
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return Response(
        content=buffer.getvalue(),
        media_type="image/png",
        headers={
            "Cache-Control": "no-store, private, max-age=0",
            "X-Content-Type-Options": "nosniff",
            "X-Robots-Tag": "noindex, noarchive, nosnippet",
            "Content-Disposition": 'inline; filename="viewer-image.png"',
        },
    )


@app.get("/series/{series_id}")
def series_detail(series_id: int) -> dict:
    try:
        row = get_series_row(series_id)
        row["folder_path"] = "已隐藏"
        row["series_uid"] = f"series-{series_id}"
        return row
    except KeyError:
        raise HTTPException(status_code=404, detail="Series not found.")


@app.get("/series/{series_id}/geometry")
def series_geometry(series_id: int) -> dict:
    try:
        series = get_series_row(series_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Series not found.")

    frames = list_frame_rows(series_id)
    payload = []
    for frame in frames:
        metadata = frame.get("metadata_json")
        if isinstance(metadata, str):
            metadata_payload = loads(metadata, {})
        else:
            metadata_payload = metadata or {}
        image_position = frame.get("image_position_json")
        if isinstance(image_position, str):
            image_position_payload = loads(image_position, [])
        else:
            image_position_payload = image_position or []
        payload.append(
            {
                "id": frame["id"],
                "slice_index": frame["slice_index"],
                "phase_index": frame["phase_index"],
                "image_position": image_position_payload,
                "image_orientation": metadata_payload.get("image_orientation", []),
                "pixel_spacing": metadata_payload.get("pixel_spacing", [series.get("pixel_spacing_x") or 1.0, series.get("pixel_spacing_y") or 1.0]),
            }
        )

    return {"series_id": series_id, "frames": payload}
