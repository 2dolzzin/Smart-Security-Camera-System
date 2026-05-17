"""
scheduler.py
매일 자정에 30일 이상 된 녹화 파일을 자동 삭제하는 스케줄러.
APScheduler 사용.
"""

import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import get_connection

RECORDINGS_DIR = Path(__file__).parent / "recordings"
RETENTION_DAYS = 30


async def delete_old_recordings():
    """30일 초과 파일 & DB 레코드 삭제"""
    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    cutoff_str = cutoff.isoformat()
    print(f"[Scheduler] 오래된 녹화 삭제 시작 (기준: {cutoff_str})")

    conn = get_connection()

    # 삭제 대상 조회
    rows = conn.execute(
        "SELECT id, filepath FROM recordings WHERE started_at < ?",
        (cutoff_str,)
    ).fetchall()

    deleted_count = 0
    for row in rows:
        rec_id, filepath = row["id"], row["filepath"]

        # 파일 삭제 (본 영상 + 부산물 _raw.mp4 / _vlm.mp4)
        p = Path(filepath)
        for target in (p, p.with_name(f"{p.stem}_raw.mp4"), p.with_name(f"{p.stem}_vlm.mp4")):
            if target.exists():
                try:
                    target.unlink()
                    print(f"[Scheduler] 파일 삭제: {target}")
                except Exception as e:
                    print(f"[Scheduler] 파일 삭제 실패 {target}: {e}")

        # DB에서 연결된 motion_logs 먼저 삭제
        conn.execute("DELETE FROM motion_logs WHERE recording_id=?", (rec_id,))
        # recordings 삭제
        conn.execute("DELETE FROM recordings WHERE id=?", (rec_id,))
        deleted_count += 1

    conn.commit()
    conn.close()

    # 빈 날짜 디렉토리 정리
    _cleanup_empty_dirs()

    print(f"[Scheduler] 완료: {deleted_count}개 녹화 삭제")


def _cleanup_empty_dirs():
    if not RECORDINGS_DIR.exists():
        return
    for date_dir in RECORDINGS_DIR.iterdir():
        if date_dir.is_dir() and not any(date_dir.iterdir()):
            date_dir.rmdir()
            print(f"[Scheduler] 빈 디렉토리 삭제: {date_dir}")


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    # 매일 자정 실행
    scheduler.add_job(
        delete_old_recordings,
        trigger="cron",
        hour=0,
        minute=0,
        id="delete_old_recordings",
    )
    scheduler.start()
    print("[Scheduler] 자동 삭제 스케줄러 시작 (매일 00:00)")
    return scheduler
