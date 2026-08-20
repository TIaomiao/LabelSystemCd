from __future__ import annotations

import html
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

import urllib.error
import urllib.parse
import urllib.request

from flask import Blueprint, Response, current_app, jsonify, request, send_file
from flask_login import current_user
from werkzeug.utils import secure_filename

try:
    import pydicom
except ImportError:  # pragma: no cover - production MRIAgent env includes pydicom.
    pydicom = None


SHOWCASE_DATA_ROOT = Path(os.environ.get("LABELSYSTEM_SHOWCASE_DATA_ROOT", "/home/Larry/data/CMR_ALL")).resolve()
SHOWCASE_OUTPUT_ROOT = Path("/home/Larry/code/Ziqiu/MRIAgent/src/output/CMR_ALL").resolve()
MRIAGENT_ROOT = Path("/home/Larry/code/Ziqiu/MRIAgent").resolve()
MRIAGENT_SRC_ROOT = MRIAGENT_ROOT / "src"
REPORT_UPLOAD_ROOT = MRIAGENT_ROOT / "data" / "showcase_uploads"
REPORT_OUTPUT_ROOT = MRIAGENT_ROOT / "src" / "output" / "showcase_uploads"
REPORT_SERVER_PATH_ROOTS = [
    Path(path).resolve()
    for path in os.environ.get("LABELSYSTEM_MRI_REPORT_SERVER_PATH_ROOTS", "/home/Larry/data").split(":")
    if path.strip()
]
REPORT_UPLOAD_MAX_BYTES = int(os.environ.get("LABELSYSTEM_MRI_REPORT_UPLOAD_MAX_BYTES", str(2 * 1024 * 1024 * 1024)))
REPORT_MAX_CONCURRENT_JOBS = int(os.environ.get("LABELSYSTEM_MRI_REPORT_MAX_CONCURRENT_JOBS", "1"))
SHOWCASE_WEB_ORIGIN = os.environ.get("LABELSYSTEM_SHOWCASE_WEB_ORIGIN", "http://127.0.0.1:3015").rstrip("/")
SHOWCASE_PROXY_HEADERS = {
    "connection",
    "content-length",
    "host",
    "transfer-encoding",
}
SHOWCASE_WEB_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
LOGGER = logging.getLogger(__name__)
MRI_REPORT_JOBS: dict[str, dict[str, Any]] = {}
MRI_REPORT_JOBS_LOCK = threading.Lock()
MRI_REPORT_RUN_SEMAPHORE = threading.BoundedSemaphore(max(1, REPORT_MAX_CONCURRENT_JOBS))


def _showcase_overlay() -> str:
    user_html = ""
    if getattr(current_user, "is_authenticated", False):
        username = html.escape(getattr(current_user, "username", "User"))
        admin_link = ""
        if getattr(current_user, "is_admin", False):
            admin_link = '<a class="ls-showcase-chip secondary" href="/admin/monitor">后台监控</a>'
        user_html = f"""
        <div class="ls-showcase-chip user">{username}</div>
        {admin_link}
        <button class="ls-showcase-chip secondary" type="button" id="ls-showcase-logout">退出</button>
        """
    else:
        user_html = '<a class="ls-showcase-chip secondary" href="/login">登录</a>'

    return f"""
<style>
  .ls-showcase-overlay {{
    position: fixed;
    top: 14px;
    right: 14px;
    z-index: 2147483646;
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    justify-content: flex-end;
    max-width: min(100vw - 28px, 760px);
  }}
  .ls-showcase-chip {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 40px;
    padding: 0 14px;
    border-radius: 8px;
    border: 1px solid rgba(148, 163, 184, 0.18);
    background: rgba(2, 6, 23, 0.84);
    color: #f8fafc;
    text-decoration: none;
    font: 600 14px/1 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    backdrop-filter: blur(10px);
    box-shadow: 0 10px 30px rgba(2, 6, 23, 0.24);
  }}
  .ls-showcase-chip.primary {{
    background: #a3e635;
    color: #111827;
    border-color: transparent;
  }}
  .ls-showcase-chip.user {{
    color: #cbd5e1;
    cursor: default;
  }}
  .ls-showcase-experiment-banner {{
    position: fixed;
    left: 18px;
    bottom: 18px;
    z-index: 2147483645;
    max-width: min(560px, calc(100vw - 36px));
    padding: 14px 16px;
    border-radius: 14px;
    border: 1px solid rgba(251, 191, 36, 0.28);
    background: rgba(15, 23, 42, 0.92);
    color: #f8fafc;
    font: 500 13px/1.55 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    box-shadow: 0 18px 48px rgba(2, 6, 23, 0.34);
    backdrop-filter: blur(12px);
  }}
  .ls-showcase-experiment-banner strong {{
    color: #facc15;
  }}
  .ls-showcase-experiment-banner a {{
    color: #bef264;
    font-weight: 700;
    text-decoration: none;
  }}
  @media (max-width: 720px) {{
    .ls-showcase-overlay {{
      top: auto;
      bottom: 12px;
      left: 12px;
      right: 12px;
      justify-content: center;
    }}
  }}
</style>
<script>
(function() {{
  var overlayHtml = {json.dumps(f'''
    <a class="ls-showcase-chip secondary" href="/showcase/">主页</a>
    <a class="ls-showcase-chip secondary" href="/demo">Demo</a>
    <a class="ls-showcase-chip secondary" href="/showcase/report">报告生成实验</a>
    <a class="ls-showcase-chip secondary" href="/evaluation">报告评分</a>
    <a class="ls-showcase-chip secondary" href="/vlm-demo">大模型页</a>
    <a class="ls-showcase-chip primary" href="/workstation">进入工作站</a>
    {user_html}
  ''')};

  function rewriteLinks(root) {{
    (root || document).querySelectorAll('a[href^="/"]').forEach(function(anchor) {{
      var href = anchor.getAttribute('href') || '';
      if (!href || href.startsWith('/_next') || href.startsWith('/api/')) {{
        return;
      }}
      if (href === '/') {{
        anchor.setAttribute('href', '/showcase/');
        return;
      }}
      if (href === '/demo') {{
        anchor.setAttribute('href', '/demo');
        return;
      }}
      if (href === '/report') {{
        anchor.setAttribute('href', '/showcase/report');
        return;
      }}
    }});
  }}

  var observer = new MutationObserver(function(mutations) {{
    mutations.forEach(function(mutation) {{
      mutation.addedNodes.forEach(function(node) {{
        if (node && node.nodeType === 1) {{
          rewriteLinks(node);
        }}
      }});
    }});
  }});

  function installOverlay() {{
    rewriteLinks(document);
    observer.observe(document.documentElement, {{ childList: true, subtree: true }});

    if (document.querySelector('.ls-showcase-overlay')) {{
      return;
    }}
    var overlay = document.createElement('div');
    overlay.className = 'ls-showcase-overlay';
    overlay.innerHTML = overlayHtml;
    document.body.appendChild(overlay);

    var logoutButton = document.getElementById('ls-showcase-logout');
    if (logoutButton) {{
      logoutButton.addEventListener('click', function() {{
        fetch('/api/auth/logout', {{ method: 'POST', credentials: 'include' }})
          .finally(function() {{
            window.location.reload();
          }});
      }});
    }}

    if (window.location.pathname.indexOf('/showcase/report') === 0 && !document.querySelector('.ls-showcase-experiment-banner')) {{
      var banner = document.createElement('div');
      banner.className = 'ls-showcase-experiment-banner';
      banner.innerHTML = '<strong>算法验证入口</strong>：这里用于临时上传或服务器路径 DICOM 的实验性 MRIAgent 跑通检查；正式 AI_V2 报告质量评估请进入 <a href="/evaluation">报告评分页</a>，按 AI_V2 版本独立保存评分。';
      document.body.appendChild(banner);
    }}
  }}

  window.addEventListener('load', function() {{
    window.setTimeout(installOverlay, 300);
  }}, {{ once: true }});
}})();
</script>
"""

cardio_showcase_bp = Blueprint("cardio_showcase", __name__)


def _proxy_showcase(path: str = "", *, inject_overlay: bool = True) -> Response:
    upstream_url = f"{SHOWCASE_WEB_ORIGIN}/{path.lstrip('/')}"
    if request.query_string:
        upstream_url = f"{upstream_url}?{request.query_string.decode('utf-8', errors='ignore')}"

    upstream_request = urllib.request.Request(
        upstream_url,
        method=request.method,
        headers={
            "Accept": request.headers.get("Accept", "*/*"),
            "User-Agent": request.headers.get("User-Agent", "LabelSystem-ShowcaseProxy"),
        },
    )

    try:
        with SHOWCASE_WEB_OPENER.open(upstream_request, timeout=30) as upstream_response:
            body = upstream_response.read()
            content_type = upstream_response.headers.get("Content-Type", "text/plain; charset=utf-8")

            if inject_overlay and content_type.startswith("text/html"):
                text = body.decode("utf-8", errors="ignore")
                if "</head>" in text:
                    text = text.replace("</head>", f"{_showcase_overlay()}</head>", 1)
                body = text.encode("utf-8")

            response = Response(body, status=upstream_response.status, content_type=content_type)
            for header, value in upstream_response.headers.items():
                if header.lower() in SHOWCASE_PROXY_HEADERS:
                    continue
                response.headers[header] = value
            return response
    except urllib.error.HTTPError as exc:
        return Response(exc.read(), status=exc.code, content_type=exc.headers.get("Content-Type", "text/plain; charset=utf-8"))
    except urllib.error.URLError as exc:
        current_app.logger.exception("Showcase proxy failed: %s", exc)
        return Response("Showcase service is unavailable", status=502, content_type="text/plain; charset=utf-8")


def _resolve_patient_dir(patient_id: str) -> Path | None:
    exact = SHOWCASE_DATA_ROOT / patient_id
    if exact.is_dir():
        return exact

    for item in SHOWCASE_DATA_ROOT.iterdir():
        if not item.is_dir():
            continue
        name = item.name
        if name == patient_id or name.startswith(f"{patient_id}_") or name.startswith(f"{patient_id} "):
            return item
    return None


def _resolve_output_dir(patient_id: str) -> Path | None:
    clean_id = patient_id.strip()
    for item in SHOWCASE_OUTPUT_ROOT.iterdir():
        if not item.is_dir():
            continue
        name = item.name
        if name.startswith(clean_id) or clean_id in name:
            return item
    return None


def _safe_path(root: Path, value: str) -> Path:
    candidate = (root / value).resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("invalid path")
    return candidate


def _find_files(directory: Path, root: Path) -> list[str]:
    if not directory.exists():
        return []

    files: list[str] = []
    for item in directory.rglob("*"):
        if not item.is_file():
            continue
        if item.suffix.lower() not in {".png", ".jpg", ".jpeg", ".json"}:
            continue
        files.append(str(item.relative_to(root)))
    files.sort()
    return files


def _set_mri_report_job(job_id: str, **updates: Any) -> None:
    with MRI_REPORT_JOBS_LOCK:
        job = MRI_REPORT_JOBS.setdefault(job_id, {})
        job.update(updates)
        job["updated_at"] = time.time()


def _get_mri_report_job(job_id: str) -> dict[str, Any] | None:
    with MRI_REPORT_JOBS_LOCK:
        job = MRI_REPORT_JOBS.get(job_id)
        return dict(job) if job else None


def _safe_extract_zip(archive_path: Path, target_dir: Path, max_total_bytes: int = REPORT_UPLOAD_MAX_BYTES) -> int:
    extracted_bytes = 0
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            extracted_bytes += member.file_size
            if extracted_bytes > max_total_bytes:
                raise ValueError("zip 解压后数据超过当前 2GB 限制，请先拆分后再试。")
            member_path = (target_dir / member.filename).resolve()
            if target_dir not in member_path.parents:
                raise ValueError("Invalid zip member path")
            member_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, member_path.open("wb") as dest:
                shutil.copyfileobj(source, dest)
    return extracted_bytes


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(_as_text(item) for item in value)
    return str(value)


def _detect_report_sequence_from_text(text: str) -> str | None:
    normalized = re.sub(r"[\s_\-]+", " ", text.lower()).strip()
    excluded_tokens = (
        "survey",
        "interactive",
        "localizer",
        "scout",
        "t2 stir",
        "stir",
        "black blood",
        "bb",
        "2ch",
        "2 ch",
        "two chamber",
        "3ch",
        "3 ch",
        "three chamber",
        "perfusion",
        "dyn",
        "look locker",
        "ll",
    )
    if any(keyword in normalized for keyword in excluded_tokens):
        return None
    if any(keyword in normalized for keyword in ("lge", "late gadolinium", "delayed enhancement", "delay enhancement", "psir")):
        return "LGE"
    if any(keyword in normalized for keyword in ("4ch", "4 ch", "4 chamber", "four chamber", "hla", "horizontal long axis")):
        return "4CH"
    if any(keyword in normalized for keyword in ("sax", "short axis", "shortaxis", "sa cine", "cine sa", "m2d sa")):
        return "SAX"
    if re.search(r"(^| )sa($| )", normalized):
        return "SAX"
    return None


def _detect_report_sequence(path: Path) -> str | None:
    text = " ".join(part.lower() for part in path.parts)
    return _detect_report_sequence_from_text(text)


def _read_dicom_upload_metadata(file_path: Path, staging_dir: Path) -> dict[str, Any]:
    relative_path = file_path.relative_to(staging_dir)
    path_sequence = _detect_report_sequence(relative_path)
    metadata: dict[str, Any] = {
        "path": file_path,
        "relative_path": str(relative_path),
        "series_uid": f"path:{relative_path.parent}",
        "series_number": None,
        "instance_number": None,
        "sequence": path_sequence,
        "description": "",
        "rows": None,
        "columns": None,
    }
    if pydicom is None:
        return metadata

    try:
        ds = pydicom.dcmread(str(file_path), stop_before_pixels=True, force=True)
    except Exception:
        return metadata
    if not _looks_like_dicom_dataset(ds):
        return metadata

    description_parts = [
        getattr(ds, "SeriesDescription", ""),
        getattr(ds, "ProtocolName", ""),
        getattr(ds, "SequenceName", ""),
        getattr(ds, "ImageType", ""),
    ]
    description = " ".join(_as_text(part) for part in description_parts if _as_text(part))
    metadata.update(
        {
            "series_uid": _as_text(getattr(ds, "SeriesInstanceUID", "")) or metadata["series_uid"],
            "series_number": getattr(ds, "SeriesNumber", None),
            "instance_number": getattr(ds, "InstanceNumber", None),
            "description": description,
            "rows": getattr(ds, "Rows", None),
            "columns": getattr(ds, "Columns", None),
        }
    )
    metadata["sequence"] = _detect_report_sequence_from_text(f"{description} {relative_path}") or path_sequence
    return metadata


def _is_dicom_upload_candidate(file_path: Path) -> bool:
    suffix = file_path.suffix.lower()
    if suffix == ".zip":
        return False
    if pydicom is None:
        return suffix in {".dcm", ".dicom", ".ima"}
    try:
        ds = pydicom.dcmread(str(file_path), stop_before_pixels=True, force=True)
        return _looks_like_dicom_dataset(ds)
    except Exception:
        return False


def _looks_like_dicom_dataset(dataset: Any) -> bool:
    return any(
        hasattr(dataset, name)
        for name in ("SOPInstanceUID", "SeriesInstanceUID", "StudyInstanceUID", "Modality", "Rows", "Columns")
    )


def _sort_upload_instance_value(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _is_allowed_report_server_path(path: Path) -> bool:
    resolved = path.resolve()
    return any(resolved == root or root in resolved.parents for root in REPORT_SERVER_PATH_ROOTS)


def _link_or_copy_report_dicom(source: Path, sequence_dir: Path, index: int, *, use_symlink: bool = False) -> Path:
    sequence_dir.mkdir(exist_ok=True)
    dest = sequence_dir / f"{index:05d}.dcm"
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    if use_symlink:
        dest.symlink_to(source.resolve())
    else:
        shutil.copy2(source, dest)
    return dest


def _metric_value(metrics: dict[str, Any], name: str) -> Any:
    for item in metrics.get("requested_metrics", []) or []:
        if isinstance(item, dict) and item.get("name") == name:
            return item.get("value")
    return None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _round_metric(value: Any, digits: int = 2) -> Any:
    if _is_number(value):
        return round(float(value), digits)
    return value


def _assess_mri_report_quality(metrics: dict[str, Any] | None) -> dict[str, Any]:
    if not metrics:
        return {"level": "unknown", "warnings": ["未读取到 metrics.json，无法评估自动分析质量。"]}

    warnings: list[str] = []
    raw = metrics.get("raw_measurements", {}) or {}
    sax = raw.get("sax_metrics", {}) or {}
    lv = sax.get("lv", {}) or {}
    rv = sax.get("rv", {}) or {}
    phase = sax.get("phase_assignments", {}) or {}
    all_phases = sax.get("all_phases", []) or []

    lv_edv = lv.get("EDV_ml", _metric_value(metrics, "LVEDV"))
    lv_esv = lv.get("ESV_ml", _metric_value(metrics, "LVESV"))
    lvef = lv.get("EF_percent", _metric_value(metrics, "LVEF"))
    rv_edv = rv.get("EDV_ml", _metric_value(metrics, "RVEDV"))
    rvef = rv.get("EF_percent", _metric_value(metrics, "RVEF"))
    ed_trigger = phase.get("ED_trigger")
    es_trigger = phase.get("ES_trigger")

    if len(all_phases) < 2:
        warnings.append(f"SAX 仅得到 {len(all_phases)} 个有效时相，无法可靠判定 ED/ES。")
    if ed_trigger == es_trigger:
        warnings.append(f"ED 与 ES 被判为同一触发时间（{ed_trigger}），心功能指标不可信。")
    if _is_number(lv_edv) and lv_edv < 20:
        warnings.append(f"LVEDV={lv_edv:.2f} mL 明显低于常规心脏 MRI 生理范围，疑似分割/像素间距/序列选择失败。")
    if _is_number(lv_edv) and _is_number(lv_esv) and abs(float(lv_edv) - float(lv_esv)) < 1e-3:
        warnings.append("LVEDV 与 LVESV 完全相同，说明收缩/舒张时相选择失败或分割无有效变化。")
    if _is_number(lvef) and (lvef <= 0 or lvef > 90):
        warnings.append(f"LVEF={lvef:.2f}% 超出生理可信范围，不能作为诊断依据。")
    if _is_number(rv_edv) and rv_edv == 0:
        warnings.append("RVEDV=0 mL，右室分割/测量失败。")
    if _is_number(rvef) and rvef == 0:
        warnings.append("RVEF=0%，右室功能测量失败或不可用。")

    for source in (sax, raw.get("four_ch_metrics", {}) or {}, raw.get("lge_metrics", {}) or {}):
        for warning in source.get("warnings", []) or []:
            text = str(warning).strip()
            if text and text not in warnings:
                warnings.append(text)

    return {
        "level": "low" if warnings else "ok",
        "warnings": warnings,
        "key_metrics": {
            "LVEDV": _round_metric(lv_edv),
            "LVESV": _round_metric(lv_esv),
            "LVEF": _round_metric(lvef),
            "RVEDV": _round_metric(rv_edv),
            "RVEF": _round_metric(rvef),
            "ED_trigger": _round_metric(ed_trigger),
            "ES_trigger": _round_metric(es_trigger),
            "SAX_phase_count": len(all_phases),
        },
    }


def _plain_report_text(report: Any) -> str:
    if isinstance(report, dict):
        text = report.get("text")
        return text if isinstance(text, str) else ""
    return report if isinstance(report, str) else ""


def _sanitize_showcase_report(report: Any, metrics: dict[str, Any] | None, quality: dict[str, Any]) -> dict[str, Any]:
    text = _plain_report_text(report).strip()
    leaked_internal_json = any(token in text for token in ("sequence_classification", "raw_measurements", "requested_metrics"))
    low_quality = quality.get("level") == "low"

    if low_quality or leaked_internal_json or not text:
        key = quality.get("key_metrics", {}) or {}
        warning_lines = "\n".join(f"- {warning}" for warning in (quality.get("warnings") or []))
        metric_lines = "\n".join(
            f"- {name}: {value}"
            for name, value in key.items()
            if value is not None
        )
        reason = "自动测量质量低，暂不生成诊断结论。" if low_quality else "报告生成接口返回异常，已拦截内部调试内容。"
        return {
            "text": (
                "# CMR 自动分析质量控制结果\n\n"
                "## 结论\n"
                f"{reason}\n\n"
                "## 关键指标快照\n"
                f"{metric_lines or '- 暂无可用关键指标。'}\n\n"
                "## 需要人工复核的问题\n"
                f"{warning_lines or '- 暂无明确质量警告。'}\n\n"
                "## 下一步\n"
                "请回到原始 DICOM/工作站中复核 SAX stack、ED/ES 时相、分割轮廓和 LGE 对齐结果；在这些结果可信前，不应把本次自动输出作为正式诊断报告。"
            ),
            "quality": quality,
            "suppressed_raw_report": True,
        }

    if isinstance(report, dict):
        clean = dict(report)
        clean["quality"] = quality
        return clean
    return {"text": text, "quality": quality}


def _finalize_report_case_from_dicoms(
    *,
    patient_id: str,
    patient_dir: Path,
    dicom_files: list[Path],
    metadata_root: Path,
    prompt: str,
    source_mode: str,
    use_symlink: bool = False,
) -> tuple[str, Path, dict[str, Any]]:
    if not dicom_files:
        raise ValueError("未发现 DICOM 文件，请上传完整 DICOM 文件夹或选择服务器病例根目录。")

    series_groups: dict[str, dict[str, Any]] = {}
    for file_path in dicom_files:
        metadata = _read_dicom_upload_metadata(file_path, metadata_root)
        group = series_groups.setdefault(
            metadata["series_uid"],
            {
                "series_uid": metadata["series_uid"],
                "sequence": metadata["sequence"],
                "description": metadata["description"],
                "series_number": metadata["series_number"],
                "rows": metadata["rows"],
                "columns": metadata["columns"],
                "files": [],
            },
        )
        group["files"].append(metadata)

    selected_groups: dict[str, dict[str, Any]] = {}
    for group in series_groups.values():
        sequence = group["sequence"]
        if sequence is None:
            continue
        current = selected_groups.get(sequence)
        if current is None or len(group["files"]) > len(current["files"]):
            selected_groups[sequence] = group

    copied_counts: dict[str, int] = {}
    selected_series: list[dict[str, Any]] = []
    for sequence in ("SAX", "4CH", "LGE"):
        group = selected_groups.get(sequence)
        if not group:
            continue
        files = sorted(
            group["files"],
            key=lambda item: (
                item["instance_number"] is None,
                _sort_upload_instance_value(item["instance_number"]),
                item["relative_path"],
            ),
        )
        sequence_dir = patient_dir / sequence
        for index, item in enumerate(files, start=1):
            _link_or_copy_report_dicom(item["path"], sequence_dir, index, use_symlink=use_symlink)
        copied_counts[sequence] = len(files)
        selected_series.append(
            {
                "sequence": sequence,
                "files": len(files),
                "series_number": group.get("series_number"),
                "description": group.get("description") or "",
                "matrix": f"{group.get('rows') or '?'}x{group.get('columns') or '?'}",
            }
        )

    required_sequences = {"SAX", "4CH", "LGE"}
    missing_sequences = sorted(required_sequences - set(copied_counts))
    if missing_sequences:
        detected_descriptions = sorted(
            {
                str(group.get("description") or group.get("series_uid") or "").strip()[:120]
                for group in series_groups.values()
                if group.get("description") or group.get("series_uid")
            }
        )
        detail = "；".join(item for item in detected_descriptions[:8] if item)
        raise ValueError(
            "上传数据不完整，未同时识别到 SAX、4CH、LGE。"
            f"缺少：{', '.join(missing_sequences)}。"
            f"当前检测到 {len(dicom_files)} 个 DICOM、{len(series_groups)} 个 Series。"
            + (f" 主要序列：{detail}" if detail else "")
        )

    patient_info = {
        "patient_id": patient_id,
        "imaging_goal": prompt or "请基于上传的心脏 MRI DICOM 序列生成结构化 CMR 诊断报告。",
        "metadata_source": source_mode,
    }
    (patient_dir / "patient_info.json").write_text(
        json.dumps(patient_info, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    input_summary = {
        "patient_id": patient_id,
        "case_dir": patient_dir.name,
        "sequences": sorted(copied_counts),
        "copied_counts": copied_counts,
        "uploaded_dicom_files": len(dicom_files),
        "detected_series": len(series_groups),
        "selected_series": selected_series,
        "header_grouping": pydicom is not None,
        "source_mode": source_mode,
        "linked_dicoms": use_symlink,
    }
    return patient_id, patient_dir, input_summary


def _prepare_report_case(job_id: str, uploaded_files: list[Any], prompt: str) -> tuple[str, Path, dict[str, Any]]:
    REPORT_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    REPORT_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    patient_id = f"upload_{job_id}"
    patient_dir = REPORT_UPLOAD_ROOT / patient_id
    if patient_dir.exists():
        shutil.rmtree(patient_dir)
    patient_dir.mkdir(parents=True, exist_ok=True)

    staging_dir = patient_dir / "_staging"
    staging_dir.mkdir(parents=True, exist_ok=True)

    allowed_suffixes = {"", ".dcm", ".dicom", ".ima", ".zip"}
    saved_count = 0
    total_bytes = 0
    for uploaded in uploaded_files:
        original_name = secure_filename(uploaded.filename or "upload.dcm")
        if not original_name:
            original_name = f"upload_{saved_count}.dcm"
        suffix = Path(original_name).suffix.lower()
        if suffix not in allowed_suffixes:
            continue
        target = staging_dir / f"{saved_count:04d}_{original_name}"
        uploaded.save(target)
        total_bytes += target.stat().st_size
        if total_bytes > REPORT_UPLOAD_MAX_BYTES:
            raise ValueError("上传数据超过当前 2GB 限制，请先压缩或拆分后再试。")
        saved_count += 1
        if suffix == ".zip":
            total_bytes += _safe_extract_zip(target, staging_dir / f"{target.stem}_unzipped", REPORT_UPLOAD_MAX_BYTES)
            if total_bytes > REPORT_UPLOAD_MAX_BYTES:
                raise ValueError("上传数据解压后超过当前 2GB 限制，请先压缩或拆分后再试。")

    dicom_files = sorted(p for p in staging_dir.rglob("*") if p.is_file() and _is_dicom_upload_candidate(p))
    result = _finalize_report_case_from_dicoms(
        patient_id=patient_id,
        patient_dir=patient_dir,
        dicom_files=dicom_files,
        metadata_root=staging_dir,
        prompt=prompt,
        source_mode="showcase_upload",
        use_symlink=False,
    )
    shutil.rmtree(staging_dir, ignore_errors=True)
    return result


def _prepare_report_case_from_server_path(job_id: str, server_path: str, prompt: str) -> tuple[str, Path, dict[str, Any]]:
    source_dir = Path(server_path).expanduser().resolve()
    if not _is_allowed_report_server_path(source_dir):
        raise ValueError("服务器路径不在允许范围内；当前仅允许 /home/Larry/data 下的病例目录。")
    if not source_dir.is_dir():
        raise ValueError("服务器路径不存在或不是目录。")

    REPORT_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    REPORT_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    patient_id = f"server_{job_id}"
    patient_dir = REPORT_UPLOAD_ROOT / patient_id
    if patient_dir.exists():
        shutil.rmtree(patient_dir)
    patient_dir.mkdir(parents=True, exist_ok=True)

    dicom_files = sorted(p for p in source_dir.rglob("*") if p.is_file() and _is_dicom_upload_candidate(p))
    patient_id, patient_dir, input_summary = _finalize_report_case_from_dicoms(
        patient_id=patient_id,
        patient_dir=patient_dir,
        dicom_files=dicom_files,
        metadata_root=source_dir,
        prompt=prompt,
        source_mode="server_path",
        use_symlink=True,
    )
    input_summary["server_path"] = str(source_dir)
    return patient_id, patient_dir, input_summary


def _run_mri_report_job(job_id: str, patient_id: str) -> None:
    _set_mri_report_job(job_id, status="queued", message="任务已进入受控队列，等待 MRIAgent 空闲。")
    output_dir = REPORT_OUTPUT_ROOT
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(MRIAGENT_SRC_ROOT / "main.py"),
        "--input-path",
        str(REPORT_UPLOAD_ROOT),
        "--patient-id",
        patient_id,
        "--output-path",
        str(output_dir),
        "--lge-mode",
        "gemini",
        "--threads",
        "1",
    ]
    env = os.environ.copy()
    env.setdefault("TOKENIZERS_PARALLELISM", "false")
    env.setdefault("CUDA_DEVICE_ID", "0")

    acquired = False
    try:
        MRI_REPORT_RUN_SEMAPHORE.acquire()
        acquired = True
        _set_mri_report_job(job_id, status="running", message="MRIAgent 正在处理 DICOM 并生成报告。")
        process = subprocess.run(
            cmd,
            cwd=str(MRIAGENT_SRC_ROOT),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=1800,
            check=False,
        )
        report_path = output_dir / patient_id / "report.json"
        metrics_path = output_dir / patient_id / "metrics.json"
        if process.returncode != 0:
            _set_mri_report_job(
                job_id,
                status="failed",
                message=f"MRIAgent 进程失败，退出码 {process.returncode}。",
                log_tail="\n".join((process.stdout or "").splitlines()[-40:]),
            )
            return
        if not report_path.exists():
            _set_mri_report_job(
                job_id,
                status="failed",
                message="MRIAgent 已结束，但未生成 report.json。",
                log_tail="\n".join((process.stdout or "").splitlines()[-40:]),
            )
            return
        report = json.loads(report_path.read_text(encoding="utf-8"))
        metrics = None
        if metrics_path.exists():
            try:
                metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                metrics = None
        quality = _assess_mri_report_quality(metrics)
        sanitized_report = _sanitize_showcase_report(report, metrics, quality)
        message = "报告生成完成。"
        if quality.get("level") == "low":
            message = "MRIAgent 已完成处理，但自动测量质量低，已拦截诊断结论并生成复核提示。"
        _set_mri_report_job(
            job_id,
            status="done",
            message=message,
            report=sanitized_report,
            metrics=metrics,
            quality=quality,
        )
    except subprocess.TimeoutExpired as exc:
        _set_mri_report_job(
            job_id,
            status="failed",
            message="MRIAgent 运行超时。",
            log_tail="\n".join((exc.stdout or "").splitlines()[-40:]) if exc.stdout else "",
        )
    except Exception as exc:
        LOGGER.exception("MRI report job failed")
        _set_mri_report_job(job_id, status="failed", message=str(exc))
    finally:
        if acquired:
            MRI_REPORT_RUN_SEMAPHORE.release()


@cardio_showcase_bp.get("/api/patient/info")
def patient_info():
    patient_id = (request.args.get("patientId") or "").strip()
    if not patient_id:
        return jsonify({"error": "Missing patientId"}), 400

    patient_dir = _resolve_patient_dir(patient_id)
    if not patient_dir:
        return jsonify({"error": "Patient not found"}), 404

    info_path = patient_dir / "patient_info.json"
    if info_path.exists():
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return jsonify({"error": "Patient info is invalid"}), 500
    else:
        info = {
            "patient_id": patient_dir.name,
            "sex": "未记录",
            "age": "未记录",
            "imaging_goal": "Demo 病例未提供 patient_info.json，使用页面内置病史作为展示文本。",
        }

    id_parts = patient_dir.name.replace(" ", "_").split("_")
    info["displayId"] = f"{id_parts[0]}_{id_parts[1]}" if len(id_parts) >= 2 else patient_id
    if "patient_name" in info:
        info["patient_name"] = "Anonymous Demo"
    return jsonify(info)


@cardio_showcase_bp.get("/api/patient/images")
def patient_images():
    patient_id = (request.args.get("patientId") or "").strip()
    image_type = (request.args.get("type") or "").strip().lower()
    image_index = request.args.get("index")
    if not patient_id or not image_type:
        return jsonify({"error": "Missing patientId or type"}), 400

    patient_dir = _resolve_patient_dir(patient_id)
    if not patient_dir:
        return jsonify({"error": "Patient not found"}), 404

    aliases = {
        "4ch": ["4ch"],
        "sax": ["sax", "sa"],
        "lge": ["lge"],
    }
    candidates = aliases.get(image_type, [image_type])
    target_dir = None
    for item in patient_dir.iterdir():
        if not item.is_dir():
            continue
        normalized = item.name.lower()
        if any(candidate in normalized for candidate in candidates):
            target_dir = item
            break

    if not target_dir:
        return jsonify({"error": f"Image type {image_type} not found"}), 404

    files = sorted(
        [
            item.name
            for item in target_dir.iterdir()
            if item.is_file() and (item.suffix.lower() == ".dcm" or "img" in item.name.lower())
        ]
    )
    if not files:
        return jsonify({"error": "No images found"}), 404

    if image_index is None:
        return jsonify({"count": len(files), "files": files, "type": target_dir.name})

    try:
        idx = int(image_index)
    except ValueError:
        return jsonify({"error": "Invalid index"}), 400
    if idx < 0 or idx >= len(files):
        return jsonify({"error": "Invalid index"}), 400

    return send_file(target_dir / files[idx], mimetype="application/dicom", max_age=3600)


@cardio_showcase_bp.get("/api/patient/results")
def patient_results():
    patient_id = (request.args.get("patientId") or "").strip()
    step = (request.args.get("step") or "").strip()
    if not patient_id or not step:
        return jsonify({"error": "Missing parameters"}), 400

    patient_dir = _resolve_output_dir(patient_id)
    if not patient_dir:
        return jsonify({"error": "Patient not found"}), 404

    step_map = {
        "sax_seg": "key_frames/SAX/overlays",
        "4ch_seg": "key_frames/4CH/overlays",
        "lge": "LGE_Analysis",
        "measurements": "measurements/SAX_ED",
        "measurements_4ch": "measurements/4CH_ES",
        "previews": "previews",
    }
    target_subdir = step_map.get(step)
    if not target_subdir:
        return jsonify({"error": "Invalid step"}), 400

    files = _find_files(patient_dir / target_subdir, SHOWCASE_OUTPUT_ROOT)
    return jsonify({"files": files})


@cardio_showcase_bp.get("/api/patient/files")
def patient_files():
    relative_path = (request.args.get("path") or "").strip()
    if not relative_path:
        return Response("Path is required", status=400, content_type="text/plain; charset=utf-8")

    try:
        full_path = _safe_path(SHOWCASE_OUTPUT_ROOT, relative_path)
    except ValueError:
        return Response("Invalid path", status=403, content_type="text/plain; charset=utf-8")

    if not full_path.exists() or not full_path.is_file():
        return Response("File not found", status=404, content_type="text/plain; charset=utf-8")

    suffix = full_path.suffix.lower()
    mimetype = "application/octet-stream"
    if suffix == ".png":
        mimetype = "image/png"
    elif suffix in {".jpg", ".jpeg"}:
        mimetype = "image/jpeg"
    elif suffix == ".json":
        mimetype = "application/json"

    return send_file(full_path, mimetype=mimetype, max_age=3600)


@cardio_showcase_bp.post("/api/mri-report/jobs")
def create_mri_report_job():
    prompt = (request.form.get("prompt") or "").strip()
    server_path = (request.form.get("server_path") or "").strip()
    job_id = uuid.uuid4().hex[:12]
    if server_path:
        try:
            patient_id, patient_dir, input_summary = _prepare_report_case_from_server_path(job_id, server_path, prompt)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            current_app.logger.exception("Failed to prepare MRI report server path")
            return jsonify({"error": f"服务器路径处理失败: {exc}"}), 500
        _set_mri_report_job(
            job_id,
            status="queued",
            message="服务器病例目录已接收，等待 MRIAgent 处理。",
            patient_id=patient_id,
            created_at=time.time(),
            input_summary=input_summary,
        )
        thread = threading.Thread(target=_run_mri_report_job, args=(job_id, patient_id), daemon=True)
        thread.start()
        return jsonify({"job_id": job_id, "patient_id": patient_id, "status": "queued", "input_summary": input_summary})

    uploaded_files = request.files.getlist("files")
    if not uploaded_files:
        single_file = request.files.get("file")
        uploaded_files = [single_file] if single_file else []
    if not uploaded_files:
        return jsonify({"error": "请上传 DICOM 文件或 zip 包。"}), 400

    try:
        patient_id, patient_dir, input_summary = _prepare_report_case(job_id, uploaded_files, prompt)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        current_app.logger.exception("Failed to prepare MRI report upload")
        return jsonify({"error": f"上传处理失败: {exc}"}), 500

    _set_mri_report_job(
        job_id,
        status="queued",
        message="数据已接收，等待 MRIAgent 处理。",
        patient_id=patient_id,
        created_at=time.time(),
        input_summary=input_summary,
    )

    thread = threading.Thread(target=_run_mri_report_job, args=(job_id, patient_id), daemon=True)
    thread.start()
    return jsonify({"job_id": job_id, "patient_id": patient_id, "status": "queued", "input_summary": input_summary})


@cardio_showcase_bp.get("/api/mri-report/jobs/<job_id>")
def get_mri_report_job(job_id: str):
    job = _get_mri_report_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@cardio_showcase_bp.route("/showcase", defaults={"path": ""})
@cardio_showcase_bp.route("/showcase/", defaults={"path": ""})
@cardio_showcase_bp.route("/showcase/<path:path>")
def showcase_proxy(path: str):
    normalized = path.strip("/")
    return _proxy_showcase(path, inject_overlay=normalized != "demo")


@cardio_showcase_bp.route("/demo")
@cardio_showcase_bp.route("/demo/")
def showcase_demo_proxy():
    return _proxy_showcase("demo", inject_overlay=False)


@cardio_showcase_bp.route("/_next/<path:path>")
def showcase_next_assets(path: str):
    return _proxy_showcase(f"_next/{path}")
