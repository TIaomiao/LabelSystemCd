from __future__ import annotations

from ..db import dumps, get_conn, loads, utcnow


def get_report(study_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM reports WHERE study_id = ?", (study_id,)).fetchone()
        if row is None:
            raise KeyError(study_id)
        return {
            "study_id": row["study_id"],
            "status": row["status"],
            "findings": row["findings"] or "",
            "summary": row["summary"] or "",
            "payload": loads(row["payload_json"], {}),
        }


def save_report(study_id: int, payload: dict) -> dict:
    with get_conn() as conn:
        existing = conn.execute("SELECT study_id FROM reports WHERE study_id = ?", (study_id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE reports SET status = ?, findings = ?, summary = ?, payload_json = ?, updated_at = ? WHERE study_id = ?",
                (
                    payload.get("status", "草稿"),
                    payload.get("findings", ""),
                    payload.get("summary", ""),
                    dumps(payload.get("payload", {})),
                    utcnow(),
                    study_id,
                ),
            )
        else:
            conn.execute(
                "INSERT INTO reports (study_id, status, findings, summary, payload_json, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    study_id,
                    payload.get("status", "草稿"),
                    payload.get("findings", ""),
                    payload.get("summary", ""),
                    dumps(payload.get("payload", {})),
                    utcnow(),
                ),
            )
    return get_report(study_id)
