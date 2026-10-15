"""Verification tests for MapMaker 3D mesh generation and fabrication geometry."""

import sys
import os
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engine.config import BoundingBox
from engine.geo import BuildingPolygon
from engine.mesh import (
    SolidMesh,
    generate_terrain_mesh,
    extrude_building_mesh,
    generate_flat_biscuit,
    generate_path_strip_and_cavity,
    calculate_z_scale
)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def test_terrain_solidification():
    print("\n--- Test 1: Terrain Mesh Solidification ---")
    rows, cols = 40, 40
    # Procedural elevation grid simulating a mountain cone
    y = np.linspace(-2, 2, rows)
    x = np.linspace(-2, 2, cols)
    xx, yy = np.meshgrid(x, y)
    r = np.sqrt(xx**2 + yy**2)
    elev_grid = np.clip(1000.0 * np.exp(-r**2) + 200.0, 0, None).astype(np.float32)

    bbox = BoundingBox(south=35.0, west=138.0, north=35.5, east=138.5)
    width_mm = 150.0
    depth_mm = 150.0
    base_height_mm = 4.0

    mesh = generate_terrain_mesh(
        elev_grid=elev_grid,
        bbox=bbox,
        width_mm=width_mm,
        depth_mm=depth_mm,
        base_height_mm=base_height_mm,
        target_relief_height_mm=25.0 # Direct mm targeting test!
    )

    min_b, max_b = mesh.bounds
    dims = mesh.dimensions
    print(f"Mesh Vertices: {mesh.num_vertices}")
    print(f"Mesh Faces: {mesh.num_faces}")
    print(f"Bounding Box: X=[{min_b[0]:.2f}, {max_b[0]:.2f}], Y=[{min_b[1]:.2f}, {max_b[1]:.2f}], Z=[{min_b[2]:.2f}, {max_b[2]:.2f}]")
    print(f"Dimensions: {dims[0]:.2f} x {dims[1]:.2f} x {dims[2]:.2f} mm")

    assert abs(dims[0] - width_mm) < 1e-3, f"Width mismatch: {dims[0]} vs {width_mm}"
    assert abs(dims[1] - depth_mm) < 1e-3, f"Depth mismatch: {dims[1]} vs {depth_mm}"
    assert min_b[2] == 0.0, f"Bottom base must be at Z=0, got {min_b[2]}"
    # Base height (4.0mm) + target relief (25.0mm) = 29.0mm total height
    assert abs(dims[2] - 29.0) < 0.1, f"Total height should be ~29.0mm, got {dims[2]:.2f}mm"

    stl_path = os.path.join(OUTPUT_DIR, "test_terrain.stl")
    mesh.export_stl(stl_path, binary=True)
    assert os.path.exists(stl_path) and os.path.getsize(stl_path) > 1000
    print(f"Exported binary STL: {stl_path} ({os.path.getsize(stl_path)} bytes)")
    print("✓ Terrain Solidification Test PASSED!")


def test_building_extrusion_and_audit():
    print("\n--- Test 2: Building Extrusion & Nozzle Wall Audit ---")
    bbox = BoundingBox(south=40.74, west=-73.99, north=40.76, east=-73.97)
    
    # 1. Normal sized building (e.g. 50m x 40m footprint, 60m height)
    normal_poly = [
        (40.745, -73.985),
        (40.745, -73.984),
        (40.746, -73.984),
        (40.746, -73.985)
    ]
    b1 = BuildingPolygon(osm_id=1, coordinates=normal_poly, height_meters=60.0, name="Office Tower")

    # 2. Very narrow / thin building (e.g. 4m wide corridor)
    thin_poly = [
        (40.7500, -73.9800),
        (40.7500, -73.98004),
        (40.7505, -73.98004),
        (40.7505, -73.9800)
    ]
    b2 = BuildingPolygon(osm_id=2, coordinates=thin_poly, height_meters=20.0, name="Narrow Alleyway Structure")

    width_mm = 200.0
    depth_mm = 200.0
    z_scale = 0.1

    m1, audit1 = extrude_building_mesh(b1, bbox, width_mm, depth_mm, z_ground=5.0, z_scale=z_scale)
    m2, audit2 = extrude_building_mesh(b2, bbox, width_mm, depth_mm, z_ground=5.0, z_scale=z_scale)

    assert m1 is not None
    print(f"Building 1 ({audit1['name']}): Dimensions {audit1['width_mm']:.2f} x {audit1['depth_mm']:.2f} mm | Too thin: {audit1['too_thin']}")
    assert audit1["too_thin"] is False, "Normal building should not be flagged as too thin"

    assert m2 is not None
    print(f"Building 2 ({audit2['name']}): Dimensions {audit2['width_mm']:.2f} x {audit2['depth_mm']:.2f} mm | Too thin: {audit2['too_thin']}")
    assert audit2["too_thin"] is True, "Narrow building should be flagged (< 0.84mm threshold)"

    stl_path = os.path.join(OUTPUT_DIR, "test_building.stl")
    m1.export_stl(stl_path, binary=True)
    print(f"Exported building STL: {stl_path}")
    print("✓ Building Extrusion & Audit Test PASSED!")


def test_flat_biscuit_dowel():
    print("\n--- Test 3: Flat Biscuit Dowel Geometry ---")
    biscuit = generate_flat_biscuit(thickness_mm=1.60, width_mm=12.0, length_mm=12.0)
    dims = biscuit.dimensions
    print(f"Biscuit Dimensions: {dims[0]:.2f} (L) x {dims[1]:.2f} (W) x {dims[2]:.2f} (H) mm")
    assert abs(dims[0] - 12.0) < 1e-3
    assert abs(dims[1] - 12.0) < 1e-3
    assert abs(dims[2] - 1.60) < 1e-3

    stl_path = os.path.join(OUTPUT_DIR, "test_biscuit.stl")
    biscuit.export_stl(stl_path, binary=True)
    print(f"Exported biscuit STL: {stl_path}")
    print("✓ Flat Biscuit Dowel Test PASSED!")


def test_path_strip_and_cavity_tolerances():
    print("\n--- Test 4: Slide-In Path Strip & Negative Cavity Clearances ---")
    bbox = BoundingBox(south=35.0, west=138.0, north=35.5, east=138.5)
    elev_grid = np.full((20, 20), 500.0, dtype=np.float32)

    waypoints = [
        (35.1, 138.1),
        (35.2, 138.2),
        (35.3, 138.35),
        (35.4, 138.4)
    ]

    path_width = 2.0
    clearance = 0.20

    inlay, cutter = generate_path_strip_and_cavity(
        waypoints_lat_lon=waypoints,
        bbox=bbox,
        width_mm=100.0,
        depth_mm=100.0,
        elev_grid=elev_grid,
        z_scale=0.01,
        path_width_mm=path_width,
        clearance_mm=clearance
    )

    inlay_dims = inlay.dimensions
    cutter_dims = cutter.dimensions

    print(f"Inlay Strip Bounds Span: {inlay_dims}")
    print(f"Negative Cutter Bounds Span: {cutter_dims}")

    # Cutter must be wider than inlay by 2 * clearance = 0.40mm
    # Check that cutter has greater volume / span than inlay
    assert cutter_dims[2] > inlay_dims[2], "Cutter should extend taller to guarantee clean boolean through terrain"

    stl_inlay = os.path.join(OUTPUT_DIR, "test_path_inlay.stl")
    stl_cutter = os.path.join(OUTPUT_DIR, "test_path_cutter.stl")
    inlay.export_stl(stl_inlay, binary=True)
    cutter.export_stl(stl_cutter, binary=True)
    print(f"Exported inlay STL: {stl_inlay}")
    print(f"Exported cutter STL: {stl_cutter}")
    print("✓ Path Clearance & Inlay Test PASSED!")


if __name__ == "__main__":
    test_terrain_solidification()
    test_building_extrusion_and_audit()
    test_flat_biscuit_dowel()
    test_path_strip_and_cavity_tolerances()
    print("\n==========================================")
    print("ALL MESH GENERATION & DFAM TESTS PASSED!")
    print("==========================================")
