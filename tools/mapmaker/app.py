#!/usr/bin/env python3
"""MapMaker 3D: Standalone Desktop Application & Local Service.

Automatically detects Chrome Remote Desktop display variables (Wayland/X11)
and launches the interactive 2D/3D map fabrication interface in a native desktop window.
"""

import os
import sys
import json
import urllib.parse
import subprocess
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
import numpy as np

# Ensure UTF-8 console output on Windows (prevents cp1252 UnicodeEncodeError)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from engine.config import MapMakerConfig, CanvasConfig, BoundingBox
from engine.geo import geocode_location, fetch_elevation_grid, calculate_route, fetch_osm_buildings, fetch_map_texture
from engine.blocks import fetch_urban_blocks
from engine.mesh import generate_boundary_preview_mesh
from engine.tiling import TilingEngine

PORT = 8765
GUI_DIR = os.path.join(os.path.dirname(__file__), "gui")
LATEST_GUIDE_PATH = None


def setup_display_env():
    """Detects and exports the active Chrome Remote Desktop / Wayland / X11 environment on Linux.
    No-op on Windows and macOS where the native desktop window manager handles display routing.
    """
    if not sys.platform.startswith("linux") or not hasattr(os, "getuid"):
        return

    uid = os.getuid()
    runtime_dir = f"/run/user/{uid}"
    os.environ["XDG_RUNTIME_DIR"] = runtime_dir
    
    if "WAYLAND_DISPLAY" not in os.environ:
        os.environ["WAYLAND_DISPLAY"] = "wayland-0"
    if "DISPLAY" not in os.environ:
        os.environ["DISPLAY"] = ":0"
        
    if "XAUTHORITY" not in os.environ and os.path.exists(runtime_dir):
        for fname in os.listdir(runtime_dir):
            if fname.startswith(".mutter-Xwaylandauth"):
                os.environ["XAUTHORITY"] = os.path.join(runtime_dir, fname)
                break


class MapMakerHTTPHandler(BaseHTTPRequestHandler):
    """Handles REST API and static GUI requests with full CORS support."""

    def log_message(self, format, *args):
        sys.stderr.write(f"[HTTP] {self.command} {self.path} - {args[1]}\n")

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _send_bytes(self, status_code: int, content_type: str, data: bytes):
        """Sends an HTTP response with explicit Content-Length to prevent socket stalling."""
        self.send_response(status_code)
        self._send_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, status_code: int, obj: dict):
        """Encodes and sends a JSON response with Content-Length."""
        payload = json.dumps(obj).encode("utf-8")
        self._send_bytes(status_code, "application/json", payload)

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        force_refresh = query.get("force_refresh", ["false"])[0].lower() in ("true", "1", "yes")

        if path == "/" or path == "/index.html":
            html_path = os.path.join(GUI_DIR, "index.html")
            if os.path.exists(html_path):
                with open(html_path, "rb") as f:
                    content = f.read()
                self._send_bytes(200, "text/html; charset=utf-8", content)
            else:
                self.send_error(404, "index.html not found")
            return

        elif path == "/api/geocode":
            q = query.get("q", [""])[0]
            if not q:
                self._send_json(400, {"error": "Missing search query 'q'"})
                return
            try:
                res = geocode_location(q, force_refresh=force_refresh)
                data = {
                    "display_name": res["display_name"],
                    "lat": res["lat"],
                    "lon": res["lon"],
                    "bbox": {
                        "south": res["bbox"].south,
                        "west": res["bbox"].west,
                        "north": res["bbox"].north,
                        "east": res["bbox"].east
                    },
                    "geojson": res.get("geojson")
                }
                self._send_json(200, data)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        elif path == "/api/boundary":
            q = query.get("q", [""])[0]
            if not q:
                self._send_json(400, {"error": "Missing query parameter 'q'"})
                return
            try:
                res = geocode_location(q, fetch_polygon=True, force_refresh=force_refresh)
                self._send_json(200, {
                    "status": "ok",
                    "display_name": res["display_name"],
                    "geojson": res.get("geojson"),
                    "bbox": {
                        "south": res["bbox"].south,
                        "west": res["bbox"].west,
                        "north": res["bbox"].north,
                        "east": res["bbox"].east
                    }
                })
            except Exception as err:
                self._send_json(500, {"error": str(err)})
            return

        elif path == "/api/boundary_mesh":
            try:
                s = float(query["south"][0])
                w = float(query["west"][0])
                n = float(query["north"][0])
                e = float(query["east"][0])
                bbox = BoundingBox(south=s, west=w, north=n, east=e)
                width_mm = float(query.get("width_mm", [250.0])[0])
                depth_mm = float(query.get("depth_mm", [250.0])[0])
                base_h = float(query.get("base_height", [4.0])[0])
                relief_h = float(query.get("target_relief", [15.0])[0])

                q_loc = query.get("q", [""])[0]
                boundary_geojson = None
                if q_loc:
                    geo_res = geocode_location(q_loc, fetch_polygon=True, force_refresh=force_refresh)
                    boundary_geojson = geo_res.get("geojson")

                if not boundary_geojson:
                    self._send_json(400, {"error": "No boundary GeoJSON available for this location"})
                    return

                grid = fetch_elevation_grid(bbox, grid_width=40, grid_depth=40)
                mesh_data = generate_boundary_preview_mesh(
                    elev_grid=grid,
                    bbox=bbox,
                    boundary_geojson=boundary_geojson,
                    width_mm=width_mm,
                    depth_mm=depth_mm,
                    base_height_mm=base_h,
                    target_relief_mm=relief_h
                )
                self._send_json(200, mesh_data)
            except Exception as err:
                self._send_json(500, {"error": str(err)})
            return

        elif path == "/api/elevation":
            try:
                s = float(query["south"][0])
                w = float(query["west"][0])
                n = float(query["north"][0])
                e = float(query["east"][0])
                bbox = BoundingBox(south=s, west=w, north=n, east=e)
                
                # Fetch 60x60 grid for fast 3D preview
                grid = fetch_elevation_grid(bbox, grid_width=60, grid_depth=60)
                self._send_json(200, {"grid": grid.tolist()})
            except Exception as err:
                self._send_json(500, {"error": str(err)})
            return

        elif path == "/api/map_texture":
            try:
                s = float(query["south"][0])
                w = float(query["west"][0])
                n = float(query["north"][0])
                e = float(query["east"][0])
                bbox = BoundingBox(south=s, west=w, north=n, east=e)
                size = int(query.get("size", [1024])[0])
                jpeg_bytes = fetch_map_texture(bbox, target_size=size, force_refresh=force_refresh)
                self._send_bytes(200, "image/jpeg", jpeg_bytes)
            except Exception as err:
                self._send_json(500, {"error": str(err)})
            return

        elif path == "/api/route":
            pts_str = query.get("waypoints", [""])[0]
            profile = query.get("profile", ["driving"])[0]
            if not pts_str:
                self._send_json(400, {"error": "Missing waypoints query parameter"})
                return
            try:
                pts = []
                for p in pts_str.split(";"):
                    if not p.strip(): continue
                    parts = p.split(",")
                    pts.append((float(parts[0]), float(parts[1])))
                res = calculate_route(pts, profile=profile)
                self._send_json(200, res)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        elif path == "/api/blocks" or path == "/api/buildings":
            try:
                s = float(query["south"][0])
                w = float(query["west"][0])
                n = float(query["north"][0])
                e = float(query["east"][0])
                bbox = BoundingBox(south=s, west=w, north=n, east=e)

                canvas_w = float(query.get("width_mm", [250.0])[0])
                canvas_d = float(query.get("depth_mm", [250.0])[0])
                groove_w = float(query.get("groove_w", [1.2])[0])
                min_h = float(query.get("min_h", [2.0])[0])
                max_h = float(query.get("max_h", [6.0])[0])

                blocks = fetch_urban_blocks(
                    bbox=bbox,
                    canvas_w_mm=canvas_w,
                    canvas_d_mm=canvas_d,
                    groove_w_mm=groove_w,
                    min_h_mm=min_h,
                    max_h_mm=max_h,
                    force_refresh=force_refresh
                )
                blocks_data = [b.to_dict() for b in blocks]
                self._send_json(200, {
                    "status": "ok",
                    "count": len(blocks_data),
                    "blocks": blocks_data
                })
            except Exception as err:
                self._send_json(500, {"error": str(err)})
            return

        elif path == "/api/guide":
            global LATEST_GUIDE_PATH
            if LATEST_GUIDE_PATH and os.path.exists(LATEST_GUIDE_PATH):
                with open(LATEST_GUIDE_PATH, "rb") as f:
                    content = f.read()
                self._send_bytes(200, "text/markdown; charset=utf-8", content)
            else:
                self._send_json(404, {"error": "No assembly guide generated yet."})
            return

        else:
            self._send_json(404, {"error": f"Path not found: {path}"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/boundary_mesh":
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len).decode("utf-8")
            data = json.loads(body)
            try:
                b = data["bbox"]
                bbox = BoundingBox(south=float(b["south"]), west=float(b["west"]), north=float(b["north"]), east=float(b["east"]))
                width_mm = float(data.get("width_mm", 250.0))
                depth_mm = float(data.get("depth_mm", 250.0))
                base_h = float(data.get("base_height", 4.0))
                relief_h = float(data.get("target_relief", 15.0))
                boundary_geojson = data.get("boundary_geojson")

                if not boundary_geojson:
                    q_loc = data.get("location", "")
                    if q_loc:
                        geo_res = geocode_location(
                            q_loc,
                            fetch_polygon=True,
                            force_refresh=bool(data.get("force_refresh", False))
                        )
                        boundary_geojson = geo_res.get("geojson")

                if not boundary_geojson:
                    self._send_json(400, {"error": "No boundary GeoJSON provided"})
                    return

                grid = fetch_elevation_grid(bbox, grid_width=40, grid_depth=40)
                mesh_data = generate_boundary_preview_mesh(
                    elev_grid=grid,
                    bbox=bbox,
                    boundary_geojson=boundary_geojson,
                    width_mm=width_mm,
                    depth_mm=depth_mm,
                    base_height_mm=base_h,
                    target_relief_mm=relief_h
                )
                self._send_json(200, mesh_data)
            except Exception as err:
                self._send_json(500, {"error": str(err)})
            return

        elif parsed.path == "/api/generate":
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len).decode("utf-8")
            data = json.loads(body)

            try:
                b = data["bbox"]
                bbox = BoundingBox(south=b["south"], west=b["west"], north=b["north"], east=b["east"])
                
                config = MapMakerConfig(
                    canvas=CanvasConfig(
                        width_mm=float(data.get("width", 250.0)),
                        depth_mm=float(data.get("depth", 250.0)),
                        base_shape=str(data.get("base_shape", "rectangle")),
                        base_sides=int(data.get("base_sides", 6)),
                        base_height_mm=float(data.get("base_height", 4.0)),
                        rotation_deg=float(data.get("rotation", 0.0)),
                        topography_enabled=bool(data.get("topography", True)),
                        target_relief_height_mm=float(data.get("target_height", 25.0)),
                        blocks_enabled=bool(data.get("blocks", data.get("buildings", False))),
                        block_min_height_mm=float(data.get("block_min_h", 2.0)),
                        block_max_height_mm=float(data.get("block_max_h", 6.0)),
                        block_groove_width_mm=float(data.get("block_groove_w", 1.2)),
                        buildings_enabled=bool(data.get("blocks", data.get("buildings", False))),
                        viewing_orientation=str(data.get("orientation", "tabletop")),
                        path_waypoints=[(float(p[0]), float(p[1])) for p in data.get("path_waypoints", [])],
                        landmarks=data.get("landmarks", []),
                        boundary_geojson=data.get("boundary_geojson")
                    ),
                    bbox=bbox,
                    location_name=data.get("location", "Exported Map")
                )
                if not data.get("dowels", True):
                    config.dowel.enabled = False

                tiling_engine = TilingEngine(config)
                cols, rows = tiling_engine.cols, tiling_engine.rows

                # Fetch full resolution elevation grid
                grid_res = 120 * max(cols, rows)
                grid_res = min(360, max(80, grid_res))
                elev_grid = fetch_elevation_grid(bbox, grid_width=grid_res, grid_depth=grid_res)

                out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "exports", "latest_export"))
                manifest = tiling_engine.process_and_export_all(elev_grid, out_dir)

                global LATEST_GUIDE_PATH
                LATEST_GUIDE_PATH = manifest["assembly_guide"]

                self._send_json(200, {
                    "success": True,
                    "num_tiles": manifest["num_tiles"],
                    "output_dir": out_dir,
                    "assembly_guide": manifest["assembly_guide"]
                })
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return


def start_server(port=PORT):
    from http.server import ThreadingHTTPServer
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer(("0.0.0.0", port), MapMakerHTTPHandler)
    server.serve_forever()


def launch_desktop_window(port=PORT):
    """Spawns a standalone desktop browser window across Linux, Windows, and macOS."""
    setup_display_env()
    app_url = f"http://127.0.0.1:{port}"

    if sys.platform == "win32" or os.name == "nt":
        win_candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        ]
        for exe in win_candidates:
            if exe and os.path.exists(exe):
                try:
                    subprocess.Popen(
                        [exe, f"--app={app_url}", "--enable-webgl", "--ignore-gpu-blocklist"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    print("[*] Standalone Desktop Window spawned on Windows.")
                    return
                except Exception:
                    pass
        try:
            webbrowser.open(app_url)
            print(f"[*] Opened {app_url} in default Windows browser.")
        except Exception as e:
            print(f"[!] Note: Could not auto-launch browser ({e}). Open {app_url} manually.")
        return

    elif sys.platform == "darwin":
        mac_chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if os.path.exists(mac_chrome):
            try:
                subprocess.Popen(
                    [mac_chrome, f"--app={app_url}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                print("[*] Standalone Desktop Window spawned on macOS.")
                return
            except Exception:
                pass
        try:
            webbrowser.open(app_url)
            print(f"[*] Opened {app_url} in default macOS browser.")
        except Exception as e:
            print(f"[!] Note: Could not auto-launch browser ({e}). Open {app_url} manually.")
        return

    # Linux (Wayland / X11 / Chrome Remote Desktop)
    linux_candidates = [
        "/opt/google/chrome/chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser"
    ]
    browser_exe = next((p for p in linux_candidates if os.path.exists(p)), "/opt/google/chrome/chrome")
    cmd = [
        browser_exe,
        f"--app={app_url}",
        "--ozone-platform=wayland",
        "--enable-features=UseOzonePlatform",
        "--enable-webgl",
        "--ignore-gpu-blocklist",
        "--enable-unsafe-swiftshader",
        "--class=MapMaker3D"
    ]
    
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ
        )
        print(f"[*] Standalone Desktop Window spawned on Linux display.")
    except Exception as e:
        try:
            webbrowser.open(app_url)
        except Exception:
            pass
        print(f"[!] Note: Could not auto-launch Chrome window ({e}). You can open {app_url} in your browser.")


def main():
    setup_display_env()
    print("==================================================")
    print("          MAPMAKER 3D DESKTOP APPLICATION         ")
    print("==================================================")
    if sys.platform.startswith("linux"):
        print(f"[*] Display configured for Linux / Chrome Remote Desktop:")
        print(f"    WAYLAND_DISPLAY: {os.environ.get('WAYLAND_DISPLAY')}")
        print(f"    DISPLAY:         {os.environ.get('DISPLAY')}")
        print(f"    XAUTHORITY:      {os.environ.get('XAUTHORITY')}")
    else:
        print(f"[*] Platform: {sys.platform} (Native OS Window Manager)")
    print(f"[*] Server listening on: http://127.0.0.1:{PORT}")
    print(f"[*] Opening standalone desktop window on your desktop...")

    # Start server in background thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Launch desktop application window
    launch_desktop_window(PORT)

    print("\n[✓] MapMaker 3D is running!")
    print(f"    View in Chrome Remote Desktop or open: http://127.0.0.1:{PORT}")
    print("    Press Ctrl+C to exit.")

    try:
        server_thread.join()
    except KeyboardInterrupt:
        print("\nExiting MapMaker 3D.")


if __name__ == "__main__":
    main()
