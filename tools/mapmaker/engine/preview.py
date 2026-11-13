"""Fast headless 4-view shaded diagnostic renderer for MapMaker 3D.

Produces `previews/diagnostic_views.png` (Isometric 3D, Top XY, Front XZ, Right YZ)
using pure NumPy + Pillow with directional studio shading, ocean water tinting,
and crisp multi-part depth sorting.
"""

import os
import math
from typing import List, Dict, Any, Tuple
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from .platform_utils import resolve_bold_ttf_path


def _hex_to_rgb01(hex_str: str) -> np.ndarray:
    h = hex_str.lstrip("#")
    if len(h) >= 6:
        return np.array([int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)], dtype=np.float32) / 255.0
    return np.array([0.85, 0.55, 0.25], dtype=np.float32)


def _render_orthographic_panel(
    tris_world: np.ndarray,
    normals_world: np.ndarray,
    face_colors: np.ndarray,
    depth_bias: np.ndarray,
    proj_right: np.ndarray,
    proj_up: np.ndarray,
    proj_depth: np.ndarray,
    panel_w: int = 770,
    panel_h: int = 534,
    bg_rgb: Tuple[int, int, int] = (20, 24, 33)
) -> Image.Image:
    """Renders 100% of visible front/side triangles with directional Lambertian studio shading."""
    img = Image.new("RGB", (panel_w, panel_h), color=bg_rgb)
    if len(tris_world) == 0:
        return img

    # Back-face cull triangles pointing strictly away from orthographic camera (`n · proj_depth < -0.08`)
    facing = np.einsum("nk,k->n", normals_world, proj_depth)
    vis = facing >= -0.08
    tris_v = tris_world[vis]
    norms_v = normals_world[vis]
    cols_v = face_colors[vis]
    bias_v = depth_bias[vis]

    if len(tris_v) == 0:
        return img

    u = np.einsum("ntk,k->nt", tris_v, proj_right)
    v = np.einsum("ntk,k->nt", tris_v, proj_up)
    d = np.einsum("ntk,k->nt", tris_v, proj_depth)

    u_min, u_max = float(np.min(u)), float(np.max(u))
    v_min, v_max = float(np.min(v)), float(np.max(v))
    span_u = max(1.0, u_max - u_min)
    span_v = max(1.0, v_max - v_min)

    margin = 44.0
    scale = min((panel_w - 2 * margin) / span_u, (panel_h - 2 * margin) / span_v)
    cx_u = 0.5 * (u_min + u_max)
    cy_v = 0.5 * (v_min + v_max)

    px = (u - cx_u) * scale + (panel_w * 0.5)
    py = (panel_h * 0.5) - (v - cy_v) * scale

    sun_dir = np.array([0.42, -0.52, 0.74], dtype=np.float32)
    sun_dir /= np.linalg.norm(sun_dir)
    fill_dir = np.array([-0.55, 0.45, 0.70], dtype=np.float32)
    fill_dir /= np.linalg.norm(fill_dir)

    ndotl_sun = np.clip(np.einsum("nk,k->n", norms_v, sun_dir), 0.0, 1.0)
    ndotl_fill = np.clip(np.einsum("nk,k->n", norms_v, fill_dir), 0.0, 1.0)
    intensity = np.clip(0.34 + 0.60 * ndotl_sun + 0.22 * ndotl_fill, 0.18, 1.12)[:, None]

    shaded_rgb = np.clip(cols_v * intensity * 255.0, 0, 255).astype(np.uint8)

    mean_d = np.mean(d, axis=1) + bias_v
    order = np.argsort(mean_d)

    draw = ImageDraw.Draw(img)
    px_ord = px[order]
    py_ord = py[order]
    col_ord = shaded_rgb[order]

    for i in range(len(order)):
        x0, x1, x2 = float(px_ord[i, 0]), float(px_ord[i, 1]), float(px_ord[i, 2])
        y0, y1, y2 = float(py_ord[i, 0]), float(py_ord[i, 1]), float(py_ord[i, 2])
        area2 = (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)
        if abs(area2) < 0.02:
            continue
        c = (int(col_ord[i, 0]), int(col_ord[i, 1]), int(col_ord[i, 2]))
        draw.polygon([(x0, y0), (x1, y1), (x2, y2)], fill=c)

    return img


def generate_diagnostic_views_png(
    output_path: str,
    parts: List[Dict[str, Any]],
    title_banner: str = "MapMaker 3D — Diagnostic 4-View Sheet"
) -> str:
    """Renders a 4-panel (Isometric, Top XY, Front XZ, Right YZ) diagnostic preview PNG."""
    tris_list = []
    norms_list = []
    cols_list = []
    bias_list = []

    for p in parts:
        mesh = p.get("mesh")
        if mesh is None or len(mesh.vertices) == 0 or len(mesh.faces) == 0:
            continue
        v = mesh.vertices
        f = mesh.faces
        t = v[f]
        n = mesh.compute_face_normals()
        pname = p.get("name", "").lower()
        base_col = _hex_to_rgb01(p.get("color", "#F59E0B"))

        p_bias = 0.0
        if "typography" in pname:
            p_bias = 2.5
        elif "pin" in pname or "route" in pname:
            p_bias = 1.4

        if pname.startswith("terrain"):
            top_mask = n[:, 2] >= 0.15
            z_tri = np.mean(t[:, :, 2], axis=1)
            top_zs = z_tri[top_mask] if np.any(top_mask) else z_tri
            z_min_top = float(np.percentile(top_zs, 3.0))
            z_max_top = float(np.max(top_zs))
            z_span = max(1.0, z_max_top - z_min_top)
            t_norm = np.clip((z_tri - z_min_top) / z_span, 0.0, 1.0)[:, None]

            low_col = np.array([0.20, 0.58, 0.34], dtype=np.float32)
            mid_col = np.array([0.82, 0.62, 0.28], dtype=np.float32)
            high_col = np.array([0.96, 0.97, 0.99], dtype=np.float32)
            c_arr = np.where(
                t_norm < 0.55,
                low_col + (t_norm / 0.55) * (mid_col - low_col),
                mid_col + ((t_norm - 0.55) / 0.45) * (high_col - mid_col),
            )
            # Highlight flat sea-level water deck in sapphire blue when coastal step is present
            flat_sea = top_mask & (n[:, 2] > 0.98) & (z_tri <= z_min_top + 0.15) & (z_span > 2.0)
            if np.sum(flat_sea) > len(t) * 0.04:
                c_arr[flat_sea] = np.array([0.14, 0.42, 0.82], dtype=np.float32)

            c_arr[~top_mask] = np.array([0.22, 0.25, 0.33], dtype=np.float32)
        else:
            c_arr = np.repeat(base_col[None, :], len(t), axis=0)

        tris_list.append(t)
        norms_list.append(n)
        cols_list.append(c_arr)
        bias_list.append(np.full(len(t), p_bias, dtype=np.float32))

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    sheet_w, sheet_h = 1600, 1180
    sheet = Image.new("RGB", (sheet_w, sheet_h), color=(14, 17, 23))
    draw = ImageDraw.Draw(sheet)

    ttf_path = resolve_bold_ttf_path()
    try:
        if ttf_path:
            font_hdr = ImageFont.truetype(ttf_path, 20)
            font_lbl = ImageFont.truetype(ttf_path, 15)
        else:
            raise FileNotFoundError("No bold system TrueType font resolved")
    except Exception:
        font_hdr = ImageFont.load_default()
        font_lbl = ImageFont.load_default()

    draw.rectangle([0, 0, sheet_w, 50], fill=(24, 28, 38))
    draw.text((24, 14), title_banner, fill=(245, 247, 250), font=font_hdr)

    if not tris_list:
        sheet.save(output_path, format="PNG")
        return output_path

    all_tris = np.vstack(tris_list)
    all_norms = np.vstack(norms_list)
    all_cols = np.vstack(cols_list)
    all_bias = np.concatenate(bias_list)

    az = math.radians(-38.0)
    el = math.radians(35.0)
    iso_right = np.array([math.cos(az), math.sin(az), 0.0], dtype=np.float32)
    iso_fwd = np.array([-math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), -math.sin(el)], dtype=np.float32)
    iso_depth = -iso_fwd
    iso_up = np.cross(iso_depth, iso_right)
    iso_up /= np.linalg.norm(iso_up)

    views = [
        ("ISOMETRIC 3D VIEW", iso_right, iso_up, iso_depth, (20, 66)),
        ("TOP PLAN VIEW (XY — North +Y)", np.array([1.0, 0.0, 0.0], dtype=np.float32), np.array([0.0, 1.0, 0.0], dtype=np.float32), np.array([0.0, 0.0, 1.0], dtype=np.float32), (810, 66)),
        ("FRONT ELEVATION (XZ — South Profile)", np.array([1.0, 0.0, 0.0], dtype=np.float32), np.array([0.0, 0.0, 1.0], dtype=np.float32), np.array([0.0, -1.0, 0.0], dtype=np.float32), (20, 624)),
        ("RIGHT SIDE PROFILE (YZ — East Profile)", np.array([0.0, 1.0, 0.0], dtype=np.float32), np.array([0.0, 0.0, 1.0], dtype=np.float32), np.array([1.0, 0.0, 0.0], dtype=np.float32), (810, 624)),
    ]

    for label, r_vec, u_vec, d_vec, (ox, oy) in views:
        panel = _render_orthographic_panel(
            all_tris, all_norms, all_cols, all_bias, r_vec, u_vec, d_vec, panel_w=770, panel_h=534
        )
        sheet.paste(panel, (ox, oy))
        draw.rectangle([ox, oy, ox + 770, oy + 534], outline=(49, 56, 72), width=2)
        draw.rectangle([ox, oy, ox + 320, oy + 30], fill=(255, 107, 43))
        draw.text((ox + 12, oy + 6), label, fill=(255, 255, 255), font=font_lbl)

    sheet.save(output_path, format="PNG", optimize=True)
    return output_path
