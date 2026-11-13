"""
ingest_video.py
영상 파일을 녹화로 등록하고 VLM 로그를 생성하는 명령행 도구.

카메라 캡처와 움직임 감지를 거치지 않는다. 영상을 recordings/ 에 복사하고
recordings 테이블에 등록한 뒤 ai_describer.describe_recording() 을 호출한다.
백엔드와 같은 cctv.db 를 사용하므로 결과는 /playback 과 /logs 에 표시된다.

사용 (client/backend 에서):
  VLM_SERVER_URL=http://localhost:8010 python ingest_video.py 영상1.mp4 [영상2.mp4 ...]
  옵션:
    --at "2026-11-10 14:30:00"   녹화 시작 시각 (기본: 현재 시각 - 영상 길이)
    --no-copy                    복사하지 않고 원본 경로를 등록

브라우저에서 재생하려면 H.264 mp4 여야 한다. 변환 예:
  ffmpeg -i in.avi -c:v libx264 -pix_fmt yuv420p -movflags +faststart out.mp4
"""

import argparse
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

import cv2

from database import init_db, insert_recording, close_recording, insert_motion_log, get_motion_logs_by_recording
from ai_describer import describe_recording

RECORDINGS_DIR = Path(__file__).parent / "recordings"


def video_duration(path: Path) -> float:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return 0.0
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    cap.release()
    return float(n / fps) if fps > 0 else 0.0


def ingest(src: Path, started_at: datetime | None, copy: bool) -> None:
    src = src.expanduser().resolve()
    if not src.exists():
        print(f"[Ingest] 파일 없음: {src}"); return
    dur = video_duration(src)
    if dur <= 0:
        print(f"[Ingest] 영상을 열 수 없음: {src}"); return

    st = started_at or (datetime.now() - timedelta(seconds=dur))
    if copy:
        date_dir = RECORDINGS_DIR / st.strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)
        dst = date_dir / f"{st.strftime('%H-%M-%S')}_{src.stem}.mp4"
        shutil.copy2(src, dst)
    else:
        dst = src

    rid = insert_recording(dst.name, str(dst), st)
    close_recording(rid, st + timedelta(seconds=dur), int(dur), round(dst.stat().st_size / (1024 * 1024), 2))
    lid = insert_motion_log(rid, st, dur, 1.0, 0.0, "")
    print(f"[Ingest] recording id={rid} {dst.name} ({dur:.1f}s) → VLM 호출 중...")
    describe_recording(lid, dst)

    logs = get_motion_logs_by_recording(rid)
    print(f"[Ingest] 로그 {len(logs)}개, 이상 {sum(l['is_anomaly'] for l in logs)}개")
    for l in logs:
        tag = f"이상·{l['anomaly_type']}" if l["is_anomaly"] else "정상"
        ws, we = l.get("window_start"), l.get("window_end")
        rng = f"{ws:6.1f}-{we:6.1f}s" if ws is not None else "   (창 없음)   "
        print(f"   {rng}  {tag:<14} {l['summary'] or l['description']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("videos", nargs="+", help="영상 파일 경로")
    ap.add_argument("--at", help="녹화 시작 시각 'YYYY-MM-DD HH:MM:SS' (여러 영상이면 순서대로 이어 붙임)")
    ap.add_argument("--no-copy", action="store_true", help="recordings/ 로 복사하지 않음")
    a = ap.parse_args()

    if not os.getenv("VLM_SERVER_URL"):
        print("[Ingest] 경고: VLM_SERVER_URL 미설정 — 로그는 '움직임 감지됨' 폴백만 기록됨", file=sys.stderr)

    init_db()
    t = datetime.strptime(a.at, "%Y-%m-%d %H:%M:%S") if a.at else None
    for v in a.videos:
        p = Path(v)
        ingest(p, t, copy=not a.no_copy)
        if t is not None:
            t = t + timedelta(seconds=video_duration(p) + 1)
