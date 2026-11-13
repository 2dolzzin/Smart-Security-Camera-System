#!/usr/bin/env bash
# 클라이언트 백엔드(FastAPI) 실행.
# 최초 실행 시 client/backend/venv 를 만들고 의존성을 설치한다.
# 리포 루트의 .env 가 있으면 환경변수로 읽어 들인다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/client/backend"

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

if [ ! -d venv ]; then
  python3 -m venv venv
  ./venv/bin/pip install --upgrade pip
  ./venv/bin/pip install -r requirements.txt
fi

exec ./venv/bin/uvicorn main:app --host 127.0.0.1 --port "${BACKEND_PORT:-8800}"
