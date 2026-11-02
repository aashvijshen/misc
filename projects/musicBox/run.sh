#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

PORT="${PORT:-8000}"
echo "Starting Kikkerland 15-Note Music Box Studio at http://127.0.0.1:${PORT}"
exec "$DIR/.venv/bin/uvicorn" backend.app:app --host 127.0.0.1 --port "$PORT"
