"""Multi-tile grid partitioning and subterranean biscuit pocket embedding engine for MapMaker 3D.

Splits oversized geographic canvases into printable chunks conforming to
the Bambu Lab A1 build envelope, automatically boring alignment biscuit pockets
into interior mating faces.
"""

import os
import math
import numpy as np
from typing import List, Tuple, Dict, Any, Optional

from .config import MapMakerConfig, TileSlice, BoundingBox
from .mesh import (
    SolidMesh,
    generate_terrain_mesh,
    generate_flat_biscuit,
    generate_landmark_pin_mesh,
    generate_path_strip_and_cavity,
    calculate_z_scale,
    extrude_building_mesh,
    extrude_block_mesh,
)
from .geo import fetch_osm_buildings
from .blocks import fetch_urban_blocks


class TilingEngine:
    """Manages canvas partitioning, tile generation, and alignment joint placement."""

    def __init__(self, config: MapMakerConfig):
        self.config = config
        self.cols, self.rows = config.calculate_tiling_grid()
        self.slices = config.generate_tile_slices()

    def partition_elevation_grid(self, full_elev_grid: np.ndarray) -> List[Tuple[TileSlice, np.ndarray]]:
        """Splits full canvas elevation grid into sub-grids for each tile slice.
        
        Guarantees that adjacent tiles share exact boundary rows/columns for seamless alignment.
        """
        full_rows, full_cols = full_elev_grid.shape
        partitioned = []

        for tile in self.slices:
            c = tile.col_idx
            r = tile.row_idx

            # Calculate exact grid indices with shared border sample
            c0 = int(round(c * (full_cols - 1) / self.cols))
            c1 = int(round((c + 1) * (full_cols - 1) / self.cols)) + 1
            r0 = int(round(r * (full_rows - 1) / self.rows))
            r1 = int(round((r + 1) * (full_rows - 1) / self.rows)) + 1

            sub_grid = full_elev_grid[r0:r1, c0:c1].copy()
            partitioned.append((tile, sub_grid))

        return partitioned

    def calculate_biscuit_placements(self) -> Dict[str, Any]:
        """Calculates internal seam locations and required biscuit counts."""
        pockets_per_edge = 2 if max(self.config.canvas.width_mm / self.cols, 
                                    self.config.canvas.depth_mm / self.rows) >= 100.0 else 1

        num_ew_seams = (self.cols - 1) * self.rows
        num_ns_seams = self.cols * (self.rows - 1)
        total_biscuits = (num_ew_seams + num_ns_seams) * pockets_per_edge

        return {
            "pockets_per_edge": pockets_per_edge,
            "num_ew_seams": num_ew_seams,
            "num_ns_seams": num_ns_seams,
            "total_biscuits": total_biscuits
        }

    def generate_biscuit_batch_mesh(self, total_biscuits: int) -> SolidMesh:
        """Arranges all required biscuit splines in a printable grid array."""
        if total_biscuits <= 0:
            return SolidMesh()

        d = self.config.dowel
        b_len = d.biscuit_length
        b_wid = d.biscuit_width
        b_thk = d.biscuit_thickness

        spacing = 5.0 # mm gap between biscuits on print bed
        cols_in_batch = math.ceil(math.sqrt(total_biscuits))
        batch_mesh = SolidMesh()

        for idx in range(total_biscuits):
            bx = idx % cols_in_batch
            by = idx // cols_in_batch

            x_offset = bx * (b_len + spacing)
            y_offset = by * (b_wid + spacing)

            single = generate_flat_biscuit(
                thickness_mm=b_thk,
                width_mm=b_wid,
                length_mm=b_len,
                chamfer_mm=d.lead_in_chamfer
            )
            # Translate to batch position
            single.vertices[:, 0] += x_offset
            single.vertices[:, 1] += y_offset
            batch_mesh.append(single)

        return batch_mesh

    def generate_landmark_pins_batch_mesh(self, num_pins: int) -> SolidMesh:
        """Arranges all required 3D landmark marker pins in a printable grid array on Z=0."""
        if num_pins <= 0:
            return SolidMesh()

        spacing = 8.0
        cols_in_batch = math.ceil(math.sqrt(num_pins))
        batch_mesh = SolidMesh()

        for idx in range(num_pins):
            px = idx % cols_in_batch
            py = idx // cols_in_batch
            pin_mesh = generate_landmark_pin_mesh(zero_base_for_printing=True)
            pin_mesh.vertices[:, 0] += (px - (cols_in_batch - 1) / 2.0) * spacing
            pin_mesh.vertices[:, 1] += (py - (math.ceil(num_pins / cols_in_batch) - 1) / 2.0) * spacing
            batch_mesh.append(pin_mesh)

        return batch_mesh

    def process_and_export_all(
        self,
        full_elev_grid: np.ndarray,
        output_dir: str
    ) -> Dict[str, Any]:
        """Executes full tiling, mesh generation, pocket embedding, and exports all STLs.
        
        Args:
            full_elev_grid: (R, C) elevation array covering the entire canvas.
            output_dir: Destination folder.
            
        Returns:
            Dict containing generated file paths, tile metadata, and assembly instructions.
        """
        tiles_dir = os.path.join(output_dir, "tiles")
        acc_dir = os.path.join(output_dir, "accessories")
        os.makedirs(tiles_dir, exist_ok=True)
        os.makedirs(acc_dir, exist_ok=True)

        raw_min_elev = float(np.min(full_elev_grid))
        raw_max_elev = float(np.max(full_elev_grid))
        if raw_min_elev < -50.0 and raw_max_elev > 0.0:
            global_min_elev = 0.0
            effective_full_grid = np.maximum(full_elev_grid, 0.0)
        else:
            global_min_elev = raw_min_elev
            effective_full_grid = full_elev_grid

        # Calculate unified Z scale across the entire canvas so all tiles match elevation exactly
        z_scale = calculate_z_scale(
            effective_full_grid,
            self.config.bbox or BoundingBox(south=0, west=0, north=1, east=1),
            self.config.canvas.width_mm,
            self.config.canvas.vertical_exaggeration,
            self.config.canvas.target_relief_height_mm
        )

        # Fetch urban blocks & street grid relief if enabled
        blocks = []
        if getattr(self.config.canvas, "blocks_enabled", False) and self.config.bbox:
            try:
                blocks = fetch_urban_blocks(
                    bbox=self.config.bbox,
                    canvas_w_mm=self.config.canvas.width_mm,
                    canvas_d_mm=self.config.canvas.depth_mm,
                    groove_w_mm=getattr(self.config.canvas, "block_groove_width_mm", 1.2),
                    min_h_mm=getattr(self.config.canvas, "block_min_height_mm", 2.0),
                    max_h_mm=getattr(self.config.canvas, "block_max_height_mm", 6.0),
                )
            except Exception as be:
                print(f"[WARN] Could not fetch urban blocks: {be}")

        partitioned = self.partition_elevation_grid(full_elev_grid)
        tile_manifest = []
        total_pockets_embedded = 0
        all_sockets_carved = []
        full_assembly_mesh = SolidMesh()
        exploded_assembly_mesh = SolidMesh()
        explode_gap_mm = 20.0
        half_canvas_w = self.config.canvas.width_mm / 2.0
        half_canvas_d = self.config.canvas.depth_mm / 2.0

        for tile, sub_grid in partitioned:
            active_seams = {
                "west": tile.col_idx > 0,
                "east": tile.col_idx < (self.cols - 1),
                "south": tile.row_idx > 0,
                "north": tile.row_idx < (self.rows - 1),
            }
            tile_clip_box_norm = (
                (
                    tile.col_idx / self.cols,
                    tile.row_idx / self.rows,
                    (tile.col_idx + 1) / self.cols,
                    (tile.row_idx + 1) / self.rows,
                )
                if (self.cols > 1 or self.rows > 1)
                else None
            )

            tile_mesh = generate_terrain_mesh(
                elev_grid=sub_grid,
                bbox=tile.bbox,
                width_mm=tile.width_mm,
                depth_mm=tile.depth_mm,
                base_height_mm=self.config.canvas.base_height_mm,
                vertical_exaggeration=self.config.canvas.vertical_exaggeration,
                target_relief_height_mm=self.config.canvas.target_relief_height_mm,
                topography_enabled=self.config.canvas.topography_enabled,
                base_shape=self.config.canvas.base_shape,
                base_sides=self.config.canvas.base_sides,
                rotation_deg=self.config.canvas.rotation_deg,
                boundary_geojson=self.config.canvas.boundary_geojson,
                global_min_elev=global_min_elev,
                global_z_scale=z_scale,
                active_seams=active_seams,
                dowel_config=self.config.dowel,
                tile_clip_box_norm=tile_clip_box_norm,
                route_waypoints_latlon=self.config.canvas.path_waypoints,
                landmark_pins_latlon=self.config.canvas.landmarks,
                tolerance_config=self.config.tolerances,
                global_bbox=self.config.bbox,
                global_width_mm=self.config.canvas.width_mm,
                global_depth_mm=self.config.canvas.depth_mm,
                tile_offset_xy_mm=(tile.x_min_mm, tile.y_min_mm)
            )

            pockets_list = getattr(tile_mesh, "pockets_created", [])
            sockets_list = getattr(tile_mesh, "sockets_carved", [])
            total_pockets_embedded += len(pockets_list)

            # Extrude urban blocks within this tile slice
            if blocks:
                for blk in blocks:
                    b_lat, b_lon = blk.center
                    if (tile.bbox.south <= b_lat <= tile.bbox.north and
                        tile.bbox.west <= b_lon <= tile.bbox.east):
                        try:
                            b_mesh = extrude_block_mesh(
                                block=blk,
                                bbox=tile.bbox,
                                width_mm=tile.width_mm,
                                depth_mm=tile.depth_mm,
                                z_ground=self.config.canvas.base_height_mm,
                                rotation_deg=self.config.canvas.rotation_deg
                            )
                            if b_mesh:
                                tile_mesh.append(b_mesh)
                        except Exception:
                            pass

            # 1. Append world-space copy to full_assembly_mesh and exploded_assembly_mesh
            if len(tile_mesh.vertices) > 0:
                world_verts = tile_mesh.vertices.copy()
                world_verts[:, 0] += tile.x_min_mm - half_canvas_w
                world_verts[:, 1] += tile.y_min_mm - half_canvas_d
                full_assembly_mesh.append(SolidMesh(world_verts, tile_mesh.faces.copy()))

                exp_dx = (tile.col_idx - (self.cols - 1) / 2.0) * explode_gap_mm
                exp_dy = (tile.row_idx - (self.rows - 1) / 2.0) * explode_gap_mm
                exp_verts = world_verts.copy()
                exp_verts[:, 0] += exp_dx
                exp_verts[:, 1] += exp_dy
                exploded_assembly_mesh.append(SolidMesh(exp_verts, tile_mesh.faces.copy()))

                # Place positive 3D landmark pins into full_assembly (seated) and exploded_assembly (+15mm Z hover)
                for sk in sockets_list:
                    wx = tile.x_min_mm + sk["x_mm"] - half_canvas_w
                    wy = tile.y_min_mm + sk["y_mm"] - half_canvas_d
                    wz = sk["z_surface_mm"]

                    pin_seated = generate_landmark_pin_mesh(zero_base_for_printing=False)
                    pin_seated.vertices[:, 0] += wx
                    pin_seated.vertices[:, 1] += wy
                    pin_seated.vertices[:, 2] += wz
                    full_assembly_mesh.append(pin_seated)

                    pin_exploded = generate_landmark_pin_mesh(zero_base_for_printing=False)
                    pin_exploded.vertices[:, 0] += wx + exp_dx
                    pin_exploded.vertices[:, 1] += wy + exp_dy
                    pin_exploded.vertices[:, 2] += wz + 15.0
                    exploded_assembly_mesh.append(pin_exploded)

                # Place positive biscuit spline in the exploded gap for east/north seams
                if self.config.dowel.enabled and pockets_list:
                    d = self.config.dowel
                    b_thk = d.biscuit_thickness
                    b_wid = d.biscuit_width
                    b_len = d.biscuit_length
                    for pk in pockets_list:
                        if pk["seam"] == "east":
                            bisc = generate_flat_biscuit(b_thk, b_wid, b_len, d.lead_in_chamfer)
                            # Rotate 90 deg in XY so length spans X seam and width spans Y (det = +1)
                            vx = bisc.vertices[:, 0].copy()
                            vy = bisc.vertices[:, 1].copy()
                            bisc.vertices[:, 0] = -vy
                            bisc.vertices[:, 1] = vx
                            bx_w = tile.x_min_mm + pk["center_xy"][0] - half_canvas_w + exp_dx + explode_gap_mm / 2.0
                            by_w = tile.y_min_mm + pk["center_xy"][1] - half_canvas_d + exp_dy
                            bisc.vertices[:, 0] += bx_w
                            bisc.vertices[:, 1] += by_w
                            bisc.vertices[:, 2] += pk["z_range"][0] + 0.08
                            exploded_assembly_mesh.append(bisc)
                        elif pk["seam"] == "north":
                            bisc = generate_flat_biscuit(b_thk, b_wid, b_len, d.lead_in_chamfer)
                            bx_w = tile.x_min_mm + pk["center_xy"][0] - half_canvas_w + exp_dx
                            by_w = tile.y_min_mm + pk["center_xy"][1] - half_canvas_d + exp_dy + explode_gap_mm / 2.0
                            bisc.vertices[:, 0] += bx_w
                            bisc.vertices[:, 1] += by_w
                            bisc.vertices[:, 2] += pk["z_range"][0] + 0.08
                            exploded_assembly_mesh.append(bisc)

                # 2. Center individual tile at (X=0, Y=0) so opening any single tile in FreeCAD
                # or Bambu Studio places its landmass directly at the origin (0, 0)
                min_pt, max_pt = tile_mesh.bounds
                cx = float((min_pt[0] + max_pt[0]) / 2.0)
                cy = float((min_pt[1] + max_pt[1]) / 2.0)
                tile_mesh.vertices[:, 0] -= cx
                tile_mesh.vertices[:, 1] -= cy

                for sk in sockets_list:
                    sk_entry = dict(sk)
                    sk_entry["tile_col"] = tile.col_idx
                    sk_entry["tile_row"] = tile.row_idx
                    sk_entry["tile_centered_x_mm"] = round(sk["x_mm"] - cx, 2)
                    sk_entry["tile_centered_y_mm"] = round(sk["y_mm"] - cy, 2)
                    all_sockets_carved.append(sk_entry)

            # Export tile STL
            tile_filename = f"tile_col{tile.col_idx}_row{tile.row_idx}.stl"
            tile_path = os.path.join(tiles_dir, tile_filename)
            tile_mesh.export_stl(tile_path, binary=True)

            dims = tile_mesh.dimensions
            tile_manifest.append({
                "col": tile.col_idx,
                "row": tile.row_idx,
                "filename": tile_filename,
                "path": tile_path,
                "width_mm": float(dims[0]),
                "depth_mm": float(dims[1]),
                "height_mm": float(dims[2]),
                "pockets_count": len(pockets_list),
                "pockets": pockets_list,
                "sockets_count": len(sockets_list),
                "sockets": sockets_list,
                "file_size_bytes": os.path.getsize(tile_path)
            })

        # Generate and export 3D Route Inlay Strip if path_waypoints has >= 2 points
        route_inlay_path = None
        route_inlay_size = 0
        if self.config.canvas.path_waypoints and len(self.config.canvas.path_waypoints) >= 2 and self.config.bbox:
            tol = self.config.tolerances
            inlay_mesh, _ = generate_path_strip_and_cavity(
                waypoints_lat_lon=self.config.canvas.path_waypoints,
                bbox=self.config.bbox,
                width_mm=self.config.canvas.width_mm,
                depth_mm=self.config.canvas.depth_mm,
                elev_grid=full_elev_grid,
                z_scale=z_scale,
                base_height_mm=self.config.canvas.base_height_mm,
                path_width_mm=tol.path_default_width,
                path_depth_mm=tol.path_default_depth,
                clearance_mm=tol.path_joint_clearance,
                tactile_offset_mm=tol.path_top_offset,
                global_min_elev=global_min_elev,
                rotation_deg=self.config.canvas.rotation_deg
            )
            if len(inlay_mesh.vertices) > 0:
                # World-space copy for full_assembly (seated) and exploded_assembly (+15mm Z hover)
                inlay_world_v = inlay_mesh.vertices.copy()
                inlay_world_v[:, 0] -= half_canvas_w
                inlay_world_v[:, 1] -= half_canvas_d
                full_assembly_mesh.append(SolidMesh(inlay_world_v, inlay_mesh.faces.copy()))

                inlay_exp_v = inlay_world_v.copy()
                inlay_exp_v[:, 2] += 15.0
                exploded_assembly_mesh.append(SolidMesh(inlay_exp_v, inlay_mesh.faces.copy()))

                # Center route_inlay.stl at (X=0, Y=0, Z_min=0) for print bed slicing
                r_min, r_max = inlay_mesh.bounds
                inlay_mesh.vertices[:, 0] -= float((r_min[0] + r_max[0]) / 2.0)
                inlay_mesh.vertices[:, 1] -= float((r_min[1] + r_max[1]) / 2.0)
                inlay_mesh.vertices[:, 2] -= float(r_min[2])
                route_inlay_path = os.path.join(acc_dir, "route_inlay.stl")
                inlay_mesh.export_stl(route_inlay_path, binary=True)
                route_inlay_size = os.path.getsize(route_inlay_path)

        # Generate and export 3D Landmark Pins batch if any landmarks were added
        num_pins_to_export = max(len(all_sockets_carved), len(self.config.canvas.landmarks or []))
        pins_path = None
        pins_file_size = 0
        if num_pins_to_export > 0:
            pins_batch_mesh = self.generate_landmark_pins_batch_mesh(num_pins_to_export)
            pins_path = os.path.join(acc_dir, "landmark_pins.stl")
            pins_batch_mesh.export_stl(pins_path, binary=True)
            pins_file_size = os.path.getsize(pins_path)

        # Export full assembly and exploded assembly (with biscuit dowels, route inlay, and landmark pins)
        full_asm_path = os.path.join(output_dir, "full_assembly.stl")
        exploded_asm_path = os.path.join(output_dir, "exploded_assembly.stl")
        if len(full_assembly_mesh.vertices) > 0:
            full_assembly_mesh.export_stl(full_asm_path, binary=True)
        if len(exploded_assembly_mesh.vertices) > 0:
            exploded_assembly_mesh.export_stl(exploded_asm_path, binary=True)

        # Generate and export biscuits
        biscuit_info = self.calculate_biscuit_placements()
        total_biscuits = max(biscuit_info["total_biscuits"], total_pockets_embedded // 2)
        biscuit_path = os.path.join(acc_dir, "biscuit_splines.stl")

        if self.config.dowel.enabled and total_biscuits > 0:
            biscuit_batch_mesh = self.generate_biscuit_batch_mesh(total_biscuits)
            biscuit_batch_mesh.export_stl(biscuit_path, binary=True)
            biscuit_file_size = os.path.getsize(biscuit_path)
        else:
            biscuit_file_size = 0

        # Generate Markdown assembly guide
        guide_path = os.path.join(output_dir, "ASSEMBLY_GUIDE.md")
        with open(guide_path, "w", encoding="utf-8") as f:
            f.write("# MapMaker 3D Assembly & Print Guide\n\n")
            if getattr(self.config, "location_name", None):
                f.write(f"**Location**: {self.config.location_name}\n")
            f.write(f"**Target Canvas Size**: {self.config.canvas.width_mm:.1f} x {self.config.canvas.depth_mm:.1f} mm\n")
            f.write(f"**Tiling Grid**: {self.cols} Columns x {self.rows} Rows ({len(tile_manifest)} total tiles)\n")
            f.write(f"**Print Bed Allocation**: ~{tile_manifest[0]['width_mm']:.1f} x {tile_manifest[0]['depth_mm']:.1f} mm per tile (Fits within {self.config.printer.name})\n")
            f.write(f"**Total Biscuits Needed**: {total_biscuits} ({biscuit_info['pockets_per_edge']} per internal seam)\n")
            if route_inlay_path:
                f.write(f"**Route Inlay Strip**: `accessories/{os.path.basename(route_inlay_path)}` (Press-fits into the 2.40 mm recessed terrain trench)\n")
            if pins_path:
                f.write(f"**Landmark Pins**: {num_pins_to_export} pins in `accessories/{os.path.basename(pins_path)}` (Plug into pre-bored Ø2.30 mm terrain sockets)\n")
            f.write("\n## Tile Layout Matrix\n\n")
            f.write("```\n")
            for r in reversed(range(self.rows)):
                row_str = " | ".join([f"[Col {c}, Row {r}]" for c in range(self.cols)])
                f.write(f"North  {row_str}\n")
            f.write("South\n```\n\n")
            if all_sockets_carved:
                f.write("## Landmark Pin Socket Locations\n\n")
                for idx, sk in enumerate(all_sockets_carved, 1):
                    f.write(
                        f"- **Pin {idx} ({sk['name']})**: Tile `[Col {sk['tile_col']}, Row {sk['tile_row']}]` "
                        f"at `(X={sk['tile_centered_x_mm']} mm, Y={sk['tile_centered_y_mm']} mm, Z={sk['z_surface_mm']} mm)` "
                        f"— Ø{sk['diameter_mm']} mm blind socket\n"
                    )
                f.write("\n")
            f.write("## Slicing & Printing Notes (Bambu Lab A1)\n")
            f.write("1. **Orientation**: Print all tiles flat on the bed (Z=0 on the build plate). Each tile is centered at (0, 0) for instant framing in FreeCAD and Bambu Studio.\n")
            f.write("2. **Infill**: 10-15% Gyroid infill is recommended for solid rigidity with low filament weight.\n")
            f.write(f"3. **Biscuits**: Print `{os.path.basename(biscuit_path)}` in PLA/PETG. Slide them into the mating pockets with a dab of CA glue.\n")
            if route_inlay_path:
                f.write("4. **Route Placement**: Print `accessories/route_inlay.stl` in a contrasting accent color and press it directly into the matching recessed channel on the terrain.\n")
            if pins_path:
                f.write("5. **Landmark Pin Placement**: Print `accessories/landmark_pins.stl` in an accent color and push the Ø2.00 mm pegs into the pre-bored Ø2.30 mm socket holes on the terrain.\n")
            f.write("6. **Assembly Previews**: Open `full_assembly.stl` or `exploded_assembly.stl` in FreeCAD to view all tiles, biscuit splines, route inlays, and landmark pins together.\n")

        return {
            "num_tiles": len(tile_manifest),
            "cols": self.cols,
            "rows": self.rows,
            "tiles": tile_manifest,
            "full_assembly": full_asm_path,
            "exploded_assembly": exploded_asm_path,
            "biscuits": {
                "total_count": total_biscuits,
                "path": biscuit_path,
                "file_size_bytes": biscuit_file_size
            },
            "route_inlay": {
                "path": route_inlay_path,
                "file_size_bytes": route_inlay_size
            },
            "landmark_pins": {
                "total_count": num_pins_to_export,
                "sockets_carved": all_sockets_carved,
                "path": pins_path,
                "file_size_bytes": pins_file_size
            },
            "assembly_guide": guide_path
        }
