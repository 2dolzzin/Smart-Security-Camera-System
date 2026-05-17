"""
main.py
FastAPI 앱 진입점.
- DB 초기화
- 카메라 시작 (상시 자동 녹화)
- 30일 자동 삭제 스케줄러 시작
- 라우터 등록
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from camera import camera_manager
from scheduler import start_scheduler
from routers import stream, recordings, logs, settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── 시작 ──
    print("[Main] 서버 시작")
    init_db()
    await camera_manager.start()
    scheduler = start_scheduler()

    yield

    # ── 종료 ──
    print("[Main] 서버 종료")
    camera_manager.stop()
    scheduler.shutdown()


app = FastAPI(
    title="CCTV 모니터링 시스템",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — React 개발 서버(5173) 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(stream.router)
app.include_router(recordings.router)
app.include_router(logs.router)
app.include_router(settings.router)


@app.get("/")
def health():
    return {"status": "ok", "message": "CCTV 모니터링 시스템 가동 중"}
