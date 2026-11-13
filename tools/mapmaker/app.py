#!/usr/bin/env python3
"""MapMaker 3D: Standalone Desktop Application & Local Fabrication Service.

Automatically detects Chrome Remote Desktop display variables (Wayland/X11)
and launches the interactive 2D/3D memorabilia design interface in a native desktop window.
"""

import os
import re
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

from engine.config import (
    MapMakerConfig,
    CanvasConfig,
    PrinterProfile,
    DowelProfile,
    ToleranceProfile,
    BoundingBox,
)
from engine.geo import (
    geocode_location,
    fetch_elevation_grid,
    calculate_route,
    fetch_osm_buildings,
    fetch_map_texture,
    parse_gps_track,
)
from engine.blocks import fetch_urban_blocks
from engine.mesh import generate_boundary_preview_mesh
from engine.tiling import TilingEngine
from engine.platform_utils import (
    get_app_root_dir,
    get_writable_base_dir,
    open_in_file_explorer,
)

PORT = 8765
GUI_DIR = os.path.join(get_app_root_dir(), "gui")
LATEST_EXPORT_META = {
    "dir": None,
    "guide": None,
    "zip": None,
    "3mf": None,
    "preview": None,
    "slug": "mapmaker_export",
}


def _slugify(name: str) -> str:
    base = (name or "exported_map").split(",")[0].strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", base).strip("_")
    return slug[:40] if slug else "exported_map"


def setup_display_env():
    """Detects and exports the active Chrome Remote Desktop / Wayland / X11 environment on Linux."""
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

    def _send_bytes(self, status_code: int, content_type: str, data: bytes, download_filename: str = ""):
        self.send_response(status_code)
        self._send_cors_headers()
        self.send_header("Content-Type", content_type)
        if download_filename:
            self.send_header("Content-Disposition", f'attachment; filename="{download_filename}"')
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, status_code: int, obj: dict):
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
                fetch_poly = query.get("poly", ["true"])[0].lower() != "false"
                res = geocode_location(q, fetch_polygon=fetch_poly, force_refresh=force_refresh)
                bb = res["bbox"]
                self._send_json(200, {
                    "display_name": res["display_name"],
                    "lat": res["lat"],
                    "lon": res["lon"],
                    "bbox": {
                        "south": bb.south,
                        "west": bb.west,
                        "north": bb.north,
                        "east": bb.east
                    },
                    "real_aspect_ratio": round(bb.real_aspect_ratio, 4),
                    "geojson": res.get("geojson")
                })
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
                bb = res["bbox"]
                self._send_json(200, {
                    "status": "ok",
                    "display_name": res["display_name"],
                    "geojson": res.get("geojson"),
                    "real_aspect_ratio": round(bb.real_aspect_ratio, 4),
                    "bbox": {
                        "south": bb.south,
                        "west": bb.west,
                        "north": bb.north,
                        "east": bb.east
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

                grid = fetch_elevation_grid(bbox, grid_width=70, grid_depth=70)
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
                res_n = int(query.get("res", [90])[0])
                res_n = max(40, min(160, res_n))
                grid = fetch_elevation_grid(bbox, grid_width=res_n, grid_depth=res_n)
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
            profile = query.get("profile", ["hiking"])[0]
            if not pts_str:
                self._send_json(400, {"error": "Missing waypoints query parameter"})
                return
            try:
                pts = []
                for p in pts_str.split(";"):
                    if not p.strip():
                        continue
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

        elif path == "/api/buildings_3d":
            try:
                s = float(query["south"][0])
                w = float(query["west"][0])
                n = float(query["north"][0])
                e = float(query["east"][0])
                bbox = BoundingBox(south=s, west=w, north=n, east=e)
                bldgs = fetch_osm_buildings(bbox, max_buildings=1800, force_refresh=force_refresh)
                self._send_json(200, {
                    "status": "ok",
                    "count": len(bldgs),
                    "buildings": [b.to_dict() for b in bldgs]
                })
            except Exception as err:
                self._send_json(500, {"error": str(err)})
            return

        elif path == "/api/guide":
            gp = LATEST_EXPORT_META.get("guide")
            if gp and os.path.exists(gp):
                with open(gp, "rb") as f:
                    self._send_bytes(200, "text/markdown; charset=utf-8", f.read())
            else:
                self._send_json(404, {"error": "No assembly guide generated yet."})
            return

        elif path == "/api/download_zip":
            zp = LATEST_EXPORT_META.get("zip")
            slug = LATEST_EXPORT_META.get("slug", "mapmaker_export")
            if zp and os.path.exists(zp):
                with open(zp, "rb") as f:
                    self._send_bytes(200, "application/zip", f.read(), download_filename=f"{slug}_3dprint.zip")
            else:
                self._send_json(404, {"error": "No export ZIP generated yet."})
            return

        elif path == "/api/download_3mf":
            mp = LATEST_EXPORT_META.get("3mf")
            slug = LATEST_EXPORT_META.get("slug", "mapmaker_export")
            if mp and os.path.exists(mp):
                with open(mp, "rb") as f:
                    self._send_bytes(200, "model/3mf", f.read(), download_filename=f"{slug}.3mf")
            else:
                self._send_json(404, {"error": "No 3MF generated yet."})
            return

        elif path == "/api/preview_png":
            pp = LATEST_EXPORT_META.get("preview")
            if pp and os.path.exists(pp):
                with open(pp, "rb") as f:
                    self._send_bytes(200, "image/png", f.read())
            else:
                self._send_json(404, {"error": "No preview PNG generated yet."})
            return

        elif path == "/api/ping":
            self._send_json(200, {"app": "MapMaker3D", "status": "ok"})
            return

        else:
            self._send_json(404, {"error": f"Path not found: {path}"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"

        if parsed.path == "/api/open_folder":
            target_dir = LATEST_EXPORT_META.get("dir")
            if not target_dir or not os.path.exists(target_dir):
                target_dir = os.path.join(get_writable_base_dir(), "exports")
                os.makedirs(target_dir, exist_ok=True)
            opened = open_in_file_explorer(target_dir)
            self._send_json(200, {"status": "ok" if opened else "fallback", "path": target_dir})
            return

        elif parsed.path == "/api/upload_track":
            try:
                data = json.loads(body)
                track_res = parse_gps_track(
                    content=data.get("content", ""),
                    filename=data.get("filename", "track.gpx")
                )
                self._send_json(200, {"status": "ok", **track_res})
            except Exception as err:
                self._send_json(400, {"error": str(err)})
            return

        elif parsed.path == "/api/boundary_mesh":
            try:
                data = json.loads(body)
                b = data["bbox"]
                bbox = BoundingBox(south=float(b["south"]), west=float(b["west"]), north=float(b["north"]), east=float(b["east"]))
                width_mm = float(data.get("width_mm", 250.0))
                depth_mm = float(data.get("depth_mm", 250.0))
                base_h = float(data.get("base_height", 4.0))
                relief_h = float(data.get("target_relief", 15.0))
                rot_deg = float(data.get("rotation", 0.0))
                depress_water = bool(data.get("depress_water", False))
                topography = bool(data.get("topography", True))
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

                grid = fetch_elevation_grid(bbox, grid_width=70, grid_depth=70)
                mesh_data = generate_boundary_preview_mesh(
                    elev_grid=grid,
                    bbox=bbox,
                    boundary_geojson=boundary_geojson,
                    width_mm=width_mm,
                    depth_mm=depth_mm,
                    base_height_mm=base_h,
                    target_relief_mm=relief_h,
                    rotation_deg=rot_deg,
                    depress_water=depress_water,
                    topography_enabled=topography
                )
                self._send_json(200, mesh_data)
            except Exception as err:
                self._send_json(500, {"error": str(err)})
            return

        elif parsed.path == "/api/generate":
            try:
                data = json.loads(body)
                b = data["bbox"]
                bbox = BoundingBox(
                    south=float(b["south"]),
                    west=float(b["west"]),
                    north=float(b["north"]),
                    east=float(b["east"])
                )

                z_mult_raw = data.get("z_multiplier")
                z_mult = float(z_mult_raw) if (z_mult_raw is not None and str(z_mult_raw).strip() != "") else None
                target_h = None if (z_mult is not None and z_mult > 0) else float(data.get("target_height", 25.0))
                vert_exag = z_mult if (z_mult is not None and z_mult > 0) else 2.0

                urban_mode = str(data.get("urban_mode", "none"))
                if urban_mode == "none" and data.get("blocks"):
                    urban_mode = "blocks"
                elif urban_mode == "none" and data.get("buildings"):
                    urban_mode = "buildings"

                printer = PrinterProfile(
                    name=str(data.get("printer_name", "Bambu Lab A1")),
                    bed_width=float(data.get("bed_width", 256.0)),
                    bed_depth=float(data.get("bed_depth", 256.0)),
                    nozzle_diameter=float(data.get("nozzle_diameter", 0.40)),
                    line_width=round(float(data.get("nozzle_diameter", 0.40)) * 1.05, 2),
                    min_printable_wall=round(float(data.get("nozzle_diameter", 0.40)) * 2.10, 2),
                )

                tolerances = ToleranceProfile(
                    path_joint_clearance=float(data.get("path_clearance", 0.20)),
                    pin_socket_clearance=float(data.get("pin_clearance", 0.15)),
                )

                dowel = DowelProfile(
                    enabled=bool(data.get("dowels", True)),
                    dowel_type=str(data.get("dowel_type", "flat_biscuit")),
                )

                loc_name = str(data.get("location", "Exported Map"))
                config = MapMakerConfig(
                    printer=printer,
                    dowel=dowel,
                    tolerances=tolerances,
                    canvas=CanvasConfig(
                        width_mm=float(data.get("width", 250.0)),
                        depth_mm=float(data.get("depth", 250.0)),
                        lock_aspect_ratio=bool(data.get("lock_aspect_ratio", False)),
                        base_shape=str(data.get("base_shape", "rectangle")),
                        base_sides=int(data.get("base_sides", 6)),
                        base_height_mm=float(data.get("base_height", 4.0)),
                        rotation_deg=float(data.get("rotation", 0.0)),
                        topography_enabled=bool(data.get("topography", True)),
                        vertical_exaggeration=vert_exag,
                        target_relief_height_mm=target_h,
                        urban_mode=urban_mode,
                        blocks_enabled=(urban_mode == "blocks"),
                        block_min_height_mm=float(data.get("block_min_h", 2.0)),
                        block_max_height_mm=float(data.get("block_max_h", 6.0)),
                        block_groove_width_mm=float(data.get("block_groove_w", 1.2)),
                        buildings_enabled=(urban_mode == "buildings"),
                        building_height_scale=float(data.get("building_scale", 1.2)),
                        viewing_orientation=str(data.get("orientation", "tabletop")),
                        route_mode=str(data.get("route_mode", "hiking")),
                        path_style=str(data.get("path_style", "flat_strip")),
                        depress_water=bool(data.get("depress_water", True)),
                        frame_enabled=bool(data.get("frame_enabled", False)),
                        frame_width_mm=float(data.get("frame_width", 4.2)),
                        frame_height_mm=float(data.get("frame_height", 3.2)),
                        title_text=str(data.get("title_text", "")).strip(),
                        subtitle_text=str(data.get("subtitle_text", "")).strip(),
                        path_waypoints=[(float(p[0]), float(p[1])) for p in data.get("path_waypoints", [])],
                        landmarks=data.get("landmarks", []),
                        boundary_geojson=data.get("boundary_geojson")
                    ),
                    bbox=bbox,
                    location_name=loc_name
                )

                if config.canvas.lock_aspect_ratio:
                    config.apply_aspect_ratio_lock()

                tiling_engine = TilingEngine(config)
                cols, rows = tiling_engine.cols, tiling_engine.rows

                # High-definition elevation sampling (~180 samples per tile axis)
                grid_w = min(440, max(160, 180 * cols))
                grid_d = min(440, max(160, 180 * rows))
                elev_grid = fetch_elevation_grid(bbox, grid_width=grid_w, grid_depth=grid_d)

                slug = _slugify(config.canvas.title_text or loc_name)
                out_dir = os.path.abspath(os.path.join(get_writable_base_dir(), "exports", slug))
                manifest = tiling_engine.process_and_export_all(
                    elev_grid,
                    out_dir,
                    clean_output_dir=True,
                    generate_preview=True,
                    export_3mf=True,
                    create_zip=True
                )

                LATEST_EXPORT_META["dir"] = out_dir
                LATEST_EXPORT_META["guide"] = manifest.get("assembly_guide")
                LATEST_EXPORT_META["zip"] = manifest.get("export_zip")
                LATEST_EXPORT_META["3mf"] = manifest.get("assembly_3mf")
                LATEST_EXPORT_META["preview"] = manifest.get("diagnostic_preview")
                LATEST_EXPORT_META["slug"] = slug

                self._send_json(200, {
                    "success": True,
                    "slug": slug,
                    "num_tiles": manifest["num_tiles"],
                    "canvas_width_mm": config.canvas.width_mm,
                    "canvas_depth_mm": config.canvas.depth_mm,
                    "output_dir": out_dir,
                    "assembly_guide": manifest["assembly_guide"],
                    "has_3mf": bool(manifest.get("assembly_3mf")),
                    "has_zip": bool(manifest.get("export_zip")),
                    "has_preview": bool(manifest.get("diagnostic_preview")),
                })
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return


def start_server(port=PORT, host="127.0.0.1"):
    """Starts local HTTP server. Defaults to 127.0.0.1 so Windows Defender Firewall never prompts for UAC."""
    from http.server import ThreadingHTTPServer
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer((host, port), MapMakerHTTPHandler)
    server.serve_forever()


def _resolve_startup_port(preferred_port=PORT, host="127.0.0.1"):
    """Returns (port, already_running_mapmaker). Avoids [WinError 10048] on double-click."""
    import socket
    import urllib.request

    for cand in range(preferred_port, preferred_port + 15):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.35)
            in_use = (s.connect_ex(("127.0.0.1", cand)) == 0)
        if not in_use:
            return cand, False
        if cand == preferred_port:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{cand}/api/ping", timeout=0.8) as r:
                    info = json.loads(r.read().decode("utf-8"))
                    if info.get("app") == "MapMaker3D":
                        return cand, True
            except Exception:
                pass
    return preferred_port, False


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
        print("[*] Standalone Desktop Window spawned on Linux display.")
    except Exception as e:
        try:
            webbrowser.open(app_url)
        except Exception:
            pass
        print(f"[!] Note: Could not auto-launch Chrome window ({e}). You can open {app_url} in your browser.")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="MapMaker 3D Desktop Studio")
    parser.add_argument("--port", type=int, default=PORT, help="Local port (default: 8765)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--no-window", action="store_true", help="Run headless HTTP server without opening browser")
    args, _ = parser.parse_known_args()

    setup_display_env()
    active_port, already_running = _resolve_startup_port(args.port, args.host)

    print("==================================================")
    print("          MAPMAKER 3D DESKTOP APPLICATION         ")
    print("==================================================")

    if already_running:
        print(f"[*] MapMaker 3D is already running on http://127.0.0.1:{active_port} — opening window!")
        if not args.no_window:
            launch_desktop_window(active_port)
        return

    if sys.platform.startswith("linux"):
        print("[*] Display configured for Linux / Chrome Remote Desktop:")
        print(f"    WAYLAND_DISPLAY: {os.environ.get('WAYLAND_DISPLAY')}")
        print(f"    DISPLAY:         {os.environ.get('DISPLAY')}")
        print(f"    XAUTHORITY:      {os.environ.get('XAUTHORITY')}")
    else:
        print(f"[*] Platform: {sys.platform} (Native OS Window Manager)")
    print(f"[*] Server listening on: http://{args.host}:{active_port}")

    server_thread = threading.Thread(target=start_server, kwargs={"port": active_port, "host": args.host}, daemon=True)
    server_thread.start()

    if not args.no_window:
        print("[*] Opening standalone desktop window on your desktop...")
        launch_desktop_window(active_port)

    print("\n[✓] MapMaker 3D is running!")
    print(f"    Open in browser: http://127.0.0.1:{active_port}")
    print("    Press Ctrl+C to exit.")

    try:
        server_thread.join()
    except KeyboardInterrupt:
        print("\nExiting MapMaker 3D.")


if __name__ == "__main__":
    main()
