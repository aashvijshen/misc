#!/usr/bin/env python3
"""Local HTTP Web Server for Maker Deck & Pricing Studio.

Usage:
    python3 tools/showcase/server.py [port]
Default port: 8090 (http://localhost:8090)
"""

import json
import mimetypes
import os
import re
import shutil
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, unquote, urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from stl_scanner import (
    CATALOG_PATH,
    PROJECTS_DIR,
    classify_media_kind,
    sync_catalog_with_disk,
)

STATIC_DIR = os.path.join(BASE_DIR, "static")

mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("video/webm", ".webm")
mimetypes.add_type("video/quicktime", ".mov")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/gif", ".gif")


def load_catalog() -> dict:
    if not os.path.isfile(CATALOG_PATH):
        return {"settings": {}, "spools": [], "items": [], "orders": []}
    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_catalog(data: dict) -> None:
    tmp_path = CATALOG_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, CATALOG_PATH)


def sanitize_filename(name: str) -> str:
    base = os.path.basename(name)
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", base).strip("_")
    return cleaned or "media.jpg"


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class ShowcaseHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("[showcase] %s\n" % (fmt % args))

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Range")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def send_json(self, payload: dict, status: int = 200):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def serve_file(self, full_path: str, content_type: str = None):
        if not os.path.isfile(full_path):
            self.send_error(404, "File not found")
            return
        if not content_type:
            content_type, _ = mimetypes.guess_type(full_path)
            content_type = content_type or "application/octet-stream"

        total_size = os.path.getsize(full_path)
        range_header = self.headers.get("Range")

        # HTTP 206 Range support so .mp4/.mov/.webm videos loop smoothly on mobile browsers
        if range_header and range_header.startswith("bytes="):
            m = re.match(r"bytes=(\d*)-(\d*)", range_header)
            if m:
                start_s, end_s = m.groups()
                start = int(start_s) if start_s else 0
                end = int(end_s) if end_s else total_size - 1
                end = min(end, total_size - 1)
                if start <= end and start < total_size:
                    chunk_len = end - start + 1
                    self.send_response(206)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Range", f"bytes {start}-{end}/{total_size}")
                    self.send_header("Content-Length", str(chunk_len))
                    self.end_headers()
                    with open(full_path, "rb") as f:
                        f.seek(start)
                        remaining = chunk_len
                        while remaining > 0:
                            buf = f.read(min(65536, remaining))
                            if not buf:
                                break
                            self.wfile.write(buf)
                            remaining -= len(buf)
                    return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(total_size))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        with open(full_path, "rb") as f:
            shutil.copyfileobj(f, self.wfile)

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path in ("/", "/index.html"):
            self.serve_file(os.path.join(STATIC_DIR, "index.html"), "text/html; charset=utf-8")
        elif path in ("/manifest.json", "/sw.js"):
            ctype = (
                "application/manifest+json"
                if path.endswith(".json")
                else "application/javascript"
            )
            self.serve_file(os.path.join(STATIC_DIR, path.lstrip("/")), ctype)
        elif path.startswith("/static/"):
            rel = os.path.normpath(path[len("/static/") :])
            if rel.startswith(".."):
                self.send_error(403, "Forbidden")
                return
            self.serve_file(os.path.join(STATIC_DIR, rel))
        elif path.startswith("/media/"):
            parts = [p for p in path.split("/") if p]
            if len(parts) < 4 or parts[2] not in ("photos", "previews"):
                self.send_error(400, "Invalid media path")
                return
            slug = sanitize_filename(parts[1])
            folder = parts[2]
            rel_file = os.path.normpath("/".join(parts[3:]))
            if rel_file.startswith(".."):
                self.send_error(403, "Forbidden")
                return
            target = os.path.join(PROJECTS_DIR, slug, folder, rel_file)
            self.serve_file(target)
        elif path == "/api/catalog":
            self.send_json(load_catalog())
        else:
            self.send_error(404, "Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        qs = parse_qs(parsed.query)

        try:
            if path == "/api/catalog":
                body = self.read_json_body()
                if not isinstance(body, dict) or "items" not in body:
                    self.send_json({"error": "Invalid catalog payload"}, 400)
                    return
                save_catalog(body)
                self.send_json({"ok": True, "catalog": body})

            elif path == "/api/rescan":
                catalog = load_catalog()
                updated = sync_catalog_with_disk(catalog)
                save_catalog(updated)
                self.send_json({"ok": True, "catalog": updated})

            elif path == "/api/upload_media":
                slug = sanitize_filename((qs.get("slug") or [""])[0])
                raw_name = (qs.get("filename") or ["photo.jpg"])[0]
                filename = sanitize_filename(raw_name)
                length = int(self.headers.get("Content-Length", "0"))
                if not slug or length <= 0:
                    self.send_json({"error": "Missing slug or empty file"}, 400)
                    return

                proj_dir = os.path.join(PROJECTS_DIR, slug)
                if not os.path.isdir(proj_dir):
                    self.send_json({"error": f"Project {slug} not found"}, 404)
                    return

                photos_dir = os.path.join(proj_dir, "photos")
                os.makedirs(photos_dir, exist_ok=True)

                dest_path = os.path.join(photos_dir, filename)
                stem, ext = os.path.splitext(filename)
                idx = 2
                while os.path.exists(dest_path):
                    filename = f"{stem}_{idx}{ext}"
                    dest_path = os.path.join(photos_dir, filename)
                    idx += 1

                remaining = length
                with open(dest_path, "wb") as out_f:
                    while remaining > 0:
                        chunk = self.rfile.read(min(65536, remaining))
                        if not chunk:
                            break
                        out_f.write(chunk)
                        remaining -= len(chunk)

                media_url = f"/media/{slug}/photos/{filename}"
                media_entry = {
                    "url": media_url,
                    "label": stem.replace("_", " ").title(),
                    "kind": classify_media_kind(ext.lower(), "photos"),
                    "isDiagnostic": False,
                }
                catalog = load_catalog()
                for item in catalog.get("items", []):
                    if item.get("slug") == slug:
                        excluded = item.setdefault("excludedMedia", [])
                        if media_url in excluded:
                            excluded.remove(media_url)
                        item.setdefault("media", []).insert(0, media_entry)
                        break
                save_catalog(catalog)
                self.send_json({"ok": True, "media": media_entry, "catalog": catalog})

            elif path == "/api/delete_media":
                body = self.read_json_body()
                slug = sanitize_filename(body.get("slug", ""))
                url = body.get("url", "")
                if not slug or not url:
                    self.send_json({"error": "Missing slug or url"}, 400)
                    return

                catalog = load_catalog()
                for item in catalog.get("items", []):
                    if item.get("slug") == slug:
                        item["media"] = [
                            m for m in item.get("media", []) if m.get("url") != url
                        ]
                        # If deleting a CAD render in previews/, permanently exclude it from rescan
                        if f"/media/{slug}/previews/" in url:
                            excl = item.setdefault("excludedMedia", [])
                            if url not in excl:
                                excl.append(url)
                        elif f"/media/{slug}/photos/" in url:
                            parts = [p for p in url.split("/") if p]
                            if len(parts) >= 4:
                                rel_fn = os.path.normpath("/".join(parts[3:]))
                                if not rel_fn.startswith(".."):
                                    disk_file = os.path.join(
                                        PROJECTS_DIR, slug, "photos", rel_fn
                                    )
                                    if os.path.isfile(disk_file):
                                        os.remove(disk_file)
                        break

                save_catalog(catalog)
                self.send_json({"ok": True, "catalog": catalog})

            elif path == "/api/set_cover":
                body = self.read_json_body()
                slug = sanitize_filename(body.get("slug", ""))
                url = body.get("url", "")
                catalog = load_catalog()
                for item in catalog.get("items", []):
                    if item.get("slug") == slug:
                        media = item.get("media", [])
                        chosen = [m for m in media if m.get("url") == url]
                        others = [m for m in media if m.get("url") != url]
                        if chosen:
                            item["media"] = chosen + others
                        break
                save_catalog(catalog)
                self.send_json({"ok": True, "catalog": catalog})

            else:
                self.send_json({"error": "Unknown endpoint"}, 404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    catalog = load_catalog()
    updated = sync_catalog_with_disk(catalog)
    save_catalog(updated)

    server = ThreadedHTTPServer(("0.0.0.0", port), ShowcaseHandler)
    print(f"Maker Deck & Pricing Studio running at http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.server_close()


if __name__ == "__main__":
    main()
