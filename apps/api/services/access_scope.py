from __future__ import annotations

from pathlib import Path

from ..db import get_conn


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def source_path_matches_roots(source_path: str, roots: list[str]) -> bool:
    if not isinstance(source_path, str) or not source_path.strip():
        return False
    raw_source = Path(source_path).expanduser().absolute()
    resolved_source = raw_source.resolve(strict=False)
    for raw_root in roots:
        if not isinstance(raw_root, str) or not raw_root.strip():
            continue
        root = Path(raw_root).expanduser().absolute()
        if _path_is_within(raw_source, root) or _path_is_within(
            resolved_source,
            root.resolve(strict=False),
        ):
            return True
    return False


def study_source_matches_roots(study_id: int, roots: list[str]) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT source_path FROM studies WHERE id = ?",
            (study_id,),
        ).fetchone()
    if row is None:
        raise KeyError(study_id)
    return source_path_matches_roots(str(row["source_path"] or ""), roots)


def job_study_scope(job_id: int) -> dict[str, int]:
    """Return the owning study for an inference job without exposing job output."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT jobs.series_id AS series_id, series.study_id AS study_id
            FROM jobs
            JOIN series ON series.id = jobs.series_id
            WHERE jobs.id = ?
            """,
            (job_id,),
        ).fetchone()
    if row is None:
        raise KeyError(job_id)
    return {
        "series_id": int(row["series_id"]),
        "study_id": int(row["study_id"]),
    }
