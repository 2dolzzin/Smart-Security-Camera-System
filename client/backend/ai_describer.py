"""
ai_describer.py
모션 세션 종료 시 만들어진 녹화 영상을 전처리한 뒤,
우리가 AWS GPU 인스턴스에 띄운 VLM 서버(server/app.py — Qwen2.5-VL)로 보내
한국어 설명을 받아 해당 motion_log 의 description 으로 기록한다.

흐름:
  녹화 mp4 완성  →  downsample_video()  →  POST {VLM_SERVER_URL}/describe  →  update_motion_log_description()

호출 위치:
  recorder.Recorder.stop_recording(on_complete=...) 콜백 (백그라운드 스레드)에서
  describe_recording(log_id, final_path) 가 불린다. 따라서 이 모듈의 함수는
  모두 동기(blocking) 로 작성한다.

환경변수:
  VLM_SERVER_URL   VLM 서버 주소. 예: http://<aws-public-ip>:8001
                   비어 있으면 서버 호출을 건너뛰고 폴백 문구를 쓴다.
  VLM_TIMEOUT      서버 응답 타임아웃(초). 기본 60.
  VLM_QUESTION     서버에 보낼 질문 텍스트(선택). 없으면 서버 기본 프롬프트 사용.
"""

import os
from pathlib import Path

import httpx

from preprocess import downsample_video
from database import update_motion_log_description

FALLBACK_DESC = "움직임 감지됨"

VLM_SERVER_URL = os.getenv("VLM_SERVER_URL", "").rstrip("/")
VLM_TIMEOUT = float(os.getenv("VLM_TIMEOUT", "60"))
VLM_QUESTION = os.getenv("VLM_QUESTION", "")


def describe_video(video_path: Path) -> str:
    """
    전처리된(가벼운) 영상을 VLM 서버 /describe 로 업로드하여 한국어 설명을 받는다.
    서버 미설정/오류 시 폴백 문구 반환.
    """
    if not VLM_SERVER_URL:
        print("[VLM] VLM_SERVER_URL 미설정 — 서버 호출 생략")
        return FALLBACK_DESC

    url = f"{VLM_SERVER_URL}/describe"
    try:
        with open(video_path, "rb") as f:
            files = {"file": (Path(video_path).name, f, "video/mp4")}
            data = {"question": VLM_QUESTION} if VLM_QUESTION else None
            resp = httpx.post(url, files=files, data=data, timeout=VLM_TIMEOUT)
        resp.raise_for_status()
        body = resp.json()
        desc = (body.get("description") or "").strip()
        if not desc:
            return FALLBACK_DESC
        elapsed = body.get("elapsed_sec")
        print(f"[VLM] 응답: '{desc}'" + (f" ({elapsed}s)" if elapsed is not None else ""))
        return desc
    except Exception as e:
        print(f"[VLM] 서버 호출 오류 ({url}): {e}")
        return FALLBACK_DESC


def describe_recording(log_id: int, video_path: Path) -> None:
    """
    녹화 영상 1개에 대해: 전처리 → VLM 설명 생성 → 로그 description 업데이트.
    recorder 의 백그라운드 스레드에서 호출된다.

    전처리 결과(VLM 에 실제로 보낸 360p·4fps mp4)는 삭제하지 않고
    녹화 파일 옆에 `<같은이름>_vlm.mp4` 로 남겨둔다 — 개발자가 직접 확인용.
    (해당 녹화를 삭제하거나 30일 정리 시 함께 삭제됨)
    """
    video_path = Path(video_path)
    vlm_path = video_path.with_name(f"{video_path.stem}_vlm.mp4")

    description = FALLBACK_DESC
    try:
        if downsample_video(video_path, vlm_path):
            print(f"[VLM] 전처리 영상 보관: {vlm_path}")
            description = describe_video(vlm_path) or FALLBACK_DESC
        else:
            vlm_path.unlink(missing_ok=True)   # 전처리 실패 → 빈/깨진 파일 정리
    except Exception as e:
        print(f"[VLM] 처리 오류 (log_id={log_id}): {e}")

    update_motion_log_description(log_id, description)
    print(f"[VLM] 로그 설명 기록 완료 id={log_id}: {description}")
