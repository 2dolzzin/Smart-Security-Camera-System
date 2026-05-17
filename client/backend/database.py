"""
database.py
SQLite 데이터베이스 초기화 및 쿼리 헬퍼
"""

import sqlite3
import os
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "cctv.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """테이블 생성 (최초 실행 시)"""
    conn = get_connection()
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS recordings (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            filename        TEXT NOT NULL,
            filepath        TEXT NOT NULL,
            started_at      DATETIME NOT NULL,
            ended_at        DATETIME,
            duration_sec    INTEGER,
            file_size_mb    REAL
        );

        CREATE TABLE IF NOT EXISTS motion_logs (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            recording_id            INTEGER REFERENCES recordings(id),
            detected_at             DATETIME NOT NULL,
            duration_sec            REAL,
            intensity               REAL,
            timestamp_offset_sec    REAL,
            description             TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            key     TEXT PRIMARY KEY,
            value   TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_recordings_started
            ON recordings(started_at);

        CREATE INDEX IF NOT EXISTS idx_motion_detected
            ON motion_logs(detected_at);
    """)

    conn.commit()
    conn.close()
    print("[DB] 초기화 완료:", DB_PATH)


# ──────────────────────────────────────────────
# recordings 헬퍼
# ──────────────────────────────────────────────

def insert_recording(filename: str, filepath: str, started_at: datetime) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO recordings (filename, filepath, started_at) VALUES (?, ?, ?)",
        (filename, filepath, started_at.isoformat())
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


def close_recording(recording_id: int, ended_at: datetime, duration_sec: int, file_size_mb: float):
    conn = get_connection()
    conn.execute(
        """UPDATE recordings
           SET ended_at=?, duration_sec=?, file_size_mb=?
           WHERE id=?""",
        (ended_at.isoformat(), duration_sec, file_size_mb, recording_id)
    )
    conn.commit()
    conn.close()


def get_recordings(date_str: str | None = None):
    """날짜(YYYY-MM-DD) 필터 또는 전체 목록"""
    conn = get_connection()
    if date_str:
        rows = conn.execute(
            "SELECT * FROM recordings WHERE started_at LIKE ? ORDER BY started_at DESC",
            (f"{date_str}%",)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM recordings ORDER BY started_at DESC LIMIT 200"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recording_by_id(recording_id: int):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM recordings WHERE id=?", (recording_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_recording(recording_id: int):
    """녹화 DB 레코드 + 연결된 motion_logs 삭제 (파일 삭제는 호출자가)."""
    conn = get_connection()
    conn.execute("DELETE FROM motion_logs WHERE recording_id=?", (recording_id,))
    conn.execute("DELETE FROM recordings WHERE id=?", (recording_id,))
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────
# motion_logs 헬퍼
# ──────────────────────────────────────────────

def insert_motion_log(
    recording_id: int,
    detected_at: datetime,
    duration_sec: float,
    intensity: float,
    timestamp_offset_sec: float,
    description: str = ""
) -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO motion_logs
           (recording_id, detected_at, duration_sec, intensity, timestamp_offset_sec, description)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (recording_id, detected_at.isoformat(), duration_sec,
         intensity, timestamp_offset_sec, description)
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


def update_motion_log_description(log_id: int, description: str):
    conn = get_connection()
    conn.execute(
        "UPDATE motion_logs SET description=? WHERE id=?",
        (description, log_id)
    )
    conn.commit()
    conn.close()


def get_motion_logs(period: str = "day"):
    """
    period: 'day' | 'week' | 'month'
    최신순 정렬
    """
    period_map = {"day": 1, "week": 7, "month": 30}
    days = period_map.get(period, 1)

    conn = get_connection()
    # detected_at 은 로컬 시각 ISO 문자열('YYYY-MM-DDTHH:MM:SS...').
    # 'T' 구분자를 공백으로 바꿔 SQLite datetime 과 사전식 비교가 맞도록 하고,
    # 'localtime' 으로 로컬 기준 N일 범위를 계산한다.
    rows = conn.execute(
        """SELECT ml.*, r.filepath, r.filename
           FROM motion_logs ml
           LEFT JOIN recordings r ON ml.recording_id = r.id
           WHERE replace(ml.detected_at, 'T', ' ') >= datetime('now', 'localtime', ?)
           ORDER BY ml.detected_at DESC""",
        (f"-{days} days",)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_motion_log_by_id(log_id: int):
    conn = get_connection()
    row = conn.execute(
        """SELECT ml.*, r.filepath, r.filename
           FROM motion_logs ml
           LEFT JOIN recordings r ON ml.recording_id = r.id
           WHERE ml.id=?""",
        (log_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ──────────────────────────────────────────────
# settings (key-value) 헬퍼
# ──────────────────────────────────────────────

def get_setting(key: str, default=None):
    """저장된 설정값(문자열) 반환. 없으면 default."""
    conn = get_connection()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value):
    conn = get_connection()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    conn.commit()
    conn.close()
