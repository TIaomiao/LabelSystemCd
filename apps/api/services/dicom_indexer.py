from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import hashlib
from pathlib import Path
from typing import Any
import re

import numpy as np
import pydicom
from pydicom.pixel_data_handlers.util import apply_voi_lut

from ..db import dumps, get_conn, init_db, loads, utcnow


def _looks_like_dicom_file(path: Path) -> bool:
    if not path.is_file():
        return False
    name = path.name.strip()
    lower = name.lower()
    if lower.endswith((".dcm", ".dic", ".ima")):
        return True
    if lower == "dicomdir":
        return False
    # RenJi exports include extensionless Philips-style files like IM_0001,
    # and some exports use long numeric UID-like filenames.
    return bool(re.fullmatch(r"(?:im[_-]?)?\d{4,}", lower) or re.fullmatch(r"\d[\d.]{15,}", lower))


def _iter_dicom_files(root: Path) -> list[Path]:
    try:
        return sorted(
            [item for item in root.rglob("*") if _looks_like_dicom_file(item)],
            key=lambda item: str(item.relative_to(root)).lower(),
        )
    except PermissionError:
        return []


def sanitize_source_path(source_path: str) -> Path:
    cleaned = (source_path or "").strip().strip('"').strip("'")
    if not cleaned:
        raise FileNotFoundError(source_path)
    return Path(cleaned).expanduser()


def _directory_has_dicom(root: Path) -> bool:
    try:
        for path in root.rglob("*"):
            if _looks_like_dicom_file(path):
                return True
    except PermissionError:
        return False
    return False


def _selection_range_from_sequence_name(name: str) -> tuple[int, int] | None:
    match = re.match(r"^(?:2CH|3CH|4CH|SAX|LGE)=(\d+)-(\d+)$", name.strip(), flags=re.IGNORECASE)
    if not match:
        return None
    start = int(match.group(1))
    end = int(match.group(2))
    if start <= 0 or end < start:
        return None
    return start, end


def _selected_dicom_files(root: Path) -> list[Path]:
    sequence_dirs = sorted(
        [child for child in root.iterdir() if child.is_dir() and _selection_range_from_sequence_name(child.name)],
        key=lambda item: item.name.lower(),
    )
    if not sequence_dirs:
        return _iter_dicom_files(root)

    selected_files: list[Path] = []
    selected_dir_paths = {sequence_dir.resolve() for sequence_dir in sequence_dirs}
    for sequence_dir in sequence_dirs:
        files = _iter_dicom_files(sequence_dir)
        selected_range = _selection_range_from_sequence_name(sequence_dir.name)
        if selected_range is None:
            selected_files.extend(files)
            continue
        start, end = selected_range
        selected_files.extend(files[start - 1 : end])

    for file_path in _iter_dicom_files(root):
        if any(parent.resolve() in selected_dir_paths for parent in file_path.parents):
            continue
        selected_files.append(file_path)
    return selected_files


def list_directories(source_path: str | None, fallback_path: str) -> dict[str, Any]:
    root = sanitize_source_path(source_path or fallback_path)
    if root.is_file():
        root = root.parent
    if not root.exists():
        raise FileNotFoundError(str(root))
    directories = []
    for child in sorted(root.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        if not child.is_dir():
            continue
        directories.append(
            {
                "name": child.name,
                "path": str(child),
                "has_dicom": _directory_has_dicom(child),
            }
        )
    return {
        "current_path": str(root),
        "parent_path": str(root.parent) if root.parent != root else None,
        "directories": directories,
        "default_sample_path": fallback_path,
    }


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _dicom_value_text(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return " ".join(_safe_text(item) for item in value)
    return _safe_text(value)


def _dataset_tag_text(ds: pydicom.dataset.FileDataset, tag: tuple[int, int]) -> str:
    elem = ds.get(tag)
    if elem is None:
        return ""
    return _dicom_value_text(elem.value)


def _series_role_token(
    folder_path: str | Path,
    description: str,
    protocol_name: str = "",
    image_type: str = "",
    scanning_sequence: str = "",
    sequence_variant: str = "",
    mr_acquisition_type: str = "",
    philips_slice_orientation: str = "",
) -> str:
    folder = Path(folder_path)
    return " ".join(
        part.lower()
        for part in (
            folder.name,
            description,
            protocol_name,
            image_type,
            scanning_sequence,
            sequence_variant,
            mr_acquisition_type,
            philips_slice_orientation,
        )
        if part
    )


def _has_any_token(token: str, markers: tuple[str, ...]) -> bool:
    return any(marker in token for marker in markers)


def _public_study_label(study_id: int) -> str:
    return f"Study-{study_id:06d}"


def _public_patient_id_from_source(source_path: str, fallback: str) -> str:
    normalized = str(source_path or "")
    if "/CMR_ALL/" not in normalized:
        return fallback
    match = re.search(r"(?<!\d)(\d{10})(?!\d)", normalized)
    if not match:
        return fallback
    return f"登记号：{match.group(1)}"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_image_storage_dataset(ds: pydicom.dataset.FileDataset) -> bool:
    sop_class_uid = _safe_text(getattr(ds, "SOPClassUID", ""))
    if not sop_class_uid:
        file_meta = getattr(ds, "file_meta", None)
        sop_class_uid = _safe_text(getattr(file_meta, "MediaStorageSOPClassUID", ""))
    if not sop_class_uid:
        return False

    try:
        uid = pydicom.uid.UID(sop_class_uid)
    except (TypeError, ValueError):
        return False

    # Newer pydicom versions expose the DICOM registry classification
    # directly.  pydicom 2.x (used by this deployment) does not, so fall back
    # to the registry's standard SOP Class name.  This accepts MR/Enhanced MR,
    # secondary capture and other genuine Image Storage classes, while
    # rejecting Raw Data Storage, SR, presentation states and segmentations.
    is_image_storage = getattr(uid, "is_image_storage", None)
    if is_image_storage is not None:
        if callable(is_image_storage):
            is_image_storage = is_image_storage()
        return bool(is_image_storage)
    return "Image Storage" in uid.name


def _normalize_patient_age(raw_age: Any, birth_date: str, study_date: str) -> str:
    text = _safe_text(raw_age).upper()
    if text:
        return text
    if len(birth_date) != 8 or len(study_date) != 8:
        return ""
    try:
        birth = datetime.strptime(birth_date, "%Y%m%d")
        study = datetime.strptime(study_date, "%Y%m%d")
    except ValueError:
        return ""
    years = study.year - birth.year - ((study.month, study.day) < (birth.month, birth.day))
    if years < 0:
        return ""
    return f"{years:03d}Y"


def _pixel_spacing(ds: pydicom.dataset.FileDataset) -> tuple[float, float]:
    spacing = getattr(ds, "PixelSpacing", None) or [1.0, 1.0]
    try:
        if len(spacing) < 2:
            return 1.0, 1.0
    except TypeError:
        return 1.0, 1.0
    return _safe_float(spacing[1], 1.0), _safe_float(spacing[0], 1.0)


def _image_position(ds: pydicom.dataset.FileDataset) -> list[float]:
    value = getattr(ds, "ImagePositionPatient", None) or [0.0, 0.0, 0.0]
    try:
        if len(value) < 3:
            return [0.0, 0.0, 0.0]
        return [_safe_float(item) for item in value[:3]]
    except TypeError:
        return [0.0, 0.0, 0.0]


def _image_orientation(ds: pydicom.dataset.FileDataset) -> list[float]:
    value = getattr(ds, "ImageOrientationPatient", None) or [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    try:
        if len(value) < 6:
            return [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        return [_safe_float(item) for item in value[:6]]
    except TypeError:
        return [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]


def orientation_label(description: str, role: str) -> str:
    text = description.lower()
    if role == "lge_lax":
        return "LGE-LAX"
    if role == "cine_lax_2ch" or "2ch" in text:
        return "LAX-2CH"
    if role == "cine_lax_3ch" or "3ch" in text:
        return "LAX-3CH"
    if role == "cine_lax_4ch" or "4ch" in text:
        return "LAX-4CH"
    if role == "lge_sax":
        return "LGE-SAX"
    if role == "cine_sax":
        return "SAX"
    return "UNKNOWN"


LGE_MARKERS = ("psir", "lge", "late enhancement", "delayed enhancement", "delay", "scar")
TWO_CH_MARKERS = ("2ch", "2-ch", "2 chamber", "two chamber", "c2ch", "lax_2", "lax 2")
THREE_CH_MARKERS = ("3ch", "3-ch", "3 chamber", "three chamber", "c3ch", "lax_3", "lax 3")
FOUR_CH_MARKERS = ("4ch", "4-ch", "4 chamber", "four chamber", "c4ch", "lax_4", "lax 4")
SAX_STACK_MARKERS = ("8sl", "10sl", "12sl")
SAX_MARKERS = ("sax", "short axis", "csax", "sbtfe_bh_m2d", "sa stack", *SAX_STACK_MARKERS)
CINE_MARKERS = ("cine", "retro", "btfe", "b-tfe", "sbtfe", "trufi", "truefisp", "segmented")
NON_FUNCTION_CINE_MARKERS = (
    "survey",
    "define",
    "localizer",
    "locator",
    "scout",
    "interactive",
    "dynamic",
    "perfusion",
    "first pass",
    "first_pass",
    "perf",
    "dyn_stfe",
    "dyn stfe",
    "t1",
    "t2",
    "t2map",
    "t2_map",
    "t2 map",
    "molli",
    "r2",
    "stir",
    "qflow",
    "dwi",
    "ivim",
    "ll pp",
    "ir_tfe",
    "new",
)


def infer_role(
    folder: Path,
    description: str,
    unique_positions: int,
    unique_phases: int,
    *,
    protocol_name: str = "",
    image_type: str = "",
    scanning_sequence: str = "",
    sequence_variant: str = "",
    mr_acquisition_type: str = "",
    philips_slice_orientation: str = "",
) -> str:
    token = _series_role_token(
        folder,
        description,
        protocol_name,
        image_type,
        scanning_sequence,
        sequence_variant,
        mr_acquisition_type,
        philips_slice_orientation,
    )
    has_lge_marker = _has_any_token(token, LGE_MARKERS)
    has_2ch_marker = _has_any_token(token, TWO_CH_MARKERS)
    has_3ch_marker = _has_any_token(token, THREE_CH_MARKERS)
    has_4ch_marker = _has_any_token(token, FOUR_CH_MARKERS)
    has_sax_marker = _has_any_token(token, SAX_MARKERS)
    if has_lge_marker:
        if has_2ch_marker or has_3ch_marker or has_4ch_marker:
            return "lge_lax"
        if has_sax_marker or unique_positions > 1:
            return "lge_sax"
        return "lge_lax"

    if _has_any_token(token, NON_FUNCTION_CINE_MARKERS):
        return "unknown"

    if has_2ch_marker and unique_phases > 1:
        return "cine_lax_2ch"
    if has_3ch_marker and unique_phases > 1:
        return "cine_lax_3ch"
    if has_4ch_marker and unique_phases > 1:
        return "cine_lax_4ch"

    # Older RenJi HCM Philips cine long-axis views often all share the generic
    # B-TFE_BH name. The Philips private Slice Orientation tag separates the
    # horizontal long-axis 4CH-like view from sagittal/transversal planning views.
    if (
        "b-tfe_bh" in token
        and "coronal" in token
        and unique_positions == 1
        and unique_phases > 1
    ):
        return "cine_lax_4ch"

    if has_sax_marker and unique_positions > 1 and unique_phases > 1:
        return "cine_sax"
    # A complete Philips SAX cine stack normally has more slices, but some
    # hospital acceptance exports retain only four contiguous basal slices.
    # Four spatial positions still distinguish a stack from a single-plane
    # long-axis cine, while the marker/phase checks above continue to reject
    # localizers, perfusion and explicitly labelled LAX series.
    if "sbtfe" in token and unique_positions >= 4 and unique_phases > 1:
        return "cine_sax"
    return "unknown"


def normalize_series_role(
    folder_path: str | Path,
    description: str,
    role: str,
    slice_count: int,
    phase_count: int,
    *,
    protocol_name: str = "",
    image_type: str = "",
    scanning_sequence: str = "",
    sequence_variant: str = "",
    mr_acquisition_type: str = "",
    philips_slice_orientation: str = "",
) -> str:
    token = _series_role_token(
        folder_path,
        description,
        protocol_name,
        image_type,
        scanning_sequence,
        sequence_variant,
        mr_acquisition_type,
        philips_slice_orientation,
    )
    has_lge_marker = _has_any_token(token, LGE_MARKERS)
    has_4ch_marker = _has_any_token(token, FOUR_CH_MARKERS)
    has_sax_marker = _has_any_token(token, SAX_MARKERS)
    if has_lge_marker:
        if has_4ch_marker:
            return "lge_lax"
        if has_sax_marker or slice_count > 1:
            return "lge_sax"
        return "lge_lax"
    if _has_any_token(token, NON_FUNCTION_CINE_MARKERS):
        return "unknown"
    if has_4ch_marker and phase_count > 1 and role in {"lge_lax", "unknown"}:
        return "cine_lax_4ch"
    if "b-tfe_bh" in token and "coronal" in token and slice_count == 1 and phase_count > 1:
        return "cine_lax_4ch"
    return role


def repair_series_roles() -> int:
    init_db()
    repaired = 0
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, description, role, slice_count, phase_count, folder_path, metadata_json FROM series"
        ).fetchall()
        for row in rows:
            metadata = loads(row["metadata_json"], {}) or {}
            dicom_tags = metadata.get("dicom_tags") or {}
            next_role = normalize_series_role(
                row["folder_path"],
                row["description"] or "",
                row["role"],
                int(row["slice_count"] or 0),
                int(row["phase_count"] or 0),
                protocol_name=dicom_tags.get("protocol_name", ""),
                image_type=dicom_tags.get("image_type", ""),
                scanning_sequence=dicom_tags.get("scanning_sequence", ""),
                sequence_variant=dicom_tags.get("sequence_variant", ""),
                mr_acquisition_type=dicom_tags.get("mr_acquisition_type", ""),
                philips_slice_orientation=dicom_tags.get("philips_slice_orientation", ""),
            )
            if next_role == row["role"]:
                continue
            conn.execute(
                "UPDATE series SET role = ?, orientation = ? WHERE id = ?",
                (next_role, orientation_label(row["description"] or "", next_role), row["id"]),
            )
            repaired += 1
    return repaired


def _series_group_key(study_uid: str, series_uid: str, file_path: Path, description: str) -> str:
    token = f"{file_path.parent.name} {description}".lower()
    parent_name = file_path.parent.name.lower()
    is_lge_stack = _has_any_token(token, LGE_MARKERS)
    if is_lge_stack:
        return f"{study_uid}:split-lge:{file_path.parent.resolve()}:{description.strip().lower()}"
    is_split_sax = (
        parent_name.startswith("sax")
        and "sax" in token
        and any(word in token for word in ["cine", "btfe", "b-tfe", "segmented"])
    )
    if is_split_sax:
        return f"{study_uid}:split-sax:{file_path.parent.resolve()}"
    return series_uid


def _position_key(position: list[float], normal: np.ndarray) -> float:
    return round(float(np.dot(np.array(position), normal)), 3)


def _position_group(position: list[float]) -> tuple[float, float, float]:
    return tuple(round(float(value), 3) for value in position[:3])


def _normal_from_orientation(orientation: list[float]) -> np.ndarray:
    row = np.array(orientation[:3])
    col = np.array(orientation[3:6])
    normal = np.cross(row, col)
    if not np.any(normal):
        return np.array([0.0, 0.0, 1.0])
    return normal / np.linalg.norm(normal)


def _dicom_time_seconds(value: Any) -> float | None:
    raw = _safe_text(value)
    match = re.match(r"^(\d{2})(\d{2})(\d{2}(?:\.\d+)?)", raw)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    if hours > 23 or minutes > 59 or seconds >= 60:
        return None
    return hours * 3600 + minutes * 60 + seconds


def _split_sax_family(items: list[dict[str, Any]]) -> tuple[str, tuple[float, ...], int, int] | None:
    if not items:
        return None
    first = items[0]
    token = _series_role_token(
        first["folder_path"],
        first["series_description"],
        first.get("protocol_name", ""),
        first.get("image_type", ""),
        first.get("scanning_sequence", ""),
        first.get("sequence_variant", ""),
        first.get("mr_acquisition_type", ""),
        first.get("philips_slice_orientation", ""),
    )
    if _has_any_token(token, LGE_MARKERS + NON_FUNCTION_CINE_MARKERS):
        return None
    if _has_any_token(token, TWO_CH_MARKERS + THREE_CH_MARKERS + FOUR_CH_MARKERS):
        return None
    if not _has_any_token(token, CINE_MARKERS):
        return None
    if not (_has_any_token(token, SAX_MARKERS) or re.search(r"sax[_ -]?b\d+", token)):
        return None

    positions = {_position_group(item["image_position"]) for item in items}
    if len(positions) != 1 or not 15 <= len(items) <= 50:
        return None

    description = first["series_description"].lower().strip()
    protocol = first.get("protocol_name", "").lower().strip()
    family = re.sub(r"sax[_ -]?b\d+", "sax_b#", f"{description} {protocol}")
    family = re.sub(r"\s+", " ", family).strip()
    orientation = tuple(round(float(value), 4) for value in first["image_orientation"][:6])
    return family, orientation, int(first["rows"]), int(first["cols"])


def _is_complete_split_sax_stack(members: list[tuple[str, list[dict[str, Any]]]]) -> bool:
    if not 5 <= len(members) <= 20:
        return False
    first_items = [items[0] for _, items in members]
    positions = [_position_group(item["image_position"]) for item in first_items]
    if len(set(positions)) != len(positions):
        return False
    phase_counts = [len(items) for _, items in members]
    if max(phase_counts) - min(phase_counts) > 2:
        return False

    normal = _normal_from_orientation(first_items[0]["image_orientation"])
    coordinates = sorted(_position_key(item["image_position"], normal) for item in first_items)
    gaps = [abs(right - left) for left, right in zip(coordinates, coordinates[1:])]
    if not gaps or min(gaps) < 0.5:
        return False
    median_gap = float(np.median(gaps))
    return all(0.4 * median_gap <= gap <= 2.5 * median_gap for gap in gaps)


def _merge_split_sax_series_groups(
    series_groups: dict[str, list[dict[str, Any]]],
    study_uid: str,
) -> int:
    buckets: dict[tuple[str, tuple[float, ...], int, int], list[tuple[str, list[dict[str, Any]]]]] = defaultdict(list)
    for group_key, items in series_groups.items():
        family = _split_sax_family(items)
        if family is not None:
            buckets[family].append((group_key, items))

    merge_count = 0
    for candidates in buckets.values():
        candidates.sort(
            key=lambda member: (
                member[1][0].get("acquisition_seconds")
                if member[1][0].get("acquisition_seconds") is not None
                else float("inf"),
                int(member[1][0].get("series_number") or 0),
            )
        )
        clusters: list[list[tuple[str, list[dict[str, Any]]]]] = []
        current: list[tuple[str, list[dict[str, Any]]]] = []
        current_positions: set[tuple[float, float, float]] = set()
        previous_time: float | None = None
        previous_number = 0
        for member in candidates:
            first = member[1][0]
            position = _position_group(first["image_position"])
            acquisition = first.get("acquisition_seconds")
            series_number = int(first.get("series_number") or 0)
            time_contiguous = (
                previous_time is not None
                and acquisition is not None
                and 0 <= acquisition - previous_time <= 120
            )
            number_contiguous = previous_number > 0 and 0 < series_number - previous_number <= 2
            should_split = bool(current) and (
                position in current_positions or not (time_contiguous or number_contiguous)
            )
            if should_split:
                clusters.append(current)
                current = []
                current_positions = set()
            current.append(member)
            current_positions.add(position)
            previous_time = acquisition
            previous_number = series_number
        if current:
            clusters.append(current)

        for cluster in clusters:
            if not _is_complete_split_sax_stack(cluster):
                continue
            source_uids = sorted(
                str(items[0].get("source_series_uid") or group_key)
                for group_key, items in cluster
            )
            digest = hashlib.sha1("\n".join(source_uids).encode("utf-8")).hexdigest()[:20]
            merged_key = f"{study_uid}:logical-sax:{digest}"
            merged_items = [item for _, items in cluster for item in items]
            for group_key, _ in cluster:
                series_groups.pop(group_key, None)
            for item in merged_items:
                item["series_uid"] = merged_key
            series_groups[merged_key] = merged_items
            merge_count += 1
    return merge_count


def _source_scoped_study_uid(dicom_study_uid: str, source_path: str) -> str:
    """Return a stable internal study key for ambiguous DICOM identities.

    The source path is deliberately included only in the fallback identity.  A
    well-formed, non-colliding StudyInstanceUID therefore keeps its historical
    database value, while missing or reused UIDs cannot alias another import.
    """

    try:
        normalized_source = str(Path(source_path).expanduser().resolve())
    except OSError:
        normalized_source = str(Path(source_path).expanduser().absolute())
    digest = hashlib.sha256(normalized_source.encode("utf-8")).hexdigest()
    prefix = dicom_study_uid or "missing-study-uid"
    return f"{prefix}:source:{digest}"


def _resolve_internal_study_uid(conn, *, dicom_study_uid: str, source_path: str) -> str:
    """Resolve the database identity without claiming another source's study."""

    same_source = conn.execute(
        "SELECT study_uid FROM studies WHERE source_path = ? ORDER BY id DESC LIMIT 1",
        (source_path,),
    ).fetchone()
    if same_source is not None:
        # Preserve the identity (and therefore series identities/state matching)
        # established by the first successful import of this exact source.
        return str(same_source["study_uid"])

    if dicom_study_uid:
        uid_owner = conn.execute(
            "SELECT source_path FROM studies WHERE study_uid = ? LIMIT 1",
            (dicom_study_uid,),
        ).fetchone()
        if uid_owner is None:
            return dicom_study_uid

    return _source_scoped_study_uid(dicom_study_uid, source_path)


def _scope_series_groups_to_study(
    series_groups: dict[str, list[dict[str, Any]]],
    *,
    dicom_study_uid: str,
    internal_study_uid: str,
) -> None:
    """Make series/frame keys unique when the study needed a source scope."""

    if internal_study_uid == dicom_study_uid:
        return

    scoped_groups: dict[str, list[dict[str, Any]]] = {}
    for group_key, items in series_groups.items():
        group_digest = hashlib.sha256(group_key.encode("utf-8")).hexdigest()
        scoped_key = f"{internal_study_uid}:series:{group_digest}"
        for item in items:
            item["series_uid"] = scoped_key
        scoped_groups[scoped_key] = items
    series_groups.clear()
    series_groups.update(scoped_groups)


def _study_patient_demographics_from_source(source_path: str) -> dict[str, str]:
    try:
        root = sanitize_source_path(source_path)
    except FileNotFoundError:
        return {"patient_sex": "", "patient_age": ""}
    if root.is_file():
        candidates = [root]
    else:
        candidates = _iter_dicom_files(root)
    for file_path in candidates:
        try:
            ds = pydicom.dcmread(str(file_path), stop_before_pixels=True, force=True)
        except Exception:
            continue
        study_date = _safe_text(getattr(ds, "StudyDate", ""))
        return {
            "patient_sex": _safe_text(getattr(ds, "PatientSex", "")),
            "patient_age": _normalize_patient_age(
                getattr(ds, "PatientAge", ""),
                _safe_text(getattr(ds, "PatientBirthDate", "")),
                study_date,
            ),
        }
    return {"patient_sex": "", "patient_age": ""}


def _snapshot_existing_study_state(
    conn,
    *,
    source_path: str,
) -> dict[str, Any]:
    study_rows = conn.execute(
        "SELECT id FROM studies WHERE source_path = ?",
        (source_path,),
    ).fetchall()
    if not study_rows:
        return {"contours": {}, "measurements": {}, "report": None}

    study_ids = [int(row["id"]) for row in study_rows]
    placeholders = ",".join("?" for _ in study_ids)
    series_rows = conn.execute(
        f"""
        SELECT id, study_id, series_uid, role, description, slice_count, phase_count, file_count, orientation
        FROM series
        WHERE study_id IN ({placeholders})
        """,
        study_ids,
    ).fetchall()
    if not series_rows:
        report_row = conn.execute(
            f"""
            SELECT status, findings, summary, payload_json, updated_at
            FROM reports
            WHERE study_id IN ({placeholders})
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            study_ids,
        ).fetchone()
        return {
            "contours": {},
            "measurements": {},
            "report": {key: report_row[key] for key in report_row.keys()} if report_row else None,
        }

    series_ids = [int(row["id"]) for row in series_rows]
    series_meta_by_id = {
        int(row["id"]): {
            "study_id": int(row["study_id"]),
            "series_uid": row["series_uid"],
            "role": row["role"],
            "description": row["description"] or "",
            "slice_count": int(row["slice_count"] or 0),
            "phase_count": int(row["phase_count"] or 0),
            "file_count": int(row["file_count"] or 0),
            "orientation": row["orientation"] or "",
        }
        for row in series_rows
    }
    series_placeholders = ",".join("?" for _ in series_ids)

    contour_rows = conn.execute(
        f"""
        SELECT series_id, module, payload_json, updated_at
        FROM contours
        WHERE series_id IN ({series_placeholders})
        """,
        series_ids,
    ).fetchall()
    measurement_rows = conn.execute(
        f"""
        SELECT series_id, module, payload_json, updated_at
        FROM measurements
        WHERE series_id IN ({series_placeholders})
        """,
        series_ids,
    ).fetchall()
    report_row = conn.execute(
        f"""
        SELECT status, findings, summary, payload_json, updated_at
        FROM reports
        WHERE study_id IN ({placeholders})
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        study_ids,
    ).fetchone()

    contours: dict[tuple[str, str], dict[str, Any]] = {}
    contour_fallbacks: list[dict[str, Any]] = []
    for row in contour_rows:
        series_meta = series_meta_by_id.get(int(row["series_id"]))
        if not series_meta:
            continue
        contour = {
            "payload_json": row["payload_json"],
            "updated_at": row["updated_at"],
        }
        contours[(series_meta["series_uid"], row["module"])] = contour
        contour_fallbacks.append({**series_meta, "module": row["module"], **contour})

    measurements: dict[tuple[str, str], dict[str, Any]] = {}
    measurement_fallbacks: list[dict[str, Any]] = []
    for row in measurement_rows:
        series_meta = series_meta_by_id.get(int(row["series_id"]))
        if not series_meta:
            continue
        measurement = {
            "payload_json": row["payload_json"],
            "updated_at": row["updated_at"],
        }
        measurements[(series_meta["series_uid"], row["module"])] = measurement
        measurement_fallbacks.append({**series_meta, "module": row["module"], **measurement})

    return {
        "contours": contours,
        "contour_fallbacks": contour_fallbacks,
        "measurements": measurements,
        "measurement_fallbacks": measurement_fallbacks,
        "report": {key: report_row[key] for key in report_row.keys()} if report_row else None,
    }


def _series_restore_score(current: dict[str, Any], previous: dict[str, Any]) -> int:
    score = 0
    if current["role"] and current["role"] == previous.get("role"):
        score += 100
    if current["orientation"] and current["orientation"] == previous.get("orientation"):
        score += 20
    if current["slice_count"] == previous.get("slice_count"):
        score += 12
    if current["phase_count"] == previous.get("phase_count"):
        score += 12
    if current["file_count"] == previous.get("file_count"):
        score += 8
    if (current["description"] or "").strip().lower() == (previous.get("description") or "").strip().lower():
        score += 6
    return score


def _best_fallback_series_match(
    current: dict[str, Any],
    module_name: str,
    candidates: list[dict[str, Any]],
    used_keys: set[tuple[str, str]],
) -> dict[str, Any] | None:
    eligible = [
        candidate
        for candidate in candidates
        if candidate.get("module") == module_name
        and (candidate.get("series_uid"), module_name) not in used_keys
        and candidate.get("role") == current.get("role")
    ]
    if not eligible:
        return None
    best = max(eligible, key=lambda candidate: _series_restore_score(current, candidate))
    return best if _series_restore_score(current, best) >= 120 else None


def _restore_study_state(conn, *, study_id: int, snapshot: dict[str, Any]) -> None:
    if not snapshot:
        return

    series_rows = conn.execute(
        """
        SELECT id, series_uid, role, description, slice_count, phase_count, file_count, orientation
        FROM series
        WHERE study_id = ?
        """,
        (study_id,),
    ).fetchall()
    used_contour_keys: set[tuple[str, str]] = set()
    used_measurement_keys: set[tuple[str, str]] = set()
    for row in series_rows:
        series_id = int(row["id"])
        current = {
            "series_uid": row["series_uid"],
            "role": row["role"],
            "description": row["description"] or "",
            "slice_count": int(row["slice_count"] or 0),
            "phase_count": int(row["phase_count"] or 0),
            "file_count": int(row["file_count"] or 0),
            "orientation": row["orientation"] or "",
        }
        module_names = sorted({module for _, module in (snapshot.get("contours") or {}).keys()})
        for module_name in module_names:
            contour = (snapshot.get("contours") or {}).get((current["series_uid"], module_name))
            contour_key = (current["series_uid"], module_name)
            if contour is None:
                fallback = _best_fallback_series_match(
                    current,
                    module_name,
                    snapshot.get("contour_fallbacks") or [],
                    used_contour_keys,
                )
                if fallback is None:
                    continue
                contour = fallback
                contour_key = (fallback["series_uid"], module_name)
            conn.execute(
                """
                INSERT INTO contours (series_id, module, payload_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(series_id, module)
                DO UPDATE SET payload_json = excluded.payload_json, updated_at = excluded.updated_at
                """,
                (series_id, module_name, contour["payload_json"], contour["updated_at"]),
            )
            used_contour_keys.add(contour_key)
        module_names = sorted({module for _, module in (snapshot.get("measurements") or {}).keys()})
        for module_name in module_names:
            measurement = (snapshot.get("measurements") or {}).get((current["series_uid"], module_name))
            measurement_key = (current["series_uid"], module_name)
            if measurement is None:
                fallback = _best_fallback_series_match(
                    current,
                    module_name,
                    snapshot.get("measurement_fallbacks") or [],
                    used_measurement_keys,
                )
                if fallback is None:
                    continue
                measurement = fallback
                measurement_key = (fallback["series_uid"], module_name)
            conn.execute(
                """
                INSERT INTO measurements (series_id, module, payload_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(series_id, module)
                DO UPDATE SET payload_json = excluded.payload_json, updated_at = excluded.updated_at
                """,
                (series_id, module_name, measurement["payload_json"], measurement["updated_at"]),
            )
            used_measurement_keys.add(measurement_key)

    report = snapshot.get("report")
    if report:
        conn.execute(
            """
            UPDATE reports
            SET status = ?, findings = ?, summary = ?, payload_json = ?, updated_at = ?
            WHERE study_id = ?
            """,
            (
                report["status"],
                report["findings"],
                report["summary"],
                report["payload_json"],
                report["updated_at"],
                study_id,
            ),
        )


def import_study(source_path: str) -> int:
    init_db()
    root = sanitize_source_path(source_path)
    if not root.exists():
        raise FileNotFoundError(source_path)

    dcm_files = _selected_dicom_files(root)
    if not dcm_files:
        raise ValueError("No DICOM files found in the selected folder.")

    series_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    study_info: dict[str, Any] | None = None

    for file_path in dcm_files:
        ds = pydicom.dcmread(str(file_path), stop_before_pixels=True, force=True)
        rows = _safe_int(getattr(ds, "Rows", 0))
        cols = _safe_int(getattr(ds, "Columns", 0))
        if not _is_image_storage_dataset(ds) or rows <= 0 or cols <= 0:
            # Raw Data Storage, presentation states, structured reports and
            # similar DICOM objects may even carry matrix dimensions, but they
            # are not displayable image frames for the workstation.
            continue
        study_uid = _safe_text(getattr(ds, "StudyInstanceUID", ""))
        series_uid = _safe_text(getattr(ds, "SeriesInstanceUID", ""))
        series_description = _safe_text(getattr(ds, "SeriesDescription", file_path.parent.name))
        series_group_key = _series_group_key(study_uid, series_uid, file_path, series_description)
        image_type = _dicom_value_text(getattr(ds, "ImageType", ""))
        protocol_name = _safe_text(getattr(ds, "ProtocolName", ""))
        scanning_sequence = _dicom_value_text(getattr(ds, "ScanningSequence", ""))
        sequence_variant = _dicom_value_text(getattr(ds, "SequenceVariant", ""))
        mr_acquisition_type = _safe_text(getattr(ds, "MRAcquisitionType", ""))
        philips_slice_orientation = _dataset_tag_text(ds, (0x2001, 0x100B))
        study_info = {
            "study_uid": study_uid,
            "patient_name": _safe_text(getattr(ds, "PatientName", "")),
            "patient_id": _safe_text(getattr(ds, "PatientID", "")),
            "patient_sex": _safe_text(getattr(ds, "PatientSex", "")),
            "patient_age": _normalize_patient_age(
                getattr(ds, "PatientAge", ""),
                _safe_text(getattr(ds, "PatientBirthDate", "")),
                _safe_text(getattr(ds, "StudyDate", "")),
            ),
            "study_date": _safe_text(getattr(ds, "StudyDate", "")),
            "accession_number": _safe_text(getattr(ds, "AccessionNumber", "")),
            "source_path": str(root),
        }
        px, py = _pixel_spacing(ds)
        item = {
            "file_path": str(file_path),
            "folder_path": str(file_path.parent),
            "series_uid": series_group_key,
            "source_series_uid": series_uid,
            "series_number": _safe_int(getattr(ds, "SeriesNumber", 0)),
            "acquisition_seconds": _dicom_time_seconds(
                getattr(ds, "AcquisitionTime", "") or getattr(ds, "SeriesTime", "")
            ),
            "series_description": series_description,
            "protocol_name": protocol_name,
            "image_type": image_type,
            "scanning_sequence": scanning_sequence,
            "sequence_variant": sequence_variant,
            "mr_acquisition_type": mr_acquisition_type,
            "philips_slice_orientation": philips_slice_orientation,
            "rows": rows,
            "cols": cols,
            "pixel_spacing_x": px,
            "pixel_spacing_y": py,
            "slice_thickness": _safe_float(getattr(ds, "SliceThickness", 8.0), 8.0),
            "instance_number": _safe_int(getattr(ds, "InstanceNumber", 0)),
            "trigger_time": _safe_float(getattr(ds, "TriggerTime", 0.0), 0.0),
            "temporal_position": _safe_int(getattr(ds, "TemporalPositionIdentifier", 0), 0),
            "image_position": _image_position(ds),
            "image_orientation": _image_orientation(ds),
        }
        series_groups[series_group_key].append(item)

    if not study_info:
        raise ValueError(
            "No renderable DICOM image objects with positive Rows and Columns "
            "were found in the selected folder."
        )

    dicom_study_uid = study_info["study_uid"]
    _merge_split_sax_series_groups(series_groups, dicom_study_uid)

    with get_conn() as conn:
        # Serialize identity resolution with the replacement write so two
        # simultaneous imports cannot both claim the same raw StudyInstanceUID.
        conn.execute("BEGIN IMMEDIATE")
        internal_study_uid = _resolve_internal_study_uid(
            conn,
            dicom_study_uid=dicom_study_uid,
            source_path=study_info["source_path"],
        )
        existing_state = _snapshot_existing_study_state(
            conn,
            source_path=study_info["source_path"],
        )
        _scope_series_groups_to_study(
            series_groups,
            dicom_study_uid=dicom_study_uid,
            internal_study_uid=internal_study_uid,
        )
        conn.execute(
            "DELETE FROM studies WHERE source_path = ?",
            (study_info["source_path"],),
        )

        conn.execute(
            """
            INSERT INTO studies (
              study_uid, patient_name, patient_id, patient_sex, patient_age, study_date, accession_number, source_path, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                internal_study_uid,
                study_info["patient_name"],
                study_info["patient_id"],
                study_info["patient_sex"],
                study_info["patient_age"],
                study_info["study_date"],
                study_info["accession_number"],
                study_info["source_path"],
                utcnow(),
            ),
        )
        study_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

        for series_uid, items in series_groups.items():
            first = items[0]
            normal = _normal_from_orientation(first["image_orientation"])
            for item in items:
                item["normal_position"] = _position_key(item["image_position"], normal)
                item["position_group"] = _position_group(item["image_position"])

            grouped_by_position: dict[tuple[float, float, float], list[dict[str, Any]]] = defaultdict(list)
            for item in items:
                grouped_by_position[item["position_group"]].append(item)

            positions = sorted(
                grouped_by_position.keys(),
                key=lambda position_group: max(frame["normal_position"] for frame in grouped_by_position[position_group]),
                reverse=True,
            )

            ordered_frames: list[dict[str, Any]] = []
            phase_count = max(len(grouped_by_position[pos]) for pos in positions)
            for slice_index, position in enumerate(positions):
                phase_group = sorted(
                    grouped_by_position[position],
                    key=lambda value: (
                        value["temporal_position"],
                        value["trigger_time"],
                        value["instance_number"],
                    ),
                )
                for phase_index, frame in enumerate(phase_group):
                    ordered_frames.append({**frame, "slice_index": slice_index, "phase_index": phase_index})

            role = infer_role(
                Path(first["folder_path"]),
                first["series_description"],
                len(positions),
                phase_count,
                protocol_name=first.get("protocol_name", ""),
                image_type=first.get("image_type", ""),
                scanning_sequence=first.get("scanning_sequence", ""),
                sequence_variant=first.get("sequence_variant", ""),
                mr_acquisition_type=first.get("mr_acquisition_type", ""),
                philips_slice_orientation=first.get("philips_slice_orientation", ""),
            )
            role = normalize_series_role(
                first["folder_path"],
                first["series_description"],
                role,
                len(positions),
                phase_count,
                protocol_name=first.get("protocol_name", ""),
                image_type=first.get("image_type", ""),
                scanning_sequence=first.get("scanning_sequence", ""),
                sequence_variant=first.get("sequence_variant", ""),
                mr_acquisition_type=first.get("mr_acquisition_type", ""),
                philips_slice_orientation=first.get("philips_slice_orientation", ""),
            )
            has_predictions = int((Path(first["folder_path"]) / "predictions").exists())
            conn.execute(
                """
                INSERT INTO series (
                  study_id, series_uid, description, role, rows, cols, pixel_spacing_x, pixel_spacing_y,
                  slice_thickness, file_count, slice_count, phase_count, orientation, folder_path,
                  has_predictions, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    study_id,
                    series_uid,
                    first["series_description"],
                    role,
                    first["rows"],
                    first["cols"],
                    first["pixel_spacing_x"],
                    first["pixel_spacing_y"],
                    first["slice_thickness"],
                    len(items),
                    len(positions),
                    phase_count,
                    orientation_label(first["series_description"], role),
                    first["folder_path"],
                    has_predictions,
                    dumps(
                        {
                            "normal_vector": [float(x) for x in normal],
                            "image_orientation": first["image_orientation"],
                            "dicom_tags": {
                                "protocol_name": first.get("protocol_name", ""),
                                "image_type": first.get("image_type", ""),
                                "scanning_sequence": first.get("scanning_sequence", ""),
                                "sequence_variant": first.get("sequence_variant", ""),
                                "mr_acquisition_type": first.get("mr_acquisition_type", ""),
                                "philips_slice_orientation": first.get("philips_slice_orientation", ""),
                            },
                        }
                    ),
                    utcnow(),
                ),
            )
            series_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            for frame_index, frame in enumerate(sorted(ordered_frames, key=lambda item: (item["slice_index"], item["phase_index"]))):
                conn.execute(
                    """
                    INSERT INTO frames (
                      series_id, frame_uid, frame_index, slice_index, phase_index, instance_number, trigger_time,
                      temporal_position, file_path, image_position_json, normal_position, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        series_id,
                        f"{series_uid}:{frame['slice_index']}:{frame['phase_index']}",
                        frame_index,
                        frame["slice_index"],
                        frame["phase_index"],
                        frame["instance_number"],
                        frame["trigger_time"],
                        frame["temporal_position"],
                        frame["file_path"],
                        dumps(frame["image_position"]),
                        frame["normal_position"],
                        dumps(
                            {
                                "rows": frame["rows"],
                                "cols": frame["cols"],
                                "pixel_spacing": [frame["pixel_spacing_x"], frame["pixel_spacing_y"]],
                                "slice_thickness": frame["slice_thickness"],
                                "image_orientation": frame["image_orientation"],
                            }
                        ),
                    ),
                )

        conn.execute(
            "INSERT INTO reports (study_id, status, findings, summary, payload_json, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (study_id, "草稿", "", "", dumps({}), utcnow()),
        )
        _restore_study_state(conn, study_id=study_id, snapshot=existing_state)
    return study_id


def fetch_study_detail(study_id: int, default_sample_path: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        study = conn.execute("SELECT * FROM studies WHERE id = ?", (study_id,)).fetchone()
        if study is None:
            return None
        study_data = {key: study[key] for key in study.keys()}
        if not study_data.get("patient_sex") or not study_data.get("patient_age"):
            derived = _study_patient_demographics_from_source(study_data.get("source_path") or "")
            next_sex = study_data.get("patient_sex") or derived["patient_sex"]
            next_age = study_data.get("patient_age") or derived["patient_age"]
            if next_sex != (study_data.get("patient_sex") or "") or next_age != (study_data.get("patient_age") or ""):
                conn.execute(
                    "UPDATE studies SET patient_sex = ?, patient_age = ? WHERE id = ?",
                    (next_sex, next_age, study_id),
                )
                study_data["patient_sex"] = next_sex
                study_data["patient_age"] = next_age
        series_rows = conn.execute("SELECT * FROM series WHERE study_id = ? ORDER BY id", (study_id,)).fetchall()
        measurement_rows = conn.execute(
            """
            SELECT series_id, module, payload_json
            FROM measurements
            WHERE series_id IN (SELECT id FROM series WHERE study_id = ?)
            """,
            (study_id,),
        ).fetchall()
        measurements = {(row["series_id"], row["module"]): loads(row["payload_json"], {}) for row in measurement_rows}
        report = conn.execute("SELECT * FROM reports WHERE study_id = ?", (study_id,)).fetchone()
        report_payload = {
            "study_id": study["id"],
            "status": report["status"],
            "findings": report["findings"] or "",
            "summary": report["summary"] or "",
            "payload": loads(report["payload_json"], {}),
        }

        series_payload = []
        for row in series_rows:
            frames = conn.execute(
                """
                SELECT id, slice_index, phase_index, instance_number, trigger_time, file_path, image_position_json, metadata_json
                FROM frames
                WHERE series_id = ?
                ORDER BY slice_index, phase_index
                """,
                (row["id"],),
            ).fetchall()
            latest_measurement = measurements.get((row["id"], "function")) or measurements.get((row["id"], "lge"))
            series_payload.append(
                {
                    "id": row["id"],
                    "study_id": row["study_id"],
                    "description": row["description"] or "",
                    "role": row["role"],
                    "rows": row["rows"] or 0,
                    "cols": row["cols"] or 0,
                    "file_count": row["file_count"],
                    "slice_count": row["slice_count"],
                    "phase_count": row["phase_count"],
                    "pixel_spacing": [row["pixel_spacing_x"] or 1.0, row["pixel_spacing_y"] or 1.0],
                    "slice_thickness": row["slice_thickness"] or 8.0,
                    "orientation": row["orientation"],
                    "folder_path": row["folder_path"],
                    "has_predictions": bool(row["has_predictions"]),
                    "default_slice": max(0, row["slice_count"] // 2),
                    "default_phase": 0,
                    "frames": [
                        {
                            "id": frame["id"],
                            "slice_index": frame["slice_index"],
                            "phase_index": frame["phase_index"],
                            "instance_number": frame["instance_number"],
                            "trigger_time": frame["trigger_time"],
                            "file_path": "",
                            "image_position": loads(frame["image_position_json"], []),
                            "image_orientation": loads(frame["metadata_json"], {}).get("image_orientation", []),
                            "pixel_spacing": loads(frame["metadata_json"], {}).get("pixel_spacing", []),
                        }
                        for frame in frames
                    ],
                    "latest_measurement": latest_measurement,
                }
            )

        return {
            "id": study["id"],
            "study_uid": _public_study_label(study["id"]),
            "patient_name": "匿名患者",
            "patient_id": _public_patient_id_from_source(
                study_data.get("source_path") or "",
                _public_study_label(study["id"]),
            ),
            "patient_sex": study_data.get("patient_sex") or "",
            "patient_age": study_data.get("patient_age") or "",
            "study_date": study_data.get("study_date") or "",
            "accession_number": "",
            "source_path": "已隐藏",
            "default_sample_path": default_sample_path,
            "series": series_payload,
            "report": report_payload,
        }


def update_series_role(series_id: int, role: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE series SET role = ?, orientation = ? WHERE id = ?", (role, orientation_label("", role), series_id))


def get_series_row(series_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM series WHERE id = ?", (series_id,)).fetchone()
        if row is None:
            raise KeyError(series_id)
        return {key: row[key] for key in row.keys()}


def get_frame_row(series_id: int, slice_index: int, phase_index: int) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM frames
            WHERE series_id = ? AND slice_index = ? AND phase_index = ?
            """,
            (series_id, slice_index, phase_index),
        ).fetchone()
        if row is None:
            fallback = conn.execute(
                """
                SELECT *
                FROM frames
                WHERE series_id = ? AND slice_index = ?
                ORDER BY ABS(phase_index - ?) ASC
                LIMIT 1
                """,
                (series_id, slice_index, phase_index),
            ).fetchone()
            if fallback is None:
                raise KeyError((series_id, slice_index, phase_index))
            row = fallback
        return {key: row[key] for key in row.keys()}


def list_frame_rows(series_id: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM frames WHERE series_id = ? ORDER BY slice_index, phase_index", (series_id,)).fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]


def read_frame_pixels(frame_row: dict[str, Any]) -> np.ndarray:
    ds = pydicom.dcmread(frame_row["file_path"], force=True)
    raw = ds.pixel_array.astype(np.float32)
    arr = raw
    try:
        arr = apply_voi_lut(raw, ds)
    except Exception:
        arr = raw
    arr = arr.astype(np.float32)
    raw_low, raw_high = np.percentile(raw, [1, 99])
    arr_low, arr_high = np.percentile(arr, [1, 99])
    raw_robust_range = float(raw_high - raw_low)
    arr_robust_range = float(arr_high - arr_low)
    voi_is_collapsed = float(arr.max()) <= float(arr.min())
    voi_is_saturated = raw_robust_range > 0 and arr_robust_range <= max(1.0, raw_robust_range * 0.05)
    if (voi_is_collapsed or voi_is_saturated) and float(raw.max()) > float(raw.min()):
        arr = raw
    if getattr(ds, "PhotometricInterpretation", "") == "MONOCHROME1":
        arr = arr.max() - arr
    low, high = np.percentile(arr, [1, 99])
    if high > low:
        arr = np.clip(arr, low, high)
    arr = arr - float(arr.min())
    peak = float(arr.max())
    if peak <= 0:
        return np.zeros_like(arr, dtype=np.uint8)
    arr /= peak
    arr *= 255.0
    return arr.astype(np.uint8)
