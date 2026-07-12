from __future__ import annotations

import os
import io
import json
import csv
import hmac
import hashlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from threading import Lock

from flask import Response, abort, current_app, jsonify, request, send_from_directory
from flask_login import current_user, login_required
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import and_, or_
from sqlalchemy.orm import load_only

from extensions import db
from models import (
    CaseAssignment,
    CviCaseCatalog,
    EvaluationResult,
    FunctionalAssessment,
    ImageAnalysis,
    LGEAnalysis,
    MediaAccessLog,
    OtherFindings,
    StructureAssessment,
    User,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CVI_WEB_DIST = PROJECT_ROOT / "apps" / "web" / "dist"
CVI_API_BASE = os.environ.get("CVI_API_BASE", "http://127.0.0.1:8010").rstrip("/")
CVI_API_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
CASE_SCAN_LIMIT = 10000
CVI_MEDIA_ATTEMPTS: dict[tuple[str, str], list[float]] = {}
MEDIA_TOKEN_COOKIE = "ls_media_token"
MEDIA_TOKEN_TTL_SECONDS = 20 * 60
CVI_ALLOWED_ORIGINS = {
    "http://47.108.84.221:8282",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:5000",
    "http://localhost:5000",
}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


CVI_MEDIA_CACHE_MAX_ITEMS = _int_env("LABELSYSTEM_CVI_IMAGE_CACHE_ITEMS", 800)
CVI_MEDIA_CACHE_MAX_BYTES = _int_env("LABELSYSTEM_CVI_IMAGE_CACHE_BYTES", 512 * 1024 * 1024)
CVI_MEDIA_BROWSER_MAX_AGE = _int_env("LABELSYSTEM_CVI_IMAGE_BROWSER_MAX_AGE", 300)
CVI_MEDIA_CACHE_LOCK = Lock()
CVI_MEDIA_CACHE_BYTES = 0
CVI_MEDIA_RESPONSE_CACHE: OrderedDict[str, tuple[int, dict[str, str], bytes]] = OrderedDict()
CASE_MANIFEST_CACHE: dict[str, tuple[int, dict]] = {}

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "content-length",
}


def _safe_actor_username(value: str | None) -> str:
    if not value:
        return ""
    return urllib.parse.quote(value, safe="")


def _origin_from_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value or "")
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _allowed_origins() -> set[str]:
    configured = {
        origin.strip().rstrip("/")
        for origin in os.environ.get("LABELSYSTEM_CORS_ORIGINS", "").split(",")
        if origin.strip()
    }
    return CVI_ALLOWED_ORIGINS | configured


def _is_cvi_media_request(path: str) -> bool:
    parsed_path = path.strip("/")
    return (
        parsed_path.startswith("series/")
        and parsed_path.endswith("/image")
    )


def _browser_viewer_request() -> bool:
    allowed = _allowed_origins()
    referer_origin = _origin_from_url(request.headers.get("Referer", ""))
    origin = request.headers.get("Origin", "").rstrip("/")
    if referer_origin in allowed or origin in allowed:
        return True
    fetch_site = request.headers.get("Sec-Fetch-Site", "")
    fetch_dest = request.headers.get("Sec-Fetch-Dest", "")
    if fetch_site in {"same-origin", "same-site"} and fetch_dest in {"image", "empty"}:
        return True
    if request.remote_addr in {"127.0.0.1", "::1"}:
        return True
    return False


def _valid_media_token() -> bool:
    if not current_user.is_authenticated:
        return False
    token = request.cookies.get(MEDIA_TOKEN_COOKIE, "")
    try:
        raw_user_id, raw_expires, signature = token.split(":", 2)
        user_id = int(raw_user_id)
        expires_at = int(raw_expires)
    except (TypeError, ValueError):
        return False
    if user_id != current_user.id or expires_at < int(time.time()):
        return False
    payload = f"{user_id}:{expires_at}".encode("utf-8")
    secret = current_app.config["SECRET_KEY"].encode("utf-8")
    expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def _build_media_token(user_id: int) -> str:
    expires_at = int(time.time()) + MEDIA_TOKEN_TTL_SECONDS
    payload = f"{user_id}:{expires_at}".encode("utf-8")
    secret = current_app.config["SECRET_KEY"].encode("utf-8")
    signature = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return f"{user_id}:{expires_at}:{signature}"


def _check_cvi_media_rate(limit: int = 900, window_seconds: int = 60) -> bool:
    now = time.time()
    user_part = str(getattr(current_user, "id", "anonymous")) if current_user.is_authenticated else request.remote_addr or "unknown"
    key = ("cvi-image", user_part)
    attempts = [ts for ts in CVI_MEDIA_ATTEMPTS.get(key, []) if now - ts < window_seconds]
    if len(attempts) >= limit:
        CVI_MEDIA_ATTEMPTS[key] = attempts
        return False
    attempts.append(now)
    CVI_MEDIA_ATTEMPTS[key] = attempts
    return True


def _client_ip() -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _log_cvi_media(status: str, path: str) -> None:
    if status == "ok" and os.environ.get("LABELSYSTEM_CVI_LOG_OK_MEDIA", "0").lower() not in {"1", "true", "yes"}:
        return
    try:
        db.session.add(MediaAccessLog(
            user_id=current_user.id if current_user.is_authenticated else None,
            username=current_user.username if current_user.is_authenticated else None,
            kind="cvi-image",
            namespace="cvi",
            dataset="",
            case_id="",
            path=path[:1000],
            status=status,
            ip_address=_client_ip(),
            user_agent=(request.headers.get("User-Agent") or "")[:500],
        ))
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning("Failed to write CVI media access log: %s", exc)


def _secure_cvi_media_headers(response: Response) -> Response:
    if CVI_MEDIA_BROWSER_MAX_AGE > 0:
        response.headers["Cache-Control"] = f"private, max-age={CVI_MEDIA_BROWSER_MAX_AGE}, stale-while-revalidate=30"
        response.headers.pop("Pragma", None)
    else:
        response.headers["Cache-Control"] = "no-store, private, max-age=0"
        response.headers["Pragma"] = "no-cache"
    response.headers["Vary"] = "Cookie"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Robots-Tag"] = "noindex, noarchive, nosnippet"
    response.headers["Accept-Ranges"] = "none"
    response.headers["Content-Disposition"] = 'inline; filename="viewer-image.png"'
    response.headers["X-LabelSystem-Media-Protection"] = "token-watermark"
    if current_user.is_authenticated:
        response.set_cookie(
            MEDIA_TOKEN_COOKIE,
            _build_media_token(current_user.id),
            max_age=MEDIA_TOKEN_TTL_SECONDS,
            httponly=True,
            secure=current_app.config.get("SESSION_COOKIE_SECURE", False),
            samesite="Lax",
            path="/",
        )
    return response


def _watermark_text() -> str:
    username = current_user.username if current_user.is_authenticated else "viewer"
    return f"{username} {datetime.utcnow().strftime('%Y-%m-%d %H:%MZ')}"


def _add_edge_watermark_to_png(body: bytes) -> bytes:
    if os.environ.get("LABELSYSTEM_IMAGE_WATERMARK", "1").lower() in {"0", "false", "no"}:
        return body
    try:
        with Image.open(io.BytesIO(body)) as image:
            base = image.convert("RGBA")
            width, height = base.size
            if width < 64 or height < 64:
                return body
            overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            text = _watermark_text()
            font_size = max(10, min(16, width // 28))
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size)
            except Exception:
                font = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            pad_x = max(5, width // 90)
            pad_y = max(3, height // 120)
            margin = max(4, min(width, height) // 70)
            x = max(margin, width - text_w - pad_x * 2 - margin)
            y = max(margin, height - text_h - pad_y * 2 - margin)
            rect = (x, y, min(width - margin, x + text_w + pad_x * 2), min(height - margin, y + text_h + pad_y * 2))
            draw.rounded_rectangle(rect, radius=3, fill=(0, 0, 0, 92), outline=(255, 255, 255, 45))
            draw.text((x + pad_x, y + pad_y - 1), text, font=font, fill=(255, 255, 255, 135))
            marked = Image.alpha_composite(base, overlay).convert("RGB")
            output = io.BytesIO()
            marked.save(output, format="PNG")
            return output.getvalue()
    except Exception:
        return body


def _case_has_assignments(namespace: str, dataset: str, case_id: str) -> bool:
    raw_case_id = str(case_id or "").strip()
    normalized_case_id = _normalized_case_id(raw_case_id)
    query = CaseAssignment.query.filter_by(
        namespace=namespace,
        dataset=dataset or "",
        active=True,
    )
    if normalized_case_id:
        query = query.filter(or_(
            CaseAssignment.case_id == raw_case_id,
            CaseAssignment.case_id == normalized_case_id,
            CaseAssignment.case_id.like(f"%/{normalized_case_id}"),
        ))
    return query.first() is not None


def _dataset_has_assignments(namespace: str, dataset: str) -> bool:
    return CaseAssignment.query.filter_by(
        namespace=namespace,
        dataset=dataset or "",
        active=True,
    ).first() is not None


def _assigned_case_ids_for_current_user(namespace: str, dataset: str) -> list[str]:
    if not current_user.is_authenticated:
        return []
    rows = (
        CaseAssignment.query.options(load_only(CaseAssignment.case_id))
        .filter_by(
            namespace=namespace,
            dataset=dataset or "",
            user_id=current_user.id,
            active=True,
        )
        .order_by(CaseAssignment.case_id.asc())
        .all()
    )
    return [row.case_id for row in rows if row.case_id]


def _normalized_case_id(case_id: str) -> str:
    return Path(str(case_id or "")).name


def _user_can_access_case(namespace: str, dataset: str, case_id: str) -> bool:
    if not current_user.is_authenticated:
        return False
    if getattr(current_user, "is_admin", False):
        return True
    dataset = dataset or ""
    normalized_case_id = _normalized_case_id(case_id)
    if namespace == "functional" and dataset == "CMR_ALL":
        return True
    raw_case_id = str(case_id or "").strip()
    return CaseAssignment.query.filter_by(
        namespace=namespace,
        dataset=dataset,
        user_id=current_user.id,
        active=True,
    ).filter(or_(
        CaseAssignment.case_id == raw_case_id,
        CaseAssignment.case_id == normalized_case_id,
        CaseAssignment.case_id.like(f"%/{normalized_case_id}"),
    )).first() is not None


def _filtered_headers(headers) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


def _media_cache_key(path: str, query: str) -> str:
    user_id = getattr(current_user, "id", "anonymous") if current_user.is_authenticated else "anonymous"
    username = getattr(current_user, "username", "viewer") if current_user.is_authenticated else "viewer"
    watermark_enabled = os.environ.get("LABELSYSTEM_IMAGE_WATERMARK", "1").lower() not in {"0", "false", "no"}
    return f"{user_id}|{username}|wm={int(watermark_enabled)}|{path}?{query}"


def _media_cache_get(key: str) -> tuple[int, dict[str, str], bytes] | None:
    if CVI_MEDIA_CACHE_MAX_ITEMS <= 0 or CVI_MEDIA_CACHE_MAX_BYTES <= 0:
        return None
    with CVI_MEDIA_CACHE_LOCK:
        item = CVI_MEDIA_RESPONSE_CACHE.get(key)
        if item is None:
            return None
        CVI_MEDIA_RESPONSE_CACHE.move_to_end(key)
        return item


def _media_cache_put(key: str, status: int, headers: dict[str, str], body: bytes) -> None:
    if CVI_MEDIA_CACHE_MAX_ITEMS <= 0 or CVI_MEDIA_CACHE_MAX_BYTES <= 0 or not body:
        return
    body_size = len(body)
    if body_size > CVI_MEDIA_CACHE_MAX_BYTES:
        return

    global CVI_MEDIA_CACHE_BYTES
    cache_headers = {
        header: value
        for header, value in headers.items()
        if header.lower() not in {"cache-control", "pragma", "expires", "etag", "last-modified"}
    }
    with CVI_MEDIA_CACHE_LOCK:
        previous = CVI_MEDIA_RESPONSE_CACHE.pop(key, None)
        if previous is not None:
            CVI_MEDIA_CACHE_BYTES -= len(previous[2])

        CVI_MEDIA_RESPONSE_CACHE[key] = (status, cache_headers, body)
        CVI_MEDIA_CACHE_BYTES += body_size

        while (
            len(CVI_MEDIA_RESPONSE_CACHE) > CVI_MEDIA_CACHE_MAX_ITEMS
            or CVI_MEDIA_CACHE_BYTES > CVI_MEDIA_CACHE_MAX_BYTES
        ):
            _, removed = CVI_MEDIA_RESPONSE_CACHE.popitem(last=False)
            CVI_MEDIA_CACHE_BYTES -= len(removed[2])


def _proxy_cvi_api(path: str) -> Response:
    is_media = _is_cvi_media_request(path)
    if is_media:
        if not _browser_viewer_request():
            _log_cvi_media("blocked_origin", path)
            return Response("Image access must come from the workstation viewer.", status=403, content_type="text/plain; charset=utf-8")
        if not _check_cvi_media_rate():
            _log_cvi_media("rate_limited", path)
            return Response("Too many image requests. Please slow down.", status=429, content_type="text/plain; charset=utf-8")
        if not _valid_media_token():
            # Keep authenticated workstation sessions from losing images when the auxiliary
            # media token expires or was not planted by an older page load.
            _log_cvi_media("token_refreshed", path)

    query = request.query_string.decode("utf-8")
    target = f"{CVI_API_BASE}/{path}"
    if query:
        target = f"{target}?{query}"

    media_cache_key = ""
    if is_media and request.method == "GET":
        media_cache_key = _media_cache_key(path, query)
        cached_media = _media_cache_get(media_cache_key)
        if cached_media is not None:
            status, cached_headers, cached_body = cached_media
            response = Response(cached_body, status=status, headers=cached_headers)
            response.headers["X-LabelSystem-Image-Cache"] = "HIT"
            return _secure_cvi_media_headers(response)

    headers = _filtered_headers(request.headers)
    if current_user.is_authenticated:
        headers["X-LabelSystem-User-Id"] = str(current_user.id)
        headers["X-LabelSystem-Username"] = _safe_actor_username(current_user.username)
        headers["X-LabelSystem-Is-Admin"] = "1" if getattr(current_user, "is_admin", False) else "0"
    data = request.get_data() if request.method not in {"GET", "HEAD"} else None
    upstream_request = urllib.request.Request(
        target,
        data=data,
        headers=headers,
        method=request.method,
    )

    try:
        with CVI_API_OPENER.open(upstream_request, timeout=3600) as upstream:
            body = b"" if request.method == "HEAD" else upstream.read()
            if is_media and request.method != "HEAD" and upstream.status < 400:
                body = _add_edge_watermark_to_png(body)
                _log_cvi_media("ok", path)
                if request.method == "GET" and media_cache_key:
                    _media_cache_put(media_cache_key, upstream.status, _filtered_headers(upstream.headers), body)
            response = Response(
                body,
                status=upstream.status,
                headers=_filtered_headers(upstream.headers),
            )
            if is_media:
                response.headers["X-LabelSystem-Image-Cache"] = "MISS"
            return _secure_cvi_media_headers(response) if is_media else response
    except urllib.error.HTTPError as exc:
        body = b"" if request.method == "HEAD" else exc.read()
        if is_media and request.method != "HEAD" and exc.code < 400:
            body = _add_edge_watermark_to_png(body)
        response = Response(
            body,
            status=exc.code,
            headers=_filtered_headers(exc.headers),
        )
        return _secure_cvi_media_headers(response) if is_media else response
    except urllib.error.URLError as exc:
        current_app.logger.exception("CVI API proxy failed: %s", exc)
        return Response(
            "CVI 工作站 API 尚未启动或不可访问。",
            status=502,
            content_type="text/plain; charset=utf-8",
        )


def _json_request(path: str, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    data = None
    headers = {"Accept": "application/json"}
    if current_user.is_authenticated:
        headers["X-LabelSystem-User-Id"] = str(current_user.id)
        headers["X-LabelSystem-Username"] = _safe_actor_username(current_user.username)
        headers["X-LabelSystem-Is-Admin"] = "1" if getattr(current_user, "is_admin", False) else "0"
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    upstream_request = urllib.request.Request(
        f"{CVI_API_BASE}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with CVI_API_OPENER.open(upstream_request, timeout=3600) as upstream:
            body = upstream.read().decode("utf-8")
            return upstream.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {"detail": body or exc.reason}
        return exc.code, payload
    except urllib.error.URLError as exc:
        current_app.logger.exception("CVI API request failed: %s", exc)
        return 502, {"detail": "CVI 工作站 API 尚未启动或不可访问。"}


def _is_hidden(path: Path) -> bool:
    return path.name.startswith(".") or path.name == "__MACOSX"


def _looks_like_dicom(filename: str) -> bool:
    name = filename.strip()
    lower = name.lower()
    if lower.endswith((".dcm", ".dic", ".ima")):
        return True
    if lower == "dicomdir":
        return False
    # Several RenJi exports use extensionless Philips-style files such as IM_0001.
    return bool(re.fullmatch(r"(?:im[_-]?)?\d{4,}", lower) or re.fullmatch(r"\d[\d.]{15,}", lower))


def _selection_range_from_sequence_name(name: str) -> tuple[int, int] | None:
    match = re.match(r"^(?:4CH|SAX|LGE)=(\d+)-(\d+)$", name.strip(), flags=re.IGNORECASE)
    if not match:
        return None
    start = int(match.group(1))
    end = int(match.group(2))
    if start <= 0 or end < start:
        return None
    return start, end


def _count_selected_dicoms(sequence_dir: Path) -> int:
    files: list[Path] = []
    try:
        files = sorted(
            [item for item in sequence_dir.iterdir() if item.is_file() and _looks_like_dicom(item.name)],
            key=lambda item: item.name.lower(),
        )
    except OSError:
        files = []

    if not files:
        try:
            files = sorted(
                [item for item in sequence_dir.rglob("*") if item.is_file() and _looks_like_dicom(item.name)],
                key=lambda item: str(item.relative_to(sequence_dir)).lower(),
            )
        except OSError:
            files = []

    selected_range = _selection_range_from_sequence_name(sequence_dir.name)
    if selected_range is None:
        return len(files)
    start, end = selected_range
    return len(files[start - 1 : end])


def _base_dicom_dataset_name(dataset: str | None) -> str:
    if not dataset:
        return ""
    raw = str(dataset).strip()
    if raw.startswith("new_"):
        raw = raw.replace("new_", "", 1)
    if raw.startswith("SOLO_CMR_ALL_"):
        return "CMR_ALL"
    if raw.startswith("SOLO_CMR_Chendu_"):
        return "CMR_Chendu"
    if raw.startswith("SOLO_CMR_SCS_"):
        return "CMR_SCS"
    if raw.startswith("SOLO_CMR_YA_"):
        return "CMR_YA"
    return raw


def _configured_dataset_root(dataset: str | None) -> Path | None:
    target = _base_dicom_dataset_name(dataset)
    if not target:
        return None
    for item in current_app.config.get("CVI_LIBRARY_MULTICENTER_ROOTS", []):
        dataset_name = str(item.get("dataset") or "").strip()
        if dataset_name != target:
            continue
        path_text = str(item.get("path") or "").strip()
        if not path_text:
            continue
        root_path = Path(path_text).expanduser()
        if root_path.exists():
            return root_path
    return None


def _resolve_dicom_case_path(dataset: str, case_id: str, case_path: Path) -> Path:
    # SOLO eval datasets contain reports/metrics only; import should use the original raw DICOM case directory.
    base_root = _configured_dataset_root(_base_dicom_dataset_name(dataset))
    if base_root is not None:
        candidate = base_root / case_id
        if candidate.is_dir() and _count_selected_dicoms(candidate) > 0:
            return candidate
        basename_candidate = base_root / Path(str(case_id)).name
        if basename_candidate.is_dir() and _count_selected_dicoms(basename_candidate) > 0:
            return basename_candidate
    return case_path


def _sequence_summary(case_path: Path) -> tuple[list[dict], int, bool]:
    sequences: list[dict] = []
    total = 0
    has_dicom = False
    try:
        children = sorted(
            [child for child in case_path.iterdir() if child.is_dir() and not _is_hidden(child)],
            key=lambda item: item.name.lower(),
        )
    except OSError:
        return sequences, 0, False

    for child in children:
        if child.name in {"predictions", "inference_viz", "previews", "segmentations", "key_frames", "measurements"}:
            continue
        count = _count_selected_dicoms(child)

        if count > 0:
            has_dicom = True
        total += count
        sequences.append({"name": child.name, "dicom_count": count})

    return sequences, total, has_dicom


def _has_direct_cmr_sequence_dirs(case_path: Path) -> bool:
    try:
        child_names = [child.name for child in case_path.iterdir() if child.is_dir() and not _is_hidden(child)]
    except OSError:
        return False
    for name in child_names:
        if name in {"4CH", "SAX", "LGE"}:
            return True
        if name.startswith(("4CH=", "SAX=", "LGE=", "4CH_", "SAX_", "LGE_")):
            return True
    return False


def _has_dicom_case_content(case_path: Path) -> bool:
    try:
        if _count_selected_dicoms(case_path) > 0:
            return True
        children = [child for child in case_path.iterdir() if child.is_dir() and not _is_hidden(child)]
    except OSError:
        return False
    for child in children:
        if child.name.upper() == "DICOM":
            return True
        if _count_selected_dicoms(child) > 0:
            return True
    return False


def _source_roots() -> list[dict]:
    roots = []
    data_root = Path(current_app.config["DATA_ROOT"]).expanduser()
    if data_root.exists():
        roots.append(
            {
                "source": "annotation",
                "label": "原标注目录",
                "root": data_root,
                "dataset": data_root.name,
                "nested_dataset": False,
            }
        )

    configured_functional_roots = []
    for item in current_app.config.get("CVI_LIBRARY_MULTICENTER_ROOTS", []):
        path_text = str(item.get("path") or "").strip()
        dataset_name = str(item.get("dataset") or "").strip()
        if not path_text or not dataset_name:
            continue
        root_path = Path(path_text).expanduser()
        if not root_path.exists():
            continue
        configured_functional_roots.append(
            {
                "dataset": dataset_name,
                "label": str(item.get("label") or dataset_name),
                "path": root_path,
                "case_dir_contains_dicoms": bool(item.get("case_dir_contains_dicoms")),
                "case_dir_depth": item.get("case_dir_depth"),
                "case_id_manifest": item.get("case_id_manifest"),
                "case_id_prefix": item.get("case_id_prefix"),
            }
        )

    if configured_functional_roots:
        roots.append(
            {
                "source": "functional",
                "label": "四中心病例库",
                "root": None,
                "dataset": "",
                "nested_dataset": False,
                "datasets": configured_functional_roots,
            }
        )
    else:
        functional_root = Path(current_app.config["FUNCTIONAL_DATA_ROOT"]).expanduser()
        if functional_root.exists():
            roots.append(
                {
                    "source": "functional",
                    "label": "MRIAgent data",
                    "root": functional_root,
                    "dataset": "",
                    "nested_dataset": True,
                }
            )
    return roots


def _configured_functional_datasets() -> list[dict]:
    functional_root = next((item for item in _source_roots() if item["source"] == "functional"), None)
    dataset_items = functional_root.get("datasets") if functional_root else None
    return list(dataset_items or [])


def _eval_report_case_ids(base_dataset: str, limit: int | None = None) -> list[str]:
    if base_dataset == "CMR_ALL":
        configured_case_list = current_app.config.get("CMR_ALL_REPORT100_CASE_LIST")
        if configured_case_list:
            case_list_path = Path(str(configured_case_list)).expanduser()
            if case_list_path.exists():
                case_ids = [
                    line.strip()
                    for line in case_list_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                return case_ids[:limit] if limit else case_ids

    eval_root = Path(current_app.config["EVAL_ROOT"]).expanduser()
    if not eval_root.exists():
        return []

    preferred_datasets = []
    new_dataset = f"new_{base_dataset}"
    if (eval_root / new_dataset).is_dir():
        preferred_datasets.append(new_dataset)
    if (eval_root / base_dataset).is_dir():
        preferred_datasets.append(base_dataset)

    if not preferred_datasets:
        return []

    case_ids_by_name: dict[str, None] = {}
    for dataset_name in preferred_datasets:
        dataset_dir = eval_root / dataset_name
        case_dirs = sorted(
            [child for child in dataset_dir.iterdir() if child.is_dir() and not _is_hidden(child)],
            key=lambda path: path.name.lower(),
        )
        for case_dir in case_dirs:
            if case_dir.name in case_ids_by_name:
                continue
            if not ((case_dir / "report.json").exists() or (case_dir / "report_pro.json").exists()):
                continue
            case_ids_by_name[case_dir.name] = None
    case_ids = sorted(case_ids_by_name.keys(), key=str.lower)
    return case_ids[:limit] if limit else case_ids


def _cvi_library_options() -> list[dict]:
    is_admin = bool(getattr(current_user, "is_admin", False)) if current_user.is_authenticated else False
    username = str(getattr(current_user, "username", "") or "").strip()
    options = []

    if is_admin:
        options.append(
            {
                "value": "annotation",
                "label": "原标注目录",
                "root": str(Path(current_app.config["DATA_ROOT"]).expanduser()),
                "source": "annotation",
            }
        )
    else:
        annotation_case_ids = _assigned_case_ids_for_current_user("annotation", "")
        if annotation_case_ids:
            options.append(
                {
                    "value": "annotation",
                    "label": f"原标注目录-{username}专属",
                    "root": str(Path(current_app.config["DATA_ROOT"]).expanduser()),
                    "source": "annotation",
                    "case_ids": annotation_case_ids,
                }
            )

    for item in _configured_functional_datasets():
        dataset_name = str(item.get("dataset") or "").strip()
        if not dataset_name:
            continue
        label = str(item.get("label") or dataset_name).strip()
        root_path = Path(item["path"]).expanduser()
        user_case_ids = _assigned_case_ids_for_current_user("functional", dataset_name) if not is_admin else []

        if dataset_name == "CMR_ALL":
            report100_case_ids = _eval_report_case_ids("CMR_ALL")
            options.insert(
                0 if not options else 1,
                {
                    "value": "functional::CMR_ALL::report100",
                    "label": "昆医附二院报告评分150例",
                    "root": str(root_path),
                    "source": "functional",
                    "dataset_filters": ["CMR_ALL"],
                    "case_ids": report100_case_ids,
                },
            )
            options.insert(
                1 if options else 0,
                {
                    "value": "functional::CMR_ALL::all",
                    "label": "昆医附二院全部病例",
                    "root": str(root_path),
                    "source": "functional",
                    "dataset_filters": ["CMR_ALL"],
                },
            )
            if not is_admin and user_case_ids:
                options.append(
                    {
                        "value": "functional::CMR_ALL::assigned",
                        "label": f"昆医附二院标注任务-{username}专属",
                        "root": str(root_path),
                        "source": "functional",
                        "dataset_filters": ["CMR_ALL"],
                        "case_ids": user_case_ids,
                    }
                )
        elif not is_admin and user_case_ids:
            options.append(
                {
                    "value": f"functional::{dataset_name}::assigned",
                    "label": f"{label}-{username}专属",
                    "root": str(root_path),
                    "source": "functional",
                    "dataset_filters": [dataset_name],
                    "case_ids": user_case_ids,
                }
            )

        if is_admin:
            options.append(
                {
                    "value": f"functional::{dataset_name}",
                    "label": label,
                    "root": str(root_path),
                    "source": "functional",
                    "dataset_filters": [dataset_name],
                }
            )
    return options


def _parse_catalog_source_selection(source_value: str) -> dict | None:
    is_admin = bool(getattr(current_user, "is_admin", False)) if current_user.is_authenticated else False
    if source_value == "all":
        if not is_admin:
            return None
        return {
            "value": "all",
            "scan_source": "all",
            "query_source": "all",
            "dataset_filters": None,
            "case_ids": None,
        }

    if source_value == "functional":
        if not is_admin:
            return None
        return {
            "value": "functional",
            "scan_source": "functional",
            "query_source": "functional",
            "dataset_filters": None,
            "case_ids": None,
        }

    for item in _cvi_library_options():
        if item["value"] != source_value:
            continue
        return {
            "value": item["value"],
            "scan_source": item["source"],
            "query_source": item["source"],
            "dataset_filters": item.get("dataset_filters"),
            "case_ids": item.get("case_ids"),
        }
    return None


def _manifest_case_id(sequence: str, prefix: str) -> str:
    if sequence.isdigit():
        return f"{prefix}{int(sequence):04d}"
    if prefix and sequence.startswith(prefix) and sequence[len(prefix):].isdigit():
        return f"{prefix}{int(sequence[len(prefix):]):04d}"
    return ""


def _case_manifest_index(dataset_item: dict) -> dict:
    manifest_text = str(dataset_item.get("case_id_manifest") or "").strip()
    if not manifest_text:
        return {"relative_to_case_id": {}, "case_id_to_record": {}}

    manifest_path = Path(manifest_text).expanduser()
    if not manifest_path.is_file():
        raise RuntimeError(f"Case ID manifest is unavailable for {dataset_item['dataset']}")

    cache_key = str(manifest_path.resolve())
    modified_ns = manifest_path.stat().st_mtime_ns
    cached = CASE_MANIFEST_CACHE.get(cache_key)
    if cached and cached[0] == modified_ns:
        return cached[1]

    prefix = str(dataset_item.get("case_id_prefix") or "").strip()
    relative_to_case_id: dict[str, str] = {}
    case_id_to_record: dict[str, dict[str, str]] = {}
    try:
        with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                relative_dir = str(row.get("source_relative_dir") or "").strip()
                sequence = str(row.get("case_sequence") or "").strip()
                case_id = _manifest_case_id(sequence, prefix)
                if not case_id:
                    continue
                if not relative_dir:
                    continue
                relative_to_case_id[Path(relative_dir).as_posix()] = case_id
                case_id_to_record[case_id] = {
                    "patient_id": str(row.get("patient_id") or "").strip(),
                    "accession_number": str(row.get("accession_number") or "").strip(),
                    "study_id": str(row.get("study_id") or "").strip(),
                    "study_instance_uid": str(row.get("study_instance_uid") or "").strip(),
                }
    except OSError as exc:
        raise RuntimeError(f"Could not read case ID manifest for {dataset_item['dataset']}") from exc

    if not relative_to_case_id:
        raise RuntimeError(f"Case ID manifest has no usable Study mappings for {dataset_item['dataset']}")
    index = {
        "relative_to_case_id": relative_to_case_id,
        "case_id_to_record": case_id_to_record,
    }
    CASE_MANIFEST_CACHE[cache_key] = (modified_ns, index)
    return index


def _case_id_manifest_map(dataset_item: dict) -> dict[str, str]:
    return _case_manifest_index(dataset_item)["relative_to_case_id"]


def _configured_dataset_item(dataset: str) -> dict | None:
    canonical = _canonical_dataset(dataset)
    for item in _configured_functional_datasets():
        if _canonical_dataset(item.get("dataset")) == canonical:
            return item
    return None


def _manifest_search_matches(dataset_filters: list[str] | None, search: str) -> dict[str, set[str]]:
    needle = str(search or "").strip().casefold()
    if not needle:
        return {}
    selected = {_canonical_dataset(item) for item in (dataset_filters or [])}
    matches: dict[str, set[str]] = {}
    for dataset_item in _configured_functional_datasets():
        dataset = str(dataset_item.get("dataset") or "")
        if selected and _canonical_dataset(dataset) not in selected:
            continue
        if not dataset_item.get("case_id_manifest"):
            continue
        case_matches = set()
        for case_id, record in _case_manifest_index(dataset_item)["case_id_to_record"].items():
            values = [case_id, *record.values()]
            if any(needle in value.casefold() for value in values if value):
                case_matches.add(case_id)
        if case_matches:
            matches[dataset] = case_matches
    return matches


def _iter_dirs_at_depth(root: Path, depth: int):
    if depth < 1:
        return
    try:
        children = sorted(
            [child for child in root.iterdir() if child.is_dir() and not _is_hidden(child)],
            key=lambda path: path.name.lower(),
        )
    except OSError:
        return

    if depth == 1:
        yield from children
        return

    for child in children:
        yield from _iter_dirs_at_depth(child, depth - 1)


def _iter_case_dirs(source_filter: str = "all", dataset_filters: list[str] | None = None):
    yielded = 0
    for item in _source_roots():
        if source_filter != "all" and item["source"] != source_filter:
            continue
        dataset_roots = item.get("datasets") or []
        if dataset_roots:
            for dataset_item in dataset_roots:
                if dataset_filters and dataset_item["dataset"] not in dataset_filters:
                    continue
                dataset_dir: Path = dataset_item["path"]
                configured_depth = dataset_item.get("case_dir_depth")
                if configured_depth is not None:
                    try:
                        case_dir_depth = int(configured_depth)
                    except (TypeError, ValueError):
                        raise RuntimeError(f"Invalid case directory depth for {dataset_item['dataset']}")
                    case_id_map = _case_id_manifest_map(dataset_item)
                    for case_dir in _iter_dirs_at_depth(dataset_dir, case_dir_depth):
                        relative_case_id = case_dir.relative_to(dataset_dir).as_posix()
                        case_id = case_id_map.get(relative_case_id)
                        if not case_id:
                            continue
                        yielded += 1
                        if yielded > CASE_SCAN_LIMIT:
                            return
                        yield item["source"], dataset_item["dataset"], case_id, case_dir
                    continue
                case_dirs = sorted(
                    [child for child in dataset_dir.iterdir() if child.is_dir() and not _is_hidden(child)],
                    key=lambda path: path.name.lower(),
                )
                for case_dir in case_dirs:
                    nested_case_dirs = sorted(
                        [
                            child
                            for child in case_dir.iterdir()
                            if child.is_dir() and not _is_hidden(child)
                        ],
                        key=lambda path: path.name.lower(),
                    )
                    should_keep_case_dir = bool(dataset_item.get("case_dir_contains_dicoms"))
                    if nested_case_dirs and not _has_direct_cmr_sequence_dirs(case_dir) and not should_keep_case_dir:
                        for nested_case_dir in nested_case_dirs:
                            yielded += 1
                            if yielded > CASE_SCAN_LIMIT:
                                return
                            yield (
                                item["source"],
                                dataset_item["dataset"],
                                str(nested_case_dir.relative_to(dataset_dir)),
                                nested_case_dir,
                            )
                        continue
                    yielded += 1
                    if yielded > CASE_SCAN_LIMIT:
                        return
                    yield item["source"], dataset_item["dataset"], case_dir.name, case_dir
        elif item["nested_dataset"]:
            root: Path = item["root"]
            dataset_dirs = sorted(
                [child for child in root.iterdir() if child.is_dir() and not _is_hidden(child)],
                key=lambda path: path.name.lower(),
            )
            for dataset_dir in dataset_dirs:
                case_dirs = sorted(
                    [child for child in dataset_dir.iterdir() if child.is_dir() and not _is_hidden(child)],
                    key=lambda path: path.name.lower(),
                )
                for case_dir in case_dirs:
                    yielded += 1
                    if yielded > CASE_SCAN_LIMIT:
                        return
                    yield item["source"], dataset_dir.name, case_dir.name, case_dir
        else:
            root: Path = item["root"]
            case_dirs = sorted(
                [child for child in root.iterdir() if child.is_dir() and not _is_hidden(child)],
                key=lambda path: path.name.lower(),
            )
            for case_dir in case_dirs:
                yielded += 1
                if yielded > CASE_SCAN_LIMIT:
                    return
                yield item["source"], item["dataset"], case_dir.name, case_dir


def _refresh_case_catalog(source_filter: str = "all", dataset_filters: list[str] | None = None) -> int:
    now = datetime.utcnow()
    updated = 0
    seen_keys: set[tuple[str, str, str]] = set()
    affected_sources = {
        item["source"]
        for item in _source_roots()
        if source_filter == "all" or item["source"] == source_filter
    }
    for source, dataset, case_id, case_path in _iter_case_dirs(source_filter, dataset_filters):
        scan_path = _resolve_dicom_case_path(dataset, case_id, case_path)
        seen_keys.add((source, dataset, case_id))
        sequences, dicom_count, has_dicom = _sequence_summary(scan_path)
        full_id = f"{dataset}/{case_id}"
        existing = CviCaseCatalog.query.filter_by(source=source, dataset=dataset, case_id=case_id).first()
        if existing is None:
            existing = CviCaseCatalog(source=source, dataset=dataset, case_id=case_id, full_id=full_id)
            db.session.add(existing)
        existing.path = str(scan_path)
        existing.sequence_summary = sequences
        existing.dicom_count = dicom_count
        existing.has_dicom = has_dicom
        existing.last_seen_at = now
        existing.updated_at = now
        updated += 1

    if affected_sources:
        stale_query = CviCaseCatalog.query.filter(CviCaseCatalog.source.in_(sorted(affected_sources)))
        if dataset_filters:
            stale_query = stale_query.filter(CviCaseCatalog.dataset.in_(dataset_filters))
        stale_cases = stale_query.all()
        for stale_case in stale_cases:
            key = (stale_case.source, stale_case.dataset, stale_case.case_id)
            if key in seen_keys:
                continue
            db.session.delete(stale_case)

    db.session.commit()
    return updated


def _catalog_query(
    source: str,
    search: str,
    dataset_filters: list[str] | None = None,
    case_ids: list[str] | None = None,
):
    query = CviCaseCatalog.query
    if source != "all":
        query = query.filter(CviCaseCatalog.source == source)
    if dataset_filters:
        query = query.filter(CviCaseCatalog.dataset.in_(dataset_filters))
    if case_ids is not None:
        if not case_ids:
            return []
        case_names = [Path(str(case_id)).name for case_id in case_ids]
        query = query.filter(CviCaseCatalog.case_id.in_(case_names))
    if search:
        pattern = f"%{search}%"
        predicates = [
            CviCaseCatalog.case_id.ilike(pattern),
            CviCaseCatalog.dataset.ilike(pattern),
            CviCaseCatalog.full_id.ilike(pattern),
        ]
        for dataset, matching_case_ids in _manifest_search_matches(dataset_filters, search).items():
            predicates.append(
                and_(
                    CviCaseCatalog.dataset == dataset,
                    CviCaseCatalog.case_id.in_(sorted(matching_case_ids)),
                )
            )
        query = query.filter(or_(*predicates))
    return query


def _query_catalog(
    source: str,
    search: str,
    limit: int,
    dataset_filters: list[str] | None = None,
    case_ids: list[str] | None = None,
):
    query = _catalog_query(source, search, dataset_filters, case_ids)
    rows = query.order_by(CviCaseCatalog.dataset.asc(), CviCaseCatalog.case_id.asc()).all()
    if case_ids is not None:
        order = {Path(str(case_id)).name: index for index, case_id in enumerate(case_ids)}
        rows.sort(key=lambda row: order.get(row.case_id, len(order)))
    return rows[:limit]



def _registration_id_from_case_id(case_id: str) -> str:
    match = re.search(r"(?<!\d)(\d{10})(?!\d)", case_id or "")
    return match.group(1) if match else ""


def _public_case_code(case_id: str) -> str:
    registration_id = _registration_id_from_case_id(case_id)
    date_match = re.search(r"(?<!\d)(20\d{6})(?!\d)", case_id or "")
    if registration_id and date_match:
        return f"{registration_id}_{date_match.group(1)}"
    return re.sub(r"[A-Za-z][A-Za-z\s_-]*$", "", case_id or "").strip("_- /") or "-"


def _case_display_identity(dataset: str, case_id: str) -> dict[str, str]:
    if _canonical_dataset(dataset) == "CMR_ALL":
        registration_id = _registration_id_from_case_id(case_id)
        if registration_id:
            return {
                "primary_id_label": "登记号",
                "primary_id": registration_id,
            }
    dataset_item = _configured_dataset_item(dataset)
    if dataset_item and dataset_item.get("case_id_manifest"):
        record = _case_manifest_index(dataset_item)["case_id_to_record"].get(case_id, {})
        registration_id = str(record.get("patient_id") or "").strip()
        if registration_id:
            return {
                "primary_id_label": "登记号",
                "primary_id": registration_id,
            }
    return {
        "primary_id_label": "",
        "primary_id": "",
    }


def _catalog_payload(selection: dict, search: str, limit: int, refreshed: int = 0) -> dict:
    items = []
    case_ids = selection.get("case_ids")
    case_order = {Path(str(case_id)).name: index for index, case_id in enumerate(case_ids or [])}
    for index, case in enumerate(_query_catalog(
        selection["query_source"],
        search,
        limit,
        dataset_filters=selection.get("dataset_filters"),
        case_ids=case_ids,
    )):
        if not _user_can_access_case(case.source, case.dataset, case.case_id):
            continue
        item = case.to_dict()
        original_index = case_order.get(case.case_id, len(items))
        item["report_set_order"] = original_index + 1 if case_ids is not None else None
        item["anon_label"] = f"病例{original_index + 1:03d}" if case_ids is not None else f"病例{len(items) + 1:03d}"
        item["public_case_code"] = _public_case_code(case.case_id)
        item.update(_case_display_identity(case.dataset, case.case_id))
        items.append(item)
    return {
        "items": items,
        "count": len(items),
        "total_count": _catalog_query(
            selection["query_source"],
            search,
            dataset_filters=selection.get("dataset_filters"),
            case_ids=case_ids,
        ).count(),
        "refreshed": refreshed,
        "sources": _cvi_library_options(),
    }


def _review_target_user_id() -> int:
    if not current_user.is_authenticated:
        return 0
    requested = request.args.get("review_user_id")
    if getattr(current_user, "is_admin", False) and requested:
        try:
            user_id = int(requested)
        except ValueError:
            return int(current_user.id)
        target = User.query.get(user_id)
        if target is not None:
            return int(target.id)
    return int(current_user.id)


def _canonical_dataset(dataset: str | None) -> str:
    if not dataset:
        return ""
    return dataset.replace("new_", "", 1) if dataset.startswith("new_") else dataset


def _annotation_snapshot(user_id: int, items: list[dict]) -> dict[tuple[str, str], dict]:
    if not user_id or not items:
        return {}

    target_keys = {
        (_canonical_dataset(item.get("dataset")), str(item.get("case_id") or ""))
        for item in items
        if item.get("case_id")
    }
    if not target_keys:
        return {}

    target_case_ids = sorted({case_id for _, case_id in target_keys})
    target_datasets = sorted({
        dataset_variant
        for canonical_dataset, _ in target_keys
        for dataset_variant in ({canonical_dataset, f"new_{canonical_dataset}"} if canonical_dataset else {canonical_dataset})
        if dataset_variant
    })

    models = [
        ("functional", FunctionalAssessment),
        ("structure", StructureAssessment),
        ("lge", LGEAnalysis),
        ("imageAnalysis", ImageAnalysis),
        ("otherFindings", OtherFindings),
        ("evaluation", EvaluationResult),
    ]
    snapshot: dict[tuple[str, str], dict] = {}
    for module_key, model_class in models:
        query = model_class.query.filter_by(rater_id=user_id).filter(model_class.case_id.in_(target_case_ids))
        if target_datasets:
            query = query.filter(model_class.dataset.in_(target_datasets))
        rows = query.all()
        for row in rows:
            key = (_canonical_dataset(row.dataset), row.case_id)
            if key not in target_keys:
                continue
            item = snapshot.setdefault(
                key,
                {
                    "completed_modules": [],
                    "latest_annotation_at": None,
                },
            )
            if module_key not in item["completed_modules"]:
                item["completed_modules"].append(module_key)
            created_at = getattr(row, "created_at", None)
            created_iso = created_at.isoformat() if created_at else None
            if created_iso and (not item["latest_annotation_at"] or created_iso > item["latest_annotation_at"]):
                item["latest_annotation_at"] = created_iso
    return snapshot


def _cvi_annotation_snapshot(items: list[dict]) -> dict[int, dict]:
    study_ids = sorted({int(item["cvi_study_id"]) for item in items if item.get("cvi_study_id")})
    if not study_ids:
        return {}
    query = urllib.parse.urlencode({"study_ids": ",".join(str(study_id) for study_id in study_ids)})
    status, payload = _json_request(f"/studies/annotation-summaries?{query}")
    if status != 200:
        return {}
    raw_items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(raw_items, dict):
        return {}
    snapshot = {}
    for raw_study_id, summary in raw_items.items():
        try:
            study_id = int(raw_study_id)
        except (TypeError, ValueError):
            continue
        if isinstance(summary, dict):
            snapshot[study_id] = summary
    return snapshot


def _verify_cvi_study(study_id: int | None) -> bool:
    if not study_id:
        return False
    status, _ = _json_request(f"/studies/{study_id}")
    return status == 200


def register_cvi_workstation_routes(app) -> None:
    @app.route("/api/cvi-library/cases", methods=["GET"])
    @login_required
    def cvi_library_cases():
        source = request.args.get("source", "all")
        search = (request.args.get("search") or "").strip()
        limit = min(max(int(request.args.get("limit", 300)), 1), 1000)
        refresh = request.args.get("refresh") == "1"
        annotation_status = request.args.get("annotation_status", "all")

        selection = _parse_catalog_source_selection(source)
        if selection is None:
            available_sources = _cvi_library_options()
            if available_sources:
                selection = _parse_catalog_source_selection(available_sources[0]["value"])
                source = available_sources[0]["value"]
            if selection is None:
                return jsonify({"error": "当前账号没有可访问的病例库，请联系管理员分配。", "sources": available_sources}), 403
        if annotation_status not in {"all", "annotated", "pending"}:
            return jsonify({"error": "Unknown annotation status"}), 400

        query_source = selection["query_source"]
        existing_query = CviCaseCatalog.query
        if query_source != "all":
            existing_query = existing_query.filter_by(source=query_source)
        if selection["dataset_filters"]:
            existing_query = existing_query.filter(CviCaseCatalog.dataset.in_(selection["dataset_filters"]))
        existing_count = existing_query.count()
        refreshed = 0
        if refresh or existing_count == 0:
            refreshed = _refresh_case_catalog(selection["scan_source"], selection["dataset_filters"])
        payload = _catalog_payload(selection, search, limit, refreshed)
        payload["source"] = source
        review_user_id = _review_target_user_id()
        snapshot = _annotation_snapshot(review_user_id, payload["items"])
        cvi_snapshot = _cvi_annotation_snapshot(payload["items"])
        filtered_items = []
        for item in payload["items"]:
            summary = snapshot.get((_canonical_dataset(item["dataset"]), item["case_id"]), {})
            cvi_summary = cvi_snapshot.get(int(item["cvi_study_id"]), {}) if item.get("cvi_study_id") else {}
            completed_modules = sorted(set(summary.get("completed_modules", [])) | set(cvi_summary.get("completed_modules", [])))
            latest_values = [
                value
                for value in (summary.get("latest_annotation_at"), cvi_summary.get("latest_annotation_at"))
                if value
            ]
            annotated_frame_count = int(cvi_summary.get("annotated_frame_count") or 0)
            is_annotated = bool(completed_modules) or annotated_frame_count > 0
            item["annotation_summary"] = {
                "is_annotated": is_annotated,
                "completed_modules": completed_modules,
                "completed_count": len(completed_modules),
                "annotated_series_count": int(cvi_summary.get("annotated_series_count") or 0),
                "annotated_frame_count": annotated_frame_count,
                "latest_annotation_at": max(latest_values) if latest_values else None,
            }
            if annotation_status == "annotated" and not is_annotated:
                continue
            if annotation_status == "pending" and is_annotated:
                continue
            filtered_items.append(item)
        payload["items"] = filtered_items
        payload["count"] = len(filtered_items)
        payload["review_user_id"] = review_user_id
        if getattr(current_user, "is_admin", False):
            payload["review_users"] = [user.to_dict() for user in User.query.order_by(User.username.asc()).all()]
        else:
            payload["review_users"] = []
        return jsonify(payload)

    @app.route("/api/cvi-library/cases/<int:case_catalog_id>/import", methods=["POST"])
    @login_required
    def cvi_library_import(case_catalog_id: int):
        case = CviCaseCatalog.query.get_or_404(case_catalog_id)
        if not _user_can_access_case(case.source, case.dataset, case.case_id):
            return jsonify({"error": "这个病例尚未分配给当前账号。"}), 403
        import_path = _resolve_dicom_case_path(case.dataset, case.case_id, Path(case.path).expanduser())
        sequences, dicom_count, has_dicom = _sequence_summary(import_path)
        if has_dicom != bool(case.has_dicom) or dicom_count != int(case.dicom_count or 0) or str(import_path) != str(case.path):
            case.path = str(import_path)
            case.sequence_summary = sequences
            case.dicom_count = dicom_count
            case.has_dicom = has_dicom
            case.updated_at = datetime.utcnow()
            db.session.commit()
        if not case.has_dicom:
            return jsonify({"error": "这个病例目录里没有可导入的 DICOM 文件。"}), 400

        payload = request.get_json(silent=True) or {}
        force = bool(payload.get("force"))
        if not force and _verify_cvi_study(case.cvi_study_id):
            return jsonify({"case": case.to_dict(), "study_id": case.cvi_study_id, "reused": True})

        status, study = _json_request("/studies/import", method="POST", payload={"path": case.path})
        if status >= 400:
            return jsonify({"error": study.get("detail") or "导入 CVI 工作站失败。"}), status

        case.cvi_study_id = int(study["id"])
        case.imported_at = datetime.utcnow()
        case.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"case": case.to_dict(), "study_id": case.cvi_study_id, "study": study, "reused": False})

    @app.route("/cvi-api", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    @app.route("/cvi-api/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    @login_required
    def cvi_api_proxy(path: str = ""):
        return _proxy_cvi_api(path)

    @app.route("/cvi-workstation-app")
    @app.route("/cvi-workstation-app/")
    @app.route("/cvi-workstation-app/<path:path>")
    @login_required
    def cvi_workstation(path: str = "index.html"):
        if not CVI_WEB_DIST.is_dir():
            abort(404, "CVI workstation web bundle not found.")

        requested = path or "index.html"
        target = CVI_WEB_DIST / requested
        if target.is_file():
            return send_from_directory(CVI_WEB_DIST, requested)

        # React BrowserRouter fallback for /cvi-workstation-app/study/...
        return send_from_directory(CVI_WEB_DIST, "index.html")
