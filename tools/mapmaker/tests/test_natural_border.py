"""Automated verification test for 'No Base (Coastline / Borders)' base shape.

Tests:
1. Geocoding and boundary extraction for India, Japan, Karnataka, Texas.
2. Watertight SolidMesh generation with 0 non-manifold edges.
3. Boundary preview mesh generation for Three.js WebGL.
4. HTTP REST API endpoints.
"""

import sys
import os
import urllib.request
import json
import numpy as np

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engine.config import BoundingBox, MapMakerConfig, CanvasConfig
from engine.geo import geocode_location, fetch_elevation_grid
from engine.mesh import generate_terrain_mesh, generate_boundary_preview_mesh, SolidMesh


def check_manifold_edges(mesh: SolidMesh) -> int:
    """Verifies that every directed edge has exactly one matching reverse edge (0 boundary edges)."""
    edges = {}
    for f in mesh.faces:
        for i in range(3):
            e = (f[i], f[(i + 1) % 3])
            edges[e] = edges.get(e, 0) + 1
    unmatched = 0
    for e, count in edges.items():
        rev_e = (e[1], e[0])
        if edges.get(rev_e, 0) != count:
            unmatched += 1
    return unmatched


def test_locations():
    test_cases = ["Karnataka", "Texas", "Japan", "India"]
    print("=" * 60)
    print("TEST SUITE: 'NO BASE (COASTLINE / BORDERS)' GEOMETRY ENGINE")
    print("=" * 60)

    for name in test_cases:
        print(f"\n--- Testing Location: {name} ---")
        geo = geocode_location(name)
        bbox = geo["bbox"]
        geojson = geo.get("geojson")

        assert geojson is not None, f"Expected GeoJSON boundary for {name}, got None"
        assert geojson.get("type") in ("Polygon", "MultiPolygon"), f"Unexpected GeoJSON type {geojson.get('type')}"
        print(f"[*] Geocode resolved: {geo['display_name'][:50]}")
        print(f"    BBox: S={bbox.south:.2f}, N={bbox.north:.2f}, W={bbox.west:.2f}, E={bbox.east:.2f}")
        print(f"    GeoJSON Type: {geojson.get('type')}")

        # Fetch elevation grid
        grid = fetch_elevation_grid(bbox, grid_width=40, grid_depth=40)
        print(f"    DEM Grid: shape={grid.shape}, min={np.min(grid):.1f}m, max={np.max(grid):.1f}m")

        # Test Solid 3D Mesh Generation (CAD / STL engine)
        solid_mesh = generate_terrain_mesh(
            elev_grid=grid,
            bbox=bbox,
            width_mm=250.0,
            depth_mm=250.0,
            base_height_mm=4.0,
            vertical_exaggeration=2.0,
            target_relief_height_mm=15.0,
            base_shape="natural_border",
            boundary_geojson=geojson
        )
        assert solid_mesh.num_vertices > 0, "Solid mesh has 0 vertices"
        assert solid_mesh.num_faces > 0, "Solid mesh has 0 faces"
        unmatched_edges = check_manifold_edges(solid_mesh)
        print(f"[*] Solid Mesh: {solid_mesh.num_vertices} vertices, {solid_mesh.num_faces} faces, unmatched edges = {unmatched_edges}")
        assert unmatched_edges == 0, f"Non-manifold mesh detected for {name}: {unmatched_edges} unmatched edges"

        # Test WebGL Preview Mesh Generation
        preview = generate_boundary_preview_mesh(
            elev_grid=grid,
            bbox=bbox,
            boundary_geojson=geojson,
            width_mm=250.0,
            depth_mm=250.0,
            base_height_mm=4.0,
            target_relief_mm=15.0
        )
        assert len(preview["positions"]) > 0, "Preview mesh positions empty"
        assert len(preview["indices"]) > 0, "Preview mesh indices empty"
        assert len(preview["colors"]) == len(preview["positions"]), "Preview mesh colors length mismatch"
        print(f"[*] 3D WebGL Preview: {len(preview['positions']) // 3} verts, {len(preview['indices']) // 3} tris, top={preview['top_indices_count'] // 3} tris")
        print(f"✓ {name} verification PASSED!")

    print("\n" + "=" * 60)
    print("ALL NATURAL BORDER GEOMETRY & MANIFOLD TESTS PASSED (100% SUCCESS)!")
    print("=" * 60)


def test_api_endpoints():
    print("\n--- Testing HTTP REST API Endpoints ---")
    base_url = "http://127.0.0.1:8765"

    # Test /api/boundary
    req = urllib.request.urlopen(f"{base_url}/api/boundary?q=Karnataka")
    data = json.loads(req.read().decode())
    assert data.get("status") == "ok", "Expected status ok"
    assert data.get("geojson") is not None, "Expected geojson in /api/boundary"
    print("✓ /api/boundary?q=Karnataka returned valid boundary GeoJSON")

    # Test /api/boundary_mesh POST
    post_payload = json.dumps({
        "bbox": data["bbox"],
        "width_mm": 250.0,
        "depth_mm": 250.0,
        "base_height": 4.0,
        "target_relief": 15.0,
        "boundary_geojson": data["geojson"],
        "location": "Karnataka"
    }).encode("utf-8")

    req_post = urllib.request.Request(
        f"{base_url}/api/boundary_mesh",
        data=post_payload,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req_post) as resp:
        mesh_data = json.loads(resp.read().decode())
        assert len(mesh_data.get("positions", [])) > 0, "Expected positions in boundary mesh"
        assert len(mesh_data.get("indices", [])) > 0, "Expected indices in boundary mesh"
        print(f"✓ /api/boundary_mesh returned {len(mesh_data['positions']) // 3} verts and {len(mesh_data['indices']) // 3} triangles")

    print("\n" + "=" * 60)
    print("ALL API ENDPOINT TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    test_locations()
    test_api_endpoints()
