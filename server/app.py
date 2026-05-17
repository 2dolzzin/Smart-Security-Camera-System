"""
server/app.py
AWS GPU 인스턴스(예: g5.xlarge / A10G)에서 실행하는 Qwen2.5-VL 추론 API 서버.

이 파일은 클라이언트 백엔드(cctv-final/client/backend)가 아니라 **VLM 서버 쪽**에서 돌린다.
서버에 이미 있는 추론 스크립트(qwen2.5-vl + process_vision_info)를 HTTP API 로 감싼 것.

────────────────────────────────────────────────────────
배포 (Ubuntu, NVIDIA 드라이버 설치된 상태에서)
────────────────────────────────────────────────────────
  # 0) 드라이버 확인 — 표가 떠야 함
  nvidia-smi

  # 1) ~/qwen 에 이 파일과 requirements.txt 를 둔다
  cd ~/qwen
  pip install -r requirements.txt        # fastapi/uvicorn/python-multipart 등

  # 2) 실행 (외부에서 접속 가능하도록 0.0.0.0)
  uvicorn app:app --host 0.0.0.0 --port 8001

  # 3) AWS 보안그룹(Security Group) 인바운드에 TCP 8001 열기
  #    가능하면 우리 클라이언트 백엔드가 도는 머신 IP 만 허용 (전체 공개 비권장)

────────────────────────────────────────────────────────
엔드포인트
────────────────────────────────────────────────────────
  GET  /health
       → {"status":"ok","model":"Qwen/Qwen2.5-VL-3B-Instruct","device":"cuda"}

  POST /describe   (multipart/form-data)
       file      : 영상 파일 (필수)  — 클라이언트가 전처리한 가벼운 mp4
       question  : 질문 텍스트 (선택) — 없으면 CCTV 기본 프롬프트 사용
       → {"description": "강아지가 지나감", "elapsed_sec": 1.42}

환경변수(선택):
  VLM_MODEL           기본 "Qwen/Qwen2.5-VL-3B-Instruct"
  VLM_QUESTION        기본 CCTV 설명 프롬프트
  VLM_MAX_NEW_TOKENS  기본 64
"""

import contextlib
import os
import tempfile
import threading
import time

import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration
from qwen_vl_utils import process_vision_info

MODEL_NAME = os.getenv("VLM_MODEL", "Qwen/Qwen2.5-VL-3B-Instruct")
DEFAULT_QUESTION = os.getenv(
    "VLM_QUESTION",
    "이 CCTV 영상에서 무슨 일이 일어나고 있는지 한국어로 15자 이내의 아주 짧은 한 문장으로만 "
    "설명해줘. 예: '강아지가 지나감', '낯선 사람이 접근함', '택배 기사가 방문함', '차량이 통과함'. "
    "부연 설명 없이 결과 문장만 출력해.",
)
MAX_NEW_TOKENS = int(os.getenv("VLM_MAX_NEW_TOKENS", "64"))

device = "cuda" if torch.cuda.is_available() else "cpu"
dtype = torch.bfloat16 if device == "cuda" else torch.float32

print(f"[VLM] 모델 로딩 시작: {MODEL_NAME}  (device={device}, dtype={dtype})")
model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
    MODEL_NAME,
    torch_dtype=dtype,
    device_map="auto",
)
processor = AutoProcessor.from_pretrained(MODEL_NAME)
print("[VLM] 모델 로딩 완료")

# GPU 는 한 개 — 동시 요청이 와도 추론은 한 번에 하나씩만
_infer_lock = threading.Lock()

app = FastAPI(title="Qwen2.5-VL CCTV Describe API", version="1.0.0")


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME, "device": device}


def _run_inference(video_path: str, question: str) -> tuple[str, float]:
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "video", "video": video_path},
                {"type": "text", "text": question},
            ],
        }
    ]

    text = processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    image_inputs, video_inputs = process_vision_info(messages)
    inputs = processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    ).to(model.device)

    if torch.cuda.is_available():
        torch.cuda.synchronize()
    start = time.perf_counter()

    with torch.inference_mode():
        generated_ids = model.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=False,
        )

    if torch.cuda.is_available():
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - start

    # 입력 프롬프트 토큰을 잘라내고 새로 생성된 부분만 디코드
    trimmed = [
        out_ids[len(in_ids):]
        for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
    ]
    output_text = processor.batch_decode(
        trimmed,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=True,
    )[0]
    return output_text.strip(), elapsed


@app.post("/describe")
async def describe(
    file: UploadFile = File(...),
    question: str | None = Form(None),
):
    q = (question or DEFAULT_QUESTION).strip()

    suffix = os.path.splitext(file.filename or "")[1] or ".mp4"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        with _infer_lock:
            description, elapsed = _run_inference(tmp_path, q)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"추론 실패: {e}")
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp_path)

    print(f"[VLM] /describe → '{description}'  ({elapsed:.2f}s)")
    return {"description": description, "elapsed_sec": round(elapsed, 3)}
