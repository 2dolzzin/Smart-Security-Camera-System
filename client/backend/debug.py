"""
debug.py
움직임 감지 과정 시각화 실험 스크립트.

실제 서비스(motion_detector.py)와 동일한 함수를 사용하므로
파라미터 조정 결과가 그대로 서비스에 반영됨.

실행 방법:
    python debug.py 영상파일.mp4

    # 재생 속도 조절 (기본 1배속)
    python debug.py 영상파일.mp4 --speed 2

조작 키:
    Q 또는 ESC : 종료
    SPACE       : 일시정지 / 재생
    S           : 현재 프레임 이미지 저장
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

# 실제 서비스와 동일한 함수 사용
from motion_detector import (
    to_gray,
    calc_diff,
    to_binary,
    find_motion,
    THRESHOLD_VALUE,
    MIN_CONTOUR_AREA,
)

WINDOW_ORIGINAL  = "1. 원본"
WINDOW_GRAY      = "2. 그레이스케일"
WINDOW_DIFF      = "3. 프레임 차이"
WINDOW_BINARY    = "4. 이진화 (움직임=흰색)"


def put_info(frame: np.ndarray, text: str, color=(255, 255, 255)) -> np.ndarray:
    """프레임 좌상단에 텍스트 오버레이"""
    out = frame.copy()
    cv2.putText(out, text, (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 3)   # 외곽선
    cv2.putText(out, text, (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    return out


def run(video_path: str, speed: float = 1.0):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[Debug] 영상 파일을 열 수 없습니다: {video_path}")
        sys.exit(1)

    fps      = cap.get(cv2.CAP_PROP_FPS) or 30
    delay    = max(1, int(1000 / fps / speed))   # 재생 속도 반영
    total    = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"[Debug] 파일: {video_path}")
    print(f"[Debug] FPS: {fps:.1f}  총 프레임: {total}  재생속도: {speed}x")
    print(f"[Debug] 파라미터 — THRESHOLD: {THRESHOLD_VALUE}, MIN_AREA: {MIN_CONTOUR_AREA}")
    print(f"[Debug] 조작: Q/ESC=종료  SPACE=일시정지  S=저장")

    # 창 배치 (2x2 그리드)
    cv2.namedWindow(WINDOW_ORIGINAL, cv2.WINDOW_NORMAL)
    cv2.namedWindow(WINDOW_GRAY,     cv2.WINDOW_NORMAL)
    cv2.namedWindow(WINDOW_DIFF,     cv2.WINDOW_NORMAL)
    cv2.namedWindow(WINDOW_BINARY,   cv2.WINDOW_NORMAL)

    cv2.moveWindow(WINDOW_ORIGINAL, 0,   0)
    cv2.moveWindow(WINDOW_GRAY,     660, 0)
    cv2.moveWindow(WINDOW_DIFF,     0,   420)
    cv2.moveWindow(WINDOW_BINARY,   660, 420)

    # 창 크기 통일
    for win in [WINDOW_ORIGINAL, WINDOW_GRAY, WINDOW_DIFF, WINDOW_BINARY]:
        cv2.resizeWindow(win, 640, 400)

    prev_gray = None
    paused    = False
    frame_idx = 0

    while True:
        if not paused:
            ret, frame = cap.read()
            if not ret:
                print("[Debug] 영상 재생 완료")
                break
            frame_idx += 1

        # ── 단계별 처리 (실제 서비스와 동일한 함수) ──
        curr_gray = to_gray(frame)

        if prev_gray is None:
            prev_gray = curr_gray
            continue

        diff   = calc_diff(prev_gray, curr_gray)
        thresh = to_binary(diff)
        significant, intensity = find_motion(thresh, frame)
        prev_gray = curr_gray

        motion = len(significant) > 0

        # ── 창 1: 원본 ──
        original_disp = frame.copy()
        # 움직임 윤곽선 그리기
        if motion:
            cv2.drawContours(original_disp, significant, -1, (0, 255, 0), 2)
            cv2.rectangle(original_disp, (0, 0),
                          (original_disp.shape[1]-1, original_disp.shape[0]-1),
                          (0, 0, 255), 3)
        status = f"MOTION ({intensity:.3f})" if motion else "no motion"
        color  = (0, 0, 255) if motion else (200, 200, 200)
        original_disp = put_info(
            original_disp,
            f"[{frame_idx}/{total}]  {status}",
            color,
        )

        # ── 창 2: 그레이스케일 ──
        gray_disp = put_info(
            cv2.cvtColor(curr_gray, cv2.COLOR_GRAY2BGR),
            "그레이스케일 + 블러",
        )

        # ── 창 3: 프레임 차이 ──
        # 차이값을 보기 좋게 3배 증폭
        diff_bright = cv2.convertScaleAbs(diff, alpha=3.0)
        diff_disp   = put_info(
            cv2.cvtColor(diff_bright, cv2.COLOR_GRAY2BGR),
            "프레임 차이 (3x 증폭)",
        )

        # ── 창 4: 이진화 ──
        binary_disp = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)
        # 유효 윤곽선에 빨간 테두리
        if motion:
            cv2.drawContours(binary_disp, significant, -1, (0, 0, 255), 2)
        binary_disp = put_info(
            binary_disp,
            f"이진화  threshold={THRESHOLD_VALUE}  min_area={MIN_CONTOUR_AREA}",
        )

        # ── 창 표시 ──
        cv2.imshow(WINDOW_ORIGINAL, original_disp)
        cv2.imshow(WINDOW_GRAY,     gray_disp)
        cv2.imshow(WINDOW_DIFF,     diff_disp)
        cv2.imshow(WINDOW_BINARY,   binary_disp)

        # ── 키 입력 ──
        key = cv2.waitKey(delay if not paused else 30) & 0xFF

        if key in (ord('q'), 27):     # Q or ESC
            print("[Debug] 종료")
            break
        elif key == ord(' '):          # SPACE
            paused = not paused
            print(f"[Debug] {'일시정지' if paused else '재생'}")
        elif key == ord('s'):          # S — 저장
            ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = Path(f"debug_capture_{ts}.png")
            # 4개 창을 2x2로 합쳐서 저장
            top    = np.hstack([
                cv2.resize(original_disp, (640, 400)),
                cv2.resize(gray_disp,     (640, 400)),
            ])
            bottom = np.hstack([
                cv2.resize(diff_disp,   (640, 400)),
                cv2.resize(binary_disp, (640, 400)),
            ])
            combined = np.vstack([top, bottom])
            cv2.imwrite(str(path), combined)
            print(f"[Debug] 저장: {path}")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="움직임 감지 디버그 뷰어")
    parser.add_argument("video", help="영상 파일 경로 (예: recordings/2026-04-05/16-30-00.mp4)")
    parser.add_argument("--speed", type=float, default=1.0, help="재생 속도 (기본: 1.0)")
    args = parser.parse_args()

    run(args.video, args.speed)
