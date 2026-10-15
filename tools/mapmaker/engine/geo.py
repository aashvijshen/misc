"""Geospatial data engine for MapMaker 3D.

Fetches and decodes:
1. Geocoding via OpenStreetMap Nominatim.
2. Digital Elevation Model (DEM) tiles via AWS Open Data Terrarium.
3. 3D Building footprint vectors and heights via OSM Overpass API.
"""

import os
import sys
import math
import time
import io
import urllib.request
import urllib.parse
import json
import hashlib
import numpy as np
from PIL import Image
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor
from shapely.geometry import shape, mapping, Polygon, MultiPolygon, Point
from .config import BoundingBox

USER_AGENT = "MapMaker3D/1.0 (3D printing CAD engine; https://github.com/aashvij/mapmaker3d)"
CACHE_DIR = os.path.expanduser("~/.cache/mapmaker3d")


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
    """Resolves a geographic place query to GPS coordinates, bounding box, and territorial GeoJSON boundary using Nominatim.
    
    Args:
        query: Search string (e.g., 'Manhattan', 'Mount Fuji', 'Kyoto, Japan', 'India', 'Texas').
        fetch_polygon: Whether to fetch high-resolution territorial/coastline GeoJSON.
        force_refresh: If True, bypass local disk cache and fetch live data.
        max_age_days: Maximum cache age in days before automatic refresh (default 60 days).
        
    Returns:
        Dict containing name, lat, lon, BoundingBox, and optional GeoJSON boundary dict.
    """
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
        poly_param = "&polygon_geojson=1&polygon_threshold=0.005" if fetch_polygon else ""
        url = f"https://nominatim.openstreetmap.org/search?q={encoded}&format=json{poly_param}&limit=1"
        
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as resp:
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
            # Resilient offline fallback if cached file exists
            if os.path.exists(cache_file):
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        loc = json.load(f)
                except Exception:
                    pass
            if loc is None:
                raise net_err
        
    lat, lon = float(loc["lat"]), float(loc["lon"])
    # Nominatim bbox is [south_lat, north_lat, west_lon, east_lon] as strings
    bb = loc.get("boundingbox", [])
    if len(bb) == 4:
        s, n, w, e = float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])
    else:
        s, n, w, e = lat - 0.05, lat + 0.05, lon - 0.05, lon + 0.05
        
    # Check for administrative / maritime bounding box bloat:
    # e.g. Tokyo prefecture includes the remote Ogasawara islands extending 1,800km into the Pacific,
    # causing the bounding box centroid to be in the ocean and span > 15 degrees.
    addresstype = loc.get("addresstype", "")
    place_class = loc.get("class", "")
    mid_lat = (s + n) / 2.0
    mid_lon = (w + e) / 2.0
    lat_span = n - s
    lon_span = e - w
    cos_l = max(0.2, math.cos(math.radians(lat)))
    center_dist = math.hypot(mid_lat - lat, (mid_lon - lon) * cos_l)
    effective_span = max(lat_span, lon_span * cos_l)

    # Countries, states, provinces, and regions represent large sovereign boundaries;
    # do NOT collapse them into a 22km city box!
    is_large_territory = addresstype in ("country", "state", "province", "region") or (place_class == "boundary" and addresstype not in ("city", "town", "suburb"))
    raw_geojson = loc.get("geojson")
    mainland_geom_override = None

    if not is_large_territory and (
        center_dist > 0.35
        or (effective_span > 0.50 and center_dist > 0.15)
        or (effective_span > 0.85 and addresstype in ("city", "town", "village", "suburb", "municipality", "borough", "quarter"))
    ):
        # If MultiPolygon has a mainland component containing/nearest to (lon, lat), use its true bounds!
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
            # Center the metropolitan map directly on the primary city / place coordinates!
            default_span_lat = 0.20  # ~22 km
            default_span_lon = default_span_lat / cos_l
            s = lat - default_span_lat / 2.0
            n = lat + default_span_lat / 2.0
            w = lon - default_span_lon / 2.0
            e = lon + default_span_lon / 2.0

    # If the bounding box is a single point or very tiny (< 0.04 deg), expand it so it forms a usable map area
    min_span = 0.04
    if abs(n - s) < min_span:
        mid_lat = (n + s) / 2.0
        s = mid_lat - min_span / 2.0
        n = mid_lat + min_span / 2.0
    if abs(e - w) < min_span:
        mid_lon = (e + w) / 2.0
        w = mid_lon - min_span / 2.0
        e = mid_lon + min_span / 2.0

    # Process territorial / coastline GeoJSON if present
    processed_geojson = None
    if raw_geojson and raw_geojson.get("type") in ("Polygon", "MultiPolygon"):
        try:
            geom = mainland_geom_override if mainland_geom_override is not None else shape(raw_geojson)
            if not geom.is_valid:
                geom = geom.buffer(0)
            
            if geom.geom_type == "MultiPolygon":
                total_area = geom.area
                # Prune tiny slivers/rocks (< 0.2% of total area) that are non-printable as separate FDM parts
                significant = [p for p in geom.geoms if (p.area / max(1e-9, total_area)) >= 0.002]
                if significant:
                    geom = MultiPolygon(significant) if len(significant) > 1 else significant[0]
            
            # If still very dense (> 2500 vertices), simplify slightly for fast client transmission and smooth mesh generation
            total_verts = sum(len(p.exterior.coords) for p in (geom.geoms if geom.geom_type == "MultiPolygon" else [geom]))
            if total_verts > 2500:
                geom = geom.simplify(0.005, preserve_topology=True)
                
            processed_geojson = mapping(geom)
        except Exception as ex:
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
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    xtile = int((lon + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
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
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read()
        with open(tile_path, "wb") as f:
            f.write(content)
            
    return Image.open(tile_path).convert("RGB")


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
        return Image.open(tile_path).convert("RGB")

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
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read()
        with open(tile_path, "wb") as f:
            f.write(content)
    except urllib.error.HTTPError as http_err:
        if http_err.code == 304 and os.path.exists(tile_path):
            # Tile has not changed on server; touch timestamp to reset TTL (0 bytes downloaded)
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
            
    return Image.open(tile_path).convert("RGB")


def fetch_map_texture(
    bbox: BoundingBox,
    target_size: int = 1024,
    force_refresh: bool = False
) -> bytes:
    """Fetches, stitches, and crops an OpenStreetMap texture precisely to the bounding box.
    
    Returns:
        JPEG image bytes.
    """
    max_deg_span = max(bbox.lat_span, bbox.lon_span)
    z = int(round(math.log2(360.0 * (target_size / 256.0) / max(0.001, max_deg_span))))
    zoom = max(2, min(16, z))

    x_min, y_north = lat_lon_to_tile(bbox.north, bbox.west, zoom)
    x_max, y_south = lat_lon_to_tile(bbox.south, bbox.east, zoom)

    y_min = min(y_north, y_south)
    y_max = max(y_north, y_south)
    x_start = min(x_min, x_max)
    x_end = max(x_min, x_max)

    # Step down zoom if too many tiles
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
        lat_rad = math.radians(lat)
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
    """Decodes a Terrarium RGB image into elevation in meters above sea level.
    
    Formula: height = (R * 256 + G + B / 256) - 32768
    """
    arr = np.array(rgb_img, dtype=np.float32)
    r = arr[:, :, 0]
    g = arr[:, :, 1]
    b = arr[:, :, 2]
    elevation = (r * 256.0 + g + (b / 256.0)) - 32768.0
    return elevation


def select_optimal_zoom(bbox: BoundingBox, target_samples: int = 250) -> int:
    """Selects the best Web Mercator zoom level (0 to 15) to cover bbox with target resolution."""
    lat_span = bbox.lat_span
    lon_span = bbox.lon_span
    max_span = max(lat_span, lon_span)
    
    # Target resolution: 360 degrees / (2^zoom * 256 pixels)
    # Solve for zoom such that tile span matches target samples
    for z in range(15, 0, -1):
        tile_deg = 360.0 / (2.0 ** z)
        tiles_needed = max_span / tile_deg
        total_pixels = tiles_needed * 256.0
        if total_pixels <= target_samples * 2.5:
            return min(14, max(4, z))
    return 8


def fetch_elevation_grid(bbox: BoundingBox, grid_width: int = 200, grid_depth: int = 200) -> np.ndarray:
    """Fetches and interpolates a unified M x N elevation grid (in meters) for a bounding box.
    
    Returns:
        np.ndarray of shape (grid_depth, grid_width) where row 0 is South and row -1 is North.
    """
    zoom = select_optimal_zoom(bbox, target_samples=max(grid_width, grid_depth))
    
    # Identify tile ranges covering bbox
    # In Mercator, y=0 is North, y_max is South
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
    
    # Download and assemble mosaic in parallel
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
            
    # Calculate geographic coordinates of mosaic corners
    north_lat, west_lon = tile_to_lat_lon(x_start, y_min, zoom)
    south_lat, east_lon = tile_to_lat_lon(x_end + 1, y_max + 1, zoom)
    
    # Sample target grid coordinates
    target_lons = np.linspace(bbox.west, bbox.east, grid_width)
    target_lats = np.linspace(bbox.south, bbox.north, grid_depth)
    
    # Map lat/lon to mosaic pixel float coordinates
    # Note: mosaic rows 0 to mosaic_h go from north_lat down to south_lat
    # Convert target lats/lons to normalized [0, 1] then pixel coordinates
    col_coords = (target_lons - west_lon) / (east_lon - west_lon) * (mosaic_w - 1)
    # Invert for Y because row 0 is North
    row_coords = (north_lat - target_lats) / (north_lat - south_lat) * (mosaic_h - 1)
    
    col_coords = np.clip(col_coords, 0, mosaic_w - 1)
    row_coords = np.clip(row_coords, 0, mosaic_h - 1)
    
    # Bilinear interpolation
    grid = np.zeros((grid_depth, grid_width), dtype=np.float32)
    for r in range(grid_depth):
        ry = row_coords[r]
        r0 = int(np.floor(ry))
        r1 = min(r0 + 1, mosaic_h - 1)
        dr = ry - r0
        
        for c in range(grid_width):
            cx = col_coords[c]
            c0 = int(np.floor(cx))
            c1 = min(c0 + 1, mosaic_w - 1)
            dc = cx - c0
            
            top = (1.0 - dc) * mosaic_elev[r0, c0] + dc * mosaic_elev[r0, c1]
            bot = (1.0 - dc) * mosaic_elev[r1, c0] + dc * mosaic_elev[r1, c1]
            grid[r, c] = (1.0 - dr) * top + dr * bot
            
    return grid


@dataclass
class BuildingPolygon:
    """Represents a 3D building footprint with height."""
    osm_id: int
    coordinates: List[Tuple[float, float]] # [(lat, lon), ...]
    height_meters: float
    min_height_meters: float = 0.0
    name: str = ""

    @property
    def center(self) -> Tuple[float, float]:
        """Returns centroid (lat, lon) of footprint."""
        if not self.coordinates:
            return (0.0, 0.0)
        lats = [c[0] for c in self.coordinates]
        lons = [c[1] for c in self.coordinates]
        return (sum(lats) / len(lats), sum(lons) / len(lons))


def parse_osm_height(tags: Dict[str, str]) -> float:
    """Resolves building height from OSM tags."""
    if "height" in tags:
        val = tags["height"].lower().replace("m", "").replace("meters", "").strip()
        try:
            return float(val)
        except ValueError:
            pass
            
    if "building:levels" in tags:
        try:
            levels = float(tags["building:levels"])
            return max(3.0, levels * 3.2) # ~3.2m per story
        except ValueError:
            pass
            
    # Default fallbacks
    b_type = tags.get("building", "yes").lower()
    if b_type in ("apartments", "commercial", "office"):
        return 16.0
    elif b_type in ("house", "residential", "garage"):
        return 6.0
    return 8.0 # Standard default


OVERPASS_ENDPOINTS = [
    "https://lambert.openstreetmap.de/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]


def fetch_osm_buildings(bbox: BoundingBox, max_buildings: int = 2000) -> List[BuildingPolygon]:
    """Queries OSM Overpass API for building footprints within the bounding box."""
    query = f"""
    [out:json][timeout:20];
    (
      way["building"]({bbox.south:.5f},{bbox.west:.5f},{bbox.north:.5f},{bbox.east:.5f});
    );
    out geom {max_buildings};
    """
    
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    res = None
    last_err = None
    
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            req = urllib.request.Request(endpoint, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                res = json.loads(resp.read().decode("utf-8"))
            if res and "elements" in res:
                break
        except Exception as e:
            last_err = e
            continue
            
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
        
    return buildings


def calculate_route(
    waypoints: List[Tuple[float, float]],
    profile: str = "driving"
) -> Dict[str, Any]:
    """Calculates a travel route along real roads using Open Source Routing Machine (OSRM).
    
    Args:
        waypoints: List of (lat, lon) coordinates where user placed route points.
        profile: Routing profile ('driving', 'walking', 'cycling').
        
    Returns:
        Dict with 'coordinates': [(lat, lon), ...], 'distance_m', 'duration_s', 'snapped': bool
    """
    if len(waypoints) < 2:
        return {
            "coordinates": waypoints,
            "distance_m": 0.0,
            "duration_s": 0.0,
            "snapped": False
        }
        
    # OSRM expects: {lon1},{lat1};{lon2},{lat2};...
    coords_str = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in waypoints)
    mode = "driving" if profile not in ("driving", "walking", "cycling") else profile
    url = f"https://router.project-osrm.org/route/v1/{mode}/{coords_str}?overview=full&geometries=geojson"
    
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            
        if data.get("code") == "Ok" and "routes" in data and len(data["routes"]) > 0:
            route = data["routes"][0]
            # GeoJSON coordinates are [lon, lat]
            geojson_pts = route["geometry"]["coordinates"]
            # Convert to [lat, lon] tuples
            route_coords = [(pt[1], pt[0]) for pt in geojson_pts]
            return {
                "coordinates": route_coords,
                "distance_m": route.get("distance", 0.0),
                "duration_s": route.get("duration", 0.0),
                "snapped": True
            }
    except Exception as e:
        sys.stderr.write(f"[WARN] OSRM routing failed ({e}), falling back to direct straight line.\n")
        
    # Graceful fallback: direct straight lines
    return {
        "coordinates": waypoints,
        "distance_m": 0.0,
        "duration_s": 0.0,
        "snapped": False,
        "fallback": True
    }

