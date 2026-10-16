"""Verification tests for MapMaker 3D multi-tile partitioning and biscuit generation."""

import sys
import os
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engine.config import MapMakerConfig, CanvasConfig, BoundingBox
from engine.tiling import TilingEngine

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output_tiling")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def test_tiling_pipeline():
    print("\n--- Test: Multi-Tile Partitioning & Biscuit Batch Engine ---")
    
    # 500 x 500 mm canvas on Bambu A1 (effective 250 x 250 mm bed) -> 2x2 grid
    config = MapMakerConfig(
        canvas=CanvasConfig(
            width_mm=500.0,
            depth_mm=500.0,
            base_height_mm=4.0,
            target_relief_height_mm=30.0
        ),
        bbox=BoundingBox(south=35.0, west=138.0, north=36.0, east=139.0),
        location_name="Mount Fuji Region"
    )

    engine = TilingEngine(config)
    cols, rows = engine.cols, engine.rows
    print(f"Calculated Grid: {cols} Cols x {rows} Rows ({len(engine.slices)} tiles)")
    assert cols == 2 and rows == 2, f"Expected 2x2 grid, got {cols}x{rows}"

    # Generate sample 80x80 elevation grid
    y = np.linspace(-3, 3, 80)
    x = np.linspace(-3, 3, 80)
    xx, yy = np.meshgrid(x, y)
    r = np.sqrt(xx**2 + yy**2)
    elev_grid = np.clip(3700.0 * np.exp(-r**2 / 4.0) + 100.0, 0, None).astype(np.float32)

    # Process and export all tiles
    res = engine.process_and_export_all(elev_grid, OUTPUT_DIR)

    print(f"Generated {res['num_tiles']} tiles in {OUTPUT_DIR}/tiles/")
    assert res['num_tiles'] == 4, f"Expected 4 tiles, got {res['num_tiles']}"

    for t in res["tiles"]:
        print(f"  Tile [Col {t['col']}, Row {t['row']}]: {t['filename']} ({t['width_mm']:.1f} x {t['depth_mm']:.1f} x {t['height_mm']:.1f} mm, {t['file_size_bytes']} bytes)")
        assert os.path.exists(t["path"])
        assert abs(t["width_mm"] - 250.0) < 1e-2
        assert abs(t["depth_mm"] - 250.0) < 1e-2
        # Check that it fits the Bambu A1 bed envelope (<= 256x256mm)
        assert t["width_mm"] <= 256.0 and t["depth_mm"] <= 256.0

    # Verify biscuit batch
    biscuits = res["biscuits"]
    print(f"Total Alignment Biscuits Needed: {biscuits['total_count']}")
    print(f"Biscuit Batch STL: {biscuits['path']} ({biscuits['file_size_bytes']} bytes)")
    assert biscuits["total_count"] == 8, f"Expected 8 biscuits for 2x2 grid, got {biscuits['total_count']}"
    assert os.path.exists(biscuits["path"]) and biscuits["file_size_bytes"] > 0

    # Verify assembly guide
    assert os.path.exists(res["assembly_guide"])
    print(f"Assembly Guide Generated: {res['assembly_guide']}")

    print("✓ Multi-Tile Partitioning & Biscuit Batch Test PASSED!")


def test_natural_border_multi_tile_and_biscuit_pockets():
    print("\n--- Test: Multi-Tile Natural Border Clipping & Subterranean Biscuit Pockets ---")
    from engine.geo import geocode_location

    geo = geocode_location("India")
    assert geo is not None and geo.get("geojson") is not None

    bbox = geo["bbox"]

    config = MapMakerConfig(
        canvas=CanvasConfig(
            width_mm=500.0,
            depth_mm=500.0,
            base_height_mm=4.0,
            target_relief_height_mm=25.0,
            base_shape="natural_border",
            boundary_geojson=geo["geojson"]
        ),
        bbox=bbox,
        location_name="India"
    )

    engine = TilingEngine(config)
    y = np.linspace(-1, 1, 60)
    x = np.linspace(-1, 1, 60)
    xx, yy = np.meshgrid(x, y)
    elev_grid = (1000.0 * (xx + yy + 2.0)).astype(np.float32)

    out_dir = os.path.join(OUTPUT_DIR, "india_test")
    res = engine.process_and_export_all(elev_grid, out_dir)
    assert res["num_tiles"] == 4

    # Verify each tile has distinct dimensions, embedded pockets, and 0 unmatched edges
    dims_set = set()
    for t in res["tiles"]:
        dim_tuple = (round(t["width_mm"], 1), round(t["depth_mm"], 1))
        dims_set.add(dim_tuple)
        assert t["pockets_count"] == 4, f"Expected 4 pockets on {t['filename']}, got {t['pockets_count']}"
        print(f"  {t['filename']}: {t['width_mm']:.1f} x {t['depth_mm']:.1f} x {t['height_mm']:.1f} mm | Pockets: {t['pockets_count']}")

    assert len(dims_set) == 4, f"Expected 4 distinct quadrant tile dimensions, got {dims_set}"
    print("✓ Multi-Tile Natural Border & Subterranean Biscuit Pockets Test PASSED!")


def _count_unmatched_edges_in_binary_stl(stl_path: str) -> int:
    with open(stl_path, "rb") as f:
        f.read(80)
        count = int(np.frombuffer(f.read(4), dtype=np.uint32)[0])
        data = np.frombuffer(f.read(count * 50), dtype=np.uint8).reshape(count, 50)
        tris = np.frombuffer(data[:, 12:48].tobytes(), dtype=np.float32).reshape(count, 3, 3)

    # Quantize vertices to 1e-3 mm to check edge manifoldness
    q = np.round(tris * 1000.0).astype(np.int64)
    edge_counts = {}
    for t in range(count):
        v0 = tuple(q[t, 0])
        v1 = tuple(q[t, 1])
        v2 = tuple(q[t, 2])
        for a, b in ((v0, v1), (v1, v2), (v2, v0)):
            if a != b:
                edge_counts[(a, b)] = edge_counts.get((a, b), 0) + 1

    unmatched = sum(1 for (a, b), c in edge_counts.items() if edge_counts.get((b, a), 0) != c)
    return unmatched


def test_route_and_landmark_pins_stl_export_and_manifold():
    print("\n--- Test: Route Inlay & Landmark Pin Sockets STL Export (100% 2-Manifold) ---")
    from engine.geo import geocode_location

    geo = geocode_location("India")
    bbox = geo["bbox"]

    # Define a route and 3 landmark pins across India
    waypoints = [
        (12.9716, 77.5946),  # Bengaluru
        (17.3850, 78.4867),  # Hyderabad
        (23.2599, 77.4126),  # Bhopal
        (28.6139, 77.2090),  # New Delhi
    ]
    landmarks = [
        {"name": "Bengaluru", "lat": 12.9716, "lon": 77.5946},
        {"name": "Mumbai", "lat": 19.0760, "lon": 72.8777},
        {"name": "New Delhi", "lat": 28.6139, "lon": 77.2090},
    ]

    config = MapMakerConfig(
        canvas=CanvasConfig(
            width_mm=500.0,
            depth_mm=500.0,
            base_height_mm=4.0,
            target_relief_height_mm=25.0,
            base_shape="natural_border",
            boundary_geojson=geo["geojson"],
            path_waypoints=waypoints,
            landmarks=landmarks
        ),
        bbox=bbox,
        location_name="India Route & Landmarks"
    )

    engine = TilingEngine(config)
    y = np.linspace(-1, 1, 60)
    x = np.linspace(-1, 1, 60)
    xx, yy = np.meshgrid(x, y)
    elev_grid = (1000.0 * (xx + yy + 2.0)).astype(np.float32)

    out_dir = os.path.join(OUTPUT_DIR, "india_route_pins")
    res = engine.process_and_export_all(elev_grid, out_dir)

    assert res["route_inlay"]["path"] is not None and os.path.exists(res["route_inlay"]["path"])
    assert res["route_inlay"]["file_size_bytes"] > 0
    assert res["landmark_pins"]["path"] is not None and os.path.exists(res["landmark_pins"]["path"])
    assert res["landmark_pins"]["total_count"] == 3
    assert len(res["landmark_pins"]["sockets_carved"]) == 3

    # Verify 0 unmatched edges on route_inlay.stl, landmark_pins.stl, and all carved terrain tiles
    u_route = _count_unmatched_edges_in_binary_stl(res["route_inlay"]["path"])
    u_pins = _count_unmatched_edges_in_binary_stl(res["landmark_pins"]["path"])
    print(f"  route_inlay.stl ({res['route_inlay']['file_size_bytes']} bytes) -> unmatched_edges = {u_route}")
    print(f"  landmark_pins.stl ({res['landmark_pins']['file_size_bytes']} bytes) -> unmatched_edges = {u_pins}")
    assert u_route == 0, f"route_inlay.stl has {u_route} unmatched edges"
    assert u_pins == 0, f"landmark_pins.stl has {u_pins} unmatched edges"

    for t in res["tiles"]:
        u_tile = _count_unmatched_edges_in_binary_stl(t["path"])
        print(f"  {t['filename']} (Sockets: {t['sockets_count']}, Pockets: {t['pockets_count']}) -> unmatched_edges = {u_tile}")
        assert u_tile == 0, f"{t['filename']} has {u_tile} unmatched edges"

    print("✓ Route Inlay & Landmark Pin Sockets STL Export Test PASSED!")


if __name__ == "__main__":
    test_tiling_pipeline()
    test_natural_border_multi_tile_and_biscuit_pockets()
    test_route_and_landmark_pins_stl_export_and_manifold()
    print("\n==========================================")
    print("ALL TILING & ASSEMBLY TESTS PASSED!")
    print("==========================================")
