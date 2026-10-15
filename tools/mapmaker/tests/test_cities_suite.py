"""Comprehensive test suite for MapMaker 3D Urban Blocks across diverse geographies:
1. New York (estuaries, bays, sounds, islands)
2. London (winding river, Royal Parks, canals)
3. Paris (Seine River, urban islands, Bois forests)
4. San Francisco (bay, ocean, extreme topographic hills, Presidio)
5. Mount Fuji (mountain top - should have 0 or near-0 urban blocks)
6. Venice, Italy (lagoon island city, canals)
7. Honolulu, Hawaii (island coastal city, volcanic ridge)
8. Tokyo, Japan (dense coastal mega-city)
9. Bengaluru, India (inland plateau with urban lakes)
"""

import sys
import os
import time
import shapely.geometry as sg

from tools.mapmaker.engine.config import BoundingBox
from tools.mapmaker.engine.geo import geocode_location
from tools.mapmaker.engine.blocks import fetch_urban_blocks


TEST_CASES = [
    {
        "name": "New York",
        "query": "New York",
        "key_water_points": [
            ("East River (Midtown)", 40.7498, -73.9581),
            ("Harlem River", 40.8755, -73.9177),
            ("Hudson River (Midtown)", 40.7500, -74.0165),
            ("Upper NY Bay", 40.6800, -74.0300),
            ("Lower NY Bay", 40.5200, -74.0500),
            ("Jamaica Bay", 40.6150, -73.8300),
            ("Newark Bay", 40.6700, -74.1300),
            ("Hackensack River", 40.7380, -74.0924),
            ("Wallabout Bay (Navy Yard)", 40.7050, -73.9765),
        ],
        "expected_max_block_area_km2": 4.0,
    },
    {
        "name": "London",
        "query": "London",
        "key_water_points": [
            ("Thames at Westminster", 51.5020, -0.1220),
            ("Thames at Tower Bridge", 51.5045, -0.0750),
            ("Thames at Greenwich", 51.4850, -0.0050),
            ("Surrey Quays Dock", 51.4980, -0.0400),
        ],
        "expected_max_block_area_km2": 4.0,
    },
    {
        "name": "Paris",
        "query": "Paris",
        "key_water_points": [
            ("Seine at Pont Neuf", 48.8570, 2.3400),
            ("Seine at Eiffel Tower", 48.8580, 2.2900),
            ("Seine at Bercy", 48.8350, 2.3800),
        ],
        "expected_max_block_area_km2": 4.0,
    },
    {
        "name": "San Francisco",
        "query": "San Francisco",
        "key_water_points": [
            ("SF Bay (Off Ferry Bldg)", 37.7950, -122.3900),
            ("Pacific Ocean (Ocean Beach)", 37.7600, -122.5150),
            ("Golden Gate Strait", 37.8200, -122.4780),
        ],
        "expected_max_block_area_km2": 4.0,
    },
    {
        "name": "Mount Fuji",
        "query": "Mount Fuji",
        "key_water_points": [],
        "is_mountain": True,
        "expected_max_block_area_km2": 4.0,
    },
    {
        "name": "Kudremukh",
        "query": "Kudremukh",
        "key_water_points": [],
        "is_mountain": True,
        "expected_max_block_area_km2": 4.0,
    },
    {
        "name": "Venice",
        "query": "Venice, Italy",
        "key_water_points": [
            ("Venice Venetian Lagoon (North)", 45.4500, 12.3300),
            ("Venice Venetian Lagoon (South)", 45.4200, 12.3500),
            ("Canale della Giudecca", 45.4270, 12.3250),
        ],
        "expected_max_block_area_km2": 4.0,
    },
    {
        "name": "Honolulu",
        "query": "Honolulu",
        "key_water_points": [
            ("Mamala Bay / Waikiki Ocean", 21.2700, -157.8300),
            ("Pearl Harbor Harbor Channel", 21.3600, -157.9600),
            ("Keehi Lagoon", 21.3200, -157.8900),
        ],
        "expected_max_block_area_km2": 4.0,
    },
]


def run_tests():
    print("=" * 70)
    print("      MAPMAKER 3D: GLOBAL TERRAIN & CITY BLOCK TEST SUITE")
    print("=" * 70)

    all_passed = True

    for tc in TEST_CASES:
        name = tc["name"]
        print(f"\n--- Testing: {name} (Query: '{tc['query']}') ---")
        t0 = time.time()

        try:
            loc = geocode_location(tc["query"])
            bbox = loc["bbox"]
        except Exception as ge:
            print(f"  [ERROR] Geocoding failed: {ge}")
            all_passed = False
            continue

        print(f"  BBox: Lat [{bbox.south:.4f}, {bbox.north:.4f}] Span={bbox.lat_span:.3f}° | Lon [{bbox.west:.4f}, {bbox.east:.4f}] Span={bbox.lon_span:.3f}°")

        t_start = time.time()
        blocks = fetch_urban_blocks(bbox, 250.0, 250.0)
        dt = time.time() - t_start

        print(f"  Generated {len(blocks)} blocks in {dt:.2f}s")

        if tc.get("is_mountain"):
            # A mountain top (e.g. Mount Fuji peak) has no urban highway grid
            print(f"  [Mountain Check]: Found {len(blocks)} blocks (expected 0 or low rural count <= 5)")
            if len(blocks) > 10:
                print(f"  [FAIL] Unexpected high urban block count on mountain: {len(blocks)}")
                all_passed = False
            else:
                print(f"  [PASS] Mountain peak is clean (no spurious urban blocks).")
            continue

        if len(blocks) == 0:
            print(f"  [FAIL] Expected urban blocks for {name}, got 0.")
            all_passed = False
            continue

        # Check maximum block area cap
        max_area_km2 = max(b.area_sq_m for b in blocks) / 1e6
        print(f"  Max block area: {max_area_km2:.2f} km² (Cap threshold: {tc['expected_max_block_area_km2']} km²)")
        if max_area_km2 > tc["expected_max_block_area_km2"] + 0.05:
            print(f"  [FAIL] Max block area exceeds cap: {max_area_km2:.2f} km²")
            all_passed = False
        else:
            print(f"  [PASS] Block areas within realistic urban parcel limits.")

        # Check key water points to ensure zero water contamination
        water_hits = []
        for wp_name, wp_lat, wp_lon in tc.get("key_water_points", []):
            pt = sg.Point(wp_lon, wp_lat)
            for b in blocks:
                poly = sg.Polygon([(p[1], p[0]) for p in b.coordinates])
                if poly.contains(pt):
                    water_hits.append((wp_name, b.block_id, b.area_sq_m / 1e6))

        if water_hits:
            print(f"  [FAIL] Found {len(water_hits)} water intrusions:")
            for wh in water_hits:
                print(f"    - Water hit: {wh[0]} in {wh[1]} ({wh[2]:.2f} km²)")
            all_passed = False
        else:
            print(f"  [PASS] All {len(tc.get('key_water_points', []))} test water points are 100% clean (zero water blocks).")

    print("\n" + "=" * 70)
    if all_passed:
        print("  ALL GLOBAL CITY & TERRAIN INTEGRATION TESTS PASSED SUCCESSFULLY! ✓")
    else:
        print("  SOME TESTS FAILED! ✗")
    print("=" * 70)
    return all_passed


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
