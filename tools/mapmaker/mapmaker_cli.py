#!/usr/bin/env python3
"""MapMaker 3D: Unified Command Line Tool for 3D Printable Terrain Models.

Fetches real-world elevation, 3D buildings, partitions oversized canvases
into Bambu Lab A1 printable bed tiles, and generates subterranean biscuit joints.
"""

import os
import sys
import argparse
import numpy as np

# Ensure UTF-8 console output on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure mapmaker directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from engine.config import MapMakerConfig, CanvasConfig, BoundingBox
from engine.geo import geocode_location, fetch_elevation_grid, fetch_osm_buildings
from engine.mesh import generate_terrain_mesh, extrude_building_mesh
from engine.tiling import TilingEngine


def main():
    parser = argparse.ArgumentParser(
        description="MapMaker 3D: Generate precision 3D-printable terrain models."
    )
    parser.add_argument("--location", type=str, help="Location query (e.g., 'Mount Fuji', 'Manhattan')")
    parser.add_argument("--bbox", type=str, help="Bounding box as south,west,north,east")
    parser.add_argument("--width", type=float, default=250.0, help="Canvas physical width in mm (default: 250mm)")
    parser.add_argument("--depth", type=float, default=250.0, help="Canvas physical depth in mm (default: 250mm)")
    parser.add_argument("--base-height", type=float, default=4.0, help="Solid base slab height in mm (default: 4.0mm)")
    parser.add_argument("--vertical-scale", type=float, default=2.0, help="Z elevation scale multiplier (default: 2.0x)")
    parser.add_argument("--target-height", type=float, default=None, help="Target maximum relief height in mm")
    parser.add_argument("--no-topography", action="store_true", help="Generate flat 2D map slab without elevation")
    parser.add_argument("--buildings", action="store_true", default=False, help="Fetch and extrude 3D OSM buildings")
    parser.add_argument("--building-scale", type=float, default=1.0, help="Multiplier for building heights")
    parser.add_argument("--no-dowels", action="store_true", help="Disable subterranean alignment biscuit joints")
    parser.add_argument("--output", type=str, default="./mapmaker_output", help="Output directory")

    args = parser.parse_args()

    if not args.location and not args.bbox:
        parser.error("Must specify either --location or --bbox")

    os.makedirs(args.output, exist_ok=True)

    print("==================================================")
    print("           MAPMAKER 3D TERRAIN GENERATOR          ")
    print("==================================================")

    # 1. Resolve Geographic Extent
    if args.location:
        print(f"[*] Geocoding query: '{args.location}'...")
        geo_res = geocode_location(args.location)
        bbox = geo_res["bbox"]
        location_name = geo_res["display_name"]
        print(f"    Resolved: {location_name}")
        print(f"    Coordinates: Lat {geo_res['lat']:.4f}, Lon {geo_res['lon']:.4f}")
    else:
        parts = [float(p.strip()) for p in args.bbox.split(",")]
        bbox = BoundingBox(south=parts[0], west=parts[1], north=parts[2], east=parts[3])
        location_name = f"Custom Bounds ({bbox.south:.3f}, {bbox.west:.3f})"

    print(f"    Bounding Box: South={bbox.south:.4f}, West={bbox.west:.4f}, North={bbox.north:.4f}, East={bbox.east:.4f}")

    # 2. Build Project Configuration
    config = MapMakerConfig(
        canvas=CanvasConfig(
            width_mm=args.width,
            depth_mm=args.depth,
            base_height_mm=args.base_height,
            topography_enabled=not args.no_topography,
            vertical_exaggeration=args.vertical_scale,
            target_relief_height_mm=args.target_height,
            buildings_enabled=args.buildings,
            building_height_scale=args.building_scale
        ),
        bbox=bbox,
        location_name=location_name
    )
    if args.no_dowels:
        config.dowel.enabled = False

    tiling_engine = TilingEngine(config)
    cols, rows = tiling_engine.cols, tiling_engine.rows
    print(f"\n[*] Canvas: {args.width:.1f} x {args.depth:.1f} mm | Tiling Matrix: {cols} Cols x {rows} Rows ({len(tiling_engine.slices)} tiles)")

    # 3. Fetch Elevation Data
    grid_res = 120 * max(cols, rows)
    grid_w = min(400, grid_res)
    grid_d = min(400, grid_res)
    print(f"\n[*] Fetching AWS Terrarium elevation tiles ({grid_w}x{grid_d} grid)...")
    elev_grid = fetch_elevation_grid(bbox, grid_width=grid_w, grid_depth=grid_d)
    min_elev = float(np.min(elev_grid))
    max_elev = float(np.max(elev_grid))
    print(f"    Elevation Range: {min_elev:.1f} m to {max_elev:.1f} m (Delta: {max_elev - min_elev:.1f} m)")

    # 4. Optional: Fetch Buildings
    if args.buildings:
        print(f"\n[*] Fetching OSM building footprints for urban structures...")
        try:
            buildings = fetch_osm_buildings(bbox, max_buildings=1500)
            print(f"    Found {len(buildings)} building footprints.")
        except Exception as e:
            print(f"    WARNING: Could not fetch buildings: {e}")
            buildings = []
    else:
        buildings = []

    # 5. Partition Canvas & Export Deliverables
    print(f"\n[*] Partitioning canvas and solidifying 3D meshes...")
    manifest = tiling_engine.process_and_export_all(elev_grid, args.output)

    print("\n==================================================")
    print("                GENERATION COMPLETE               ")
    print("==================================================")
    print(f"Tiles Output Directory: {os.path.join(args.output, 'tiles')}")
    for t in manifest["tiles"]:
        print(f"  - {t['filename']}: {t['width_mm']:.1f} x {t['depth_mm']:.1f} x {t['height_mm']:.1f} mm ({t['file_size_bytes']} bytes)")

    if manifest["biscuits"]["total_count"] > 0:
        print(f"Alignment Biscuits: {manifest['biscuits']['path']} ({manifest['biscuits']['total_count']} biscuits in batch)")

    print(f"Assembly Guide: {manifest['assembly_guide']}")
    print("All deliverables ready for slicing in Bambu Studio!")


if __name__ == "__main__":
    main()
