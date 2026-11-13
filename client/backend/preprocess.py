"""
preprocess.py
녹화 영상을 VLM 서버로 보내기 전에 해상도와 프레임 수를 줄이는 전처리 모듈.

- 해상도를 1/REDUCE 로 축소
- 프레임을 TARGET_FPS 로 다운샘플링
- mp4v 코덱으로 다시 저장

원본은 건드리지 않고 dst 경로에 새 파일을 만든다.
"""

from pathlib import Path

import cv2

# ── 파라미터 ──────────────────────────────
# 녹화 영상은 1280x720 이므로 REDUCE=2 이면 640x360 이 된다.
REDUCE     = 2    # 가로/세로 축소 비율 (1/REDUCE)
TARGET_FPS = 4    # 목표 fps. 실제 fps 는 원본fps / round(원본fps / TARGET_FPS)
MIN_HEIGHT = 240  # 축소 후 높이가 이 값보다 작아지면 축소하지 않는다


def downsample_video(
    src: Path,
    dst: Path,
    reduce: int = REDUCE,
    target_fps: int = TARGET_FPS,
) -> bool:
    """
    src 영상을 해상도 1/reduce, 약 target_fps 로 다운샘플하여 dst 에 저장한다.
    성공하면 True, 실패하면 False. 블로킹 함수이다.
    """
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        print(f"[Preprocess] 영상 열기 실패: {src}")
        return False

    old_fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    src_w, src_h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if src_h / reduce < MIN_HEIGHT:
        reduce = 1
    width   = max(1, int(src_w / reduce))
    height  = max(1, int(src_h / reduce))
    frame_interval = max(1, int(round(old_fps / target_fps)))
    # 결과 파일에는 실제 fps(old_fps / frame_interval)를 기록해 원본과 재생 시간을 일치시킨다.
    real_fps = old_fps / frame_interval

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(dst), fourcc, real_fps, (width, height))
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

    print(f"[Preprocess] 완료: {dst.name} ({width}x{height}, {real_fps:.2f}fps, {written}프레임)")
    return True
