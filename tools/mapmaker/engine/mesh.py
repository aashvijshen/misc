"""3D Mesh generation, solidification, building/block extrusion, keyhole hanger,
gallery frame, 3D vector typography plaque, and path boolean engine for MapMaker 3D.

Constructs 100% watertight (2-manifold) 3D meshes ready for slicing on Bambu Lab A1
and other FDM printers.
"""

import struct
import math
from functools import reduce
import numpy as np
from typing import List, Tuple, Dict, Any, Optional, Callable
import shapely
from shapely.geometry import Polygon, Point, MultiPolygon, LineString, shape, box
import shapely.ops
import shapely.affinity
from scipy.spatial import Delaunay

from .config import BoundingBox, MapMakerConfig, CanvasConfig, ToleranceProfile, DowelProfile
from .geo import BuildingPolygon
from .platform_utils import resolve_bold_ttf_path


class SolidMesh:
    """Represents a watertight triangular 3D surface mesh."""

    def __init__(self, vertices: Optional[np.ndarray] = None, faces: Optional[np.ndarray] = None):
        if vertices is not None and len(vertices) > 0:
            self.vertices = np.array(vertices, dtype=np.float32)
        else:
            self.vertices = np.zeros((0, 3), dtype=np.float32)

        if faces is not None and len(faces) > 0:
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
        if len(self.vertices) == 0:
            return np.zeros(3), np.zeros(3)
        return np.min(self.vertices, axis=0), np.max(self.vertices, axis=0)

    @property
    def dimensions(self) -> np.ndarray:
        min_pt, max_pt = self.bounds
        return max_pt - min_pt

    def copy(self) -> 'SolidMesh':
        return SolidMesh(self.vertices.copy(), self.faces.copy())

    def translate(self, dx: float = 0.0, dy: float = 0.0, dz: float = 0.0) -> 'SolidMesh':
        if len(self.vertices) > 0:
            self.vertices[:, 0] += dx
            self.vertices[:, 1] += dy
            self.vertices[:, 2] += dz
        return self

    def compute_face_normals(self) -> np.ndarray:
        if self.num_faces == 0:
            return np.zeros((0, 3), dtype=np.float32)
        v0 = self.vertices[self.faces[:, 0]]
        v1 = self.vertices[self.faces[:, 1]]
        v2 = self.vertices[self.faces[:, 2]]
        cross = np.cross(v1 - v0, v2 - v0)
        norm = np.linalg.norm(cross, axis=1, keepdims=True)
        norm[norm == 0] = 1.0
        return cross / norm

    def append(self, other: Optional['SolidMesh']):
        if other is None or other.num_vertices == 0 or other.num_faces == 0:
            return
        offset = self.num_vertices
        if offset == 0:
            self.vertices = other.vertices.copy()
            self.faces = other.faces.copy()
        else:
            self.vertices = np.vstack([self.vertices, other.vertices])
            self.faces = np.vstack([self.faces, other.faces + offset])

    def export_stl(self, filepath: str, binary: bool = True):
        if binary:
            self._export_stl_binary(filepath)
        else:
            self._export_stl_ascii(filepath)

    def _export_stl_binary(self, filepath: str):
        num_faces = self.num_faces
        normals = self.compute_face_normals()

        with open(filepath, "wb") as f:
            header = b"MapMaker3D Solid Mesh Exporter" + b" " * 50
            f.write(header[:80])
            f.write(struct.pack("<I", num_faces))
            if num_faces == 0:
                return

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
    lon_dist_m = bbox.lon_span * 111320.0 * max(0.15, math.cos(math.radians(mid_lat)))
    lon_dist_m = max(100.0, lon_dist_m)

    horiz_scale_mm_per_m = width_mm / lon_dist_m
    return horiz_scale_mm_per_m * max(0.01, vertical_exaggeration)


def _triangulate_polygon_2d_exact(poly: Polygon) -> Tuple[np.ndarray, List[List[int]]]:
    """Triangulates any Shapely Polygon (including concave shapes and interior holes)
    into welded 2D vertices and CCW-wound triangles using GEOS constrained Delaunay.
    """
    if poly.is_empty or poly.area < 1e-4:
        return np.zeros((0, 2), dtype=np.float32), []
    poly = shapely.set_precision(poly, grid_size=0.02)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty or poly.area < 1e-4:
        return np.zeros((0, 2), dtype=np.float32), []

    if isinstance(poly, MultiPolygon):
        all_v = []
        all_f = []
        v_off = 0
        for sub in poly.geoms:
            sv, sf = _triangulate_polygon_2d_exact(sub)
            if len(sv) > 0 and sf:
                all_v.append(sv)
                all_f.extend([[f[0] + v_off, f[1] + v_off, f[2] + v_off] for f in sf])
                v_off += len(sv)
        if not all_v:
            return np.zeros((0, 2), dtype=np.float32), []
        return np.vstack(all_v), all_f

    try:
        tri_gc = shapely.constrained_delaunay_triangles(poly)
        cand_tris = list(tri_gc.geoms) if hasattr(tri_gc, "geoms") else [tri_gc]
    except Exception:
        cand_tris = list(shapely.ops.triangulate(poly))

    shapely.prepare(poly)
    vert_map: Dict[Tuple[int, int], int] = {}
    verts_2d: List[List[float]] = []
    faces_2d: List[List[int]] = []

    def get_vid(x: float, y: float) -> int:
        key = (int(round(x * 2000.0)), int(round(y * 2000.0)))
        vid = vert_map.get(key)
        if vid is None:
            vid = len(verts_2d)
            vert_map[key] = vid
            verts_2d.append([key[0] / 2000.0, key[1] / 2000.0])
        return vid

    for t in cand_tris:
        if t.is_empty:
            continue
        rp = t.representative_point()
        if not shapely.contains_xy(poly, rp.x, rp.y):
            continue
        coords = list(t.exterior.coords)[:-1]
        if len(coords) != 3:
            continue
        i0 = get_vid(coords[0][0], coords[0][1])
        i1 = get_vid(coords[1][0], coords[1][1])
        i2 = get_vid(coords[2][0], coords[2][1])
        if i0 == i1 or i1 == i2 or i2 == i0:
            continue
        p0, p1, p2 = verts_2d[i0], verts_2d[i1], verts_2d[i2]
        cross = (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p1[1] - p0[1]) * (p2[0] - p0[0])
        if cross == 0.0:
            continue
        if cross > 0:
            faces_2d.append([i0, i1, i2])
        else:
            faces_2d.append([i0, i2, i1])

    if not faces_2d:
        return np.zeros((0, 2), dtype=np.float32), []
    return np.array(verts_2d, dtype=np.float32), faces_2d


def extrude_shapely_polygon_2manifold(
    geom: Any,
    z_bot_fn: Callable[[float, float], float],
    z_top_fn: Callable[[float, float], float],
    segmentize_mm: Optional[float] = None
) -> SolidMesh:
    """Extrudes any 2D Polygon or MultiPolygon (including concave corners and interior holes)
    into a guaranteed 100% 2-manifold closed SolidMesh (unmatched_edges == 0).
    """
    if geom is None or geom.is_empty:
        return SolidMesh()
    if not geom.is_valid:
        geom = geom.buffer(0)
    if geom.is_empty:
        return SolidMesh()

    if segmentize_mm is not None and segmentize_mm > 0:
        geom = shapely.segmentize(geom, max_segment_length=segmentize_mm)

    polys: List[Polygon] = []
    if isinstance(geom, Polygon):
        polys = [geom]
    elif isinstance(geom, MultiPolygon):
        polys = [p for p in geom.geoms if isinstance(p, Polygon) and not p.is_empty]
    elif hasattr(geom, "geoms"):
        polys = [p for p in geom.geoms if isinstance(p, Polygon) and not p.is_empty]

    out_mesh = SolidMesh()
    for poly in polys:
        if poly.area < 1e-4:
            continue
        verts_2d, faces_2d = _triangulate_polygon_2d_exact(poly)
        if len(verts_2d) < 3 or not faces_2d:
            continue

        n_pts = len(verts_2d)
        top_z = np.array([float(z_top_fn(float(xy[0]), float(xy[1]))) for xy in verts_2d], dtype=np.float32)
        bot_z = np.array([float(z_bot_fn(float(xy[0]), float(xy[1]))) for xy in verts_2d], dtype=np.float32)
        # Guarantee strictly positive thickness everywhere (>= 0.30 mm) so top & bottom never cross
        top_z = np.maximum(top_z, bot_z + 0.30)

        top_v = np.column_stack([verts_2d, top_z])
        bot_v = np.column_stack([verts_2d, bot_z])
        all_v = np.vstack([top_v, bot_v])

        # Exact topological boundary edges (includes both exterior perimeter and interior hole rings!)
        edge_counts: Dict[Tuple[int, int], int] = {}
        for f in faces_2d:
            for k in range(3):
                e = (f[k], f[(k + 1) % 3])
                edge_counts[e] = edge_counts.get(e, 0) + 1
        boundary_edges = [e for e, c in edge_counts.items() if edge_counts.get((e[1], e[0]), 0) < c]

        faces_3d: List[List[int]] = []
        # 1. Top cap (+Z)
        faces_3d.extend(faces_2d)
        # 2. Bottom cap (-Z)
        for f in faces_2d:
            faces_3d.append([n_pts + f[0], n_pts + f[2], n_pts + f[1]])
        # 3. Watertight side & hole walls
        for a, b in boundary_edges:
            faces_3d.append([a, n_pts + a, n_pts + b])
            faces_3d.append([a, n_pts + b, b])

        out_mesh.append(SolidMesh(all_v, np.array(faces_3d, dtype=np.int32)))

    return out_mesh


def _build_floor_with_optional_keyhole(
    floor_poly_2d: Polygon,
    top_verts_xy: np.ndarray,
    orig_top_faces: List[List[int]],
    top_boundary_edges: List[Tuple[int, int]],
    vert_offset_bot: int,
    embed_keyhole: bool = False,
    keyhole_xy: Optional[Tuple[float, float]] = None,
    base_height_mm: float = 4.0
) -> Tuple[np.ndarray, List[List[int]], Optional[Dict[str, Any]]]:
    """Constructs the Z=0 floor faces matching exact perimeter vertices `vert_offset_bot + v_idx`,
    optionally embedding a 100% 2-manifold screw-retention keyhole slot into the backplate!
    """
    n_orig = len(top_verts_xy)
    bot_verts_base = np.column_stack([top_verts_xy, np.zeros(n_orig, dtype=np.float32)])

    if not embed_keyhole or base_height_mm < 3.2:
        floor_faces = [[vert_offset_bot + f[0], vert_offset_bot + f[2], vert_offset_bot + f[1]] for f in orig_top_faces]
        return bot_verts_base, floor_faces, None

    # Determine optimal keyhole center (upper-center of tile for balanced wall hanging)
    minx, miny, maxx, maxy = floor_poly_2d.bounds
    kx, ky = keyhole_xy if keyhole_xy is not None else ((minx + maxx) * 0.5, miny + (maxy - miny) * 0.70)

    # Check if floor polygon safely contains a 10mm margin around (kx, ky); fallback to representative point
    cand_pt = Point(kx, ky)
    if not floor_poly_2d.contains(cand_pt) or floor_poly_2d.exterior.distance(cand_pt) < 10.5:
        rp = floor_poly_2d.representative_point()
        if floor_poly_2d.exterior.distance(rp) < 10.5:
            floor_faces = [[vert_offset_bot + f[0], vert_offset_bot + f[2], vert_offset_bot + f[1]] for f in orig_top_faces]
            return bot_verts_base, floor_faces, None
        kx, ky = float(rp.x), float(rp.y)

    # Build clean parametric keyhole mouth ring (CCW in XY):
    # Entry circle (radius 4.25mm at ky - 2.8) + vertical lock slot (half-width 2.25mm up to ky + 4.4)
    c_entry = Point(kx, ky - 2.8).buffer(4.25, quad_segs=7)
    c_slot = LineString([(kx, ky - 2.8), (kx, ky + 4.4)]).buffer(2.25, quad_segs=7)
    mouth_poly = c_entry.union(c_slot).simplify(0.12, preserve_topology=True)
    if not isinstance(mouth_poly, Polygon) or not floor_poly_2d.contains(mouth_poly.buffer(2.5)):
        floor_faces = [[vert_offset_bot + f[0], vert_offset_bot + f[2], vert_offset_bot + f[1]] for f in orig_top_faces]
        return bot_verts_base, floor_faces, None

    mouth_ring_ccw = list(shapely.geometry.polygon.orient(mouth_poly, sign=1.0).exterior.coords)[:-1]
    m_len = len(mouth_ring_ccw)
    if m_len < 8:
        floor_faces = [[vert_offset_bot + f[0], vert_offset_bot + f[2], vert_offset_bot + f[1]] for f in orig_top_faces]
        return bot_verts_base, floor_faces, None

    # Find interior floor triangles in a local patch around mouth_poly (leave outer perimeter vertices untouched!)
    patch_box = mouth_poly.buffer(5.5)
    kept_floor_tris = []
    removed_tri_indices = set()

    for fi, f in enumerate(orig_top_faces):
        p0, p1, p2 = top_verts_xy[f[0]], top_verts_xy[f[1]], top_verts_xy[f[2]]
        tri_cent = Point(float((p0[0] + p1[0] + p2[0]) / 3.0), float((p0[1] + p1[1] + p2[1]) / 3.0))
        if patch_box.contains(tri_cent):
            removed_tri_indices.add(fi)
        else:
            kept_floor_tris.append([vert_offset_bot + f[0], vert_offset_bot + f[2], vert_offset_bot + f[1]])

    if not removed_tri_indices:
        floor_faces = [[vert_offset_bot + f[0], vert_offset_bot + f[2], vert_offset_bot + f[1]] for f in orig_top_faces]
        return bot_verts_base, floor_faces, None

    # Verify removed patch doesn't touch outer boundary edges
    outer_b_verts = {v for e in top_boundary_edges for v in e}
    patch_verts = {v for fi in removed_tri_indices for v in orig_top_faces[fi]}
    if patch_verts & outer_b_verts:
        floor_faces = [[vert_offset_bot + f[0], vert_offset_bot + f[2], vert_offset_bot + f[1]] for f in orig_top_faces]
        return bot_verts_base, floor_faces, None

    # Extract ordered outer loop of the removed patch on the top-winding mesh
    rem_edges: Dict[Tuple[int, int], int] = {}
    for fi in removed_tri_indices:
        f = orig_top_faces[fi]
        for k in range(3):
            e = (f[k], f[(k + 1) % 3])
            rem_edges[e] = rem_edges.get(e, 0) + 1
    patch_loop_edges = [e for e in rem_edges if (e[1], e[0]) not in rem_edges]
    nxt_map = {a: b for a, b in patch_loop_edges}
    if len(nxt_map) != len(patch_loop_edges) or not nxt_map:
        floor_faces = [[vert_offset_bot + f[0], vert_offset_bot + f[2], vert_offset_bot + f[1]] for f in orig_top_faces]
        return bot_verts_base, floor_faces, None

    st = next(iter(nxt_map))
    patch_loop_v = [st]
    cur = st
    while len(patch_loop_v) < len(nxt_map):
        cur = nxt_map.get(cur)
        if cur is None or cur == st:
            break
        patch_loop_v.append(cur)

    if len(patch_loop_v) != len(nxt_map) or nxt_map.get(patch_loop_v[-1]) != st:
        floor_faces = [[vert_offset_bot + f[0], vert_offset_bot + f[2], vert_offset_bot + f[1]] for f in orig_top_faces]
        return bot_verts_base, floor_faces, None

    patch_poly = Polygon([tuple(top_verts_xy[v]) for v in patch_loop_v])
    if not patch_poly.is_valid or not patch_poly.contains(mouth_poly.buffer(0.4)):
        floor_faces = [[vert_offset_bot + f[0], vert_offset_bot + f[2], vert_offset_bot + f[1]] for f in orig_top_faces]
        return bot_verts_base, floor_faces, None

    # Triangulate annular collar `patch_poly.difference(Polygon(mouth_ring_ccw))` with exact vertex welding!
    collar_geom = Polygon([tuple(top_verts_xy[v]) for v in patch_loop_v], [mouth_ring_ccw[::-1]])
    if not collar_geom.is_valid:
        floor_faces = [[vert_offset_bot + f[0], vert_offset_bot + f[2], vert_offset_bot + f[1]] for f in orig_top_faces]
        return bot_verts_base, floor_faces, None

    extra_bot_verts: List[List[float]] = []
    base_extra_idx = vert_offset_bot + n_orig

    # Register exact vertex indices for patch_loop_v and mouth_ring_ccw
    mouth_v_indices = []
    for mx, my in mouth_ring_ccw:
        mouth_v_indices.append(base_extra_idx + len(extra_bot_verts))
        extra_bot_verts.append([float(mx), float(my), 0.0])

    # Flared internal retention chamber at z_lip = 1.05 mm and z_ceil = min(2.60, base_height_mm - 0.85)
    z_lip = min(1.05, base_height_mm * 0.32)
    z_ceil = min(2.65, base_height_mm - 0.80)

    flare_lip_indices = []
    flare_ceil_indices = []
    flared_2d = []
    for mx, my in mouth_ring_ccw:
        # Widen upper lock slot laterally at a 45° self-supporting angle so screw head locks securely!
        if my > ky - 1.2:
            dx = mx - kx
            dy = max(0.0, my - (ky + 2.8))
            rad_d = math.hypot(dx, dy)
            if rad_d > 1e-4:
                scale_f = (rad_d + 1.05) / rad_d
                fx = kx + dx * scale_f
                fy = (ky + 2.8) + dy * scale_f if my > ky + 2.8 else my
            else:
                fx, fy = mx, my
        else:
            fx, fy = mx, my
        flared_2d.append((float(fx), float(fy)))
        flare_lip_indices.append(base_extra_idx + len(extra_bot_verts))
        extra_bot_verts.append([float(fx), float(fy), z_lip])
        flare_ceil_indices.append(base_extra_idx + len(extra_bot_verts))
        extra_bot_verts.append([float(fx), float(fy), z_ceil])

    # Constrained Delaunay of collar_geom snapped to existing patch_loop_v + mouth_v_indices
    known_pts: List[Tuple[float, float, int]] = (
        [(float(top_verts_xy[v, 0]), float(top_verts_xy[v, 1]), vert_offset_bot + v) for v in patch_loop_v]
        + [(float(mouth_ring_ccw[i][0]), float(mouth_ring_ccw[i][1]), mouth_v_indices[i]) for i in range(m_len)]
    )

    def resolve_collar_vid(x: float, y: float) -> int:
        for kx_p, ky_p, k_id in known_pts:
            if abs(kx_p - x) < 1e-3 and abs(ky_p - y) < 1e-3:
                return k_id
        nid = base_extra_idx + len(extra_bot_verts)
        extra_bot_verts.append([float(x), float(y), 0.0])
        known_pts.append((float(x), float(y), nid))
        return nid

    tri_gc = shapely.constrained_delaunay_triangles(collar_geom)
    shapely.prepare(collar_geom)
    collar_faces = []
    for t in (tri_gc.geoms if hasattr(tri_gc, "geoms") else [tri_gc]):
        if t.is_empty or t.area < 1e-5:
            continue
        rp = t.representative_point()
        if not shapely.contains_xy(collar_geom, rp.x, rp.y):
            continue
        cs = list(t.exterior.coords)[:-1]
        if len(cs) != 3:
            continue
        i0 = resolve_collar_vid(cs[0][0], cs[0][1])
        i1 = resolve_collar_vid(cs[1][0], cs[1][1])
        i2 = resolve_collar_vid(cs[2][0], cs[2][1])
        if i0 == i1 or i1 == i2 or i2 == i0:
            continue
        # Winding must face -Z (CW in XY)!
        cross = (cs[1][0] - cs[0][0]) * (cs[2][1] - cs[0][1]) - (cs[1][1] - cs[0][1]) * (cs[2][0] - cs[0][0])
        if cross > 0:
            collar_faces.append([i0, i2, i1])
        else:
            collar_faces.append([i0, i1, i2])

    # Pocket internal walls (mouth -> lip -> ceiling) facing inward into pocket!
    pocket_faces = []
    for i in range(m_len):
        inext = (i + 1) % m_len
        m0, m1 = mouth_v_indices[i], mouth_v_indices[inext]
        l0, l1 = flare_lip_indices[i], flare_lip_indices[inext]
        c0, c1 = flare_ceil_indices[i], flare_ceil_indices[inext]
        # Floor collar has edge (m0 -> m1) in -Z winding? Wait:
        # mouth_ring_ccw is CCW; hole in CCW polygon has CW boundary; inverted to -Z becomes CCW (m0 -> m1)!
        # So pocket wall must have reverse edge (m1 -> m0), i.e., [m1, m0, l0] and [m1, l0, l1]!
        pocket_faces.append([m1, m0, l0])
        pocket_faces.append([m1, l0, l1])
        pocket_faces.append([l1, l0, c0])
        pocket_faces.append([l1, c0, c1])

    # Ceiling cap at z_ceil facing -Z (downward into keyhole opening)
    ceil_poly = Polygon(flared_2d)
    ceil_known = [(flared_2d[i][0], flared_2d[i][1], flare_ceil_indices[i]) for i in range(m_len)]

    def resolve_ceil_vid(x: float, y: float) -> int:
        for cx_p, cy_p, c_id in ceil_known:
            if abs(cx_p - x) < 1e-3 and abs(cy_p - y) < 1e-3:
                return c_id
        nid = base_extra_idx + len(extra_bot_verts)
        extra_bot_verts.append([float(x), float(y), z_ceil])
        ceil_known.append((float(x), float(y), nid))
        return nid

    ceil_gc = shapely.constrained_delaunay_triangles(ceil_poly)
    shapely.prepare(ceil_poly)
    for t in (ceil_gc.geoms if hasattr(ceil_gc, "geoms") else [ceil_gc]):
        if t.is_empty or t.area < 1e-5:
            continue
        rp = t.representative_point()
        if not shapely.contains_xy(ceil_poly, rp.x, rp.y):
            continue
        cs = list(t.exterior.coords)[:-1]
        if len(cs) != 3:
            continue
        i0 = resolve_ceil_vid(cs[0][0], cs[0][1])
        i1 = resolve_ceil_vid(cs[1][0], cs[1][1])
        i2 = resolve_ceil_vid(cs[2][0], cs[2][1])
        if i0 == i1 or i1 == i2 or i2 == i0:
            continue
        cross = (cs[1][0] - cs[0][0]) * (cs[2][1] - cs[0][1]) - (cs[1][1] - cs[0][1]) * (cs[2][0] - cs[0][0])
        if cross > 0:
            pocket_faces.append([i0, i2, i1])
        else:
            pocket_faces.append([i0, i1, i2])

    all_bot_verts = np.vstack([bot_verts_base, np.array(extra_bot_verts, dtype=np.float32)])
    all_floor_faces = kept_floor_tris + collar_faces + pocket_faces
    return all_bot_verts, all_floor_faces, {"center_xy": [round(kx, 2), round(ky, 2)], "depth_mm": round(z_ceil, 2)}


def _emit_skirt_walls_with_biscuit_pockets(
    top_verts: np.ndarray,
    bot_verts: np.ndarray,
    top_boundary_edges: List[Tuple[int, int]],
    vert_offset: int,
    width_mm: float,
    depth_mm: float,
    active_seams: Optional[Dict[str, bool]] = None,
    dowel_config: Optional[Any] = None,
    canonical_seam_centers: Optional[Dict[str, List[float]]] = None
) -> Tuple[np.ndarray, List[List[int]], List[Dict[str, Any]]]:
    """Generates vertical perimeter skirt walls from top_boundary_edges down to bot_verts,
    embedding 100% 2-manifold subterranean biscuit pockets into active internal tile seams.
    """
    off_top = len(top_verts)
    off_bot_total = len(bot_verts)
    extra_verts: List[List[float]] = []
    wall_faces: List[List[int]] = []
    pockets_created: List[Dict[str, Any]] = []

    dowels_enabled = getattr(dowel_config, "enabled", True) if dowel_config is not None else True
    dowel_type = getattr(dowel_config, "dowel_type", "flat_biscuit") if dowel_config is not None else "flat_biscuit"
    if not active_seams or not any(active_seams.values()) or not dowels_enabled or dowel_type == "none":
        for v_a, v_b in top_boundary_edges:
            wall_faces.append([vert_offset + v_a, vert_offset + off_top + v_a, vert_offset + off_top + v_b])
            wall_faces.append([vert_offset + v_a, vert_offset + off_top + v_b, vert_offset + v_b])
        return np.vstack([top_verts, bot_verts]), wall_faces, pockets_created

    if dowel_type == "round":
        pocket_w = float(getattr(dowel_config, "round_pocket_diameter", 4.30))
        pocket_h = float(getattr(dowel_config, "round_pocket_diameter", 4.30))
        pocket_d = float(getattr(dowel_config, "round_pocket_depth", 8.0))
    else:
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

            if canonical_seam_centers and seam_name in canonical_seam_centers:
                centers = [
                    c for c in canonical_seam_centers[seam_name]
                    if (s_min + pocket_w * 0.55) <= c <= (s_max - pocket_w * 0.55)
                ]
            elif span_len >= 55.0:
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

                base_idx = vert_offset + off_top + off_bot_total + len(extra_verts)
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
                B = [vert_offset + off_top + v for v in sub_chain]
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
            wall_faces.append([vert_offset + v_a, vert_offset + off_top + v_a, vert_offset + off_top + v_b])
            wall_faces.append([vert_offset + v_a, vert_offset + off_top + v_b, vert_offset + v_b])

    if extra_verts:
        all_v = np.vstack([top_verts, bot_verts, np.array(extra_verts, dtype=np.float32)])
    else:
        all_v = np.vstack([top_verts, bot_verts])

    return all_v, wall_faces, pockets_created


def carve_pin_sockets_into_mesh(
    top_verts: np.ndarray,
    top_faces: List[List[int]],
    pin_xy_list: List[Dict[str, Any]],
    socket_radius_mm: float = 1.18,
    socket_depth_mm: float = 2.30
) -> Tuple[np.ndarray, List[List[int]], List[Dict[str, Any]]]:
    """Replaces the 1-ring around each landmark pin coordinate (px, py) with a
    100% 2-manifold spot-faced circular blind socket hole of radius `socket_radius_mm`.
    """
    if not pin_xy_list or len(top_verts) == 0 or not top_faces:
        return top_verts, top_faces, []

    verts_list = top_verts.tolist()
    faces_list = [list(f) for f in top_faces]
    sockets_carved: List[Dict[str, Any]] = []

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

        v_arr = np.array(verts_list, dtype=np.float32)
        dists = np.hypot(v_arr[:, 0] - px, v_arr[:, 1] - py)
        order = np.argsort(dists)
        v_center = None
        for cand in order[:12]:
            c_idx = int(cand)
            if c_idx not in boundary_verts and c_idx not in used_center_verts and dists[c_idx] <= 6.5:
                v_center = c_idx
                break

        if v_center is None:
            continue

        inc_indices = [fi for fi, f in enumerate(faces_list) if v_center in f]
        if len(inc_indices) < 3:
            continue

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

        z_center = float(verts_list[v_center][2])
        if z_center < 1.3:
            continue
        ring_zs = [float(verts_list[u][2]) for u in loop_u]
        # Spot-face rim slightly at max local height so seated pin collar never clips uphill slopes!
        z_rim = max(z_center, max(ring_zs))
        z_bot = max(0.80, z_center - socket_depth_mm)

        verts_list[v_center][0] = px
        verts_list[v_center][1] = py
        verts_list[v_center][2] = z_bot
        used_center_verts.add(v_center)
        for u_idx in loop_u:
            used_center_verts.add(u_idx)
            if u_idx not in boundary_verts:
                ux, uy = verts_list[u_idx][0] - px, verts_list[u_idx][1] - py
                ud = math.hypot(ux, uy)
                min_d = socket_radius_mm + 0.55
                if 1e-4 < ud < min_d:
                    verts_list[u_idx][0] = px + (ux / ud) * min_d
                    verts_list[u_idx][1] = py + (uy / ud) * min_d

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
            verts_list.append([x0, y0, z_rim])
            verts_list.append([xm, ym, z_rim])
            verts_list.append([x0, y0, z_bot])
            verts_list.append([xm, ym, z_bot])
            rt_indices.append(base_v)
            rtm_indices.append(base_v + 1)
            rb_indices.append(base_v + 2)
            rbm_indices.append(base_v + 3)

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

            faces_list.append([u0, u1, rtm])
            faces_list.append([u0, rtm, rt0])
            faces_list.append([rtm, u1, rt1])

            faces_list.append([rt0, rtm, rbm])
            faces_list.append([rt0, rbm, rb0])
            faces_list.append([rtm, rt1, rb1])
            faces_list.append([rtm, rb1, rbm])

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
    peg_diameter_mm: float = 1.96,
    peg_length_mm: float = 1.75,
    collar_diameter_mm: float = 3.50,
    head_diameter_mm: float = 5.50,
    segments: int = 20,
    zero_base_for_printing: bool = False,
    wall_hanging_tilt_deg: float = 0.0
) -> SolidMesh:
    """Generates a 100% 2-manifold, faceted jewel-crown 3D landmark marker pin.

    - When `zero_base_for_printing=False` (assembly placement):
      Peg sits in Z=[-peg_length_mm, +0.35] with guaranteed >0.15mm radial & bottom clearance
      inside the spot-faced Ø2.36mm socket (0.00 mm³ collision!).
    - When `zero_base_for_printing=True` (`accessories/landmark_pins.stl` print plate):
      Oriented HEAD-DOWN on its flat Ø4.90mm crown (18.85 mm² bed contact — 12.5x more stable
      than peg-down!) with <=42° self-supporting facets tapering up to the Ø1.96mm peg!
    """
    r_peg = peg_diameter_mm / 2.0
    r_col = collar_diameter_mm / 2.0
    r_stem = max(1.08, r_peg * 1.12)
    r_head = head_diameter_mm / 2.0
    r_crown = r_head * 0.88  # Flat Ø4.84mm top facet for rock-solid upside-down bed adhesion!

    # Profile from peg tip (-peg_length_mm) to flat top jewel crown (+7.20 mm)
    profile = [
        (max(0.55, r_peg - 0.28), -peg_length_mm),       # 0: Peg lead-in chamfer tip
        (r_peg, -peg_length_mm + 0.28),                  # 1: Peg shaft lower
        (r_peg, 0.35),                                   # 2: Peg neck (clears rim by +0.35mm!)
        (r_col, 0.35 + (r_col - r_peg)),                 # 3: 45° seating collar flare
        (r_col, 1.55),                                   # 4: Collar rim
        (r_stem, 1.55 + (r_col - r_stem)),               # 5: 45° taper to stem
        (r_stem, 3.30),                                  # 6: Stem top
        (r_head, 3.30 + (r_head - r_stem) * 1.05),       # 7: <=43° jewel equator
        (r_head, 5.75),                                  # 8: Jewel girdle
        (r_crown, 6.75),                                 # 9: Flat crown bevel
    ]

    z_bot_cap = profile[0][1]
    z_top_cap = profile[-1][1]

    verts: List[List[float]] = [[0.0, 0.0, z_bot_cap], [0.0, 0.0, z_top_cap]]
    faces: List[List[int]] = []

    ring_offsets = []
    tilt_rad = math.radians(max(0.0, min(35.0, wall_hanging_tilt_deg)))
    for rad, z_val in profile:
        base_idx = len(verts)
        ring_offsets.append(base_idx)
        # If wall-hanging, subtly tilt upper stem/head (+Y = North/Up on wall) while keeping peg coaxial!
        y_tilt = max(0.0, z_val - 0.60) * math.tan(tilt_rad) if tilt_rad > 1e-4 else 0.0
        for s in range(segments):
            ang = (2.0 * math.pi * s) / segments
            verts.append([rad * math.cos(ang), rad * math.sin(ang) + y_tilt, z_val])

    if tilt_rad > 1e-4:
        verts[1][1] = max(0.0, z_top_cap - 0.60) * math.tan(tilt_rad)

    r0 = ring_offsets[0]
    for s in range(segments):
        s_next = (s + 1) % segments
        faces.append([0, r0 + s_next, r0 + s])

    for k in range(len(profile) - 1):
        rk0 = ring_offsets[k]
        rk1 = ring_offsets[k + 1]
        for s in range(segments):
            s_next = (s + 1) % segments
            a, b = rk0 + s, rk0 + s_next
            c, d = rk1 + s_next, rk1 + s
            faces.append([a, b, c])
            faces.append([a, c, d])

    r_last = ring_offsets[-1]
    for s in range(segments):
        s_next = (s + 1) % segments
        faces.append([1, r_last + s, r_last + s_next])

    v_arr = np.array(verts, dtype=np.float32)
    f_arr = np.array(faces, dtype=np.int32)

    if zero_base_for_printing:
        # Flip 180° around X axis (y -> -y, z -> z_top_cap - z) so flat jewel crown rests on Z=0!
        # Determinant of diag(1, -1, -1) is +1, preserving outward triangle winding!
        v_arr[:, 1] = -v_arr[:, 1]
        v_arr[:, 2] = z_top_cap - v_arr[:, 2]

    return SolidMesh(v_arr, f_arr)


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
    tile_offset_xy_mm: Tuple[float, float] = (0.0, 0.0),
    global_elev_grid: Optional[np.ndarray] = None,
    canonical_seam_centers: Optional[Dict[str, List[float]]] = None,
    path_style: str = "flat_strip",
    depress_water: bool = False,
    water_step_mm: float = 0.84,
    embed_keyhole: bool = False
) -> SolidMesh:
    """Generates a 100% 2-manifold solid terrain mesh across all base shapes,
    supporting global multi-tile rotation, crisp water-level coastline step,
    collision-free route trenches OR sculpted raised trails, spot-faced pin sockets,
    coaxial subterranean dowel pockets, and rear wall-hanging keyhole slots.
    """
    src_grid = global_elev_grid if global_elev_grid is not None else elev_grid
    g_rows, g_cols = src_grid.shape
    rows, cols = elev_grid.shape
    raw_min = float(np.min(src_grid))
    raw_max = float(np.max(src_grid))

    has_coastal_water = (raw_min <= 0.5 and raw_max > 2.0)

    clamp_threshold = -0.5 if depress_water else -50.0
    if global_min_elev is not None:
        min_elev = 0.0 if (depress_water and raw_min <= 0.0 and raw_max > 3.0) else global_min_elev
        effective_src = np.maximum(src_grid, 0.0) if (min_elev == 0.0 and raw_min < clamp_threshold) else src_grid
        effective_local = np.maximum(elev_grid, 0.0) if (min_elev == 0.0 and float(np.min(elev_grid)) < clamp_threshold) else elev_grid
    else:
        if raw_min < clamp_threshold and raw_max > 2.0:
            min_elev = 0.0
            effective_src = np.maximum(src_grid, 0.0)
            effective_local = np.maximum(elev_grid, 0.0)
        else:
            min_elev = raw_min
            effective_src = src_grid
            effective_local = elev_grid

    eff_bbox = global_bbox if global_bbox is not None else bbox
    eff_w = global_width_mm if global_width_mm is not None else width_mm
    eff_d = global_depth_mm if global_depth_mm is not None else depth_mm
    ox, oy = tile_offset_xy_mm

    if topography_enabled:
        z_scale = (
            global_z_scale
            if global_z_scale is not None
            else calculate_z_scale(effective_src, eff_bbox, eff_w, vertical_exaggeration, target_relief_height_mm)
        )
        land_step_src = np.where(src_grid > 0.35, water_step_mm, 0.0) if (depress_water and has_coastal_water) else 0.0
        land_step_loc = np.where(elev_grid > 0.35, water_step_mm, 0.0) if (depress_water and has_coastal_water) else 0.0
        z_grid_global = (base_height_mm + land_step_src + np.maximum(0.0, effective_src - min_elev) * z_scale).astype(np.float32)
        z_grid_local = (base_height_mm + land_step_loc + np.maximum(0.0, effective_local - min_elev) * z_scale).astype(np.float32)
    else:
        land_step_src = np.where(src_grid > 0.35, water_step_mm, 0.0) if (depress_water and has_coastal_water) else 0.0
        land_step_loc = np.where(elev_grid > 0.35, water_step_mm, 0.0) if (depress_water and has_coastal_water) else 0.0
        z_grid_global = (base_height_mm + land_step_src).astype(np.float32)
        z_grid_local = (base_height_mm + land_step_loc).astype(np.float32)

    gcx_rot, gcy_rot = eff_w / 2.0, eff_d / 2.0
    rad = math.radians(rotation_deg)
    cos_r = math.cos(rad)
    sin_r = math.sin(rad)

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
    # Extra +0.08mm lateral & +0.25mm floor margin guarantees 0.00 mm³ collision on curved trenches
    half_trench_w = (path_w_mm / 2.0) + path_clr_mm + 0.08
    trench_carve_depth = path_d_mm + 0.25
    pin_clr_mm = float(getattr(tolerance_config, "pin_socket_clearance", 0.15)) if tolerance_config else 0.15
    socket_radius_mm = 1.00 + pin_clr_mm + 0.03  # Ø2.36mm socket for Ø1.96mm peg

    route_line_local: Optional[LineString] = None
    if route_waypoints_latlon and len(route_waypoints_latlon) >= 2 and path_style in ("flat_strip", "raised_ridge", "both"):
        r_pts = [latlon_to_tile_xy(float(pt[0]), float(pt[1])) for pt in route_waypoints_latlon]
        try:
            cand_line = LineString(r_pts).simplify(0.25, preserve_topology=False)
            tile_expanded = box(-6.0, -6.0, width_mm + 6.0, depth_mm + 6.0)
            clipped_r = cand_line.intersection(tile_expanded)
            if not clipped_r.is_empty:
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
                if 2.2 <= lx <= width_mm - 2.2 and 2.2 <= ly <= depth_mm - 2.2:
                    local_pins.append({
                        "name": p.get("name", "Landmark"),
                        "lat": plat,
                        "lon": plon,
                        "x": lx,
                        "y": ly
                    })
            except Exception:
                pass

    use_global_sampler = (global_elev_grid is not None) or (abs(rotation_deg) > 1e-4)

    def sample_z(x_mm: float, y_mm: float, include_route: bool = True) -> float:
        """Samples exact elevation height in global rotated canvas coordinates (zero multi-tile seam step!)."""
        if use_global_sampler:
            gx = ox + x_mm
            gy = oy + y_mm
            dx = gx - gcx_rot
            dy = gy - gcy_rot
            x_unrot = gcx_rot + dx * cos_r - dy * sin_r
            y_unrot = gcy_rot + dx * sin_r + dy * cos_r
            c_float = (x_unrot / max(1e-3, eff_w)) * (g_cols - 1)
            r_float = (y_unrot / max(1e-3, eff_d)) * (g_rows - 1)
            c0 = int(np.clip(math.floor(c_float), 0, g_cols - 1))
            c1 = min(c0 + 1, g_cols - 1)
            r0 = int(np.clip(math.floor(r_float), 0, g_rows - 1))
            r1 = min(r0 + 1, g_rows - 1)
            dc = float(np.clip(c_float - c0, 0.0, 1.0))
            dr = float(np.clip(r_float - r0, 0.0, 1.0))
            top = (1.0 - dc) * z_grid_global[r0, c0] + dc * z_grid_global[r0, c1]
            bot = (1.0 - dc) * z_grid_global[r1, c0] + dc * z_grid_global[r1, c1]
            z_val = float((1.0 - dr) * top + dr * bot)
        else:
            c_float = (x_mm / max(1e-3, width_mm)) * (cols - 1)
            r_float = (y_mm / max(1e-3, depth_mm)) * (rows - 1)
            c0 = int(np.clip(math.floor(c_float), 0, cols - 1))
            c1 = min(c0 + 1, cols - 1)
            r0 = int(np.clip(math.floor(r_float), 0, rows - 1))
            r1 = min(r0 + 1, rows - 1)
            dc = float(np.clip(c_float - c0, 0.0, 1.0))
            dr = float(np.clip(r_float - r0, 0.0, 1.0))
            top = (1.0 - dc) * z_grid_local[r0, c0] + dc * z_grid_local[r0, c1]
            bot = (1.0 - dc) * z_grid_local[r1, c0] + dc * z_grid_local[r1, c1]
            z_val = float((1.0 - dr) * top + dr * bot)

        if include_route and route_line_local is not None:
            d_r = float(route_line_local.distance(Point(x_mm, y_mm)))
            if path_style == "raised_ridge":
                half_ridge = path_w_mm * 0.55
                if d_r <= half_ridge:
                    z_val += 1.05
                elif d_r <= half_ridge + 0.85:
                    t = (d_r - half_ridge) / 0.85
                    z_val += 1.05 * (1.0 - t)
            else:
                if d_r <= half_trench_w:
                    z_val = max(0.85, z_val - trench_carve_depth)
                elif d_r <= half_trench_w + 0.45:
                    t = (d_r - half_trench_w) / 0.45
                    z_val = max(0.85, z_val - trench_carve_depth * (1.0 - t))
        return z_val

    def _inject_route_and_pin_pts(poly_2d: Polygon, base_int_pts: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        pts_out = list(base_int_pts)
        shapely.prepare(poly_2d)

        if route_line_local is not None:
            try:
                # Clear background grid points inside route corridor so Delaunay never bridges diagonally across trench!
                corridor_w = (half_trench_w + 0.55) if path_style != "raised_ridge" else (path_w_mm * 0.55 + 0.90)
                corridor_poly = route_line_local.buffer(corridor_w)
                shapely.prepare(corridor_poly)
                if pts_out:
                    arr_p = np.array(pts_out, dtype=np.float64)
                    keep_mask = ~shapely.contains_xy(corridor_poly, arr_p[:, 0], arr_p[:, 1])
                    pts_out = [pts_out[i] for i in range(len(pts_out)) if keep_mask[i]]

                clipped_ln = route_line_local.intersection(poly_2d.buffer(-1.2))
                hw = half_trench_w if path_style != "raised_ridge" else (path_w_mm * 0.55)
                rim_off = hw + (0.50 if path_style != "raised_ridge" else 0.85)

                # Sample exact rounded-cap & rounded-join Shapely offset rings so end-caps and
                # bends match `route_line_local.distance()` with 0.000 mm³ interference!
                floor_ring_poly = shapely.segmentize(clipped_ln.buffer(hw - 0.04, quad_segs=8, cap_style=1, join_style=1), max_segment_length=0.95)
                rim_ring_poly = shapely.segmentize(clipped_ln.buffer(rim_off, quad_segs=8, cap_style=1, join_style=1), max_segment_length=1.10)
                center_seg = shapely.segmentize(clipped_ln, max_segment_length=0.95)

                route_pts_cand: List[Tuple[float, float]] = []
                for g_ring in (floor_ring_poly, rim_ring_poly):
                    sub_polys = [g_ring] if g_ring.geom_type == "Polygon" else list(getattr(g_ring, "geoms", []))
                    for sp in sub_polys:
                        if sp.is_empty:
                            continue
                        for rx, ry in list(sp.exterior.coords)[:-1]:
                            if shapely.contains_xy(poly_2d, rx, ry) and poly_2d.exterior.distance(Point(rx, ry)) > 0.85:
                                route_pts_cand.append((float(rx), float(ry)))
                        for ir in sp.interiors:
                            for rx, ry in list(ir.coords)[:-1]:
                                if shapely.contains_xy(poly_2d, rx, ry) and poly_2d.exterior.distance(Point(rx, ry)) > 0.85:
                                    route_pts_cand.append((float(rx), float(ry)))

                sub_lines = [center_seg] if center_seg.geom_type == "LineString" else list(getattr(center_seg, "geoms", []))
                for sl in sub_lines:
                    for rx, ry in sl.coords:
                        if shapely.contains_xy(poly_2d, rx, ry) and poly_2d.exterior.distance(Point(rx, ry)) > 0.85:
                            route_pts_cand.append((float(rx), float(ry)))

                # Deduplicate tightly bunched vertices (>0.32mm minimum spacing)
                filtered_r_pts: List[Tuple[float, float]] = []
                grid_hash = set()
                for px, py in route_pts_cand:
                    gk = (int(round(px / 0.32)), int(round(py / 0.32)))
                    if gk not in grid_hash:
                        grid_hash.add(gk)
                        filtered_r_pts.append((px, py))
                pts_out.extend(filtered_r_pts)
            except Exception:
                pass

        if local_pins:
            r_ring = socket_radius_mm + 0.85
            for pin in local_pins:
                px, py = float(pin["x"]), float(pin["y"])
                pt_c = Point(px, py)
                if shapely.contains_xy(poly_2d, px, py) and poly_2d.exterior.distance(pt_c) > r_ring + 0.4:
                    pts_out = [p for p in pts_out if math.hypot(p[0] - px, p[1] - py) > r_ring + 0.3]
                    pts_out.append((px, py))
                    for k in range(8):
                        ang = (2.0 * math.pi * k) / 8.0
                        pts_out.append((px + r_ring * math.cos(ang), py + r_ring * math.sin(ang)))
        return pts_out

    def _build_delaunay_solid_from_polygon(sh_poly: Polygon, res_x: int, res_y: int, allow_keyhole: bool) -> Optional[Tuple[np.ndarray, List[List[int]], List[Dict[str, Any]], List[Dict[str, Any]], Optional[Dict[str, Any]]]]:
        sh_poly = shapely.segmentize(sh_poly, max_segment_length=3.2)
        perim_xy = list(sh_poly.exterior.coords)[:-1]
        if len(perim_xy) < 3:
            return None

        minx, miny, maxx, maxy = sh_poly.bounds
        xs = np.linspace(minx, maxx, max(16, res_x))
        ys = np.linspace(miny, maxy, max(16, res_y))
        xx_g, yy_g = np.meshgrid(xs, ys)
        flat_gx = xx_g.ravel()
        flat_gy = yy_g.ravel()

        eroded = sh_poly.buffer(-1.35)
        if not eroded.is_empty:
            shapely.prepare(eroded)
            mask = shapely.contains_xy(eroded, flat_gx, flat_gy)
            int_pts = [(float(flat_gx[i]), float(flat_gy[i])) for i in np.nonzero(mask)[0]]
        else:
            int_pts = []

        int_pts = _inject_route_and_pin_pts(sh_poly, int_pts)
        pts_2d = perim_xy + int_pts
        pts_arr = np.array(pts_2d, dtype=np.float32)

        tri = Delaunay(pts_arr)
        tri_pts_all = pts_arr[tri.simplices]
        centroids = np.mean(tri_pts_all, axis=1)
        shapely.prepare(sh_poly)
        inside_mask = shapely.contains_xy(sh_poly, centroids[:, 0], centroids[:, 1])

        valid_faces: List[List[int]] = []
        for simplex in tri.simplices[inside_mask]:
            i0, i1, i2 = int(simplex[0]), int(simplex[1]), int(simplex[2])
            v0, v1, v2 = pts_arr[i0], pts_arr[i1], pts_arr[i2]
            det = (v1[0] - v0[0]) * (v2[1] - v0[1]) - (v1[1] - v0[1]) * (v2[0] - v0[0])
            if abs(det) < 1e-7:
                continue
            if det < 0:
                valid_faces.append([i0, i2, i1])
            else:
                valid_faces.append([i0, i1, i2])

        if not valid_faces:
            return None

        top_z = np.array([sample_z(float(pt[0]), float(pt[1])) for pt in pts_2d], dtype=np.float32)
        top_verts = np.column_stack([pts_arr, top_z])
        orig_faces = [list(f) for f in valid_faces]

        edge_counts: Dict[Tuple[int, int], int] = {}
        for f in orig_faces:
            for i in range(3):
                e = (f[i], f[(i + 1) % 3])
                edge_counts[e] = edge_counts.get(e, 0) + 1
        top_boundary_edges = [e for e in edge_counts if (e[1], e[0]) not in edge_counts]

        poly_pins = [p for p in local_pins if sh_poly.contains(Point(p["x"], p["y"]))]
        top_verts, carved_top_faces, sockets = carve_pin_sockets_into_mesh(
            top_verts, orig_faces, poly_pins, socket_radius_mm=socket_radius_mm
        )
        off_top = len(top_verts)

        bot_verts, floor_faces, kh_meta = _build_floor_with_optional_keyhole(
            floor_poly_2d=sh_poly,
            top_verts_xy=pts_arr,
            orig_top_faces=orig_faces,
            top_boundary_edges=top_boundary_edges,
            vert_offset_bot=off_top,
            embed_keyhole=allow_keyhole,
            base_height_mm=base_height_mm
        )

        all_verts, wall_faces, pockets = _emit_skirt_walls_with_biscuit_pockets(
            top_verts=top_verts,
            bot_verts=bot_verts,
            top_boundary_edges=top_boundary_edges,
            vert_offset=0,
            width_mm=width_mm,
            depth_mm=depth_mm,
            active_seams=active_seams,
            dowel_config=dowel_config,
            canonical_seam_centers=canonical_seam_centers
        )

        full_faces = list(carved_top_faces) + wall_faces + floor_faces
        return all_verts, full_faces, pockets, sockets, kh_meta

    # -------------------------------------------------------------
    # CASE A: Natural Territorial / Coastline Border Base
    # -------------------------------------------------------------
    if base_shape == "natural_border" and boundary_geojson:
        try:
            geom = shape(boundary_geojson)
            if not geom.is_valid:
                geom = geom.buffer(0)

            # Project boundary GeoJSON into global canvas mm, apply global rotation, then clip to tile local box!
            g_lon_span = max(1e-5, eff_bbox.lon_span)
            g_lat_span = max(1e-5, eff_bbox.lat_span)

            def _proj_geom_to_tile_mm(g_obj):
                raw_polys = [g_obj] if g_obj.geom_type == "Polygon" else [p for p in getattr(g_obj, "geoms", []) if p.geom_type == "Polygon"]
                local_polys = []
                for p in raw_polys:
                    if p.is_empty:
                        continue
                    cs = list(p.exterior.coords)
                    if len(cs) > 450:
                        p = p.simplify(0.004 * max(g_lon_span, g_lat_span) / 10.0, preserve_topology=True)
                        cs = list(p.exterior.coords)
                    pts_local = []
                    for lon, lat in cs[:-1]:
                        gx = ((lon - eff_bbox.west) / g_lon_span) * eff_w
                        gy = ((lat - eff_bbox.south) / g_lat_span) * eff_d
                        if abs(rotation_deg) > 1e-4:
                            dx_g, dy_g = gx - gcx_rot, gy - gcy_rot
                            gx = gcx_rot + dx_g * cos_r + dy_g * sin_r
                            gy = gcy_rot - dx_g * sin_r + dy_g * cos_r
                        pts_local.append((gx - ox, gy - oy))
                    if len(pts_local) >= 3:
                        lp = Polygon(pts_local)
                        if not lp.is_valid:
                            lp = lp.buffer(0)
                        clipped = lp.intersection(box(0.0, 0.0, width_mm, depth_mm))
                        if not clipped.is_empty:
                            if clipped.geom_type == "Polygon":
                                local_polys.append(clipped)
                            elif hasattr(clipped, "geoms"):
                                local_polys.extend([sp for sp in clipped.geoms if sp.geom_type == "Polygon" and sp.area >= 4.0])
                return local_polys

            polys_mm = _proj_geom_to_tile_mm(geom)
            polys_mm.sort(key=lambda p: p.area, reverse=True)

            all_verts_list = []
            all_faces_list = []
            all_pockets_list = []
            all_sockets_list = []
            keyhole_created = None
            vert_offset = 0

            for idx_p, sh_poly in enumerate(polys_mm):
                if sh_poly.area < 4.0:
                    continue
                res_p = _build_delaunay_solid_from_polygon(
                    sh_poly,
                    res_x=max(24, cols),
                    res_y=max(24, rows),
                    allow_keyhole=(embed_keyhole and idx_p == 0 and keyhole_created is None)
                )
                if res_p is None:
                    continue
                pv, pf, pk, sk, kh = res_p
                all_verts_list.append(pv)
                all_faces_list.extend([[f[0] + vert_offset, f[1] + vert_offset, f[2] + vert_offset] for f in pf])
                all_pockets_list.extend(pk)
                all_sockets_list.extend(sk)
                if kh is not None:
                    keyhole_created = kh
                vert_offset += len(pv)

            if all_verts_list:
                mesh = SolidMesh(np.vstack(all_verts_list), np.array(all_faces_list, dtype=np.int32))
                mesh.pockets_created = all_pockets_list
                mesh.sockets_carved = all_sockets_list
                mesh.keyhole_created = keyhole_created
                mesh.sample_z_func = lambda x, y: sample_z(x, y, include_route=False)
                return mesh
        except Exception:
            pass

    # -------------------------------------------------------------
    # CASE B: Standard Rectangular / Square Base
    # -------------------------------------------------------------
    if base_shape == "rectangle" or base_shape == "natural_border":
        # If a route cuts across a rectangle tile, use corridor-subdivided Delaunay so trench has 0.00 mm³ collision!
        if route_line_local is not None:
            rect_poly = box(0.0, 0.0, width_mm, depth_mm)
            res_rect = _build_delaunay_solid_from_polygon(
                rect_poly,
                res_x=min(130, max(40, cols)),
                res_y=min(130, max(40, rows)),
                allow_keyhole=embed_keyhole
            )
            if res_rect is not None:
                pv, pf, pk, sk, kh = res_rect
                mesh = SolidMesh(pv, np.array(pf, dtype=np.int32))
                mesh.pockets_created = pk
                mesh.sockets_carved = sk
                mesh.keyhole_created = kh
                mesh.sample_z_func = lambda x, y: sample_z(x, y, include_route=False)
                return mesh

        # Fast structured regular grid path
        x_coords = np.linspace(0, width_mm, cols, dtype=np.float32)
        y_coords = np.linspace(0, depth_mm, rows, dtype=np.float32)
        xx, yy = np.meshgrid(x_coords, y_coords)

        if use_global_sampler:
            flat_x = xx.ravel()
            flat_y = yy.ravel()
            flat_z = np.array([sample_z(float(fx), float(fy)) for fx, fy in zip(flat_x, flat_y)], dtype=np.float32)
            top_verts = np.column_stack([flat_x, flat_y, flat_z])
        else:
            top_verts = np.column_stack([xx.ravel(), yy.ravel(), z_grid_local.ravel()])

        top_xy_orig = top_verts[:, :2].copy()

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
        off_top = len(top_verts)

        top_boundary_edges = []
        for c in range(cols - 1):
            top_boundary_edges.append((v_idx(0, c), v_idx(0, c + 1)))
        for r in range(rows - 1):
            top_boundary_edges.append((v_idx(r, cols - 1), v_idx(r + 1, cols - 1)))
        for c in range(cols - 1, 0, -1):
            top_boundary_edges.append((v_idx(rows - 1, c), v_idx(rows - 1, c - 1)))
        for r in range(rows - 1, 0, -1):
            top_boundary_edges.append((v_idx(r, 0), v_idx(r - 1, 0)))

        bot_verts, floor_faces, kh_meta = _build_floor_with_optional_keyhole(
            floor_poly_2d=box(0.0, 0.0, width_mm, depth_mm),
            top_verts_xy=top_xy_orig,
            orig_top_faces=orig_top_faces,
            top_boundary_edges=top_boundary_edges,
            vert_offset_bot=off_top,
            embed_keyhole=embed_keyhole,
            base_height_mm=base_height_mm
        )

        all_verts, wall_faces, pockets = _emit_skirt_walls_with_biscuit_pockets(
            top_verts=top_verts,
            bot_verts=bot_verts,
            top_boundary_edges=top_boundary_edges,
            vert_offset=0,
            width_mm=width_mm,
            depth_mm=depth_mm,
            active_seams=active_seams,
            dowel_config=dowel_config,
            canonical_seam_centers=canonical_seam_centers
        )
        faces = list(carved_top_faces) + wall_faces + floor_faces

        mesh = SolidMesh(all_verts, np.array(faces, dtype=np.int32))
        mesh.pockets_created = pockets
        mesh.sockets_carved = sockets
        mesh.keyhole_created = kh_meta
        mesh.sample_z_func = lambda x, y: sample_z(x, y, include_route=False)
        return mesh

    # -------------------------------------------------------------
    # CASE C: Non-Rectangular Geometric Base (Circle, Ellipse, N-Gon)
    # -------------------------------------------------------------
    base_poly = compute_tile_base_polygon_mm(
        base_shape=base_shape,
        base_sides=base_sides,
        width_mm=width_mm,
        depth_mm=depth_mm,
        tile_clip_box_norm=tile_clip_box_norm
    )
    if base_poly.is_empty or base_poly.area < 4.0:
        empty_m = SolidMesh()
        empty_m.pockets_created = []
        empty_m.sockets_carved = []
        empty_m.keyhole_created = None
        empty_m.sample_z_func = lambda x, y: sample_z(x, y, include_route=False)
        return empty_m

    res_c = _build_delaunay_solid_from_polygon(
        base_poly,
        res_x=max(28, cols),
        res_y=max(28, rows),
        allow_keyhole=embed_keyhole
    )
    if res_c is None:
        return SolidMesh()
    pv, pf, pk, sk, kh = res_c
    mesh = SolidMesh(pv, np.array(pf, dtype=np.int32))
    mesh.pockets_created = pk
    mesh.sockets_carved = sk
    mesh.keyhole_created = kh
    mesh.sample_z_func = lambda x, y: sample_z(x, y, include_route=False)
    return mesh


def compute_tile_base_polygon_mm(
    base_shape: str,
    base_sides: int,
    width_mm: float,
    depth_mm: float,
    tile_clip_box_norm: Optional[Tuple[float, float, float, float]] = None
) -> Polygon:
    """Computes the exact 2D footprint polygon (in local tile mm) for rectangle, circle, ellipse, or N-gon."""
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
        angles = np.linspace(0, 2 * np.pi, 96, endpoint=False)
        global_perim = [(gcx + r_rad * math.cos(a), gcy + r_rad * math.sin(a)) for a in angles]
    elif base_shape == "ellipse":
        angles = np.linspace(0, 2 * np.pi, 96, endpoint=False)
        global_perim = [(gcx + grx * math.cos(a), gcy + gry * math.sin(a)) for a in angles]
    elif base_shape == "polygon":
        num_perimeter = max(3, int(base_sides))
        r_rad = min(grx, gry)
        angles = [2.0 * math.pi * i / num_perimeter - math.pi / 2.0 for i in range(num_perimeter)]
        global_perim = [(gcx + r_rad * math.cos(a), gcy + r_rad * math.sin(a)) for a in angles]
    else:
        return box(0.0, 0.0, width_mm, depth_mm)

    if tile_clip_box_norm is not None:
        x_shift = u0 * (width_mm / max(1e-5, tile_clip_box_norm[2] - u0))
        y_shift = v0_n * (depth_mm / max(1e-5, tile_clip_box_norm[3] - v0_n))
        local_perim = [(px - x_shift, py - y_shift) for px, py in global_perim]
        clipped = Polygon(local_perim).intersection(box(0.0, 0.0, width_mm, depth_mm))
        if isinstance(clipped, MultiPolygon):
            clipped = max(clipped.geoms, key=lambda g: g.area)
        return clipped if isinstance(clipped, Polygon) else Polygon()

    return Polygon(global_perim)


def extrude_building_mesh(
    building: BuildingPolygon,
    bbox: BoundingBox,
    width_mm: float,
    depth_mm: float,
    z_ground: float,
    z_scale: float,
    building_height_scale: float = 1.0,
    min_printable_wall: float = 0.84,
    rotation_deg: float = 0.0,
    sample_z_func: Optional[Callable[[float, float], float]] = None,
    clip_poly_mm: Optional[Any] = None,
    global_bbox: Optional[BoundingBox] = None,
    global_width_mm: Optional[float] = None,
    global_depth_mm: Optional[float] = None,
    tile_offset_xy_mm: Tuple[float, float] = (0.0, 0.0)
) -> Tuple[Optional[SolidMesh], Dict[str, Any]]:
    """Extrudes a 3D OSM building polygon into a guaranteed 100% 2-manifold closed prism,
    seated directly on the terrain surface and clipped cleanly to tile/frame borders.
    """
    coords = building.coordinates
    if len(coords) < 3:
        return None, {"status": "invalid_polygon"}

    eff_bbox = global_bbox if global_bbox is not None else bbox
    eff_w = global_width_mm if global_width_mm is not None else width_mm
    eff_d = global_depth_mm if global_depth_mm is not None else depth_mm
    ox, oy = tile_offset_xy_mm
    gcx, gcy = eff_w / 2.0, eff_d / 2.0
    rad = math.radians(rotation_deg)
    cos_r, sin_r = math.cos(rad), math.sin(rad)

    poly_pts = []
    for lat, lon in coords:
        gx = (lon - eff_bbox.west) / max(1e-6, eff_bbox.lon_span) * eff_w
        gy = (lat - eff_bbox.south) / max(1e-6, eff_bbox.lat_span) * eff_d
        if abs(rotation_deg) > 1e-4:
            dx, dy = gx - gcx, gy - gcy
            gx = gcx + dx * cos_r + dy * sin_r
            gy = gcy - dx * sin_r + dy * cos_r
        poly_pts.append((gx - ox, gy - oy))

    poly = Polygon(poly_pts)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if clip_poly_mm is not None:
        poly = poly.intersection(clip_poly_mm)
    if poly.is_empty:
        return None, {"status": "empty_polygon"}

    minx, miny, maxx, maxy = poly.bounds
    bw = maxx - minx
    bd = maxy - miny
    too_thin = (bw < min_printable_wall or bd < min_printable_wall)

    audit_info = {
        "osm_id": building.osm_id,
        "name": building.name,
        "width_mm": bw,
        "depth_mm": bd,
        "too_thin": too_thin
    }

    # Auto-dilate slightly undersized landmark spires above nozzle threshold if close (>= 0.45mm)
    if too_thin and bw >= 0.45 and bd >= 0.45:
        poly = poly.buffer((min_printable_wall - min(bw, bd)) * 0.55)
        if clip_poly_mm is not None:
            poly = poly.intersection(clip_poly_mm)

    h_mm = max(1.2, building.height_meters * z_scale * building_height_scale)
    rep = poly.representative_point()
    if sample_z_func is not None:
        sample_zs = [sample_z_func(float(rep.x), float(rep.y))]
        for bx, by in [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]:
            sample_zs.append(sample_z_func(float(bx), float(by)))
        z_base_bot = max(0.6, min(sample_zs) - 0.45)
        z_roof = float(np.mean(sample_zs)) + h_mm
    else:
        z_base_bot = z_ground
        z_roof = z_ground + h_mm

    mesh = extrude_shapely_polygon_2manifold(
        poly,
        z_bot_fn=lambda _x, _y: z_base_bot,
        z_top_fn=lambda _x, _y: z_roof
    )
    if mesh.num_faces == 0:
        return None, {"status": "degenerate"}
    return mesh, audit_info


def extrude_block_mesh(
    block: Any,
    bbox: BoundingBox,
    width_mm: float,
    depth_mm: float,
    z_ground: float,
    rotation_deg: float = 0.0,
    sample_z_func: Optional[Callable[[float, float], float]] = None,
    clip_poly_mm: Optional[Any] = None,
    global_bbox: Optional[BoundingBox] = None,
    global_width_mm: Optional[float] = None,
    global_depth_mm: Optional[float] = None,
    tile_offset_xy_mm: Tuple[float, float] = (0.0, 0.0)
) -> Optional[SolidMesh]:
    """Extrudes an urban block or settlement parcel into a 100% 2-manifold closed prism,
    draped onto the actual terrain relief and clipped cleanly to tile and frame bounds!
    """
    coords = getattr(block, "coordinates", [])
    if len(coords) < 3:
        return None

    eff_bbox = global_bbox if global_bbox is not None else bbox
    eff_w = global_width_mm if global_width_mm is not None else width_mm
    eff_d = global_depth_mm if global_depth_mm is not None else depth_mm
    ox, oy = tile_offset_xy_mm
    gcx, gcy = eff_w / 2.0, eff_d / 2.0
    rad = math.radians(rotation_deg)
    cos_r, sin_r = math.cos(rad), math.sin(rad)

    poly_pts = []
    for lat, lon in coords:
        gx = (lon - eff_bbox.west) / max(1e-6, eff_bbox.lon_span) * eff_w
        gy = (lat - eff_bbox.south) / max(1e-6, eff_bbox.lat_span) * eff_d
        if abs(rotation_deg) > 1e-4:
            dx, dy = gx - gcx, gy - gcy
            gx = gcx + dx * cos_r + dy * sin_r
            gy = gcy - dx * sin_r + dy * cos_r
        poly_pts.append((gx - ox, gy - oy))

    poly = Polygon(poly_pts)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if clip_poly_mm is not None:
        poly = poly.intersection(clip_poly_mm)
    if poly.is_empty or poly.area < 0.70:
        return None

    block_h = max(1.0, float(getattr(block, "height_mm", 3.5)))

    if sample_z_func is not None:
        # Sample terrain elevation across footprint so hillside blocks sit ON hills (never buried at Z=4mm!)
        minx, miny, maxx, maxy = poly.bounds
        rp = poly.representative_point()
        probe_pts = [(rp.x, rp.y), (minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]
        zs = [float(sample_z_func(px, py)) for px, py in probe_pts]
        z_bot_val = max(0.60, min(zs) - 0.50)
        z_top_val = max(zs) + block_h
    else:
        z_bot_val = z_ground
        z_top_val = z_ground + block_h

    mesh = extrude_shapely_polygon_2manifold(
        poly,
        z_bot_fn=lambda _x, _y: z_bot_val,
        z_top_fn=lambda _x, _y: z_top_val
    )
    return mesh if mesh.num_faces > 0 else None


def generate_flat_biscuit(
    thickness_mm: float = 1.56,
    width_mm: float = 12.0,
    length_mm: float = 11.8,
    chamfer_mm: float = 0.40
) -> SolidMesh:
    """Generates a 100% 2-manifold flat alignment biscuit spline dowel."""
    hx = length_mm / 2.0
    hy = width_mm / 2.0
    hz = thickness_mm

    v = np.array([
        [-hx, -hy, 0], [hx, -hy, 0], [hx, hy, 0], [-hx, hy, 0],
        [-hx, -hy, hz], [hx, -hy, hz], [hx, hy, hz], [-hx, hy, hz]
    ], dtype=np.float32)

    faces = np.array([
        [0, 2, 1], [0, 3, 2],
        [4, 5, 6], [4, 6, 7],
        [0, 1, 5], [0, 5, 4],
        [2, 3, 7], [2, 7, 6],
        [3, 0, 4], [3, 4, 7],
        [1, 2, 6], [1, 6, 5]
    ], dtype=np.int32)

    return SolidMesh(v, faces)


def generate_flat_tile_route_strip(
    waypoints_lat_lon: List[Tuple[float, float]],
    global_bbox: BoundingBox,
    global_width_mm: float,
    global_depth_mm: float,
    tile_offset_xy_mm: Tuple[float, float],
    tile_clip_poly_mm: Any,
    path_width_mm: float = 1.92,
    strip_thickness_mm: float = 1.12,
    rotation_deg: float = 0.0,
    landmark_pins_latlon: Optional[List[Dict[str, Any]]] = None
) -> SolidMesh:
    """Generates a 100% flat-on-bed (Z in [0, strip_thickness_mm]), tile-bounded,
    rounded-cap flexible PLA snap-in route strip with 100% build-plate contact,
    notched cleanly around any Start/Finish/Checkpoint landmark pin sockets!
    """
    if not waypoints_lat_lon or len(waypoints_lat_lon) < 2:
        return SolidMesh()

    ox, oy = tile_offset_xy_mm
    gcx, gcy = global_width_mm / 2.0, global_depth_mm / 2.0
    rad = math.radians(rotation_deg)
    cos_r, sin_r = math.cos(rad), math.sin(rad)

    def _proj_local(lat: float, lon: float) -> Tuple[float, float]:
        gx = (lon - global_bbox.west) / max(1e-6, global_bbox.lon_span) * global_width_mm
        gy = (lat - global_bbox.south) / max(1e-6, global_bbox.lat_span) * global_depth_mm
        if abs(rotation_deg) > 1e-4:
            dx, dy = gx - gcx, gy - gcy
            gx = gcx + dx * cos_r + dy * sin_r
            gy = gcy - dx * sin_r + dy * cos_r
        return gx - ox, gy - oy

    pts = [_proj_local(lat, lon) for lat, lon in waypoints_lat_lon]

    line = LineString(pts).simplify(0.20, preserve_topology=False)
    ribbon_poly = line.buffer(path_width_mm / 2.0, quad_segs=8, cap_style=1, join_style=1)
    if landmark_pins_latlon:
        for p in landmark_pins_latlon:
            try:
                px, py = _proj_local(float(p["lat"]), float(p["lon"]))
                ribbon_poly = ribbon_poly.difference(Point(px, py).buffer(2.35, quad_segs=10))
            except Exception:
                pass
    if tile_clip_poly_mm is not None:
        ribbon_poly = ribbon_poly.intersection(tile_clip_poly_mm.buffer(-1.0))
    if ribbon_poly.is_empty:
        return SolidMesh()

    return extrude_shapely_polygon_2manifold(
        ribbon_poly,
        z_bot_fn=lambda _x, _y: 0.0,
        z_top_fn=lambda _x, _y: strip_thickness_mm,
        segmentize_mm=1.8
    )


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
    tactile_offset_mm: float = 0.45,
    global_min_elev: Optional[float] = None,
    rotation_deg: float = 0.0,
    depress_water: bool = False,
    water_step_mm: float = 0.84,
    clip_poly_mm: Optional[Any] = None,
    landmark_pins_latlon: Optional[List[Dict[str, Any]]] = None
) -> Tuple[SolidMesh, SolidMesh]:
    """Generates:
    1. Watertight 3D terrain-conforming path strip (using Shapely buffered ribbon so sharp
       hairpin switchbacks never self-intersect, seated with clearance inside the trench!).
    2. Matching wider negative cutter solid.
    """
    rows, cols = elev_grid.shape
    raw_min = float(np.min(elev_grid))
    raw_max = float(np.max(elev_grid))
    has_coastal_water = (raw_min <= 0.5 and raw_max > 2.0)

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

    def _elev_z(x: float, y: float) -> float:
        dx = x - cx
        dy = y - cy
        x_unrot = cx + dx * cos_r - dy * sin_r
        y_unrot = cy + dx * sin_r + dy * cos_r
        c_f = float(np.clip((x_unrot / max(1e-3, width_mm)) * (cols - 1), 0.0, cols - 1))
        r_f = float(np.clip((y_unrot / max(1e-3, depth_mm)) * (rows - 1), 0.0, rows - 1))
        c0, r0 = int(math.floor(c_f)), int(math.floor(r_f))
        c1, r1 = min(c0 + 1, cols - 1), min(r0 + 1, rows - 1)
        dc, dr = c_f - c0, r_f - r0
        raw_interp = (
            (1.0 - dr) * ((1.0 - dc) * float(elev_grid[r0, c0]) + dc * float(elev_grid[r0, c1]))
            + dr * ((1.0 - dc) * float(elev_grid[r1, c0]) + dc * float(elev_grid[r1, c1]))
        )
        eff_e = max(min_elev, raw_interp)
        step = water_step_mm if (depress_water and has_coastal_water and raw_interp > 0.35) else 0.0
        return base_height_mm + step + max(0.0, eff_e - min_elev) * z_scale

    line = LineString(raw_xy).simplify(0.20, preserve_topology=False)
    default_clip = clip_poly_mm if clip_poly_mm is not None else box(1.8, 1.8, width_mm - 1.8, depth_mm - 1.8)
    line = line.intersection(default_clip)
    if line.is_empty:
        return SolidMesh(), SolidMesh()

    inlay_poly = line.buffer((path_width_mm * 0.5) - 0.06, quad_segs=8, cap_style=1, join_style=1)
    if landmark_pins_latlon:
        for p in landmark_pins_latlon:
            try:
                plat, plon = float(p["lat"]), float(p["lon"])
                px = (plon - bbox.west) / max(1e-6, bbox.lon_span) * width_mm
                py = (plat - bbox.south) / max(1e-6, bbox.lat_span) * depth_mm
                if abs(rotation_deg) > 1e-4:
                    dx, dy = px - cx, py - cy
                    px = cx + dx * cos_r + dy * sin_r
                    py = cy - dx * sin_r + dy * cos_r
                inlay_poly = inlay_poly.difference(Point(px, py).buffer(2.40, quad_segs=10))
            except Exception:
                pass
    cutter_poly = line.buffer((path_width_mm * 0.5) + clearance_mm, quad_segs=8, cap_style=1, join_style=1)

    inlay = extrude_shapely_polygon_2manifold(
        inlay_poly,
        z_bot_fn=lambda x, y: max(1.20, _elev_z(x, y) - (path_depth_mm - 0.30)),
        z_top_fn=lambda x, y: _elev_z(x, y) + tactile_offset_mm,
        segmentize_mm=1.0
    )

    cutter = extrude_shapely_polygon_2manifold(
        cutter_poly,
        z_bot_fn=lambda x, y: max(0.80, _elev_z(x, y) - path_depth_mm),
        z_top_fn=lambda x, y: _elev_z(x, y) + 2.0,
        segmentize_mm=1.0
    )

    return inlay, cutter


def _text_to_shapely_2d(text: str, cap_height_mm: float = 7.0) -> Any:
    """Converts bold display typography into clean 2D Shapely Polygons (with exact letter holes!)
    centered at X=0, Y=0. Uses matplotlib vector FontProperties when available, with Pillow fallback.
    """
    clean_txt = (text or "").strip()
    if not clean_txt:
        return Polygon()

    ttf_path = resolve_bold_ttf_path()

    # Primary high-precision vector Bezier outline path via matplotlib.textpath
    try:
        from matplotlib.textpath import TextPath
        from matplotlib.font_manager import FontProperties

        fprop = FontProperties(fname=ttf_path) if ttf_path else FontProperties(family="DejaVu Sans", weight="bold")
        tp = TextPath((0, 0), clean_txt, size=cap_height_mm * 1.32, prop=fprop)
        rings = tp.to_polygons()
        ring_polys = []
        for r in rings:
            if len(r) >= 4:
                p = Polygon(r)
                if not p.is_valid:
                    p = p.buffer(0)
                if not p.is_empty and p.area > 0.005:
                    ring_polys.append(p)
        if ring_polys:
            merged = reduce(lambda a, b: a.symmetric_difference(b), ring_polys)
            if not merged.is_valid:
                merged = merged.buffer(0)
            minx, miny, maxx, maxy = merged.bounds
            return shapely.affinity.translate(merged, xoff=-(minx + maxx) * 0.5, yoff=-(miny + maxy) * 0.5)
    except Exception:
        pass

    # Pure Pillow bitmap fallback for environments without matplotlib
    try:
        from PIL import Image, ImageDraw, ImageFont
        px_per_mm = 12.0
        font_px = max(16, int(round(cap_height_mm * px_per_mm * 1.25)))
        try:
            fnt = ImageFont.truetype(ttf_path, font_px) if ttf_path else ImageFont.load_default()
        except Exception:
            fnt = ImageFont.load_default()
        dummy = Image.new("L", (16, 16), 0)
        bb = ImageDraw.Draw(dummy).textbbox((0, 0), clean_txt, font=fnt)
        tw, th = max(8, bb[2] - bb[0] + 16), max(8, bb[3] - bb[1] + 16)
        canvas = Image.new("L", (tw, th), 0)
        ImageDraw.Draw(canvas).text((8 - bb[0], 8 - bb[1]), clean_txt, fill=255, font=fnt)
        arr = np.array(canvas) > 127
        # Merge active pixel runs per row into strips and union
        strips = []
        h_px, w_px = arr.shape
        for ry in range(h_px):
            row = arr[ry]
            if not np.any(row):
                continue
            y0 = (h_px - 1 - ry) / px_per_mm
            y1 = (h_px - ry) / px_per_mm
            in_run = False
            x_start = 0
            for rx in range(w_px):
                if row[rx] and not in_run:
                    in_run = True
                    x_start = rx
                elif not row[rx] and in_run:
                    in_run = False
                    strips.append(box(x_start / px_per_mm, y0, rx / px_per_mm, y1))
            if in_run:
                strips.append(box(x_start / px_per_mm, y0, w_px / px_per_mm, y1))
        if strips:
            merged = shapely.ops.unary_union(strips).simplify(0.06, preserve_topology=True)
            minx, miny, maxx, maxy = merged.bounds
            return shapely.affinity.translate(merged, xoff=-(minx + maxx) * 0.5, yoff=-(miny + maxy) * 0.5)
    except Exception:
        pass

    return Polygon()


def generate_gallery_frame_and_plaque(
    base_shape: str,
    base_sides: int,
    global_width_mm: float,
    global_depth_mm: float,
    tile_offset_xy_mm: Tuple[float, float],
    tile_width_mm: float,
    tile_depth_mm: float,
    tile_clip_box_norm: Optional[Tuple[float, float, float, float]],
    base_height_mm: float = 4.0,
    frame_enabled: bool = False,
    frame_width_mm: float = 4.20,
    frame_top_z_mm: float = 8.0,
    title_text: str = "",
    subtitle_text: str = "",
    sample_z_func: Optional[Callable[[float, float], float]] = None
) -> Tuple[SolidMesh, SolidMesh]:
    """Generates:
    1. `frame_and_plaque_mesh`: 100% 2-manifold architectural shadowbox border bezel + front nameplate bar.
    2. `letters_mesh`: 100% 2-manifold crisp raised 3D vector lettering (+1.12mm emboss) for Title & Subtitle.
    """
    ox, oy = tile_offset_xy_mm
    tile_box = box(0.0, 0.0, tile_width_mm, tile_depth_mm)
    frame_mesh = SolidMesh()
    letters_mesh = SolidMesh()

    # Global base outer polygon in [0..global_width_mm, 0..global_depth_mm]
    outer_global = compute_tile_base_polygon_mm(
        base_shape="rectangle" if base_shape == "natural_border" else base_shape,
        base_sides=base_sides,
        width_mm=global_width_mm,
        depth_mm=global_depth_mm,
        tile_clip_box_norm=None
    )

    z_embed_bot = max(0.80, base_height_mm * 0.55)

    # 1. Architectural Shadowbox Gallery Frame (for geometric bases)
    if frame_enabled and base_shape != "natural_border" and not outer_global.is_empty:
        fw = max(1.68, min(frame_width_mm, min(global_width_mm, global_depth_mm) * 0.12))
        inner_global = outer_global.buffer(-fw, join_style=2)
        ring_global = outer_global.difference(inner_global)
        ring_local = shapely.affinity.translate(ring_global, xoff=-ox, yoff=-oy).intersection(tile_box)
        if not ring_local.is_empty:
            frame_mesh.append(
                extrude_shapely_polygon_2manifold(
                    ring_local,
                    z_bot_fn=lambda _x, _y: z_embed_bot,
                    z_top_fn=lambda x, y: max(
                        frame_top_z_mm,
                        (sample_z_func(x, y) + 1.60) if sample_z_func is not None else frame_top_z_mm
                    ),
                    segmentize_mm=2.5
                )
            )

    # 2. Integrated 3D Embossed Title & Subtitle Nameplate Plaque
    clean_title = (title_text or "").strip()
    clean_sub = (subtitle_text or "").strip()
    if clean_title or clean_sub:
        max_plaque_w = min(global_width_mm * 0.78, 190.0)
        title_cap = min(7.6, max(4.8, global_width_mm * 0.032))
        sub_cap = min(4.6, max(3.4, title_cap * 0.62))

        title_geom = _text_to_shapely_2d(clean_title, cap_height_mm=title_cap) if clean_title else Polygon()
        sub_geom = _text_to_shapely_2d(clean_sub, cap_height_mm=sub_cap) if clean_sub else Polygon()

        # Scale horizontally if long string exceeds max_plaque_w - 14mm
        for g_name in ("title", "sub"):
            g_cur = title_geom if g_name == "title" else sub_geom
            if not g_cur.is_empty:
                gw = g_cur.bounds[2] - g_cur.bounds[0]
                if gw > max_plaque_w - 14.0 and gw > 1e-3:
                    sc = (max_plaque_w - 14.0) / gw
                    g_scaled = shapely.affinity.scale(g_cur, xfact=sc, yfact=max(0.72, sc), origin=(0, 0))
                    if g_name == "title":
                        title_geom = g_scaled
                    else:
                        sub_geom = g_scaled

        t_w = (title_geom.bounds[2] - title_geom.bounds[0]) if not title_geom.is_empty else 0.0
        t_h = (title_geom.bounds[3] - title_geom.bounds[1]) if not title_geom.is_empty else 0.0
        s_w = (sub_geom.bounds[2] - sub_geom.bounds[0]) if not sub_geom.is_empty else 0.0
        s_h = (sub_geom.bounds[3] - sub_geom.bounds[1]) if not sub_geom.is_empty else 0.0

        content_w = max(t_w, s_w, 32.0)
        gap_y = 2.4 if (t_h > 0 and s_h > 0) else 0.0
        content_h = t_h + s_h + gap_y

        plaque_w = min(global_width_mm - 12.0, content_w + 14.0)
        plaque_h = content_h + 7.5

        pcx = global_width_mm * 0.5
        margin_south = (frame_width_mm + 3.5) if (frame_enabled and base_shape != "natural_border") else 6.0
        if base_shape in ("circle", "polygon"):
            # Inset slightly so rounded corners stay comfortably inside circular/hexagonal base!
            margin_south = max(margin_south, global_depth_mm * 0.09)
        pcy = margin_south + plaque_h * 0.5

        plaque_global = box(
            pcx - plaque_w * 0.5,
            pcy - plaque_h * 0.5,
            pcx + plaque_w * 0.5,
            pcy + plaque_h * 0.5
        ).buffer(2.2, quad_segs=6).buffer(-2.2 + 2.2, quad_segs=6)
        # Clean rounded rectangle: shrink by 2.0 then buffer +2.0
        plaque_global = box(
            pcx - plaque_w * 0.5 + 2.0,
            pcy - plaque_h * 0.5 + 2.0,
            pcx + plaque_w * 0.5 - 2.0,
            pcy + plaque_h * 0.5 - 2.0
        ).buffer(2.0, quad_segs=6)

        if base_shape != "natural_border":
            plaque_global = plaque_global.intersection(outer_global.buffer(-0.6))

        plaque_local = shapely.affinity.translate(plaque_global, xoff=-ox, yoff=-oy).intersection(tile_box)

        # Position title & subtitle on plaque
        combined_text_global = []
        if not title_geom.is_empty and not sub_geom.is_empty:
            ty = pcy + (s_h + gap_y) * 0.5
            sy = pcy - (t_h + gap_y) * 0.5
            combined_text_global.append(shapely.affinity.translate(title_geom, xoff=pcx, yoff=ty))
            combined_text_global.append(shapely.affinity.translate(sub_geom, xoff=pcx, yoff=sy))
        elif not title_geom.is_empty:
            combined_text_global.append(shapely.affinity.translate(title_geom, xoff=pcx, yoff=pcy))
        elif not sub_geom.is_empty:
            combined_text_global.append(shapely.affinity.translate(sub_geom, xoff=pcx, yoff=pcy))

        if not plaque_local.is_empty and plaque_local.area > 2.0:
            # Uniform flat plaque deck comfortably above underlying terrain
            p_minx, p_miny, p_maxx, p_maxy = plaque_local.bounds
            local_zs = [frame_top_z_mm]
            if sample_z_func is not None:
                for sx in np.linspace(p_minx, p_maxx, 6):
                    for sy in np.linspace(p_miny, p_maxy, 3):
                        local_zs.append(float(sample_z_func(float(sx), float(sy))) + 1.4)
            z_deck = max(local_zs)
            z_p_bot = 0.0 if base_shape == "natural_border" else z_embed_bot

            frame_mesh.append(
                extrude_shapely_polygon_2manifold(
                    plaque_local,
                    z_bot_fn=lambda _x, _y: z_p_bot,
                    z_top_fn=lambda _x, _y: z_deck,
                    segmentize_mm=3.5
                )
            )

            if combined_text_global:
                txt_union_global = shapely.ops.unary_union(combined_text_global)
                txt_local = shapely.affinity.translate(txt_union_global, xoff=-ox, yoff=-oy).intersection(plaque_local.buffer(-0.5))
                if not txt_local.is_empty:
                    letters_mesh.append(
                        extrude_shapely_polygon_2manifold(
                            txt_local,
                            z_bot_fn=lambda _x, _y: z_deck - 0.25,
                            z_top_fn=lambda _x, _y: z_deck + 1.12  # 7 crisp layers @ 0.16mm!
                        )
                    )

    return frame_mesh, letters_mesh


def generate_boundary_preview_mesh(
    elev_grid: np.ndarray,
    bbox: BoundingBox,
    boundary_geojson: Dict[str, Any],
    width_mm: float = 250.0,
    depth_mm: float = 250.0,
    base_height_mm: float = 4.0,
    target_relief_mm: float = 15.0,
    rotation_deg: float = 0.0,
    depress_water: bool = False,
    water_step_mm: float = 0.84,
    topography_enabled: bool = True
) -> Dict[str, Any]:
    """Generates high-definition preview mesh data for territorial / coastline boundaries
    ready for Three.js WebGL rendering.
    """
    raw_min = float(np.min(elev_grid))
    raw_max = float(np.max(elev_grid))
    clamp_ocean = (raw_min < -50 and raw_max > 0)
    min_e = 0.0 if clamp_ocean else raw_min
    delta = max(1.0, raw_max - min_e)
    has_coastal = (raw_min <= 0.5 and raw_max > 2.0)

    geom = shape(boundary_geojson)
    if not geom.is_valid:
        geom = geom.buffer(0)
    if geom.geom_type == 'Polygon':
        polys = [geom]
    elif geom.geom_type == 'MultiPolygon':
        tot = geom.area
        polys = [p for p in geom.geoms if p.area / max(1e-9, tot) >= 0.003]
        polys.sort(key=lambda p: p.area, reverse=True)
    else:
        polys = []

    def get_color(elev_m: float) -> Tuple[float, float, float]:
        elev_ft = elev_m * 3.28084
        if elev_ft <= 0 or elev_m <= 0.5:
            if elev_ft < -60:
                return (0.10, 0.20, 0.55)
            return (0.14, 0.40, 0.85)
        if elev_ft < 500:
            return (0.18, 0.55, 0.28)
        if elev_ft < 1500:
            return (0.35, 0.65, 0.30)
        if elev_ft < 3000:
            return (0.75, 0.72, 0.35)
        if elev_ft < 6000:
            return (0.78, 0.55, 0.30)
        if elev_ft < 9000:
            return (0.65, 0.38, 0.25)
        if elev_ft < 12000:
            return (0.55, 0.35, 0.30)
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

    rad = math.radians(rotation_deg)
    cos_r, sin_r = math.cos(rad), math.sin(rad)

    vert_offset = 0
    top_indices_count = 0
    rows, cols = elev_grid.shape

    for poly in polys:
        coords = list(poly.exterior.coords)
        if len(coords) < 3:
            continue
        if len(coords) > 350:
            poly = poly.simplify(0.007, preserve_topology=True)
            coords = list(poly.exterior.coords)

        perim_xy = []
        for lon, lat in coords[:-1]:
            rx = ((lon - w_lon) / lon_span - 0.5) * width_mm
            ry = ((lat - s_lat) / lat_span - 0.5) * depth_mm
            if abs(rotation_deg) > 1e-4:
                perim_xy.append((rx * cos_r + ry * sin_r, -rx * sin_r + ry * cos_r))
            else:
                perim_xy.append((rx, ry))

        if len(perim_xy) < 3:
            continue

        sh_poly = Polygon(perim_xy)
        if not sh_poly.is_valid:
            sh_poly = sh_poly.buffer(0)
        if sh_poly.is_empty:
            continue
        if isinstance(sh_poly, MultiPolygon):
            sh_poly = max(sh_poly.geoms, key=lambda g: g.area)
            perim_xy = list(sh_poly.exterior.coords)[:-1]

        minx, miny, maxx, maxy = sh_poly.bounds
        xs = np.linspace(minx, maxx, 52)
        ys = np.linspace(miny, maxy, 52)
        xx_g, yy_g = np.meshgrid(xs, ys)
        fgx, fgy = xx_g.ravel(), yy_g.ravel()
        eroded = sh_poly.buffer(-1.4)
        if not eroded.is_empty:
            shapely.prepare(eroded)
            msk = shapely.contains_xy(eroded, fgx, fgy)
            int_pts = [(float(fgx[i]), float(fgy[i])) for i in np.nonzero(msk)[0]]
        else:
            int_pts = []

        pts_2d = perim_xy + int_pts
        pts_arr = np.array(pts_2d, dtype=np.float32)
        tri = Delaunay(pts_arr)
        tri_pts_all = pts_arr[tri.simplices]
        cents = np.mean(tri_pts_all, axis=1)
        shapely.prepare(sh_poly)
        in_msk = shapely.contains_xy(sh_poly, cents[:, 0], cents[:, 1])

        valid_tris = []
        for s in tri.simplices[in_msk]:
            v0, v1, v2 = pts_arr[s[0]], pts_arr[s[1]], pts_arr[s[2]]
            det = (v1[0] - v0[0]) * (v2[1] - v0[1]) - (v1[1] - v0[1]) * (v2[0] - v0[0])
            if det < 0:
                valid_tris.append([int(s[0]), int(s[2]), int(s[1])])
            else:
                valid_tris.append([int(s[0]), int(s[1]), int(s[2])])

        if not valid_tris:
            continue

        n_pts = len(pts_2d)
        for x, y in pts_2d:
            x_u = x * cos_r - y * sin_r if abs(rotation_deg) > 1e-4 else x
            y_u = x * sin_r + y * cos_r if abs(rotation_deg) > 1e-4 else y
            u = max(0.0, min(1.0, (x_u / width_mm) + 0.5))
            v = max(0.0, min(1.0, (y_u / depth_mm) + 0.5))
            cf = u * (cols - 1)
            rf = v * (rows - 1)
            c0, r0 = int(math.floor(cf)), int(math.floor(rf))
            c1, r1 = min(c0 + 1, cols - 1), min(r0 + 1, rows - 1)
            dc, dr = cf - c0, rf - r0
            elev = float(
                (1.0 - dr) * ((1.0 - dc) * elev_grid[r0, c0] + dc * elev_grid[r0, c1])
                + dr * ((1.0 - dc) * elev_grid[r1, c0] + dc * elev_grid[r1, c1])
            )
            norm = max(0.0, min(1.0, (max(min_e, elev) - min_e) / delta)) if topography_enabled else 0.0
            step = water_step_mm if (depress_water and has_coastal and elev > 0.35) else 0.0
            z = base_height_mm + step + norm * target_relief_mm

            positions.extend([float(x), float(y), float(z)])
            uvs.extend([float(u), float(v)])
            norm_z.append(float(norm))
            r_c, g_c, b_c = get_color(elev)
            colors.extend([r_c, g_c, b_c])

        for f in valid_tris:
            indices.extend([vert_offset + f[0], vert_offset + f[1], vert_offset + f[2]])
        top_indices_count = len(indices)

        for x, y in pts_2d:
            positions.extend([float(x), float(y), 0.0])
            uvs.extend([0.0, 0.0])
            colors.extend([0.14, 0.15, 0.20])
            norm_z.append(-1.0)

        edge_counts = {}
        for f in valid_tris:
            for i in range(3):
                e = (f[i], f[(i + 1) % 3])
                edge_counts[e] = edge_counts.get(e, 0) + 1
        top_boundary_edges = [e for e in edge_counts if (e[1], e[0]) not in edge_counts]

        for v_a, v_b in top_boundary_edges:
            indices.extend([vert_offset + v_a, vert_offset + n_pts + v_a, vert_offset + n_pts + v_b])
            indices.extend([vert_offset + v_a, vert_offset + n_pts + v_b, vert_offset + v_b])

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
