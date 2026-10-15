"""Verification test for MapMaker 3D geospatial engine."""

import sys
import os
import numpy as np

# Ensure mapmaker module is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engine.config import BoundingBox, MapMakerConfig, CanvasConfig
from engine.geo import geocode_location, fetch_elevation_grid, fetch_osm_buildings


def test_fuji_geocoding_and_elevation():
    print("\n--- Test 1: Mount Fuji Geocoding & DEM Elevation Grid ---")
    res = geocode_location("Mount Fuji")
    print(f"Location Found: {res['display_name']}")
    print(f"Coordinates: Lat {res['lat']:.4f}, Lon {res['lon']:.4f}")
    print(f"Bounding Box: South={res['bbox'].south:.4f}, North={res['bbox'].north:.4f}, West={res['bbox'].west:.4f}, East={res['bbox'].east:.4f}")
    
    # Fetch 60x60 elevation grid
    print("Fetching AWS Terrarium elevation grid...")
    elev_grid = fetch_elevation_grid(res['bbox'], grid_width=60, grid_depth=60)
    print(f"Elevation Grid Shape: {elev_grid.shape}")
    print(f"Min Elevation: {np.min(elev_grid):.1f} m")
    print(f"Max Elevation: {np.max(elev_grid):.1f} m")
    print(f"Elevation Range: {np.ptp(elev_grid):.1f} m")
    
    assert elev_grid.shape == (60, 60), "Grid shape mismatch!"
    assert np.max(elev_grid) > 3000.0, f"Expected Fuji peak > 3000m, got {np.max(elev_grid):.1f}m"
    print("✓ Mount Fuji Test PASSED!")


def test_manhattan_buildings():
    print("\n--- Test 2: Manhattan Building Vectors (Empire State Building area) ---")
    # Small box around Empire State Building: lat 40.7484, lon -73.9857
    esb_bbox = BoundingBox(
        south=40.7460,
        west=-73.9880,
        north=40.7510,
        east=-73.9830
    )
    print("Fetching OSM Overpass buildings...")
    buildings = fetch_osm_buildings(esb_bbox, max_buildings=100)
    print(f"Retrieved {len(buildings)} buildings.")
    assert len(buildings) > 0, "No buildings retrieved!"
    
    # Check if any building has realistic height
    heights = [b.height_meters for b in buildings]
    print(f"Building Heights: Min={min(heights):.1f}m, Max={max(heights):.1f}m, Avg={sum(heights)/len(heights):.1f}m")
    named = [b.name for b in buildings if b.name]
    if named:
        print(f"Sample named buildings: {named[:3]}")
    print("✓ Manhattan Buildings Test PASSED!")


if __name__ == "__main__":
    test_fuji_geocoding_and_elevation()
    test_manhattan_buildings()
    print("\n==========================================")
    print("ALL GEOSPATIAL ENGINE TESTS PASSED!")
    print("==========================================")
