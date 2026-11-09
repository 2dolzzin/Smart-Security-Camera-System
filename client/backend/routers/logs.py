"""
routers/logs.py
움직임/이상 로그 조회 API.

  GET /api/logs?period=day|week|month&anomaly=1&type=Robbery
  GET /api/logs/search?q=편의점에서 물건을 훔침&period=month&anomaly=1&top_k=20
      → 질의를 VLM 서버 /embed 로 임베딩하고, SQLite 의 로그 임베딩과 코사인 유사도로 상위 N 반환
  GET /api/logs/{id}
"""

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query

from database import get_motion_logs, get_motion_log_by_id, search_motion_logs
from ai_describer import embed_text, VLM_SERVER_URL

router = APIRouter(prefix="/api/logs")

ANOMALY_TYPES = ["Abuse", "Arrest", "Arson", "Assault", "Burglary", "Explosion", "Fighting", "RoadAccidents",
                 "Robbery", "Shooting", "Shoplifting", "Stealing", "Vandalism"]


@router.get("")
def list_logs(
    period: Literal["day", "week", "month"] = Query("day", description="조회 기간: day | week | month"),
    anomaly: int = Query(0, description="1이면 이상 로그만"),
    type: Optional[str] = Query(None, description="이상 유형 필터 (예: Robbery)"),
):
    """
    로그 목록. period에 따라 최근 1일 / 7일 / 30일 범위 반환.
    각 로그는 창(window) 단위: window_start/window_end(녹화 내 초), is_anomaly, anomaly_type,
    scene, action, objects, summary 를 가진다. description 은 summary 와 같음(구버전 UI 호환).
    """
    if type and type not in ANOMALY_TYPES:
        raise HTTPException(status_code=400, detail=f"type 은 {ANOMALY_TYPES} 중 하나")
    rows = get_motion_logs(period=period, anomaly_only=bool(anomaly), anomaly_type=type)
    return {"logs": rows, "total": len(rows), "period": period,
            "anomaly_total": sum(1 for r in rows if r["is_anomaly"])}


@router.get("/search")
def search_logs(
    q: str = Query(..., min_length=1, description="자연어 질의"),
    period: Literal["day", "week", "month"] = Query("month"),
    anomaly: int = Query(0),
    top_k: int = Query(20, ge=1, le=100),
):
    """
    자연어 검색. 질의 임베딩은 서버(/embed)에서, 유사도 계산은 클라이언트(numpy)에서.
    """
    if not VLM_SERVER_URL:
        raise HTTPException(status_code=503, detail="VLM_SERVER_URL 미설정 — 검색 불가")
    vec = embed_text(q)
    if vec is None:
        raise HTTPException(status_code=502, detail="VLM 서버 임베딩 실패")
    rows = search_motion_logs(vec, period=period, anomaly_only=bool(anomaly), top_k=top_k)
    return {"logs": rows, "total": len(rows), "query": q, "period": period}


@router.get("/{log_id}")
def get_log(log_id: int):
    """특정 로그 상세 (연결된 녹화 정보 포함)"""
    row = get_motion_log_by_id(log_id)
    if not row:
        raise HTTPException(status_code=404, detail="로그를 찾을 수 없습니다.")
    return row
