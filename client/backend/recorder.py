"""
recorder.py - 이벤트 기반 녹화 모듈

코덱 선택:
1. OpenCV 로 avc1(H.264) 저장을 시도한다.
2. avc1 을 쓸 수 없으면 mp4v 로 저장한 뒤 FFmpeg 로 컨테이너를 remux 한다 (-c copy, +faststart).
3. FFmpeg 가 없으면 mp4v 파일을 그대로 최종 파일로 사용한다.

녹화 시작/종료 시점은 camera.MotionSession 이 결정한다.
"""

import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from database import insert_recording, close_recording, get_connection

RECORDINGS_DIR = Path(__file__).parent / "recordings"
FPS    = 15
WIDTH  = 1280
HEIGHT = 720


def _pick_fourcc() -> tuple[int, str]:
    """
    플랫폼에서 사용 가능한 코덱 선택.
    avc1 → H.264 직접 저장 (FFmpeg 불필요)
    mp4v → MPEG-4, 이후 FFmpeg으로 remux 필요
    """
    # avc1 지원 여부 확인 (임시 파일로 테스트)
    test_path = RECORDINGS_DIR / "_codec_test.mp4"
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        fourcc = cv2.VideoWriter_fourcc(*"avc1")
        writer = cv2.VideoWriter(str(test_path), fourcc, 15, (64, 64))
        if writer.isOpened():
            writer.write(np.zeros((64, 64, 3), dtype=np.uint8))
            writer.release()
            if test_path.exists() and test_path.stat().st_size > 1000:
                test_path.unlink(missing_ok=True)
                print("[Recorder] 코덱: avc1 (H.264 직접 저장)")
                return fourcc, "avc1"
        writer.release()
    except Exception:
        pass
    finally:
        test_path.unlink(missing_ok=True)

    print("[Recorder] 코덱: mp4v (FFmpeg remux 필요)")
    return cv2.VideoWriter_fourcc(*"mp4v"), "mp4v"


# 앱 시작 시 1회만 코덱 결정
_FOURCC, _CODEC_NAME = _pick_fourcc()


def _finalize_file(tmp_path: Path, final_path: Path,
                   recording_id: int, ended_at: datetime, duration: int,
                   on_complete: Optional[Callable[[Path], None]] = None):
    """
    백그라운드 스레드:
    avc1이면 rename만, mp4v이면 FFmpeg remux 시도.
    어떤 경우든 최종 파일이 생기도록 보장.
    최종 파일이 준비되면 on_complete(final_path) 콜백을 호출한다.
    """
    def _update_db():
        if final_path.exists() and final_path.stat().st_size > 0:
            size_mb = round(final_path.stat().st_size / (1024 * 1024), 2)
            close_recording(recording_id, ended_at, duration, size_mb)
            print(f"[Recorder] 완료: {final_path.name} ({duration}초, {size_mb}MB)")
            if on_complete:
                try:
                    on_complete(final_path)
                except Exception as e:
                    print(f"[Recorder] on_complete 콜백 오류: {e}")

    # ── avc1: 그냥 rename ──
    if _CODEC_NAME == "avc1":
        try:
            tmp_path.rename(final_path)
        except Exception as e:
            print(f"[Recorder] rename 실패: {e}")
            try:
                import shutil
                shutil.copy2(str(tmp_path), str(final_path))
                tmp_path.unlink(missing_ok=True)
            except Exception as e2:
                print(f"[Recorder] copy 실패: {e2}")
        _update_db()
        return

    # ── mp4v: FFmpeg remux 시도 ──
    # -movflags +faststart : moov atom을 앞으로 → 브라우저 스트리밍 가능
    # -c copy              : 재인코딩 없이 컨테이너만 변환
    cmd = [
        "ffmpeg", "-y",
        "-i", str(tmp_path),
        "-c", "copy",
        "-movflags", "+faststart",
        str(final_path),
    ]
    print(f"[Recorder] FFmpeg remux: {tmp_path.name} → {final_path.name}")
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode == 0 and final_path.exists() and final_path.stat().st_size > 0:
            tmp_path.unlink(missing_ok=True)
            _update_db()
            return
        else:
            err = result.stderr.decode(errors="replace")
            print(f"[Recorder] FFmpeg remux 실패:\n{err}")
    except FileNotFoundError:
        print("[Recorder] FFmpeg 없음 — 임시 파일을 최종 파일로 사용")
    except subprocess.TimeoutExpired:
        print("[Recorder] FFmpeg 타임아웃")
    except Exception as e:
        print(f"[Recorder] FFmpeg 예외: {e}")

    # FFmpeg 실패 → tmp 파일 자체를 최종 파일로 사용
    try:
        if final_path.exists():
            final_path.unlink()
        tmp_path.rename(final_path)
    except Exception as e:
        print(f"[Recorder] 폴백 rename 실패: {e}")
    _update_db()


class Recorder:
    def __init__(self):
        self._writer: Optional[cv2.VideoWriter] = None
        self._recording_id: Optional[int] = None
        self._started_at: Optional[datetime] = None
        self._frame_count: int = 0
        self._final_path: Optional[Path] = None
        self._tmp_path: Optional[Path] = None
        self._is_recording: bool = False
        self.fps: float = float(FPS)   # 녹화 파일 fps

    def _make_paths(self, dt: datetime) -> tuple[Path, Path]:
        date_dir = RECORDINGS_DIR / dt.strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)
        stem  = dt.strftime("%H-%M-%S")
        final = date_dir / f"{stem}.mp4"
        tmp   = date_dir / f"{stem}_raw.mp4"
        return final, tmp

    def start_recording(self) -> bool:
        if self._is_recording:
            return False

        now = datetime.now()
        self._final_path, self._tmp_path = self._make_paths(now)

        self._writer = cv2.VideoWriter(
            str(self._tmp_path), _FOURCC, self.fps, (WIDTH, HEIGHT)
        )
        if not self._writer.isOpened():
            print(f"[Recorder] VideoWriter 열기 실패 (코덱: {_CODEC_NAME})")
            self._writer = None
            return False

        self._started_at  = now
        self._frame_count = 0
        self._is_recording = True
        self._recording_id = insert_recording(
            filename=self._final_path.name,
            filepath=str(self._final_path),
            started_at=now,
        )
        print(f"[Recorder] 녹화 시작: {self._final_path.name} (코덱: {_CODEC_NAME})")
        return True

    def stop_recording(self, on_complete: Optional[Callable[[Path], None]] = None):
        """
        녹화 종료. on_complete 가 주어지면 최종 mp4 파일이 준비된 직후
        on_complete(final_path) 가 백그라운드 스레드에서 호출된다.
        """
        if not self._is_recording or not self._writer:
            return

        self._writer.release()
        self._writer = None
        self._is_recording = False

        if not (self._recording_id and self._started_at and self._tmp_path):
            return

        # 값을 로컬에 복사한 뒤 즉시 초기화 (스레드 안전)
        recording_id = self._recording_id
        started_at   = self._started_at
        tmp_path     = self._tmp_path
        final_path   = self._final_path
        frame_count  = self._frame_count

        self._recording_id = None
        self._started_at   = None
        self._final_path   = None
        self._tmp_path     = None
        self._frame_count  = 0

        ended_at = datetime.now()
        duration = int((ended_at - started_at).total_seconds())

        if frame_count > 0 and tmp_path.exists() and tmp_path.stat().st_size > 0:
            t = threading.Thread(
                target=_finalize_file,
                args=(tmp_path, final_path, recording_id, ended_at, duration, on_complete),
                daemon=True,
            )
            t.start()
        else:
            print(f"[Recorder] 프레임 없음(count={frame_count}) — 파일 생략")
            tmp_path.unlink(missing_ok=True)
            conn = get_connection()
            conn.execute("DELETE FROM recordings WHERE id=?", (recording_id,))
            conn.commit()
            conn.close()

    def write_frame(self, frame: np.ndarray):
        if not self._is_recording or not self._writer:
            return
        resized = cv2.resize(frame, (WIDTH, HEIGHT))
        self._writer.write(resized)
        self._frame_count += 1

    def stop(self):
        if self._is_recording:
            self.stop_recording()
        print("[Recorder] 종료")

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def current_recording_id(self) -> Optional[int]:
        return self._recording_id
