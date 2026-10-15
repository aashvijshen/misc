"""Urban Block & Street Network Relief Engine for MapMaker 3D.

Partitions geographic areas into tactile city blocks and settlement parcels
separated by recessed printable street network channels, supporting dense cities,
suburbs, and rural villages across all scales.
"""

import os
import sys
import math
import hashlib
import urllib.request
import urllib.parse
import json
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any, Optional
import io
from PIL import Image

import numpy as np
import shapely.geometry as sg
import shapely.ops as so
from shapely.validation import make_valid

from .config import BoundingBox
from .geo import fetch_elevation_grid, fetch_map_texture, _is_cache_fresh

CACHE_DIR = os.path.expanduser("~/.cache/mapmaker3d")
OVERPASS_CACHE_DIR = os.path.join(CACHE_DIR, "overpass")
USER_AGENT = "MapMaker3D/1.0 (3D printing CAD engine; https://github.com/aashvij/mapmaker3d)"
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://lambert.openstreetmap.de/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]


@dataclass
class UrbanBlock:
    """Represents a tactile extruded urban block or settlement parcel."""
    block_id: str
    coordinates: List[Tuple[float, float]]  # [(lat, lon), ...] exterior ring
    height_mm: float
    area_sq_m: float
    is_arterial: bool
    center: Tuple[float, float]  # (centroid_lat, centroid_lon)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.block_id,
            "coordinates": self.coordinates,
            "height_mm": round(self.height_mm, 2),
            "area_sq_m": round(self.area_sq_m, 1),
            "is_arterial": self.is_arterial,
            "center": [round(self.center[0], 5), round(self.center[1], 5)]
        }


def _get_hash_unit(seed_str: str) -> float:
    """Returns a deterministic pseudo-random float in [0.0, 1.0] from a string key."""
    h = hashlib.md5(seed_str.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xffffffff


def _is_water_pixel(rgb: Tuple[int, int, int]) -> bool:
    """Detects if an RGB pixel from the standard OSM Carto map texture is water."""
    r, g, b = rgb
    # 1. Standard open water / river / ocean / bay / canal (cyan/blue, e.g. #aad3df, #a5c9d7, #8da5c9)
    if (b > r + 8 and g > r + 8):
        return True
    # 2. Saturated blue / harbor / reservoir
    if (b > 175 and b > r + 15):
        return True
    # 3. Deep / shadowed water
    if r < 135 and b > r + 6 and g > r + 4:
        return True
    return False


def _is_green_nature_pixel(rgb: Tuple[int, int, int]) -> bool:
    """Detects if an RGB pixel from the standard OSM Carto map texture is natural
    vegetation, forest, national park, nature reserve, or open mountain landscape.
    """
    r, g, b = rgb
    # 1. Forest, woodland, national parks, nature reserves (#c8d7ab, #aed1a0, #b5e2b0)
    if (g > r + 10 and g > b + 4):
        return True
    # 2. Vivid park / meadow green
    if (g > 190 and r < 200 and b < 200 and g > r + 6):
        return True
    return False


def _fetch_overpass_cached(
    query: str,
    force_refresh: bool = False,
    max_age_days: int = 30
) -> Optional[Dict[str, Any]]:
    """Fetches OSM Overpass query with automatic local disk caching and TTL expiration."""
    os.makedirs(OVERPASS_CACHE_DIR, exist_ok=True)
    q_hash = hashlib.md5(query.encode("utf-8")).hexdigest()
    cache_file = os.path.join(OVERPASS_CACHE_DIR, f"{q_hash}.json")
    if not force_refresh and _is_cache_fresh(cache_file, max_age_days):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded"
    }

    res = None
    last_err = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            req = urllib.request.Request(endpoint, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=22) as resp:
                res = json.loads(resp.read().decode("utf-8"))
            if res and "elements" in res:
                break
        except Exception as e:
            last_err = e
            continue

    if res and "elements" in res:
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(res, f)
        except Exception:
            pass
        return res

    # Resilient offline fallback if cached file exists
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    sys.stderr.write(f"[WARN] Overpass street query failed ({last_err}), returning empty blocks.\n")
    return None


def fetch_urban_blocks(
    bbox: BoundingBox,
    canvas_w_mm: float = 250.0,
    canvas_d_mm: float = 250.0,
    groove_w_mm: float = 1.2,
    min_h_mm: float = 2.0,
    max_h_mm: float = 6.0,
    force_refresh: bool = False
) -> List[UrbanBlock]:
    """Fetches OSM highways and open spaces, partitioning the terrain into
    tactile extruded blocks separated by printable street channels.
    """
    lat_span = max(1e-5, bbox.lat_span)
    lon_span = max(1e-5, bbox.lon_span)
    max_span = max(lat_span, lon_span)

    # 1. Tiered Highway Level-of-Detail (LOD)
    # Calibrated to 3D print line width & real-world road spacing:
    # At local scale (<= ~10 km), residential streets separate fine-grained parcel blocks.
    # At city/metro scale (> 10 km), using residential alleys causes adjacent 1.2mm grooves
    # to overlap and destroy suburban sectors (e.g. Uttarahalli); using arterial & collector
    # roads preserves continuous urban super-blocks across all neighborhoods without gaps.
    if max_span <= 0.09:
        # Neighborhood / village / town scale (<= ~10 km): include residential and local roads
        hw_filter = "motorway|trunk|primary|secondary|tertiary|residential|unclassified|living_street"
    elif max_span <= 0.40:
        # City / metro scale (10 km - 45 km): arterial corridors & collector network
        hw_filter = "motorway|trunk|primary|secondary|tertiary"
    else:
        # Regional scale (> 45 km): major arterial network
        hw_filter = "motorway|trunk|primary|secondary"

    overpass_query = f"""
    [out:json][timeout:25];
    (
      way["highway"~"{hw_filter}"]({bbox.south:.5f},{bbox.west:.5f},{bbox.north:.5f},{bbox.east:.5f});
      way["leisure"~"park|marina"]({bbox.south:.5f},{bbox.west:.5f},{bbox.north:.5f},{bbox.east:.5f});
      way["natural"~"water|bay"]({bbox.south:.5f},{bbox.west:.5f},{bbox.north:.5f},{bbox.east:.5f});
      way["waterway"~"riverbank|dock|canal"]({bbox.south:.5f},{bbox.west:.5f},{bbox.north:.5f},{bbox.east:.5f});
      way["water"]({bbox.south:.5f},{bbox.west:.5f},{bbox.north:.5f},{bbox.east:.5f});
      way["landuse"="reservoir"]({bbox.south:.5f},{bbox.west:.5f},{bbox.north:.5f},{bbox.east:.5f});
    );
    out geom;
    """

    res = _fetch_overpass_cached(overpass_query, force_refresh=force_refresh)
    if res is None:
        return []

    elements = res.get("elements", [])
    if not elements:
        return []

    # Pre-fetch map texture raster mask (target_size=1024 provides high-fidelity river & canal resolution)
    tex_img = None
    try:
        tex_bytes = fetch_map_texture(bbox, target_size=1024, force_refresh=force_refresh)
        tex_img = Image.open(io.BytesIO(tex_bytes)).convert("RGB")
    except Exception as e:
        sys.stderr.write(f"[DEBUG] Map texture raster mask unavailable: {e}\n")

    # 2. Compute minimum printable street buffer in geographic degrees
    # Target minimum nozzle clearance on bed (groove_w_mm)
    deg_per_mm_y = lat_span / max(10.0, canvas_d_mm)
    deg_per_mm_x = lon_span / max(10.0, canvas_w_mm)
    avg_deg_per_mm = (deg_per_mm_y + deg_per_mm_x) / 2.0

    # Scale-bounded road buffer:
    # At regional / metro scales, clamp physical road buffer half-width to <= 20 meters
    # so road grooves never overlap and obliterate dense city blocks (e.g. Manhattan).
    max_buffer_deg = 20.0 / 111139.0
    base_buffer_deg = min(max_buffer_deg, (groove_w_mm / 2.0) * avg_deg_per_mm)

    road_polys = []
    park_water_polys = []

    for el in elements:
        geom = el.get("geometry", [])
        if len(geom) < 2:
            continue

        pts = [(pt["lon"], pt["lat"]) for pt in geom]
        tags = el.get("tags", {})
        hw_type = tags.get("highway", "")

        if hw_type:
            # Scale buffer slightly for major freeways vs street network
            if hw_type in ("motorway", "trunk"):
                buf = base_buffer_deg * 1.35
            else:
                buf = base_buffer_deg

            line = sg.LineString(pts)
            road_polys.append(line.buffer(buf, cap_style=sg.CAP_STYLE.flat, join_style=sg.JOIN_STYLE.mitre))

        elif (
            tags.get("leisure") in ("park", "marina")
            or tags.get("natural") in ("water", "bay")
            or tags.get("waterway") in ("riverbank", "dock", "canal")
            or "water" in tags
            or tags.get("landuse") == "reservoir"
        ):
            if len(pts) >= 3:
                try:
                    poly = sg.Polygon(pts)
                    if poly.is_valid:
                        park_water_polys.append(poly)
                    else:
                        poly = poly.buffer(0)
                        if poly.is_valid and not poly.is_empty:
                            park_water_polys.append(poly)
                except Exception:
                    pass

    # 3. Planar Inversion / Boolean Difference
    bbox_poly = sg.box(bbox.west, bbox.south, bbox.east, bbox.north)
    all_recessed = []
    if road_polys:
        all_recessed.extend(road_polys)
    if park_water_polys:
        all_recessed.extend(park_water_polys)

    if not all_recessed:
        return []

    recessed_union = so.unary_union(all_recessed)
    diff = bbox_poly.difference(recessed_union)

    if diff.is_empty:
        return []

    candidate_polys = []
    if isinstance(diff, sg.Polygon):
        candidate_polys = [diff]
    elif isinstance(diff, sg.MultiPolygon):
        candidate_polys = list(diff.geoms)
    elif hasattr(diff, "geoms"):
        candidate_polys = [g for g in diff.geoms if isinstance(g, sg.Polygon)]

    total_bbox_area = bbox_poly.area
    # Minimum physical area threshold (~4 printable nozzle widths square) to eliminate slivers
    min_area_deg2 = (base_buffer_deg * 2.0) ** 2

    # Approximate meter conversion at this latitude
    mid_lat = (bbox.south + bbox.north) / 2.0
    cos_lat = math.cos(math.radians(mid_lat))
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * cos_lat

    # Sample coarse DEM elevation grid to detect sea-level water bodies (ocean, bays, sounds)
    elev_grid = None
    has_ocean = False
    try:
        elev_grid = fetch_elevation_grid(bbox, grid_width=128, grid_depth=128)
        if elev_grid is not None and float(np.min(elev_grid)) <= 0.0:
            has_ocean = True
    except Exception as e:
        sys.stderr.write(f"[DEBUG] DEM water grid lookup skipped: {e}\n")

    blocks = []
    for idx, poly in enumerate(candidate_polys):
        if poly.is_empty or not poly.is_valid:
            poly = poly.buffer(0)
            if poly.is_empty or not isinstance(poly, sg.Polygon):
                continue

        p_area = poly.area
        if p_area < min_area_deg2:
            continue  # Sub-printable nozzle artifact

        # Simplify coordinates to eliminate sub-micron redundant vertices
        simpl_tol = base_buffer_deg * 0.15
        simpl_poly = poly.simplify(simpl_tol, preserve_topology=True)
        if not isinstance(simpl_poly, sg.Polygon) or simpl_poly.is_empty:
            simpl_poly = poly

        # Centroid
        c = simpl_poly.centroid
        c_lat, c_lon = c.y, c.x

        # Calculate real-world area in square meters and square kilometers
        area_sq_m = p_area * (m_per_deg_lat * m_per_deg_lon)
        area_sq_km = area_sq_m / 1e6

        # Water & Wilderness exclusion:
        # 1. Any parcel > 4.0 sq km (or > 3.0% of total bbox area) is open water, sound, bay, or unbuilt regional wilderness tract
        if area_sq_km > 4.0 or p_area > 0.030 * total_bbox_area:
            continue

        # 2. Cartographic Raster Water & Nature Masks:
        # Direct pixel-level verification against OSM pre-rendered geography
        if tex_img is not None:
            img_w, img_h = tex_img.size
            # Multi-point raster sampling: centroid, representative point, and interior grid samples
            sample_pts = [simpl_poly.centroid, simpl_poly.representative_point()]
            minx, miny, maxx, maxy = simpl_poly.bounds
            for gx in np.linspace(minx, maxx, 4):
                for gy in np.linspace(miny, maxy, 4):
                    q_pt = sg.Point(gx, gy)
                    if simpl_poly.contains(q_pt):
                        sample_pts.append(q_pt)

            water_count = 0
            green_nature_count = 0
            for spt in sample_pts:
                px = max(0, min(img_w - 1, int(round((spt.x - bbox.west) / max(1e-6, lon_span) * (img_w - 1)))))
                py = max(0, min(img_h - 1, int(round((bbox.north - spt.y) / max(1e-6, lat_span) * (img_h - 1)))))
                rgb = tex_img.getpixel((px, py))
                if _is_water_pixel(rgb):
                    water_count += 1
                if _is_green_nature_pixel(rgb):
                    green_nature_count += 1

            # Water exclusion: if >= 15% of interior points detect water, or any water point for parcels > 0.05 sq km
            if water_count >= max(1, len(sample_pts) * 0.15) or (area_sq_km > 0.05 and water_count >= 1):
                continue

            # Nature & Wilderness exclusion:
            # Exclude parcels identified as forests, woodlands, national parks, or nature reserves
            # (e.g. Kudremukh, mountain slopes, Central Park, Presidio)
            if green_nature_count >= len(sample_pts) / 2.0 or (area_sq_km > 0.05 and green_nature_count >= 1):
                continue

        # 3. Coastal sea-level DEM filter:
        # In coastal areas (min elev <= 0m), blocks at or below sea-level (<= 1.5m for parcels > 0.05 sq km, or <= 0m)
        # are open water bodies (bays, sounds, harbors, rivers) and should not be extruded.
        if has_ocean and elev_grid is not None:
            grid_h, grid_w = elev_grid.shape
            r = int(round((c_lat - bbox.south) / max(1e-6, lat_span) * (grid_h - 1)))
            c_idx = int(round((c_lon - bbox.west) / max(1e-6, lon_span) * (grid_w - 1)))
            r = max(0, min(grid_h - 1, r))
            c_idx = max(0, min(grid_w - 1, c_idx))
            elev_m = float(elev_grid[r, c_idx])
            if elev_m <= 0.0 or (elev_m <= 1.5 and area_sq_km > 0.05):
                continue

        ext_coords = list(simpl_poly.exterior.coords)
        if len(ext_coords) < 3:
            continue

        # Invert from (lon, lat) to (lat, lon) for MapMaker / Leaflet format
        coords_lat_lon = [(pt[1], pt[0]) for pt in ext_coords]

        # Height Assignment: pure stochastic variation within user range [min_h_mm, max_h_mm]
        hash_seed = f"block_{c_lat:.5f}_{c_lon:.5f}_{idx}"
        r_unit = _get_hash_unit(hash_seed)
        h_mm = min_h_mm + r_unit * (max_h_mm - min_h_mm)
        h_mm = max(1.0, min(30.0, h_mm))

        blocks.append(UrbanBlock(
            block_id=f"blk_{idx}",
            coordinates=coords_lat_lon,
            height_mm=h_mm,
            area_sq_m=area_sq_m,
            is_arterial=False,
            center=(c_lat, c_lon)
        ))

    return blocks
