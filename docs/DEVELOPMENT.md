# 개발 문서

이 문서는 코드가 어떻게 구성되어 있고 각 부분을 어떻게 구현했는지를 설명한다.
프로젝트의 배경과 실험 결과는 [README](../README.md)와 [결과보고서](REPORT.md)에 있다.

## 목차

1. [저장소 구조](#1-저장소-구조)
2. [프로세스 배치와 통신](#2-프로세스-배치와-통신)
3. [클라이언트 백엔드](#3-클라이언트-백엔드)
4. [VLM 어댑터 서버](#4-vlm-어댑터-서버)
5. [프론트엔드](#5-프론트엔드)
6. [연구 파이프라인](#6-연구-파이프라인)
7. [인터페이스 명세](#7-인터페이스-명세)
8. [설정값](#8-설정값)
9. [실행과 검증](#9-실행과-검증)
10. [구현 중 만난 문제와 해결](#10-구현-중-만난-문제와-해결)

---

## 1. 저장소 구조

```
scene_log/
├── client/
│   ├── backend/                  카메라가 연결된 PC에서 실행하는 FastAPI 서버
│   │   ├── main.py               앱 진입점. DB, 카메라, 스케줄러 기동과 라우터 등록
│   │   ├── camera.py             캡처 루프, WebSocket 브로드캐스트, MotionSession
│   │   ├── motion_detector.py    프레임 차분 기반 움직임 감지
│   │   ├── recorder.py           세션 단위 녹화, 코덱 선택, FFmpeg remux
│   │   ├── preprocess.py         VLM 입력용 다운샘플
│   │   ├── ai_describer.py       VLM 서버 호출과 로그 기록
│   │   ├── database.py           SQLite 스키마, 마이그레이션, 쿼리, 임베딩 검색
│   │   ├── scheduler.py          보관 기간이 지난 녹화 삭제
│   │   ├── debug.py              움직임 감지 단계 시각화 도구
│   │   ├── ingest_video.py       영상 파일을 녹화로 등록하는 명령행 도구
│   │   ├── routers/
│   │   │   ├── stream.py         WebSocket /ws/stream
│   │   │   ├── recordings.py     녹화 목록, 상세, 삭제, 영상 스트리밍
│   │   │   ├── logs.py           로그 목록, 검색, 상세
│   │   │   └── settings.py       런타임 설정
│   │   └── requirements.txt
│   └── frontend/                 React 단일 페이지 앱 (Vite)
│       ├── src/
│       │   ├── main.jsx, App.jsx     진입점과 라우팅
│       │   ├── api/index.js          REST 호출 함수
│       │   ├── store/index.js        Zustand 전역 상태
│       │   ├── anomaly.js            이상 유형 한국어 표시명, 시간 포맷
│       │   ├── components/           Sidebar, VideoPlayer, MotionLogList
│       │   ├── pages/                LivePage, PlaybackPage, LogPage, SettingsPage
│       │   └── index.css             전체 스타일
│       └── vite.config.js            /api, /ws 를 백엔드로 프록시
├── server/
│   ├── app.py                    GPU 서버에서 실행하는 VLM 어댑터
│   └── requirements.txt
├── research/                     데이터 구축, 학습, 평가 스크립트와 산출물
│   ├── *.py                      파이프라인 스크립트 6개
│   ├── lf/                       LLaMA-Factory 학습·병합 설정
│   ├── clips/                    클립 메타데이터, teacher 로그
│   ├── eval/                     조건별 지표
│   └── demo/                     시연용 영상 구성과 실행 기록
├── scripts/                      실행 스크립트
│   ├── run_client.sh             백엔드와 프론트엔드를 함께 실행
│   ├── run_backend.sh
│   ├── run_frontend.sh
│   └── run_server.sh             GPU 서버용 (vLLM, 어댑터)
├── docs/                         개발 문서, 결과보고서, AI 활용보고서
├── .env.example                  백엔드 환경변수 예시
└── README.md
```

코드는 실행 위치를 기준으로 나눴다. `client/`는 카메라가 달린 PC에서, `server/`는 GPU 서버에서, `research/`는 학습과 평가를 할 때만 GPU 서버에서 실행한다.

---

## 2. 프로세스 배치와 통신

실행 중에는 프로세스 네 개가 동작한다.

| 위치 | 프로세스 | 포트 | 역할 |
|---|---|---|---|
| 클라이언트 PC | `client/backend` (uvicorn) | 8800 | 캡처, 감지, 녹화, DB, REST, WebSocket |
| 클라이언트 PC | `client/frontend` (Vite) | 5173 | 웹 UI. `/api`, `/ws`를 8800으로 프록시 |
| GPU 서버 | `server/app.py` (uvicorn) | 8010 | 영상을 창 단위 로그로 변환, 임베딩 |
| GPU 서버 | vLLM | 8002 | LoRA 병합 모델 서빙 (OpenAI 호환 API) |

통신 경로는 세 가지다.

- **브라우저와 백엔드**: 실시간 영상은 WebSocket, 나머지는 REST다.
- **백엔드와 어댑터**: 녹화가 끝날 때마다 전처리한 mp4를 `POST /describe`로 올린다. 검색할 때는 `POST /embed`로 질의 임베딩을 받는다.
- **어댑터와 vLLM**: 같은 서버 안에서 `POST /v1/chat/completions`를 호출한다. vLLM 포트는 외부에 열지 않는다.

GPU가 필요한 연산은 모두 서버에 있다. 클라이언트는 OpenCV, SQLite, numpy만 사용한다. 서버가 꺼져 있어도 클라이언트는 녹화와 재생을 계속하고, 로그 설명만 기본 문구로 대체한다.

---

## 3. 클라이언트 백엔드

### 3.1 앱 기동 (`main.py`)

FastAPI의 `lifespan` 컨텍스트에서 다음 순서로 기동한다.

1. `init_db()`로 테이블을 만들고 부족한 열을 추가한다.
2. `camera_manager.start()`로 캡처 태스크를 시작한다.
3. `start_scheduler()`로 자정 삭제 작업을 등록한다.

순서가 중요하다. 카메라는 시작할 때 `settings` 테이블에서 침묵 시간을 읽기 때문에 DB 초기화가 먼저 끝나야 한다. 종료할 때는 카메라와 스케줄러를 내린다. CORS는 Vite 개발 서버(5173)만 허용한다.

### 3.2 캡처와 세션 (`camera.py`)

`CameraManager`는 모듈 수준 싱글턴이다. asyncio 태스크 하나가 캡처 루프를 돈다.

**입력 소스.** `CAMERA_SOURCE` 환경변수가 있으면 그 파일이나 스트림을 열고, 없으면 0번 웹캠을 연다. 둘 다 실패하면 검은 화면에 시각을 그리는 데모 루프로 전환한다. 파일 입력은 원본 fps로 재생한다. 이렇게 해야 침묵 시간 계산이 영상 속 시간과 맞는다. 파일이 끝나면 처음으로 되감고 감지기의 이전 프레임을 초기화한다. 초기화하지 않으면 마지막 프레임과 첫 프레임의 차이가 움직임으로 잡힌다.

**블로킹 호출 분리.** `cv2.VideoCapture.read()`는 블로킹이므로 `loop.run_in_executor`로 스레드 풀에서 실행한다. 이벤트 루프는 WebSocket 전송과 REST 응답을 계속 처리한다.

**프레임 처리 순서.** `_process_frame`은 프레임마다 다음을 수행한다.

1. `MotionDetector.detect()`로 움직임을 감지한다.
2. 움직임이 있으면 `MotionSession.on_motion()`을 호출한다.
3. `MotionSession.check_silence()`로 침묵 시간을 확인한다.
4. 녹화 중이면 `Recorder.write_frame()`으로 프레임을 쓴다.
5. 세션 상태에 따라 빨간 테두리와 시각을 그린다.
6. JPEG(품질 75)로 인코딩하고 base64 문자열로 구독자에게 보낸다.

**MotionSession.** 녹화 구간을 결정하는 상태 기계다. 상태는 활성 여부, 시작 시각, 마지막 움직임 시각, 최대 강도 네 가지다.

- 비활성 상태에서 움직임이 오면 활성으로 바꾸고 녹화를 시작한다.
- 활성 상태에서 움직임이 오면 마지막 움직임 시각만 갱신한다.
- 마지막 움직임 이후 `silence_sec`가 지나면 `_finalize()`를 호출한다.

`_finalize()`는 로그 행을 먼저 만든 뒤 녹화를 끝낸다. 로그 행의 설명은 비워 두고, 녹화 파일이 완성되면 콜백에서 채운다. `recording_id`는 `stop_recording()`이 내부 상태를 지우기 전에 읽어야 하므로 호출 순서를 고정했다.

**구독자 관리.** WebSocket 연결마다 크기 4의 `asyncio.Queue`를 하나씩 만든다. 큐가 가득 차면 그 프레임은 버린다. 느린 클라이언트 하나가 캡처 루프를 막지 않도록 하기 위해서다.

**런타임 설정.** `silence_sec`는 3초에서 600초 사이로 제한하고 `settings` 테이블에 저장한다. 값을 바꾸면 다음 프레임부터 바로 적용된다.

### 3.3 움직임 감지 (`motion_detector.py`)

프레임 차분 방식이다. 처리 단계를 함수 네 개로 나눴다.

| 함수 | 처리 | 파라미터 |
|---|---|---|
| `to_gray` | 그레이스케일 변환 후 가우시안 블러 | `BLUR_SIZE = (21, 21)` |
| `calc_diff` | 이전 프레임과의 절대차 | |
| `to_binary` | 임계값 이진화 후 팽창 | `THRESHOLD_VALUE = 25`, `DILATE_ITER = 2` |
| `find_motion` | 외곽선 검출 후 면적 필터 | `MIN_CONTOUR_AREA = 1500` |

`find_motion`은 면적 기준을 넘는 외곽선과 강도를 반환한다. 강도는 유효 외곽선 면적의 합을 전체 픽셀 수로 나눈 값이다. `MotionDetector.detect()`는 이전 그레이 프레임을 보관하면서 네 함수를 순서대로 호출하고, 유효 외곽선이 있으면 `RawMotion`을 반환한다.

단계를 함수로 나눈 이유는 `debug.py`가 같은 함수를 가져다 쓰기 때문이다. `debug.py`는 원본, 그레이스케일, 차분, 이진화 결과를 창 네 개로 보여 주므로 파라미터를 바꿨을 때의 효과를 바로 확인할 수 있다.

### 3.4 녹화 (`recorder.py`)

**코덱 선택.** 모듈을 불러올 때 `_pick_fourcc()`가 한 번 실행된다. 64×64 프레임 한 장을 avc1로 써 보고 파일 크기가 1000바이트를 넘으면 avc1을 쓴다. 실패하면 mp4v를 쓴다. OpenCV 빌드에 따라 H.264 인코더가 없을 수 있어서 실제로 써 보는 방식으로 판별한다.

**파일 경로.** 녹화는 `recordings/YYYY-MM-DD/HH-MM-SS.mp4`에 저장한다. 쓰는 동안에는 `_raw.mp4` 접미사를 붙인 임시 파일에 쓴다. 프레임은 모두 1280×720으로 맞춘다.

**마무리.** `stop_recording()`은 writer를 닫고 인스턴스 상태를 지역 변수로 복사한 뒤 초기화한다. 그다음 데몬 스레드에서 `_finalize_file()`을 실행한다. 상태를 먼저 비우기 때문에 마무리가 진행되는 동안 다음 녹화를 시작할 수 있다.

`_finalize_file()`의 동작은 코덱에 따라 다르다.

- avc1이면 임시 파일의 이름만 바꾼다.
- mp4v이면 `ffmpeg -c copy -movflags +faststart`로 컨테이너를 다시 만든다. 재인코딩은 하지 않는다. `+faststart`는 moov atom을 파일 앞으로 옮겨 브라우저가 전체를 받기 전에 재생을 시작할 수 있게 한다.
- FFmpeg가 없거나 실패하면 임시 파일을 그대로 최종 파일로 쓴다.

어느 경로든 최종 파일이 생기면 `recordings` 행에 종료 시각, 길이, 크기를 기록하고 `on_complete(final_path)` 콜백을 호출한다. 프레임이 한 장도 없으면 파일과 DB 행을 지운다.

### 3.5 전처리 (`preprocess.py`)

`downsample_video()`는 녹화 파일을 VLM 입력용으로 줄인다. 기본값은 해상도 1/2, 약 4fps다. 1280×720 녹화는 640×360이 된다.

두 가지 처리가 들어 있다.

- **실제 fps 기록.** 프레임 간격은 `round(원본fps / 4)`다. 15fps 원본이면 4프레임마다 한 장을 쓰므로 실제 fps는 3.75다. 결과 파일에 이 값을 기록한다. 4를 기록하면 재생 시간이 원본보다 짧아져서 서버가 계산한 창 시각이 원본 녹화와 어긋난다.
- **최소 높이.** 축소 후 높이가 240 미만이 되면 축소하지 않는다. 저해상도 입력이 더 작아지는 것을 막는다.

결과는 `<이름>_vlm.mp4`로 녹화 옆에 남긴다. 서버에 실제로 보낸 입력을 나중에 확인할 수 있다.

### 3.6 VLM 호출과 로그 기록 (`ai_describer.py`)

`describe_recording(log_id, video_path)`가 진입점이다. 녹화 마무리 스레드에서 호출되므로 동기 함수로 작성했고 HTTP 클라이언트도 `httpx`의 동기 API를 쓴다.

처리 순서는 다음과 같다.

1. `downsample_video()`로 전처리한다.
2. `describe_video()`가 mp4를 multipart로 `/describe`에 올리고 응답 JSON을 받는다.
3. `_store_logs()`가 응답의 `logs[]`를 DB에 기록한다.

`_store_logs()`는 파싱에 성공한 창만 사용한다. 첫 창은 세션 종료 때 만든 행을 갱신하고, 두 번째 창부터는 새 행을 추가한다. 새 행의 `detected_at`은 녹화 시작 시각에 창 시작 오프셋을 더한 값이다. 이렇게 하면 로그 목록에서 창마다 실제 발생 시각이 표시된다.

서버 주소가 없거나, 요청이 실패하거나, 파싱된 창이 하나도 없으면 설명에 `"움직임 감지됨"`만 기록한다. 예외는 모두 잡아서 콘솔에 출력하고 녹화 스레드는 정상 종료한다.

`embed_text()`는 검색 질의를 `/embed`로 보내 벡터를 받는다.

### 3.7 데이터베이스 (`database.py`)

SQLite를 WAL 모드로 쓴다. 캡처 루프, 녹화 스레드, REST 핸들러가 동시에 접근하므로 함수마다 연결을 열고 닫는다.

**마이그레이션.** `init_db()`는 `CREATE TABLE IF NOT EXISTS`를 실행한 뒤 `_migrate_motion_logs()`를 호출한다. 이 함수는 `PRAGMA table_info(motion_logs)`로 현재 열 목록을 읽고 `VLM_COLUMNS`에 있는데 테이블에 없는 열만 `ALTER TABLE ADD COLUMN`으로 추가한다. 이전 버전의 DB 파일을 그대로 쓸 수 있다.

**임베딩 저장.** 1024차원 벡터를 float32 바이트열(4096바이트)로 바꿔 BLOB 열에 넣는다. `embedding_to_blob`과 `blob_to_embedding`이 변환을 맡는다.

**API 변환.** `_row_to_log()`는 행을 dict로 바꾸면서 `embedding`을 빼고 `objects_json`을 리스트로 파싱한다. 벡터를 응답에 실으면 로그 하나당 수 KB가 늘어나므로 제외했다.

**기간 필터.** `detected_at`은 `YYYY-MM-DDTHH:MM:SS` 형식의 로컬 시각 문자열이다. `_period_clause()`는 `T`를 공백으로 바꿔 SQLite의 `datetime('now', 'localtime', '-N days')`와 문자열 비교가 되도록 한다.

**검색.** `search_motion_logs()`는 기간과 이상 여부 조건에 맞고 임베딩이 있는 행을 모두 읽는다. 행렬로 쌓아 질의 벡터와 내적을 구하고 상위 `top_k`개를 반환한다. 양쪽을 다시 정규화하므로 내적이 코사인 유사도다. 보관 기간이 30일이라 로그 수가 수천 개 수준이어서 별도의 벡터 인덱스 없이 전수 계산으로 처리한다.

### 3.8 라우터 (`routers/`)

**`stream.py`.** WebSocket 연결을 받으면 구독 큐를 만들고 큐에서 꺼낸 메시지를 JSON으로 보낸다. 5초 동안 프레임이 없으면 `{"ping": true}`를 보내 연결을 유지한다. 연결이 끊기면 `finally`에서 구독을 해제한다.

**`recordings.py`.** 목록은 최종 mp4 파일이 실제로 존재하는 녹화만 반환한다. remux가 끝나지 않은 녹화는 자동으로 빠진다. 삭제는 본 파일, `_raw.mp4`, `_vlm.mp4`, DB 행, 연결된 로그를 함께 지운다.

영상 스트리밍은 Range 요청을 직접 처리한다. `Range: bytes=start-end` 헤더를 파싱해서 해당 구간만 1MB 단위로 읽어 보내고 상태 코드 206과 `Content-Range`를 붙인다. 브라우저의 `<video>`는 탐색할 때 Range 요청을 보내므로 이 처리가 없으면 로그를 눌러 특정 시각으로 이동할 수 없다.

**`logs.py`.** 목록, 검색, 상세 세 가지다. `/search`는 `/{log_id}`보다 먼저 선언했다. 순서가 바뀌면 FastAPI가 `search`를 정수 `log_id`로 해석하려다 422를 반환한다. `type` 파라미터는 13개 유형 목록에 없으면 400을 반환한다. 검색은 서버 주소가 없으면 503, 임베딩 요청이 실패하면 502를 반환한다.

**`settings.py`.** 현재 값과 허용 범위를 반환하고 변경 요청을 `CameraManager`에 전달한다.

### 3.9 자동 삭제 (`scheduler.py`)

APScheduler의 `AsyncIOScheduler`로 매일 00:00에 `delete_old_recordings()`를 실행한다. 시작 시각이 30일보다 오래된 녹화를 찾아 파일과 부산물, 로그 행, 녹화 행을 지우고 빈 날짜 폴더를 정리한다.

### 3.10 영상 등록 도구 (`ingest_video.py`)

영상 파일을 녹화처럼 등록하는 명령행 도구다. 캡처와 움직임 감지를 건너뛰고 `recordings/`에 복사, `recordings` 행 등록, 빈 로그 행 생성, `describe_recording()` 호출 순으로 처리한다. 백엔드와 같은 DB 파일을 쓰므로 결과가 웹 UI에 바로 보인다. `--at`으로 녹화 시작 시각을 지정할 수 있고, 여러 파일을 주면 앞 영상의 길이만큼 시각을 뒤로 밀어 차례로 등록한다. 처리 후에는 창별 판정과 요약을 콘솔에 출력한다.

카메라 없이 로그 생성과 화면을 확인하거나 미리 찍어 둔 영상을 시연에 쓸 때 사용한다.

### 3.11 스레드와 동시성 정리

| 실행 단위 | 하는 일 |
|---|---|
| asyncio 이벤트 루프 | 캡처 루프, WebSocket, REST, 스케줄러 |
| 스레드 풀 | `VideoCapture.read()` |
| 녹화 마무리 스레드 (녹화마다 1개) | remux, 전처리, VLM 요청, 로그 기록 |

VLM 요청은 수 초에서 수십 초가 걸린다. 이 작업을 마무리 스레드 안에서 처리하므로 캡처 루프는 지연 없이 다음 세션을 녹화한다.

---

## 4. VLM 어댑터 서버

`server/app.py` 한 파일이다. vLLM 앞에서 영상 디코딩, 프레임 선택, 프롬프트 구성, 출력 파싱, 임베딩을 맡는다. 모델 추론 자체는 vLLM에 위임한다.

### 4.1 창 분할 (`extract_windows`)

영상을 한 번 순차 디코딩하면서 `window_sec`(기본 20초) 단위로 끊는다. 프레임 시각은 `인덱스 / fps`로 계산한다. 현재 창의 시작에서 `window_sec` 이상 지나면 창을 닫고 새 창을 연다. 프레임마다 160×120 그레이스케일로 줄여 직전 프레임과의 절대차 평균을 점수로 저장한다. 점수는 창이 바뀔 때 새로 시작한다.

마지막 창이 `MIN_TAIL_SEC`(3초)보다 짧으면 앞 창에 합친다. 1~2초짜리 창은 프레임이 부족해서 따로 처리하지 않는다.

fps 메타데이터가 없거나 0 이하, 240 초과이면 4로 간주한다.

### 4.2 프레임 선택 (`pick_change_frames`)

창 하나에서 8장을 고른다. 프레임 인덱스를 8개 구간으로 등분하고 구간마다 차분 점수가 가장 큰 프레임을 고른다. 등분 때문에 시간축 전체가 고르게 포함되고, 구간 안에서는 변화가 가장 큰 순간이 선택된다. 창의 프레임이 8장보다 적으면 같은 프레임을 반복해서 8장을 채운다.

이 규칙은 학습 데이터를 만들 때 쓴 `research/make_clips.py`의 규칙과 같다. 학습과 추론의 입력 분포를 맞추기 위해서다.

### 4.3 모델 호출 (`vllm_describe`)

선택한 8장을 JPEG(품질 90)로 인코딩해 base64 data URL로 만든다. 이미지 8개 뒤에 `INSTRUCTION` 텍스트를 붙인 사용자 메시지 하나로 `chat/completions`를 호출한다. `temperature`는 0, `max_tokens`는 400이다.

`INSTRUCTION`은 학습 데이터의 사용자 프롬프트와 같은 문자열이다. LoRA는 이 프롬프트에 대한 응답 형식을 학습했으므로 추론에서도 바꾸지 않는다. 클라이언트가 보내는 `question` 필드는 받기만 하고 쓰지 않는다.

모델 id는 환경변수로 지정하거나, 비워 두면 vLLM의 `/v1/models` 응답에서 첫 번째를 쓴다. 기동 시점에 vLLM이 꺼져 있어도 요청이 올 때 다시 조회한다.

### 4.4 출력 파싱 (`parse_log`)

모델 출력에서 정규식 `\{.*\}`로 중괄호 블록을 찾아 JSON으로 읽는다. `is_anomaly`나 `anomaly_type` 키가 없으면 실패로 처리한다. 성공하면 다음과 같이 정규화한다.

- `is_anomaly`는 `"이상"`이 아니면 모두 `"정상"`으로 바꾼다.
- `anomaly_type`이 14개 허용 값에 없으면 `"None"`으로 바꾼다.
- `is_anomaly`가 `"정상"`이면 `anomaly_type`을 `"None"`으로 맞춘다.
- `objects`가 리스트가 아니면 빈 리스트로 바꾼다.
- `scene`, `action`, `summary`는 문자열로 변환한다.

파싱에 실패한 창은 `log`가 `null`이고 `raw`에 원문이 남는다.

### 4.5 임베딩 (`load_embedder`, `embed_texts`)

BAAI/bge-m3를 `transformers`의 `AutoModel`로 직접 불러온다. 마지막 은닉 상태의 CLS 토큰을 꺼내 L2 정규화한 1024차원 벡터를 쓴다. GPU에서는 float16으로 올린다. 추론은 `threading.Lock`으로 한 번에 하나씩 처리한다.

로그의 임베딩 대상 텍스트는 `summary + " " + action`이다. 요약만 쓰면 문장이 짧아 검색어와 겹치는 표현이 적어서 동작 문장을 함께 넣었다.

`EMBED_DISABLE=1`이면 모델을 올리지 않는다. 이때 `/describe`는 임베딩 없이 동작하고 `/embed`는 503을 반환한다.

### 4.6 요청 처리와 오류 코드 (`describe`)

업로드 파일을 임시 파일로 저장하고 창 분할, 창별 모델 호출, 일괄 임베딩 순으로 처리한 뒤 `finally`에서 임시 파일을 지운다. 창은 순서대로 하나씩 처리한다.

| 상황 | 응답 |
|---|---|
| `window_sec`가 3~120 범위를 벗어남 | 400 |
| 영상을 열 수 없거나 프레임이 없음 | 400 |
| vLLM 호출 실패 | 502 |
| `/embed`에서 임베딩 모델이 없음 | 503 |
| `/embed`의 `text`가 비어 있음 | 400 |

`/health`는 요청할 때마다 vLLM의 모델 목록을 조회해 `status`를 `ok` 또는 `degraded`로 반환한다.

---

## 5. 프론트엔드

React 18, React Router 6, Zustand, Axios, dayjs를 쓴다. 빌드 도구는 Vite다. 개발 서버가 `/api`와 `/ws`를 백엔드로 프록시하므로 코드에서는 상대 경로만 쓴다.

### 5.1 라우팅과 전역 상태

`App.jsx`가 사이드바와 네 개 경로(`/live`, `/playback`, `/logs`, `/settings`)를 구성한다. 루트는 `/live`로 보낸다.

Zustand 스토어에는 두 가지만 둔다.

- `playbackTarget`: 로그를 눌렀을 때 재생할 녹화 id와 시작 오프셋. 로그 페이지가 쓰고 재생 페이지가 읽은 뒤 비운다.
- `motionDetected`: 실시간 페이지의 움직임 표시.

### 5.2 실시간 페이지 (`LivePage.jsx`)

WebSocket 메시지의 base64 JPEG를 `<img>`의 `src`에 직접 넣는다. React 상태를 거치지 않고 ref로 DOM을 갱신하므로 프레임마다 다시 렌더링하지 않는다. 연결이 끊기면 3초 뒤에 다시 연결한다. 언마운트 여부는 ref로 기억해서 페이지를 떠난 뒤에는 재연결하지 않는다. 1초마다 수신 프레임 수를 세어 FPS로 표시한다.

### 5.3 로그 목록 (`MotionLogList.jsx`)

상태는 기간, 이상만 보기, 검색어다. 검색어는 입력 중인 값과 제출된 값을 분리했다. 제출된 값이 있으면 `/api/logs/search`를, 없으면 `/api/logs`를 호출한다.

일반 목록에서는 이상 로그를 위로 올리고 나머지를 뒤에 붙인다. 검색 결과는 서버가 준 유사도 순서를 유지하고 점수를 백분율 배지로 표시한다. 항목마다 판정 배지, 장소 배지, 요약, 동작 문장, 녹화 내 오프셋을 보여 준다. 항목을 누르면 `playbackTarget`을 설정하고 재생 페이지로 이동한다.

### 5.4 재생 페이지 (`PlaybackPage.jsx`, `VideoPlayer.jsx`)

왼쪽에 날짜 선택과 녹화 목록, 오른쪽에 플레이어와 구간 로그가 있다. 로그 페이지에서 넘어온 경우 마운트할 때 `playbackTarget`을 읽어 해당 녹화를 불러오고 시작 오프셋을 설정한다.

`VideoPlayer`는 타임라인을 직접 그린다. 로그마다 `window_start`와 `window_end`를 영상 길이에 대한 비율로 바꿔 막대를 배치한다. 이상은 빨강, 정상은 파랑이다. 막대를 누르면 그 창의 시작으로 이동한다. 시작 오프셋은 `onLoadedMetadata`와 `useEffect` 양쪽에서 적용한다. 메타데이터가 로드되기 전에는 `currentTime`을 설정해도 반영되지 않기 때문이다.

구간 로그 목록의 항목을 누르면 `startOffset`에 창 시작 + 0.001을 넣는다. 같은 항목을 다시 눌러도 값이 바뀌지 않으면 `useEffect`가 실행되지 않으므로 값을 조금 다르게 준다.

### 5.5 표시명 (`anomaly.js`)

이상 유형은 DB와 API에서 영문 열거형으로 다루고 화면에서만 한국어로 바꾼다. `ANOMALY_LABELS`가 대응표다.

---

## 6. 연구 파이프라인

`research/`의 스크립트는 순서대로 실행한다. 각 단계의 출력이 다음 단계의 입력이다.

```
UCF-Crime 영상 + UCA 주석
   │  build_uca_table.py
   ▼
uca_segments.csv (구간 23,542개)
   │  classify_segments.py   (Qwen3-8B, 텍스트)
   ▼
uca_segments.csv + seg_is_anomaly
   │  make_clips.py
   ▼
clips/manifest.csv, clips/frames/<clip_id>/{change,uniform}/f0..f7.jpg
   │  teacher_logs.py        (Qwen3-VL-32B)
   ▼
clips/teacher_logs.jsonl
   │  convert_lf.py
   ▼
lf/data/cctv_{train,val,test}.json
   │  LLaMA-Factory (train_lora.yaml, merge_lora.yaml)
   ▼
병합 모델
   │  eval_test.py
   ▼
eval/<이름>.jsonl, eval/<이름>_metrics.json
```

### 6.1 `build_uca_table.py`

UCA의 Train, Val, Test JSON 세 개를 합쳐 구간 하나당 한 줄인 CSV를 만든다. UCA JSON은 영상 이름을 키로 하고 `duration`, `timestamps`, `sentences`를 값으로 가진다. 영상 이름에서 유형을 추출하고 UCF-Crime의 공식 분할과 파일 경로를 붙인다. 문장에 쉼표가 들어 있으므로 CSV는 `csv` 모듈로 읽고 쓴다.

### 6.2 `classify_segments.py`

UCA의 구간은 "무언가 일어난 구간"이어서 이상 영상 안에도 평범한 장면이 많다. 이 스크립트는 구간 문장이 사건 자체인지 전후의 평범한 장면인지를 가른다. 정상 영상의 구간은 모두 0으로 두고, 이상 영상의 구간 8,347개만 Qwen3-8B에 묻는다.

시스템 프롬프트는 과제를 설명하고 `anomaly` 또는 `normal` 한 단어로 답하게 한다. 사용자 메시지에는 유형 이름, 유형의 한 줄 정의(`DEF`), 구간 문장을 넣는다. `temperature` 0, `max_tokens` 4, thinking은 끈다. 스레드 32개로 동시에 요청하고 실패하면 최대 3번 시도한다. 응답이 두 단어 중 하나로 시작하지 않으면 라벨을 비워 둔다. 원문 응답은 `seg_label_raw` 열에 남긴다.

### 6.3 `make_clips.py`

1. 겹치는 구간을 합친다. 하나라도 이상이면 이상으로 두고 문장은 ` || `로 잇는다.
2. 3초 미만은 버리고 60초를 넘으면 앞 60초만 쓴다.
3. 이상 구간 전부, 정상 영상에서 편당 최대 4개(`NORMAL_PER_VIDEO`), 이상 영상 속 정상 구간을 고른다. 이상 영상 속 정상 구간은 학습 분할에서 최대 `HARD_NEG_TRAIN`개를 무작위로 뽑고 테스트 분할에서는 전부 쓴다. 난수 시드는 0으로 고정했다.
4. 구간을 디코딩해 8장을 뽑는다. `change`는 8등분한 각 구간에서 차분이 가장 큰 프레임, `uniform`은 각 구간의 가운데 프레임이다. 디코딩된 프레임이 8장 미만인 클립은 제외한다.

프레임 추출은 `ProcessPoolExecutor`로 클립 단위 병렬 처리한다.

클립 id는 `{영상이름}_{시작초×10, 6자리}`다. 영상 클립은 만들지 않고 프레임만 JPEG(품질 90)로 저장한다.

### 6.4 `teacher_logs.py`

Qwen3-VL-32B에 `change` 프레임 8장과 해당 구간의 UCA 영어 문장을 주고 `scene`, `objects`, `action`, `summary`를 한국어 JSON으로 받는다. `is_anomaly`와 `anomaly_type`은 모델에 묻지 않고 manifest의 라벨을 코드로 넣는다.

시스템 프롬프트에 네 가지 규칙을 적었다. 화면에 보이는 것만 쓴다. 의도·감정·원인을 추측하지 않는다. 외모 평가와 인종 표현을 쓰지 않는다. JSON 한 덩어리만 출력한다. 참고 문장은 800자까지만 넣는다. `temperature`는 0.2다. 응답에서 JSON을 추출해 네 개 키가 모두 있는지 확인하고 실패하면 한 번 더 시도한다.

결과는 한 줄씩 바로 파일에 덧붙인다. 이미 처리한 클립 id는 건너뛰므로 중단 후 다시 실행해도 된다. `--n 300`은 학습 분할에서 이상과 정상을 절반씩 뽑아 시험 생성하는 옵션이다.

### 6.5 `convert_lf.py`

LLaMA-Factory의 sharegpt 멀티모달 형식으로 바꾼다. 사용자 메시지는 `<image>` 8개와 `INSTRUCTION`, 어시스턴트 메시지는 목표 JSON 문자열, `images`는 프레임 절대경로 8개다. 검증 세트는 학습 영상의 10%를 영상 단위로 떼어 만든다. 같은 영상의 클립이 학습과 검증에 나뉘어 들어가지 않게 하기 위해서다. 평가용으로 `uniform` 프레임을 쓴 테스트 파일도 함께 만든다.

### 6.6 학습과 병합 (`lf/train_lora.yaml`, `lf/merge_lora.yaml`)

| 항목 | 값 |
|---|---|
| 베이스 모델 | Qwen/Qwen3-VL-8B-Instruct |
| LoRA | rank 32, alpha 64, dropout 0.05, 대상 모듈 all |
| 고정 | 비전 인코더, 멀티모달 프로젝터 |
| 입력 | cutoff_len 6144, image_max_pixels 262144 |
| 배치 | 4 × 누적 4 (유효 16) |
| 학습률 | 1e-4, cosine, warmup 0.05 |
| 에폭 | 3 |
| 정밀도 | bf16 |

`llamafactory-cli train`으로 학습하고 `llamafactory-cli export`로 어댑터를 베이스 모델에 병합한다. 병합한 모델 폴더를 vLLM이 그대로 서빙한다. 200 스텝마다 검증 loss를 계산하고 체크포인트를 저장한다.

저장소의 두 yaml은 2차 학습 때의 설정이다. 1차 학습은 출력 경로의 접미사 `-hn`이 없고 `make_clips.py`의 `HARD_NEG_TRAIN`이 600이었다.

### 6.7 `eval_test.py`

테스트 클립 798개에 대해 vLLM 서버를 호출하고 결과를 `eval/<이름>.jsonl`에, 지표를 `eval/<이름>_metrics.json`에 저장한다. 인자로 서버 포트와 프레임 종류를 받는다. 지표는 파싱 성공률, 이상 판정의 정확도·정밀도·재현율·F1, 이상 클립에 한정한 유형 정확도, 유형별 재현율이다. 파싱 기준은 어댑터의 `parse_log`와 같다.

정밀도, 재현율, F1은 파싱에 성공한 클립만으로 계산한다. 정확도는 두 가지를 기록한다. `acc_parsed`는 파싱 성공분만의 정확도이고 `acc_all`은 파싱 실패를 오답으로 친 정확도다. 보고서의 정확도는 `acc_all`이다. 스레드 16개로 동시에 요청하며 798 클립에 약 3분이 걸린다.

---

## 7. 인터페이스 명세

### 7.1 클라이언트 백엔드 (`:8800`)

| 메서드 | 경로 | 설명 |
|---|---|---|
| WS | `/ws/stream` | `{frame, motion, timestamp}` 또는 `{ping: true}` |
| GET | `/api/recordings?date=YYYY-MM-DD` | 녹화 목록 |
| GET | `/api/recordings/{id}` | 녹화 상세와 창 로그 |
| GET | `/api/recordings/{id}/video` | 영상 스트리밍 (Range) |
| DELETE | `/api/recordings/{id}` | 녹화, 로그, 부산물 삭제 |
| GET | `/api/logs?period=&anomaly=&type=` | 로그 목록. 응답에 `anomaly_total` 포함 |
| GET | `/api/logs/search?q=&period=&anomaly=&top_k=` | 자연어 검색. 각 로그에 `score` 포함 |
| GET | `/api/logs/{id}` | 로그 상세 |
| GET | `/api/settings` | 현재 설정과 허용 범위 |
| PUT | `/api/settings` | `{"silence_sec": 45}` |

로그 객체의 필드는 다음과 같다.

```json
{
  "id": 12, "recording_id": 3,
  "detected_at": "2026-11-10T14:30:25",
  "window_start": 20.0, "window_end": 40.0,
  "is_anomaly": 1, "anomaly_type": "Robbery",
  "scene": "편의점", "action": "...", "summary": "...",
  "objects": [{"type": "사람", "count": 2, "appearance": "..."}],
  "description": "...", "intensity": 0.12,
  "filename": "14-30-05.mp4", "filepath": "..."
}
```

### 7.2 VLM 어댑터 (`:8010`)

| 메서드 | 경로 | 요청 | 응답 |
|---|---|---|---|
| GET | `/health` | | `status`, `vllm`, `model`, `embed_ready`, `window_sec` |
| POST | `/describe` | multipart `file`, 선택 `window_sec` | `description`, `logs[]`, `duration_sec`, `n_windows`, `window_sec`, `elapsed_sec` |
| POST | `/embed` | `{"text": "..."}` | `{"embedding": [1024 floats]}` |

`logs[]`의 원소는 `window_start`, `window_end`, `log`, `raw`, `embedding`을 가진다.

### 7.3 모델 출력 스키마

```json
{"scene": "장소 유형",
 "objects": [{"type": "사람|차량|동물|물건", "count": 1, "appearance": "외형"}],
 "action": "관찰 가능한 동작 1문장",
 "is_anomaly": "정상|이상",
 "anomaly_type": "Abuse|Arrest|Arson|Assault|Burglary|Explosion|Fighting|RoadAccidents|Robbery|Shooting|Shoplifting|Stealing|Vandalism|None",
 "summary": "1문장 요약"}
```

### 7.4 DB 스키마

**recordings**

| 열 | 형식 | 설명 |
|---|---|---|
| id | INTEGER PK | |
| filename, filepath | TEXT | |
| started_at, ended_at | DATETIME | ISO 문자열 |
| duration_sec | INTEGER | |
| file_size_mb | REAL | |

**motion_logs**

| 열 | 형식 | 설명 |
|---|---|---|
| id | INTEGER PK | |
| recording_id | INTEGER FK | |
| detected_at | DATETIME | 녹화 시작 + 창 시작 |
| duration_sec | REAL | 창 길이 |
| intensity | REAL | 세션 중 최대 움직임 강도 |
| timestamp_offset_sec | REAL | 녹화 내 오프셋 |
| description | TEXT | summary와 같은 값 또는 기본 문구 |
| window_start, window_end | REAL | 녹화 내 창 구간(초) |
| is_anomaly | INTEGER | 0 또는 1 |
| anomaly_type | TEXT | 영문 열거형 |
| scene, action, summary | TEXT | |
| objects_json | TEXT | JSON 배열 문자열 |
| embedding | BLOB | float32 × 1024 |

**settings**: `key`, `value` 쌍. 현재 `silence_sec` 하나를 쓴다.

인덱스는 `recordings(started_at)`, `motion_logs(detected_at)`, `motion_logs(is_anomaly)`에 있다.

---

## 8. 설정값

### 8.1 환경변수

| 대상 | 변수 | 기본값 | 설명 |
|---|---|---|---|
| 백엔드 | `VLM_SERVER_URL` | 없음 | 어댑터 주소. 없으면 VLM 호출 생략 |
| 백엔드 | `VLM_TIMEOUT` | 300 | 어댑터 응답 대기(초) |
| 백엔드 | `VLM_WINDOW_SEC` | 없음 | 창 길이 지정(3~120) |
| 백엔드 | `CAMERA_SOURCE` | 없음 | 입력 영상 경로 또는 스트림 URL |
| 어댑터 | `VLLM_URL` | `http://localhost:8002` | vLLM 주소 |
| 어댑터 | `VLLM_MODEL` | 자동 | 모델 id |
| 어댑터 | `VLLM_TIMEOUT` | 180 | vLLM 응답 대기(초) |
| 어댑터 | `WINDOW_SEC` | 20 | 창 길이 |
| 어댑터 | `MIN_TAIL_SEC` | 3 | 합칠 꼬리 창 기준 |
| 어댑터 | `EMBED_MODEL` | `BAAI/bge-m3` | 임베딩 모델 |
| 어댑터 | `EMBED_DEVICE` | cuda 또는 cpu | 임베딩 장치 |
| 어댑터 | `EMBED_DISABLE` | 0 | 1이면 임베딩 끔 |

### 8.2 코드 상수

| 파일 | 상수 | 값 |
|---|---|---|
| `camera.py` | `FPS_TARGET` | 15 |
| `camera.py` | `DEFAULT_SILENCE_SEC` | 30 (허용 3~600) |
| `motion_detector.py` | `THRESHOLD_VALUE`, `MIN_CONTOUR_AREA` | 25, 1500 |
| `recorder.py` | `WIDTH`, `HEIGHT`, `FPS` | 1280, 720, 15 |
| `preprocess.py` | `REDUCE`, `TARGET_FPS`, `MIN_HEIGHT` | 2, 4, 240 |
| `scheduler.py` | `RETENTION_DAYS` | 30 |
| `server/app.py` | `N_FRAMES`, `MAX_TOKENS` | 8, 400 |

---

## 9. 실행과 검증

### 9.1 실행

GPU 서버에서 모델 서버와 어댑터를 띄운다.

```bash
GPU=1 MODEL_DIR=/path/to/qwen3vl8b-cctv ./scripts/run_server.sh vllm
```

```bash
GPU=1 ./scripts/run_server.sh
```

클라이언트 PC에서 `.env.example`을 `.env`로 복사해 `VLM_SERVER_URL`을 채운 뒤 실행한다.

```bash
./scripts/run_client.sh
```

서버가 다른 네트워크에 있으면 SSH 터널을 열고 `VLM_SERVER_URL=http://localhost:8010`으로 둔다.

```bash
ssh -N -L 8010:localhost:8010 <계정>@<서버>
```

### 9.2 상태 확인

```bash
curl http://localhost:8010/health
```

```bash
curl http://localhost:8800/
```

어댑터의 `status`가 `degraded`이면 vLLM이 꺼져 있는 것이다.

### 9.3 카메라 없이 검증하기

방법은 세 가지다.

- `CAMERA_SOURCE`에 영상 파일을 지정하면 그 영상이 카메라 입력처럼 감지, 녹화, 전처리, VLM 호출을 모두 거친다. 움직임이 끊이지 않는 영상은 세션이 끝나지 않으므로 `/settings`에서 침묵 시간을 짧게 둔다.
- `ingest_video.py`로 영상을 녹화로 바로 등록한다.
- 어댑터만 따로 확인하려면 파일을 직접 올린다.

```bash
curl -F file=@sample.mp4 http://localhost:8010/describe
```

백엔드 콘솔의 `[VLM] 응답: 창 N개, 이상 M개` 출력으로 서버 연동을 확인한다.

### 9.4 움직임 감지 파라미터 조정

```bash
cd client/backend && python debug.py <영상 경로> --speed 2
```

Space로 일시정지, S로 현재 화면 저장, Q로 종료한다.

---

## 10. 구현 중 만난 문제와 해결

| 문제 | 원인 | 해결 |
|---|---|---|
| 로그의 창 시각이 녹화와 어긋남 | 전처리 파일에 명목 fps 4를 기록해 재생 시간이 약 6% 짧아짐 | 실제 fps(원본fps / 프레임 간격)를 기록 |
| 저해상도 입력에서 판정이 흔들림 | 320×240 입력이 전처리에서 160×120으로 줄어듦 | 축소 후 높이가 240 미만이면 축소하지 않음 |
| `/api/logs/search`가 422를 반환 | `/{log_id}` 라우트가 먼저 매칭됨 | `/search`를 먼저 선언 |
| 긴 창에서 사건을 놓침 | 60초 창은 학습 클립의 길이 분포(평균 17초)를 벗어남 | 기본 창 길이를 20초로 설정 |
| 브라우저에서 녹화가 재생되지 않음 | mp4v 코덱은 브라우저가 지원하지 않는 경우가 있음 | avc1을 우선 시도하고 실패하면 FFmpeg로 remux |
| 영상 탐색이 되지 않음 | Range 요청을 처리하지 않으면 `<video>`가 탐색하지 못함 | 206 부분 응답 구현 |
| 파일 입력 반복 재생 시 거짓 움직임 | 마지막 프레임과 첫 프레임의 차이가 감지됨 | 되감을 때 감지기 초기화 |
| 같은 구간 로그를 다시 눌러도 이동하지 않음 | 상태 값이 같아 `useEffect`가 실행되지 않음 | 오프셋에 0.001을 더해 값 변경 |
| bge-m3 가중치 다운로드가 조용히 실패 | 해당 저장소에는 safetensors가 없고 `pytorch_model.bin`만 있음 | 파일명을 직접 지정해 다운로드 |
| 학습 데이터가 이전 상태로 변환됨 | 클립을 다시 만든 뒤 teacher 로그 생성을 건너뜀 | manifest와 teacher 로그의 줄 수를 맞춰 본 뒤 변환 |
