"""
camera.py
웹캠 캡처 + 실시간 스트리밍 + MotionSession(30초 침묵 감지)

MotionSession 동작:
  움직임 감지 → 녹화 시작
  움직임 있을 때마다 타이머 리셋
  마지막 움직임으로부터 30초 침묵 → 녹화 종료 + 로그 1개 저장
"""

import asyncio
import base64
import os
import time
from datetime import datetime
from typing import Optional, Set

import cv2
import numpy as np

from motion_detector import MotionDetector, RawMotion
from recorder import Recorder
from ai_describer import describe_recording
from database import insert_motion_log, get_setting, set_setting

CAMERA_INDEX        = 0
# CAMERA_SOURCE 환경변수에 영상 파일 경로 또는 스트림 URL 을 지정하면 웹캠 대신 사용한다.
# 파일 입력은 끝에 도달하면 처음부터 반복 재생한다.
CAMERA_SOURCE       = os.getenv("CAMERA_SOURCE", "").strip() or None
FPS_TARGET          = 15
FRAME_INTERVAL      = 1.0 / FPS_TARGET
DEFAULT_SILENCE_SEC = 30.0          # 녹화 종료까지 무동작 대기 시간(초) 기본값
MIN_SILENCE_SEC     = 3.0
MAX_SILENCE_SEC     = 600.0


class MotionSession:
    def __init__(self, recorder: Recorder):
        self._recorder        = recorder
        self._active          = False
        self._started_at:     Optional[datetime] = None
        self._last_motion_at: Optional[datetime] = None
        self._peak_intensity: float = 0.0

    def on_motion(self, raw: RawMotion):
        now = raw.detected_at

        if not self._active:
            self._active         = True
            self._started_at     = now
            self._peak_intensity = raw.intensity
            self._recorder.start_recording()
            print(f"[Session] 시작: {now.strftime('%H:%M:%S')}")

        # 타이머 리셋
        self._last_motion_at = now

        # 가장 강했던 움직임 강도 기록
        if raw.intensity > self._peak_intensity:
            self._peak_intensity = raw.intensity

    async def check_silence(self, silence_sec: float):
        """매 프레임마다 호출 — silence_sec 초 침묵이면 세션 종료"""
        if not self._active or self._last_motion_at is None:
            return
        elapsed = (datetime.now() - self._last_motion_at).total_seconds()
        if elapsed >= silence_sec:
            self._finalize()

    def _finalize(self):
        if not self._active:
            return

        self._active = False
        duration = (datetime.now() - self._started_at).total_seconds()
        print(f"[Session] 종료 — 지속 {duration:.1f}초, 녹화 종료 및 로그 저장")

        started_at     = self._started_at
        peak_intensity = self._peak_intensity

        self._started_at     = None
        self._last_motion_at = None
        self._peak_intensity = 0.0

        # recording_id는 stop_recording() 호출 전에 가져와야 함
        recording_id = self._recorder.current_recording_id or 0

        # 로그 행을 먼저 만들고, 설명은 VLM 처리 후 갱신한다
        log_id = insert_motion_log(
            recording_id=recording_id,
            detected_at=started_at,
            duration_sec=duration,
            intensity=peak_intensity,
            timestamp_offset_sec=0.0,
            description="",
        )

        # 녹화 파일이 완성되면 백그라운드 스레드에서 VLM 로그를 생성한다
        self._recorder.stop_recording(
            on_complete=lambda final_path: describe_recording(log_id, final_path)
        )

    def force_stop(self):
        """서버 종료 시 동기 강제 종료"""
        if self._active:
            self._recorder.stop_recording()
            self._active = False
            print("[Session] 강제 종료")

    @property
    def is_active(self) -> bool:
        return self._active


class CameraManager:
    def __init__(self):
        self._cap: Optional[cv2.VideoCapture] = None
        self._running          = False
        self._latest_frame:    Optional[bytes] = None
        self._is_motion_active = False
        self._subscribers:     Set[asyncio.Queue] = set()
        self._is_file_source   = False
        self._src_fps          = float(FPS_TARGET)     # 입력 영상 fps (파일 소스일 때 갱신)
        self.silence_sec       = DEFAULT_SILENCE_SEC   # 녹화 종료까지 무동작 대기(초)

        self._detector = MotionDetector()
        self._recorder = Recorder()
        self._session  = MotionSession(self._recorder)

    # ── 설정: 무동작 대기 시간 ──────────────────────────
    def _load_silence_sec(self):
        raw = get_setting("silence_sec")
        if raw is not None:
            try:
                self.silence_sec = self._clamp_silence(float(raw))
            except (TypeError, ValueError):
                pass

    @staticmethod
    def _clamp_silence(v: float) -> float:
        return max(MIN_SILENCE_SEC, min(MAX_SILENCE_SEC, v))

    def set_silence_sec(self, v: float) -> float:
        """무동작 대기 시간을 변경하고 DB에 저장. 적용된(클램프된) 값을 반환."""
        self.silence_sec = self._clamp_silence(float(v))
        set_setting("silence_sec", self.silence_sec)
        print(f"[Camera] 무동작 대기 시간 변경: {self.silence_sec}초")
        return self.silence_sec

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=4)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self._subscribers.discard(q)

    async def _broadcast(self, data: dict):
        dead = set()
        for q in self._subscribers:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass
            except Exception:
                dead.add(q)
        self._subscribers -= dead

    async def start(self):
        if self._running:
            return
        self._running = True
        self._load_silence_sec()
        print(f"[Camera] 무동작 대기 시간: {self.silence_sec}초")

        source = CAMERA_SOURCE if CAMERA_SOURCE is not None else CAMERA_INDEX
        self._is_file_source = CAMERA_SOURCE is not None
        self._cap = cv2.VideoCapture(source)
        if not self._cap.isOpened():
            if self._is_file_source:
                print(f"[Camera] 입력 영상 열기 실패: {CAMERA_SOURCE} — 데모 모드")
            else:
                print("[Camera] 웹캠 없음 — 데모 모드")
            asyncio.create_task(self._demo_loop())
            return

        # 파일 입력은 원본 fps 로 재생하여 침묵 시간 계산이 영상 시간과 일치하도록 한다.
        if self._is_file_source:
            fps = self._cap.get(cv2.CAP_PROP_FPS)
            self._src_fps = fps if (fps and 1.0 <= fps <= 120.0) else float(FPS_TARGET)
            self._recorder.fps = self._src_fps   # 녹화 파일도 원본 속도로 저장
        else:
            self._src_fps = float(FPS_TARGET)

        asyncio.create_task(self._capture_loop())
        if self._is_file_source:
            print(f"[Camera] 입력 영상 캡처 시작(반복 재생, {self._src_fps:.1f}fps): {CAMERA_SOURCE}")
        else:
            print("[Camera] 웹캠 캡처 시작")

    async def _capture_loop(self):
        loop = asyncio.get_event_loop()
        frame_interval = 1.0 / self._src_fps   # 파일 소스면 원본 fps, 웹캠이면 1/15
        while self._running:
            t0 = time.monotonic()
            ret, frame = await loop.run_in_executor(None, self._cap.read)
            if not ret:
                if self._is_file_source:
                    # 영상 끝에서 처음으로 되감고 감지기의 이전 프레임을 초기화한다
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    self._detector.reset()
                    await asyncio.sleep(0.05)
                    continue
                await asyncio.sleep(0.1)
                continue
            await self._process_frame(frame)
            sleep = frame_interval - (time.monotonic() - t0)
            if sleep > 0:
                await asyncio.sleep(sleep)

    async def _demo_loop(self):
        frame_n = 0
        while self._running:
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            cv2.putText(
                frame,
                f"DEMO  {datetime.now().strftime('%H:%M:%S')}",
                (50, 360), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 200, 0), 3,
            )
            frame_n += 1
            await self._process_frame(frame)
            await asyncio.sleep(FRAME_INTERVAL)

    async def _process_frame(self, frame: np.ndarray):
        # 1) 움직임 감지
        raw: Optional[RawMotion] = self._detector.detect(frame)

        # 2) 세션 업데이트
        if raw:
            self._session.on_motion(raw)

        # 3) 무동작 대기 시간만큼 침묵하면 세션 종료
        await self._session.check_silence(self.silence_sec)

        # 4) 녹화 중이면 프레임 기록
        self._recorder.write_frame(frame)

        # 5) 오버레이
        self._is_motion_active = self._session.is_active
        display = self._detector.draw_boxes(frame, self._is_motion_active)
        cv2.putText(
            display,
            datetime.now().strftime("%Y-%m-%d  %H:%M:%S"),
            (10, display.shape[0] - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1,
        )

        # 6) 브로드캐스트
        _, buf = cv2.imencode(".jpg", display, [cv2.IMWRITE_JPEG_QUALITY, 75])
        jpg_b64 = base64.b64encode(buf.tobytes()).decode()
        self._latest_frame = buf.tobytes()

        await self._broadcast({
            "frame":     jpg_b64,
            "motion":    self._is_motion_active,
            "timestamp": datetime.now().isoformat(),
        })

    def stop(self):
        self._running = False
        self._session.force_stop()
        self._recorder.stop()
        if self._cap:
            self._cap.release()
        print("[Camera] 종료")

    @property
    def latest_frame_bytes(self) -> Optional[bytes]:
        return self._latest_frame


camera_manager = CameraManager()
