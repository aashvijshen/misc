#!/usr/bin/env python3
"""Shared Maker's Mark / Brand Logo generator for FreeCAD & Blender 3D prints.

Supports additive (embossed relief), subtractive (debossed engraving), and
cartouche (flush raised emblem inside a recessed stadium pocket) insertions on
any standard face ('top', 'bottom', 'front', 'back', 'left', 'right') or any
custom 3D surface plane (origin, normal, up_dir).

Automatically enforces Bambu Lab A1 (0.40 mm nozzle, 0.42 mm line width) minimum
stroke and open-ring island dimensions, computes proper right-handed SO(3)
viewer orientation (zero backwards-mirroring bugs), and adds 45-deg downward
support ramps when placing deeper additive emblems on vertical walls.

Python (FreeCAD) Usage:
    from maker_mark import apply_maker_mark
    part = apply_maker_mark(part, mode="subtractive", face="bottom", width_mm=24.0, depth_mm=0.40)
    part = apply_maker_mark(part, mode="additive", face="top", width_mm=26.0, depth_mm=0.50)
    part = apply_maker_mark(part, mode="cartouche", face="front", width_mm=24.0, depth_mm=0.50)

CLI Usage (for existing .stl / Blender meshes):
    python3 ~/playground/3d/tools/maker_mark.py apply input.stl output.stl \\
        --mode subtractive --face bottom --width 24.0 --depth 0.40
"""

import argparse
import math
import os
import subprocess
import sys
import tempfile

for _fc_dir in ("/usr/lib/freecad/lib", "/usr/lib/freecad-python3/lib"):
    if os.path.isdir(_fc_dir) and _fc_dir not in sys.path:
        sys.path.append(_fc_dir)

import FreeCAD as App
import Mesh
import Part
import numpy as np
from shapely import affinity
from shapely.geometry import LineString, Point
from shapely.ops import unary_union


LOGO_ASPECT_H_OVER_W = 0.3925  # Height / Width ratio of the canonical Maker Logo


# ==============================================================================
# 1. CANONICAL 2D VECTOR GEOMETRY (Nozzle-Safe Parametric Shapely Builder)
# ==============================================================================
def _eval_cubic_bezier(p0, p1, p2, p3, n=36):
    t = np.linspace(0.0, 1.0, n)[:, None]
    p0, p1, p2, p3 = map(np.asarray, (p0, p1, p2, p3))
    pts = (
        ((1.0 - t) ** 3) * p0
        + 3.0 * ((1.0 - t) ** 2) * t * p1
        + 3.0 * (1.0 - t) * (t ** 2) * p2
        + (t ** 3) * p3
    )
    return [tuple(row) for row in pts]


def build_logo_2d(width_mm=24.0, min_stroke_mm=0.92, min_hole_dia_mm=1.35, mirror_x=False):
    """Builds the 2D MultiPolygon of the Maker Logo centered at (0, 0) in XY.

    Args:
        width_mm: Target total logo width in mm.
        min_stroke_mm: Minimum trace/groove width for 0.40mm nozzle reliability.
        min_hole_dia_mm: Minimum open-ring ('o') inner island diameter for Layer 1 adhesion.
        mirror_x: Optional explicit X mirror (not needed when using apply_maker_mark's SO(3) frame).
    """
    w = float(width_mm)
    stroke_n = max(0.0290, float(min_stroke_mm) / w)
    r_trace = 0.5 * stroke_n
    r_ring_in = max(0.0155, (float(min_hole_dia_mm) / w) * 0.5)
    r_ring_out = max(0.0385, r_ring_in + stroke_n * 0.92)

    y_base = -0.005
    p_L = (0.0385, y_base)
    p_R = (1.0 - 0.0385, y_base)
    p_bend = (0.232, y_base)
    p_peak = (0.376, 0.159)
    p_low = (0.608, -0.163)

    dx, dy = p_low[0] - p_peak[0], p_low[1] - p_peak[1]
    t1, t2 = 0.448, 0.622
    c_bar1 = (p_peak[0] + t1 * dx, p_peak[1] + t1 * dy)
    c_bar2 = (p_peak[0] + t2 * dx, p_peak[1] + t2 * dy)

    bdir = (math.cos(math.radians(45.0)), math.sin(math.radians(45.0)))
    half_bar = 0.0575
    bar_shift = -0.005
    b1_a = (c_bar1[0] + (bar_shift - half_bar) * bdir[0], c_bar1[1] + (bar_shift - half_bar) * bdir[1])
    b1_b = (c_bar1[0] + (bar_shift + half_bar) * bdir[0], c_bar1[1] + (bar_shift + half_bar) * bdir[1])
    b2_a = (c_bar2[0] + (bar_shift - half_bar) * bdir[0], c_bar2[1] + (bar_shift - half_bar) * bdir[1])
    b2_b = (c_bar2[0] + (bar_shift + half_bar) * bdir[0], c_bar2[1] + (bar_shift + half_bar) * bdir[1])

    s1 = _eval_cubic_bezier(p_low, (0.662, -0.194), (0.734, -0.166), (0.688, -0.100), n=36)
    s2 = _eval_cubic_bezier((0.688, -0.100), (0.640, -0.031), (0.662, y_base), (0.758, y_base), n=36)
    s_pts = s1 + s2[1:] + [(p_R[0] - r_ring_in * 0.5, y_base)]

    left_chain = [(p_L[0] + r_ring_in * 0.5, y_base), p_bend, p_peak, c_bar1]
    lower_diag = [c_bar2, p_low]

    shapes = [
        LineString(left_chain).buffer(r_trace, cap_style=1, join_style=1, quad_segs=24),
        LineString([b1_a, b1_b]).buffer(r_trace, cap_style=1, join_style=1, quad_segs=24),
        LineString([b2_a, b2_b]).buffer(r_trace, cap_style=1, join_style=1, quad_segs=24),
        LineString(lower_diag).buffer(r_trace, cap_style=1, join_style=1, quad_segs=24),
        LineString(s_pts).buffer(r_trace, cap_style=1, join_style=1, quad_segs=24),
        Point(p_peak).buffer(max(0.0380, r_trace * 1.28), quad_segs=36),
        Point(p_low).buffer(max(0.0325, r_trace * 1.12), quad_segs=36),
        Point(p_L).buffer(r_ring_out, quad_segs=36),
        Point(p_R).buffer(r_ring_out, quad_segs=36),
    ]
    merged = unary_union(shapes)
    holes = unary_union([
        Point(p_L).buffer(r_ring_in, quad_segs=28),
        Point(p_R).buffer(r_ring_in, quad_segs=28),
    ])
    poly_n = merged.difference(holes)
    poly = affinity.translate(poly_n, xoff=-0.5, yoff=0.0)
    sx = -w if mirror_x else w
    return affinity.scale(poly, xfact=sx, yfact=w, origin=(0, 0))


def _iter_polys(geom):
    return list(geom.geoms) if hasattr(geom, "geoms") else [geom]


def _shapely_to_prism_list(geom, z0, height, simplify_tol=0.018):
    """Extrudes each connected polygon of a 2D Shapely geometry into clean OpenCASCADE Solids."""
    solids = []

    def _clean_wire(coords):
        pts = []
        for x, y in coords[:-1]:
            v = App.Vector(float(x), float(y), float(z0))
            if not pts or (v - pts[-1]).Length > 1e-3:
                pts.append(v)
        if len(pts) >= 2 and (pts[0] - pts[-1]).Length <= 1e-3:
            pts.pop()
        pts.append(pts[0])
        return Part.makePolygon(pts)

    for p in _iter_polys(geom):
        if p.is_empty or p.area < 1e-4:
            continue
        ps = p.simplify(simplify_tol, preserve_topology=True)
        face = Part.Face(_clean_wire(list(ps.exterior.coords)))
        for interior in ps.interiors:
            hole_face = Part.Face(_clean_wire(list(interior.coords)))
            face = face.cut(hole_face)
        solids.append(face.extrude(App.Vector(0, 0, float(height))))
    return solids


def _make_stadium_prism(len_u, wid_v, z0, height):
    """Builds an analytical 4-edge stadium prism centered at (0, 0) in local (u, v, w)."""
    r = 0.5 * float(wid_v)
    hu = max(1e-4, 0.5 * float(len_u) - r)
    p1 = App.Vector(-hu, -r, z0)
    p2 = App.Vector(hu, -r, z0)
    p3 = App.Vector(hu, r, z0)
    p4 = App.Vector(-hu, r, z0)
    wire = Part.Wire([
        Part.LineSegment(p1, p2).toShape(),
        Part.Arc(p2, App.Vector(hu + r, 0.0, z0), p3).toShape(),
        Part.LineSegment(p3, p4).toShape(),
        Part.Arc(p4, App.Vector(-hu - r, 0.0, z0), p1).toShape(),
    ])
    return Part.Face(wire).extrude(App.Vector(0, 0, float(height)))


# ==============================================================================
# 2. RIGHT-HANDED SO(3) SURFACE FRAME & PLACEMENT RESOLVER
# ==============================================================================
def resolve_surface_frame(bbox, face="bottom", origin=None, normal=None, up_dir=None, offset_uv=(0.0, 0.0)):
    """Computes an exact right-handed SE(3) matrix (r, u, n, origin) for any target surface.

    When looking AT the surface along -normal with up_dir pointing Up, local +u points
    to the viewer's Right (r = (-n) x u), guaranteeing left-to-right readability on
    every face (top, bottom, front, back, left, right, or custom angled planes) with det=+1.
    """
    cx = 0.5 * (bbox.XMin + bbox.XMax)
    cy = 0.5 * (bbox.YMin + bbox.YMax)
    cz = 0.5 * (bbox.ZMin + bbox.ZMax)

    presets = {
        "top":    ((cx, cy, bbox.ZMax), (0.0,  0.0,  1.0), (0.0, 1.0, 0.0)),
        "bottom": ((cx, cy, bbox.ZMin), (0.0,  0.0, -1.0), (0.0, 1.0, 0.0)),
        "front":  ((cx, bbox.YMin, cz), (0.0, -1.0,  0.0), (0.0, 0.0, 1.0)),
        "back":   ((cx, bbox.YMax, cz), (0.0,  1.0,  0.0), (0.0, 0.0, 1.0)),
        "right":  ((bbox.XMax, cy, cz), (1.0,  0.0,  0.0), (0.0, 0.0, 1.0)),
        "left":   ((bbox.XMin, cy, cz), (-1.0, 0.0,  0.0), (0.0, 0.0, 1.0)),
    }

    if origin is None or normal is None:
        key = str(face).lower()
        if key not in presets:
            raise ValueError(f"Unknown face={face!r}; choose from {list(presets)} or pass origin & normal.")
        p_orig, p_norm, p_up = presets[key]
        origin = p_orig if origin is None else origin
        normal = p_norm if normal is None else normal
        if up_dir is None:
            up_dir = p_up

    n = np.asarray(normal, dtype=float)
    n_len = np.linalg.norm(n)
    if n_len < 1e-9:
        raise ValueError("Surface normal must be non-zero.")
    n = n / n_len

    if up_dir is None:
        up_dir = (0.0, 1.0, 0.0) if abs(n[2]) > 0.92 else (0.0, 0.0, 1.0)
    u = np.asarray(up_dir, dtype=float)
    u = u - np.dot(u, n) * n
    u_len = np.linalg.norm(u)
    if u_len < 1e-9:
        fallback = np.array([0.0, 1.0, 0.0]) if abs(n[1]) < 0.9 else np.array([1.0, 0.0, 0.0])
        u = fallback - np.dot(fallback, n) * n
        u_len = np.linalg.norm(u)
    u = u / u_len

    # Viewer looks along (-n); screen-right is r = (-n) x u, and r x u == +n (det == +1)!
    r = np.cross(-n, u)
    r = r / np.linalg.norm(r)

    du, dv = float(offset_uv[0]), float(offset_uv[1])
    o = np.asarray(origin, dtype=float) + du * r + dv * u

    mat = App.Matrix(
        float(r[0]), float(u[0]), float(n[0]), float(o[0]),
        float(r[1]), float(u[1]), float(n[1]), float(o[1]),
        float(r[2]), float(u[2]), float(n[2]), float(o[2]),
        0.0,         0.0,         0.0,         1.0,
    )
    return mat, o, r, u, n


def _transform_solids(solids, mat):
    out = []
    for s in solids:
        sc = s.copy()
        sc.transformShape(mat)
        out.append(sc)
    return out


# ==============================================================================
# 3. LOCAL TOOL BUILDERS FOR SUBTRACTIVE, ADDITIVE & CARTOUCHE MODES
# ==============================================================================
def build_mark_tools_local(
    mode="subtractive",
    width_mm=24.0,
    depth_mm=0.40,
    normal_z=1.0,
    vertical_draft="auto",
    min_stroke_mm=0.92,
    min_hole_dia_mm=1.35,
):
    """Builds (cut_solids, fuse_solids) in local surface coordinates (u, v, w=0 at surface)."""
    mode = str(mode).lower()
    w = float(width_mm)
    d = float(depth_mm)
    embed = 0.15  # Overlap into parent solid for clean non-coplanar Booleans

    logo_2d = build_logo_2d(
        width_mm=w,
        min_stroke_mm=min_stroke_mm,
        min_hole_dia_mm=min_hole_dia_mm,
        mirror_x=False,
    )

    if mode == "subtractive":
        cut_solids = _shapely_to_prism_list(logo_2d, -d, d + embed)
        return cut_solids, []

    if mode == "additive":
        use_draft = (
            (abs(normal_z) < 0.70 and d >= 0.45)
            if vertical_draft == "auto"
            else bool(vertical_draft)
        )
        if not use_draft:
            fuse_solids = _shapely_to_prism_list(logo_2d, -embed, d + embed)
            return [], fuse_solids

        # Build 45-deg downward (-v) chiseled support slices so vertical walls need 0 supports!
        n_steps = max(2, int(math.ceil(d / 0.18)))
        step_h = d / float(n_steps)
        fuse_solids = []
        for k in range(n_steps):
            w0 = -embed if k == 0 else k * step_h - 0.03
            h_k = (step_h + embed) if k == 0 else (step_h + 0.03)
            drop_v = (n_steps - 1 - k) * step_h
            if drop_v <= 1e-4:
                slice_2d = logo_2d
            else:
                # Sweep downward along -v to form a 45-deg support ramp under overhangs
                swept = [logo_2d]
                n_sub = max(2, int(math.ceil(drop_v / 0.20)))
                for j in range(1, n_sub + 1):
                    swept.append(affinity.translate(logo_2d, xoff=0.0, yoff=-drop_v * (j / float(n_sub))))
                slice_2d = unary_union(swept)
            fuse_solids.extend(_shapely_to_prism_list(slice_2d, w0, h_k))
        return [], fuse_solids

    if mode == "cartouche":
        # Recessed stadium pocket of depth d, with raised logo rising flush back to w = 0.00!
        margin = max(1.60, 0.065 * w)
        stad_u = w + 2.0 * margin
        stad_v = LOGO_ASPECT_H_OVER_W * w + 2.0 * margin
        pocket = _make_stadium_prism(stad_u, stad_v, -d, d + embed)
        fuse_solids = _shapely_to_prism_list(logo_2d, -d - embed, d + embed)
        return [pocket], fuse_solids

    raise ValueError(f"Unknown mode={mode!r}; expected 'subtractive', 'additive', or 'cartouche'.")


# ==============================================================================
# 4. PUBLIC API FOR FREECAD PART.SHAPE
# ==============================================================================
def apply_maker_mark(
    part_shape,
    mode="subtractive",
    face="bottom",
    width_mm=24.0,
    depth_mm=0.40,
    origin=None,
    normal=None,
    up_dir=None,
    offset_uv=(0.0, 0.0),
    vertical_draft="auto",
    min_stroke_mm=0.92,
    min_hole_dia_mm=1.35,
):
    """Applies the Maker's Mark to a FreeCAD Part.Shape and verifies B-Rep validity.

    Args:
        part_shape: Input FreeCAD Part.Shape solid.
        mode: 'subtractive' (deboss), 'additive' (emboss), or 'cartouche' (flush badge in pocket).
        face: Preset ('bottom', 'top', 'front', 'back', 'left', 'right'), ignored if origin & normal set.
        width_mm: Total width of the logo in mm (default: 24.0 mm).
        depth_mm: Engraving depth or relief height in mm (default: 0.40 mm = 2 layers).
        origin: Optional custom (x, y, z) point on the target surface.
        normal: Optional custom outward normal vector (nx, ny, nz).
        up_dir: Optional 'up' direction vector for reading orientation.
        offset_uv: (du, dv) in-plane offset in mm along viewer (right, up).
        vertical_draft: 'auto' (adds 45-deg lower support ramp on vertical walls if depth>=0.45), True, or False.
    """
    bbox = part_shape.BoundBox
    mat, o_vec, _, _, n_vec = resolve_surface_frame(
        bbox, face=face, origin=origin, normal=normal, up_dir=up_dir, offset_uv=offset_uv
    )

    if str(mode).lower() == "additive" and n_vec[2] < -0.95 and abs(o_vec[2] - bbox.ZMin) < 0.08:
        raise ValueError(
            "Refusing mode='additive' on Z=ZMin print-bed face (would lift part off the PEI bed). "
            "Use mode='subtractive' or mode='cartouche' on 'bottom', or place 'additive' on another face."
        )

    cut_local, fuse_local = build_mark_tools_local(
        mode=mode,
        width_mm=width_mm,
        depth_mm=depth_mm,
        normal_z=float(n_vec[2]),
        vertical_draft=vertical_draft,
        min_stroke_mm=min_stroke_mm,
        min_hole_dia_mm=min_hole_dia_mm,
    )

    result = part_shape.copy()
    for c_sol in _transform_solids(cut_local, mat):
        result = result.cut(c_sol)
    for f_sol in _transform_solids(fuse_local, mat):
        result = result.fuse(f_sol)

    if not result.isValid():
        raise RuntimeError(f"apply_maker_mark({mode!r}, face={face!r}) produced an invalid B-Rep shape.")
    return result


# ==============================================================================
# 5. BLENDER / EXISTING STL MESH CLI PIPELINE
# ==============================================================================
def _write_shapes_stl(shapes, path, deflection=0.020):
    mesh = Mesh.Mesh()
    for shp in shapes:
        sub = Mesh.Mesh()
        sub.addFacets(shp.tessellate(deflection))
        mesh.addMesh(sub)
    mesh.write(path)


def apply_maker_mark_to_stl(
    input_stl,
    output_stl,
    mode="subtractive",
    face="bottom",
    width_mm=24.0,
    depth_mm=0.40,
    offset_uv=(0.0, 0.0),
    vertical_draft="auto",
):
    """Applies the Maker's Mark to any existing .stl mesh using Blender's EXACT Boolean solver."""
    in_mesh = Mesh.Mesh(os.path.abspath(input_stl))
    bbox = in_mesh.BoundBox
    mat, o_vec, _, _, n_vec = resolve_surface_frame(bbox, face=face, offset_uv=offset_uv)

    if str(mode).lower() == "additive" and n_vec[2] < -0.95 and abs(o_vec[2] - bbox.ZMin) < 0.08:
        raise ValueError(
            "Refusing mode='additive' on Z=ZMin print-bed face. Use 'subtractive' or 'cartouche'."
        )

    cut_local, fuse_local = build_mark_tools_local(
        mode=mode,
        width_mm=width_mm,
        depth_mm=depth_mm,
        normal_z=float(n_vec[2]),
        vertical_draft=vertical_draft,
    )
    cut_world = _transform_solids(cut_local, mat)
    fuse_world = _transform_solids(fuse_local, mat)

    with tempfile.TemporaryDirectory(prefix="maker_mark_") as tmpdir:
        cut_stl = os.path.join(tmpdir, "cut_tool.stl") if cut_world else ""
        fuse_stl = os.path.join(tmpdir, "fuse_tool.stl") if fuse_world else ""
        if cut_world:
            _write_shapes_stl(cut_world, cut_stl)
        if fuse_world:
            _write_shapes_stl(fuse_world, fuse_stl)

        blender_code = f"""
import bpy, bmesh, sys

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.stl_import(filepath={repr(os.path.abspath(input_stl))})
target = bpy.context.selected_objects[0]
target.name = "Target"

def run_bool(op_type, tool_path):
    bpy.ops.wm.stl_import(filepath=tool_path)
    tool = bpy.context.selected_objects[0]
    tool.name = "Tool"
    bpy.context.view_layer.objects.active = target
    mod = target.modifiers.new(name="MarkBool", type='BOOLEAN')
    mod.operation = op_type
    mod.solver = 'EXACT'
    mod.object = tool
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(tool, do_unlink=True)

if {repr(cut_stl)}:
    run_bool('DIFFERENCE', {repr(cut_stl)})
if {repr(fuse_stl)}:
    run_bool('UNION', {repr(fuse_stl)})

bm = bmesh.new()
bm.from_mesh(target.data)
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
non_m = [e for e in bm.edges if not e.is_manifold]
bm.to_mesh(target.data)
bm.free()

if len(non_m) > 0:
    print(f"ERROR: Non-manifold edges after Boolean: {{len(non_m)}}")
    sys.exit(2)

bpy.ops.object.select_all(action='DESELECT')
target.select_set(True)
bpy.ops.wm.stl_export(filepath={repr(os.path.abspath(output_stl))}, export_selected_objects=True)
print("STL Maker's Mark applied cleanly (0 non-manifold edges):", {repr(os.path.abspath(output_stl))})
"""
        res = subprocess.run(["blender", "-b", "--python-expr", blender_code], capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Blender Boolean failed:\n{res.stdout}\n{res.stderr}")
    return os.path.abspath(output_stl)


def _main():
    parser = argparse.ArgumentParser(description="Apply Maker's Mark to 3D print STL meshes.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_app = sub.add_parser("apply", help="Apply additive/subtractive/cartouche mark to an .stl file")
    p_app.add_argument("input_stl", help="Input .stl path")
    p_app.add_argument("output_stl", help="Output .stl path")
    p_app.add_argument("--mode", choices=["subtractive", "additive", "cartouche"], default="subtractive")
    p_app.add_argument("--face", choices=["bottom", "top", "front", "back", "left", "right"], default="bottom")
    p_app.add_argument("--width", type=float, default=24.0, help="Logo width in mm (default: 24.0)")
    p_app.add_argument("--depth", type=float, default=0.40, help="Depth / height in mm (default: 0.40)")
    p_app.add_argument("--du", type=float, default=0.0, help="Horizontal in-plane offset (mm)")
    p_app.add_argument("--dv", type=float, default=0.0, help="Vertical in-plane offset (mm)")

    args = parser.parse_args()
    if args.cmd == "apply":
        out = apply_maker_mark_to_stl(
            args.input_stl,
            args.output_stl,
            mode=args.mode,
            face=args.face,
            width_mm=args.width,
            depth_mm=args.depth,
            offset_uv=(args.du, args.dv),
        )
        print(f"Done: {out}")


if __name__ == "__main__":
    _main()
