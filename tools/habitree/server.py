#!/usr/bin/env python3
"""Local HTTP Web Server for HabiTree 3D Generator Tool.

Usage:
    python3 server.py [port]
Default port: 8080 (http://localhost:8080)
"""

import sys
import os
import json
import mimetypes
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

# Add current directory to path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from generator import generate_habit_tree

OUTPUT_DIR = os.path.join(BASE_DIR, "output")
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class HabiTreeHandler(BaseHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        path = self.path.split('?')[0]
        
        if path == '/' or path == '/index.html':
            self.serve_file(os.path.join(STATIC_DIR, "index.html"), "text/html")
        elif path.startswith('/static/'):
            rel_path = path[8:]
            self.serve_file(os.path.join(STATIC_DIR, rel_path))
        elif path == '/api/manifest':
            manifest_path = os.path.join(OUTPUT_DIR, "manifest.json")
            if os.path.exists(manifest_path):
                self.serve_file(manifest_path, "application/json")
            else:
                self.send_error(404, "Manifest not found. Generate a tree first.")
        elif path == '/api/model/master.stl':
            stl_path = os.path.join(OUTPUT_DIR, "habit_tree_master.stl")
            self.serve_file(stl_path, "model/stl")
        elif path == '/api/model/scene_bundle':
            manifest_path = os.path.join(OUTPUT_DIR, "manifest.json")
            if not os.path.exists(manifest_path):
                self.send_error(404, "Manifest not found. Generate a tree first.")
                return
            try:
                import base64
                with open(manifest_path, 'r') as f:
                    manifest = json.load(f)
                
                base_stl_path = os.path.join(OUTPUT_DIR, "base_planter.stl")
                base_b64 = ""
                if os.path.exists(base_stl_path):
                    with open(base_stl_path, "rb") as bf:
                        base_b64 = base64.b64encode(bf.read()).decode("ascii")
                        
                bundle_parts = []
                for p in manifest.get("parts", []):
                    p_file = os.path.join(OUTPUT_DIR, p["filename"])
                    if os.path.exists(p_file):
                        with open(p_file, "rb") as pf:
                            p_data = base64.b64encode(pf.read()).decode("ascii")
                            bundle_parts.append({
                                "day": p["day"],
                                "zone": p["zone"],
                                "name": p["name"],
                                "color": p["color"],
                                "dimensions": p.get("dimensions", {}),
                                "data": p_data
                            })
                            
                payload = json.dumps({
                    "status": "success",
                    "palette": manifest.get("palette", {}),
                    "piece_count": manifest.get("piece_count", len(bundle_parts)),
                    "total_volume_cm3": manifest.get("total_volume_cm3", 0),
                    "estimated_mass_grams": manifest.get("estimated_mass_grams", 0),
                    "base": {
                        "color": manifest.get("palette", {}).get("base", "#2A2E33"),
                        "data": base_b64
                    },
                    "parts": bundle_parts
                })
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(payload.encode('utf-8'))))
                self.end_headers()
                self.wfile.write(payload.encode('utf-8'))
            except Exception as e:
                self.send_error(500, f"Error creating scene bundle: {e}")
        elif path == '/api/download/zip':
            zip_path = os.path.join(OUTPUT_DIR, "habit_tree_pieces.zip")
            self.serve_file(zip_path, "application/zip", as_attachment=True, download_name="habit_tree_pieces.zip")
        elif path == '/api/download/step':
            step_path = os.path.join(OUTPUT_DIR, "habit_tree_master.step")
            self.serve_file(step_path, "application/step", as_attachment=True, download_name="habit_tree_master.step")
        elif path.startswith('/api/model/part/'):
            part_name = path[16:]
            part_path = os.path.join(OUTPUT_DIR, "parts", part_name)
            self.serve_file(part_path, "model/stl")
        elif path.startswith('/api/model/plate/'):
            plate_name = path[17:]
            plate_path = os.path.join(OUTPUT_DIR, "plates", plate_name)
            self.serve_file(plate_path, "model/stl", as_attachment=True, download_name=plate_name)
        else:
            self.send_error(404, "Endpoint not found")

    def do_POST(self):
        if self.path == '/api/generate':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                params = json.loads(post_data) if post_data else {}
                style = params.get("style", "zen_bonsai")
                pieces = int(params.get("pieces", 30))
                seed = int(params.get("seed", 42))
                
                print(f"[Server] Triggering generation: style={style}, pieces={pieces}, seed={seed}")
                import importlib
                import generator
                importlib.reload(generator)
                manifest = generator.generate_habit_tree(style=style, piece_count=pieces, seed=seed, output_dir=OUTPUT_DIR)
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success", "manifest": manifest}).encode('utf-8'))
            except Exception as e:
                print(f"[Server ERROR] {e}")
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        else:
            self.send_error(404, "Endpoint not found")

    def serve_file(self, filepath, content_type=None, as_attachment=False, download_name=None):
        if not os.path.exists(filepath):
            self.send_error(404, f"File {os.path.basename(filepath)} not found")
            return
            
        if content_type is None:
            content_type, _ = mimetypes.guess_type(filepath)
            content_type = content_type or "application/octet-stream"
            
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(os.path.getsize(filepath)))
        if as_attachment:
            fname = download_name or os.path.basename(filepath)
            self.send_header('Content-Disposition', f'attachment; filename="{fname}"')
        self.end_headers()
        
        with open(filepath, 'rb') as f:
            while chunk := f.read(65536):
                self.wfile.write(chunk)

def run(port=8080):
    server_address = ('', port)
    httpd = ThreadedHTTPServer(server_address, HabiTreeHandler)
    print(f"============================================================")
    print(f"  🌳 HabiTree 3D Generator Server Running!")
    print(f"  👉 Open your browser at: http://localhost:{port}")
    print(f"============================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.server_close()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run(port)
