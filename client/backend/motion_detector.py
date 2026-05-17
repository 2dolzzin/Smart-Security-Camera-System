"""
motion_detector.py
OpenCV 기반 움직임 감지 모듈.

[구조]
각 처리 단계를 독립 함수로 분리:
  to_gray()       : 그레이스케일 + 블러
  calc_diff()     : 프레임 차이 계산
  to_binary()     : 이진화 + 팽창
  find_motion()   : 윤곽선 탐지 + 면적 필터

MotionDetector.detect() 는 위 함수들을 순서대로 호출.
debug.py 에서도 동일한 함수를 사용하므로
파라미터 변경 시 실제 서비스와 실험 결과가 항상 일치함.
"""

import cv2
import numpy as np
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

# ── 파라미터 (여기서 조정하면 서비스 + 실험 모두 반영) ──
BLUR_SIZE        = (21, 21)
THRESHOLD_VALUE  = 25       # 이진화 임계값 (높을수록 둔감)
MIN_CONTOUR_AREA = 1500     # 최소 움직임 면적 (높을수록 둔감)
DILATE_ITER      = 2        # 팽창 반복 횟수


# ── 단계별 함수 ────────────────────────────────────────

def to_gray(frame: np.ndarray) -> np.ndarray:
    """
    1단계: BGR → 그레이스케일 + 가우시안 블러
    블러는 카메라 노이즈로 인한 오탐지를 줄여줌
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, BLUR_SIZE, 0)
    return gray


def calc_diff(prev_gray: np.ndarray, curr_gray: np.ndarray) -> np.ndarray:
    """
    2단계: 이전 프레임과 현재 프레임의 절댓값 차이 계산
    움직임이 있는 픽셀일수록 차이값이 큼
    """
    return cv2.absdiff(prev_gray, curr_gray)


def to_binary(diff: np.ndarray) -> np.ndarray:
    """
    3단계: 이진화 + 팽창
    - 차이값 >= THRESHOLD_VALUE → 255 (움직임 있음, 흰색)
    - 차이값 <  THRESHOLD_VALUE → 0   (움직임 없음, 검정)
    - 팽창(dilate): 끊어진 픽셀을 이어붙여 하나의 덩어리로 만듦
    """
    _, thresh = cv2.threshold(diff, THRESHOLD_VALUE, 255, cv2.THRESH_BINARY)
    thresh = cv2.dilate(thresh, None, iterations=DILATE_ITER)
    return thresh


def find_motion(
    thresh: np.ndarray,
    frame: np.ndarray,
) -> tuple[list, float]:
    """
    4단계: 윤곽선 탐지 + 면적 필터
    반환값: (유효한 윤곽선 리스트, intensity)
    intensity = 전체 픽셀 대비 움직임 픽셀 비율 (0.0 ~ 1.0)
    """
    contours, _ = cv2.findContours(
        thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    significant = [c for c in contours if cv2.contourArea(c) >= MIN_CONTOUR_AREA]

    if not significant:
        return [], 0.0

    total_pixels   = frame.shape[0] * frame.shape[1]
    changed_pixels = sum(cv2.contourArea(c) for c in significant)
    intensity      = min(changed_pixels / total_pixels, 1.0)

    return significant, intensity


# ── 데이터 클래스 ───────────────────────────────────────

@dataclass
class RawMotion:
    """단순 감지 신호 — 프레임 + 강도"""
    detected_at: datetime
    intensity: float         # 변화 픽셀 비율 (0.0 ~ 1.0)
    frame: np.ndarray        # 감지 시점 프레임 (AI 분석용)


# ── 실제 서비스용 클래스 ────────────────────────────────

class MotionDetector:
    """
    실제 서비스(camera.py)에서 사용.
    단계별 함수를 순서대로 호출하여 RawMotion 반환.
    """

    def __init__(self):
        self._prev_gray: Optional[np.ndarray] = None

    def reset(self):
        self._prev_gray = None

    def detect(self, frame: np.ndarray) -> Optional[RawMotion]:
        curr_gray = to_gray(frame)

        if self._prev_gray is None:
            self._prev_gray = curr_gray
            return None

        diff   = calc_diff(self._prev_gray, curr_gray)
        thresh = to_binary(diff)
        self._prev_gray = curr_gray

        significant, intensity = find_motion(thresh, frame)
        if not significant:
            return None

        return RawMotion(
            detected_at=datetime.now(),
            intensity=intensity,
            frame=frame.copy(),
        )

    @staticmethod
    def draw_boxes(frame: np.ndarray, has_motion: bool) -> np.ndarray:
        """움직임 감지 중일 때 빨간 테두리 오버레이"""
        out = frame.copy()
        if has_motion:
            h, w = out.shape[:2]
            cv2.rectangle(out, (0, 0), (w - 1, h - 1), (0, 0, 255), 4)
            cv2.putText(
                out, "MOTION DETECTED", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2,
            )
        return out
