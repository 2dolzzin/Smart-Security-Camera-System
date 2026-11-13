"""
server/app.py
VLM 어댑터 서버. GPU 서버에서 실행한다.

vLLM 으로 서빙 중인 Qwen3-VL-8B LoRA 병합 모델(OpenAI 호환 API)을 호출하여
영상 파일을 창(window) 단위의 구조화 JSON 로그로 변환하고,
로그 텍스트의 bge-m3 임베딩을 함께 반환한다.

엔드포인트:
  GET  /health
       → {"status": "ok|degraded", "vllm": bool, "model": str,
          "embed_model": str|null, "embed_ready": bool, "window_sec": float}
         vLLM 서버에 연결할 수 없으면 status 는 "degraded".

  POST /describe   (multipart/form-data)
       file       : 영상 파일 (필수)
       question   : 선택. 수신만 하고 사용하지 않는다. 프롬프트는 INSTRUCTION 으로 고정.
       window_sec : 선택. 창 길이(3~120초). 없으면 WINDOW_SEC.
       → {"description": 첫 로그의 summary,
          "logs": [{"window_start": float, "window_end": float,
                    "log": {scene, objects, action, is_anomaly, anomaly_type, summary} | null,
                    "raw": 모델 출력 원문,
                    "embedding": [1024 floats] | null}, ...],
          "duration_sec": float, "n_windows": int, "window_sec": float, "elapsed_sec": float}
         영상을 window_sec 길이의 창으로 나누어 창마다 로그 1개를 만든다.
         MIN_TAIL_SEC 보다 짧은 마지막 창은 앞 창에 합친다.
         JSON 파싱에 실패한 창은 log 와 embedding 이 null.

  POST /embed      (application/json {"text": str})
       → {"embedding": [1024 floats]}

환경변수:
  VLLM_URL        vLLM 서버 주소. 기본 http://localhost:8002
  VLLM_MODEL      모델 id. 비우면 기동 시 {VLLM_URL}/v1/models 의 첫 모델을 사용
  VLLM_TIMEOUT    vLLM 요청 타임아웃(초). 기본 180
  WINDOW_SEC      창 길이(초). 기본 20
  MIN_TAIL_SEC    이보다 짧은 마지막 창은 앞 창에 합친다. 기본 3
  EMBED_MODEL     임베딩 모델. 기본 BAAI/bge-m3
  EMBED_DEVICE    임베딩 모델 장치. 기본 cuda(사용 가능 시) / cpu
  EMBED_DISABLE   "1" 이면 임베딩 모델을 로드하지 않는다 (embedding 은 null, /embed 는 503)

실행:
  uvicorn app:app --host 0.0.0.0 --port 8010
"""

import base64
import contextlib
import json
import os
import re
import tempfile
import threading
import time

import cv2
import numpy as np
import requests
import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

# ───────────────────────── 설정 ─────────────────────────
VLLM_URL = os.getenv("VLLM_URL", "http://localhost:8002").rstrip("/")
VLLM_MODEL = os.getenv("VLLM_MODEL", "")
VLLM_TIMEOUT = float(os.getenv("VLLM_TIMEOUT", "180"))
WINDOW_SEC = float(os.getenv("WINDOW_SEC", "20"))
MIN_TAIL_SEC = float(os.getenv("MIN_TAIL_SEC", "3"))
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
EMBED_DEVICE = os.getenv("EMBED_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
EMBED_DISABLE = os.getenv("EMBED_DISABLE", "0") == "1"

N_FRAMES = 8
MAX_TOKENS = 400

# 학습(research/convert_lf.py)과 평가(research/eval_test.py)에 사용한 프롬프트와 동일한 문자열.
INSTRUCTION = """다음은 CCTV 영상에서 시간순으로 추출한 프레임 8장이다. 아래 JSON 형식으로 로그를 작성하라. 화면에 보이는 것만 기술하고, 의도나 감정은 추측하지 않는다.
{"scene": 장소 유형, "objects": [{"type": "사람|차량|동물|물건", "count": 정수, "appearance": 외형}], "action": 관찰 가능한 동작 1문장, "is_anomaly": "정상|이상", "anomaly_type": "Abuse|Arrest|Arson|Assault|Burglary|Explosion|Fighting|RoadAccidents|Robbery|Shooting|Shoplifting|Stealing|Vandalism|None", "summary": 1문장 요약}"""

ANOMALY_TYPES = {"Abuse", "Arrest", "Arson", "Assault", "Burglary", "Explosion", "Fighting", "RoadAccidents",
                 "Robbery", "Shooting", "Shoplifting", "Stealing", "Vandalism", "None"}


# ───────────────────────── vLLM ─────────────────────────
def vllm_models() -> list[str]:
    r = requests.get(f"{VLLM_URL}/v1/models", timeout=5)
    r.raise_for_status()
    return [m["id"] for m in r.json().get("data", [])]


def resolve_model() -> str:
    global VLLM_MODEL
    if not VLLM_MODEL:
        with contextlib.suppress(Exception):
            ids = vllm_models()
            if ids:
                VLLM_MODEL = ids[0]
    return VLLM_MODEL


def b64_jpeg(frame_bgr) -> str:
    ok, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise RuntimeError("JPEG 인코딩 실패")
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def vllm_describe(frames) -> str:
    model = resolve_model()
    if not model:
        raise RuntimeError(f"vLLM 모델을 찾을 수 없음 ({VLLM_URL})")
    content = [{"type": "image_url", "image_url": {"url": b64_jpeg(f)}} for f in frames]
    content.append({"type": "text", "text": INSTRUCTION})
    body = {"model": model, "max_tokens": MAX_TOKENS, "temperature": 0,
            "messages": [{"role": "user", "content": content}]}
    r = requests.post(f"{VLLM_URL}/v1/chat/completions", json=body, timeout=VLLM_TIMEOUT)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def parse_log(txt: str):
    """모델 출력 원문에서 JSON 블록을 추출해 dict 로 반환한다. 필수 키가 없거나 파싱에 실패하면 None."""
    try:
        m = re.search(r"\{.*\}", txt, re.S)
        d = json.loads(m.group(0))
        if "is_anomaly" not in d or "anomaly_type" not in d:
            return None
        # 열거형 필드를 허용 값으로 정규화
        d["is_anomaly"] = "이상" if str(d["is_anomaly"]).strip() == "이상" else "정상"
        if d["anomaly_type"] not in ANOMALY_TYPES:
            d["anomaly_type"] = "None"
        if d["is_anomaly"] == "정상":
            d["anomaly_type"] = "None"
        if not isinstance(d.get("objects"), list):
            d["objects"] = []
        for k in ("scene", "action", "summary"):
            d[k] = str(d.get(k, "") or "")
        return d
    except Exception:
        return None


# ───────────────────────── 프레임 추출 ─────────────────────────
def pick_change_frames(frames, scores):
    """프레임 열을 N_FRAMES 개 구간으로 등분하고 각 구간에서 차분 점수가 최대인 프레임을 고른다.
    프레임 수가 N_FRAMES 미만이면 같은 프레임을 반복해 채운다."""
    n = len(frames)
    if n == 0:
        return []
    if n < N_FRAMES:
        idxs = [min(i * n // N_FRAMES, n - 1) for i in range(N_FRAMES)]
    else:
        sc = np.asarray(scores)
        idxs = [int(b[np.argmax(sc[b])]) for b in np.array_split(np.arange(n), N_FRAMES)]
    return [frames[i] for i in idxs]


def extract_windows(video_path: str, window_sec: float = None):
    """
    영상을 순차 디코드하며 window_sec 단위의 창으로 나눈다.
    반환: ([(start_sec, end_sec, frames)], duration_sec, fps). frames 는 창마다 N_FRAMES 장.
    차분 점수는 160x120 그레이스케일 프레임 간 절대차의 평균이며 창마다 새로 계산한다.
    """
    window_sec = window_sec or WINDOW_SEC
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError("영상을 열 수 없음")
    fps = cap.get(cv2.CAP_PROP_FPS) or 4.0
    if fps <= 0 or fps > 240:
        fps = 4.0

    windows = []   # [(start, end, frames, scores)]
    cur_frames, cur_scores, prev = [], [], None
    cur_start = 0.0
    idx = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        t = idx / fps
        if t - cur_start >= window_sec and cur_frames:
            windows.append((cur_start, t, cur_frames, cur_scores))
            cur_frames, cur_scores, prev = [], [], None
            cur_start = t
        g = cv2.cvtColor(cv2.resize(fr, (160, 120)), cv2.COLOR_BGR2GRAY)
        cur_scores.append(0.0 if prev is None else float(np.mean(cv2.absdiff(g, prev))))
        prev = g
        cur_frames.append(fr)
        idx += 1
    cap.release()
    duration = idx / fps
    if cur_frames:
        windows.append((cur_start, duration, cur_frames, cur_scores))
    if not windows:
        raise RuntimeError("디코드된 프레임이 없음")

    # MIN_TAIL_SEC 보다 짧은 마지막 창은 앞 창에 합친다
    if len(windows) >= 2 and (windows[-1][1] - windows[-1][0]) < MIN_TAIL_SEC:
        s0, _, f0, sc0 = windows[-2]
        _, e1, f1, sc1 = windows[-1]
        windows[-2:] = [(s0, e1, f0 + f1, sc0 + sc1)]

    out = [(s, e, pick_change_frames(f, sc)) for s, e, f, sc in windows]
    return out, duration, fps


# ───────────────────────── 임베딩 (bge-m3) ─────────────────────────
# transformers AutoModel 로 로드한다. dense 임베딩 = CLS 토큰 은닉 상태를 L2 정규화한 벡터.
_embed_lock = threading.Lock()
_tok = _emb = None


def load_embedder():
    global _tok, _emb
    if EMBED_DISABLE:
        print("[EMBED] EMBED_DISABLE=1 — 임베딩 모델을 올리지 않음")
        return
    from transformers import AutoModel, AutoTokenizer
    t0 = time.time()
    _tok = AutoTokenizer.from_pretrained(EMBED_MODEL)
    dtype = torch.float16 if EMBED_DEVICE.startswith("cuda") else torch.float32
    _emb = AutoModel.from_pretrained(EMBED_MODEL, dtype=dtype).to(EMBED_DEVICE).eval()
    print(f"[EMBED] {EMBED_MODEL} 로딩 완료 ({EMBED_DEVICE}, {time.time() - t0:.1f}s)")


@torch.inference_mode()
def embed_texts(texts: list[str]) -> list[list[float]]:
    if _emb is None:
        raise RuntimeError("임베딩 모델이 로드되지 않음")
    with _embed_lock:
        enc = _tok(texts, padding=True, truncation=True, max_length=512, return_tensors="pt").to(EMBED_DEVICE)
        out = _emb(**enc).last_hidden_state[:, 0]
        out = torch.nn.functional.normalize(out.float(), dim=-1)
        return out.cpu().tolist()


# ───────────────────────── FastAPI ─────────────────────────
app = FastAPI(title="CCTV VLM Adapter", version="2.0.0")


@app.on_event("startup")
def _startup():
    m = resolve_model()
    print(f"[VLLM] {VLLM_URL} 모델: {m or '(응답 없음 — 요청 시 재시도)'}")
    load_embedder()


class EmbedReq(BaseModel):
    text: str


@app.get("/health")
def health():
    vllm_ok, model = False, VLLM_MODEL
    with contextlib.suppress(Exception):
        ids = vllm_models()
        vllm_ok = bool(ids)
        model = model or (ids[0] if ids else "")
    return {
        "status": "ok" if vllm_ok else "degraded",
        "vllm": vllm_ok, "vllm_url": VLLM_URL, "model": model,
        "embed_model": None if EMBED_DISABLE else EMBED_MODEL, "embed_ready": _emb is not None,
        "window_sec": WINDOW_SEC,
    }


@app.post("/embed")
def embed(req: EmbedReq):
    if _emb is None:
        raise HTTPException(status_code=503, detail="임베딩 모델 비활성")
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text가 비어 있음")
    return {"embedding": embed_texts([text])[0]}


@app.post("/describe")
def describe(file: UploadFile = File(...), question: str | None = Form(None),
             window_sec: float | None = Form(None)):
    if window_sec is not None and not (3 <= window_sec <= 120):
        raise HTTPException(status_code=400, detail="window_sec는 3~120 사이")
    t0 = time.perf_counter()
    suffix = os.path.splitext(file.filename or "")[1] or ".mp4"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file.file.read())
        tmp_path = tmp.name
    try:
        try:
            windows, duration, fps = extract_windows(tmp_path, window_sec)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"영상 처리 실패: {e}")

        logs = []
        for ws, we, frames in windows:
            entry = {"window_start": round(ws, 2), "window_end": round(we, 2), "log": None, "raw": "", "embedding": None}
            try:
                raw = vllm_describe(frames)
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"vLLM 호출 실패: {e}")
            entry["raw"] = raw
            entry["log"] = parse_log(raw)
            logs.append(entry)

        if _emb is not None:
            texts = [f"{e['log']['summary']} {e['log']['action']}".strip() for e in logs if e["log"]]
            if texts:
                vecs = embed_texts(texts)
                it = iter(vecs)
                for e in logs:
                    if e["log"]:
                        e["embedding"] = next(it)

        first = next((e["log"] for e in logs if e["log"]), None)
        description = (first or {}).get("summary", "") if first else ""
        elapsed = time.perf_counter() - t0
        n_anom = sum(1 for e in logs if e["log"] and e["log"]["is_anomaly"] == "이상")
        print(f"[VLM] /describe {file.filename} {duration:.1f}s/{fps:.0f}fps → 창 {len(logs)}개, 이상 {n_anom}개, "
              f"'{description}' ({elapsed:.2f}s)")
        return {"description": description, "logs": logs,
                "duration_sec": round(duration, 2), "n_windows": len(logs),
                "window_sec": window_sec or WINDOW_SEC, "elapsed_sec": round(elapsed, 3)}
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp_path)
