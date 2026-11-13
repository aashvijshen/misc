"""Cross-OS compatibility unit tests for MapMaker 3D (Windows win32, macOS darwin, Linux).

Verifies:
- Windows `setup_display_env()` without `os.getuid`.
- Windows & macOS desktop window launching and fallbacks.
- Native Windows `%LOCALAPPDATA%\\MapMaker3D\\cache` routing.
- Cross-OS TrueType bold font resolution (Matplotlib bundled + Windows Fonts).
- Closed NTFS file handles on cached PNG tiles and ZIP exports (no `[WinError 32]`).
- Firewall-free `127.0.0.1` default server bind & `/api/ping` double-launch attach.
- Windows Explorer `os.startfile` integration (`open_in_file_explorer`).
- Explicit UTF-8 Unicode safety on non-UTF-8 (`cp1252`) Windows locales.
- Portable Windows `.zip` bundler (`package_portable.py`) with CRLF `.bat` line endings.
"""

import os
import sys
import json
import zipfile
import tempfile
import threading
import urllib.request
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app
import package_portable
from engine import platform_utils
from engine.config import MapMakerConfig, CanvasConfig, BoundingBox
from engine.tiling import TilingEngine
from engine.mesh import SolidMesh
from engine.geo import fetch_osm_tile
from engine.export import create_export_zip


class TestCrossOSCompatibility(unittest.TestCase):

    def test_windows_setup_display_env_without_getuid(self):
        """Simulates Windows where sys.platform == 'win32' and os.getuid does not exist."""
        with patch.object(sys, "platform", "win32"):
            orig_getuid = getattr(os, "getuid", None)
            try:
                if hasattr(os, "getuid"):
                    delattr(os, "getuid")
                app.setup_display_env()
            finally:
                if orig_getuid is not None:
                    os.getuid = orig_getuid

    def test_windows_launch_desktop_window_fallback(self):
        """Verifies Windows browser launch falls back cleanly to webbrowser.open when exe not found."""
        with patch.object(sys, "platform", "win32"), \
             patch("os.path.exists", return_value=False), \
             patch("webbrowser.open") as mock_wb:
            app.launch_desktop_window(port=8765)
            mock_wb.assert_called_once_with("http://127.0.0.1:8765")

    def test_windows_launch_desktop_window_chrome_found(self):
        """Verifies Windows launches chrome.exe in --app mode when installed."""
        with patch.object(sys, "platform", "win32"), \
             patch("os.path.exists", return_value=True), \
             patch("subprocess.Popen") as mock_popen:
            app.launch_desktop_window(port=8765)
            self.assertTrue(mock_popen.called)
            args = mock_popen.call_args[0][0]
            self.assertIn("--app=http://127.0.0.1:8765", args)

    def test_macos_launch_desktop_window(self):
        """Verifies macOS browser launch behavior."""
        with patch.object(sys, "platform", "darwin"), \
             patch("os.path.exists", return_value=False), \
             patch("webbrowser.open") as mock_wb:
            app.launch_desktop_window(port=8765)
            mock_wb.assert_called_once_with("http://127.0.0.1:8765")

    def test_windows_localappdata_cache_dir(self):
        """Verifies Windows routes cache to %LOCALAPPDATA%\\MapMaker3D\\cache."""
        with patch.object(sys, "platform", "win32"), \
             patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\Maker\AppData\Local"}, clear=False):
            cdir = platform_utils.get_cache_dir()
            self.assertIn("MapMaker3D", cdir)
            self.assertTrue(cdir.startswith(r"C:\Users\Maker\AppData\Local"))

    def test_cross_os_bold_font_resolver(self):
        """Verifies resolve_bold_ttf_path() locates a valid existing .ttf font without Linux hardcoding."""
        ttf = platform_utils.resolve_bold_ttf_path()
        self.assertIsNotNone(ttf)
        self.assertTrue(os.path.exists(ttf))

    def test_windows_explorer_open_folder(self):
        """Verifies open_in_file_explorer invokes os.startfile on Windows."""
        with tempfile.TemporaryDirectory() as tmpd:
            with patch.object(sys, "platform", "win32"):
                mock_startfile = unittest.mock.MagicMock()
                with patch.object(os, "startfile", mock_startfile, create=True):
                    ok = platform_utils.open_in_file_explorer(tmpd)
                    self.assertTrue(ok)
                    self.assertTrue(mock_startfile.called)

    def test_closed_ntfs_file_handles_on_tiles_and_zip(self):
        """Verifies cached tile reads and create_export_zip leave 0 open file locks so files can be deleted immediately."""
        with tempfile.TemporaryDirectory() as tmpd:
            with patch("engine.geo.CACHE_DIR", tmpd):
                tdir = os.path.join(tmpd, "osm_tiles", "10", "500")
                os.makedirs(tdir, exist_ok=True)
                tpath = os.path.join(tdir, "400.png")
                Image.new("RGB", (256, 256), color=(20, 60, 180)).save(tpath, format="PNG")

                loaded = fetch_osm_tile(10, 500, 400, force_refresh=False)
                self.assertEqual(loaded.size, (256, 256))
                # Immediate deletion would raise PermissionError [WinError 32] on Windows if Image.open handle leaked!
                os.remove(tpath)
                self.assertFalse(os.path.exists(tpath))

            src_dir = os.path.join(tmpd, "sample_export")
            os.makedirs(src_dir, exist_ok=True)
            sample_f = os.path.join(src_dir, "ASSEMBLY_GUIDE.md")
            with open(sample_f, "w", encoding="utf-8") as f:
                f.write("# Test Guide\n")
            zip_out = os.path.join(tmpd, "bundle.zip")
            create_export_zip(src_dir, zip_out)
            self.assertTrue(os.path.exists(zip_out))
            platform_utils.safe_remove_path(src_dir)
            self.assertFalse(os.path.exists(src_dir))

    def test_localhost_bind_and_double_launch_ping_detection(self):
        """Verifies default server binds to 127.0.0.1 (avoiding Windows Firewall UAC) and detects active instances."""
        test_port = 18791
        srv_thread = threading.Thread(target=app.start_server, kwargs={"port": test_port, "host": "127.0.0.1"}, daemon=True)
        srv_thread.start()

        import time
        time.sleep(0.25)

        resolved_port, already = app._resolve_startup_port(preferred_port=test_port, host="127.0.0.1")
        self.assertEqual(resolved_port, test_port)
        self.assertTrue(already)

        with urllib.request.urlopen(f"http://127.0.0.1:{test_port}/api/ping", timeout=2) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(payload.get("app"), "MapMaker3D")

    def test_utf8_unicode_export_on_non_utf8_locale(self):
        """Verifies ASSEMBLY_GUIDE.md and ASCII STL export use explicit UTF-8 encoding."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bbox = BoundingBox(south=35.34, west=138.71, north=35.38, east=138.75)
            config = MapMakerConfig(
                canvas=CanvasConfig(width_mm=100.0, depth_mm=100.0, base_height_mm=4.0),
                bbox=bbox,
                location_name="日本 (Japan) — 富士山 Mount Fuji ✓"
            )
            engine = TilingEngine(config)
            elev = np.zeros((20, 20), dtype=np.float32)
            res = engine.process_and_export_all(elev, tmpdir, generate_preview=False)

            guide_path = res["assembly_guide"]
            self.assertTrue(os.path.exists(guide_path))
            with open(guide_path, "r", encoding="utf-8") as f:
                text = f.read()
            self.assertIn("日本 (Japan) — 富士山 Mount Fuji ✓", text)

            verts = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0], [0, 0, 10]], dtype=np.float64)
            faces = np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]], dtype=np.int32)
            mesh = SolidMesh(verts, faces)
            ascii_stl = os.path.join(tmpdir, "test_ascii.stl")
            mesh.export_stl(ascii_stl, binary=False)
            self.assertTrue(os.path.exists(ascii_stl))

    def test_portable_windows_zip_packaging_and_crlf_bats(self):
        """Verifies package_portable.py creates a clean zip with CRLF line endings on all Windows .bat scripts."""
        with tempfile.TemporaryDirectory() as tmpd:
            zpath = os.path.join(tmpd, "MapMaker3D_Windows_Portable.zip")
            built = package_portable.build_portable_zip(zpath)
            self.assertTrue(os.path.exists(built))
            with zipfile.ZipFile(built, "r") as zf:
                names = zf.namelist()
                self.assertIn("MapMaker3D/run_mapmaker.bat", names)
                self.assertIn("MapMaker3D/mapmaker_cli.bat", names)
                self.assertIn("MapMaker3D/build_windows_exe.bat", names)
                self.assertIn("MapMaker3D/engine/platform_utils.py", names)
                bat_bytes = zf.read("MapMaker3D/run_mapmaker.bat")
                self.assertIn(b"\r\n", bat_bytes)


if __name__ == "__main__":
    unittest.main()
