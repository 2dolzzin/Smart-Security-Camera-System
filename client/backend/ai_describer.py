"""
ai_describer.py
녹화 영상을 전처리한 뒤 VLM 어댑터 서버(server/app.py)로 전송하고,
응답으로 받은 창 단위 구조화 로그와 임베딩을 motion_logs 에 기록한다.

처리 순서:
  녹화 mp4 → downsample_video() → POST {VLM_SERVER_URL}/describe → 응답 logs[]
    → 첫 창은 세션 종료 시 생성된 로그 행을 갱신하고, 나머지 창은 새 행으로 추가

describe_recording() 은 recorder 의 백그라운드 스레드에서 호출되므로
이 모듈의 함수는 모두 동기(blocking) 방식이다.

환경변수:
  VLM_SERVER_URL   VLM 어댑터 주소. 예: http://localhost:8010
                   비어 있으면 서버 호출을 생략하고 FALLBACK_DESC 를 기록한다.
  VLM_TIMEOUT      서버 응답 타임아웃(초). 기본 300
  VLM_WINDOW_SEC   서버 창 길이(3~120초). 비우면 서버 기본값
  VLM_QUESTION     /describe 의 question 필드로 전달할 문자열. 서버는 이 값을 사용하지 않는다.
"""

import os
from pathlib import Path

import httpx

from preprocess import downsample_video
from database import (
    update_motion_log_description, update_motion_log_vlm, insert_window_log, get_motion_log_by_id,
)
from datetime import datetime

FALLBACK_DESC = "움직임 감지됨"

VLM_SERVER_URL = os.getenv("VLM_SERVER_URL", "").rstrip("/")
VLM_TIMEOUT = float(os.getenv("VLM_TIMEOUT", "300"))
VLM_WINDOW_SEC = os.getenv("VLM_WINDOW_SEC", "").strip()
VLM_QUESTION = os.getenv("VLM_QUESTION", "")


def describe_video(video_path: Path) -> dict | None:
    """
    전처리된 영상을 VLM 어댑터 /describe 로 업로드하고 응답 JSON 을 반환한다.
    서버 주소가 없거나 요청이 실패하면 None.
    """
    if not VLM_SERVER_URL:
        print("[VLM] VLM_SERVER_URL 미설정 — 서버 호출 생략")
        return None

    url = f"{VLM_SERVER_URL}/describe"
    try:
        data = {}
        if VLM_QUESTION:
            data["question"] = VLM_QUESTION
        if VLM_WINDOW_SEC:
            data["window_sec"] = VLM_WINDOW_SEC
        with open(video_path, "rb") as f:
            files = {"file": (Path(video_path).name, f, "video/mp4")}
            resp = httpx.post(url, files=files, data=data or None, timeout=VLM_TIMEOUT)
        resp.raise_for_status()
        body = resp.json()
        n = len(body.get("logs") or [])
        n_anom = sum(1 for e in body.get("logs") or [] if (e.get("log") or {}).get("is_anomaly") == "이상")
        print(f"[VLM] 응답: 창 {n}개, 이상 {n_anom}개, '{body.get('description', '')}' ({body.get('elapsed_sec')}s)")
        return body
    except Exception as e:
        print(f"[VLM] 서버 호출 오류 ({url}): {e}")
        return None


def embed_text(text: str) -> list[float] | None:
    """텍스트를 서버 /embed 로 임베딩한다. 실패하면 None."""
    if not VLM_SERVER_URL or not text.strip():
        return None
    try:
        resp = httpx.post(f"{VLM_SERVER_URL}/embed", json={"text": text}, timeout=30)
        resp.raise_for_status()
        return resp.json().get("embedding")
    except Exception as e:
        print(f"[VLM] /embed 오류: {e}")
        return None


def _store_logs(log_id: int, body: dict) -> str:
    """
    어댑터 응답의 logs[] 를 motion_logs 에 기록한다.
    첫 창은 기존 행(log_id)을 갱신하고 나머지 창은 새 행으로 추가한다.
    반환: 첫 로그의 summary. 기록할 로그가 없으면 빈 문자열.
    """
    entries = [e for e in (body.get("logs") or []) if e.get("log")]
    if not entries:
        return ""

    base = get_motion_log_by_id(log_id)
    recording_id = base["recording_id"] if base else 0
    intensity = base["intensity"] if base else 0.0
    try:
        started_at = datetime.fromisoformat(base["detected_at"]) if base else datetime.now()
    except Exception:
        started_at = datetime.now()

    first = entries[0]
    update_motion_log_vlm(log_id, first["log"], first["window_start"], first["window_end"], first.get("embedding"))
    for e in entries[1:]:
        insert_window_log(recording_id, started_at, intensity,
                          e["log"], e["window_start"], e["window_end"], e.get("embedding"))
    return first["log"].get("summary") or FALLBACK_DESC


def describe_recording(log_id: int, video_path: Path) -> None:
    """
    녹화 영상 1개를 전처리하고 VLM 로그를 생성해 motion_logs 에 기록한다.

    전처리 결과는 녹화 파일과 같은 폴더에 `<이름>_vlm.mp4` 로 보관한다.
    이 파일은 해당 녹화가 삭제될 때 함께 삭제된다.
    """
    video_path = Path(video_path)
    vlm_path = video_path.with_name(f"{video_path.stem}_vlm.mp4")

    description = ""
    try:
        if downsample_video(video_path, vlm_path):
            print(f"[VLM] 전처리 영상 보관: {vlm_path}")
            body = describe_video(vlm_path)
            if body:
                description = _store_logs(log_id, body)
        else:
            vlm_path.unlink(missing_ok=True)
    except Exception as e:
        print(f"[VLM] 처리 오류 (log_id={log_id}): {e}")

    if not description:
        # VLM 로그를 얻지 못한 경우 기본 문구만 기록
        update_motion_log_description(log_id, FALLBACK_DESC)
        description = FALLBACK_DESC
    print(f"[VLM] 로그 기록 완료 id={log_id}: {description}")
