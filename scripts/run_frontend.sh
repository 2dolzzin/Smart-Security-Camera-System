#!/usr/bin/env bash
# 프론트엔드(Vite 개발 서버, :5173) 실행.
# 최초 실행 시 node_modules 를 설치한다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/client/frontend"

if [ ! -d node_modules ]; then
  npm install
fi

exec npm run dev
