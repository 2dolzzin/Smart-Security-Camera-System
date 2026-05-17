"""
routers/logs.py
움직임 감지 로그 조회 API.
period=day|week|month 필터 지원.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Literal

from database import get_motion_logs, get_motion_log_by_id

router = APIRouter(prefix="/api/logs")


@router.get("")
def list_logs(
    period: Literal["day", "week", "month"] = Query(
        "day", description="조회 기간: day | week | month"
    )
):
    """
    움직임 로그 목록.
    period에 따라 최근 1일 / 7일 / 30일 범위 반환.
    """
    rows = get_motion_logs(period=period)
    return {"logs": rows, "total": len(rows), "period": period}


@router.get("/{log_id}")
def get_log(log_id: int):
    """특정 로그 상세 (연결된 녹화 정보 포함)"""
    row = get_motion_log_by_id(log_id)
    if not row:
        raise HTTPException(status_code=404, detail="로그를 찾을 수 없습니다.")
    return row
