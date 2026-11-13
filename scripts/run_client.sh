#!/usr/bin/env bash
# 클라이언트 측(백엔드 + 프론트엔드)을 한 번에 실행한다.
# Ctrl+C 를 누르면 두 프로세스를 함께 종료한다.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$DIR/run_backend.sh" &
BACK_PID=$!
"$DIR/run_frontend.sh" &
FRONT_PID=$!

cleanup() {
  kill "$BACK_PID" "$FRONT_PID" 2>/dev/null || true
  wait "$BACK_PID" "$FRONT_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "백엔드   http://localhost:${BACKEND_PORT:-8800}"
echo "프론트   http://localhost:5173"
wait
