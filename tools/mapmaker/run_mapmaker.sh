#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if ! python3 -c "import numpy, scipy, shapely, PIL" >/dev/null 2>&1; then
    echo "[*] Installing required Python dependencies..."
    python3 -m pip install -r requirements.txt
fi

exec python3 app.py "$@"
