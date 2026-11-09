"""
ai_describer.py
모션 세션 종료 시 만들어진 녹화 영상을 전처리한 뒤, GPU 서버의 VLM 어댑터(server/app.py)로 보내
**구조화 로그**(장소·객체·행동·이상여부·이상유형·요약 + 임베딩)를 받아 motion_logs 에 기록한다.

흐름:
  녹화 mp4 완성 → downsample_video() → POST {VLM_SERVER_URL}/describe
    → 응답 logs[] (20초 창마다 1개)
    → 첫 창은 세션 종료 시 만들어 둔 로그 행을 채우고(update), 나머지 창은 새 행 insert

호출 위치:
  recorder.Recorder.stop_recording(on_complete=...) 콜백 (백그라운드 스레드)에서
  describe_recording(log_id, final_path) 가 불린다. 따라서 이 모듈의 함수는 모두 동기(blocking).

환경변수:
  VLM_SERVER_URL   VLM 어댑터 주소. 예: http://localhost:8010 (SSH 터널) / http://<서버IP>:8010 (LAN)
                   비어 있으면 서버 호출을 건너뛰고 폴백 문구를 쓴다.
  VLM_TIMEOUT      서버 응답 타임아웃(초). 기본 300. 서버는 20초 창당 약 2초 걸리므로
                   10분 녹화(30창)면 60초 이상 필요.
  VLM_WINDOW_SEC   (선택) 서버 창 길이 덮어쓰기(3~120). 비우면 서버 기본(20초).
  VLM_QUESTION     (구버전 호환) 보내긴 하지만 서버가 무시한다.
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
    전처리된(가벼운) 영상을 VLM 어댑터 /describe 로 업로드하여 응답 JSON 전체를 반환.
    서버 미설정/오류 시 None.
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
    """검색 질의 임베딩. 서버 /embed 호출. 실패 시 None."""
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
    어댑터 응답의 logs[] 를 motion_logs 에 기록. 첫 창 → 기존 행 update, 나머지 → insert.
    반환: 첫 로그의 description (콘솔 출력용).
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
    녹화 영상 1개에 대해: 전처리 → VLM 구조화 로그 생성 → motion_logs 기록(창 수만큼).
    recorder 의 백그라운드 스레드에서 호출된다.

    전처리 결과(VLM 에 실제로 보낸 360p·4fps mp4)는 삭제하지 않고
    녹화 파일 옆에 `<같은이름>_vlm.mp4` 로 남겨둔다 — 개발자가 직접 확인용.
    (해당 녹화를 삭제하거나 30일 정리 시 함께 삭제됨)
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
            vlm_path.unlink(missing_ok=True)   # 전처리 실패 → 빈/깨진 파일 정리
    except Exception as e:
        print(f"[VLM] 처리 오류 (log_id={log_id}): {e}")

    if not description:
        # 서버 미설정/실패/파싱 실패 → 기존 폴백 (단일 로그, 구조화 필드 비움)
        update_motion_log_description(log_id, FALLBACK_DESC)
        description = FALLBACK_DESC
    print(f"[VLM] 로그 기록 완료 id={log_id}: {description}")
