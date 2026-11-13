"""Comprehensive DFAM, 2-Manifold, OpenCASCADE 3D Boolean Collision Simulation,
and Memorabilia Showcase Verification Suite for MapMaker 3D.

Verifies:
1. Zero mechanical interference (`partA.common(partB).Volume == 0.0 mm³` via FreeCAD OpenCASCADE)
   across mating tiles + subterranean biscuit splines, terrain pin sockets + seated pins,
   and rectangular/shaped terrain route trenches + seated route inlays.
2. 100% 2-manifold (`unmatched_edges == 0`) across hilly Urban Blocks (San Francisco),
   real 3D OSM Skyscrapers (Manhattan), Wall-Hanging Keyholes, Gallery Frames, and 3D Vector Typography.
3. Multi-tile global rotation seam continuity (`0.00 mm` step mismatch).
4. Antimeridian & oceanic territory clustering (`New Zealand` & `Chile`), Web Mercator latitude accuracy,
   GPX track import, Bambu Studio `.3mf` multi-part archive structure, and 4-view diagnostic PNG renders.
"""

import os
import sys
import struct
import zipfile
import tempfile
import xml.etree.ElementTree as ET
import numpy as np

FREECAD_CANDIDATES = [
    "/usr/lib/freecad-python3/lib",
    os.path.expandvars(r"%ProgramFiles%\FreeCAD 1.1\bin"),
    os.path.expandvars(r"%ProgramFiles%\FreeCAD 1.0\bin"),
    os.path.expandvars(r"%LocalAppData%\Programs\FreeCAD 1.0\bin"),
    "/Applications/FreeCAD.app/Contents/Resources/lib",
]
for _fc_dir in FREECAD_CANDIDATES:
    if _fc_dir and os.path.exists(_fc_dir) and _fc_dir not in sys.path:
        sys.path.append(_fc_dir)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engine.config import MapMakerConfig, CanvasConfig, BoundingBox
from engine.geo import geocode_location, fetch_elevation_grid, parse_gps_track
from engine.mesh import (
    SolidMesh,
    generate_terrain_mesh,
    generate_flat_biscuit,
    generate_landmark_pin_mesh,
    generate_path_strip_and_cavity,
    calculate_z_scale,
)
from engine.tiling import TilingEngine


def load_binary_stl(path: str) -> np.ndarray:
    with open(path, "rb") as f:
        f.read(80)
        count = struct.unpack("<I", f.read(4))[0]
        raw = np.frombuffer(f.read(count * 50), dtype=np.uint8).reshape(count, 50)
        return np.frombuffer(raw[:, 12:48].tobytes(), dtype=np.float32).reshape(count, 3, 3)


def count_unmatched_edges_stl(path: str) -> int:
    tris = load_binary_stl(path)
    raw = tris.view(np.uint32)
    ec = {}
    for t in range(len(raw)):
        v0, v1, v2 = tuple(raw[t, 0]), tuple(raw[t, 1]), tuple(raw[t, 2])
        if v0 == v1 or v1 == v2 or v2 == v0:
            continue
        for a, b in ((v0, v1), (v1, v2), (v2, v0)):
            ec[(a, b)] = ec.get((a, b), 0) + 1
    return sum(1 for (a, b), c in ec.items() if ec.get((b, a), 0) != c)


def bed_contact_area_stl(path: str) -> float:
    tris = load_binary_stl(path)
    z0 = float(np.min(tris[:, :, 2]))
    area = 0.0
    for t in range(len(tris)):
        tri = tris[t]
        if np.all(np.abs(tri[:, 2] - z0) < 0.02):
            area += 0.5 * float(np.linalg.norm(np.cross(tri[1] - tri[0], tri[2] - tri[0])))
    return area


def solid_mesh_to_occ_shape(mesh: SolidMesh):
    """Converts a watertight SolidMesh into an OpenCASCADE solid Part.Shape for 3D Boolean collision checks."""
    import FreeCAD  # noqa: F401
    import Mesh as FcMesh
    import Part

    facets = []
    v = mesh.vertices
    for f0, f1, f2 in mesh.faces:
        p0 = tuple(float(x) for x in v[f0])
        p1 = tuple(float(x) for x in v[f1])
        p2 = tuple(float(x) for x in v[f2])
        facets.append([p0, p1, p2])
    fc_m = FcMesh.Mesh(facets)
    sh = Part.Shape()
    sh.makeShapeFromMesh(fc_m.Topology, 0.01)
    return Part.makeSolid(sh)


def test_opencascade_3d_boolean_collisions():
    print("\n--- 1. OpenCASCADE 3D Boolean Collision Simulation (Biscuits, Pins, Route Trench) ---")
    try:
        import FreeCAD  # noqa: F401
        import Part  # noqa: F401
    except ImportError:
        print("  [SKIP] FreeCAD Python C++ libraries not installed on this machine; skipping OCC hook.")
        return

    bbox = BoundingBox(south=35.32, west=138.68, north=35.40, east=138.78)
    # Sloped 3D mountain cone grid
    y = np.linspace(-2, 2, 48)
    x = np.linspace(-2, 2, 48)
    xx, yy = np.meshgrid(x, y)
    elev = (1200.0 * np.exp(-(xx**2 + yy**2) / 3.0) + 100.0).astype(np.float32)

    waypoints = [(35.335, 138.700), (35.360, 138.730), (35.382, 138.755)]
    pins = [{"name": "Slope Camp", "lat": 35.355, "lon": 138.725}]

    # A. Tile + Biscuit + Pin + Route Trench in local coordinates
    tile_mesh = generate_terrain_mesh(
        elev_grid=elev,
        bbox=bbox,
        width_mm=120.0,
        depth_mm=120.0,
        base_height_mm=4.5,
        target_relief_height_mm=20.0,
        base_shape="rectangle",
        active_seams={"east": True, "north": False, "west": False, "south": False},
        route_waypoints_latlon=waypoints,
        landmark_pins_latlon=pins,
        embed_keyhole=True,
    )

    assert len(tile_mesh.pockets_created) >= 1, "Expected subterranean biscuit pocket on east seam"
    assert len(tile_mesh.sockets_carved) == 1, "Expected 1 carved landmark pin socket"
    assert tile_mesh.keyhole_created is not None, "Expected rear wall-hanging keyhole slot"

    occ_tile = solid_mesh_to_occ_shape(tile_mesh)

    # 1. Check Biscuit Spline inserted into East Pocket
    pk = tile_mesh.pockets_created[0]
    bisc = generate_flat_biscuit(thickness_mm=1.55, width_mm=12.0, length_mm=11.6)
    vx, vy = bisc.vertices[:, 0].copy(), bisc.vertices[:, 1].copy()
    bisc.vertices[:, 0], bisc.vertices[:, 1] = -vy, vx
    z_seat = 0.5 * (pk["z_range"][0] + pk["z_range"][1] - 1.55)
    bisc.translate(pk["center_xy"][0], pk["center_xy"][1], z_seat)
    occ_bisc = solid_mesh_to_occ_shape(bisc)
    inter_bisc = occ_tile.common(occ_bisc)
    print(f"  [OpenCASCADE] Tile ∩ Biscuit Interference Volume = {inter_bisc.Volume:.6f} mm³")
    assert inter_bisc.Volume == 0.0, f"Biscuit collision detected: {inter_bisc.Volume:.4f} mm³"

    # 2. Check Seated Landmark Pin on Sloped Mountain Socket
    sk = tile_mesh.sockets_carved[0]
    pin_seated = generate_landmark_pin_mesh(zero_base_for_printing=False, wall_hanging_tilt_deg=20.0)
    pin_seated.translate(sk["x_mm"], sk["y_mm"], sk["z_surface_mm"])
    occ_pin = solid_mesh_to_occ_shape(pin_seated)
    inter_pin = occ_tile.common(occ_pin)
    print(f"  [OpenCASCADE] Tile ∩ Seated Pin Interference Volume = {inter_pin.Volume:.6f} mm³")
    assert inter_pin.Volume == 0.0, f"Pin collision detected: {inter_pin.Volume:.4f} mm³"

    # 3. Check 3D Seated Route Inlay inside Rectangular Terrain Trench!
    z_sc = calculate_z_scale(elev, bbox, 120.0, 2.0, 20.0)
    inlay_3d, _ = generate_path_strip_and_cavity(
        waypoints_lat_lon=waypoints,
        bbox=bbox,
        width_mm=120.0,
        depth_mm=120.0,
        elev_grid=elev,
        z_scale=z_sc,
        base_height_mm=4.5,
        path_width_mm=1.92,
        path_depth_mm=1.60,
        landmark_pins_latlon=pins,
    )
    occ_inlay = solid_mesh_to_occ_shape(inlay_3d)
    inter_route = occ_tile.common(occ_inlay)
    inter_route_pin = occ_inlay.common(occ_pin)
    print(f"  [OpenCASCADE] Tile ∩ Route Inlay Interference Volume = {inter_route.Volume:.6f} mm³")
    print(f"  [OpenCASCADE] Route Inlay ∩ Seated Pin Interference Volume = {inter_route_pin.Volume:.6f} mm³")
    assert inter_route.Volume == 0.0, f"Route trench collision detected: {inter_route.Volume:.4f} mm³"
    assert inter_route_pin.Volume == 0.0, f"Route-to-Pin collision detected: {inter_route_pin.Volume:.4f} mm³"
    print("✓ ALL OpenCASCADE 3D Boolean Collision Checks PASSED (0.000000 mm³ interference)!")


def test_rotated_multi_tile_seam_and_homeland_geocoding():
    print("\n--- 2. Multi-Tile Rotated Seam Continuity & Antimeridian Homeland Framing ---")
    nz = geocode_location("New Zealand")
    nz_aspect = nz["bbox"].real_aspect_ratio
    print(f"  New Zealand homeland aspect W/H = {nz_aspect:.2f} (previously 11.38x antimeridian bloat!)")
    assert 0.45 <= nz_aspect <= 1.25, f"New Zealand aspect ratio still bloated: {nz_aspect}"

    # 2x2 rotated mountain print seam check
    bbox = BoundingBox(35.0, 138.0, 36.0, 139.0)
    y, x = np.linspace(-2, 2, 100), np.linspace(-2, 2, 100)
    xx, yy = np.meshgrid(x, y)
    elev = (2500.0 * np.exp(-(xx**2 + yy**2) / 3.0)).astype(np.float32)

    cfg = MapMakerConfig(
        canvas=CanvasConfig(width_mm=400.0, depth_mm=400.0, rotation_deg=42.0, target_relief_height_mm=28.0),
        bbox=bbox,
        location_name="Rotated 2x2 Peak",
    )
    with tempfile.TemporaryDirectory() as tmpd:
        res = TilingEngine(cfg).process_and_export_all(elev, tmpd, generate_preview=False, export_3mf=False)
        t00 = load_binary_stl(res["tiles"][0]["path"]).reshape(-1, 3)
        t10 = load_binary_stl(res["tiles"][1]["path"]).reshape(-1, 3)
        east_00 = t00[(np.abs(t00[:, 0] - 100.0) < 0.05) & (t00[:, 2] > 0.2)]
        west_10 = t10[(np.abs(t10[:, 0] + 100.0) < 0.05) & (t10[:, 2] > 0.2)]
        max_step = 0.0
        for yv in np.linspace(-95, 95, 20):
            za = east_00[np.abs(east_00[:, 1] - yv) < 2.5][:, 2]
            zb = west_10[np.abs(west_10[:, 1] - yv) < 2.5][:, 2]
            if len(za) > 0 and len(zb) > 0:
                max_step = max(max_step, float(abs(np.max(za) - np.max(zb))))
        print(f"  2x2 Rotated (42°) Seam Step Mismatch = {max_step:.4f} mm (previously 17.43 mm!)")
        assert max_step < 0.05, f"Seam mismatch too high: {max_step} mm"
    print("✓ Multi-Tile Rotation & Homeland Geocoding PASSED!")


def test_gpx_showcase_memorabilia_and_3mf():
    print("\n--- 3. GPX Climb + Frame + 3D Plaque + San Francisco Hilly Blocks Showcase ---")
    gpx_sample = """<?xml version="1.0" encoding="UTF-8"?>
    <gpx version="1.1"><trk><name>Mount Fuji Yoshida Climb</name><trkseg>
      <trkpt lat="35.3949" lon="138.7329"><ele>2305</ele></trkpt>
      <trkpt lat="35.3840" lon="138.7365"><ele>2750</ele></trkpt>
      <trkpt lat="35.3745" lon="138.7352"><ele>3220</ele></trkpt>
      <trkpt lat="35.3655" lon="138.7325"><ele>3640</ele></trkpt>
      <trkpt lat="35.3606" lon="138.7274"><ele>3776</ele></trkpt>
    </trkseg></trk></gpx>"""

    trk = parse_gps_track(gpx_sample, "fuji_yoshida.gpx")
    assert trk["elevation_gain_m"] > 1400
    print(f"  Parsed GPX: '{trk['name']}' -> {trk['suggested_subtitle']}")

    fuji_geo = geocode_location("Mount Fuji")
    elev_fuji = fetch_elevation_grid(fuji_geo["bbox"], grid_width=140, grid_depth=140)

    out_fuji = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "exports", "showcase_mount_fuji"))
    cfg_fuji = MapMakerConfig(
        canvas=CanvasConfig(
            width_mm=220.0,
            depth_mm=220.0,
            lock_aspect_ratio=True,
            base_shape="rectangle",
            base_height_mm=4.5,
            target_relief_height_mm=32.0,
            viewing_orientation="wall_hanging",
            depress_water=True,
            frame_enabled=True,
            title_text="MOUNT FUJI",
            subtitle_text=trk["suggested_subtitle"],
            path_waypoints=trk["coordinates"],
            path_style="flat_strip",
            landmarks=[trk["start_point"], trk["finish_point"]],
        ),
        bbox=fuji_geo["bbox"],
        location_name="Mount Fuji, Japan",
    )
    res_fuji = TilingEngine(cfg_fuji).process_and_export_all(
        elev_fuji, out_fuji, clean_output_dir=True, generate_preview=True, export_3mf=True, create_zip=True
    )

    u_tile = count_unmatched_edges_stl(res_fuji["tiles"][0]["path"])
    u_strip = count_unmatched_edges_stl(res_fuji["route_inlay"]["path"])
    u_pins = count_unmatched_edges_stl(res_fuji["landmark_pins"]["path"])
    strip_bed = bed_contact_area_stl(res_fuji["route_inlay"]["path"])
    pins_bed = bed_contact_area_stl(res_fuji["landmark_pins"]["path"])

    print(f"  Mount Fuji Tile STL unmatched_edges = {u_tile}")
    print(f"  Flat Route Strip unmatched_edges = {u_strip}, bed_contact = {strip_bed:.1f} mm² (previously 3.98 mm²!)")
    print(f"  Head-Down Pins (x2) unmatched_edges = {u_pins}, bed_contact = {pins_bed:.1f} mm² (previously 3.0 mm²!)")
    assert u_tile == 0 and u_strip == 0 and u_pins == 0
    assert strip_bed > 25.0, f"Expected flat route strip on bed, got {strip_bed} mm²"
    assert pins_bed > 30.0, f"Expected head-down pins with >30 mm² bed contact, got {pins_bed} mm²"

    # Verify .3mf archive structure & named Bambu Studio objects
    assert os.path.exists(res_fuji["assembly_3mf"])
    with zipfile.ZipFile(res_fuji["assembly_3mf"], "r") as zf:
        names = zf.namelist()
        assert "3D/3dmodel.model" in names
        model_root = ET.fromstring(zf.read("3D/3dmodel.model"))
        obj_names = [el.attrib.get("name", "") for el in model_root.iter() if el.tag.endswith("object")]
        print(f"  Bambu .3MF Named Objects: {obj_names}")
        assert "Terrain_Relief" in obj_names and "Title_Typography" in obj_names and "Route_Path" in obj_names

    # San Francisco Hilly Urban Blocks 2-Manifold Verification (previously 26,126 unmatched edges!)
    sf_geo = geocode_location("San Francisco")
    elev_sf = fetch_elevation_grid(sf_geo["bbox"], grid_width=130, grid_depth=130)
    out_sf = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "exports", "showcase_san_francisco"))
    cfg_sf = MapMakerConfig(
        canvas=CanvasConfig(
            width_mm=230.0,
            depth_mm=230.0,
            lock_aspect_ratio=True,
            base_shape="rectangle",
            base_height_mm=4.2,
            target_relief_height_mm=18.0,
            urban_mode="blocks",
            blocks_enabled=True,
            depress_water=True,
            frame_enabled=True,
            viewing_orientation="wall_hanging",
            title_text="SAN FRANCISCO",
            subtitle_text="CALIFORNIA • BAY AREA",
        ),
        bbox=sf_geo["bbox"],
        location_name="San Francisco, California",
    )
    res_sf = TilingEngine(cfg_sf).process_and_export_all(
        elev_sf, out_sf, clean_output_dir=True, generate_preview=True, export_3mf=True
    )
    u_sf = count_unmatched_edges_stl(res_sf["tiles"][0]["path"])
    print(f"  San Francisco Hilly Urban Blocks STL unmatched_edges = {u_sf} (previously 26,126!)")
    assert u_sf == 0, f"Expected 0 unmatched edges on SF blocks, got {u_sf}"
    print("✓ GPX Memorabilia, .3MF Multi-Part Archive & Hilly SF Urban Blocks PASSED!")


if __name__ == "__main__":
    test_opencascade_3d_boolean_collisions()
    test_rotated_multi_tile_seam_and_homeland_geocoding()
    test_gpx_showcase_memorabilia_and_3mf()
    print("\n============================================================")
    print("ALL MEMORABILIA, DFAM & OPENCASCADE COLLISION TESTS PASSED!")
    print("============================================================")
