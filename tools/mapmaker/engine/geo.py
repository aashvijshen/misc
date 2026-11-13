"""Geospatial data engine for MapMaker 3D.

Fetches and decodes:
1. Geocoding & homeland territorial boundary extraction via OpenStreetMap Nominatim.
2. Exact Web Mercator Digital Elevation Model (DEM) tiles via AWS Open Data Terrarium.
3. 3D Building footprint vectors and heights via OSM Overpass API (with disk caching).
4. Multi-mode trail/hiking, cycling, and driving routing via OSM OSRM servers.
5. GPX, KML, and GeoJSON track import with distance & elevation-gain stats.
"""

import os
import sys
import math
import time
import io
import re
import urllib.request
import urllib.parse
import json
import hashlib
import xml.etree.ElementTree as ET
import numpy as np
from scipy.ndimage import map_coordinates
from PIL import Image
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor
from shapely.geometry import shape, mapping, Polygon, MultiPolygon, Point, LineString
from .config import BoundingBox
from .platform_utils import get_cache_dir, urlopen_resilient

USER_AGENT = "MapMaker3D/2.0 (3D printing CAD engine; https://github.com/aashvij/mapmaker3d)"
CACHE_DIR = get_cache_dir()


def _is_cache_fresh(filepath: str, max_age_days: int) -> bool:
    """Checks whether a cached file exists and is younger than max_age_days."""
    if not os.path.exists(filepath):
        return False
    if max_age_days <= 0:
        return False
    try:
        age_sec = time.time() - os.path.getmtime(filepath)
        return age_sec < (max_age_days * 86400)
    except Exception:
        return False


def geocode_location(
    query: str,
    fetch_polygon: bool = True,
    force_refresh: bool = False,
    max_age_days: int = 60
) -> Dict[str, Any]:
    """Resolves a geographic place query to GPS coordinates, bounding box, and territorial GeoJSON boundary."""
    nom_cache_dir = os.path.join(CACHE_DIR, "nominatim")
    os.makedirs(nom_cache_dir, exist_ok=True)
    cache_key = hashlib.md5(f"{query.lower().strip()}_{fetch_polygon}".encode('utf-8')).hexdigest()
    cache_file = os.path.join(nom_cache_dir, f"{cache_key}.json")

    loc = None
    if not force_refresh and _is_cache_fresh(cache_file, max_age_days):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                loc = json.load(f)
        except Exception:
            loc = None

    if loc is None:
        encoded = urllib.parse.quote(query)
        poly_param = "&polygon_geojson=1&polygon_threshold=0.004" if fetch_polygon else ""
        url = f"https://nominatim.openstreetmap.org/search?q={encoded}&format=json{poly_param}&limit=1"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen_resilient(req, timeout=15) as resp:
                data = json.loads(resp.read().decode('utf-8'))

            if not data:
                raise ValueError(f"No location found for query: '{query}'")

            loc = data[0]
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(loc, f)
            except Exception:
                pass
        except ValueError:
            raise
        except Exception as net_err:
            if os.path.exists(cache_file):
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        loc = json.load(f)
                except Exception:
                    pass
            if loc is None:
                raise net_err

    lat, lon = float(loc["lat"]), float(loc["lon"])
    bb = loc.get("boundingbox", [])
    if len(bb) == 4:
        s, n, w, e = float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])
    else:
        s, n, w, e = lat - 0.05, lat + 0.05, lon - 0.05, lon + 0.05

    addresstype = loc.get("addresstype", "")
    place_class = loc.get("class", "")
    mid_lat = (s + n) / 2.0
    mid_lon = (w + e) / 2.0
    lat_span = n - s
    lon_span = e - w
    cos_l = max(0.2, math.cos(math.radians(lat)))
    center_dist = math.hypot(mid_lat - lat, (mid_lon - lon) * cos_l)
    effective_span = max(lat_span, lon_span * cos_l)

    is_large_territory = addresstype in ("country", "state", "province", "region") or (
        place_class == "boundary" and addresstype not in ("city", "town", "suburb", "quarter", "borough", "municipality")
    )
    raw_geojson = loc.get("geojson")
    mainland_geom_override = None

    if not is_large_territory and (
        center_dist > 0.35
        or (effective_span > 0.50 and center_dist > 0.15)
        or (effective_span > 0.85 and addresstype in ("city", "town", "village", "suburb", "municipality", "borough", "quarter"))
    ):
        used_mainland_poly = False
        if raw_geojson and raw_geojson.get("type") == "MultiPolygon":
            try:
                full_geom = shape(raw_geojson)
                if not full_geom.is_valid:
                    full_geom = full_geom.buffer(0)
                pt_center = Point(lon, lat)
                geoms_list = list(full_geom.geoms) if hasattr(full_geom, "geoms") else [full_geom]
                best_poly = min(geoms_list, key=lambda g: g.distance(pt_center))
                pw, ps, pe, pn = best_poly.bounds
                if 0.04 <= (pn - ps) <= 3.0 and 0.04 <= (pe - pw) <= 3.0:
                    s, n, w, e = ps, pn, pw, pe
                    mainland_geom_override = best_poly
                    used_mainland_poly = True
            except Exception:
                pass

        if not used_mainland_poly:
            default_span_lat = 0.20  # ~22 km
            default_span_lon = default_span_lat / cos_l
            s = lat - default_span_lat / 2.0
            n = lat + default_span_lat / 2.0
            w = lon - default_span_lon / 2.0
            e = lon + default_span_lon / 2.0

    # For large countries/states with trans-oceanic territories or antimeridian wraps
    # (e.g. New Zealand Chatham Islands across +-180, Chile Easter Island, France overseas, US Aleutians),
    # cluster around the primary homeland landmass so mainland geometry isn't squashed!
    elif is_large_territory and raw_geojson and raw_geojson.get("type") == "MultiPolygon":
        try:
            full_geom = shape(raw_geojson)
            if not full_geom.is_valid:
                full_geom = full_geom.buffer(0)
            geoms_list = list(full_geom.geoms) if hasattr(full_geom, "geoms") else [full_geom]
            if len(geoms_list) > 1 and (lon_span > 32.0 or lat_span > 32.0):
                pt_ref = Point(lon, lat)
                # Anchor on largest homeland landmass near Nominatim reference point
                scored = sorted(
                    geoms_list,
                    key=lambda g: g.area / (1.0 + 0.15 * g.distance(pt_ref)),
                    reverse=True
                )
                anchor = scored[0]
                ax, ay = anchor.centroid.x, anchor.centroid.y
                # Keep all islands within 18 degrees of the anchor landmass (and same hemisphere side of antimeridian)
                homeland_parts = [
                    g for g in geoms_list
                    if abs(g.centroid.x - ax) <= 48.0 and anchor.distance(g) <= 18.0
                ]
                if homeland_parts and len(homeland_parts) < len(geoms_list):
                    clustered = MultiPolygon(homeland_parts) if len(homeland_parts) > 1 else homeland_parts[0]
                    cw, cs, ce, cn = clustered.bounds
                    # Only apply if raw bbox had extreme oceanic bloat (> 1.45x span of homeland cluster)
                    if (e - w) > 1.45 * (ce - cw) or (n - s) > 1.45 * (cn - cs):
                        w, s, e, n = cw, cs, ce, cn
                        mainland_geom_override = clustered
        except Exception:
            pass

    # Expand point/tiny bounding boxes (e.g. single mountain peak or monument) to a scenic ~7-8 km frame
    min_span_lat = 0.055
    min_span_lon = min_span_lat / cos_l
    if abs(n - s) < min_span_lat:
        mid_lat = (n + s) / 2.0
        s = mid_lat - min_span_lat / 2.0
        n = mid_lat + min_span_lat / 2.0
    if abs(e - w) < min_span_lon:
        mid_lon = (e + w) / 2.0
        w = mid_lon - min_span_lon / 2.0
        e = mid_lon + min_span_lon / 2.0

    # Process territorial / coastline GeoJSON if present
    processed_geojson = None
    if raw_geojson and raw_geojson.get("type") in ("Polygon", "MultiPolygon"):
        try:
            geom = mainland_geom_override if mainland_geom_override is not None else shape(raw_geojson)
            if not geom.is_valid:
                geom = geom.buffer(0)

            if geom.geom_type == "MultiPolygon":
                total_area = geom.area
                significant = [p for p in geom.geoms if (p.area / max(1e-9, total_area)) >= 0.002]
                if significant:
                    geom = MultiPolygon(significant) if len(significant) > 1 else significant[0]

            total_verts = sum(len(p.exterior.coords) for p in (geom.geoms if geom.geom_type == "MultiPolygon" else [geom]))
            if total_verts > 3200:
                geom = geom.simplify(0.004, preserve_topology=True)

            processed_geojson = mapping(geom)
        except Exception:
            processed_geojson = raw_geojson

    return {
        "display_name": loc.get("display_name", query),
        "lat": lat,
        "lon": lon,
        "bbox": BoundingBox(south=s, west=w, north=n, east=e),
        "geojson": processed_geojson
    }


def lat_lon_to_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
    """Converts WGS84 latitude/longitude to Web Mercator tile indices (x, y) at zoom level."""
    lat_clamped = max(-85.0511, min(85.0511, lat))
    lat_rad = math.radians(lat_clamped)
    n = 2.0 ** zoom
    xtile = int(max(0, min(n - 1, math.floor((lon + 180.0) / 360.0 * n))))
    ytile = int(max(0, min(n - 1, math.floor((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n))))
    return xtile, ytile


def tile_to_lat_lon(xtile: int, ytile: int, zoom: int) -> Tuple[float, float]:
    """Converts top-left corner of Web Mercator tile to latitude/longitude."""
    n = 2.0 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1.0 - 2.0 * ytile / n)))
    lat_deg = math.degrees(lat_rad)
    return lat_deg, lon_deg


def fetch_terrarium_tile(zoom: int, x: int, y: int) -> Image.Image:
    """Fetches an AWS Terrarium elevation tile, caching to disk."""
    tile_dir = os.path.join(CACHE_DIR, "terrarium", str(zoom), str(x))
    os.makedirs(tile_dir, exist_ok=True)
    tile_path = os.path.join(tile_dir, f"{y}.png")

    if not os.path.exists(tile_path):
        url = f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{zoom}/{x}/{y}.png"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen_resilient(req, timeout=15) as resp:
            content = resp.read()
        with open(tile_path, "wb") as f:
            f.write(content)

    with Image.open(tile_path) as im:
        return im.convert("RGB")


def fetch_osm_tile(
    zoom: int,
    x: int,
    y: int,
    force_refresh: bool = False,
    max_age_days: int = 30
) -> Image.Image:
    """Fetches an OpenStreetMap standard map tile, caching to disk with TTL and HTTP 304 validation."""
    import email.utils
    import urllib.error

    tile_dir = os.path.join(CACHE_DIR, "osm_tiles", str(zoom), str(x))
    os.makedirs(tile_dir, exist_ok=True)
    tile_path = os.path.join(tile_dir, f"{y}.png")

    if not force_refresh and _is_cache_fresh(tile_path, max_age_days):
        with Image.open(tile_path) as im:
            return im.convert("RGB")

    url = f"https://tile.openstreetmap.org/{zoom}/{x}/{y}.png"
    headers = {"User-Agent": USER_AGENT}
    if os.path.exists(tile_path) and not force_refresh:
        try:
            mtime = os.path.getmtime(tile_path)
            headers["If-Modified-Since"] = email.utils.formatdate(mtime, usegmt=True)
        except Exception:
            pass

    try:
        req = urllib.request.Request(url, headers=headers)
        with urlopen_resilient(req, timeout=10) as resp:
            content = resp.read()
        with open(tile_path, "wb") as f:
            f.write(content)
    except urllib.error.HTTPError as http_err:
        if http_err.code == 304 and os.path.exists(tile_path):
            try:
                os.utime(tile_path, None)
            except Exception:
                pass
        elif os.path.exists(tile_path):
            pass
        else:
            raise
    except Exception:
        if not os.path.exists(tile_path):
            raise

    with Image.open(tile_path) as im:
        return im.convert("RGB")


def fetch_map_texture(
    bbox: BoundingBox,
    target_size: int = 1024,
    force_refresh: bool = False
) -> bytes:
    """Fetches, stitches, and crops an OpenStreetMap texture precisely to the bounding box."""
    max_deg_span = max(bbox.lat_span, bbox.lon_span)
    z = int(round(math.log2(360.0 * (target_size / 256.0) / max(0.001, max_deg_span))))
    zoom = max(2, min(16, z))

    x_min, y_north = lat_lon_to_tile(bbox.north, bbox.west, zoom)
    x_max, y_south = lat_lon_to_tile(bbox.south, bbox.east, zoom)

    y_min = min(y_north, y_south)
    y_max = max(y_north, y_south)
    x_start = min(x_min, x_max)
    x_end = max(x_min, x_max)

    if (x_end - x_start + 1) * (y_max - y_min + 1) > 25:
        zoom = max(2, zoom - 1)
        x_min, y_north = lat_lon_to_tile(bbox.north, bbox.west, zoom)
        x_max, y_south = lat_lon_to_tile(bbox.south, bbox.east, zoom)
        y_min, y_max = min(y_north, y_south), max(y_north, y_south)
        x_start, x_end = min(x_min, x_max), max(x_min, x_max)

    num_x = x_end - x_start + 1
    num_y = y_max - y_min + 1

    mosaic = Image.new("RGB", (num_x * 256, num_y * 256), color=(240, 240, 240))
    tile_jobs = []
    for ix, x in enumerate(range(x_start, x_end + 1)):
        for iy, y in enumerate(range(y_min, y_max + 1)):
            tile_jobs.append((ix, iy, x, y))

    def _fetch_one_osm(job):
        ix, iy, x, y = job
        try:
            return ix, iy, fetch_osm_tile(zoom, x, y, force_refresh=force_refresh)
        except Exception:
            return ix, iy, None

    with ThreadPoolExecutor(max_workers=min(12, max(2, len(tile_jobs)))) as executor:
        for ix, iy, tile in executor.map(_fetch_one_osm, tile_jobs):
            if tile is not None:
                mosaic.paste(tile, (ix * 256, iy * 256))

    n_tiles = 2.0 ** zoom

    def lat_lon_to_global_px(lat, lon):
        lat_rad = math.radians(max(-85.0511, min(85.0511, lat)))
        gx = (lon + 180.0) / 360.0 * n_tiles * 256.0
        gy = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n_tiles * 256.0
        return gx, gy

    left_px, top_px = lat_lon_to_global_px(bbox.north, bbox.west)
    right_px, bottom_px = lat_lon_to_global_px(bbox.south, bbox.east)

    origin_x = x_start * 256.0
    origin_y = y_min * 256.0

    crop_box = (
        max(0, int(round(left_px - origin_x))),
        max(0, int(round(top_px - origin_y))),
        min(mosaic.width, max(1, int(round(right_px - origin_x)))),
        min(mosaic.height, max(1, int(round(bottom_px - origin_y))))
    )

    cropped = mosaic.crop(crop_box)
    resized = cropped.resize((target_size, target_size), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    resized.save(buf, format="JPEG", quality=88, optimize=True)
    return buf.getvalue()


def decode_terrarium_elevation(rgb_img: Image.Image) -> np.ndarray:
    """Decodes a Terrarium RGB image into elevation in meters above sea level."""
    arr = np.array(rgb_img, dtype=np.float32)
    r = arr[:, :, 0]
    g = arr[:, :, 1]
    b = arr[:, :, 2]
    return (r * 256.0 + g + (b / 256.0)) - 32768.0


def select_optimal_zoom(bbox: BoundingBox, target_samples: int = 250) -> int:
    """Selects the best Web Mercator zoom level (4 to 14) to cover bbox with crisp resolution."""
    max_span = max(bbox.lat_span, bbox.lon_span)
    for z in range(15, 0, -1):
        tile_deg = 360.0 / (2.0 ** z)
        tiles_needed = max_span / tile_deg
        total_pixels = tiles_needed * 256.0
        if total_pixels <= max(512.0, target_samples * 2.8) and tiles_needed <= 7.0:
            return min(14, max(4, z))
    return 6


def fetch_elevation_grid(bbox: BoundingBox, grid_width: int = 200, grid_depth: int = 200) -> np.ndarray:
    """Fetches and resamples an exact Web-Mercator-corrected M x N elevation grid (in meters).

    Returns:
        np.ndarray of shape (grid_depth, grid_width) where row 0 is South and row -1 is North.
    """
    zoom = select_optimal_zoom(bbox, target_samples=max(grid_width, grid_depth))

    x_min, y_north = lat_lon_to_tile(bbox.north, bbox.west, zoom)
    x_max, y_south = lat_lon_to_tile(bbox.south, bbox.east, zoom)

    y_min = min(y_north, y_south)
    y_max = max(y_north, y_south)
    x_start = min(x_min, x_max)
    x_end = max(x_min, x_max)

    num_x_tiles = x_end - x_start + 1
    num_y_tiles = y_max - y_min + 1

    mosaic_w = num_x_tiles * 256
    mosaic_h = num_y_tiles * 256
    mosaic_elev = np.zeros((mosaic_h, mosaic_w), dtype=np.float32)

    tile_jobs = []
    for ix, x in enumerate(range(x_start, x_end + 1)):
        for iy, y in enumerate(range(y_min, y_max + 1)):
            tile_jobs.append((ix, iy, x, y))

    def _fetch_one_elev(job):
        ix, iy, x, y = job
        tile_img = fetch_terrarium_tile(zoom, x, y)
        tile_elev = decode_terrarium_elevation(tile_img)
        return ix, iy, tile_elev

    with ThreadPoolExecutor(max_workers=min(12, max(2, len(tile_jobs)))) as executor:
        for ix, iy, tile_elev in executor.map(_fetch_one_elev, tile_jobs):
            r0 = iy * 256
            r1 = (iy + 1) * 256
            c0 = ix * 256
            c1 = (ix + 1) * 256
            mosaic_elev[r0:r1, c0:c1] = tile_elev

    # Exact Web Mercator pixel mapping (eliminates up to +87km latitude drift on country maps!)
    n_tiles = 2.0 ** zoom
    origin_px_x = x_start * 256.0
    origin_px_y = y_min * 256.0

    target_lons = np.linspace(bbox.west, bbox.east, grid_width, dtype=np.float64)
    target_lats = np.linspace(bbox.south, bbox.north, grid_depth, dtype=np.float64)
    lat_rads = np.radians(np.clip(target_lats, -85.0511, 85.0511))

    col_coords = ((target_lons + 180.0) / 360.0) * (n_tiles * 256.0) - origin_px_x - 0.5
    row_coords = ((1.0 - np.arcsinh(np.tan(lat_rads)) / math.pi) / 2.0) * (n_tiles * 256.0) - origin_px_y - 0.5

    col_coords = np.clip(col_coords, 0.0, mosaic_w - 1.0)
    row_coords = np.clip(row_coords, 0.0, mosaic_h - 1.0)

    rr, cc = np.meshgrid(row_coords, col_coords, indexing="ij")
    grid = map_coordinates(mosaic_elev, [rr, cc], order=1, mode="nearest").astype(np.float32)
    return grid


@dataclass
class BuildingPolygon:
    """Represents a 3D building footprint with height."""
    osm_id: int
    coordinates: List[Tuple[float, float]]  # [(lat, lon), ...]
    height_meters: float
    min_height_meters: float = 0.0
    name: str = ""

    @property
    def center(self) -> Tuple[float, float]:
        if not self.coordinates:
            return (0.0, 0.0)
        lats = [c[0] for c in self.coordinates]
        lons = [c[1] for c in self.coordinates]
        return (sum(lats) / len(lats), sum(lons) / len(lons))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": f"bldg_{self.osm_id}",
            "osm_id": self.osm_id,
            "name": self.name,
            "coordinates": self.coordinates,
            "height_meters": round(self.height_meters, 1),
            "center": [round(self.center[0], 5), round(self.center[1], 5)]
        }


def parse_osm_height(tags: Dict[str, str]) -> float:
    """Resolves building height in meters from OSM tags."""
    if "height" in tags:
        raw = tags["height"].lower().strip()
        m_num = re.search(r"[-+]?\d*\.?\d+", raw)
        if m_num:
            try:
                val = float(m_num.group(0))
                if "ft" in raw or "'" in raw:
                    val *= 0.3048
                return max(3.0, val)
            except ValueError:
                pass

    for lvl_key in ("building:levels", "levels"):
        if lvl_key in tags:
            try:
                levels = float(tags[lvl_key])
                return max(3.0, levels * 3.2)
            except ValueError:
                pass

    b_type = tags.get("building", "yes").lower()
    if b_type in ("skyscraper", "tower"):
        return 85.0
    if b_type in ("apartments", "commercial", "office", "hotel", "hospital", "university"):
        return 18.0
    if b_type in ("house", "residential", "detached", "terrace", "garage"):
        return 6.5
    return 9.0


OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://lambert.openstreetmap.de/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]


def fetch_osm_buildings(
    bbox: BoundingBox,
    max_buildings: int = 2500,
    force_refresh: bool = False,
    max_age_days: int = 30
) -> List[BuildingPolygon]:
    """Queries OSM Overpass API for 3D building footprints within bbox, with persistent disk caching."""
    bldg_cache_dir = os.path.join(CACHE_DIR, "buildings")
    os.makedirs(bldg_cache_dir, exist_ok=True)

    # For very wide boxes (> 0.12 deg ~ 13km), focus on taller named/multi-story landmark buildings so Overpass stays fast
    max_span = max(bbox.lat_span, bbox.lon_span)
    if max_span > 0.14:
        query = f"""
        [out:json][timeout:22];
        (
          way["building"]["height"]({bbox.south:.5f},{bbox.west:.5f},{bbox.north:.5f},{bbox.east:.5f});
          way["building"]["building:levels"~"^[4-9]|[1-9][0-9]"]({bbox.south:.5f},{bbox.west:.5f},{bbox.north:.5f},{bbox.east:.5f});
        );
        out geom {max_buildings};
        """
    else:
        query = f"""
        [out:json][timeout:22];
        (
          way["building"]({bbox.south:.5f},{bbox.west:.5f},{bbox.north:.5f},{bbox.east:.5f});
        );
        out geom {max_buildings};
        """

    q_hash = hashlib.md5(query.encode("utf-8")).hexdigest()
    cache_file = os.path.join(bldg_cache_dir, f"{q_hash}.json")

    res = None
    if not force_refresh and _is_cache_fresh(cache_file, max_age_days):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                res = json.load(f)
        except Exception:
            res = None

    if res is None:
        data = urllib.parse.urlencode({"data": query}).encode("utf-8")
        headers = {
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded"
        }
        last_err = None
        for endpoint in OVERPASS_ENDPOINTS:
            try:
                req = urllib.request.Request(endpoint, data=data, headers=headers)
                with urlopen_resilient(req, timeout=20) as resp:
                    cand = json.loads(resp.read().decode("utf-8"))
                if cand and "elements" in cand:
                    res = cand
                    try:
                        with open(cache_file, "w", encoding="utf-8") as f:
                            json.dump(res, f)
                    except Exception:
                        pass
                    break
            except Exception as e:
                last_err = e
                continue

        if res is None and os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    res = json.load(f)
            except Exception:
                pass

        if res is None:
            raise RuntimeError(f"All Overpass endpoints failed! Last error: {last_err}")

    elements = res.get("elements", [])
    buildings = []

    for el in elements:
        if el.get("type") != "way" or "geometry" not in el:
            continue

        geom = el["geometry"]
        coords = [(pt["lat"], pt["lon"]) for pt in geom]
        if len(coords) < 3:
            continue

        tags = el.get("tags", {})
        height = parse_osm_height(tags)

        buildings.append(BuildingPolygon(
            osm_id=el["id"],
            coordinates=coords,
            height_meters=height,
            name=tags.get("name", "")
        ))

    # Sort tallest first so if capped, iconic skyscrapers are always preserved
    buildings.sort(key=lambda b: b.height_meters, reverse=True)
    return buildings[:max_buildings]


def _haversine_distance_m(pts: List[Tuple[float, float]]) -> float:
    """Computes total geodesic polyline length in meters."""
    total = 0.0
    R = 6371000.0
    for i in range(len(pts) - 1):
        lat1, lon1 = math.radians(pts[i][0]), math.radians(pts[i][1])
        lat2, lon2 = math.radians(pts[i + 1][0]), math.radians(pts[i + 1][1])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        total += 2.0 * R * math.asin(min(1.0, math.sqrt(a)))
    return total


def calculate_route(
    waypoints: List[Tuple[float, float]],
    profile: str = "hiking"
) -> Dict[str, Any]:
    """Calculates a route along hiking trails, cycling paths, driving roads, or direct segments.

    Args:
        waypoints: List of (lat, lon) coordinates.
        profile: 'hiking' / 'walking' / 'foot', 'cycling' / 'bike', 'driving' / 'roads', or 'direct'.
    """
    if len(waypoints) < 2:
        return {
            "coordinates": waypoints,
            "distance_m": 0.0,
            "duration_s": 0.0,
            "profile": profile,
            "snapped": False
        }

    prof = (profile or "hiking").lower().strip()
    if prof == "direct":
        return {
            "coordinates": waypoints,
            "distance_m": _haversine_distance_m(waypoints),
            "duration_s": 0.0,
            "profile": "direct",
            "snapped": False
        }

    coords_str = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in waypoints)

    if prof in ("hiking", "walking", "foot", "trail"):
        candidate_urls = [
            f"https://routing.openstreetmap.de/routed-foot/route/v1/foot/{coords_str}?overview=full&geometries=geojson",
        ]
    elif prof in ("cycling", "bike", "bicycle"):
        candidate_urls = [
            f"https://routing.openstreetmap.de/routed-bike/route/v1/bike/{coords_str}?overview=full&geometries=geojson",
        ]
    else:
        candidate_urls = [
            f"https://routing.openstreetmap.de/routed-car/route/v1/driving/{coords_str}?overview=full&geometries=geojson",
            f"https://router.project-osrm.org/route/v1/driving/{coords_str}?overview=full&geometries=geojson",
        ]

    for url in candidate_urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen_resilient(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if data.get("code") == "Ok" and data.get("routes"):
                route = data["routes"][0]
                geojson_pts = route["geometry"]["coordinates"]
                route_coords = [(float(pt[1]), float(pt[0])) for pt in geojson_pts]
                return {
                    "coordinates": route_coords,
                    "distance_m": float(route.get("distance", _haversine_distance_m(route_coords))),
                    "duration_s": float(route.get("duration", 0.0)),
                    "profile": prof,
                    "snapped": True
                }
        except Exception as e:
            sys.stderr.write(f"[WARN] Routing endpoint failed ({url[:55]}... -> {e})\n")

    return {
        "coordinates": waypoints,
        "distance_m": _haversine_distance_m(waypoints),
        "duration_s": 0.0,
        "profile": prof,
        "snapped": False,
        "fallback": True
    }


def parse_gps_track(content: str, filename: str = "track.gpx", max_points: int = 900) -> Dict[str, Any]:
    """Parses a .gpx, .kml, or .geojson GPS track (e.g. from Strava, Garmin, AllTrails)
    into waypoints, padded BoundingBox, track distance, elevation gain, and suggested plaque labels.
    """
    ext = os.path.splitext(filename.lower())[1]
    raw_pts: List[Tuple[float, float]] = []
    elevations: List[float] = []
    track_name = ""

    text = content.strip()
    if ext == ".geojson" or ext == ".json" or text.startswith("{"):
        obj = json.loads(text)

        def _extract_geojson(node):
            nonlocal track_name
            if not isinstance(node, dict):
                return
            props = node.get("properties") or {}
            if not track_name and isinstance(props, dict) and props.get("name"):
                track_name = str(props["name"])
            t = node.get("type")
            if t == "FeatureCollection":
                for feat in node.get("features", []):
                    _extract_geojson(feat)
            elif t == "Feature":
                _extract_geojson(node.get("geometry"))
            elif t == "LineString":
                for c in node.get("coordinates", []):
                    if len(c) >= 2:
                        raw_pts.append((float(c[1]), float(c[0])))
                        if len(c) >= 3 and c[2] is not None:
                            elevations.append(float(c[2]))
            elif t == "MultiLineString":
                for seg in node.get("coordinates", []):
                    for c in seg:
                        if len(c) >= 2:
                            raw_pts.append((float(c[1]), float(c[0])))
                            if len(c) >= 3 and c[2] is not None:
                                elevations.append(float(c[2]))

        _extract_geojson(obj)

    elif ext == ".kml" or "<kml" in text[:400].lower():
        root = ET.fromstring(text)
        for el in root.iter():
            tag = el.tag.split("}")[-1].lower()
            if tag == "name" and not track_name and el.text and el.text.strip():
                track_name = el.text.strip()
            elif tag == "coordinates" and el.text:
                for tok in el.text.strip().split():
                    parts = tok.split(",")
                    if len(parts) >= 2:
                        try:
                            lon_v, lat_v = float(parts[0]), float(parts[1])
                            raw_pts.append((lat_v, lon_v))
                            if len(parts) >= 3:
                                elevations.append(float(parts[2]))
                        except ValueError:
                            pass
    else:
        # GPX XML parser (namespace-agnostic)
        root = ET.fromstring(text)
        for el in root.iter():
            tag = el.tag.split("}")[-1].lower()
            if tag == "name" and not track_name and el.text and el.text.strip():
                track_name = el.text.strip()
            elif tag in ("trkpt", "rtept"):
                lat_s = el.attrib.get("lat")
                lon_s = el.attrib.get("lon")
                if lat_s is not None and lon_s is not None:
                    raw_pts.append((float(lat_s), float(lon_s)))
                    for child in el:
                        if child.tag.split("}")[-1].lower() == "ele" and child.text:
                            try:
                                elevations.append(float(child.text.strip()))
                            except ValueError:
                                pass

    if len(raw_pts) < 2:
        raise ValueError("GPS file must contain at least 2 track/route coordinates.")

    dist_m = _haversine_distance_m(raw_pts)
    elev_gain_m = 0.0
    max_elev_m = None
    if len(elevations) >= 2:
        max_elev_m = max(elevations)
        # Smooth minor 2m GPS barometric jitter
        last_e = elevations[0]
        for ev in elevations[1:]:
            if ev - last_e >= 2.0:
                elev_gain_m += (ev - last_e)
                last_e = ev
            elif last_e - ev >= 2.0:
                last_e = ev

    # Simplify dense GPS tracks cleanly while preserving exact start/finish & switchbacks
    if len(raw_pts) > max_points:
        line = LineString([(lon, lat) for lat, lon in raw_pts])
        span = max(line.bounds[2] - line.bounds[0], line.bounds[3] - line.bounds[1], 1e-4)
        tol = span * 0.0006
        simpl = line.simplify(tol, preserve_topology=False)
        while len(simpl.coords) > max_points and tol < span * 0.02:
            tol *= 1.5
            simpl = line.simplify(tol, preserve_topology=False)
        coords_out = [(float(lat), float(lon)) for lon, lat in simpl.coords]
    else:
        coords_out = raw_pts

    lats = [p[0] for p in coords_out]
    lons = [p[1] for p in coords_out]
    s, n = min(lats), max(lats)
    w, e = min(lons), max(lons)

    # Add 22% scenic margin around track so surrounding hills/valleys frame the path!
    pad_lat = max(0.012, (n - s) * 0.22)
    mid_lat = (s + n) / 2.0
    cos_l = max(0.2, math.cos(math.radians(mid_lat)))
    pad_lon = max(0.012 / cos_l, (e - w) * 0.22)

    bbox = BoundingBox(
        south=s - pad_lat,
        west=w - pad_lon,
        north=n + pad_lat,
        east=e + pad_lon
    )

    if not track_name:
        track_name = os.path.splitext(os.path.basename(filename))[0].replace("_", " ").replace("-", " ").title()

    dist_km = dist_m / 1000.0
    if elev_gain_m >= 25.0:
        suggested_subtitle = f"{dist_km:.1f} KM • +{int(round(elev_gain_m))} M GAIN"
    else:
        suggested_subtitle = f"{dist_km:.1f} KM"

    return {
        "name": track_name,
        "coordinates": coords_out,
        "raw_point_count": len(raw_pts),
        "point_count": len(coords_out),
        "distance_m": round(dist_m, 1),
        "distance_km": round(dist_km, 2),
        "elevation_gain_m": round(elev_gain_m, 1),
        "max_elevation_m": round(max_elev_m, 1) if max_elev_m is not None else None,
        "bbox": {
            "south": bbox.south,
            "west": bbox.west,
            "north": bbox.north,
            "east": bbox.east
        },
        "start_point": {"name": "Start", "lat": coords_out[0][0], "lon": coords_out[0][1]},
        "finish_point": {"name": "Finish", "lat": coords_out[-1][0], "lon": coords_out[-1][1]},
        "suggested_title": track_name.upper()[:28],
        "suggested_subtitle": suggested_subtitle
    }
