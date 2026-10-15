"""Unit and integration tests for MapMaker 3D cache freshness, TTL expiration,
HTTP 304 conditional validation, force_refresh bypass, and offline fallback.
"""

import os
import sys
import time
import json
import hashlib
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import urllib.error
from PIL import Image
import io

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engine.geo import _is_cache_fresh, geocode_location, fetch_osm_tile
from engine.blocks import _fetch_overpass_cached


class TestCacheFreshness(unittest.TestCase):

    def test_is_cache_fresh_helper(self):
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            temp_path = tf.name
            tf.write(b"test")

        try:
            # Fresh file created just now
            self.assertTrue(_is_cache_fresh(temp_path, max_age_days=30))

            # Set mtime to 10 days ago -> still fresh for 30-day TTL
            ten_days_ago = time.time() - (10 * 86400)
            os.utime(temp_path, (ten_days_ago, ten_days_ago))
            self.assertTrue(_is_cache_fresh(temp_path, max_age_days=30))

            # Set mtime to 35 days ago -> expired for 30-day TTL
            thirty_five_days_ago = time.time() - (35 * 86400)
            os.utime(temp_path, (thirty_five_days_ago, thirty_five_days_ago))
            self.assertFalse(_is_cache_fresh(temp_path, max_age_days=30))

            # Non-existent file
            self.assertFalse(_is_cache_fresh(temp_path + "_nonexistent", max_age_days=30))
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_overpass_ttl_and_force_refresh(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("engine.blocks.OVERPASS_CACHE_DIR", tmpdir):
                query = "[out:json];way(1,2,3,4);out;"
                q_hash = hashlib.md5(query.encode("utf-8")).hexdigest()
                cache_file = os.path.join(tmpdir, f"{q_hash}.json")

                old_payload = {"elements": [{"id": 1, "version": "old_cached"}]}
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(old_payload, f)

                # 1. Fresh cache hit (no network call)
                with patch("urllib.request.urlopen") as mock_urlopen:
                    res = _fetch_overpass_cached(query, force_refresh=False, max_age_days=30)
                    self.assertEqual(res["elements"][0]["version"], "old_cached")
                    mock_urlopen.assert_not_called()

                # 2. force_refresh=True bypasses fresh cache and fetches live
                new_payload = {"elements": [{"id": 1, "version": "live_refreshed"}]}
                mock_resp = MagicMock()
                mock_resp.read.return_value = json.dumps(new_payload).encode("utf-8")
                mock_resp.__enter__.return_value = mock_resp

                with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
                    res = _fetch_overpass_cached(query, force_refresh=True, max_age_days=30)
                    self.assertEqual(res["elements"][0]["version"], "live_refreshed")
                    self.assertTrue(mock_urlopen.called)

                # 3. Expired TTL (40 days old) triggers automatic refresh even with force_refresh=False
                old_time = time.time() - (40 * 86400)
                os.utime(cache_file, (old_time, old_time))

                ttl_payload = {"elements": [{"id": 1, "version": "ttl_auto_refreshed"}]}
                mock_resp.read.return_value = json.dumps(ttl_payload).encode("utf-8")

                with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
                    res = _fetch_overpass_cached(query, force_refresh=False, max_age_days=30)
                    self.assertEqual(res["elements"][0]["version"], "ttl_auto_refreshed")
                    self.assertTrue(mock_urlopen.called)

                # 4. Offline resilience: if network fails on expired cache, falls back to existing disk cache
                os.utime(cache_file, (old_time, old_time))
                with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Offline")):
                    res = _fetch_overpass_cached(query, force_refresh=True, max_age_days=30)
                    self.assertIsNotNone(res)
                    self.assertEqual(res["elements"][0]["version"], "ttl_auto_refreshed")

    def test_osm_tile_304_not_modified_and_force_refresh(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("engine.geo.CACHE_DIR", tmpdir):
                z, x, y = 12, 2048, 1360
                tile_dir = os.path.join(tmpdir, "osm_tiles", str(z), str(x))
                os.makedirs(tile_dir, exist_ok=True)
                tile_path = os.path.join(tile_dir, f"{y}.png")

                # Create a valid 256x256 blue PNG in cache
                img = Image.new("RGB", (256, 256), color=(10, 20, 200))
                img.save(tile_path, format="PNG")

                # 1. Fresh cache hit -> 0 network requests
                with patch("urllib.request.urlopen") as mock_urlopen:
                    out_img = fetch_osm_tile(z, x, y, force_refresh=False, max_age_days=30)
                    self.assertEqual(out_img.getpixel((0, 0)), (10, 20, 200))
                    mock_urlopen.assert_not_called()

                # 2. Expired tile -> sends If-Modified-Since, receives 304 Not Modified, touches mtime
                old_time = time.time() - (45 * 86400)
                os.utime(tile_path, (old_time, old_time))
                self.assertFalse(_is_cache_fresh(tile_path, max_age_days=30))

                http_304 = urllib.error.HTTPError(
                    url="https://tile.openstreetmap.org/12/2048/1360.png",
                    code=304,
                    msg="Not Modified",
                    hdrs={},
                    fp=None
                )
                with patch("urllib.request.urlopen", side_effect=http_304) as mock_urlopen:
                    out_img = fetch_osm_tile(z, x, y, force_refresh=False, max_age_days=30)
                    self.assertEqual(out_img.getpixel((0, 0)), (10, 20, 200))
                    # Verify If-Modified-Since header was sent
                    req_sent = mock_urlopen.call_args[0][0]
                    self.assertIn("If-modified-since", req_sent.headers)
                    # Verify file timestamp was refreshed
                    self.assertTrue(_is_cache_fresh(tile_path, max_age_days=30))

                # 3. force_refresh=True -> downloads updated green tile
                buf = io.BytesIO()
                Image.new("RGB", (256, 256), color=(50, 220, 80)).save(buf, format="PNG")
                mock_resp = MagicMock()
                mock_resp.read.return_value = buf.getvalue()
                mock_resp.__enter__.return_value = mock_resp

                with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
                    out_img = fetch_osm_tile(z, x, y, force_refresh=True, max_age_days=30)
                    self.assertEqual(out_img.getpixel((0, 0)), (50, 220, 80))


if __name__ == "__main__":
    unittest.main()
