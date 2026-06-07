from flask import Flask, Response, jsonify, redirect, request
from flask_cors import CORS
from flask_login import current_user
import os
import secrets
from urllib.parse import quote
from routes import register_routes
from extensions import db, login_manager
from models import User

app = Flask(__name__)


def _load_secret_key():
    env_secret = os.environ.get('LABELSYSTEM_SECRET_KEY')
    if env_secret:
        return env_secret
    instance_dir = os.path.join(app.root_path, 'instance')
    os.makedirs(instance_dir, exist_ok=True)
    secret_path = os.path.join(instance_dir, 'secret_key')
    if os.path.exists(secret_path):
        with open(secret_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    secret = secrets.token_urlsafe(48)
    with open(secret_path, 'w', encoding='utf-8') as f:
        f.write(secret)
    try:
        os.chmod(secret_path, 0o600)
    except OSError:
        pass
    return secret


def _cors_origins():
    raw = os.environ.get(
        'LABELSYSTEM_CORS_ORIGINS',
        'http://47.108.84.221:8282,http://127.0.0.1:5173,http://localhost:5173',
    )
    return [origin.strip() for origin in raw.split(',') if origin.strip()]


# Enable CORS with credentials only for known workstation origins.
CORS(app, supports_credentials=True, resources={r"/api/*": {"origins": _cors_origins()}})

# Configuration
app.config['DATA_ROOT'] = '/home/Larry/data/CMR_SCS'
app.config['EVAL_ROOT'] = '/home/Larry/code/Ziqiu/MRIAgent/src/output'
app.config['CMR_ALL_REPORT100_CASE_LIST'] = '/home/Larry/code/Ziqiu/LabelSystem/tmp/km_replacement_strict2025_latest_correctroot_relative_paths.txt'
app.config['FUNCTIONAL_DATA_ROOT'] = '/home/Larry/code/Ziqiu/MRIAgent/data'
app.config['CVI_LIBRARY_MULTICENTER_ROOTS'] = [
    {
        'dataset': 'CMR_ALL',
        'label': '昆医附二院',
        'path': '/home/Larry/data/CMR_ALL',
    },
    {
        'dataset': 'CMR_Chendu',
        'label': '成都中心',
        'path': '/home/Larry/data/CMR_Chendu',
    },
    {
        'dataset': 'CMR_SCS',
        'label': '四川省人民医院',
        'path': '/home/Larry/data/CMR_SCS',
    },
    {
        'dataset': 'CMR_YA',
        'label': '延安医院',
        'path': '/home/Larry/data/CMR_YA/merged_files',
    },
    {
        'dataset': 'CMR_RenJi_HCM',
        'label': '上海仁济医院-HCM',
        'path': '/home/Larry/data/CMR_RenJi/HCM_extracted/给云南图像',
        'case_dir_contains_dicoms': True,
    },
    {
        'dataset': 'CMR_RenJi_MI',
        'label': '上海仁济医院-MI',
        'path': '/home/Larry/data/CMR_RenJi/心肌梗死200例_extracted/昆医二院',
        'case_dir_contains_dicoms': True,
    },
]
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.root_path, 'instance', 'labelsystem.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'connect_args': {'timeout': 30}
}
app.config['SECRET_KEY'] = _load_secret_key()
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('LABELSYSTEM_COOKIE_SECURE', '').lower() in {'1', 'true', 'yes'}

# Initialize extensions
db.init_app(app)
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def _next_login_target() -> str:
    if request.query_string:
        return request.full_path[:-1] if request.full_path.endswith('?') else request.full_path
    return request.path or '/'


def _looks_like_json_request() -> bool:
    path = request.path or ''
    if path.startswith('/api/') or path.startswith('/cvi-api'):
        return True
    accept = (request.headers.get('Accept') or '').lower()
    return 'application/json' in accept


@login_manager.unauthorized_handler
def handle_unauthorized():
    if _looks_like_json_request():
        return jsonify({'error': 'Authentication required'}), 401

    fetch_dest = (request.headers.get('Sec-Fetch-Dest') or '').lower()
    if (request.path or '').startswith('/cvi-workstation-app') and fetch_dest not in {'document', 'iframe'}:
        return Response('Authentication required', status=401, content_type='text/plain; charset=utf-8')

    next_target = quote(_next_login_target(), safe='/:?&=%')
    return redirect(f'/login?next={next_target}')


def _public_api_path(path: str) -> bool:
    return path in {
        '/api/auth/login',
        '/api/auth/register',
        '/api/auth/forgot-password',
        '/api/auth/me',
        '/api/auth/logout',
    } or path.startswith('/api/patient/')


@app.before_request
def require_authenticated_api_user():
    if not request.path.startswith('/api/'):
        return None
    if _public_api_path(request.path):
        return None
    if not current_user.is_authenticated:
        return jsonify({'error': 'Authentication required'}), 401
    if not getattr(current_user, 'is_approved', False):
        return jsonify({'error': 'Account is pending administrator approval'}), 403
    return None


def _ensure_user_schema():
    db.create_all()
    admin_users = {
        username.strip()
        for username in os.environ.get('LABELSYSTEM_ADMIN_USERS', 'pengliang,lzq,wanglujing').split(',')
        if username.strip()
    }
    with db.engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(user)").fetchall()}
        if 'is_approved' not in columns:
            conn.exec_driver_sql("ALTER TABLE user ADD COLUMN is_approved BOOLEAN NOT NULL DEFAULT 0")
            conn.exec_driver_sql("UPDATE user SET is_approved = 1")
        if 'is_admin' not in columns:
            conn.exec_driver_sql("ALTER TABLE user ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0")
        if 'requested_at' not in columns:
            conn.exec_driver_sql("ALTER TABLE user ADD COLUMN requested_at DATETIME")
            conn.exec_driver_sql("UPDATE user SET requested_at = CURRENT_TIMESTAMP WHERE requested_at IS NULL")
        if 'approved_at' not in columns:
            conn.exec_driver_sql("ALTER TABLE user ADD COLUMN approved_at DATETIME")
            conn.exec_driver_sql("UPDATE user SET approved_at = CURRENT_TIMESTAMP WHERE is_approved = 1 AND approved_at IS NULL")
        if 'last_login_at' not in columns:
            conn.exec_driver_sql("ALTER TABLE user ADD COLUMN last_login_at DATETIME")
        if 'last_logout_at' not in columns:
            conn.exec_driver_sql("ALTER TABLE user ADD COLUMN last_logout_at DATETIME")
        if 'login_count' not in columns:
            conn.exec_driver_sql("ALTER TABLE user ADD COLUMN login_count INTEGER NOT NULL DEFAULT 0")
        if 'email' not in columns:
            conn.exec_driver_sql("ALTER TABLE user ADD COLUMN email VARCHAR(255)")
        if 'password_reset_status' not in columns:
            conn.exec_driver_sql("ALTER TABLE user ADD COLUMN password_reset_status VARCHAR(32) NOT NULL DEFAULT 'none'")
        if 'password_reset_requested_at' not in columns:
            conn.exec_driver_sql("ALTER TABLE user ADD COLUMN password_reset_requested_at DATETIME")
        if 'password_reset_handled_at' not in columns:
            conn.exec_driver_sql("ALTER TABLE user ADD COLUMN password_reset_handled_at DATETIME")
        if 'password_reset_note' not in columns:
            conn.exec_driver_sql("ALTER TABLE user ADD COLUMN password_reset_note TEXT")
        conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS ix_user_email_unique ON user(email) WHERE email IS NOT NULL")
        if admin_users:
            placeholders = ','.join(['?'] * len(admin_users))
            conn.exec_driver_sql(
                f"UPDATE user SET is_admin = 1, is_approved = 1, approved_at = COALESCE(approved_at, CURRENT_TIMESTAMP) WHERE username IN ({placeholders})",
                tuple(admin_users),
            )

        eval_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(evaluation_result)").fetchall()}
        if eval_columns and 'dimension_scores' not in eval_columns:
            conn.exec_driver_sql("ALTER TABLE evaluation_result ADD COLUMN dimension_scores TEXT")

# Register Hospital Browser Blueprint
from hospital_browser.routes import hospital_browser_bp
app.register_blueprint(hospital_browser_bp, url_prefix='/api/hospital-browser')

from cardio_showcase import cardio_showcase_bp
app.register_blueprint(cardio_showcase_bp)

register_routes(app)

from cvi_workstation import register_cvi_workstation_routes
register_cvi_workstation_routes(app)

from function_qc import register_function_qc_routes
register_function_qc_routes(app)

if __name__ == '__main__':
    with app.app_context():
        _ensure_user_schema()
    debug_enabled = os.environ.get('LABELSYSTEM_DEBUG', '').lower() in {'1', 'true', 'yes'}
    app.run(debug=debug_enabled, port=5000, use_reloader=False, threaded=True)
