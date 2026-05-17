# CCTV 모니터링 시스템

로컬 CCTV/웹캠 영상에서 **움직임 구간만 자동으로 녹화**하고, 그 구간을 **자체 호스팅 VLM**으로 한국어로 설명·로그화하는 시스템입니다.

- 항상 켜져 있고, 사람이 영상을 통째로 다시 볼 필요 없이 **이벤트(움직임)별 짧은 클립 + 한 줄 설명**만 쌓입니다.
- VLM은 외부 API가 아니라 **AWS GPU 인스턴스에 직접 띄운 Qwen2.5-VL-3B** — 비용·프라이버시 부담 없음.

---

## 시스템 구성

두 개의 서버 + 한 개의 웹 UI 로 나뉩니다.

```
┌─────────────────────── 클라이언트 측 (사용자 PC) ───────────────────────┐
│                                                                       │
│   [웹캠 / 입력 영상]                       [브라우저]                   │
│        │                                       │                      │
│        ▼                                       ▼                      │
│   ┌──────────────────────┐               ┌──────────────────┐         │
│   │ client/backend       │◄── WebSocket ─┤ client/frontend  │         │
│   │  (FastAPI)           │   REST        │  (React)         │         │
│   │  · 모션 감지·녹화      │◄────────────►│  /live /playback │         │
│   │  · 전처리(360p·4fps)  │               │  /logs /settings │         │
│   │  · SQLite 로그        │               └──────────────────┘         │
│   └─────────┬────────────┘                                            │
└─────────────┼─────────────────────────────────────────────────────────┘
              │ POST /describe (다운샘플 mp4 업로드)
              ▼
┌─────────────────────────────────────────────────────────────────────┐
│             server/ (AWS GPU 인스턴스 · A10G)                        │
│             FastAPI + Qwen2.5-VL-3B-Instruct                        │
│             영상 → 한국어 설명 1문장                                  │
└─────────────────────────────────────────────────────────────────────┘
```

### 데이터 흐름 (한 이벤트의 일생)

1. **카메라 캡처** — 웹캠 또는 `CAMERA_SOURCE` 영상 파일을 프레임 단위로 읽음
2. **움직임 감지** — 프레임 차분(grayscale → blur → absdiff → threshold → dilate → contour) 후 변화 픽셀 비율이 임계치 이상이면 "움직임" 신호
3. **세션 녹화** (`MotionSession`) — 움직임 감지되면 녹화 시작 → 움직임이 이어지면 타이머 리셋 → **마지막 움직임 후 N초간 정적**이면 세션 종료 (N은 `/settings`에서 변경)
4. **영상 마무리** — `recorder`가 백그라운드 스레드에서 mp4 최종화 (avc1 코덱 가능하면 직접 저장, 아니면 mp4v로 받아 FFmpeg `-c copy`로 브라우저 호환 mp4로 remux)
5. **전처리** — `preprocess.downsample_video`가 그 mp4를 **해상도 1/2(→360p) + 4fps**로 다운샘플 (같은 폴더에 `..._vlm.mp4` 로 보관)
6. **VLM 호출** — `ai_describer`가 그 작은 mp4를 `POST {VLM_SERVER_URL}/describe`로 업로드 → Qwen2.5-VL이 한국어 한 줄 설명 반환
7. **로그 기록** — `motion_logs.description` 업데이트 → 프론트 `/logs`·`/playback` 타임라인에 표시
8. **자동 정리** — 30일 지난 녹화·로그·`_vlm.mp4`는 매일 자정 자동 삭제

---

## 기술 스택

| 영역 | 기술 |
|------|------|
| Frontend | React 18, React Router v6, Zustand, Axios, dayjs, Vite |
| Backend (Client) | Python 3.11+, FastAPI, OpenCV, SQLite (WAL), APScheduler, httpx |
| VLM Server | Python 3.11+, FastAPI, PyTorch, Transformers, **Qwen2.5-VL-3B-Instruct**, `qwen-vl-utils` |
| 영상 저장·변환 | FFmpeg (mp4 remux), 로컬 파일시스템 |
| 인프라 | AWS EC2 (예: `g5.xlarge` / NVIDIA A10G 24GB) |

---

## 디렉토리 구조

```
cctv-final/
├── client/                         ← 사용자 PC 측 (백엔드 + 프론트)
│   ├── backend/
│   │   ├── main.py                 # FastAPI 진입점 (lifespan: DB·카메라·스케줄러 기동)
│   │   ├── camera.py               # 캡처 루프 + WebSocket 브로드캐스트 + MotionSession
│   │   ├── motion_detector.py      # OpenCV 움직임 감지 (debug.py 와 함수 공유)
│   │   ├── recorder.py             # 이벤트 기반 녹화 + 코덱 자동선택 + FFmpeg remux
│   │   ├── preprocess.py           # 녹화 mp4 → 360p·4fps 다운샘플 (VLM 입력용)
│   │   ├── ai_describer.py         # 전처리 → VLM 서버 호출 → 로그 description 기록
│   │   ├── scheduler.py            # 30일 자동 정리 스케줄러
│   │   ├── database.py             # SQLite 초기화·헬퍼 (recordings/motion_logs/settings)
│   │   ├── debug.py                # 모션 감지 4분할 시각화 (파라미터 튜닝용)
│   │   ├── routers/
│   │   │   ├── stream.py           # WebSocket /ws/stream
│   │   │   ├── recordings.py       # 녹화 목록/상세/스트리밍(Range)/삭제 API
│   │   │   ├── logs.py             # 로그 목록/상세 API
│   │   │   └── settings.py         # 런타임 설정 GET/PUT API
│   │   ├── recordings/             # 저장 영상 (.gitignore — 사생활)
│   │   └── requirements.txt
│   │
│   └── frontend/
│       ├── src/
│       │   ├── App.jsx
│       │   ├── main.jsx
│       │   ├── index.css
│       │   ├── api/index.js
│       │   ├── store/index.js      # Zustand (playbackTarget, motionDetected)
│       │   ├── pages/
│       │   │   ├── LivePage.jsx
│       │   │   ├── PlaybackPage.jsx
│       │   │   ├── LogPage.jsx
│       │   │   └── SettingsPage.jsx
│       │   └── components/
│       │       ├── Sidebar.jsx
│       │       ├── VideoPlayer.jsx
│       │       └── MotionLogList.jsx
│       ├── vite.config.js          # /api·/ws → http://localhost:8800 프록시
│       └── package.json
│
└── server/                         ← AWS GPU 인스턴스용 VLM API 서버
    ├── app.py                      # POST /describe (영상 업로드 → 한국어 설명)
    └── requirements.txt
```

---

## 실행 방법

총 3개 컴포넌트를 띄웁니다. 처음 한 번만 설치, 그 뒤로는 실행만.

### 1. VLM 서버 (AWS GPU 인스턴스)

GPU(예: A10G) + NVIDIA 드라이버가 설치된 Ubuntu 인스턴스에서.

```bash
# 0) GPU·드라이버 확인 — NVIDIA-SMI 표가 나와야 함
nvidia-smi

# 1) ~/qwen 에 server/app.py, server/requirements.txt 를 복사
#    (로컬에서 scp 또는 VSCode Remote-SSH)

# 2) torch / transformers / qwen-vl-utils 가 설치된 환경 활성화 (예: conda env)
conda activate qwen
pip install fastapi "uvicorn[standard]" python-multipart

# 3) 실행 — 외부 접속용으로 0.0.0.0
cd ~/qwen
uvicorn app:app --host 0.0.0.0 --port 8001
```

`[VLM] 모델 로딩 완료` → `Uvicorn running on http://0.0.0.0:8001` 이 뜨면 정상. 모델은 서버 켤 때 한 번만 GPU에 적재되고, 요청마다 재로딩하지 않음. 가중치는 첫 실행 시 HuggingFace에서 받아 `~/.cache/huggingface/`에 영구 저장됨.

**AWS 보안그룹 인바운드에 TCP 8001 허용** (Source는 가능하면 클라이언트 PC IP만, 데모면 `0.0.0.0/0`).

SSH 끊겨도 살리고 싶으면 `tmux new -s vlm` 안에서 실행 후 `Ctrl+b → d`.

### 2. 백엔드 (클라이언트 PC)

```bash
cd client/backend

python3 -m venv venv
source venv/bin/activate                          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# AWS VLM 서버 주소 지정 (uvicorn 과 같은 터미널에서 export)
export VLM_SERVER_URL="http://<AWS-퍼블릭-IP>:8001"

uvicorn main:app --port 8800
```

- `VLM_SERVER_URL` 을 안 주면 VLM 호출은 건너뛰고 로그 설명에 `"움직임 감지됨"` 폴백 문구가 들어갑니다.
- 데모/테스트 중엔 `--reload` 빼고 실행하는 게 안전 (녹화 파일 쓰는 도중 리로드되면 짧은 잔재 녹화가 생길 수 있음).

### 3. 프론트엔드 (클라이언트 PC, 새 터미널)

```bash
cd client/frontend
npm install
npm run dev
```

→ 브라우저 **http://localhost:5173** 접속.

### 동작 확인 한 줄

```bash
curl http://<AWS-퍼블릭-IP>:8001/health    # VLM 서버
curl http://localhost:8800/                # 클라이언트 백엔드
```
둘 다 `{"status":"ok", ...}` 나오면 풀스택 OK.

---

## 페이지 구성

| 경로 | 설명 |
|------|------|
| `/live` | 실시간 카메라 스트리밍 (움직임 감지 시 빨간 테두리), WebSocket 자동 재연결 |
| `/playback` | 날짜별 녹화 목록 → 영상 재생 + 타임라인 + 움직임 마커 + 구간 요약 + **녹화 삭제(🗑)** |
| `/logs` | 움직임 로그 (오늘/일주일/한 달 필터), 클릭 시 해당 녹화로 점프 |
| `/settings` | 녹화 종료 대기 시간(무동작 N초) 조절 — 즉시 반영 |

---

## 주요 기능

- **이벤트 기반 자동 녹화** — 움직임 시작 → 녹화, 마지막 움직임 후 N초 정적이면 종료. 녹화 1개 = 움직임 로그 1개.
- **이벤트 단위 파일 저장** — `recordings/YYYY-MM-DD/HH-MM-SS.mp4`. 통영상 저장 대비 디스크 사용량 극단적으로 작음.
- **VLM 한국어 장면 설명** — 녹화 → 전처리(360p·4fps) → AWS Qwen2.5-VL → 짧은 한 문장 → motion_log에 기록 → 프론트에 표시.
- **로그 클릭 → 영상 점프** — 로그 항목 클릭 시 해당 녹화 자동 재생.
- **녹화 삭제** — `/playback`에서 영상·DB·연결된 로그·부산물(`_raw.mp4`, `_vlm.mp4`)까지 일괄 삭제.
- **설정 가능한 침묵 타임아웃** — `/settings`에서 3–600초, DB에 저장되어 즉시 반영(서버 재시작 불필요).
- **30일 자동 정리** — 매일 자정 오래된 녹화·로그·부산물 일괄 삭제.
- **테스트용 영상 입력 모드** — `CAMERA_SOURCE` 환경변수로 웹캠 대신 사전 녹화된 영상을 입력 (실제 카메라처럼 원본 fps로 재생, 끝나면 처음부터 반복).
- **개발자용 전처리 결과 보관** — VLM에 실제 보낸 다운샘플 mp4(`..._vlm.mp4`)를 녹화 옆에 저장 → 디스크에서 직접 검증 가능.
- **HTTP Range 지원 영상 스트리밍** — `<video>` seek 정상 동작.
- **WebSocket keep-alive 핑** — 프레임 5초 공백 시에도 연결 유지.

---

## 환경변수

### 백엔드 (`client/backend/`)

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `VLM_SERVER_URL` | AWS VLM 서버 주소 (예: `http://1.2.3.4:8001`). 비어 있으면 VLM 호출 생략, 로그 설명은 `"움직임 감지됨"` | (없음) |
| `VLM_TIMEOUT` | VLM 서버 응답 대기 시간(초) | `60` |
| `VLM_QUESTION` | VLM에 보낼 질문 텍스트. 비우면 서버 기본 CCTV 프롬프트 사용 | (없음) |
| `CAMERA_SOURCE` | 테스트용 입력 영상 경로(또는 RTSP URL 등). 파일이면 끝까지 가면 반복 재생. 미지정 시 웹캠 | (없음) |

### VLM 서버 (`server/`)

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `VLM_MODEL` | HuggingFace 모델 ID | `Qwen/Qwen2.5-VL-3B-Instruct` |
| `VLM_QUESTION` | 클라이언트가 question을 안 주면 사용할 기본 프롬프트 | (CCTV 한 줄 설명 프롬프트) |
| `VLM_MAX_NEW_TOKENS` | 생성 최대 토큰 수 | `64` |

### DB에 저장되는 런타임 설정

| 키 | 설명 | 범위 |
|----|------|------|
| `silence_sec` | 녹화 종료까지 무동작 대기(초). `/settings` 또는 `PUT /api/settings` 로 변경 | 3–600 |

---

## 카메라 / 입력 설정

`client/backend/camera.py` 상단:

```python
CAMERA_INDEX = 0   # 기본 웹캠 (1, 2 ... 로 다른 장치 선택 가능)
```

웹캠이 없거나 열기 실패하면 **데모 모드**로 자동 전환(검은 화면에 시간 오버레이).

테스트 시 **사전 녹화 영상**을 카메라처럼 사용하려면:

```bash
export CAMERA_SOURCE="/path/to/test.mp4"
uvicorn main:app --port 8800
```

→ 원본 영상의 fps 그대로 실시간 재생되며, 모션 감지/녹화/VLM 파이프라인을 그대로 통과합니다. 끝나면 처음부터 반복 재생.

---

## API 명세

### 클라이언트 백엔드 (`http://localhost:8800`)

**WebSocket**
- `/ws/stream` — 실시간 프레임 + 모션 플래그. 메시지: `{frame: <base64 jpeg>, motion: bool, timestamp: ISO}` 또는 keep-alive `{ping: true}`.

**REST**

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/recordings` | 녹화 목록 (`?date=YYYY-MM-DD`, 실제 파일 존재 시에만) |
| GET | `/api/recordings/{id}` | 녹화 상세 + 연결된 움직임 로그 |
| GET | `/api/recordings/{id}/video` | 영상 파일 스트리밍 (HTTP Range 완전 지원 → seek 가능) |
| DELETE | `/api/recordings/{id}` | 영상·DB·연결 로그·부산물(`_raw.mp4`/`_vlm.mp4`) 일괄 삭제 |
| GET | `/api/logs` | 움직임 로그 목록 (`?period=day\|week\|month`) |
| GET | `/api/logs/{id}` | 로그 상세 (연결 녹화 정보 포함) |
| GET | `/api/settings` | 런타임 설정 + 허용 범위 |
| PUT | `/api/settings` | 설정 변경 (`{"silence_sec": 45}`) — 즉시 반영 |

### VLM 서버 (`http://<AWS-IP>:8001`)

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/health` | `{"status":"ok","model":...,"device":"cuda"}` |
| POST | `/describe` | multipart: `file=<영상>`, `question=<텍스트 선택>` → `{"description":"...", "elapsed_sec":1.42}` |

---

## 전처리 (VLM 입력) 파라미터

`client/backend/preprocess.py` 상단:

```python
REDUCE     = 2    # 1/REDUCE 로 가로/세로 축소 (1280x720 → 640x360 = 360p)
TARGET_FPS = 4    # 결과 영상 초당 프레임 수
```

팀 사전 실험에서 **360p / 4fps가 인식 신뢰도 마지노선**(이 이하로 내리면 객체를 오인하기 시작)으로 검증되어 기본값으로 채택. 더 가볍게 가려면 `REDUCE=4, TARGET_FPS=2`(180p·2fps)도 가능하나 인식률 하락 감수.

### 개발자용: 실제로 VLM에 보낸 영상 확인

전처리 결과는 자동 삭제되지 않고 녹화 옆에 보관됩니다:

```
client/backend/recordings/2026-05-12/14-30-05.mp4         ← 원본 녹화 (720p)
client/backend/recordings/2026-05-12/14-30-05_vlm.mp4     ← VLM에 보낸 다운샘플본 (360p, 4fps)
```

VLC/QuickTime 등으로 직접 열어보면 됩니다. (해당 녹화를 삭제하거나 30일 정리 시 함께 삭제됨)

---

## 모션 감지 파라미터 튜닝

`client/backend/motion_detector.py` 상단:

```python
BLUR_SIZE        = (21, 21)
THRESHOLD_VALUE  = 25       # 이진화 임계값 (높을수록 둔감)
MIN_CONTOUR_AREA = 1500     # 최소 움직임 면적 (높을수록 둔감)
DILATE_ITER      = 2
```

특정 영상에 대해 어떻게 감지되는지 시각적으로 보려면:

```bash
cd client/backend
python debug.py /path/to/video.mp4 --speed 2
```

원본 / 그레이스케일 / 프레임 차이 / 이진화 4분할 창. `debug.py`는 실제 서비스(`camera.py`)와 동일한 함수를 사용하므로 여기서 파라미터를 튜닝한 결과가 그대로 서비스에 반영됩니다.

---

## 운영 / 정리 정책

- **30일 자동 삭제** — 매일 00:00 (`scheduler.py`). 30일 초과 녹화의 `.mp4` + `_raw.mp4` + `_vlm.mp4` + DB의 `recordings`·`motion_logs` 일괄 삭제, 빈 날짜 폴더도 제거.
- **수동 삭제** — `/playback` 페이지의 🗑 버튼 또는 `DELETE /api/recordings/{id}`.
- **DB 초기화** — 깨끗이 다시 시작하고 싶으면 `client/backend/cctv.db*` 와 `client/backend/recordings/` 안의 날짜 폴더 삭제. 백엔드 재실행 시 `init_db()`가 테이블 자동 재생성.

---

## 트러블슈팅

| 증상 | 확인 |
|------|------|
| 백엔드 `Address already in use` (8800) | 이전 uvicorn이 남아있음 → `pkill -f "uvicorn main:app"` 후 재실행. 다른 프로세스(VSCode 등)가 잡고 있으면 `lsof -nP -iTCP:8800 -sTCP:LISTEN`로 확인 |
| 프론트에서 "서버에 연결 중..." 만 계속 | 백엔드 콘솔에 에러 없는지 + `curl http://localhost:8800/` 로 직접 확인 + 브라우저 DevTools `Network`/`Console` 탭 |
| VLM 호출 시 타임아웃/연결 거부 | ① AWS 보안그룹 인바운드 8001 열려있는지 ② AWS `uvicorn app:app --host 0.0.0.0 ...` 가 살아있는지 ③ `VLM_SERVER_URL` IP가 현재 인스턴스 퍼블릭 IP인지 (stop/start 시 IP 바뀜 — Elastic IP 권장) |
| 1~2초짜리 짧은 녹화가 잔뜩 생김 | 백엔드가 도중에 재시작되는 중 (`--reload` 가 파일 변화 감지 등). `--reload` 빼고 실행 |
| 로그에 "움직임 감지됨"만 나오고 실제 설명이 없음 | `VLM_SERVER_URL` 미설정이거나 VLM 호출이 모두 실패하는 상태. 백엔드 콘솔의 `[VLM] ...` 로그 확인 |
| 영상이 브라우저에서 안 재생됨 | mp4v 코덱으로 저장되고 FFmpeg가 없어 remux 실패한 경우. `brew install ffmpeg` 후 재실행. (avc1을 직접 쓸 수 있는 환경이면 FFmpeg 불필요) |

---

## 라이선스 / 데이터 출처

- 코드: 캡스톤 프로젝트 내부 사용.
- 테스트에 사용한 외부 영상(공개 라이브캠, UCF-Crime 등)은 각 출처의 라이선스를 따르며, 본 시스템은 **로컬 처리·실험 목적**으로만 사용합니다.
