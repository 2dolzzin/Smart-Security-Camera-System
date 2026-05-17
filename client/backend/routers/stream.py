"""
routers/stream.py
WebSocket 실시간 스트리밍 엔드포인트.
클라이언트가 연결되면 CameraManager 구독자로 등록되어
base64 JPEG 프레임을 수신합니다.
"""

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from camera import camera_manager

router = APIRouter()


@router.websocket("/ws/stream")
async def websocket_stream(websocket: WebSocket):
    await websocket.accept()
    queue = camera_manager.subscribe()
    print(f"[WS] 클라이언트 연결: {websocket.client}")

    try:
        while True:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                # 프레임 없음 — keep-alive ping 후 계속 대기
                await websocket.send_text(json.dumps({"ping": True}))
                continue
            await websocket.send_text(json.dumps(data))
    except WebSocketDisconnect:
        print(f"[WS] 클라이언트 연결 종료: {websocket.client}")
    except Exception as e:
        print(f"[WS] 오류: {e}")
    finally:
        camera_manager.unsubscribe(queue)
