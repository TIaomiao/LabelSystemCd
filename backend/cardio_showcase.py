from __future__ import annotations

import html
import json
import os
from pathlib import Path

import urllib.error
import urllib.parse
import urllib.request

from flask import Blueprint, Response, current_app, jsonify, request, send_file
from flask_login import current_user


SHOWCASE_DATA_ROOT = Path(os.environ.get("LABELSYSTEM_SHOWCASE_DATA_ROOT", "/home/Larry/data/CMR_ALL")).resolve()
SHOWCASE_OUTPUT_ROOT = Path("/home/Larry/code/Ziqiu/MRIAgent/src/output/CMR_ALL").resolve()
SHOWCASE_WEB_ORIGIN = os.environ.get("LABELSYSTEM_SHOWCASE_WEB_ORIGIN", "http://127.0.0.1:3015").rstrip("/")
SHOWCASE_PROXY_HEADERS = {
    "connection",
    "content-length",
    "host",
    "transfer-encoding",
}
SHOWCASE_WEB_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
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
