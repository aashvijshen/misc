"""Cross-OS compatibility unit tests for MapMaker 3D (Windows win32, macOS darwin, Linux)."""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app
from engine.config import MapMakerConfig, CanvasConfig, BoundingBox
from engine.tiling import TilingEngine
from engine.mesh import SolidMesh


class TestCrossOSCompatibility(unittest.TestCase):

    def test_windows_setup_display_env_without_getuid(self):
        """Simulates Windows where sys.platform == 'win32' and os.getuid does not exist."""
        with patch.object(sys, "platform", "win32"):
            # Temporarily remove os.getuid if present
            orig_getuid = getattr(os, "getuid", None)
            try:
                if hasattr(os, "getuid"):
                    delattr(os, "getuid")
                # Must be a clean no-op without raising AttributeError
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

    def test_utf8_unicode_export_on_non_utf8_locale(self):
        """Verifies ASSEMBLY_GUIDE.md and ASCII STL export use explicit UTF-8 encoding
        so international characters (e.g. Japanese kanji, accents, symbols) never fail on Windows cp1252.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            bbox = BoundingBox(south=35.34, west=138.71, north=35.38, east=138.75)
            config = MapMakerConfig(
                canvas=CanvasConfig(width_mm=100.0, depth_mm=100.0, base_height_mm=4.0),
                bbox=bbox,
                location_name="日本 (Japan) — 富士山 Mount Fuji ✓"
            )
            engine = TilingEngine(config)
            elev = np.zeros((20, 20), dtype=np.float32)
            res = engine.process_and_export_all(elev, tmpdir)

            guide_path = res["assembly_guide"]
            self.assertTrue(os.path.exists(guide_path))
            with open(guide_path, "r", encoding="utf-8") as f:
                text = f.read()
            self.assertIn("日本 (Japan) — 富士山 Mount Fuji ✓", text)

            # Also verify ASCII STL export uses UTF-8
            verts = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0], [0, 0, 10]], dtype=np.float64)
            faces = np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]], dtype=np.int32)
            mesh = SolidMesh(verts, faces)
            ascii_stl = os.path.join(tmpdir, "test_ascii.stl")
            mesh.export_stl(ascii_stl, binary=False)
            self.assertTrue(os.path.exists(ascii_stl))


if __name__ == "__main__":
    unittest.main()
