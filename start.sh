#!/usr/bin/env bash
# Linux / macOS launcher
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
if [ ! -f .venv/.installed ]; then .venv/bin/pip install -q -r requirements.txt && touch .venv/.installed; fi
PORT="${PORT:-8000}"
echo "http://127.0.0.1:$PORT"
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
