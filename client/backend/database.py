"""
database.py
SQLite 데이터베이스 초기화 및 쿼리 헬퍼
"""

import json
import sqlite3
import os
from datetime import datetime
from pathlib import Path

import numpy as np

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
            description             TEXT,
            -- VLM 구조화 로그. 녹화 1개에 창(window) 단위 로그가 여러 개 연결된다
            window_start            REAL,
            window_end              REAL,
            is_anomaly              INTEGER DEFAULT 0,
            anomaly_type            TEXT,
            scene                   TEXT,
            action                  TEXT,
            objects_json            TEXT,
            summary                 TEXT,
            embedding               BLOB
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
    _migrate_motion_logs(conn)
    conn.close()
    print("[DB] 초기화 완료:", DB_PATH)


# motion_logs 에 추가할 VLM 로그 열. 기존 DB 에 없는 열만 ALTER TABLE 로 추가한다.
VLM_COLUMNS = [
    ("window_start", "REAL"), ("window_end", "REAL"),
    ("is_anomaly", "INTEGER DEFAULT 0"), ("anomaly_type", "TEXT"),
    ("scene", "TEXT"), ("action", "TEXT"), ("objects_json", "TEXT"),
    ("summary", "TEXT"), ("embedding", "BLOB"),
]


def _migrate_motion_logs(conn: sqlite3.Connection):
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(motion_logs)").fetchall()}
    added = []
    for col, typ in VLM_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE motion_logs ADD COLUMN {col} {typ}")
            added.append(col)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_motion_anomaly ON motion_logs(is_anomaly)")
    conn.commit()
    if added:
        print(f"[DB] motion_logs 열 추가: {added}")


# ──────────────────────────────────────────────
# 임베딩 직렬화 (float32 bytes ↔ numpy)
# ──────────────────────────────────────────────

def embedding_to_blob(vec) -> bytes | None:
    if vec is None:
        return None
    return np.asarray(vec, dtype=np.float32).tobytes()


def blob_to_embedding(blob) -> np.ndarray | None:
    if not blob:
        return None
    return np.frombuffer(blob, dtype=np.float32)


def _row_to_log(row) -> dict:
    """motion_logs 행을 API 응답용 dict 로 변환한다. embedding 은 제외하고 objects_json 은 objects 리스트로 파싱한다."""
    d = dict(row)
    d.pop("embedding", None)
    try:
        d["objects"] = json.loads(d.get("objects_json") or "[]")
    except Exception:
        d["objects"] = []
    d["is_anomaly"] = int(d.get("is_anomaly") or 0)
    return d


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


def _vlm_fields(log: dict, window_start: float, window_end: float, embedding) -> dict:
    """VLM 로그 JSON 1개를 motion_logs 열 값 dict 로 변환한다."""
    return {
        "description": log.get("summary") or "움직임 감지됨",
        "window_start": float(window_start),
        "window_end": float(window_end),
        "is_anomaly": 1 if log.get("is_anomaly") == "이상" else 0,
        "anomaly_type": log.get("anomaly_type") or "None",
        "scene": log.get("scene") or "",
        "action": log.get("action") or "",
        "objects_json": json.dumps(log.get("objects") or [], ensure_ascii=False),
        "summary": log.get("summary") or "",
        "embedding": embedding_to_blob(embedding),
    }


def update_motion_log_vlm(log_id: int, log: dict, window_start: float, window_end: float, embedding=None):
    """기존 로그 행에 첫 창의 VLM 결과를 기록한다. timestamp_offset_sec 과 duration_sec 도 창 기준으로 갱신한다."""
    f = _vlm_fields(log, window_start, window_end, embedding)
    f["timestamp_offset_sec"] = f["window_start"]
    f["duration_sec"] = f["window_end"] - f["window_start"]
    cols = ", ".join(f"{k}=?" for k in f)
    conn = get_connection()
    conn.execute(f"UPDATE motion_logs SET {cols} WHERE id=?", (*f.values(), log_id))
    conn.commit()
    conn.close()


def insert_window_log(recording_id: int, started_at: datetime, intensity: float,
                      log: dict, window_start: float, window_end: float, embedding=None) -> int:
    """창 1개의 VLM 결과를 새 로그 행으로 추가한다. detected_at 은 녹화 시작 시각 + 창 시작 오프셋."""
    from datetime import timedelta
    f = _vlm_fields(log, window_start, window_end, embedding)
    detected_at = (started_at + timedelta(seconds=window_start)).isoformat()
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO motion_logs
           (recording_id, detected_at, duration_sec, intensity, timestamp_offset_sec,
            description, window_start, window_end, is_anomaly, anomaly_type, scene, action,
            objects_json, summary, embedding)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (recording_id, detected_at, f["window_end"] - f["window_start"], intensity, f["window_start"],
         f["description"], f["window_start"], f["window_end"], f["is_anomaly"], f["anomaly_type"],
         f["scene"], f["action"], f["objects_json"], f["summary"], f["embedding"])
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


PERIOD_DAYS = {"day": 1, "week": 7, "month": 30}


def _period_clause(period: str):
    # detected_at 은 로컬 시각 ISO 문자열('YYYY-MM-DDTHH:MM:SS...').
    # 'T' 구분자를 공백으로 바꿔 SQLite datetime 과 사전식 비교가 맞도록 하고,
    # 'localtime' 으로 로컬 기준 N일 범위를 계산한다.
    days = PERIOD_DAYS.get(period, 1)
    return "replace(ml.detected_at, 'T', ' ') >= datetime('now', 'localtime', ?)", (f"-{days} days",)


def get_motion_logs(period: str = "day", anomaly_only: bool = False, anomaly_type: str | None = None):
    """
    period: 'day' | 'week' | 'month'. anomaly_only=True 면 is_anomaly=1 만. 최신순 정렬.
    """
    where, params = _period_clause(period)
    if anomaly_only:
        where += " AND ml.is_anomaly = 1"
    if anomaly_type:
        where += " AND ml.anomaly_type = ?"
        params = (*params, anomaly_type)
    conn = get_connection()
    rows = conn.execute(
        f"""SELECT ml.*, r.filepath, r.filename
            FROM motion_logs ml
            LEFT JOIN recordings r ON ml.recording_id = r.id
            WHERE {where}
            ORDER BY ml.detected_at DESC""",
        params,
    ).fetchall()
    conn.close()
    return [_row_to_log(r) for r in rows]


def search_motion_logs(query_vec, period: str = "month", anomaly_only: bool = False, top_k: int = 20):
    """
    질의 임베딩과 로그 임베딩의 코사인 유사도가 높은 순으로 top_k 개를 반환한다.
    각 결과에 score(유사도)를 포함한다.
    """
    where, params = _period_clause(period)
    where += " AND ml.embedding IS NOT NULL"
    if anomaly_only:
        where += " AND ml.is_anomaly = 1"
    conn = get_connection()
    rows = conn.execute(
        f"""SELECT ml.*, r.filepath, r.filename
            FROM motion_logs ml
            LEFT JOIN recordings r ON ml.recording_id = r.id
            WHERE {where}""",
        params,
    ).fetchall()
    conn.close()
    if not rows:
        return []
    q = np.asarray(query_vec, dtype=np.float32)
    q = q / (np.linalg.norm(q) + 1e-8)
    mat = np.stack([blob_to_embedding(r["embedding"]) for r in rows])
    mat = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-8)
    sims = mat @ q
    order = np.argsort(-sims)[:top_k]
    out = []
    for i in order:
        d = _row_to_log(rows[int(i)])
        d["score"] = round(float(sims[i]), 4)
        out.append(d)
    return out


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
    return _row_to_log(row) if row else None


def get_motion_logs_by_recording(recording_id: int):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM motion_logs WHERE recording_id=? ORDER BY timestamp_offset_sec, detected_at",
        (recording_id,)
    ).fetchall()
    conn.close()
    return [_row_to_log(r) for r in rows]


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
