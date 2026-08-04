from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterable

from .config import DB_PATH, ensure_runtime_dirs


def utcnow() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    return json.loads(value)


@contextmanager
def get_conn() -> Iterable[sqlite3.Connection]:
    ensure_runtime_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS studies (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              study_uid TEXT NOT NULL UNIQUE,
              patient_name TEXT,
              patient_id TEXT,
              study_date TEXT,
              accession_number TEXT,
              source_path TEXT NOT NULL,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS series (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              study_id INTEGER NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
              series_uid TEXT NOT NULL UNIQUE,
              description TEXT,
              role TEXT NOT NULL,
              rows INTEGER,
              cols INTEGER,
              pixel_spacing_x REAL,
              pixel_spacing_y REAL,
              slice_thickness REAL,
              file_count INTEGER NOT NULL,
              slice_count INTEGER NOT NULL,
              phase_count INTEGER NOT NULL,
              orientation TEXT,
              folder_path TEXT NOT NULL,
              has_predictions INTEGER NOT NULL DEFAULT 0,
              metadata_json TEXT,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS frames (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              series_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
              frame_uid TEXT NOT NULL UNIQUE,
              frame_index INTEGER NOT NULL,
              slice_index INTEGER NOT NULL,
              phase_index INTEGER NOT NULL,
              instance_number INTEGER,
              trigger_time REAL,
              temporal_position INTEGER,
              file_path TEXT NOT NULL,
              image_position_json TEXT,
              normal_position REAL,
              metadata_json TEXT
            );

            CREATE TABLE IF NOT EXISTS contours (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              series_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
              module TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(series_id, module)
            );

            CREATE TABLE IF NOT EXISTS measurements (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              series_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
              module TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(series_id, module)
            );

            CREATE TABLE IF NOT EXISTS jobs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              job_type TEXT NOT NULL,
              study_id INTEGER,
              series_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
              module TEXT NOT NULL,
              status TEXT NOT NULL,
              adapter TEXT NOT NULL,
              request_json TEXT,
              result_json TEXT,
              error TEXT,
              progress_current INTEGER NOT NULL DEFAULT 0,
              progress_total INTEGER NOT NULL DEFAULT 0,
              message TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reports (
              study_id INTEGER PRIMARY KEY REFERENCES studies(id) ON DELETE CASCADE,
              status TEXT NOT NULL,
              findings TEXT,
              summary TEXT,
              payload_json TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        _ensure_column(conn, "jobs", "progress_current", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "jobs", "progress_total", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "jobs", "message", "TEXT")
        _ensure_column(conn, "studies", "patient_sex", "TEXT")
        _ensure_column(conn, "studies", "patient_age", "TEXT")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
