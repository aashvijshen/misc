#!/usr/bin/env python3
"""MapMaker 3D: Unified Command Line Tool for Display-Grade 3D Printable Locations.

Supports global places, coastlines/borders, GPX/KML/GeoJSON marathon & climb tracks,
hiking/cycling/driving routing, visited landmark pins, street-grid urban blocks,
real 3D OSM buildings, wall-hanging keyholes, shadowbox frames, 3D embossed title plaques,
and multi-part Bambu Studio .3mf exports.
"""

import os
import sys
import argparse
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from engine.config import MapMakerConfig, CanvasConfig, PrinterProfile, BoundingBox
from engine.geo import geocode_location, fetch_elevation_grid, calculate_route, parse_gps_track
from engine.tiling import TilingEngine


def main():
    parser = argparse.ArgumentParser(
        description="MapMaker 3D: Generate display-grade 3D-printable location & route memorabilia."
    )
    parser.add_argument("--location", type=str, help="Location query (e.g., 'Mount Fuji', 'India', 'Manhattan')")
    parser.add_argument("--bbox", type=str, help="Bounding box as south,west,north,east")
    parser.add_argument("--gpx", type=str, help="Path to .gpx, .kml, or .geojson track file (Strava/Garmin/AllTrails)")
    parser.add_argument("--width", type=float, default=250.0, help="Canvas physical width (or longest side when locked) in mm")
    parser.add_argument("--depth", type=float, default=None, help="Canvas physical depth in mm (auto-proportioned if omitted)")
    parser.add_argument("--no-aspect-lock", action="store_true", help="Disable automatic geographic aspect-ratio lock")
    parser.add_argument("--base-shape", type=str, default="rectangle",
                        choices=["rectangle", "circle", "ellipse", "polygon", "natural_border"],
                        help="Base perimeter shape")
    parser.add_argument("--base-sides", type=int, default=6, help="Polygon sides when --base-shape=polygon")
    parser.add_argument("--rotation", type=float, default=0.0, help="Map rotation angle in degrees (0-360)")
    parser.add_argument("--base-height", type=float, default=4.0, help="Solid base slab height in mm (default: 4.0mm)")
    parser.add_argument("--vertical-scale", type=float, default=2.0, help="Z elevation scale multiplier (default: 2.0x)")
    parser.add_argument("--target-height", type=float, default=25.0, help="Target relief height in mm (set 0 to use --vertical-scale)")
    parser.add_argument("--no-topography", action="store_true", help="Generate flat 2D map slab without elevation")
    parser.add_argument("--depress-water", action="store_true", default=True, help="Step land up +0.84mm above sea/water level")
    parser.add_argument("--no-depress-water", action="store_false", dest="depress_water", help="Disable coastline water step")
    parser.add_argument("--blocks", action="store_true", default=False, help="Extrude tactile urban blocks & street grid")
    parser.add_argument("--buildings", action="store_true", default=False, help="Extrude real 3D OSM buildings & skyscrapers")
    parser.add_argument("--building-scale", type=float, default=1.2, help="Multiplier for 3D building heights")
    parser.add_argument("--waypoints", type=str, default="", help="Semicolon-separated lat,lon waypoints (e.g. '35.394,138.732;35.362,138.730')")
    parser.add_argument("--route-mode", type=str, default="hiking", choices=["hiking", "cycling", "driving", "direct"],
                        help="Routing profile when --waypoints is used")
    parser.add_argument("--path-style", type=str, default="flat_strip", choices=["flat_strip", "raised_ridge"],
                        help="'flat_strip' (snap-in inlay + trench) or 'raised_ridge' (sculpted trail)")
    parser.add_argument("--pins", type=str, default="", help="Semicolon-separated place names or 'Name:lat,lon' to pin")
    parser.add_argument("--orientation", type=str, default="tabletop", choices=["tabletop", "wall_hanging"],
                        help="Display orientation ('wall_hanging' embeds rear keyhole hanger)")
    parser.add_argument("--frame", action="store_true", default=False, help="Add raised shadowbox gallery frame")
    parser.add_argument("--title", type=str, default="", help="3D embossed title plaque text (e.g. 'MOUNT FUJI')")
    parser.add_argument("--subtitle", type=str, default="", help="3D embossed subtitle / stats text (e.g. '3,776 M • JAPAN')")
    parser.add_argument("--bed-size", type=float, default=256.0, help="Printer physical bed width/depth in mm (default: 256mm Bambu A1)")
    parser.add_argument("--no-dowels", action="store_true", help="Disable subterranean alignment biscuit joints")
    parser.add_argument("--output", type=str, default="./mapmaker_output", help="Output directory")

    args = parser.parse_args()

    if not args.location and not args.bbox and not args.gpx:
        parser.error("Must specify at least one of --location, --bbox, or --gpx")

    os.makedirs(args.output, exist_ok=True)

    print("==================================================")
    print("       MAPMAKER 3D MEMORABILIA GENERATOR          ")
    print("==================================================")

    boundary_geojson = None
    path_waypoints = []
    landmarks = []
    title_text = args.title
    subtitle_text = args.subtitle

    # 1. Optional GPX / KML / GeoJSON Track Load
    track_bbox = None
    track_title = ""
    if args.gpx:
        print(f"[*] Loading GPS track: '{args.gpx}'...")
        with open(args.gpx, "r", encoding="utf-8") as f:
            t_res = parse_gps_track(f.read(), filename=args.gpx)
        path_waypoints = t_res["coordinates"]
        tb = t_res["bbox"]
        track_bbox = BoundingBox(south=tb["south"], west=tb["west"], north=tb["north"], east=tb["east"])
        track_title = t_res["name"]
        if not title_text:
            title_text = t_res["suggested_title"]
        if not subtitle_text:
            subtitle_text = t_res["suggested_subtitle"]
        landmarks.extend([t_res["start_point"], t_res["finish_point"]])
        print(f"    Track '{track_title}': {t_res['distance_km']} km (+{t_res['elevation_gain_m']}m gain, {t_res['point_count']} pts)")

    # 2. Resolve Geographic Extent
    if args.location:
        print(f"[*] Geocoding query: '{args.location}'...")
        geo_res = geocode_location(args.location, fetch_polygon=True)
        bbox = geo_res["bbox"]
        boundary_geojson = geo_res.get("geojson")
        location_name = geo_res["display_name"]
        print(f"    Resolved: {location_name}")
    elif args.bbox:
        parts = [float(p.strip()) for p in args.bbox.split(",")]
        bbox = BoundingBox(south=parts[0], west=parts[1], north=parts[2], east=parts[3])
        location_name = title_text or f"Custom Bounds ({bbox.south:.3f}, {bbox.west:.3f})"
    else:
        bbox = track_bbox
        location_name = track_title or "GPS Track Route"

    print(f"    Bounding Box: South={bbox.south:.4f}, West={bbox.west:.4f}, North={bbox.north:.4f}, East={bbox.east:.4f}")

    # 3. Resolve Manual Waypoints & Pins
    if args.waypoints:
        raw_wps = []
        for tok in args.waypoints.split(";"):
            if "," in tok:
                la, lo = tok.split(",")[:2]
                raw_wps.append((float(la.strip()), float(lo.strip())))
        if len(raw_wps) >= 2:
            r_out = calculate_route(raw_wps, profile=args.route_mode)
            path_waypoints = r_out["coordinates"]
            print(f"[*] Routed ({args.route_mode}): {r_out['distance_m']/1000:.1f} km ({len(path_waypoints)} pts)")

    if args.pins:
        for tok in args.pins.split(";"):
            tok = tok.strip()
            if not tok:
                continue
            if ":" in tok and "," in tok.split(":", 1)[1]:
                pname, coords_s = tok.split(":", 1)
                la, lo = coords_s.split(",")[:2]
                landmarks.append({"name": pname.strip(), "lat": float(la), "lon": float(lo)})
            else:
                try:
                    pg = geocode_location(tok, fetch_polygon=False)
                    landmarks.append({"name": tok, "lat": pg["lat"], "lon": pg["lon"]})
                    print(f"    Pinned '{tok}' -> ({pg['lat']:.4f}, {pg['lon']:.4f})")
                except Exception as pe:
                    print(f"    [WARN] Could not geocode pin '{tok}': {pe}")

    lock_aspect = (not args.no_aspect_lock) and (args.depth is None)
    depth_mm = args.depth if args.depth is not None else args.width
    target_h = args.target_height if (args.target_height and args.target_height > 0) else None
    urban_mode = "buildings" if args.buildings else ("blocks" if args.blocks else "none")

    config = MapMakerConfig(
        printer=PrinterProfile(bed_width=args.bed_size, bed_depth=args.bed_size),
        canvas=CanvasConfig(
            width_mm=args.width,
            depth_mm=depth_mm,
            lock_aspect_ratio=lock_aspect,
            rotation_deg=args.rotation,
            base_shape=args.base_shape,
            base_sides=args.base_sides,
            base_height_mm=args.base_height,
            topography_enabled=not args.no_topography,
            vertical_exaggeration=args.vertical_scale,
            target_relief_height_mm=target_h,
            urban_mode=urban_mode,
            blocks_enabled=(urban_mode == "blocks"),
            buildings_enabled=(urban_mode == "buildings"),
            building_height_scale=args.building_scale,
            viewing_orientation=args.orientation,
            route_mode=args.route_mode,
            path_style=args.path_style,
            depress_water=args.depress_water,
            frame_enabled=args.frame,
            title_text=title_text,
            subtitle_text=subtitle_text,
            path_waypoints=path_waypoints,
            landmarks=landmarks,
            boundary_geojson=boundary_geojson
        ),
        bbox=bbox,
        location_name=location_name
    )
    if args.no_dowels:
        config.dowel.enabled = False
    if lock_aspect:
        config.apply_aspect_ratio_lock(max_longest_side_mm=args.width)

    tiling_engine = TilingEngine(config)
    cols, rows = tiling_engine.cols, tiling_engine.rows
    print(f"\n[*] Canvas: {config.canvas.width_mm:.1f} x {config.canvas.depth_mm:.1f} mm | Grid: {cols}x{rows} ({len(tiling_engine.slices)} tiles)")

    grid_w = min(440, max(160, 180 * cols))
    grid_d = min(440, max(160, 180 * rows))
    print(f"[*] Fetching exact Web-Mercator AWS Terrarium DEM ({grid_w}x{grid_d} grid)...")
    elev_grid = fetch_elevation_grid(bbox, grid_width=grid_w, grid_depth=grid_d)
    print(f"    Elevation Range: {float(np.min(elev_grid)):.1f} m to {float(np.max(elev_grid)):.1f} m")

    print("[*] Solidifying 2-manifold 3D meshes, .3mf multi-part package, and 4-view preview...")
    manifest = tiling_engine.process_and_export_all(
        elev_grid,
        args.output,
        clean_output_dir=True,
        generate_preview=True,
        export_3mf=True,
        create_zip=False
    )

    print("\n==================================================")
    print("                GENERATION COMPLETE               ")
    print("==================================================")
    for t in manifest["tiles"]:
        print(f"  - Tile {t['filename']}: {t['width_mm']:.1f} x {t['depth_mm']:.1f} x {t['height_mm']:.1f} mm ({t['file_size_bytes']} bytes)")
    if manifest.get("assembly_3mf"):
        print(f"  - Bambu Studio Multi-Part 3MF: {manifest['assembly_3mf']}")
    if manifest.get("diagnostic_preview"):
        print(f"  - 4-View Diagnostic Render:    {manifest['diagnostic_preview']}")
    if manifest["biscuits"]["total_count"] > 0:
        print(f"  - Alignment Biscuits ({manifest['biscuits']['total_count']}):    {manifest['biscuits']['path']}")
    if manifest["route_inlay"]["path"]:
        print(f"  - Flat Snap-In Route Strip:    {manifest['route_inlay']['path']}")
    if manifest["landmark_pins"]["path"]:
        print(f"  - Head-Down Landmark Pins ({manifest['landmark_pins']['total_count']}): {manifest['landmark_pins']['path']}")
    print(f"  - Assembly & Slicing Guide:    {manifest['assembly_guide']}")


if __name__ == "__main__":
    main()
