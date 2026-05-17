"""
preprocess.py
녹화 영상을 VLM 서버로 보내기 전 가볍게 만드는 전처리 모듈.

- 해상도를 1/REDUCE 로 축소
- 프레임을 TARGET_FPS 로 다운샘플링
- mp4v 코덱으로 다시 저장

원본은 건드리지 않고 dst 경로에 새 파일을 만든다.
"""

from pathlib import Path

import cv2

# ── 파라미터 ──────────────────────────────
# 팀 실험 결과 "360p / 4fps" 가 인식 신뢰도 마지노선이라 그 값에 맞춤.
# (녹화 영상은 1280x720 로 정규화되므로 REDUCE=2 → 640x360 = 360p)
REDUCE     = 2    # 해상도를 얼마나 줄일 것인가 (가로/세로 각각 1/REDUCE)
TARGET_FPS = 4    # 결과 영상의 초당 프레임 수


def downsample_video(
    src: Path,
    dst: Path,
    reduce: int = REDUCE,
    target_fps: int = TARGET_FPS,
) -> bool:
    """
    src 영상을 해상도 1/reduce, target_fps 로 다운샘플하여 dst 에 저장.
    성공하면 True, 실패하면 False.
    (cv2 호출이 블로킹이므로 별도 스레드/executor 에서 호출할 것)
    """
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        print(f"[Preprocess] 영상 열기 실패: {src}")
        return False

    old_fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    width   = max(1, int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)  / reduce))
    height  = max(1, int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) / reduce))
    frame_interval = max(1, int(round(old_fps / target_fps)))

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(dst), fourcc, target_fps, (width, height))
    if not out.isOpened():
        print(f"[Preprocess] VideoWriter 열기 실패: {dst}")
        cap.release()
        return False

    frame_idx   = 0
    written      = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % frame_interval == 0:
            resized = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
            out.write(resized)
            written += 1
        frame_idx += 1

    cap.release()
    out.release()

    if written == 0 or not dst.exists() or dst.stat().st_size == 0:
        print(f"[Preprocess] 결과 영상이 비어 있음: {dst}")
        dst.unlink(missing_ok=True)
        return False

    print(f"[Preprocess] 완료: {dst.name} ({width}x{height}, {target_fps}fps, {written}프레임)")
    return True
