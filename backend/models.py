import os
import torch
import torch.nn as nn
from extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from sqlalchemy import CheckConstraint, DDL, event

# 配置 HuggingFace 镜像源（解决网络连接问题）
# 方法1: 设置环境变量（如果支持）
if "HF_ENDPOINT" not in os.environ:
    # 尝试使用国内镜像
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
    
# 方法2: 配置 huggingface_hub（如果已安装）
try:
    from huggingface_hub import configure_hf_hub
    # 设置镜像端点
    configure_hf_hub(endpoint="https://hf-mirror.com")
except ImportError:
    pass  # huggingface_hub 可能未安装，跳过
except Exception:
    pass  # 配置失败，使用默认设置

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True)
    password_hash = db.Column(db.String(128))
    is_approved = db.Column(db.Boolean, default=False, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime)
    last_login_at = db.Column(db.DateTime)
    last_logout_at = db.Column(db.DateTime)
    login_count = db.Column(db.Integer, default=0, nullable=False)
    password_reset_status = db.Column(db.String(32), default='none', nullable=False)
    password_reset_requested_at = db.Column(db.DateTime)
    password_reset_handled_at = db.Column(db.DateTime)
    password_reset_note = db.Column(db.Text)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):
        return bool(self.is_approved)
    
    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'is_approved': bool(self.is_approved),
            'is_admin': bool(self.is_admin),
        }

    def to_admin_dict(self):
        return {
            **self.to_dict(),
            'requested_at': self.requested_at.isoformat() if self.requested_at else None,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'last_login_at': self.last_login_at.isoformat() if self.last_login_at else None,
            'last_logout_at': self.last_logout_at.isoformat() if self.last_logout_at else None,
            'login_count': self.login_count or 0,
            'password_reset_status': self.password_reset_status or 'none',
            'password_reset_requested_at': self.password_reset_requested_at.isoformat() if self.password_reset_requested_at else None,
            'password_reset_handled_at': self.password_reset_handled_at.isoformat() if self.password_reset_handled_at else None,
            'password_reset_note': self.password_reset_note,
        }


class UserMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    subject = db.Column(db.String(200), default='', nullable=False)
    body = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(32), default='direct', nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    read_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    sender = db.relationship('User', foreign_keys=[sender_id], backref=db.backref('sent_messages', lazy=True))
    recipient = db.relationship('User', foreign_keys=[recipient_id], backref=db.backref('received_messages', lazy=True))

    def to_dict(self):
        return {
            'id': self.id,
            'sender_id': self.sender_id,
            'sender_username': self.sender.username if self.sender else '系统',
            'recipient_id': self.recipient_id,
            'recipient_username': self.recipient.username if self.recipient else None,
            'subject': self.subject or '',
            'body': self.body,
            'category': self.category,
            'is_read': bool(self.is_read),
            'read_at': self.read_at.isoformat() if self.read_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

class CviCaseCatalog(db.Model):
    __table_args__ = (
        db.UniqueConstraint('source', 'dataset', 'case_id', name='uq_cvi_case_catalog_source_case'),
    )

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(50), nullable=False)
    dataset = db.Column(db.String(100), nullable=False)
    case_id = db.Column(db.String(200), nullable=False)
    full_id = db.Column(db.String(320), nullable=False)
    path = db.Column(db.Text, nullable=False)
    sequence_summary = db.Column(db.JSON)
    dicom_count = db.Column(db.Integer, default=0)
    has_dicom = db.Column(db.Boolean, default=False)
    cvi_study_id = db.Column(db.Integer)
    imported_at = db.Column(db.DateTime)
    last_seen_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'source': self.source,
            'dataset': self.dataset,
            'case_id': self.case_id,
            'full_id': self.full_id,
            'sequence_summary': self.sequence_summary or [],
            'dicom_count': self.dicom_count or 0,
            'has_dicom': bool(self.has_dicom),
            'cvi_study_id': self.cvi_study_id,
            'imported_at': self.imported_at.isoformat() if self.imported_at else None,
            'last_seen_at': self.last_seen_at.isoformat() if self.last_seen_at else None,
        }


class CaseAssignment(db.Model):
    __table_args__ = (
        db.UniqueConstraint('namespace', 'dataset', 'case_id', 'user_id', name='uq_case_assignment_target_user'),
    )

    id = db.Column(db.Integer, primary_key=True)
    namespace = db.Column(db.String(50), nullable=False, default='functional')
    dataset = db.Column(db.String(100), nullable=False, default='')
    case_id = db.Column(db.String(200), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    active = db.Column(db.Boolean, default=True, nullable=False)

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('case_assignments', lazy=True))
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    def to_dict(self):
        return {
            'id': self.id,
            'namespace': self.namespace,
            'dataset': self.dataset,
            'case_id': self.case_id,
            'user_id': self.user_id,
            'username': self.user.username if self.user else None,
            'created_by': self.created_by.username if self.created_by else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'active': bool(self.active),
        }


class DatasetAccessGrant(db.Model):
    """Persistent whole-dataset access, separate from per-case work assignment."""

    __table_args__ = (
        db.UniqueConstraint(
            'namespace',
            'dataset',
            'user_id',
            name='uq_dataset_access_grant_target_user',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    namespace = db.Column(db.String(50), nullable=False, default='functional')
    dataset = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)

    user = db.relationship(
        'User',
        foreign_keys=[user_id],
        backref=db.backref('dataset_access_grants', lazy=True),
    )
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    def to_dict(self):
        return {
            'id': self.id,
            'namespace': self.namespace,
            'dataset': self.dataset,
            'user_id': self.user_id,
            'username': self.user.username if self.user else None,
            'created_by': self.created_by.username if self.created_by else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'active': bool(self.active),
        }


class DatasetAccessAudit(db.Model):
    """Append-only history for whole-dataset permission changes."""

    __table_args__ = (
        CheckConstraint("action IN ('grant', 'revoke')", name='ck_dataset_access_audit_action'),
        db.UniqueConstraint(
            'batch_id',
            'namespace',
            'dataset',
            'target_user_id',
            name='uq_dataset_access_audit_batch_target',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.String(36), nullable=False, index=True)
    namespace = db.Column(db.String(50), nullable=False)
    dataset = db.Column(db.String(100), nullable=False)
    dataset_label = db.Column(db.String(200), nullable=False)
    target_user_id = db.Column(db.Integer, nullable=False)
    target_username = db.Column(db.String(64), nullable=False)
    action = db.Column(db.String(16), nullable=False)
    actor_user_id = db.Column(db.Integer, nullable=False)
    actor_username = db.Column(db.String(64), nullable=False)
    request_ip = db.Column(db.String(64), nullable=False, default='')
    release_version = db.Column(db.String(64), nullable=False, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'batch_id': self.batch_id,
            'namespace': self.namespace,
            'dataset': self.dataset,
            'dataset_label': self.dataset_label,
            'target_user_id': self.target_user_id,
            'target_username': self.target_username,
            'action': self.action,
            'actor_user_id': self.actor_user_id,
            'actor_username': self.actor_username,
            'request_ip': self.request_ip,
            'release_version': self.release_version,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


event.listen(
    DatasetAccessAudit.__table__,
    'after_create',
    DDL(
        """
        CREATE TRIGGER IF NOT EXISTS dataset_access_audit_no_update
        BEFORE UPDATE ON dataset_access_audit
        BEGIN
            SELECT RAISE(ABORT, 'dataset_access_audit is append-only');
        END
        """
    ).execute_if(dialect='sqlite'),
)
event.listen(
    DatasetAccessAudit.__table__,
    'after_create',
    DDL(
        """
        CREATE TRIGGER IF NOT EXISTS dataset_access_audit_no_delete
        BEFORE DELETE ON dataset_access_audit
        BEGIN
            SELECT RAISE(ABORT, 'dataset_access_audit is append-only');
        END
        """
    ).execute_if(dialect='sqlite'),
)


class MediaAccessLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    username = db.Column(db.String(64))
    kind = db.Column(db.String(50), nullable=False)
    namespace = db.Column(db.String(50), default='')
    dataset = db.Column(db.String(100), default='')
    case_id = db.Column(db.String(200), default='')
    path = db.Column(db.Text)
    status = db.Column(db.String(32), nullable=False)
    ip_address = db.Column(db.String(64))
    user_agent = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User')

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'username': self.username,
            'kind': self.kind,
            'namespace': self.namespace,
            'dataset': self.dataset,
            'case_id': self.case_id,
            'path': self.path,
            'status': self.status,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

class EvaluationResult(db.Model):
    __table_args__ = (
        db.UniqueConstraint('dataset', 'case_id', 'rater_id', name='uq_eval_result_case_rater'),
    )
    id = db.Column(db.Integer, primary_key=True)
    dataset = db.Column(db.String(100), nullable=False)
    case_id = db.Column(db.String(100), nullable=False)
    rater_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Old single score (deprecated but kept for compatibility/migration)
    score = db.Column(db.Float, nullable=True)
    
    # New Likert scales (1-5)
    score_coverage = db.Column(db.Integer)
    score_consistency = db.Column(db.Integer)
    score_hallucination = db.Column(db.Integer)
    dimension_scores = db.Column(db.JSON)
    
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    rater = db.relationship('User', backref=db.backref('evaluations', lazy=True))
    
    def to_dict(self):
        return {
            'id': self.id,
            'dataset': self.dataset,
            'case_id': self.case_id,
            'rater': self.rater.username,
            'score': self.score,
            'score_coverage': self.score_coverage,
            'score_consistency': self.score_consistency,
            'score_hallucination': self.score_hallucination,
            'dimension_scores': self.dimension_scores or {},
            'comment': self.comment,
            'created_at': self.created_at.isoformat()
        }

class FunctionalAssessment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    dataset = db.Column(db.String(100), nullable=False)
    case_id = db.Column(db.String(100), nullable=False)
    rater_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # New field for quantitative assessment (JSON)
    # Stores the comparison table: AI Value, Report Value, Consistency Judgement
    metrics_data = db.Column(db.JSON)
    
    # Left Ventricle (LV)
    lv_lvedv_increased = db.Column(db.String(50))
    lv_lvesv_increased = db.Column(db.String(50))
    lv_lvef_decreased = db.Column(db.String(50))
    lv_sv_decreased = db.Column(db.String(50))
    lv_lvedd_enlarged = db.Column(db.String(50))
    lv_ivs_thickened = db.Column(db.String(50))
    lv_lvpw_thickened = db.Column(db.String(50))
    lv_rwt_increased = db.Column(db.String(50))
    lv_si_increased = db.Column(db.String(50))
    
    # Right Ventricle (RV)
    rv_rvedv_increased = db.Column(db.String(50))
    rv_rvesv_increased = db.Column(db.String(50))
    rv_rvef_decreased = db.Column(db.String(50))
    rv_rvedd_enlarged = db.Column(db.String(50))
    rv_si_increased = db.Column(db.String(50))
    
    # Ratio
    ratio_lvrv_increased = db.Column(db.String(50))
    
    # Atrial
    la_lav_increased = db.Column(db.String(50))
    ra_rav_increased = db.Column(db.String(50))
    la_si_increased = db.Column(db.String(50))
    ra_si_increased = db.Column(db.String(50))
    la_lr_increased = db.Column(db.String(50))
    ra_lr_increased = db.Column(db.String(50))
    
    rater = db.relationship('User', backref=db.backref('functional_assessments', lazy=True))
    
    def to_dict(self):
        return {
            'id': self.id,
            'dataset': self.dataset,
            'case_id': self.case_id,
            'rater': self.rater.username,
            'created_at': self.created_at.isoformat(),
            'metrics_data': self.metrics_data,
            'answers': {
                'lv_lvedv_increased': self.lv_lvedv_increased,
                'lv_lvesv_increased': self.lv_lvesv_increased,
                'lv_lvef_decreased': self.lv_lvef_decreased,
                'lv_sv_decreased': self.lv_sv_decreased,
                'lv_lvedd_enlarged': self.lv_lvedd_enlarged,
                'lv_ivs_thickened': self.lv_ivs_thickened,
                'lv_lvpw_thickened': self.lv_lvpw_thickened,
                'lv_rwt_increased': self.lv_rwt_increased,
                'lv_si_increased': self.lv_si_increased,
                
                'rv_rvedv_increased': self.rv_rvedv_increased,
                'rv_rvesv_increased': self.rv_rvesv_increased,
                'rv_rvef_decreased': self.rv_rvef_decreased,
                'rv_rvedd_enlarged': self.rv_rvedd_enlarged,
                'rv_si_increased': self.rv_si_increased,
                
                'ratio_lvrv_increased': self.ratio_lvrv_increased,
                
                'la_lav_increased': self.la_lav_increased,
                'ra_rav_increased': self.ra_rav_increased,
                'la_si_increased': self.la_si_increased,
                'ra_si_increased': self.ra_si_increased,
                'la_lr_increased': self.la_lr_increased,
                'ra_lr_increased': self.ra_lr_increased
            }
        }

class LGEAnalysis(db.Model):
    __table_args__ = (
        db.UniqueConstraint('dataset', 'case_id', 'rater_id', name='uq_lge_analysis_case_rater'),
    )
    id = db.Column(db.Integer, primary_key=True)
    dataset = db.Column(db.String(100), nullable=False)
    case_id = db.Column(db.String(100), nullable=False)
    rater_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Left Ventricle (LV)
    lv_enhancement = db.Column(db.Boolean)  # False=None, True=Present
    lv_enhancement_boxes = db.Column(db.JSON)  # Store list of boxes: [{x, y, w, h, image_name}, ...]
    lv_enhancement_anterior_insertion = db.Column(db.Boolean)
    lv_enhancement_posterior_insertion = db.Column(db.Boolean)
    lv_distribution_pattern = db.Column(db.String(50))  # subendocardial, mid_myocardial, subepicardial
    lv_transmurality = db.Column(db.String(50))  # 0%, 1-25%, 26-50%, 51-75%, 76-100%
    lv_mvo = db.Column(db.Boolean)  # True=Present, False=Absent

    # Right Ventricle (RV)
    rv_enhancement = db.Column(db.Boolean)  # False=None, True=Present
    rv_enhancement_location = db.Column(db.String(500))  # JSON string or comma-separated (apical, septal, anterior, free_wall)
    rv_enhancement_boxes = db.Column(db.JSON)  # Store list of boxes: [{x, y, w, h, image_name}, ...]

    # Pericardium
    pericardial_enhancement = db.Column(db.Boolean)  # False=None, True=Present
    pericardial_enhancement_boxes = db.Column(db.JSON)  # Store list of boxes: [{x, y, w, h, image_name}, ...]

    # Hidden Images
    hidden_images = db.Column(db.JSON)

    rater = db.relationship('User', backref=db.backref('lge_analyses', lazy=True))

    def to_dict(self):
        return {
            'id': self.id,
            'dataset': self.dataset,
            'case_id': self.case_id,
            'rater': self.rater.username,
            'created_at': self.created_at.isoformat(),
            'answers': {
                'lv_enhancement': self.lv_enhancement,
                'lv_enhancement_boxes': self.lv_enhancement_boxes or [],
                'lv_enhancement_anterior_insertion': self.lv_enhancement_anterior_insertion,
                'lv_enhancement_posterior_insertion': self.lv_enhancement_posterior_insertion,
                'lv_distribution_pattern': self.lv_distribution_pattern,
                'lv_transmurality': self.lv_transmurality,
                'lv_mvo': self.lv_mvo,
                'rv_enhancement': self.rv_enhancement,
                'rv_enhancement_location': self.rv_enhancement_location,
                'rv_enhancement_boxes': self.rv_enhancement_boxes or [],
                'pericardial_enhancement': self.pericardial_enhancement,
                'pericardial_enhancement_boxes': self.pericardial_enhancement_boxes or [],
                'hidden_images': self.hidden_images or []
            }
        }

class ImageAnalysis(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    dataset = db.Column(db.String(100), nullable=False)
    case_id = db.Column(db.String(100), nullable=False)
    rater_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 1. Overall Image Quality
    overall_quality = db.Column(db.String(50))  # good, moderate, poor

    # 2. Artifacts Presence
    has_artifacts = db.Column(db.Boolean)

    # 3. Artifact Severity
    artifact_severity = db.Column(db.String(50))  # mild, moderate, severe

    # 3. Artifact Classification (Deprecated)
    has_banding_artifact = db.Column(db.Boolean)
    has_motion_artifact = db.Column(db.Boolean)
    has_aliasing_artifact = db.Column(db.Boolean)
    has_susceptibility_artifact = db.Column(db.Boolean)
    
    # Deprecated fields (kept for compatibility if needed, or can be removed)
    # has_respiratory_artifact = db.Column(db.Boolean)
    # has_flow_artifact = db.Column(db.Boolean)
    # has_metal_artifact = db.Column(db.Boolean)

    # Store list of boxes: [{x, y, w, h, slice_index, image_name, type}, ...]
    artifact_boxes = db.Column(db.JSON)

    rater = db.relationship('User', backref=db.backref('image_analyses', lazy=True))

    def to_dict(self):
        return {
            'id': self.id,
            'dataset': self.dataset,
            'case_id': self.case_id,
            'rater': self.rater.username,
            'created_at': self.created_at.isoformat(),
            'answers': {
                'overall_quality': self.overall_quality,
                'has_artifacts': self.has_artifacts,
                'artifact_severity': self.artifact_severity,
                'has_banding_artifact': self.has_banding_artifact,
                'has_motion_artifact': self.has_motion_artifact,
                'has_aliasing_artifact': self.has_aliasing_artifact,
                'has_susceptibility_artifact': self.has_susceptibility_artifact
            },
            'artifact_boxes': self.artifact_boxes or []
        }

class OtherFindings(db.Model):
    __table_args__ = (
        db.UniqueConstraint('dataset', 'case_id', 'rater_id', name='uq_other_findings_case_rater'),
    )
    id = db.Column(db.Integer, primary_key=True)
    dataset = db.Column(db.String(100), nullable=False)
    case_id = db.Column(db.String(100), nullable=False)
    rater_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Intramyocardial fat infiltration
    fat_infiltration_location = db.Column(db.String(255))

    # Thrombus
    thrombus_present = db.Column(db.Boolean)
    thrombus_location = db.Column(db.String(255))
    thrombus_size = db.Column(db.String(255))
    thrombus_mobility = db.Column(db.String(255))

    # Pericardial effusion
    pericardial_effusion = db.Column(db.String(50)) # trace, small, moderate, large

    # Pleural effusion
    pleural_effusion = db.Column(db.String(255))

    # Other
    other_findings_desc = db.Column(db.Text)

    rater = db.relationship('User', backref=db.backref('other_findings', lazy=True))

    def to_dict(self):
        return {
            'id': self.id,
            'dataset': self.dataset,
            'case_id': self.case_id,
            'rater': self.rater.username,
            'created_at': self.created_at.isoformat(),
            'answers': {
                'fat_infiltration_location': self.fat_infiltration_location,
                'thrombus_present': self.thrombus_present,
                'thrombus_location': self.thrombus_location,
                'thrombus_size': self.thrombus_size,
                'thrombus_mobility': self.thrombus_mobility,
                'pericardial_effusion': self.pericardial_effusion,
                'pleural_effusion': self.pleural_effusion,
                'other_findings_desc': self.other_findings_desc
            }
        }

class StructureAssessment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    dataset = db.Column(db.String(100), nullable=False)
    case_id = db.Column(db.String(100), nullable=False)
    rater_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # LV Wall Thickness
    lv_wall_thickness = db.Column(db.String(50))  # normal, thickened, thinned
    lv_thickened_type = db.Column(db.String(50))  # concentric, eccentric, asymmetric
    lv_thickened_location = db.Column(db.String(200))
    lv_thickened_max_thickness = db.Column(db.Float)
    lv_thinned_type = db.Column(db.String(50))  # diffuse, local
    lv_thinned_location = db.Column(db.String(200))
    lv_thinned_max_thickness = db.Column(db.Float)
    lv_increased_trabeculation = db.Column(db.Boolean)
    lv_outflow_obstruction = db.Column(db.Boolean)
    
    # Myocardial Motion
    lv_wall_motion = db.Column(db.String(50))  # normal, enhanced, reduced, paradoxical
    lv_enhanced_type = db.Column(db.String(50))  # diffuse, local
    lv_enhanced_location = db.Column(db.String(200))
    lv_reduced_type = db.Column(db.String(50))  # diffuse, local
    lv_reduced_location = db.Column(db.String(200))
    lv_paradoxical_location = db.Column(db.String(200))
    lv_aneurysm = db.Column(db.String(50))  # true, false, none
    
    # Valvular Morphology & Function
    valvular_stenosis = db.Column(db.JSON)  # [mitral, tricuspid, aortic]
    mitral_regurgitation = db.Column(db.String(50))  # none, mild, moderate, severe
    tricuspid_regurgitation = db.Column(db.String(50))  # none, mild, moderate, severe
    aortic_regurgitation = db.Column(db.String(50))  # none, mild, moderate, severe
    
    rater = db.relationship('User', backref=db.backref('structure_assessments', lazy=True))
    
    def to_dict(self):
        return {
            'id': self.id,
            'dataset': self.dataset,
            'case_id': self.case_id,
            'rater': self.rater.username,
            'created_at': self.created_at.isoformat(),
            'answers': {
                'lv_wall_thickness': self.lv_wall_thickness,
                'lv_thickened_type': self.lv_thickened_type,
                'lv_thickened_location': self.lv_thickened_location,
                'lv_thickened_max_thickness': self.lv_thickened_max_thickness,
                'lv_thinned_type': self.lv_thinned_type,
                'lv_thinned_location': self.lv_thinned_location,
                'lv_thinned_max_thickness': self.lv_thinned_max_thickness,
                'lv_increased_trabeculation': self.lv_increased_trabeculation,
                'lv_outflow_obstruction': self.lv_outflow_obstruction,
                
                'lv_wall_motion': self.lv_wall_motion,
                'lv_enhanced_type': self.lv_enhanced_type,
                'lv_enhanced_location': self.lv_enhanced_location,
                'lv_reduced_type': self.lv_reduced_type,
                'lv_reduced_location': self.lv_reduced_location,
                'lv_paradoxical_location': self.lv_paradoxical_location,
                'lv_aneurysm': self.lv_aneurysm,
                
                'valvular_stenosis': self.valvular_stenosis,
                'mitral_regurgitation': self.mitral_regurgitation,
                'tricuspid_regurgitation': self.tricuspid_regurgitation,
                'aortic_regurgitation': self.aortic_regurgitation
            }
        }

class SegmentationAnnotation(db.Model):
    __table_args__ = (
        db.UniqueConstraint('sample_id', 'sequence', 'rater_id', name='uq_seg_annotation_sample_seq_rater'),
    )
    id = db.Column(db.Integer, primary_key=True)
    sample_id = db.Column(db.String(100), nullable=False)
    sequence = db.Column(db.String(100), nullable=False)
    rater_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    tool_state = db.Column(db.JSON, nullable=False)
    
    rater = db.relationship('User', backref=db.backref('segmentation_annotations', lazy=True))
    
    def to_dict(self):
        return {
            'id': self.id,
            'sample_id': self.sample_id,
            'sequence': self.sequence,
            'rater': self.rater.username if self.rater_id else None,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'tool_state': self.tool_state
        }

class CardiacAnnotation(db.Model):
    __table_args__ = (
        db.UniqueConstraint('sample_id', 'sequence', 'rater_id', name='uq_cardiac_annotation_sample_seq_rater'),
    )
    id = db.Column(db.Integer, primary_key=True)
    sample_id = db.Column(db.String(100), nullable=False)
    sequence = db.Column(db.String(100), nullable=False)
    rater_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Store annotations in JSON format:
    # { "la": [{points: [...]}, ...], "ra": [...], "lv": [...], "rv": [...] }
    annotations_data = db.Column(db.JSON, nullable=False)
    
    rater = db.relationship('User', backref=db.backref('cardiac_annotations', lazy=True))
    
    def to_dict(self):
        return {
            'id': self.id,
            'sample_id': self.sample_id,
            'sequence': self.sequence,
            'rater': self.rater.username if self.rater_id else None,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'annotations_data': self.annotations_data
        }


class FeedbackSession(db.Model):
    __tablename__ = 'feedback_session'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    title = db.Column(db.String(160), default='新对话', nullable=False)
    status = db.Column(db.String(24), default='active', nullable=False, index=True)
    context_json = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_message_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    user = db.relationship('User', backref=db.backref('feedback_sessions', lazy=True))

    def to_dict(self, include_user=False):
        payload = {
            'id': self.id,
            'title': self.title or '新对话',
            'status': self.status or 'active',
            'context': self.context_json or {},
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_message_at': self.last_message_at.isoformat() if self.last_message_at else None,
        }
        if include_user:
            payload.update({
                'user_id': self.user_id,
                'username': self.user.username if self.user else None,
            })
        return payload


class FeedbackMessage(db.Model):
    __tablename__ = 'feedback_message'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('feedback_session.id'), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    role = db.Column(db.String(16), nullable=False)
    content = db.Column(db.Text, nullable=False)
    reasoning_level = db.Column(db.String(16), default='medium', nullable=False)
    page_context = db.Column(db.JSON)
    model_name = db.Column(db.String(120))
    latency_ms = db.Column(db.Integer)
    rating = db.Column(db.String(16))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    session = db.relationship(
        'FeedbackSession',
        backref=db.backref('messages', lazy=True, cascade='all, delete-orphan'),
    )
    author = db.relationship('User')

    def to_dict(self, include_debug=False):
        payload = {
            'id': self.id,
            'session_id': self.session_id,
            'role': self.role,
            'content': self.content,
            'reasoning_level': self.reasoning_level or 'medium',
            'page_context': self.page_context or {},
            'rating': self.rating,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'attachments': [item.to_dict() for item in self.attachments],
        }
        if include_debug:
            payload.update({
                'author_id': self.author_id,
                'model_name': self.model_name,
                'latency_ms': self.latency_ms,
            })
        return payload


class FeedbackAttachment(db.Model):
    __tablename__ = 'feedback_attachment'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('feedback_session.id'), nullable=False, index=True)
    message_id = db.Column(db.Integer, db.ForeignKey('feedback_message.id'), index=True)
    uploader_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    storage_path = db.Column(db.Text, nullable=False)
    original_name = db.Column(db.String(255), default='screenshot.png', nullable=False)
    mime_type = db.Column(db.String(64), default='image/png', nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    width = db.Column(db.Integer, nullable=False)
    height = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    session = db.relationship('FeedbackSession', backref=db.backref('attachments', lazy=True))
    message = db.relationship(
        'FeedbackMessage',
        backref=db.backref('attachments', lazy=True, order_by='FeedbackAttachment.id'),
    )
    uploader = db.relationship('User')

    def to_dict(self):
        return {
            'id': self.id,
            'session_id': self.session_id,
            'message_id': self.message_id,
            'original_name': self.original_name or 'screenshot.png',
            'mime_type': self.mime_type or 'image/png',
            'size_bytes': self.size_bytes,
            'width': self.width,
            'height': self.height,
            'url': f'/api/feedback/attachments/{self.id}',
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class FeedbackIssue(db.Model):
    __tablename__ = 'feedback_issue'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('feedback_session.id'), nullable=False, index=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    source_message_id = db.Column(db.Integer, db.ForeignKey('feedback_message.id'), index=True)
    category = db.Column(db.String(32), default='other', nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    summary = db.Column(db.Text, default='', nullable=False)
    page = db.Column(db.String(120), default='', nullable=False)
    operation = db.Column(db.Text, default='', nullable=False)
    expected_behavior = db.Column(db.Text, default='', nullable=False)
    actual_behavior = db.Column(db.Text, default='', nullable=False)
    impact = db.Column(db.Text, default='', nullable=False)
    severity = db.Column(db.String(16), default='medium', nullable=False, index=True)
    status = db.Column(db.String(24), default='open', nullable=False, index=True)
    acceptance_criteria = db.Column(db.Text, default='', nullable=False)
    change_scope = db.Column(db.String(32), default='needs_review', nullable=False)
    admin_note = db.Column(db.Text, default='', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    session = db.relationship('FeedbackSession', backref=db.backref('issues', lazy=True))
    reporter = db.relationship('User')
    source_message = db.relationship('FeedbackMessage')

    def to_dict(self, include_user=False):
        payload = {
            'id': self.id,
            'session_id': self.session_id,
            'source_message_id': self.source_message_id,
            'category': self.category or 'other',
            'title': self.title,
            'summary': self.summary or '',
            'page': self.page or '',
            'operation': self.operation or '',
            'expected_behavior': self.expected_behavior or '',
            'actual_behavior': self.actual_behavior or '',
            'impact': self.impact or '',
            'severity': self.severity or 'medium',
            'status': self.status or 'open',
            'acceptance_criteria': self.acceptance_criteria or '',
            'change_scope': self.change_scope or 'needs_review',
            'admin_note': self.admin_note or '',
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_paths:
            payload.update({
                'worktree_path': self.worktree_path or '',
                'artifact_dir': self.artifact_dir or '',
            })
        return payload
        latest_codex_run = self.codex_runs[-1] if self.codex_runs else None
        if latest_codex_run is not None:
            payload['codex_investigation'] = latest_codex_run.to_dict(include_result=False)
        if include_user:
            payload.update({
                'reporter_id': self.reporter_id,
                'reporter_username': self.reporter.username if self.reporter else None,
            })
        return payload


class FeedbackWorkPlan(db.Model):
    __tablename__ = 'feedback_work_plan'

    id = db.Column(db.Integer, primary_key=True)
    issue_id = db.Column(db.Integer, db.ForeignKey('feedback_issue.id'), nullable=False, unique=True, index=True)
    status = db.Column(db.String(24), default='draft', nullable=False, index=True)
    proposal_json = db.Column(db.JSON, nullable=False, default=dict)
    generated_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    approved_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    approved_at = db.Column(db.DateTime)
    queue_note = db.Column(db.Text, default='', nullable=False)
    execution_note = db.Column(db.Text, default='', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    issue = db.relationship('FeedbackIssue', backref=db.backref('work_plan', uselist=False, lazy=True))
    generated_by = db.relationship('User', foreign_keys=[generated_by_id])
    approved_by = db.relationship('User', foreign_keys=[approved_by_id])

    def to_dict(self):
        return {
            'id': self.id,
            'issue_id': self.issue_id,
            'status': self.status or 'draft',
            'proposal': self.proposal_json or {},
            'generated_by': self.generated_by.username if self.generated_by else None,
            'approved_by': self.approved_by.username if self.approved_by else None,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'queue_note': self.queue_note or '',
            'execution_note': self.execution_note or '',
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class FeedbackCodexRun(db.Model):
    __tablename__ = 'feedback_codex_run'

    id = db.Column(db.Integer, primary_key=True)
    issue_id = db.Column(db.Integer, db.ForeignKey('feedback_issue.id'), nullable=False, index=True)
    initiated_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    status = db.Column(db.String(24), default='pending', nullable=False, index=True)
    phase = db.Column(db.String(24), default='investigation', nullable=False)
    revision_note = db.Column(db.Text, default='', nullable=False)
    base_sha = db.Column(db.String(64), default='', nullable=False)
    branch = db.Column(db.String(160), default='', nullable=False)
    dirty_worktree = db.Column(db.Boolean, default=False, nullable=False)
    model_name = db.Column(db.String(120), default='', nullable=False)
    prompt_hash = db.Column(db.String(64), default='', nullable=False)
    result_json = db.Column(db.JSON, nullable=False, default=dict)
    error_message = db.Column(db.Text, default='', nullable=False)
    artifact_dir = db.Column(db.Text, default='', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    started_at = db.Column(db.DateTime)
    finished_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    issue = db.relationship(
        'FeedbackIssue',
        backref=db.backref(
            'codex_runs',
            lazy=True,
            cascade='all, delete-orphan',
            order_by='FeedbackCodexRun.id',
        ),
    )
    initiated_by = db.relationship('User')

    def to_dict(self, include_result=True):
        payload = {
            'id': self.id,
            'issue_id': self.issue_id,
            'status': self.status or 'pending',
            'phase': self.phase or 'investigation',
            'revision_note': self.revision_note or '',
            'base_sha': self.base_sha or '',
            'branch': self.branch or '',
            'dirty_worktree': bool(self.dirty_worktree),
            'model_name': self.model_name or '',
            'prompt_hash': self.prompt_hash or '',
            'error_message': self.error_message or '',
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'finished_at': self.finished_at.isoformat() if self.finished_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_result:
            payload['result'] = self.result_json or {}
        return payload


class FeedbackExecutionRun(db.Model):
    """Auditable Codex change candidate produced in an isolated Git worktree."""

    __tablename__ = 'feedback_execution_run'
    __table_args__ = (
        db.UniqueConstraint('work_plan_id', 'attempt', name='uq_feedback_execution_plan_attempt'),
    )

    id = db.Column(db.Integer, primary_key=True)
    issue_id = db.Column(db.Integer, db.ForeignKey('feedback_issue.id'), nullable=False, index=True)
    work_plan_id = db.Column(db.Integer, db.ForeignKey('feedback_work_plan.id'), nullable=False, index=True)
    attempt = db.Column(db.Integer, nullable=False, default=1)
    initiated_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    merged_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    status = db.Column(db.String(32), default='queued', nullable=False, index=True)
    phase = db.Column(db.String(48), default='queued', nullable=False)
    base_sha = db.Column(db.String(64), nullable=False)
    target_branch = db.Column(db.String(160), default='main', nullable=False)
    candidate_branch = db.Column(db.String(200), default='', nullable=False)
    candidate_sha = db.Column(db.String(64), default='', nullable=False)
    worktree_path = db.Column(db.Text, default='', nullable=False)
    artifact_dir = db.Column(db.Text, default='', nullable=False)
    process_id = db.Column(db.Integer)
    exit_code = db.Column(db.Integer)
    model_name = db.Column(db.String(120), default='', nullable=False)
    prompt_hash = db.Column(db.String(64), default='', nullable=False)
    plan_snapshot_json = db.Column(db.JSON, nullable=False, default=dict)
    plan_hash = db.Column(db.String(64), default='', nullable=False)
    diff_hash = db.Column(db.String(64), default='', nullable=False)
    changed_files_json = db.Column(db.JSON, nullable=False, default=list)
    tests_json = db.Column(db.JSON, nullable=False, default=dict)
    tests_passed = db.Column(db.Boolean)
    review_note = db.Column(db.Text, default='', nullable=False)
    merge_note = db.Column(db.Text, default='', nullable=False)
    error_message = db.Column(db.Text, default='', nullable=False)
    stop_requested = db.Column(db.Boolean, default=False, nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    started_at = db.Column(db.DateTime)
    finished_at = db.Column(db.DateTime)
    reviewed_at = db.Column(db.DateTime)
    merged_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    issue = db.relationship('FeedbackIssue', backref=db.backref('execution_runs', lazy=True))
    work_plan = db.relationship('FeedbackWorkPlan', backref=db.backref('execution_runs', lazy=True))
    initiated_by = db.relationship('User', foreign_keys=[initiated_by_id])
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_id])
    merged_by = db.relationship('User', foreign_keys=[merged_by_id])

    def to_dict(self, include_paths=False):
        files = self.changed_files_json if isinstance(self.changed_files_json, list) else []
        tests = self.tests_json if isinstance(self.tests_json, dict) else {}
        payload = {
            'id': self.id,
            'issue_id': self.issue_id,
            'work_plan_id': self.work_plan_id,
            'attempt': self.attempt,
            'status': self.status or 'queued',
            'phase': self.phase or 'queued',
            'base_sha': self.base_sha or '',
            'target_branch': self.target_branch or 'main',
            'candidate_branch': self.candidate_branch or '',
            'candidate_sha': self.candidate_sha or '',
            'model_name': self.model_name or '',
            'plan_hash': self.plan_hash or '',
            'diff_hash': self.diff_hash or '',
            'changed_files': files,
            'changed_file_count': len(files),
            'tests': tests,
            'tests_passed': self.tests_passed,
            'review_note': self.review_note or '',
            'merge_note': self.merge_note or '',
            'error_message': self.error_message or '',
            'stop_requested': bool(self.stop_requested),
            'version': int(self.version or 1),
            'initiated_by': self.initiated_by.username if self.initiated_by else None,
            'reviewed_by': self.reviewed_by.username if self.reviewed_by else None,
            'merged_by': self.merged_by.username if self.merged_by else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'finished_at': self.finished_at.isoformat() if self.finished_at else None,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'merged_at': self.merged_at.isoformat() if self.merged_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_paths:
            payload.update({
                'worktree_path': self.worktree_path or '',
                'artifact_dir': self.artifact_dir or '',
            })
        return payload

class MedicalMultimodalClassifier(nn.Module):
    """医学多模态分类器：结合医学影像和指令进行分类"""
    
    def __init__(self, num_classes=3):
        super().__init__()
        from transformers import ViTModel, DistilBertModel
        
        # 图像编码器：ViT-Base
        # 使用镜像源或本地缓存
        try:
            self.vision_encoder = ViTModel.from_pretrained(
                "google/vit-base-patch16-224",
                local_files_only=False,  # 允许从网络下载
            )
        except Exception as e:
            # 如果网络失败，尝试使用本地缓存
            print(f"警告：从网络下载 ViT 模型失败: {e}")
            print("尝试使用本地缓存...")
            self.vision_encoder = ViTModel.from_pretrained(
                "google/vit-base-patch16-224",
                local_files_only=True,  # 仅使用本地缓存
            )
        
        # 文本编码器：DistilBERT
        try:
            self.text_encoder = DistilBertModel.from_pretrained(
                "distilbert-base-uncased",
                local_files_only=False,
            )
        except Exception as e:
            print(f"警告：从网络下载 DistilBERT 模型失败: {e}")
            print("尝试使用本地缓存...")
            self.text_encoder = DistilBertModel.from_pretrained(
                "distilbert-base-uncased",
                local_files_only=True,
            )
        
        # 多模态融合分类头
        self.fusion_classifier = nn.Sequential(
            nn.Linear(768 + 768, 512),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(512, num_classes)
        )
    
    def forward(self, pixel_values, input_ids, attention_mask, labels=None):
        # 图像特征提取 [B, 768]
        vision_features = self.vision_encoder(pixel_values).last_hidden_state[:, 0]
        
        # 文本特征提取 [B, 768]
        text_features = self.text_encoder(input_ids, attention_mask).last_hidden_state[:, 0]
        
        # 特征融合
        fused_features = torch.cat([vision_features, text_features], dim=1)  # [B, 1536]
        
        # 分类
        logits = self.fusion_classifier(fused_features)  # [B, 3]
        
        # 计算损失
        loss = None
        if labels is not None:
            loss_fn = nn.CrossEntropyLoss()
            loss = loss_fn(logits, labels)
        
        return {"loss": loss, "logits": logits}
