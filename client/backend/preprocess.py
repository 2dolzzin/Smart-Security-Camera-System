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
TARGET_FPS = 4    # 결과 영상의 초당 프레임 수 (근사치 — 실제는 원본fps/round(원본fps/4))
MIN_HEIGHT = 240  # 이보다 작아지면 축소하지 않음


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
    src_w, src_h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    # 원본이 이미 작으면(테스트용 저해상도 영상 등) 더 줄이지 않는다 — VLM 학습 데이터가 320x240 이었음
    if src_h / reduce < MIN_HEIGHT:
        reduce = 1
    width   = max(1, int(src_w / reduce))
    height  = max(1, int(src_h / reduce))
    frame_interval = max(1, int(round(old_fps / target_fps)))
    # 실제 결과 fps = old_fps / frame_interval (예: 15fps→4프레임마다 = 3.75fps).
    # 파일에 target_fps(4)를 적으면 재생 시간이 6% 줄어 VLM 로그의 창 시각(window_start)이
    # 원본 녹화 시각과 어긋난다 → 실제 fps 를 기록해 시간축을 보존한다.
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
