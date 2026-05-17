"""
routers/settings.py
런타임 설정 조회/변경 API.

현재 항목:
  silence_sec  — 마지막 움직임 이후 이 시간(초) 동안 정지가 이어지면 녹화 종료.
                 변경 즉시 반영 (서버 재시작 불필요).
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from camera import camera_manager, MIN_SILENCE_SEC, MAX_SILENCE_SEC

router = APIRouter(prefix="/api/settings")


class SettingsUpdate(BaseModel):
    silence_sec: float | None = Field(
        default=None,
        description=f"녹화 종료까지 무동작 대기 시간(초). {MIN_SILENCE_SEC}~{MAX_SILENCE_SEC}",
    )


def _current() -> dict:
    return {
        "silence_sec": camera_manager.silence_sec,
        "silence_sec_min": MIN_SILENCE_SEC,
        "silence_sec_max": MAX_SILENCE_SEC,
    }


@router.get("")
def get_settings():
    return _current()


@router.put("")
def update_settings(payload: SettingsUpdate):
    if payload.silence_sec is not None:
        try:
            camera_manager.set_silence_sec(payload.silence_sec)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="silence_sec 값이 올바르지 않습니다.")
    return _current()
