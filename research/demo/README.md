# 시연용 데모 영상 — ucf_demo.mp4 (2026-11-10)

UCF-Crime 5편을 이어 붙인 5분 30초 영상. 클라이언트 백엔드의 `CAMERA_SOURCE`로 넣어
"카메라 대신 영상"으로 전체 흐름(감지 → 녹화 → VLM → 창 로그)을 돌린다.
1280×720·30fps로 업스케일(노트북 웹캠과 같은 경로), 클립 사이 12초 정지, 마지막 60초 정지. `CAMERA_LOOP=0`이면 거기서 멈춘다.

## 타임라인 (영상 기준 초)

| 구간 | 클립 | 원본 구간 | 서버에서 확인된 결과 (예행연습 2026-11-10 21:30) |
|---|---|---|---|
| 0–30 | Normal_Videos_246 (관제실) | 0–30s | 창 2개 모두 정상 |
| 42–100 | Robbery050 (주차장 픽업트럭) | 0–58s | 20–40s 창 **이상 · 강도**, 나머지 정상 |
| 112–156 | RoadAccidents001 (정원 앞 도로) | 0–44s | 0–20s 창 **이상 · 교통사고** |
| 168–218 | Fighting003 (지하철 승강장) | 55–105s | 0–20s 창 **이상 · 싸움** |
| 230–273 | Explosion008 (교차로) | 15–58s | 앞에 8초짜리 정상 세션 1개, 이어서 0–20s 창 **이상 · 폭발** |
| 273–330 | 마지막 프레임 정지 | | 세션 없음 (로그 화면 보여줄 시간) |

세션 종료 대기(silence_sec)는 **8초**로 심어 둠 — 클립 안의 무동작 공백(최대 6.8초)보다 길고 클립 사이 정지(12초)보다 짧아서 클립마다 세션이 하나씩 생긴다.
3초로 두면 Robbery050이 7초·3초 조각으로 쪼개져 사건 창이 어긋나고, 30초로 두면 클립들이 한 세션으로 붙는다.
Normal_027은 0–20초 창이 매번 Robbery로 오탐돼서 Normal_246으로 바꿨다. Arson010·Shoplifting001은 유형이 흔들려 제외.

## 실행 (서버, tmux 세션 `vlm`)

- 창 1 `server`: vLLM(:8002), 창 3 `adapter`: 어댑터(:8010) — 떠 있어야 함. `curl localhost:8010/health`
- 창 4 `web`: `npm run dev -- --host 0.0.0.0 --port 5173` (이미 실행 중)
- 창 5 `client`: 아래 명령이 타이핑돼 있음. **Enter 치는 순간 영상이 시작**된다.
  ```
  source venv/bin/activate && VLM_SERVER_URL=http://localhost:8010 CAMERA_SOURCE=<리포>/research/demo/ucf_demo.mp4 CAMERA_LOOP=0 uvicorn main:app --host 0.0.0.0 --port 8800
  ```
  `CAMERA_LOOP=0`: 영상이 끝나면 반복하지 않고 마지막 프레임에서 멈춘다(반복하면 같은 로그가 한 바퀴마다 또 쌓임). 다시 돌리려면 Ctrl+C 후 다시 Enter.
- 브라우저: 노트북에서 http://<서버 IP>:5173 (같은 내부망) 또는 VSCode 포트 포워딩으로 http://localhost:5173

## DB는 지우지 않는다 (2026-11-10 결정)

로그가 많이 쌓여 있는 편이 /logs 필터·검색 시연에 좋다. 데모 영상을 한 번 돌릴 때마다 녹화 6개·로그 13개가 쌓인다(같은 내용이 반복되므로 보통 한 번이면 충분).
시작 전 `ingest_video.py`로 UCF 18편(유형 12 + 정상 6, 720p 업스케일, 최근 7일에 9시간 간격)을 미리 넣어 두었다 (`research/demo/ingest/`).

## (필요할 때만) DB·녹화 초기화

```
cd <리포>/client/backend && rm -rf recordings && mkdir recordings && rm -f cctv.db && \
venv/bin/python -c "from database import init_db, set_setting; init_db(); set_setting('silence_sec', 8.0); set_setting('max_session_sec', 60.0)"
```
백엔드(창 5)를 Ctrl+C로 끈 뒤 실행하고, 다시 Enter.
예전 테스트 데이터는 `cctv.db.bak-20261110`, `recordings.bak-20261110`에 있음.

## 2026-11-10 21:40 첫 실행에서 발견한 문제 (고침)
- 서버(리눅스)에서는 OpenCV가 mp4v 코덱으로 녹화하고 `-c copy` 로 컨테이너만 바꿔서 브라우저가 재생 못 함 → `recorder.py`가 libx264로 변환하도록 고침. 기존 6개 파일도 변환해 둠.
- 영상이 끝나면 처음부터 반복돼 같은 로그가 또 쌓임 → `CAMERA_LOOP=0` 추가.
- 로그 한 줄은 20초 창 하나다. 35초 정상 클립이면 비슷한 내용의 로그가 2줄 생기는 게 정상.

## 영상 다시 만들기

```
cd research/UCF_Crime && P="scale=1280:720:flags=lanczos,setsar=1,fps=30,tpad=stop_mode=clone:stop_duration=12,setpts=PTS-STARTPTS" && L="${P/stop_duration=12/stop_duration=60}" && ffmpeg -y -v error \
 -ss 0 -t 30 -i Testing_Normal_Videos_Anomaly/Normal_Videos_246_x264.mp4 -ss 0 -t 58 -i Robbery/Robbery050_x264.mp4 \
 -ss 0 -t 44 -i RoadAccidents/RoadAccidents001_x264.mp4 -ss 55 -t 50 -i Fighting/Fighting003_x264.mp4 -ss 15 -t 43 -i Explosion/Explosion008_x264.mp4 \
 -filter_complex "[0:v]$P[v0];[1:v]$P[v1];[2:v]$P[v2];[3:v]$P[v3];[4:v]$L[v4];[v0][v1][v2][v3][v4]concat=n=5:v=1:a=0[out]" \
 -map "[out]" -an -c:v libx264 -preset fast -crf 20 -pix_fmt yuv420p -movflags +faststart ../demo/ucf_demo.mp4
```
