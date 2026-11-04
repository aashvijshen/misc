#!/usr/bin/env python3
"""Cross-platform launcher for KIKKER-15 Music Box Studio (Windows, macOS, Linux).

Features:
  - Automatically sets working directory & UTF-8 console encoding on Windows.
  - Picks PORT (default 8000) and automatically falls back to the next free port (8001..8024)
    if port 8000 is already in use on the machine.
  - Automatically opens the studio in the default web browser once ready (pass --no-browser to skip).
"""

import argparse
import os
from pathlib import Path
import socket
import sys
import threading
import time
import webbrowser

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def configure_utf8_console() -> None:
    """Prevent cp1252 UnicodeEncodeError on Windows terminals."""
    os.environ.setdefault("PYTHONUTF8", "1")
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def is_port_free(host: str, port: int) -> bool:
    """Return True if (host, port) is available to bind on this OS."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if os.name != "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def find_available_port(preferred_port: int = 8000, host: str = "127.0.0.1", max_tries: int = 25) -> int:
    """Return `preferred_port` if free, otherwise scan upward for the next free port."""
    for offset in range(max(1, max_tries)):
        candidate = preferred_port + offset
        if is_port_free(host, candidate):
            return candidate
    raise RuntimeError(
        f"No available TCP port found between {preferred_port} and {preferred_port + max_tries - 1} on {host}."
    )


def _open_browser_when_ready(host: str, port: int, url: str) -> None:
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.25):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(0.15)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch KIKKER-15 Music Box Studio local server.")
    parser.add_argument(
        "--host",
        default=os.environ.get("HOST", "127.0.0.1"),
        help="Bind host address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "8000")),
        help="Preferred TCP port (default: 8000; auto-increments if busy)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        default=os.environ.get("NO_BROWSER", "").strip().lower() in ("1", "true", "yes"),
        help="Do not automatically open the web browser on startup",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    configure_utf8_console()
    os.chdir(ROOT_DIR)
    args = parse_args(argv)

    port = find_available_port(preferred_port=args.port, host=args.host)
    url = f"http://{args.host}:{port}"

    print("=" * 68)
    print("  KIKKER-15 // Kikkerland 15-Note Music Box Studio")
    if port != args.port:
        print(f"  Note: Port {args.port} was busy -> switched automatically to {port}")
    print(f"  Studio URL : {url}")
    print("  Stop Server: Press Ctrl+C in this window")
    print("=" * 68, flush=True)

    if not args.no_browser:
        threading.Thread(
            target=_open_browser_when_ready,
            args=(args.host, port, url),
            daemon=True,
        ).start()

    import uvicorn
    from backend.app import app

    uvicorn.run(app, host=args.host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
