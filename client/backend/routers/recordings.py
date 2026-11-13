"""
routers/recordings.py
녹화 목록/상세 조회, 삭제, 영상 스트리밍 API.

  GET    /api/recordings?date=YYYY-MM-DD   녹화 목록 (최종 mp4 파일이 존재하는 것만)
  GET    /api/recordings/{id}              녹화 메타데이터 + 연결된 로그
  DELETE /api/recordings/{id}              영상 파일, DB 레코드, 연결된 로그 삭제
  GET    /api/recordings/{id}/video        영상 스트리밍 (HTTP Range 지원)
"""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from database import (
    get_recordings,
    get_recording_by_id,
    get_connection,
    get_motion_logs_by_recording,
    delete_recording as db_delete_recording,
)

router = APIRouter(prefix="/api/recordings")


@router.get("")
def list_recordings(date: Optional[str] = Query(None, description="YYYY-MM-DD")):
    """
    녹화 목록 조회. 최종 mp4 파일이 존재하는 녹화만 반환한다.
    """
    rows = get_recordings(date_str=date)
    completed = [
        r for r in rows
        if Path(r["filepath"]).exists()
    ]
    return {"recordings": completed, "total": len(completed)}


@router.get("/{recording_id}")
def get_recording(recording_id: int):
    """특정 녹화 메타데이터 + 움직임 로그 조회"""
    row = get_recording_by_id(recording_id)
    if not row:
        raise HTTPException(status_code=404, detail="녹화를 찾을 수 없습니다.")

    return {
        "recording": row,
        "motion_logs": get_motion_logs_by_recording(recording_id),
    }


@router.delete("/{recording_id}")
def delete_recording(recording_id: int):
    """녹화 영상 파일 + DB 레코드 + 연결된 움직임 로그 삭제."""
    row = get_recording_by_id(recording_id)
    if not row:
        raise HTTPException(status_code=404, detail="녹화를 찾을 수 없습니다.")

    # 1) 파일 삭제 (있으면)
    filepath = Path(row["filepath"])
    if filepath.exists():
        try:
            filepath.unlink()
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"파일 삭제 실패: {e}")
    # 부산물 삭제 (_raw.mp4: remux 전 임시 파일, _vlm.mp4: VLM 입력용 전처리 파일)
    filepath.with_name(f"{filepath.stem}_raw.mp4").unlink(missing_ok=True)
    filepath.with_name(f"{filepath.stem}_vlm.mp4").unlink(missing_ok=True)

    # 2) DB 삭제 (motion_logs → recordings)
    db_delete_recording(recording_id)

    return {"deleted": True, "id": recording_id}


@router.get("/{recording_id}/video")
async def stream_video(recording_id: int, request: Request):
    """
    영상 파일 스트리밍. Range 헤더가 있으면 해당 바이트 구간만 206 으로 응답한다.
    """
    row = get_recording_by_id(recording_id)
    if not row:
        raise HTTPException(status_code=404, detail="녹화를 찾을 수 없습니다.")

    filepath = Path(row["filepath"])
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="영상 파일이 없습니다. 변환 중일 수 있습니다.")

    file_size = filepath.stat().st_size
    range_header = request.headers.get("range")

    if range_header:
        try:
            range_val = range_header.strip().replace("bytes=", "")
            start_str, end_str = range_val.split("-")
            start = int(start_str)
            end = int(end_str) if end_str else file_size - 1
        except Exception:
            start, end = 0, file_size - 1
    else:
        start, end = 0, file_size - 1

    end = min(end, file_size - 1)
    chunk_size = end - start + 1

    def iter_file(path: Path, s: int, length: int, buf: int = 1024 * 1024):
        with open(path, "rb") as f:
            f.seek(s)
            remaining = length
            while remaining > 0:
                data = f.read(min(buf, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_size),
        "Content-Type": "video/mp4",
    }

    return StreamingResponse(
        iter_file(filepath, start, chunk_size),
        status_code=206 if range_header else 200,
        headers=headers,
        media_type="video/mp4",
    )
