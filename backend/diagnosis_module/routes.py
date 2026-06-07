
import sys
import os
import json
import queue
import shutil
import zipfile
import tarfile
import hashlib
import logging
import traceback
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Generator

from flask import Blueprint, request, jsonify, Response, send_file, current_app
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

# 导入执行器
from .executor import DiagnosisExecutor
from .event_types import StreamEvent, EventType
from .file_manager import FileManager
from .report_generator import ReportHTMLGenerator

# 创建蓝图
diagnosis_bp = Blueprint('diagnosis', __name__)

logger = logging.getLogger(__name__)
preview_attempts = {}
ALLOWED_PREVIEW_ORIGINS = {
    'http://47.108.84.221:8282',
    'http://127.0.0.1:5173',
    'http://localhost:5173',
    'http://127.0.0.1:5000',
    'http://localhost:5000',
}

# 初始化文件和报告管理器 (Lazy initialization recommended in Flask but doing here for simplicity)
# We need to set paths relative to current_app but we are outside app context here.
# So we will initialize them inside routes or functions.

# === 工具函数 ===

def get_base_paths():
    """Get paths from current app config"""
    # Assuming config keys, fallback to defaults relative to instance path or root
    base_dir = Path(current_app.root_path).parent
    # Use config if available
    data_base = Path(current_app.config.get('DATA_ROOT', base_dir / "data"))
    output_base = Path(current_app.config.get('OUTPUT_ROOT', base_dir / "src" / "output"))
    
    # Ensure directories exist
    data_base.mkdir(parents=True, exist_ok=True)
    output_base.mkdir(parents=True, exist_ok=True)
    
    return data_base, output_base

def get_time_str() -> str:
    """获取时间戳"""
    utc_now = datetime.now(timezone.utc)
    now = utc_now.astimezone(timezone(timedelta(hours=8)))
    return now.strftime("%Y-%m-%d %H:%M:%S")


def _origin_from_url(value: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(value or '')
    if not parsed.scheme or not parsed.netloc:
        return ''
    return f"{parsed.scheme}://{parsed.netloc}"


def _allowed_preview_origins() -> set[str]:
    configured = {
        origin.strip().rstrip('/')
        for origin in os.environ.get('LABELSYSTEM_CORS_ORIGINS', '').split(',')
        if origin.strip()
    }
    return ALLOWED_PREVIEW_ORIGINS | configured


def _viewer_preview_request() -> bool:
    allowed = _allowed_preview_origins()
    referer_origin = _origin_from_url(request.headers.get('Referer', ''))
    origin = request.headers.get('Origin', '').rstrip('/')
    if referer_origin in allowed or origin in allowed:
        return True
    fetch_site = request.headers.get('Sec-Fetch-Site', '')
    fetch_dest = request.headers.get('Sec-Fetch-Dest', '')
    if fetch_site in {'same-origin', 'same-site'} and fetch_dest in {'image', 'empty'}:
        return True
    if request.remote_addr in {'127.0.0.1', '::1'}:
        return True
    return False


def _check_preview_rate(limit: int = 600, window_seconds: int = 60) -> bool:
    now = datetime.now(timezone.utc).timestamp()
    user_part = str(getattr(current_user, 'id', 'anonymous')) if current_user.is_authenticated else request.remote_addr or 'unknown'
    key = ('cardiac-preview', user_part)
    attempts = [ts for ts in preview_attempts.get(key, []) if now - ts < window_seconds]
    if len(attempts) >= limit:
        preview_attempts[key] = attempts
        return False
    attempts.append(now)
    preview_attempts[key] = attempts
    return True


def _secure_preview_response(response):
    response.headers['Cache-Control'] = 'no-store, private, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Robots-Tag'] = 'noindex, noarchive, nosnippet'
    response.headers['Accept-Ranges'] = 'none'
    response.headers['Content-Disposition'] = 'inline; filename="preview.png"'
    return response


def calculate_file_hash_id(file_path: Path) -> Tuple[str, str]:
    """
    计算文件 SHA256，并截取转换为 10 位数字 ID
    返回: (10位ID, 完整Hash)
    """
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)

    hex_digest = sha256_hash.hexdigest()
    int_val = int(hex_digest, 16)
    short_id = int_val % (10**10)
    return f"{short_id:010d}", hex_digest


def validate_structure(target_dir: Path) -> Tuple[bool, str]:
    """
    检查解压后的目录结构是否符合预期
    """
    required_dirs = ["4CH", "LGE=15-22", "SAX"]
    required_files = ["patient_info.json"]

    for d in required_dirs:
        if not (target_dir / d).is_dir():
            return False, f"Missing directory: {d}"

    for f in required_files:
        if not (target_dir / f).is_file():
            return False, f"Missing file: {f}"

    return True, "Valid"


def find_patient_info_dir(search_dir: Path) -> Path:
    """
    递归搜索 patient_info.json 所在的目录。
    返回包含 patient_info.json 和必要目录结构的最上层目录。
    如果没找到，返回 search_dir 本身。
    """
    # 首先检查当前目录是否有 patient_info.json
    if (search_dir / "patient_info.json").exists():
        return search_dir

    # 递归搜索子目录
    for item in search_dir.iterdir():
        if item.is_dir() and not item.name.startswith(".") and item.name != "__MACOSX":
            result = find_patient_info_dir(item)
            if result != item:  # 找到了
                return result
            # 检查这个子目录是否包含 patient_info.json
            if (item / "patient_info.json").exists():
                return item

    # 没找到，返回原始目录
    return search_dir


def flatten_directory(target_dir: Path):
    """
    智能展平目录结构。
    定位 patient_info.json，并将包含它的目录层内容移动到 target_dir。
    支持任意深度的嵌套。
    """
    # 忽略系统文件和缓存
    def is_ignorable(path: Path) -> bool:
        return path.name.startswith(".") or path.name == "__MACOSX"

    # 找到 patient_info.json 所在的目录
    patient_info_dir = find_patient_info_dir(target_dir)

    # 如果找到的目录就是 target_dir，说明已经在正确的位置
    if patient_info_dir == target_dir:
        return

    # 需要将 patient_info_dir 中的内容移到 target_dir
    # 先把 target_dir 中的所有东西删除（除了要保留的）
    for item in list(target_dir.iterdir()):
        if not is_ignorable(item):
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

    # 将 patient_info_dir 中的所有内容移到 target_dir
    for item in patient_info_dir.iterdir():
        if not is_ignorable(item):
            shutil.move(str(item), str(target_dir))

    # 清理空的中间目录
    # 从 patient_info_dir 开始逐级向上删除空目录
    current = patient_info_dir
    while current != target_dir:
        parent = current.parent
        try:
            if len(list(current.iterdir())) == 0:
                current.rmdir()
            current = parent
        except OSError:
            break


# === API 端点 ===

@diagnosis_bp.route("/upload", methods=["POST"])
def upload_patient_data():
    """
    上传患者数据（压缩包）
    """
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    filename = file.filename.lower()
    if not (filename.endswith('.zip') or filename.endswith('.tar') or filename.endswith('.tar.gz')):
        return jsonify({"error": "Only .zip, .tar, .tar.gz supported"}), 400

    DATA_BASE, OUTPUT_BASE = get_base_paths()
    temp_dir = DATA_BASE / "_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_archive = temp_dir / secure_filename(file.filename)

    try:
        file.save(str(temp_archive))

        # 计算 Hash 生成 ID，并追加时间戳，避免覆盖
        patient_id_base, full_hash = calculate_file_hash_id(temp_archive)
        timestamp_slug = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d%H%M%S")
        patient_id = f"{patient_id_base}_{timestamp_slug}"
        target_dir = DATA_BASE / patient_id
        target_dir.mkdir(parents=True, exist_ok=True)

        # 解压
        if filename.endswith('.zip'):
            with zipfile.ZipFile(temp_archive, 'r') as zip_ref:
                zip_ref.extractall(target_dir)
        else:
            with tarfile.open(temp_archive, 'r') as tar_ref:
                tar_ref.extractall(target_dir)

        # 结构扁平化
        flatten_directory(target_dir)

        # 结构校验
        is_valid, error_msg = validate_structure(target_dir)
        if not is_valid:
            shutil.rmtree(target_dir)
            if temp_archive.exists():
                os.remove(temp_archive)

            # 提供更友好的错误提示
            if "patient_info.json" in error_msg:
                error_detail = (
                    "未找到 patient_info.json 文件。"
                    "压缩包内必须包含以下文件/目录结构: "
                    "4CH/, SAX/, LGE=15-22/, patient_info.json。"
                    "如果有额外的目录层级，系统会自动去除。"
                )
            else:
                error_detail = (
                    f"文件夹结构无效: {error_msg}。"
                    f"需要包含: 4CH/, SAX/, LGE=15-22/, patient_info.json"
                )

            return jsonify({"error": error_detail}), 400

        # 保存元信息
        time_str = get_time_str()
        with open(target_dir / "meta.json", "w") as mf:
            json.dump({
                "hash": full_hash,
                "original_filename": file.filename,
                "upload_time": time_str
            }, mf, indent=4)

        if temp_archive.exists():
            os.remove(temp_archive)

        return jsonify({
            "message": "Upload successful",
            "patient_id": patient_id,
            "location": str(target_dir),
            "upload_time": time_str
        })

    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        traceback.print_exc()
        if temp_archive.exists():
            os.remove(temp_archive)
        if 'target_dir' in locals() and target_dir.exists():
            shutil.rmtree(target_dir)
        return jsonify({"error": str(e)}), 500


@diagnosis_bp.route("/diagnose", methods=["POST"])
def diagnose():
    """
    流式诊断端点
    """
    data = request.json
    if not data or 'patient_id' not in data:
        return jsonify({"error": "patient_id is required"}), 400

    patient_id = data['patient_id']
    prompt = data.get('prompt')

    DATA_BASE, _ = get_base_paths()
    
    # 检查患者数据是否存在
    patient_dir = DATA_BASE / patient_id
    if not patient_dir.exists():
        return jsonify({"error": "Patient data not found"}), 404

    # 创建执行器
    executor = DiagnosisExecutor(
        patient_id=patient_id,
        prompt=prompt,
        use_streaming=True
    )

    # 包装生成器为 Flask 响应
    def generate():
        try:
            event_generator = executor.run_diagnosis()
            for event_data in event_generator:
                # event_generator yields formatted SSE strings or we format here?
                # Looking at executor code, it likely yields strings if use_streaming=True
                # But let's verify executor implementation or assume it returns generator of strings formatted as SSE
                # Executor._run_with_streaming calls emit_event which likely yields string
                yield event_data
        except Exception as e:
            logger.error(f"Diagnosis failed: {e}")
            traceback.print_exc()
            # Try to emit error event if possible
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

    return Response(generate(), mimetype='text/event-stream')


@diagnosis_bp.route("/results/<patient_id>/list", methods=["GET"])
def get_results_list(patient_id):
    """获取结果文件列表"""
    DATA_BASE, OUTPUT_BASE = get_base_paths()
    file_manager = FileManager(OUTPUT_BASE)
    
    try:
        files = file_manager.list_results(patient_id)
        return jsonify({"files": files})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@diagnosis_bp.route("/results/<patient_id>/report", methods=["GET"])
def get_diagnosis_report(patient_id):
    """获取诊断报告 JSON"""
    DATA_BASE, OUTPUT_BASE = get_base_paths()
    file_manager = FileManager(OUTPUT_BASE)
    
    try:
        report = file_manager.get_report_json(patient_id)
        return jsonify(report)
    except FileNotFoundError:
        return jsonify({"error": "Report not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@diagnosis_bp.route("/results/<patient_id>/metrics", methods=["GET"])
def get_metrics(patient_id):
    """获取指标数据 JSON"""
    DATA_BASE, OUTPUT_BASE = get_base_paths()
    file_manager = FileManager(OUTPUT_BASE)
    
    try:
        metrics = file_manager.get_metrics_json(patient_id)
        return jsonify(metrics)
    except FileNotFoundError:
        return jsonify({"error": "Metrics not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@diagnosis_bp.route("/results/<patient_id>/log", methods=["GET"])
def get_workflow_log(patient_id):
    """获取工作流日志"""
    DATA_BASE, OUTPUT_BASE = get_base_paths()
    file_manager = FileManager(OUTPUT_BASE)
    
    try:
        log_content = file_manager.get_workflow_log(patient_id)
        return Response(log_content, mimetype='text/plain')
    except FileNotFoundError:
        return jsonify({"error": "Log not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@diagnosis_bp.route("/results/<patient_id>/download/<path:filepath>", methods=["GET"])
@login_required
def download_result_file(patient_id, filepath):
    """下载结果文件"""
    DATA_BASE, OUTPUT_BASE = get_base_paths()
    if not getattr(current_user, 'is_admin', False):
        return jsonify({"error": "Only administrators can download result files"}), 403
    
    try:
        # 安全检查
        case_root = (OUTPUT_BASE / patient_id).resolve()
        safe_path = (case_root / filepath).resolve()
        if not safe_path.exists():
            return jsonify({"error": "File not found"}), 404
            
        # 简单的路径遍历检查
        if str(safe_path) != str(case_root) and not str(safe_path).startswith(str(case_root) + os.sep):
             return jsonify({"error": "Access denied"}), 403

        return send_file(safe_path, as_attachment=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@diagnosis_bp.route("/results/<patient_id>/preview/<path:image_path>", methods=["GET"])
@login_required
def preview_image(patient_id, image_path):
    """预览图片"""
    DATA_BASE, OUTPUT_BASE = get_base_paths()
    if not _viewer_preview_request():
        return jsonify({"error": "Image access must come from the workstation viewer"}), 403
    if not _check_preview_rate():
        return jsonify({"error": "Too many image requests. Please slow down."}), 429
    
    try:
        case_root = (OUTPUT_BASE / patient_id).resolve()
        safe_path = (case_root / image_path).resolve()
        if not safe_path.exists():
            return jsonify({"error": "Image not found"}), 404
        if str(safe_path) != str(case_root) and not str(safe_path).startswith(str(case_root) + os.sep):
            return jsonify({"error": "Access denied"}), 403
            
        return _secure_preview_response(send_file(safe_path, mimetype='image/png'))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
