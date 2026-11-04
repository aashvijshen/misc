#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ ! -x "$DIR/.venv/bin/python" ]; then
  echo "[Setup] Creating local virtual environment in .venv ..."
  python3 -m venv "$DIR/.venv"
fi

REQ_HASH="$(python3 -c 'import hashlib, pathlib; print(hashlib.sha256(pathlib.Path("requirements.txt").read_bytes()).hexdigest())')"
STAMP_FILE="$DIR/.venv/.deps_stamp"
OLD_HASH="$(cat "$STAMP_FILE" 2>/dev/null || true)"

if [ "$REQ_HASH" != "$OLD_HASH" ] || ! "$DIR/.venv/bin/python" -c "import fastapi, uvicorn, mido, reportlab" >/dev/null 2>&1; then
  echo "[Setup] Installing Python dependencies ..."
  "$DIR/.venv/bin/pip" install -r "$DIR/requirements.txt"
  printf '%s' "$REQ_HASH" > "$STAMP_FILE"
fi

exec "$DIR/.venv/bin/python" "$DIR/launch.py" "$@"
