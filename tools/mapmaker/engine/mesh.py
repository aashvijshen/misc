"""3D Mesh generation, solidification, building extrusion, and path boolean engine for MapMaker 3D.

Constructs watertight (manifold) 3D meshes ready for slicing on Bambu Lab A1
and other FDM printers.
"""

import struct
import math
import numpy as np
from typing import List, Tuple, Dict, Any, Optional
import shapely
from shapely.geometry import Polygon, Point, MultiPolygon, LineString, shape, box
import shapely.ops
from scipy.spatial import Delaunay

from .config import BoundingBox, MapMakerConfig, CanvasConfig, ToleranceProfile, DowelProfile
from .geo import BuildingPolygon


class SolidMesh:
    """Represents a watertight triangular 3D surface mesh."""

    def __init__(self, vertices: Optional[np.ndarray] = None, faces: Optional[np.ndarray] = None):
        """
        Args:
            vertices: (N, 3) float32 numpy array.
            faces: (M, 3) int32 numpy array of triangle vertex indices.
        """
        if vertices is not None:
            self.vertices = np.array(vertices, dtype=np.float32)
        else:
            self.vertices = np.zeros((0, 3), dtype=np.float32)

        if faces is not None:
            self.faces = np.array(faces, dtype=np.int32)
        else:
            self.faces = np.zeros((0, 3), dtype=np.int32)

    @property
    def num_vertices(self) -> int:
        return len(self.vertices)

    @property
    def num_faces(self) -> int:
        return len(self.faces)

    @property
    def bounds(self) -> Tuple[np.ndarray, np.ndarray]:
        """Returns (min_xyz, max_xyz) bounding box."""
        if len(self.vertices) == 0:
            return np.zeros(3), np.zeros(3)
        return np.min(self.vertices, axis=0), np.max(self.vertices, axis=0)

    @property
    def dimensions(self) -> np.ndarray:
        min_pt, max_pt = self.bounds
        return max_pt - min_pt

    def compute_face_normals(self) -> np.ndarray:
        """Computes unit normal vectors for each triangular face."""
        v0 = self.vertices[self.faces[:, 0]]
        v1 = self.vertices[self.faces[:, 1]]
        v2 = self.vertices[self.faces[:, 2]]
        cross = np.cross(v1 - v0, v2 - v0)
        norm = np.linalg.norm(cross, axis=1, keepdims=True)
        norm[norm == 0] = 1.0
        return cross / norm

    def append(self, other: 'SolidMesh'):
        """Merges another mesh into this mesh."""
        if other.num_vertices == 0:
            return
        offset = self.num_vertices
        self.vertices = np.vstack([self.vertices, other.vertices])
        self.faces = np.vstack([self.faces, other.faces + offset])

    def export_stl(self, filepath: str, binary: bool = True):
        """Exports mesh to STL file (binary or ASCII)."""
        if binary:
            self._export_stl_binary(filepath)
        else:
            self._export_stl_ascii(filepath)

    def _export_stl_binary(self, filepath: str):
        """Writes high-speed binary STL."""
        num_faces = self.num_faces
        normals = self.compute_face_normals()

        with open(filepath, "wb") as f:
            header = b"MapMaker3D Solid Mesh Exporter" + b" " * 50
            f.write(header[:80])
            f.write(struct.pack("<I", num_faces))

            v0 = self.vertices[self.faces[:, 0]]
            v1 = self.vertices[self.faces[:, 1]]
            v2 = self.vertices[self.faces[:, 2]]

            record_dtype = np.dtype([
                ('normal', '<f4', (3,)),
                ('v0', '<f4', (3,)),
                ('v1', '<f4', (3,)),
                ('v2', '<f4', (3,)),
                ('attr', '<u2')
            ])

            records = np.zeros(num_faces, dtype=record_dtype)
            records['normal'] = normals
            records['v0'] = v0
            records['v1'] = v1
            records['v2'] = v2
            records['attr'] = 0

            f.write(records.tobytes())

    def _export_stl_ascii(self, filepath: str):
        normals = self.compute_face_normals()
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("solid MapMaker3D\n")
            for i, (i0, i1, i2) in enumerate(self.faces):
                n = normals[i]
                v0, v1, v2 = self.vertices[i0], self.vertices[i1], self.vertices[i2]
                f.write(f"  facet normal {n[0]:.6e} {n[1]:.6e} {n[2]:.6e}\n")
                f.write("    outer loop\n")
                f.write(f"      vertex {v0[0]:.6e} {v0[1]:.6e} {v0[2]:.6e}\n")
                f.write(f"      vertex {v1[0]:.6e} {v1[1]:.6e} {v1[2]:.6e}\n")
                f.write(f"      vertex {v2[0]:.6e} {v2[1]:.6e} {v2[2]:.6e}\n")
                f.write("    endloop\n")
                f.write("  endfacet\n")
            f.write("endsolid MapMaker3D\n")


def calculate_z_scale(
    elev_grid: np.ndarray,
    bbox: BoundingBox,
    width_mm: float,
    vertical_exaggeration: float = 2.0,
    target_relief_height_mm: Optional[float] = None
) -> float:
    """Calculates the Z scale multiplier (mm height per meter elevation)."""
    min_elev = float(np.min(elev_grid))
    max_elev = float(np.max(elev_grid))
    elev_range_m = max(1.0, max_elev - min_elev)

    if target_relief_height_mm is not None and target_relief_height_mm > 0:
        return target_relief_height_mm / elev_range_m

    mid_lat = (bbox.south + bbox.north) / 2.0
    lon_dist_m = bbox.lon_span * 111320.0 * math.cos(math.radians(mid_lat))
    lon_dist_m = max(100.0, lon_dist_m)

    horiz_scale_mm_per_m = width_mm / lon_dist_m
    return horiz_scale_mm_per_m * max(0.01, vertical_exaggeration)


def _emit_skirt_walls_with_biscuit_pockets(
    top_verts: np.ndarray,
    top_boundary_edges: List[Tuple[int, int]],
    vert_offset: int,
    width_mm: float,
    depth_mm: float,
    active_seams: Optional[Dict[str, bool]] = None,
    dowel_config: Optional[Any] = None
) -> Tuple[np.ndarray, List[List[int]], List[Dict[str, Any]]]:
    """Generates vertical perimeter skirt walls from top_boundary_edges down to Z=0,
    embedding 100% 2-manifold subterranean biscuit pockets into active internal tile seams.
    """
    off = len(top_verts)
    bot_verts = np.column_stack([top_verts[:, :2], np.zeros(off, dtype=np.float32)])
    extra_verts: List[List[float]] = []
    wall_faces: List[List[int]] = []
    pockets_created: List[Dict[str, Any]] = []

    dowels_enabled = getattr(dowel_config, "enabled", True) if dowel_config is not None else True
    if not active_seams or not any(active_seams.values()) or not dowels_enabled:
        for v_a, v_b in top_boundary_edges:
            wall_faces.append([vert_offset + v_a, vert_offset + off + v_a, vert_offset + off + v_b])
            wall_faces.append([vert_offset + v_a, vert_offset + off + v_b, vert_offset + v_b])
        return np.vstack([top_verts, bot_verts]), wall_faces, pockets_created

    pocket_w = float(getattr(dowel_config, "pocket_width", 14.0)) if dowel_config else 14.0
    pocket_h = float(getattr(dowel_config, "pocket_height", 1.85)) if dowel_config else 1.85
    pocket_d = float(getattr(dowel_config, "pocket_depth", 6.5)) if dowel_config else 6.5
    z0 = 1.0
    z1 = z0 + pocket_h
    eps = 0.08

    used_edges = set()

    def is_on_seam(v_idx: int, seam_name: str) -> bool:
        x, y = float(top_verts[v_idx, 0]), float(top_verts[v_idx, 1])
        if seam_name == "south":
            return abs(y - 0.0) <= eps
        if seam_name == "north":
            return abs(y - depth_mm) <= eps
        if seam_name == "west":
            return abs(x - 0.0) <= eps
        if seam_name == "east":
            return abs(x - width_mm) <= eps
        return False

    def quad(a: int, b: int, c: int, d: int) -> List[List[int]]:
        return [[a, b, c], [a, c, d]]

    for seam_name in ("south", "east", "north", "west"):
        if not active_seams.get(seam_name, False):
            continue
        seam_edges = [
            (a, b) for (a, b) in top_boundary_edges
            if is_on_seam(a, seam_name) and is_on_seam(b, seam_name)
        ]
        if not seam_edges:
            continue

        seam_next = {a: b for a, b in seam_edges}
        seam_prev = {b: a for a, b in seam_edges}
        starts = [a for a, _ in seam_edges if a not in seam_prev]

        for st in starts:
            chain = [st]
            curr = st
            visited = {st}
            while curr in seam_next and seam_next[curr] not in visited:
                curr = seam_next[curr]
                visited.add(curr)
                chain.append(curr)

            if len(chain) < 2:
                continue

            axis = 0 if seam_name in ("south", "north") else 1
            s_vals = [float(top_verts[v, axis]) for v in chain]
            s_min, s_max = min(s_vals), max(s_vals)
            span_len = s_max - s_min

            if span_len >= 55.0:
                centers = [s_min + span_len / 3.0, s_min + 2.0 * span_len / 3.0]
            elif span_len >= 18.0:
                centers = [s_min + span_len / 2.0]
            else:
                centers = []

            for c_pos in centers:
                p_min = c_pos - pocket_w / 2.0
                p_max = c_pos + pocket_w / 2.0
                sub_indices = [
                    idx for idx in range(len(chain) - 1)
                    if max(s_vals[idx], s_vals[idx + 1]) > p_min - 0.15
                    and min(s_vals[idx], s_vals[idx + 1]) < p_max + 0.15
                ]
                if not sub_indices:
                    continue

                i_start, i_end = min(sub_indices), max(sub_indices) + 1
                sub_chain = chain[i_start:i_end + 1]
                sub_edge_list = [(sub_chain[i], sub_chain[i + 1]) for i in range(len(sub_chain) - 1)]

                if any(e in used_edges for e in sub_edge_list):
                    continue
                if any(float(top_verts[v, 2]) < z1 + 0.4 for v in sub_chain):
                    continue

                p_start = top_verts[sub_chain[0], :2]
                p_end = top_verts[sub_chain[-1], :2]
                d_vec = p_end - p_start
                d_norm = float(np.linalg.norm(d_vec))
                if d_norm < pocket_w + 0.1:
                    continue

                for e in sub_edge_list:
                    used_edges.add(e)

                u = d_vec / d_norm
                n_in = np.array([-u[1], u[0]], dtype=np.float32)

                if axis == 0:
                    center_xy = np.array([c_pos, float(p_start[1])], dtype=np.float32)
                else:
                    center_xy = np.array([float(p_start[0]), c_pos], dtype=np.float32)

                pl_xy = center_xy - (pocket_w / 2.0) * u
                pr_xy = center_xy + (pocket_w / 2.0) * u
                il_xy = pl_xy + pocket_d * n_in
                ir_xy = pr_xy + pocket_d * n_in

                base_idx = vert_offset + 2 * off + len(extra_verts)
                extra_verts.extend([
                    [float(pl_xy[0]), float(pl_xy[1]), z1],  # PL_t
                    [float(pl_xy[0]), float(pl_xy[1]), z0],  # PL_b
                    [float(pr_xy[0]), float(pr_xy[1]), z0],  # PR_b
                    [float(pr_xy[0]), float(pr_xy[1]), z1],  # PR_t
                    [float(il_xy[0]), float(il_xy[1]), z1],  # IL_t
                    [float(il_xy[0]), float(il_xy[1]), z0],  # IL_b
                    [float(ir_xy[0]), float(ir_xy[1]), z0],  # IR_b
                    [float(ir_xy[0]), float(ir_xy[1]), z1],  # IR_t
                ])
                PL_t, PL_b, PR_b, PR_t = base_idx, base_idx + 1, base_idx + 2, base_idx + 3
                IL_t, IL_b, IR_b, IR_t = base_idx + 4, base_idx + 5, base_idx + 6, base_idx + 7

                T = [vert_offset + v for v in sub_chain]
                B = [vert_offset + off + v for v in sub_chain]
                k = len(sub_chain) - 1
                mid = k // 2

                for i in range(mid):
                    wall_faces.append([T[i], PL_t, T[i + 1]])
                wall_faces.append([T[mid], PL_t, PR_t])
                for i in range(mid, k):
                    wall_faces.append([T[i], PR_t, T[i + 1]])

                for i in range(mid):
                    wall_faces.append([PL_b, B[i], B[i + 1]])
                wall_faces.append([PL_b, B[mid], PR_b])
                for i in range(mid, k):
                    wall_faces.append([PR_b, B[i], B[i + 1]])

                wall_faces += quad(T[0], B[0], PL_b, PL_t)
                wall_faces += quad(PR_t, PR_b, B[k], T[k])

                wall_faces += quad(PL_t, IL_t, IR_t, PR_t)
                wall_faces += quad(PL_b, PR_b, IR_b, IL_b)
                wall_faces += quad(PL_t, PL_b, IL_b, IL_t)
                wall_faces += quad(PR_t, IR_t, IR_b, PR_b)
                wall_faces += quad(IL_t, IL_b, IR_b, IR_t)

                pockets_created.append({
                    "seam": seam_name,
                    "center_xy": [round(float(center_xy[0]), 3), round(float(center_xy[1]), 3)],
                    "z_range": [z0, z1]
                })

    for v_a, v_b in top_boundary_edges:
        if (v_a, v_b) not in used_edges:
            wall_faces.append([vert_offset + v_a, vert_offset + off + v_a, vert_offset + off + v_b])
            wall_faces.append([vert_offset + v_a, vert_offset + off + v_b, vert_offset + v_b])

    if extra_verts:
        all_v = np.vstack([top_verts, bot_verts, np.array(extra_verts, dtype=np.float32)])
    else:
        all_v = np.vstack([top_verts, bot_verts])

    return all_v, wall_faces, pockets_created


def carve_pin_sockets_into_mesh(
    top_verts: np.ndarray,
    top_faces: List[List[int]],
    pin_xy_list: List[Dict[str, Any]],
    socket_radius_mm: float = 1.15,
    socket_depth_mm: float = 2.20
) -> Tuple[np.ndarray, List[List[int]], List[Dict[str, Any]]]:
    """Replaces the 1-ring of the top-surface vertex at each pin (px, py) with a
    100% 2-manifold circular blind socket hole of radius `socket_radius_mm` and
    depth `socket_depth_mm` (floor clamped to >= 0.80 mm).

    Returns:
        (updated_top_verts, updated_top_faces, sockets_carved_metadata)
    """
    if not pin_xy_list or len(top_verts) == 0 or not top_faces:
        return top_verts, top_faces, []

    verts_list = top_verts.tolist()
    faces_list = [list(f) for f in top_faces]
    sockets_carved: List[Dict[str, Any]] = []

    # Identify exterior boundary vertices of top_faces so we never modify perimeter vertices
    edge_cnt: Dict[Tuple[int, int], int] = {}
    for f in faces_list:
        for i in range(3):
            e = (f[i], f[(i + 1) % 3])
            edge_cnt[e] = edge_cnt.get(e, 0) + 1
    boundary_verts = set()
    for (a, b) in edge_cnt:
        if (b, a) not in edge_cnt:
            boundary_verts.add(a)
            boundary_verts.add(b)

    used_center_verts = set()

    for pin in pin_xy_list:
        px = float(pin["x"])
        py = float(pin["y"])

        # Find the closest interior top vertex to (px, py)
        v_arr = np.array(verts_list, dtype=np.float32)
        dists = np.hypot(v_arr[:, 0] - px, v_arr[:, 1] - py)
        order = np.argsort(dists)
        v_center = None
        for cand in order[:8]:
            c_idx = int(cand)
            if c_idx not in boundary_verts and c_idx not in used_center_verts and dists[c_idx] <= 6.0:
                v_center = c_idx
                break

        if v_center is None:
            continue

        # Find all top faces incident to v_center
        inc_indices = [fi for fi, f in enumerate(faces_list) if v_center in f]
        if len(inc_indices) < 3:
            continue

        # Build ordered CCW loop of 1-ring outer edges (u_i -> u_{i+1}) around v_center
        ring_next: Dict[int, int] = {}
        valid_ring = True
        for fi in inc_indices:
            f = faces_list[fi]
            if f[0] == v_center:
                a, b = f[1], f[2]
            elif f[1] == v_center:
                a, b = f[2], f[0]
            else:
                a, b = f[0], f[1]
            if a in ring_next:
                valid_ring = False
                break
            ring_next[a] = b

        if not valid_ring or not ring_next:
            continue

        start_u = next(iter(ring_next.keys()))
        loop_u = [start_u]
        curr = start_u
        while len(loop_u) < len(ring_next):
            nxt = ring_next.get(curr)
            if nxt is None or nxt == start_u:
                break
            loop_u.append(nxt)
            curr = nxt

        if len(loop_u) != len(ring_next) or ring_next.get(loop_u[-1]) != start_u:
            continue

        # Snap v_center to exact (px, py) and ensure 1-ring neighbors lie outside socket_radius + 0.35 mm
        z_rim = float(verts_list[v_center][2])
        if z_rim < 1.3:
            continue
        z_bot = max(0.80, z_rim - socket_depth_mm)

        verts_list[v_center][0] = px
        verts_list[v_center][1] = py
        verts_list[v_center][2] = z_bot  # Repurpose v_center as the bottom-center floor vertex!
        used_center_verts.add(v_center)
        for u_idx in loop_u:
            used_center_verts.add(u_idx)
            if u_idx not in boundary_verts:
                ux, uy = verts_list[u_idx][0] - px, verts_list[u_idx][1] - py
                ud = math.hypot(ux, uy)
                min_d = socket_radius_mm + 0.45
                if 1e-4 < ud < min_d:
                    verts_list[u_idx][0] = px + (ux / ud) * min_d
                    verts_list[u_idx][1] = py + (uy / ud) * min_d

        # Create circular socket rim (rt_i, rtm_i) at z_rim and bottom ring (rb_i, rbm_i) at z_bot
        m = len(loop_u)
        angles = [math.atan2(verts_list[u][1] - py, verts_list[u][0] - px) for u in loop_u]
        rt_indices = []
        rtm_indices = []
        rb_indices = []
        rbm_indices = []

        for i in range(m):
            a0 = angles[i]
            a1 = angles[(i + 1) % m]
            da = (a1 - a0 + math.pi) % (2.0 * math.pi) - math.pi
            if da <= 0:
                da += 2.0 * math.pi
            amid = a0 + 0.5 * da

            x0, y0 = px + socket_radius_mm * math.cos(a0), py + socket_radius_mm * math.sin(a0)
            xm, ym = px + socket_radius_mm * math.cos(amid), py + socket_radius_mm * math.sin(amid)

            base_v = len(verts_list)
            verts_list.append([x0, y0, z_rim])  # rt_i
            verts_list.append([xm, ym, z_rim])  # rtm_i
            verts_list.append([x0, y0, z_bot])  # rb_i
            verts_list.append([xm, ym, z_bot])  # rbm_i
            rt_indices.append(base_v)
            rtm_indices.append(base_v + 1)
            rb_indices.append(base_v + 2)
            rbm_indices.append(base_v + 3)

        # Remove original 1-ring faces and replace with watertight socket bridge, walls, and floor
        inc_set = set(inc_indices)
        faces_list = [f for fi, f in enumerate(faces_list) if fi not in inc_set]

        for i in range(m):
            u0 = loop_u[i]
            u1 = loop_u[(i + 1) % m]
            rt0 = rt_indices[i]
            rtm = rtm_indices[i]
            rt1 = rt_indices[(i + 1) % m]
            rb0 = rb_indices[i]
            rbm = rbm_indices[i]
            rb1 = rb_indices[(i + 1) % m]

            # 1. Top surface bridge from outer edge (u0, u1) to circular arc (rt0 -> rtm -> rt1)
            faces_list.append([u0, u1, rtm])
            faces_list.append([u0, rtm, rt0])
            faces_list.append([rtm, u1, rt1])

            # 2. Vertical cylindrical socket walls from (rt0 -> rtm -> rt1) down to (rb0 -> rbm -> rb1)
            faces_list.append([rt0, rtm, rbm])
            faces_list.append([rt0, rbm, rb0])
            faces_list.append([rtm, rt1, rb1])
            faces_list.append([rtm, rb1, rbm])

            # 3. Socket bottom floor fan around v_center (at z_bot, facing +Z)
            faces_list.append([rb0, rbm, v_center])
            faces_list.append([rbm, rb1, v_center])

        sockets_carved.append({
            "name": pin.get("name", "Landmark"),
            "lat": pin.get("lat"),
            "lon": pin.get("lon"),
            "x_mm": round(px, 2),
            "y_mm": round(py, 2),
            "z_surface_mm": round(z_rim, 2),
            "z_bottom_mm": round(z_bot, 2),
            "diameter_mm": round(socket_radius_mm * 2.0, 2)
        })

    return np.array(verts_list, dtype=np.float32), faces_list, sockets_carved


def generate_landmark_pin_mesh(
    peg_diameter_mm: float = 2.00,
    peg_length_mm: float = 2.00,
    collar_diameter_mm: float = 3.60,
    head_diameter_mm: float = 5.60,
    segments: int = 16,
    zero_base_for_printing: bool = False
) -> SolidMesh:
    """Generates a 100% 2-manifold, support-free 3D landmark marker pin.

    When `zero_base_for_printing=False` (default for assembly placement):
      - Z in [-peg_length_mm, 0.0] is the Ø2.00mm insertion peg that slides into the terrain socket.
      - Z = 0.0 is the seating shoulder collar resting flush on the terrain surface.
      - Z in [0.0, +7.50] is the collar, stem, and support-free 45° chamfered pin head.
    When `zero_base_for_printing=True` (for `accessories/landmark_pins.stl` print bed):
      - Shifted by +peg_length_mm so the bottom face sits flat on Z = 0.0.
    """
    r_peg = peg_diameter_mm / 2.0
    r_col = collar_diameter_mm / 2.0
    r_stem = max(1.05, r_peg * 1.1)
    r_head = head_diameter_mm / 2.0
    z_shift = peg_length_mm if zero_base_for_printing else 0.0

    # Profile rings (radius, z) from bottom tip to top head
    profile = [
        (max(0.5, r_peg - 0.30), -peg_length_mm + z_shift),          # 0: Bottom lead-in chamfer
        (r_peg, -peg_length_mm + 0.30 + z_shift),                    # 1: Peg lower body
        (r_peg, 0.0 + z_shift),                                      # 2: Peg top / neck
        (r_col, 0.40 + z_shift),                                     # 3: 45° seating collar flare
        (r_col, 0.90 + z_shift),                                     # 4: Seating collar rim
        (r_stem, 1.40 + z_shift),                                    # 5: Stem base
        (r_stem, 3.40 + z_shift),                                    # 6: Stem top
        (r_head, 3.40 + (r_head - r_stem) + z_shift),                # 7: 45° support-free lower head equator
        (r_head * 0.92, 5.90 + z_shift),                             # 8: Upper head dome
        (r_head * 0.55, 6.80 + z_shift),                             # 9: Upper crown
    ]
    z_bottom_cap = profile[0][1]
    z_top_cap = 7.30 + z_shift

    verts: List[List[float]] = []
    faces: List[List[int]] = []

    # Vertex 0: bottom center cap; Vertex 1: top center cap
    verts.append([0.0, 0.0, z_bottom_cap])
    verts.append([0.0, 0.0, z_top_cap])

    ring_offsets = []
    for rad, z_val in profile:
        base_idx = len(verts)
        ring_offsets.append(base_idx)
        for s in range(segments):
            ang = (2.0 * math.pi * s) / segments
            verts.append([rad * math.cos(ang), rad * math.sin(ang), z_val])

    # Bottom cap fan (normal -Z)
    r0 = ring_offsets[0]
    for s in range(segments):
        s_next = (s + 1) % segments
        faces.append([0, r0 + s_next, r0 + s])

    # Side quad strips between consecutive rings
    for k in range(len(profile) - 1):
        rk0 = ring_offsets[k]
        rk1 = ring_offsets[k + 1]
        for s in range(segments):
            s_next = (s + 1) % segments
            a, b = rk0 + s, rk0 + s_next
            c, d = rk1 + s_next, rk1 + s
            faces.append([a, b, c])
            faces.append([a, c, d])

    # Top cap fan (normal +Z)
    r_last = ring_offsets[-1]
    for s in range(segments):
        s_next = (s + 1) % segments
        faces.append([1, r_last + s, r_last + s_next])

    return SolidMesh(np.array(verts, dtype=np.float32), np.array(faces, dtype=np.int32))


def generate_terrain_mesh(
    elev_grid: np.ndarray,
    bbox: BoundingBox,
    width_mm: float = 250.0,
    depth_mm: float = 250.0,
    base_height_mm: float = 4.0,
    vertical_exaggeration: float = 2.0,
    target_relief_height_mm: Optional[float] = None,
    topography_enabled: bool = True,
    base_shape: str = "rectangle",
    base_sides: int = 6,
    rotation_deg: float = 0.0,
    boundary_geojson: Optional[Dict[str, Any]] = None,
    global_min_elev: Optional[float] = None,
    global_z_scale: Optional[float] = None,
    active_seams: Optional[Dict[str, bool]] = None,
    dowel_config: Optional[Any] = None,
    tile_clip_box_norm: Optional[Tuple[float, float, float, float]] = None,
    route_waypoints_latlon: Optional[List[Tuple[float, float]]] = None,
    landmark_pins_latlon: Optional[List[Dict[str, Any]]] = None,
    tolerance_config: Optional[Any] = None,
    global_bbox: Optional[BoundingBox] = None,
    global_width_mm: Optional[float] = None,
    global_depth_mm: Optional[float] = None,
    tile_offset_xy_mm: Tuple[float, float] = (0.0, 0.0)
) -> SolidMesh:
    """Generates a watertight, solid terrain mesh supporting multiple base shapes:
    rectangle, circle, ellipse, regular polygon (N-gon), or natural borders,
    with custom orientation rotation, subterranean biscuit dowel pockets on internal tile seams,
    recessed route guide trenches, and 2-manifold landmark pin sockets.
    """
    rows, cols = elev_grid.shape
    raw_min = float(np.min(elev_grid))
    raw_max = float(np.max(elev_grid))

    # Clamp deep ocean bathymetry (< -50m) to 0.0m sea level when coastal land (> 0m) is present
    if global_min_elev is not None:
        min_elev = global_min_elev
        effective_elev = np.maximum(elev_grid, min_elev) if min_elev == 0.0 and raw_min < -50.0 else elev_grid
    else:
        if raw_min < -50.0 and raw_max > 0.0:
            min_elev = 0.0
            effective_elev = np.maximum(elev_grid, 0.0)
        else:
            min_elev = raw_min
            effective_elev = elev_grid

    if topography_enabled:
        z_scale = (
            global_z_scale
            if global_z_scale is not None
            else calculate_z_scale(effective_elev, bbox, width_mm, vertical_exaggeration, target_relief_height_mm)
        )
        z_grid = base_height_mm + np.maximum(0.0, effective_elev - min_elev) * z_scale
    else:
        z_grid = np.full((rows, cols), base_height_mm, dtype=np.float32)

    cx = width_mm / 2.0
    cy = depth_mm / 2.0
    rad = math.radians(rotation_deg)
    cos_r = math.cos(rad)
    sin_r = math.sin(rad)

    # Project route waypoints and landmark pins into this tile's local (x_mm, y_mm) frame
    eff_bbox = global_bbox if global_bbox is not None else bbox
    eff_w = global_width_mm if global_width_mm is not None else width_mm
    eff_d = global_depth_mm if global_depth_mm is not None else depth_mm
    ox, oy = tile_offset_xy_mm
    gcx_rot, gcy_rot = eff_w / 2.0, eff_d / 2.0

    def latlon_to_tile_xy(lat: float, lon: float) -> Tuple[float, float]:
        gx = ((lon - eff_bbox.west) / max(1e-6, eff_bbox.lon_span)) * eff_w
        gy = ((lat - eff_bbox.south) / max(1e-6, eff_bbox.lat_span)) * eff_d
        if abs(rotation_deg) > 1e-4:
            dx_g, dy_g = gx - gcx_rot, gy - gcy_rot
            gx = gcx_rot + dx_g * cos_r + dy_g * sin_r
            gy = gcy_rot - dx_g * sin_r + dy_g * cos_r
        return float(gx - ox), float(gy - oy)

    path_w_mm = float(getattr(tolerance_config, "path_default_width", 2.0)) if tolerance_config else 2.0
    path_d_mm = float(getattr(tolerance_config, "path_default_depth", 1.6)) if tolerance_config else 1.6
    path_clr_mm = float(getattr(tolerance_config, "path_joint_clearance", 0.20)) if tolerance_config else 0.20
    half_trench_w = (path_w_mm / 2.0) + path_clr_mm
    pin_clr_mm = float(getattr(tolerance_config, "pin_socket_clearance", 0.15)) if tolerance_config else 0.15
    socket_radius_mm = 1.00 + pin_clr_mm  # Ø2.00mm peg + 2*0.15mm = Ø2.30mm socket

    route_line_local: Optional[LineString] = None
    if route_waypoints_latlon and len(route_waypoints_latlon) >= 2:
        r_pts = [latlon_to_tile_xy(float(pt[0]), float(pt[1])) for pt in route_waypoints_latlon]
        try:
            cand_line = LineString(r_pts)
            tile_expanded = box(-5.0, -5.0, width_mm + 5.0, depth_mm + 5.0)
            if cand_line.intersects(tile_expanded):
                route_line_local = cand_line
        except Exception:
            route_line_local = None

    local_pins: List[Dict[str, Any]] = []
    if landmark_pins_latlon:
        for p in landmark_pins_latlon:
            try:
                plat = float(p["lat"])
                plon = float(p["lon"])
                lx, ly = latlon_to_tile_xy(plat, plon)
                if 2.5 <= lx <= width_mm - 2.5 and 2.5 <= ly <= depth_mm - 2.5:
                    local_pins.append({
                        "name": p.get("name", "Landmark"),
                        "lat": plat,
                        "lon": plon,
                        "x": lx,
                        "y": ly
                    })
            except Exception:
                pass

    def sample_z(x_mm: float, y_mm: float, include_route_trench: bool = True) -> float:
        """Bilinearly interpolates elevation height at physical model coordinate (x, y),
        accounting for base rotation and optional recessed route guide trench."""
        dx = x_mm - cx
        dy = y_mm - cy
        x_rot = cx + dx * cos_r - dy * sin_r
        y_rot = cy + dx * sin_r + dy * cos_r

        c_float = (x_rot / max(1e-3, width_mm)) * (cols - 1)
        r_float = (y_rot / max(1e-3, depth_mm)) * (rows - 1)
        c0 = int(np.clip(math.floor(c_float), 0, cols - 1))
        c1 = min(c0 + 1, cols - 1)
        r0 = int(np.clip(math.floor(r_float), 0, rows - 1))
        r1 = min(r0 + 1, rows - 1)
        dc = float(np.clip(c_float - c0, 0.0, 1.0))
        dr = float(np.clip(r_float - r0, 0.0, 1.0))
        top = (1.0 - dc) * z_grid[r0, c0] + dc * z_grid[r0, c1]
        bot = (1.0 - dc) * z_grid[r1, c0] + dc * z_grid[r1, c1]
        z_val = float((1.0 - dr) * top + dr * bot)

        if include_route_trench and route_line_local is not None:
            d_r = float(route_line_local.distance(Point(x_mm, y_mm)))
            if d_r <= half_trench_w:
                z_val = max(0.80, z_val - path_d_mm)
            elif d_r <= half_trench_w + 0.40:
                t = (d_r - half_trench_w) / 0.40
                z_val = max(0.80, z_val - path_d_mm * (1.0 - t))
        return z_val

    def _inject_route_and_pin_pts(poly_2d: Polygon, base_int_pts: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        pts_out = list(base_int_pts)
        if route_line_local is not None:
            try:
                seg_line = shapely.segmentize(route_line_local, max_segment_length=1.5)
                lines_to_extract = [seg_line] if seg_line.geom_type == "LineString" else list(getattr(seg_line, "geoms", []))
                for ln in lines_to_extract:
                    l_coords = list(ln.coords)
                    for i, (rx, ry) in enumerate(l_coords):
                        for off_d in (0.0, -half_trench_w, half_trench_w):
                            if off_d == 0.0:
                                px, py = rx, ry
                            else:
                                p_next = l_coords[min(i + 1, len(l_coords) - 1)]
                                p_prev = l_coords[max(i - 1, 0)]
                                dx_l, dy_l = p_next[0] - p_prev[0], p_next[1] - p_prev[1]
                                nl = math.hypot(dx_l, dy_l)
                                if nl < 1e-4:
                                    continue
                                px = rx - (dy_l / nl) * off_d
                                py = ry + (dx_l / nl) * off_d
                            pt_obj = Point(px, py)
                            if poly_2d.contains(pt_obj) and poly_2d.exterior.distance(pt_obj) > 1.2:
                                pts_out.append((float(px), float(py)))
            except Exception:
                pass

        if local_pins:
            r_ring = socket_radius_mm + 0.85
            for pin in local_pins:
                px, py = float(pin["x"]), float(pin["y"])
                pt_c = Point(px, py)
                if poly_2d.contains(pt_c) and poly_2d.exterior.distance(pt_c) > r_ring + 0.5:
                    pts_out = [p for p in pts_out if math.hypot(p[0] - px, p[1] - py) > r_ring + 0.3]
                    pts_out.append((px, py))
                    for k in range(8):
                        ang = (2.0 * math.pi * k) / 8.0
                        pts_out.append((px + r_ring * math.cos(ang), py + r_ring * math.sin(ang)))
        return pts_out

    # -------------------------------------------------------------
    # CASE A: Natural Territorial / Coastline Border Base
    # -------------------------------------------------------------
    if base_shape == "natural_border" and boundary_geojson:
        try:
            geom = shape(boundary_geojson)
            if not geom.is_valid:
                geom = geom.buffer(0)

            # Clip country/state boundary to this tile's geographic bounding box!
            tile_bbox_poly = box(bbox.west, bbox.south, bbox.east, bbox.north)
            geom = geom.intersection(tile_bbox_poly)
            if not geom.is_valid:
                geom = geom.buffer(0)

            if geom.geom_type == "Polygon":
                polys = [geom] if not geom.is_empty else []
            elif geom.geom_type == "MultiPolygon":
                tot = geom.area
                polys = [p for p in geom.geoms if not p.is_empty and (p.area / max(1e-9, tot)) >= 0.002]
                polys.sort(key=lambda p: p.area, reverse=True)
            elif hasattr(geom, "geoms"):
                polys = [p for p in geom.geoms if p.geom_type == "Polygon" and not p.is_empty]
            else:
                polys = []

            all_verts_list = []
            all_faces_list = []
            all_pockets_list = []
            all_sockets_list = []
            vert_offset = 0

            w_lon, e_lon = bbox.west, bbox.east
            s_lat, n_lat = bbox.south, bbox.north
            lon_span = max(1e-5, e_lon - w_lon)
            lat_span = max(1e-5, n_lat - s_lat)

            for poly in polys:
                coords = list(poly.exterior.coords)
                if len(coords) < 3:
                    continue
                if len(coords) > 300:
                    poly = poly.simplify(0.008 * max(lon_span, lat_span) / 10.0, preserve_topology=True)
                    coords = list(poly.exterior.coords)

                # Project geographic (lon, lat) to tile local mm (0 to width_mm, 0 to depth_mm)
                perim_xy = [
                    (
                        float(np.clip(((lon - w_lon) / lon_span) * width_mm, 0.0, width_mm)),
                        float(np.clip(((lat - s_lat) / lat_span) * depth_mm, 0.0, depth_mm))
                    )
                    for lon, lat in coords[:-1]
                ]
                if len(perim_xy) < 3:
                    continue

                sh_poly = Polygon(perim_xy)
                if not sh_poly.is_valid:
                    sh_poly = sh_poly.buffer(0)
                if sh_poly.is_empty or sh_poly.area < 4.0:
                    continue
                if sh_poly.geom_type == "MultiPolygon":
                    sh_poly = max(sh_poly.geoms, key=lambda g: g.area)

                # Subdivide straight seam cut lines every 3.5 mm for seamless mating & biscuit pockets
                sh_poly = shapely.segmentize(sh_poly, max_segment_length=3.5)
                perim_xy = list(sh_poly.exterior.coords)[:-1]

                minx, miny, maxx, maxy = sh_poly.bounds
                int_pts = []
                res_x = max(14, cols // 2)
                res_y = max(14, rows // 2)
                xs = np.linspace(minx, maxx, res_x)
                ys = np.linspace(miny, maxy, res_y)
                for x in xs:
                    for y in ys:
                        p = Point(x, y)
                        if sh_poly.contains(p) and sh_poly.exterior.distance(p) > 1.5:
                            int_pts.append((float(x), float(y)))

                int_pts = _inject_route_and_pin_pts(sh_poly, int_pts)
                pts_2d = perim_xy + int_pts
                pts_arr = np.array(pts_2d, dtype=np.float32)

                tri = Delaunay(pts_arr)
                valid_faces = []
                for simplex in tri.simplices:
                    tri_pts = pts_arr[simplex]
                    cp = Point(np.mean(tri_pts, axis=0))
                    if sh_poly.contains(cp):
                        v0, v1, v2 = tri_pts[0], tri_pts[1], tri_pts[2]
                        det = (v1[0] - v0[0]) * (v2[1] - v0[1]) - (v1[1] - v0[1]) * (v2[0] - v0[0])
                        if det < 0:
                            valid_faces.append([int(simplex[0]), int(simplex[2]), int(simplex[1])])
                        else:
                            valid_faces.append([int(simplex[0]), int(simplex[1]), int(simplex[2])])

                if not valid_faces:
                    continue

                top_z = np.array([sample_z(pt[0], pt[1]) for pt in pts_2d], dtype=np.float32)
                top_verts = np.column_stack([pts_arr, top_z])
                orig_faces = [list(f) for f in valid_faces]

                edge_counts = {}
                for f in orig_faces:
                    for i in range(3):
                        e = (f[i], f[(i + 1) % 3])
                        edge_counts[e] = edge_counts.get(e, 0) + 1
                top_boundary_edges = [e for e in edge_counts if (e[1], e[0]) not in edge_counts]

                poly_pins = [p for p in local_pins if sh_poly.contains(Point(p["x"], p["y"]))]
                top_verts, carved_top_faces, sockets = carve_pin_sockets_into_mesh(
                    top_verts, orig_faces, poly_pins, socket_radius_mm=socket_radius_mm
                )
                all_sockets_list.extend(sockets)
                off = len(top_verts)

                part_faces = []
                for f in carved_top_faces:
                    part_faces.append([vert_offset + f[0], vert_offset + f[1], vert_offset + f[2]])

                part_verts, wall_faces, pockets = _emit_skirt_walls_with_biscuit_pockets(
                    top_verts=top_verts,
                    top_boundary_edges=top_boundary_edges,
                    vert_offset=vert_offset,
                    width_mm=width_mm,
                    depth_mm=depth_mm,
                    active_seams=active_seams,
                    dowel_config=dowel_config
                )
                part_faces.extend(wall_faces)
                all_pockets_list.extend(pockets)

                for f in orig_faces:
                    part_faces.append([vert_offset + off + f[0], vert_offset + off + f[2], vert_offset + off + f[1]])

                all_verts_list.append(part_verts)
                all_faces_list.extend(part_faces)
                vert_offset += len(part_verts)

            if all_verts_list:
                full_verts = np.vstack(all_verts_list)
                full_faces = np.array(all_faces_list, dtype=np.int32)
                mesh = SolidMesh(full_verts, full_faces)
                mesh.pockets_created = all_pockets_list
                mesh.sockets_carved = all_sockets_list
                return mesh
        except Exception:
            pass

    # -------------------------------------------------------------
    # CASE B: Standard Rectangular / Square Base
    # -------------------------------------------------------------
    if base_shape == "rectangle" or base_shape == "natural_border":
        x_coords = np.linspace(0, width_mm, cols, dtype=np.float32)
        y_coords = np.linspace(0, depth_mm, rows, dtype=np.float32)
        xx, yy = np.meshgrid(x_coords, y_coords)

        if route_line_local is not None or abs(rotation_deg) > 1e-4:
            flat_x = xx.ravel()
            flat_y = yy.ravel()
            flat_z = np.array([sample_z(float(fx), float(fy)) for fx, fy in zip(flat_x, flat_y)], dtype=np.float32)
            top_verts = np.column_stack([flat_x, flat_y, flat_z])
        else:
            top_verts = np.column_stack([xx.ravel(), yy.ravel(), z_grid.ravel()])

        def v_idx(r, c):
            return r * cols + c

        orig_top_faces = []
        for r in range(rows - 1):
            for c in range(cols - 1):
                i00, i10 = v_idx(r, c), v_idx(r, c + 1)
                i11, i01 = v_idx(r + 1, c + 1), v_idx(r + 1, c)
                orig_top_faces.append([i00, i10, i11])
                orig_top_faces.append([i00, i11, i01])

        top_verts, carved_top_faces, sockets = carve_pin_sockets_into_mesh(
            top_verts, orig_top_faces, local_pins, socket_radius_mm=socket_radius_mm
        )
        off = len(top_verts)
        faces = list(carved_top_faces)

        # Directed CCW top boundary edges along South, East, North, West walls
        top_boundary_edges = []
        for c in range(cols - 1):
            top_boundary_edges.append((v_idx(0, c), v_idx(0, c + 1)))
        for r in range(rows - 1):
            top_boundary_edges.append((v_idx(r, cols - 1), v_idx(r + 1, cols - 1)))
        for c in range(cols - 1, 0, -1):
            top_boundary_edges.append((v_idx(rows - 1, c), v_idx(rows - 1, c - 1)))
        for r in range(rows - 1, 0, -1):
            top_boundary_edges.append((v_idx(r, 0), v_idx(r - 1, 0)))

        all_verts, wall_faces, pockets = _emit_skirt_walls_with_biscuit_pockets(
            top_verts=top_verts,
            top_boundary_edges=top_boundary_edges,
            vert_offset=0,
            width_mm=width_mm,
            depth_mm=depth_mm,
            active_seams=active_seams,
            dowel_config=dowel_config
        )
        faces.extend(wall_faces)

        def b_idx(r, c):
            return off + (r * cols + c)

        # Bottom floor at Z=0
        for r in range(rows - 1):
            for c in range(cols - 1):
                b00, b10 = b_idx(r, c), b_idx(r, c + 1)
                b11, b01 = b_idx(r + 1, c + 1), b_idx(r + 1, c)
                faces.append([b00, b11, b10])
                faces.append([b00, b01, b11])

        mesh = SolidMesh(all_verts, np.array(faces, dtype=np.int32))
        mesh.pockets_created = pockets
        mesh.sockets_carved = sockets
        return mesh

    # -------------------------------------------------------------
    # CASE C: Non-Rectangular Geometric Base (Circle, Ellipse, N-Gon)
    # -------------------------------------------------------------
    if tile_clip_box_norm is not None:
        u0, v0_n, u1, v1_n = tile_clip_box_norm
        span_u = max(1e-5, u1 - u0)
        span_v = max(1e-5, v1_n - v0_n)
        global_w = width_mm / span_u
        global_d = depth_mm / span_v
        gcx, gcy = global_w / 2.0, global_d / 2.0
        grx, gry = global_w / 2.0, global_d / 2.0
    else:
        u0, v0_n = 0.0, 0.0
        gcx, gcy = width_mm / 2.0, depth_mm / 2.0
        grx, gry = width_mm / 2.0, depth_mm / 2.0

    if base_shape == "circle":
        r_rad = min(grx, gry)
        num_perimeter = 64
        angles = np.linspace(0, 2 * np.pi, num_perimeter, endpoint=False)
        global_perim = [(gcx + r_rad * math.cos(a), gcy + r_rad * math.sin(a)) for a in angles]
    elif base_shape == "ellipse":
        num_perimeter = 64
        angles = np.linspace(0, 2 * np.pi, num_perimeter, endpoint=False)
        global_perim = [(gcx + grx * math.cos(a), gcy + gry * math.sin(a)) for a in angles]
    elif base_shape == "polygon":
        num_perimeter = max(3, int(base_sides))
        r_rad = min(grx, gry)
        angles = [2.0 * math.pi * i / num_perimeter - math.pi / 2.0 for i in range(num_perimeter)]
        global_perim = [(gcx + r_rad * math.cos(a), gcy + r_rad * math.sin(a)) for a in angles]
    else:
        global_perim = [(0, 0), (width_mm, 0), (width_mm, depth_mm), (0, depth_mm)]

    if tile_clip_box_norm is not None:
        x_shift = u0 * (width_mm / max(1e-5, tile_clip_box_norm[2] - u0))
        y_shift = v0_n * (depth_mm / max(1e-5, tile_clip_box_norm[3] - v0_n))
        local_perim = [(px - x_shift, py - y_shift) for px, py in global_perim]
        base_poly = Polygon(local_perim).intersection(box(0.0, 0.0, width_mm, depth_mm))
        if isinstance(base_poly, MultiPolygon):
            base_poly = max(base_poly.geoms, key=lambda g: g.area)
        base_poly = shapely.segmentize(base_poly, max_segment_length=3.5)
        perimeter_xy = list(base_poly.exterior.coords)[:-1]
    else:
        base_poly = Polygon(global_perim)
        base_poly = shapely.segmentize(base_poly, max_segment_length=4.0)
        perimeter_xy = list(base_poly.exterior.coords)[:-1]

    int_pts = []
    res_x = max(12, cols // 2)
    res_y = max(12, rows // 2)
    xs = np.linspace(0, width_mm, res_x)
    ys = np.linspace(0, depth_mm, res_y)

    for x in xs:
        for y in ys:
            p = Point(x, y)
            if base_poly.contains(p) and base_poly.exterior.distance(p) > 1.5:
                int_pts.append((float(x), float(y)))

    int_pts = _inject_route_and_pin_pts(base_poly, int_pts)
    all_2d_pts = perimeter_xy + int_pts
    pts_arr = np.array(all_2d_pts, dtype=np.float32)

    tri = Delaunay(pts_arr)
    valid_faces = []
    for simplex in tri.simplices:
        tri_pts = pts_arr[simplex]
        centroid = Point(np.mean(tri_pts, axis=0))
        if base_poly.contains(centroid):
            v0, v1, v2 = tri_pts[0], tri_pts[1], tri_pts[2]
            det = (v1[0] - v0[0]) * (v2[1] - v0[1]) - (v1[1] - v0[1]) * (v2[0] - v0[0])
            if det < 0:
                valid_faces.append([int(simplex[0]), int(simplex[2]), int(simplex[1])])
            else:
                valid_faces.append([int(simplex[0]), int(simplex[1]), int(simplex[2])])

    top_z = np.array([sample_z(pt[0], pt[1]) for pt in all_2d_pts], dtype=np.float32)
    top_verts = np.column_stack([pts_arr, top_z])
    orig_faces = [list(f) for f in valid_faces]

    edge_counts = {}
    for f in orig_faces:
        for i in range(3):
            e = (f[i], f[(i + 1) % 3])
            edge_counts[e] = edge_counts.get(e, 0) + 1
    top_boundary_edges = [e for e in edge_counts if (e[1], e[0]) not in edge_counts]

    poly_pins = [p for p in local_pins if base_poly.contains(Point(p["x"], p["y"]))]
    top_verts, carved_top_faces, sockets = carve_pin_sockets_into_mesh(
        top_verts, orig_faces, poly_pins, socket_radius_mm=socket_radius_mm
    )
    offset = len(top_verts)

    faces = list(carved_top_faces)

    all_verts, wall_faces, pockets = _emit_skirt_walls_with_biscuit_pockets(
        top_verts=top_verts,
        top_boundary_edges=top_boundary_edges,
        vert_offset=0,
        width_mm=width_mm,
        depth_mm=depth_mm,
        active_seams=active_seams,
        dowel_config=dowel_config
    )
    faces.extend(wall_faces)

    # Bottom floor (inverted winding of orig_faces)
    for f in orig_faces:
        faces.append([offset + f[0], offset + f[2], offset + f[1]])

    mesh = SolidMesh(all_verts, np.array(faces, dtype=np.int32))
    mesh.pockets_created = pockets
    mesh.sockets_carved = sockets
    return mesh


def extrude_building_mesh(
    building: BuildingPolygon,
    bbox: BoundingBox,
    width_mm: float,
    depth_mm: float,
    z_ground: float,
    z_scale: float,
    building_height_scale: float = 1.0,
    min_printable_wall: float = 0.84
) -> Tuple[Optional[SolidMesh], Dict[str, Any]]:
    """Extrudes a 3D building polygon into a watertight solid prism.
    
    Returns:
        (SolidMesh, audit_info_dict)
    """
    coords = building.coordinates
    if len(coords) < 3:
        return None, {"status": "invalid_polygon"}

    # Project GPS coordinates (lat, lon) to model space (x, y in mm)
    poly_pts = []
    for lat, lon in coords:
        x = (lon - bbox.west) / bbox.lon_span * width_mm
        y = (lat - bbox.south) / bbox.lat_span * depth_mm
        poly_pts.append((x, y))

    poly = Polygon(poly_pts)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty:
        return None, {"status": "empty_polygon"}

    # Printability audit: Check footprint bounding box
    minx, miny, maxx, maxy = poly.bounds
    bw = maxx - minx
    bd = maxy - miny

    audit_info = {
        "osm_id": building.osm_id,
        "name": building.name,
        "width_mm": bw,
        "depth_mm": bd,
        "too_thin": (bw < min_printable_wall or bd < min_printable_wall)
    }

    # Calculate extruded height in mm
    h_mm = max(1.0, building.height_meters * z_scale * building_height_scale)
    z_top = z_ground + h_mm

    # Simplify/clean polygon
    ext_coords = list(poly.exterior.coords)[:-1] # Remove repeated closing point
    num_pts = len(ext_coords)
    if num_pts < 3:
        return None, {"status": "too_few_points"}

    verts = []
    # Bottom ring: indices 0 to num_pts-1
    for x, y in ext_coords:
        verts.append([x, y, z_ground])
    # Top ring: indices num_pts to 2*num_pts-1
    for x, y in ext_coords:
        verts.append([x, y, z_top])

    verts = np.array(verts, dtype=np.float32)
    faces = []

    # Vertical side walls
    for i in range(num_pts):
        i_next = (i + 1) % num_pts
        b0, b1 = i, i_next
        t0, t1 = num_pts + i, num_pts + i_next
        faces.append([b0, b1, t1])
        faces.append([b0, t1, t0])

    # Triangulate top roof polygon using fan from centroid
    roof_center = np.mean(verts[num_pts:], axis=0)
    roof_center_idx = len(verts)
    verts = np.vstack([verts, roof_center])

    for i in range(num_pts):
        i_next = (i + 1) % num_pts
        faces.append([roof_center_idx, num_pts + i, num_pts + i_next])

    # Bottom floor face
    floor_center = np.mean(verts[:num_pts], axis=0)
    floor_center_idx = len(verts)
    verts = np.vstack([verts, floor_center])

    for i in range(num_pts):
        i_next = (i + 1) % num_pts
        faces.append([floor_center_idx, i_next, i])

    return SolidMesh(verts, np.array(faces, dtype=np.int32)), audit_info


def extrude_block_mesh(
    block: Any,
    bbox: BoundingBox,
    width_mm: float,
    depth_mm: float,
    z_ground: float,
    rotation_deg: float = 0.0,
    sample_z_func: Optional[Any] = None
) -> Optional[SolidMesh]:
    """Extrudes an urban block or settlement parcel into a watertight solid prism."""
    coords = getattr(block, "coordinates", [])
    if len(coords) < 3:
        return None

    # Project GPS coordinates (lat, lon) to physical model space (x, y in mm)
    poly_pts = []
    cx_mm = width_mm / 2.0
    cy_mm = depth_mm / 2.0
    rad = math.radians(rotation_deg)
    cos_r = math.cos(rad)
    sin_r = math.sin(rad)

    lat_span = max(1e-5, bbox.lat_span)
    lon_span = max(1e-5, bbox.lon_span)

    for lat, lon in coords:
        raw_x = (lon - bbox.west) / lon_span * width_mm
        raw_y = (lat - bbox.south) / lat_span * depth_mm
        # Rotate coordinates around model center
        dx = raw_x - cx_mm
        dy = raw_y - cy_mm
        x_rot = cx_mm + dx * cos_r - dy * sin_r
        y_rot = cy_mm + dx * sin_r + dy * cos_r
        poly_pts.append((x_rot, y_rot))

    poly = Polygon(poly_pts)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty or not isinstance(poly, Polygon):
        return None

    ext_coords = list(poly.exterior.coords)[:-1]
    num_pts = len(ext_coords)
    if num_pts < 3:
        return None

    # Ground elevation at perimeter vertices
    z_bottoms = []
    for x, y in ext_coords:
        if sample_z_func:
            z_bottoms.append(sample_z_func(x, y))
        else:
            z_bottoms.append(z_ground)

    z_max_ground = max(z_bottoms)
    block_h = getattr(block, "height_mm", 4.0)
    z_top = z_max_ground + max(1.0, block_h)

    verts = []
    # Bottom ring: 0 to num_pts - 1
    for i, (x, y) in enumerate(ext_coords):
        verts.append([x, y, z_bottoms[i]])
    # Top ring: num_pts to 2*num_pts - 1
    for x, y in ext_coords:
        verts.append([x, y, z_top])

    faces = []
    # Vertical side walls
    for i in range(num_pts):
        i_next = (i + 1) % num_pts
        b0, b1 = i, i_next
        t0, t1 = num_pts + i, num_pts + i_next
        faces.append([b0, b1, t1])
        faces.append([b0, t1, t0])

    # Triangulate top roof polygon using constrained Delaunay
    triangles = shapely.ops.triangulate(poly)
    inside_triangles = [t for t in triangles if poly.buffer(1e-5).contains(t.centroid)]

    for tri in inside_triangles:
        t_pts = list(tri.exterior.coords)[:-1]
        t_indices = []
        for tx, ty in t_pts:
            matched = False
            for v_idx in range(num_pts):
                vx, vy = ext_coords[v_idx]
                if abs(vx - tx) < 1e-4 and abs(vy - ty) < 1e-4:
                    t_indices.append(num_pts + v_idx)
                    matched = True
                    break
            if not matched:
                new_idx = len(verts)
                verts.append([tx, ty, z_top])
                t_indices.append(new_idx)

        # Counter-clockwise winding for top face (+Z normal)
        v0 = np.array(verts[t_indices[0]])
        v1 = np.array(verts[t_indices[1]])
        v2 = np.array(verts[t_indices[2]])
        cross_z = (v1[0] - v0[0]) * (v2[1] - v0[1]) - (v1[1] - v0[1]) * (v2[0] - v0[0])
        if cross_z < 0:
            faces.append([t_indices[0], t_indices[2], t_indices[1]])
        else:
            faces.append([t_indices[0], t_indices[1], t_indices[2]])

    return SolidMesh(np.array(verts, dtype=np.float32), np.array(faces, dtype=np.int32))



def generate_flat_biscuit(
    thickness_mm: float = 1.60,
    width_mm: float = 12.0,
    length_mm: float = 12.0,
    chamfer_mm: float = 0.40
) -> SolidMesh:
    """Generates a separate printable flat alignment biscuit (spline dowel)."""
    # Box centered at origin, lying flat on Z=0 to Z=thickness_mm
    hx = length_mm / 2.0
    hy = width_mm / 2.0
    hz = thickness_mm

    # 8-corner box
    v = np.array([
        [-hx, -hy, 0], [hx, -hy, 0], [hx, hy, 0], [-hx, hy, 0], # bottom
        [-hx, -hy, hz], [hx, -hy, hz], [hx, hy, hz], [-hx, hy, hz] # top
    ], dtype=np.float32)

    faces = np.array([
        # bottom (-Z)
        [0, 2, 1], [0, 3, 2],
        # top (+Z)
        [4, 5, 6], [4, 6, 7],
        # south (-Y)
        [0, 1, 5], [0, 5, 4],
        # north (+Y)
        [2, 3, 7], [2, 7, 6],
        # west (-X)
        [3, 0, 4], [3, 4, 7],
        # east (+X)
        [1, 2, 6], [1, 6, 5]
    ], dtype=np.int32)

    return SolidMesh(v, faces)


def generate_path_strip_and_cavity(
    waypoints_lat_lon: List[Tuple[float, float]],
    bbox: BoundingBox,
    width_mm: float,
    depth_mm: float,
    elev_grid: np.ndarray,
    z_scale: float,
    base_height_mm: float = 4.0,
    path_width_mm: float = 2.0,
    path_depth_mm: float = 1.6,
    clearance_mm: float = 0.20,
    tactile_offset_mm: float = 0.40,
    global_min_elev: Optional[float] = None,
    rotation_deg: float = 0.0
) -> Tuple[SolidMesh, SolidMesh]:
    """Generates:
    1. The separate slide-in path inlay strip (to be printed in contrasting color).
    2. The negative cutter mesh used to carve the toleranced cavity in the terrain.
    
    Returns:
        (path_inlay_mesh, negative_cutter_mesh)
    """
    rows, cols = elev_grid.shape
    raw_min = float(np.min(elev_grid))
    raw_max = float(np.max(elev_grid))
    if global_min_elev is not None:
        min_elev = global_min_elev
    elif raw_min < -50.0 and raw_max > 0.0:
        min_elev = 0.0
    else:
        min_elev = raw_min

    cx = width_mm / 2.0
    cy = depth_mm / 2.0
    rad = math.radians(rotation_deg)
    cos_r = math.cos(rad)
    sin_r = math.sin(rad)

    # Convert waypoints to model coordinates (X, Y) and subdivide every 2.0 mm for smooth terrain conformality
    raw_xy = []
    for lat, lon in waypoints_lat_lon:
        x = (lon - bbox.west) / max(1e-6, bbox.lon_span) * width_mm
        y = (lat - bbox.south) / max(1e-6, bbox.lat_span) * depth_mm
        if abs(rotation_deg) > 1e-4:
            dx, dy = x - cx, y - cy
            x = cx + dx * cos_r + dy * sin_r
            y = cy - dx * sin_r + dy * cos_r
        if not raw_xy or math.hypot(x - raw_xy[-1][0], y - raw_xy[-1][1]) > 0.05:
            raw_xy.append((float(x), float(y)))

    if len(raw_xy) < 2:
        return SolidMesh(), SolidMesh()

    seg_xy = [raw_xy[0]]
    for i in range(len(raw_xy) - 1):
        x0, y0 = raw_xy[i]
        x1, y1 = raw_xy[i + 1]
        d_seg = math.hypot(x1 - x0, y1 - y0)
        n_sub = max(1, int(math.ceil(d_seg / 2.0)))
        for s in range(1, n_sub + 1):
            t = s / n_sub
            seg_xy.append((x0 + t * (x1 - x0), y0 + t * (y1 - y0)))

    model_pts = []
    for x, y in seg_xy:
        dx = x - cx
        dy = y - cy
        x_unrot = cx + dx * cos_r - dy * sin_r
        y_unrot = cy + dx * sin_r + dy * cos_r
        c_f = float(np.clip((x_unrot / max(1e-3, width_mm)) * (cols - 1), 0.0, cols - 1))
        r_f = float(np.clip((y_unrot / max(1e-3, depth_mm)) * (rows - 1), 0.0, rows - 1))
        c0, r0 = int(math.floor(c_f)), int(math.floor(r_f))
        c1, r1 = min(c0 + 1, cols - 1), min(r0 + 1, rows - 1)
        dc, dr = c_f - c0, r_f - r0
        e00 = max(min_elev, float(elev_grid[r0, c0]))
        e10 = max(min_elev, float(elev_grid[r0, c1]))
        e01 = max(min_elev, float(elev_grid[r1, c0]))
        e11 = max(min_elev, float(elev_grid[r1, c1]))
        elev_interp = (1.0 - dr) * ((1.0 - dc) * e00 + dc * e10) + dr * ((1.0 - dc) * e01 + dc * e11)
        z = base_height_mm + max(0.0, elev_interp - min_elev) * z_scale
        model_pts.append((x, y, z))

    # Construct swept path ribbon along waypoints
    def make_ribbon(half_w: float, z_bottom_delta: float, z_top_delta: float) -> SolidMesh:
        pts = np.array(model_pts)
        num_w = len(pts)
        verts = []
        faces = []

        # Generate left and right offset points along path
        for i in range(num_w):
            p = pts[i]
            if i == 0:
                tangent = pts[1] - pts[0]
            elif i == num_w - 1:
                tangent = pts[-1] - pts[-2]
            else:
                tangent = pts[i + 1] - pts[i - 1]
            
            # Normal in XY plane
            dx, dy = tangent[0], tangent[1]
            length = math.sqrt(dx * dx + dy * dy)
            if length == 0:
                nx, ny = 0, 1
            else:
                nx, ny = -dy / length, dx / length

            lx = p[0] + nx * half_w
            ly = p[1] + ny * half_w
            rx = p[0] - nx * half_w
            ry = p[1] - ny * half_w

            # 4 vertices per waypoint segment: bottom_left, bottom_right, top_left, top_right
            z_bot = p[2] + z_bottom_delta
            z_top = p[2] + z_top_delta

            verts.append([lx, ly, z_bot]) # 4*i + 0
            verts.append([rx, ry, z_bot]) # 4*i + 1
            verts.append([lx, ly, z_top]) # 4*i + 2
            verts.append([rx, ry, z_top]) # 4*i + 3

        verts = np.array(verts, dtype=np.float32)

        # Quads along segments
        for i in range(num_w - 1):
            bl0, br0, tl0, tr0 = 4 * i, 4 * i + 1, 4 * i + 2, 4 * i + 3
            bl1, br1, tl1, tr1 = 4 * (i + 1), 4 * (i + 1) + 1, 4 * (i + 1) + 2, 4 * (i + 1) + 3

            # Top surface (+Z)
            faces.append([tl0, tr0, tr1])
            faces.append([tl0, tr1, tl1])
            # Bottom surface (-Z)
            faces.append([bl0, br1, br0])
            faces.append([bl0, bl1, br1])
            # Left side
            faces.append([bl0, tl0, tl1])
            faces.append([bl0, tl1, bl1])
            # Right side
            faces.append([br0, tr1, tr0])
            faces.append([br0, br1, tr1])

        # Caps at ends
        # Start cap (i=0)
        faces.append([0, 1, 3])
        faces.append([0, 3, 2])
        # End cap (i=num_w-1)
        last = 4 * (num_w - 1)
        faces.append([last, last + 2, last + 3])
        faces.append([last, last + 3, last + 1])

        return SolidMesh(verts, np.array(faces, dtype=np.int32))

    # 1. Separate Inlay Piece:
    # Width = path_width_mm, recessed -path_depth_mm to +tactile_offset_mm
    inlay = make_ribbon(
        half_w=path_width_mm / 2.0,
        z_bottom_delta=-path_depth_mm,
        z_top_delta=tactile_offset_mm
    )

    # 2. Negative Cavity Cutter:
    # Width = path_width_mm + 2 * clearance_mm, depth = -path_depth_mm to +2.0mm above surface to cleanly cut terrain
    cutter = make_ribbon(
        half_w=(path_width_mm / 2.0) + clearance_mm,
        z_bottom_delta=-path_depth_mm,
        z_top_delta=2.0
    )

    return inlay, cutter


def generate_boundary_preview_mesh(
    elev_grid: np.ndarray,
    bbox: BoundingBox,
    boundary_geojson: Dict[str, Any],
    width_mm: float = 250.0,
    depth_mm: float = 250.0,
    base_height_mm: float = 4.0,
    target_relief_mm: float = 15.0
) -> Dict[str, Any]:
    """Generates preview mesh data for territorial / coastline boundaries
    ready for Three.js WebGL rendering.
    
    Returns:
        Dict with 'positions', 'indices', 'uvs', 'colors', 'norm_z', 'top_indices_count'.
    """
    raw_min = float(np.min(elev_grid))
    raw_max = float(np.max(elev_grid))
    clamp_ocean = (raw_min < -50 and raw_max > 0)
    min_e = 0.0 if clamp_ocean else raw_min
    delta = max(1.0, raw_max - min_e)

    geom = shape(boundary_geojson)
    if not geom.is_valid:
        geom = geom.buffer(0)
    if geom.geom_type == 'Polygon':
        polys = [geom]
    elif geom.geom_type == 'MultiPolygon':
        tot = geom.area
        polys = [p for p in geom.geoms if p.area / max(1e-9, tot) >= 0.005]
        polys.sort(key=lambda p: p.area, reverse=True)
    else:
        polys = []

    def get_color(elev_m: float) -> Tuple[float, float, float]:
        elev_ft = elev_m * 3.28084
        if elev_ft <= 0 or elev_m <= 0.5:
            if elev_ft < -60: return (0.10, 0.20, 0.55)
            return (0.14, 0.40, 0.85)
        if elev_ft < 500: return (0.18, 0.55, 0.28)
        if elev_ft < 1500: return (0.35, 0.65, 0.30)
        if elev_ft < 3000: return (0.75, 0.72, 0.35)
        if elev_ft < 6000: return (0.78, 0.55, 0.30)
        if elev_ft < 9000: return (0.65, 0.38, 0.25)
        if elev_ft < 12000: return (0.55, 0.35, 0.30)
        return (0.90, 0.90, 0.94)

    positions: List[float] = []
    colors: List[float] = []
    uvs: List[float] = []
    indices: List[int] = []
    norm_z: List[float] = []

    w_lon, e_lon = bbox.west, bbox.east
    s_lat, n_lat = bbox.south, bbox.north
    lon_span = max(1e-5, e_lon - w_lon)
    lat_span = max(1e-5, n_lat - s_lat)

    vert_offset = 0
    top_indices_count = 0

    rows, cols = elev_grid.shape

    for poly in polys:
        coords = list(poly.exterior.coords)
        if len(coords) < 3:
            continue
        if len(coords) > 250:
            poly = poly.simplify(0.01, preserve_topology=True)
            coords = list(poly.exterior.coords)

        perim_xy = [
            (
                ((lon - w_lon) / lon_span - 0.5) * width_mm,
                ((lat - s_lat) / lat_span - 0.5) * depth_mm
            )
            for lon, lat in coords[:-1]
        ]
        if len(perim_xy) < 3:
            continue

        sh_poly = Polygon(perim_xy)
        if not sh_poly.is_valid:
            sh_poly = sh_poly.buffer(0)

        minx, miny, maxx, maxy = sh_poly.bounds
        int_pts = []
        for x in np.linspace(minx, maxx, 22):
            for y in np.linspace(miny, maxy, 22):
                p = Point(x, y)
                if sh_poly.contains(p) and sh_poly.exterior.distance(p) > 1.5:
                    int_pts.append((x, y))

        pts_2d = perim_xy + int_pts
        pts_arr = np.array(pts_2d, dtype=np.float32)
        tri = Delaunay(pts_arr)
        valid_tris = []
        for s in tri.simplices:
            tri_pts = pts_arr[s]
            cp = Point(np.mean(tri_pts, axis=0))
            if sh_poly.contains(cp):
                v0, v1, v2 = tri_pts[0], tri_pts[1], tri_pts[2]
                det = (v1[0] - v0[0]) * (v2[1] - v0[1]) - (v1[1] - v0[1]) * (v2[0] - v0[0])
                if det < 0:
                    valid_tris.append([s[0], s[2], s[1]])
                else:
                    valid_tris.append(list(s))

        n_pts = len(pts_2d)
        # Sample elevations & top surface
        for x, y in pts_2d:
            u = max(0.0, min(1.0, (x / width_mm) + 0.5))
            v = max(0.0, min(1.0, (y / depth_mm) + 0.5))
            c = u * (cols - 1)
            r = v * (rows - 1)
            c0, r0 = int(c), int(r)
            elev = float(elev_grid[min(r0, rows - 1), min(c0, cols - 1)])
            norm = max(0.0, min(1.0, (elev - min_e) / delta))
            z = base_height_mm + norm * target_relief_mm

            positions.extend([float(x), float(y), float(z)])
            uvs.extend([float(u), float(v)])
            norm_z.append(float(norm))
            r_c, g_c, b_c = get_color(elev)
            colors.extend([r_c, g_c, b_c])

        # Top faces
        for f in valid_tris:
            indices.extend([vert_offset + f[0], vert_offset + f[1], vert_offset + f[2]])
        top_indices_count = len(indices)

        # Bottom floor vertices at Z = 0
        for x, y in pts_2d:
            positions.extend([float(x), float(y), 0.0])
            uvs.extend([0.0, 0.0])
            colors.extend([0.14, 0.15, 0.20])
            norm_z.append(-1.0)

        # Identify exact boundary edges of top surface
        edge_counts = {}
        for f in valid_tris:
            for i in range(3):
                e = (f[i], f[(i + 1) % 3])
                edge_counts[e] = edge_counts.get(e, 0) + 1
        top_boundary_edges = [e for e in edge_counts if (e[1], e[0]) not in edge_counts]

        # Skirt drop walls along exact boundary edges
        for e in top_boundary_edges:
            v_a, v_b = e
            indices.extend([vert_offset + v_a, vert_offset + n_pts + v_a, vert_offset + n_pts + v_b])
            indices.extend([vert_offset + v_a, vert_offset + n_pts + v_b, vert_offset + v_b])

        # Floor faces (inverted winding)
        for f in valid_tris:
            indices.extend([vert_offset + n_pts + f[0], vert_offset + n_pts + f[2], vert_offset + n_pts + f[1]])

        vert_offset += n_pts * 2

    return {
        "positions": [float(p) for p in positions],
        "indices": [int(i) for i in indices],
        "uvs": [float(u) for u in uvs],
        "colors": [float(c) for c in colors],
        "norm_z": [float(z) for z in norm_z],
        "top_indices_count": int(top_indices_count)
    }

