#!/usr/bin/env bash
# GPU 서버에서 VLM 어댑터(server/app.py, :8010)를 실행한다.
# vLLM 모델 서버가 VLLM_URL(기본 http://localhost:8002)에 먼저 떠 있어야 한다.
#
# 사용 예:
#   GPU=1 ./scripts/run_server.sh              # 어댑터만 실행
#   GPU=1 MODEL_DIR=/path/to/merged-model ./scripts/run_server.sh vllm   # vLLM 모델 서버 실행
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GPU="${GPU:-0}"

if [ "${1:-adapter}" = "vllm" ]; then
  : "${MODEL_DIR:?MODEL_DIR 에 병합된 모델 경로를 지정하세요}"
  CUDA_VISIBLE_DEVICES="$GPU" exec vllm serve "$MODEL_DIR" \
    --port "${VLLM_PORT:-8002}" \
    --max-model-len 8192 \
    --limit-mm-per-prompt '{"image":8}' \
    --gpu-memory-utilization "${GPU_MEM_UTIL:-0.8}"
fi

cd "$ROOT/server"
CUDA_VISIBLE_DEVICES="$GPU" exec uvicorn app:app \
  --host "${ADAPTER_HOST:-0.0.0.0}" --port "${ADAPTER_PORT:-8010}"
