"""Multi-tile grid partitioning, coaxial biscuit jointing, multi-part .3mf packaging,
and 4-view diagnostic preview engine for MapMaker 3D.

Splits geographic canvases into printable chunks conforming to the target build envelope,
automatically embedding alignment pockets, keyhole hangers, urban/building relief,
gallery frames, 3D embossed title plaques, route inlays, and landmark pins.
"""

import os
import math
import shutil
import numpy as np
from typing import List, Tuple, Dict, Any, Optional
import shapely
from shapely.geometry import box, shape, Polygon, MultiPolygon
import shapely.affinity

from .config import MapMakerConfig, TileSlice, BoundingBox
from .mesh import (
    SolidMesh,
    generate_terrain_mesh,
    generate_flat_biscuit,
    generate_landmark_pin_mesh,
    generate_path_strip_and_cavity,
    generate_flat_tile_route_strip,
    generate_gallery_frame_and_plaque,
    compute_tile_base_polygon_mm,
    calculate_z_scale,
    extrude_building_mesh,
    extrude_block_mesh,
)
from .geo import fetch_osm_buildings
from .blocks import fetch_urban_blocks
from .export import export_3mf_assembly, create_export_zip
from .preview import generate_diagnostic_views_png
from .platform_utils import safe_remove_path


class TilingEngine:
    """Manages canvas partitioning, tile generation, and multi-part memorabilia export."""

    def __init__(self, config: MapMakerConfig):
        self.config = config
        self.cols, self.rows = config.calculate_tiling_grid()
        self.slices = config.generate_tile_slices()

    def partition_elevation_grid(self, full_elev_grid: np.ndarray) -> List[Tuple[TileSlice, np.ndarray]]:
        """Splits full canvas elevation grid into sub-grids with shared boundary samples."""
        full_rows, full_cols = full_elev_grid.shape
        partitioned = []

        for tile in self.slices:
            c = tile.col_idx
            r = tile.row_idx

            c0 = int(round(c * (full_cols - 1) / self.cols))
            c1 = int(round((c + 1) * (full_cols - 1) / self.cols)) + 1
            r0 = int(round(r * (full_rows - 1) / self.rows))
            r1 = int(round((r + 1) * (full_rows - 1) / self.rows)) + 1

            sub_grid = full_elev_grid[r0:r1, c0:c1].copy()
            partitioned.append((tile, sub_grid))

        return partitioned

    def calculate_biscuit_placements(self) -> Dict[str, Any]:
        """Calculates internal seam locations and nominal biscuit counts."""
        pockets_per_edge = 2 if max(
            self.config.canvas.width_mm / self.cols,
            self.config.canvas.depth_mm / self.rows
        ) >= 100.0 else 1

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
        """Arranges all required biscuit splines in a printable grid array on Z=0."""
        if total_biscuits <= 0:
            return SolidMesh()

        d = self.config.dowel
        b_len = min(d.biscuit_length, d.pocket_depth * 2.0 - 1.0)
        b_wid = d.biscuit_width
        b_thk = min(d.biscuit_thickness, d.pocket_height - 0.25)

        spacing = 5.0
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
            single.translate(x_offset, y_offset, 0.0)
            batch_mesh.append(single)

        return batch_mesh

    def generate_landmark_pins_batch_mesh(self, num_pins: int, wall_tilt_deg: float = 0.0) -> SolidMesh:
        """Arranges all required 3D landmark marker pins head-down on Z=0 for ultra-stable bed adhesion."""
        if num_pins <= 0:
            return SolidMesh()

        spacing = 9.0
        cols_in_batch = math.ceil(math.sqrt(num_pins))
        rows_in_batch = math.ceil(num_pins / cols_in_batch)
        batch_mesh = SolidMesh()

        for idx in range(num_pins):
            px = idx % cols_in_batch
            py = idx // cols_in_batch
            pin_mesh = generate_landmark_pin_mesh(
                zero_base_for_printing=True,
                wall_hanging_tilt_deg=wall_tilt_deg
            )
            pin_mesh.translate(
                (px - (cols_in_batch - 1) / 2.0) * spacing,
                (py - (rows_in_batch - 1) / 2.0) * spacing,
                0.0
            )
            batch_mesh.append(pin_mesh)

        return batch_mesh

    def _compute_tile_interior_clip_poly(
        self,
        tile: TileSlice,
        tile_clip_box_norm: Optional[Tuple[float, float, float, float]]
    ) -> Any:
        """Computes safe interior clipping region (in local tile mm) for urban blocks and buildings
        so structures never overhang outside coastlines, circles, hexagons, or gallery frames!
        """
        cv = self.config.canvas
        tile_inner = box(0.45, 0.45, tile.width_mm - 0.45, tile.depth_mm - 0.45)

        if cv.base_shape == "natural_border" and cv.boundary_geojson and self.config.bbox:
            try:
                geom = shape(cv.boundary_geojson)
                if not geom.is_valid:
                    geom = geom.buffer(0)
                eb = self.config.bbox
                ew, ed = cv.width_mm, cv.depth_mm
                gcx, gcy = ew * 0.5, ed * 0.5
                rad = math.radians(cv.rotation_deg)
                cos_r, sin_r = math.cos(rad), math.sin(rad)

                raw_polys = [geom] if geom.geom_type == "Polygon" else [p for p in getattr(geom, "geoms", []) if p.geom_type == "Polygon"]
                local_parts = []
                for p in raw_polys:
                    pts = []
                    for lon, lat in list(p.exterior.coords)[:-1]:
                        gx = (lon - eb.west) / max(1e-6, eb.lon_span) * ew
                        gy = (lat - eb.south) / max(1e-6, eb.lat_span) * ed
                        if abs(cv.rotation_deg) > 1e-4:
                            dx, dy = gx - gcx, gy - gcy
                            gx = gcx + dx * cos_r + dy * sin_r
                            gy = gcy - dx * sin_r + dy * cos_r
                        pts.append((gx - tile.x_min_mm, gy - tile.y_min_mm))
                    if len(pts) >= 3:
                        lp = Polygon(pts).buffer(-0.8).intersection(tile_inner)
                        if not lp.is_empty:
                            local_parts.append(lp)
                if local_parts:
                    return shapely.ops.unary_union(local_parts)
            except Exception:
                pass
            return tile_inner

        base_p = compute_tile_base_polygon_mm(
            base_shape=cv.base_shape,
            base_sides=cv.base_sides,
            width_mm=tile.width_mm,
            depth_mm=tile.depth_mm,
            tile_clip_box_norm=tile_clip_box_norm
        )
        inset = (cv.frame_width_mm + 0.6) if cv.frame_enabled else 0.8
        eroded = base_p.buffer(-inset) if base_p.area > 20.0 else base_p
        clipped = eroded.intersection(tile_inner) if not eroded.is_empty else tile_inner

        # Keep urban blocks & 3D buildings clear of the front Title/Subtitle Plaque!
        if (getattr(cv, "title_text", "").strip() or getattr(cv, "subtitle_text", "").strip()) and cv.base_shape != "natural_border":
            pw = min(cv.width_mm * 0.78, 192.0)
            ph = 26.0 if (cv.title_text.strip() and cv.subtitle_text.strip()) else 18.5
            margin_s = (cv.frame_width_mm + 3.5) if cv.frame_enabled else 6.0
            if cv.base_shape in ("circle", "polygon"):
                margin_s = max(margin_s, cv.depth_mm * 0.09)
            pcx = cv.width_mm * 0.5
            p_excl_global = box(pcx - pw * 0.5 - 1.5, 0.0, pcx + pw * 0.5 + 1.5, margin_s + ph + 1.8)
            p_excl_local = shapely.affinity.translate(p_excl_global, xoff=-tile.x_min_mm, yoff=-tile.y_min_mm)
            clipped = clipped.difference(p_excl_local)

        return clipped

    def process_and_export_all(
        self,
        full_elev_grid: np.ndarray,
        output_dir: str,
        clean_output_dir: bool = False,
        generate_preview: bool = True,
        export_3mf: bool = True,
        create_zip: bool = False
    ) -> Dict[str, Any]:
        """Executes full tiling, mesh solidification, accessories batching, .3mf multi-part
        export, 4-view diagnostic rendering, and assembly guide generation.
        """
        if clean_output_dir and os.path.exists(output_dir):
            for sub in ("tiles", "accessories", "previews"):
                safe_remove_path(os.path.join(output_dir, sub))
            for fn in ("full_assembly.stl", "exploded_assembly.stl", "full_assembly.3mf", "mapmaker_package.zip"):
                safe_remove_path(os.path.join(output_dir, fn))

        tiles_dir = os.path.join(output_dir, "tiles")
        acc_dir = os.path.join(output_dir, "accessories")
        prev_dir = os.path.join(output_dir, "previews")
        os.makedirs(tiles_dir, exist_ok=True)
        os.makedirs(acc_dir, exist_ok=True)

        cv = self.config.canvas
        if cv.lock_aspect_ratio and self.config.bbox:
            self.config.apply_aspect_ratio_lock()
            self.cols, self.rows = self.config.calculate_tiling_grid()
            self.slices = self.config.generate_tile_slices()

        raw_min_elev = float(np.min(full_elev_grid))
        raw_max_elev = float(np.max(full_elev_grid))
        clamp_thresh = -0.5 if getattr(cv, "depress_water", False) else -50.0
        if raw_min_elev < clamp_thresh and raw_max_elev > 2.0:
            global_min_elev = 0.0
            effective_full_grid = np.maximum(full_elev_grid, 0.0)
        else:
            global_min_elev = raw_min_elev
            effective_full_grid = full_elev_grid

        z_scale = calculate_z_scale(
            effective_full_grid,
            self.config.bbox or BoundingBox(south=0, west=0, north=1, east=1),
            cv.width_mm,
            cv.vertical_exaggeration,
            cv.target_relief_height_mm
        )

        # Resolve urban mode ("none", "blocks", or "buildings")
        urban_mode = getattr(cv, "urban_mode", "none")
        if urban_mode == "none":
            if getattr(cv, "blocks_enabled", False):
                urban_mode = "blocks"
            elif getattr(cv, "buildings_enabled", False):
                urban_mode = "buildings"

        blocks = []
        buildings = []
        if urban_mode == "blocks" and self.config.bbox:
            try:
                blocks = fetch_urban_blocks(
                    bbox=self.config.bbox,
                    canvas_w_mm=cv.width_mm,
                    canvas_d_mm=cv.depth_mm,
                    groove_w_mm=getattr(cv, "block_groove_width_mm", 1.2),
                    min_h_mm=getattr(cv, "block_min_height_mm", 2.0),
                    max_h_mm=getattr(cv, "block_max_height_mm", 6.0),
                )
            except Exception as be:
                print(f"[WARN] Could not fetch urban blocks: {be}")
        elif urban_mode == "buildings" and self.config.bbox:
            try:
                buildings = fetch_osm_buildings(self.config.bbox, max_buildings=2200)
            except Exception as bld_err:
                print(f"[WARN] Could not fetch 3D OSM buildings: {bld_err}")

        is_wall_hanging = (getattr(cv, "viewing_orientation", "tabletop") == "wall_hanging")
        want_keyhole = is_wall_hanging and getattr(cv, "keyhole_hanger", True)
        wall_pin_tilt = 20.0 if is_wall_hanging else 0.0

        partitioned = self.partition_elevation_grid(full_elev_grid)
        tile_manifest = []
        east_north_pockets_count = 0
        all_sockets_carved = []
        keyholes_carved = []

        # Separate world-space component meshes for color-coded .3mf & 4-view diagnostic render!
        world_terrain_only = SolidMesh()
        world_urban_only = SolidMesh()
        world_frame_only = SolidMesh()
        world_letters_only = SolidMesh()
        world_pins_only = SolidMesh()
        world_route_only = SolidMesh()

        full_assembly_mesh = SolidMesh()
        exploded_assembly_mesh = SolidMesh()
        flat_route_strips: List[SolidMesh] = []

        explode_gap_mm = 20.0
        half_canvas_w = cv.width_mm / 2.0
        half_canvas_d = cv.depth_mm / 2.0

        frame_top_z = cv.base_height_mm + (cv.water_step_mm if cv.depress_water else 0.0) + cv.frame_height_mm

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

            embed_kh_here = want_keyhole and (tile.row_idx == self.rows - 1)

            terrain_part = generate_terrain_mesh(
                elev_grid=sub_grid,
                bbox=tile.bbox,
                width_mm=tile.width_mm,
                depth_mm=tile.depth_mm,
                base_height_mm=cv.base_height_mm,
                vertical_exaggeration=cv.vertical_exaggeration,
                target_relief_height_mm=cv.target_relief_height_mm,
                topography_enabled=cv.topography_enabled,
                base_shape=cv.base_shape,
                base_sides=cv.base_sides,
                rotation_deg=cv.rotation_deg,
                boundary_geojson=cv.boundary_geojson,
                global_min_elev=global_min_elev,
                global_z_scale=z_scale,
                active_seams=active_seams,
                dowel_config=self.config.dowel,
                tile_clip_box_norm=tile_clip_box_norm,
                route_waypoints_latlon=cv.path_waypoints,
                landmark_pins_latlon=cv.landmarks,
                tolerance_config=self.config.tolerances,
                global_bbox=self.config.bbox,
                global_width_mm=cv.width_mm,
                global_depth_mm=cv.depth_mm,
                tile_offset_xy_mm=(tile.x_min_mm, tile.y_min_mm),
                global_elev_grid=full_elev_grid,
                path_style=getattr(cv, "path_style", "flat_strip"),
                depress_water=getattr(cv, "depress_water", False),
                water_step_mm=getattr(cv, "water_step_mm", 0.84),
                embed_keyhole=embed_kh_here
            )

            pockets_list = getattr(terrain_part, "pockets_created", [])
            sockets_list = getattr(terrain_part, "sockets_carved", [])
            kh_info = getattr(terrain_part, "keyhole_created", None)
            local_z_sampler = getattr(terrain_part, "sample_z_func", None)

            if kh_info is not None:
                keyholes_carved.append({"tile_col": tile.col_idx, "tile_row": tile.row_idx, **kh_info})

            east_north_pockets_count += sum(1 for pk in pockets_list if pk["seam"] in ("east", "north"))

            # Clipping region for urban structures and flat route strips inside this tile
            interior_clip = self._compute_tile_interior_clip_poly(tile, tile_clip_box_norm)
            tile_urban_mesh = SolidMesh()

            if blocks and self.config.bbox:
                for blk in blocks:
                    try:
                        b_mesh = extrude_block_mesh(
                            block=blk,
                            bbox=tile.bbox,
                            width_mm=tile.width_mm,
                            depth_mm=tile.depth_mm,
                            z_ground=cv.base_height_mm,
                            rotation_deg=cv.rotation_deg,
                            sample_z_func=local_z_sampler,
                            clip_poly_mm=interior_clip,
                            global_bbox=self.config.bbox,
                            global_width_mm=cv.width_mm,
                            global_depth_mm=cv.depth_mm,
                            tile_offset_xy_mm=(tile.x_min_mm, tile.y_min_mm)
                        )
                        if b_mesh:
                            tile_urban_mesh.append(b_mesh)
                    except Exception:
                        pass

            elif buildings and self.config.bbox:
                for bldg in buildings:
                    try:
                        b_mesh, _ = extrude_building_mesh(
                            building=bldg,
                            bbox=tile.bbox,
                            width_mm=tile.width_mm,
                            depth_mm=tile.depth_mm,
                            z_ground=cv.base_height_mm,
                            z_scale=z_scale,
                            building_height_scale=cv.building_height_scale,
                            min_printable_wall=self.config.printer.min_printable_wall,
                            rotation_deg=cv.rotation_deg,
                            sample_z_func=local_z_sampler,
                            clip_poly_mm=interior_clip,
                            global_bbox=self.config.bbox,
                            global_width_mm=cv.width_mm,
                            global_depth_mm=cv.depth_mm,
                            tile_offset_xy_mm=(tile.x_min_mm, tile.y_min_mm)
                        )
                        if b_mesh:
                            tile_urban_mesh.append(b_mesh)
                    except Exception:
                        pass

            # Gallery shadowbox frame + 3D embossed title/subtitle plaque
            tile_frame_mesh, tile_letters_mesh = generate_gallery_frame_and_plaque(
                base_shape=cv.base_shape,
                base_sides=cv.base_sides,
                global_width_mm=cv.width_mm,
                global_depth_mm=cv.depth_mm,
                tile_offset_xy_mm=(tile.x_min_mm, tile.y_min_mm),
                tile_width_mm=tile.width_mm,
                tile_depth_mm=tile.depth_mm,
                tile_clip_box_norm=tile_clip_box_norm,
                base_height_mm=cv.base_height_mm,
                frame_enabled=getattr(cv, "frame_enabled", False),
                frame_width_mm=getattr(cv, "frame_width_mm", 4.20),
                frame_top_z_mm=frame_top_z,
                title_text=getattr(cv, "title_text", ""),
                subtitle_text=getattr(cv, "subtitle_text", ""),
                sample_z_func=local_z_sampler
            )

            # Generate flat-on-bed snap-in route strip segment for this tile (fits <=250mm Bambu A1 bed!)
            if cv.path_waypoints and len(cv.path_waypoints) >= 2 and self.config.bbox and getattr(cv, "path_style", "flat_strip") != "raised_ridge":
                strip_seg = generate_flat_tile_route_strip(
                    waypoints_lat_lon=cv.path_waypoints,
                    global_bbox=self.config.bbox,
                    global_width_mm=cv.width_mm,
                    global_depth_mm=cv.depth_mm,
                    tile_offset_xy_mm=(tile.x_min_mm, tile.y_min_mm),
                    tile_clip_poly_mm=interior_clip,
                    path_width_mm=max(1.2, self.config.tolerances.path_default_width - 0.08),
                    strip_thickness_mm=1.12,
                    rotation_deg=cv.rotation_deg,
                    landmark_pins_latlon=cv.landmarks
                )
                if strip_seg.num_faces > 0:
                    flat_route_strips.append(strip_seg)

            # Combine solid tile mesh for single-piece STL export
            tile_mesh = terrain_part.copy()
            tile_mesh.append(tile_urban_mesh)
            tile_mesh.append(tile_frame_mesh)
            tile_mesh.append(tile_letters_mesh)

            wx_shift = tile.x_min_mm - half_canvas_w
            wy_shift = tile.y_min_mm - half_canvas_d

            if terrain_part.num_vertices > 0:
                world_terrain_only.append(terrain_part.copy().translate(wx_shift, wy_shift, 0.0))
            if tile_urban_mesh.num_vertices > 0:
                world_urban_only.append(tile_urban_mesh.copy().translate(wx_shift, wy_shift, 0.0))
            if tile_frame_mesh.num_vertices > 0:
                world_frame_only.append(tile_frame_mesh.copy().translate(wx_shift, wy_shift, 0.0))
            if tile_letters_mesh.num_vertices > 0:
                world_letters_only.append(tile_letters_mesh.copy().translate(wx_shift, wy_shift, 0.0))

            if len(tile_mesh.vertices) > 0:
                world_tile = tile_mesh.copy().translate(wx_shift, wy_shift, 0.0)
                full_assembly_mesh.append(world_tile)

                exp_dx = (tile.col_idx - (self.cols - 1) / 2.0) * explode_gap_mm
                exp_dy = (tile.row_idx - (self.rows - 1) / 2.0) * explode_gap_mm
                exploded_assembly_mesh.append(world_tile.copy().translate(exp_dx, exp_dy, 0.0))

                for sk in sockets_list:
                    wx = tile.x_min_mm + sk["x_mm"] - half_canvas_w
                    wy = tile.y_min_mm + sk["y_mm"] - half_canvas_d
                    wz = sk["z_surface_mm"]

                    pin_seated = generate_landmark_pin_mesh(
                        zero_base_for_printing=False,
                        wall_hanging_tilt_deg=wall_pin_tilt
                    ).translate(wx, wy, wz)
                    full_assembly_mesh.append(pin_seated)
                    world_pins_only.append(pin_seated.copy())

                    pin_exploded = generate_landmark_pin_mesh(
                        zero_base_for_printing=False,
                        wall_hanging_tilt_deg=wall_pin_tilt
                    ).translate(wx + exp_dx, wy + exp_dy, wz + 15.0)
                    exploded_assembly_mesh.append(pin_exploded)

                if self.config.dowel.enabled and pockets_list:
                    d = self.config.dowel
                    b_thk = min(d.biscuit_thickness, d.pocket_height - 0.25)
                    b_wid = d.biscuit_width
                    b_len = min(d.biscuit_length, d.pocket_depth * 2.0 - 1.0)
                    for pk in pockets_list:
                        z_seat = 0.5 * (pk["z_range"][0] + pk["z_range"][1] - b_thk)
                        if pk["seam"] == "east":
                            bisc = generate_flat_biscuit(b_thk, b_wid, b_len, d.lead_in_chamfer)
                            vx = bisc.vertices[:, 0].copy()
                            vy = bisc.vertices[:, 1].copy()
                            bisc.vertices[:, 0] = -vy
                            bisc.vertices[:, 1] = vx
                            bx_w = tile.x_min_mm + pk["center_xy"][0] - half_canvas_w + exp_dx + explode_gap_mm / 2.0
                            by_w = tile.y_min_mm + pk["center_xy"][1] - half_canvas_d + exp_dy
                            bisc.translate(bx_w, by_w, z_seat)
                            exploded_assembly_mesh.append(bisc)
                        elif pk["seam"] == "north":
                            bisc = generate_flat_biscuit(b_thk, b_wid, b_len, d.lead_in_chamfer)
                            bx_w = tile.x_min_mm + pk["center_xy"][0] - half_canvas_w + exp_dx
                            by_w = tile.y_min_mm + pk["center_xy"][1] - half_canvas_d + exp_dy + explode_gap_mm / 2.0
                            by_w_adj = by_w
                            bisc.translate(bx_w, by_w_adj, z_seat)
                            exploded_assembly_mesh.append(bisc)

                # Center individual tile STL at (X=0, Y=0) for instant slicer & FreeCAD framing
                min_pt, max_pt = tile_mesh.bounds
                cx = float((min_pt[0] + max_pt[0]) / 2.0)
                cy = float((min_pt[1] + max_pt[1]) / 2.0)
                tile_mesh.translate(-cx, -cy, 0.0)

                for sk in sockets_list:
                    sk_entry = dict(sk)
                    sk_entry["tile_col"] = tile.col_idx
                    sk_entry["tile_row"] = tile.row_idx
                    sk_entry["tile_centered_x_mm"] = round(sk["x_mm"] - cx, 2)
                    sk_entry["tile_centered_y_mm"] = round(sk["y_mm"] - cy, 2)
                    all_sockets_carved.append(sk_entry)

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

        # Export 3D route visualization (for .3mf & assembly STLs) + flat-on-bed printable route_inlay.stl!
        route_inlay_path = None
        route_inlay_size = 0
        if cv.path_waypoints and len(cv.path_waypoints) >= 2 and self.config.bbox:
            tol = self.config.tolerances
            inlay_3d, _ = generate_path_strip_and_cavity(
                waypoints_lat_lon=cv.path_waypoints,
                bbox=self.config.bbox,
                width_mm=cv.width_mm,
                depth_mm=cv.depth_mm,
                elev_grid=full_elev_grid,
                z_scale=z_scale,
                base_height_mm=cv.base_height_mm,
                path_width_mm=tol.path_default_width,
                path_depth_mm=tol.path_default_depth,
                clearance_mm=tol.path_joint_clearance,
                tactile_offset_mm=0.65 if getattr(cv, "path_style", "flat_strip") == "raised_ridge" else tol.path_top_offset,
                global_min_elev=global_min_elev,
                rotation_deg=cv.rotation_deg,
                depress_water=getattr(cv, "depress_water", False),
                water_step_mm=getattr(cv, "water_step_mm", 0.84),
                landmark_pins_latlon=cv.landmarks
            )
            if inlay_3d.num_vertices > 0:
                inlay_world = inlay_3d.copy().translate(-half_canvas_w, -half_canvas_d, 0.0)
                world_route_only.append(inlay_world)
                full_assembly_mesh.append(inlay_world.copy())
                exploded_assembly_mesh.append(inlay_world.copy().translate(0.0, 0.0, 15.0))

            # Build flat-on-bed (Z=0), bed-fitting (`<=250mm`) printable `accessories/route_inlay.stl`
            if flat_route_strips:
                print_strip_batch = SolidMesh()
                cursor_x = 0.0
                for seg in flat_route_strips:
                    s_min, s_max = seg.bounds
                    sw = float(s_max[0] - s_min[0])
                    sc_y = float((s_min[1] + s_max[1]) * 0.5)
                    shifted = seg.copy().translate(-float(s_min[0]) + cursor_x, -sc_y, -float(s_min[2]))
                    print_strip_batch.append(shifted)
                    cursor_x += sw + 6.0
                b_min, b_max = print_strip_batch.bounds
                print_strip_batch.translate(
                    -float((b_min[0] + b_max[0]) * 0.5),
                    -float((b_min[1] + b_max[1]) * 0.5),
                    -float(b_min[2])
                )
                route_inlay_path = os.path.join(acc_dir, "route_inlay.stl")
                print_strip_batch.export_stl(route_inlay_path, binary=True)
                route_inlay_size = os.path.getsize(route_inlay_path)

        # Export head-down stable landmark pins batch
        num_pins_to_export = max(len(all_sockets_carved), len(cv.landmarks or []))
        pins_path = None
        pins_file_size = 0
        if num_pins_to_export > 0:
            pins_batch_mesh = self.generate_landmark_pins_batch_mesh(num_pins_to_export, wall_tilt_deg=wall_pin_tilt)
            pins_path = os.path.join(acc_dir, "landmark_pins.stl")
            pins_batch_mesh.export_stl(pins_path, binary=True)
            pins_file_size = os.path.getsize(pins_path)

        # Export full_assembly.stl and exploded_assembly.stl
        full_asm_path = os.path.join(output_dir, "full_assembly.stl")
        exploded_asm_path = os.path.join(output_dir, "exploded_assembly.stl")
        if full_assembly_mesh.num_vertices > 0:
            full_assembly_mesh.export_stl(full_asm_path, binary=True)
        if exploded_assembly_mesh.num_vertices > 0:
            exploded_assembly_mesh.export_stl(exploded_asm_path, binary=True)

        # Export alignment biscuits batch (exact count matching active interior seam pairs)
        biscuit_info = self.calculate_biscuit_placements()
        total_biscuits = east_north_pockets_count if east_north_pockets_count > 0 else biscuit_info["total_biscuits"]
        if self.cols == 1 and self.rows == 1:
            total_biscuits = 0
        biscuit_path = os.path.join(acc_dir, "biscuit_splines.stl")

        if self.config.dowel.enabled and total_biscuits > 0:
            biscuit_batch_mesh = self.generate_biscuit_batch_mesh(total_biscuits)
            biscuit_batch_mesh.export_stl(biscuit_path, binary=True)
            biscuit_file_size = os.path.getsize(biscuit_path)
        else:
            biscuit_file_size = 0

        # Assemble named multi-color component list for .3mf & 4-view diagnostic sheet
        color_parts = [
            {"name": "Terrain_Relief", "mesh": world_terrain_only, "color": "#2E8B57"},
            {"name": "Urban_Structures", "mesh": world_urban_only, "color": "#CBD5E1"},
            {"name": "Frame_And_Plaque", "mesh": world_frame_only, "color": "#1E293B"},
            {"name": "Title_Typography", "mesh": world_letters_only, "color": "#F8FAFC"},
            {"name": "Route_Path", "mesh": world_route_only, "color": "#FF5500"},
            {"name": "Landmark_Pins", "mesh": world_pins_only, "color": "#EF4444"},
        ]

        assembly_3mf_path = None
        if export_3mf:
            assembly_3mf_path = os.path.join(output_dir, "full_assembly.3mf")
            export_3mf_assembly(
                assembly_3mf_path,
                color_parts,
                assembly_name=(self.config.location_name or "MapMaker_3D").split(",")[0].strip(),
                bed_center_xy=(self.config.printer.bed_width * 0.5, self.config.printer.bed_depth * 0.5)
            )

        preview_png_path = None
        if generate_preview:
            os.makedirs(prev_dir, exist_ok=True)
            preview_png_path = os.path.join(prev_dir, "diagnostic_views.png")
            loc_hdr = (self.config.location_name or "MapMaker 3D").split(",")[0]
            generate_diagnostic_views_png(
                preview_png_path,
                color_parts,
                title_banner=f"MapMaker 3D — {loc_hdr} ({cv.width_mm:.0f} x {cv.depth_mm:.0f} mm, {self.cols}x{self.rows} Grid)"
            )

        # Generate Markdown assembly guide
        guide_path = os.path.join(output_dir, "ASSEMBLY_GUIDE.md")
        with open(guide_path, "w", encoding="utf-8") as f:
            f.write("# MapMaker 3D Assembly & Print Guide\n\n")
            if getattr(self.config, "location_name", None):
                f.write(f"**Location**: {self.config.location_name}\n")
            f.write(f"**Target Canvas Size**: {cv.width_mm:.1f} x {cv.depth_mm:.1f} mm\n")
            f.write(f"**Base Shape**: `{cv.base_shape}` | **Display Mode**: `{cv.viewing_orientation}`\n")
            f.write(f"**Tiling Grid**: {self.cols} Columns x {self.rows} Rows ({len(tile_manifest)} total tiles)\n")
            if tile_manifest:
                f.write(f"**Print Bed Allocation**: ~{tile_manifest[0]['width_mm']:.1f} x {tile_manifest[0]['depth_mm']:.1f} mm per tile (Fits within {self.config.printer.name})\n")
            f.write(f"**Total Biscuits Needed**: {total_biscuits}\n")
            if assembly_3mf_path and os.path.exists(assembly_3mf_path):
                f.write("**Multi-Color / Bambu Studio File**: `full_assembly.3mf` (Pre-grouped objects for 1-click AMS filament coloring)\n")
            if route_inlay_path:
                f.write(f"**Route Inlay Strip**: `accessories/{os.path.basename(route_inlay_path)}` (Prints 100% flat on Z=0; flexes and press-fits into the recessed terrain channel)\n")
            elif cv.path_waypoints and getattr(cv, "path_style", "") == "raised_ridge":
                f.write("**Route Trail**: Sculpted directly onto terrain as a raised +1.05 mm tactile ridge\n")
            if pins_path:
                f.write(f"**Landmark Pins**: {num_pins_to_export} pins in `accessories/{os.path.basename(pins_path)}` (Oriented head-down on flat Ø4.9 mm crown for rock-solid bed adhesion; zero supports/brims needed)\n")
            if keyholes_carved:
                f.write(f"**Wall-Hanging Keyholes**: {len(keyholes_carved)} rear screw-lock keyhole slot(s) embedded into Z=0 backplate\n")

            f.write("\n## Tile Layout Matrix\n\n```\n")
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
                        f"— Ø{sk['diameter_mm']} mm spot-faced blind socket\n"
                    )
                f.write("\n")

            f.write(f"## Slicing & Printing Notes ({self.config.printer.name})\n")
            f.write("1. **Orientation**: Print all tiles flat on the bed (`Z=0` on build plate). Every tile is origin-centered at `(0, 0)`.\n")
            f.write("2. **Layer Height & Infill**: `0.16 mm` Optimal layer height (or Adaptive Layer Height for smooth peaks) with `12%` Gyroid infill.\n")
            if getattr(cv, "depress_water", False) or getattr(cv, "title_text", ""):
                f.write("3. **Easy Single-Extruder Color Pop**: Add a filament pause/swap in Bambu Studio just above the water level (`Z ≈ 4.2 mm`) or on the top 5 layers of the raised 3D title plaque for crisp two-tone contrast even without an AMS!\n")
            if total_biscuits > 0:
                f.write(f"4. **Biscuits**: Print `accessories/{os.path.basename(biscuit_path)}` flat on the bed and slide into mating seam pockets with a drop of CA glue.\n")
            if route_inlay_path:
                f.write("5. **Route Strip**: Print `accessories/route_inlay.stl` in a bright accent color (1.12 mm thin flexible PLA) and press-fit it directly into the matching terrain channel.\n")
            if pins_path:
                f.write("6. **Landmark Pins**: Print `accessories/landmark_pins.stl` as-oriented (flat jewel crown on the bed) and press the Ø1.96 mm pegs into the Ø2.36 mm terrain sockets.\n")

        zip_path = None
        if create_zip:
            zip_path = create_export_zip(output_dir, os.path.join(output_dir, "mapmaker_package.zip"))

        return {
            "num_tiles": len(tile_manifest),
            "cols": self.cols,
            "rows": self.rows,
            "tiles": tile_manifest,
            "full_assembly": full_asm_path,
            "exploded_assembly": exploded_asm_path,
            "assembly_3mf": assembly_3mf_path,
            "diagnostic_preview": preview_png_path,
            "export_zip": zip_path,
            "keyholes": keyholes_carved,
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
