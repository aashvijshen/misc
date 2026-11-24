#!/usr/bin/env python3
"""Parametric FreeCAD builder & verifier for `bbmp_signboard` (Iteration 3.0).

Models the palm-sized (96.0 x 60.5 mm) Heritage Bengaluru Kempegowda Gopura Arch
BBMP Signboard matching `original.webp`, now with **true 3D-printed bold letters**
shaped via HarfBuzz (`uharfbuzz` + `fontTools` + `shapely`) and fused directly onto
the solid signboard plate for crisp 0.40mm-nozzle printing on the Bambu Lab A1:

  1. `arch_signboard.stl` / `.FCStd` (Prints flat back-down on Z=0 in Bright Yellow PLA, 0 supports):
     - Continuous 4.20mm solid signboard web (paper-insert recess removed to match `original.webp`).
     - Raised 3D-bolded Kannada/English sign word (`+1.25mm` proud relief to Z=5.45mm, default `ಬೆಂಗಳೂರು`)
       with cluster-aware HarfBuzz shaping, round-join outward stroke thickening (`+0.22mm`), and
       smart counter-hole preservation (`>= 0.88mm` clear openings) for 2-3+ perimeter walls @ 0.42mm.
     - Raised +1.10mm stepped red arch border & 3-tier Kempegowda Gopura tower (Z=5.30mm).
     - Raised +0.60mm crescent garland & twin symmetric curled scroll volutes (Z=4.80mm).
     - Twin 7.6 x 7.2 mm square pillars standing proud of the signplate, topped with cornice collars
       and domed finial caps, with vertical front flute pockets and bottom pedestal tenons.
  2. `pedestal_feet.stl` / `.FCStd` (Prints flat on Z=0 in Bright Yellow PLA, 0 supports):
     - Pair of 2-tier stepped square pedestal bases (14.8 x 14.8 x 5.2 mm) for upright stability.
  3. `pillar_flutes_red.stl` / `.FCStd` (Prints flat in 90s in Traffic Red PLA, 0 supports):
     - Pair of rounded-end vertical red flute inlays for crisp zero-paint pillar stripes.
  4. `model.stl` / `.FCStd`:
     - Full upright standing assembly (verified 0.000000 mm^3 Boolean collision across all part pairs).
"""

import argparse
import io
import math
import os
import subprocess
import sys
import tempfile

import uharfbuzz as hb
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

FREECAD_LIB = "/usr/lib/freecad-python3/lib"
if FREECAD_LIB not in sys.path:
    sys.path.append(FREECAD_LIB)

import FreeCAD as App
import Mesh
import MeshPart
import Part


# ==============================================================================
# PHOTOMETRICALLY CALIBRATED DIMENSIONS (mm) MATCHING `original.webp`
# Coordinate convention during flat build:
#   X: horizontal left-right (-48.0 .. +48.0 mm, total assembled width = 96.0 mm)
#   Y: vertical height of sign (0.0 = ground .. 60.5 mm = lotus apex)
#   Z: front-to-back thickness when lying flat on print bed (Z=0.0 is flat back!)
# ==============================================================================
TOTAL_W = 96.00
TOTAL_H = 60.50

# Slender Depth / Thickness Profile (Z-axis when lying flat on print bed)
WEB_Z = 4.20                      # Solid 4.20mm main yellow signboard plate
MID_RELIEF_Z = 4.80               # +0.60mm scroll volutes & teal crescent garland
RED_TRIM_Z = 5.30                 # +1.10mm stepped red arch border & Kempegowda Gopura
DEFAULT_LETTER_HEIGHT = 1.25      # +1.25mm proud 3D bold letters (Z = 5.45mm; 6+ layers @ 0.20mm)
DEFAULT_BOLD_OFFSET = 0.14        # +0.14mm outward stroke dilation (~1.48mm strokes = ~3.5 walls @ 0.42mm!)
DEFAULT_SIGN_TEXT = "ಬೆಂಗಳೂರು"
PILLAR_Z = 7.20                   # 7.2mm deep square pillars (+3.0mm proud of web!)

# Clear Inner Yellow Signboard Text Field (inside 1.68mm red border: Y = 23.88 .. 39.62 mm)
TEXT_CENTER_Y = 31.65             # Optical vertical center of the yellow signboard band
MAX_TEXT_W = 60.00                # Max safe horizontal text span (leaves >= 5mm side margins)
MAX_TEXT_H = 11.20                # Max safe vertical text span (leaves >= 2.2mm top/bottom margins)
MIN_COUNTER_RADIUS = 0.44         # Preserves >= 0.88mm clear inner counter holes (2+ nozzle widths)

# Twin Pillar & Pedestal Foot Coordinates
PILLAR_CX = 40.60                 # Pillar centerlines at X = +/-40.60 mm
PILLAR_W = 7.60                   # X width: 36.80 .. 44.40 mm
FOOT_BOT_W = 14.80                # Bottom square pedestal step: 14.80 x 14.80 mm (spans X=33.2..48.0)
FOOT_BOT_H = 2.80                 # Y = 0.00 .. 2.80 mm
FOOT_TOP_W = 11.40                # Upper square pedestal collar: 11.40 x 11.40 mm
FOOT_TOP_H = 2.40                 # Y = 2.80 .. 5.20 mm
FOOT_TOTAL_H = FOOT_BOT_H + FOOT_TOP_H  # 5.20 mm

# Pillar Capital & Domed Finial (`Y = 40.8 .. 45.7 mm`)
CAP_Y0 = 40.80
CAP_Y1 = 42.90
CAP_W = 9.40
CAP_Z = 8.00                      # Overhangs front (+Z) only; back stays flat on Z=0!
DOME_R = 2.65

# Mortise-and-Tenon Clearances (`0.20 mm/side` snug slip fit, 0.000 mm^3 seated collision)
FIT_CLEARANCE = 0.20
TENON_W = 4.80
TENON_Z = 4.60
TENON_LEN = 3.60                  # Plugs down from Y=5.20 to Y=1.60 inside pedestal foot

# Pillar Vertical Red Flute Slots & Inlays
FLUTE_SLOT_W = 2.20
FLUTE_SLOT_H = 29.60              # Y = 8.40 .. 38.00 mm
FLUTE_SLOT_DEPTH = 1.30
FLUTE_INLAY_W = FLUTE_SLOT_W - 2.0 * FIT_CLEARANCE    # 1.80 mm
FLUTE_INLAY_H = FLUTE_SLOT_H - 2.0 * FIT_CLEARANCE    # 29.20 mm
FLUTE_INLAY_THICK = FLUTE_SLOT_DEPTH - 0.20           # 1.10 mm

FONT_PRESETS = {
    "auto": {
        "label": "Auto Signboard Heavy (Noto Kannada Bold / Lato Black)",
        "kn": [
            "/usr/share/fonts/truetype/noto/NotoSansKannada-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansKannadaUI-Bold.ttf",
        ],
        "en": [
            "/usr/share/fonts/truetype/lato/Lato-Black.ttf",
            "/usr/share/fonts/truetype/msttcorefonts/Arial_Black.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ],
    },
    "kannada_sans": {
        "label": "Noto Sans Kannada Bold",
        "kn": ["/usr/share/fonts/truetype/noto/NotoSansKannada-Bold.ttf"],
        "en": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    },
    "kannada_serif": {
        "label": "Noto Serif Kannada Bold (Classic Heritage)",
        "kn": ["/usr/share/fonts/truetype/noto/NotoSerifKannada-Bold.ttf"],
        "en": ["/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"],
    },
    "arial_black": {
        "label": "Arial Black (Ultra-Thick Block Sans)",
        "kn": ["/usr/share/fonts/truetype/noto/NotoSansKannada-Bold.ttf"],
        "en": [
            "/usr/share/fonts/truetype/msttcorefonts/Arial_Black.ttf",
            "/usr/share/fonts/truetype/lato/Lato-Black.ttf",
        ],
    },
    "lato_black": {
        "label": "Lato Black (Rounded Signboard Sans)",
        "kn": ["/usr/share/fonts/truetype/noto/NotoSansKannada-Bold.ttf"],
        "en": [
            "/usr/share/fonts/truetype/lato/Lato-Black.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ],
    },
}


# ==============================================================================
# HARFBUZZ + FONTTOOLS + SHAPELY 3D-PRINT BOLD LETTER ENGINE
# ==============================================================================
def _resolve_font_path(candidates):
    for p in candidates:
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"None of the candidate fonts exist: {candidates}")


def _split_script_runs(text):
    """Splits a single-line string into contiguous Kannada vs Latin runs."""
    runs = []
    cur_chars = []
    cur_kn = None
    for ch in text:
        if ch.isspace():
            cur_chars.append(ch)
            continue
        is_kn = "\u0c80" <= ch <= "\u0cff"
        if cur_kn is None:
            cur_kn = is_kn
            cur_chars.append(ch)
        elif is_kn == cur_kn:
            cur_chars.append(ch)
        else:
            runs.append(("".join(cur_chars), cur_kn))
            cur_chars = [ch]
            cur_kn = is_kn
    if cur_chars:
        runs.append(("".join(cur_chars), bool(cur_kn)))
    return runs


def _quad_bezier(p0, p1, p2, steps=16):
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1.0 - t
        pts.append((
            mt * mt * p0[0] + 2.0 * mt * t * p1[0] + t * t * p2[0],
            mt * mt * p0[1] + 2.0 * mt * t * p1[1] + t * t * p2[1],
        ))
    return pts


def _cubic_bezier(p0, p1, p2, p3, steps=20):
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1.0 - t
        pts.append((
            mt**3 * p0[0] + 3.0 * mt**2 * t * p1[0] + 3.0 * mt * t**2 * p2[0] + t**3 * p3[0],
            mt**3 * p0[1] + 3.0 * mt**2 * t * p1[1] + 3.0 * mt * t**2 * p2[1] + t**3 * p3[1],
        ))
    return pts


def _pen_ops_to_contours(ops, dx=0.0, dy=0.0, scale=1.0):
    contours = []
    cur = []
    pt = (0.0, 0.0)
    for op, args in ops:
        if op == "moveTo":
            if len(cur) >= 3:
                contours.append(cur)
            p = (args[0][0] * scale + dx, args[0][1] * scale + dy)
            cur = [p]
            pt = p
        elif op == "lineTo":
            p = (args[0][0] * scale + dx, args[0][1] * scale + dy)
            cur.append(p)
            pt = p
        elif op == "qCurveTo":
            t_args = [(a[0] * scale + dx, a[1] * scale + dy) if a is not None else None for a in args]
            if t_args[-1] is None:
                offs = t_args[:-1]
                if offs:
                    first_on = (
                        (offs[0][0] + offs[-1][0]) * 0.5,
                        (offs[0][1] + offs[-1][1]) * 0.5,
                    )
                    cur = [first_on]
                    pt = first_on
                    for i in range(len(offs)):
                        c1 = offs[i]
                        c2 = offs[(i + 1) % len(offs)]
                        mid = ((c1[0] + c2[0]) * 0.5, (c1[1] + c2[1]) * 0.5)
                        cur.extend(_quad_bezier(pt, c1, mid))
                        pt = mid
            else:
                offs = t_args[:-1]
                end_p = t_args[-1]
                if not offs:
                    cur.append(end_p)
                    pt = end_p
                else:
                    for i in range(len(offs) - 1):
                        c1 = offs[i]
                        c2 = offs[i + 1]
                        mid = ((c1[0] + c2[0]) * 0.5, (c1[1] + c2[1]) * 0.5)
                        cur.extend(_quad_bezier(pt, c1, mid))
                        pt = mid
                    cur.extend(_quad_bezier(pt, offs[-1], end_p))
                    pt = end_p
        elif op == "curveTo":
            p1, p2, p3 = [(a[0] * scale + dx, a[1] * scale + dy) for a in args]
            cur.extend(_cubic_bezier(pt, p1, p2, p3))
            pt = p3
        elif op in ("closePath", "endPath"):
            if len(cur) >= 3:
                contours.append(cur)
            cur = []
    if len(cur) >= 3:
        contours.append(cur)
    return contours


def _signed_area(pts):
    area = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return 0.5 * area


def _as_poly_list(geom):
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]


def shape_bold_word_polygons(
    text=DEFAULT_SIGN_TEXT,
    bold_offset=DEFAULT_BOLD_OFFSET,
    scale_pct=100,
    font_key="auto",
):
    """Shapes a single-line Kannada/English word via HarfBuzz and returns:
      (multipolygon_mm, metrics_dict)
    centered on the Heritage Arch yellow signboard field around (0.0, TEXT_CENTER_Y).
    """
    clean_text = " ".join((text or "").strip().split())
    if not clean_text:
        clean_text = DEFAULT_SIGN_TEXT

    preset = FONT_PRESETS.get(font_key, FONT_PRESETS["auto"])
    bold_offset = max(0.0, min(0.45, float(bold_offset)))
    user_scale = max(65.0, min(130.0, float(scale_pct))) / 100.0

    # Determine nominal typographic em size in mm (before width/height safety clamping)
    has_kn = any("\u0c80" <= ch <= "\u0cff" for ch in clean_text)
    nominal_em_mm = (10.45 if has_kn else 9.10) * user_scale
    # Cluster tracking normalized in em so adjacent syllable clusters never fuse when bolded
    cluster_track_em = (1.65 * bold_offset) / max(4.0, nominal_em_mm)

    cursor_em = 0.0
    glyph_geoms = []
    prev_cluster_global = None

    for run_idx, (run_str, is_kn) in enumerate(_split_script_runs(clean_text)):
        fpath = _resolve_font_path(preset["kn"] if is_kn else preset["en"])
        with open(fpath, "rb") as f:
            fdata = f.read()
        hb_face = hb.Face(fdata)
        hb_font = hb.Font(hb_face)
        upem = float(hb_face.upem)

        buf = hb.Buffer()
        buf.add_str(run_str)
        buf.guess_segment_properties()
        hb.shape(hb_font, buf)

        tt = TTFont(fpath)
        gset = tt.getGlyphSet()
        inv_upem = 1.0 / upem

        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            cluster_id = (run_idx, info.cluster)
            if prev_cluster_global is not None and cluster_id != prev_cluster_global:
                cursor_em += cluster_track_em
            prev_cluster_global = cluster_id

            gname = tt.getGlyphName(info.codepoint)
            pen = DecomposingRecordingPen(gset)
            gset[gname].draw(pen)

            gx = cursor_em + pos.x_offset * inv_upem
            gy = pos.y_offset * inv_upem
            cursor_em += pos.x_advance * inv_upem

            contours = _pen_ops_to_contours(pen.value, gx, gy, inv_upem)
            if not contours:
                continue

            # Determine outer vs hole sign universally from largest-magnitude contour
            areas = [_signed_area(c) for c in contours]
            largest_area = max(areas, key=lambda a: abs(a))
            outer_is_neg = largest_area < 0.0

            outers = []
            holes = []
            for c, a in zip(contours, areas):
                if abs(a) < 1e-8:
                    continue
                p = Polygon(c).buffer(0)
                if p.is_empty:
                    continue
                if (a < 0.0) == outer_is_neg:
                    outers.append(p)
                else:
                    holes.append(p)

            if outers:
                g_poly = unary_union(outers)
                if holes:
                    g_poly = g_poly.difference(unary_union(holes))
                g_poly = g_poly.buffer(0)
                if not g_poly.is_empty:
                    glyph_geoms.append(g_poly)

    if not glyph_geoms:
        raise ValueError(f"Text '{clean_text}' produced no drawable vector glyphs!")

    raw_union = unary_union(glyph_geoms).buffer(0)
    rx0, ry0, rx1, ry1 = raw_union.bounds
    raw_w = max(1e-4, rx1 - rx0)
    raw_h = max(1e-4, ry1 - ry0)

    # Fit inside (MAX_TEXT_W, MAX_TEXT_H) after accounting for outward 2 * bold_offset expansion
    avail_w = max(10.0, MAX_TEXT_W - 2.0 * bold_offset)
    avail_h = max(5.0, MAX_TEXT_H - 2.0 * bold_offset)
    em_mm = min(nominal_em_mm, avail_w / raw_w, avail_h / raw_h)

    # Scale if word was compressed so bold_offset gently scales down on ultra-long 14+ char words
    compress_ratio = min(1.0, em_mm / nominal_em_mm)
    eff_bold = bold_offset * (0.65 + 0.35 * compress_ratio)

    rcx = 0.5 * (rx0 + rx1)
    rcy = 0.5 * (ry0 + ry1)

    def _to_mm_ring(coords):
        return [((x - rcx) * em_mm, TEXT_CENTER_Y + (y - rcy) * em_mm) for x, y in coords]

    scaled_polys = []
    for p in _as_poly_list(raw_union):
        ext = _to_mm_ring(p.exterior.coords)
        ints = [_to_mm_ring(r.coords) for r in p.interiors]
        sp = Polygon(ext, ints).buffer(0)
        if not sp.is_empty:
            scaled_polys.append(sp)

    scaled_union = unary_union(scaled_polys).buffer(0)

    # Smart "3D-Print Bold" Dilation + Counter-Hole Guard:
    # 1. Dilate outer shells outward by +eff_bold with smooth round joins.
    # 2. Shrink interior counter holes by at most 0.55 * eff_bold while guaranteeing
    #    every hole retains >= MIN_COUNTER_RADIUS (0.44mm -> 0.88mm open width) so
    #    eyes in `ಬೆ`, `ಂ`, `ಳ`, `ಇ`, `B`, `A`, `R`, `O` never fuse shut!
    if eff_bold > 1e-4:
        dilated_shells = []
        guarded_holes = []
        for p in _as_poly_list(scaled_union):
            shell = Polygon(p.exterior).buffer(eff_bold, join_style=1, quad_segs=16)
            dilated_shells.append(shell)
            for ir in p.interiors:
                hp = Polygon(ir).buffer(0)
                if hp.is_empty:
                    continue
                target_shrink = 0.55 * eff_bold
                # Binary-search max safe shrink keeping inscribed radius >= MIN_COUNTER_RADIUS
                if hp.buffer(-MIN_COUNTER_RADIUS).is_empty:
                    # Original counter is already small (e.g. tight loop in `ಳ`): preserve 100%!
                    guarded_holes.append(hp)
                elif not hp.buffer(-(target_shrink + MIN_COUNTER_RADIUS)).is_empty:
                    guarded_holes.append(hp.buffer(-target_shrink, join_style=1, quad_segs=12))
                else:
                    lo, hi = 0.0, target_shrink
                    for _ in range(8):
                        mid = 0.5 * (lo + hi)
                        if not hp.buffer(-(mid + MIN_COUNTER_RADIUS)).is_empty:
                            lo = mid
                        else:
                            hi = mid
                    guarded_holes.append(hp.buffer(-lo, join_style=1, quad_segs=12) if lo > 1e-3 else hp)

        bold_geom = unary_union(dilated_shells).buffer(0)
        if guarded_holes:
            bold_geom = bold_geom.difference(unary_union(guarded_holes)).buffer(0)
    else:
        bold_geom = scaled_union

    # Light topology-preserving simplify (0.005mm chord) for ultra-clean OpenCASCADE B-Rep edges
    cleaned_polys = []
    for p in _as_poly_list(bold_geom):
        sp = p.simplify(0.005, preserve_topology=True).buffer(0)
        for sub in _as_poly_list(sp):
            if sub.area >= 0.04:
                cleaned_polys.append(sub)

    final_mp = MultiPolygon(cleaned_polys)
    bx0, by0, bx1, by1 = final_mp.bounds

    # Re-center exact bolded bounding box cleanly on (0.0, TEXT_CENTER_Y)
    dx_fix = -0.5 * (bx0 + bx1)
    dy_fix = TEXT_CENTER_Y - 0.5 * (by0 + by1)
    if abs(dx_fix) > 1e-4 or abs(dy_fix) > 1e-4:
        shifted = []
        for p in final_mp.geoms:
            ext = [(x + dx_fix, y + dy_fix) for x, y in p.exterior.coords]
            ints = [[(x + dx_fix, y + dy_fix) for x, y in r.coords] for r in p.interiors]
            shifted.append(Polygon(ext, ints))
        final_mp = MultiPolygon(shifted)
        bx0, by0, bx1, by1 = final_mp.bounds

    total_area = final_mp.area
    total_perim = final_mp.length
    mean_stroke_mm = (2.0 * total_area / total_perim) if total_perim > 1e-6 else 0.0
    num_holes = sum(len(p.interiors) for p in final_mp.geoms)

    metrics = {
        "text": clean_text,
        "bbox_w_mm": round(bx1 - bx0, 2),
        "bbox_h_mm": round(by1 - by0, 2),
        "effective_bold_mm": round(eff_bold, 3),
        "mean_stroke_mm": round(mean_stroke_mm, 2),
        "walls_at_042": round(mean_stroke_mm / 0.42, 1),
        "num_islands": len(final_mp.geoms),
        "num_counters": num_holes,
    }
    return final_mp, metrics


def _ring_to_freecad_wire(coords, z0):
    pts = []
    for x, y in coords:
        if not pts or math.hypot(x - pts[-1][0], y - pts[-1][1]) > 0.008:
            pts.append((x, y))
    if len(pts) < 3:
        return None
    if math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) > 1e-5:
        pts.append(pts[0])
    else:
        pts[-1] = pts[0]
    if len(pts) < 4:
        return None
    vecs = [App.Vector(x, y, z0) for x, y in pts]
    return Part.makePolygon(vecs)


def polygons_to_freecad_solid(multipoly, z0, z1):
    """Extrudes a Shapely MultiPolygon (including interior counter holes) into a FreeCAD solid/compound."""
    dz = z1 - z0
    solids = []
    for poly in _as_poly_list(multipoly):
        # Ensure exterior is CCW and holes are CW for OpenCASCADE planar face builder
        ext_coords = list(poly.exterior.coords)
        if _signed_area(ext_coords[:-1]) < 0.0:
            ext_coords.reverse()
        outer_wire = _ring_to_freecad_wire(ext_coords, z0)
        if outer_wire is None:
            continue
        outer_face = Part.Face(outer_wire)

        hole_solids = []
        for ir in poly.interiors:
            h_coords = list(ir.coords)
            if _signed_area(h_coords[:-1]) < 0.0:
                h_coords.reverse()
            hw = _ring_to_freecad_wire(h_coords, z0 - 0.2)
            if hw is not None:
                h_face = Part.Face(hw)
                hole_solids.append(h_face.extrude(App.Vector(0, 0, dz + 0.4)))

        p_sol = outer_face.extrude(App.Vector(0, 0, dz))
        for hs in hole_solids:
            p_sol = p_sol.cut(hs)
        solids.append(p_sol)

    if not solids:
        raise ValueError("Failed to build any FreeCAD letter solids!")
    combined = solids[0]
    for s in solids[1:]:
        combined = combined.fuse(s)
    return combined.removeSplitter()


# ==============================================================================
# HERITAGE KEMPEGOWDA ARCH CAD GEOMETRY
# ==============================================================================
def sample_crown_half_profile(inset=0.0):
    """Returns right-half (X >= 0) (x, y) points for the ornate stepped Kempegowda crown
    from X = 0 (apex) out to X = 37.00 (inner pillar wall), optionally inset by `inset` mm
    to form the crisp 1.68mm-wide raised red border!
    """
    raw = [
        (0.00, 60.50),
        (1.60, 59.95),
        (3.20, 58.40),
        (4.80, 56.20),
        (6.20, 54.40),
        (8.20, 53.65),
        (10.00, 52.30),
        (11.40, 50.60),
        (14.50, 50.25),
        (15.60, 45.70),
        (19.50, 44.45),
        (25.80, 44.10),
        (26.60, 41.30),
        (37.00, 41.30),
    ]
    if abs(inset) < 1e-6:
        return raw

    n_pts = len(raw)
    normals = []
    for i in range(n_pts):
        x_prev, y_prev = raw[max(0, i - 1)]
        x_next, y_next = raw[min(n_pts - 1, i + 1)]
        dx, dy = x_next - x_prev, y_next - y_prev
        L = math.hypot(dx, dy) or 1.0
        nx, ny = dy / L, -dx / L
        normals.append((nx, ny))

    shifted = []
    for i, ((x, y), (nx, ny)) in enumerate(zip(raw, normals)):
        sx = x + inset * nx
        sy = y + inset * ny
        if i == 0:
            sx = 0.0
            sy = y - inset * 1.35
        elif i == n_pts - 1:
            sx = 37.00
            sy = y - inset
        shifted.append((max(0.0, sx), sy))
    return shifted


def sample_bottom_arch_half_profile(offset_y=0.0):
    """Returns right-half (X: 0 -> 37.0) points for the lower arch beam & corner spandrels."""
    pts = [(0.00, 22.20 + offset_y), (29.20, 22.20 + offset_y)]
    for k in range(1, 7):
        ang = math.radians(90.0 - k * 13.0)
        ax = (
            29.20 + (5.60 + offset_y) * math.cos(ang)
            if offset_y == 0
            else 29.20 + (5.60 - offset_y) * math.cos(ang)
        )
        ay = (22.20 - 5.60) + (5.60 + offset_y) * math.sin(ang)
        pts.append((min(35.20, ax), ay))
    pts.append((35.40, 16.80 + offset_y))
    pts.append((35.40, 15.20 + offset_y))
    pts.append((37.00, 15.20 + offset_y))
    return pts


def build_symmetric_plate(top_half, bot_half, z0, z1):
    """Extrudes a closed symmetric 2D face between `top_half` and `bot_half` from z0 to z1."""
    left_top = [(-x, y) for x, y in reversed(top_half[1:])]
    full_top = left_top + top_half
    right_bot = list(reversed(bot_half))
    left_bot = [(-x, y) for x, y in bot_half[1:]]
    poly_2d = full_top + right_bot + left_bot
    poly_2d.append(poly_2d[0])

    cleaned = [poly_2d[0]]
    for p in poly_2d[1:]:
        if math.hypot(p[0] - cleaned[-1][0], p[1] - cleaned[-1][1]) > 0.05:
            cleaned.append(p)
    if math.hypot(cleaned[0][0] - cleaned[-1][0], cleaned[0][1] - cleaned[-1][1]) > 0.05:
        cleaned.append(cleaned[0])
    else:
        cleaned[-1] = cleaned[0]

    vecs = [App.Vector(x, y, z0) for x, y in cleaned]
    face = Part.Face(Part.makePolygon(vecs))
    return face.extrude(App.Vector(0, 0, z1 - z0))


def make_pill_slot_2d(cx, y0, y1, width, z0, height):
    """Builds a vertical rounded-end stadium/pill prism."""
    r = width / 2.0
    rect_h = max(0.2, (y1 - y0) - 2.0 * r)
    box = Part.makeBox(width, rect_h, height, App.Vector(cx - r, y0 + r, z0))
    c_bot = Part.makeCylinder(r, height, App.Vector(cx, y0 + r, z0))
    c_top = Part.makeCylinder(r, height, App.Vector(cx, y1 - r, z0))
    return box.fuse(c_bot).fuse(c_top).removeSplitter()


def make_scroll_volute(sign_x=1.0):
    """Builds one symmetric Baroque/Mysore curled S-scroll volute under the crown medallion."""
    z0 = WEB_Z - 0.2
    h = (MID_RELIEF_Z - WEB_Z) + 0.2
    parts = []
    pts = [
        (5.2, 41.5, 0.95),
        (6.4, 42.3, 0.90),
        (7.8, 43.3, 0.92),
        (9.3, 43.8, 0.95),
        (10.8, 43.4, 0.95),
        (11.6, 42.2, 0.90),
        (11.1, 41.2, 1.05),
        (12.4, 42.3, 0.80),
        (13.7, 41.5, 0.95),
    ]
    for px, py, pr in pts:
        parts.append(Part.makeCylinder(pr, h, App.Vector(sign_x * px, py, z0)))
    shape = parts[0]
    for p in parts[1:]:
        shape = shape.fuse(p)
    return shape.removeSplitter()


def make_kempegowda_medallion_and_gopura():
    """Builds the circular medallion ring, teal crescent wreath, and 3-tier Kempegowda Gopura tower."""
    mcx, mcy = 0.0, 49.00
    z_base = WEB_Z - 0.2

    med_ring = Part.makeCylinder(7.55, RED_TRIM_Z - z_base, App.Vector(mcx, mcy, z_base)).cut(
        Part.makeCylinder(6.05, RED_TRIM_Z - z_base + 1.0, App.Vector(mcx, mcy, z_base - 0.5))
    )

    cres_ring = Part.makeCylinder(5.85, MID_RELIEF_Z - z_base, App.Vector(mcx, mcy, z_base)).cut(
        Part.makeCylinder(4.55, MID_RELIEF_Z - z_base + 1.0, App.Vector(mcx, mcy, z_base - 0.5))
    )
    wedge_pts = [
        App.Vector(mcx, mcy + 0.5, z_base - 0.5),
        App.Vector(mcx - 4.4, mcy + 7.5, z_base - 0.5),
        App.Vector(mcx + 4.4, mcy + 7.5, z_base - 0.5),
        App.Vector(mcx, mcy + 0.5, z_base - 0.5),
    ]
    wedge_cut = Part.Face(Part.makePolygon(wedge_pts)).extrude(App.Vector(0, 0, 5.0))
    crescent = cres_ring.cut(wedge_cut)
    for sx in (-1.0, 1.0):
        tip = Part.makeCylinder(0.75, MID_RELIEF_Z - z_base, App.Vector(sx * 3.15, mcy + 4.15, z_base))
        crescent = crescent.fuse(tip)

    h_red = RED_TRIM_Z - z_base
    t1 = Part.makeBox(5.80, 1.25, h_red, App.Vector(-2.90, 45.65, z_base))
    t2 = Part.makeBox(4.80, 1.15, h_red, App.Vector(-2.40, 47.20, z_base))
    t3 = Part.makeBox(3.80, 1.05, h_red, App.Vector(-1.90, 48.70, z_base))
    core = Part.makeBox(2.90, 4.80, h_red, App.Vector(-1.45, 45.65, z_base))
    dome_box = Part.makeBox(3.10, 2.20, h_red, App.Vector(-1.55, 49.70, z_base))
    dome_cap = Part.makeCylinder(1.55, h_red, App.Vector(0.0, 51.85, z_base))
    finial = Part.makeCylinder(0.65, h_red, App.Vector(0.0, 53.65, z_base))
    gopura = t1.fuse(t2).fuse(t3).fuse(core).fuse(dome_box).fuse(dome_cap).fuse(finial)
    win = make_pill_slot_2d(0.0, 50.35, 52.05, 1.05, WEB_Z + 0.15, 2.0)
    gopura = gopura.cut(win)

    return med_ring.fuse(crescent).fuse(gopura).removeSplitter()


def build_arch_signboard_blank():
    """Builds the base Heritage Arch Signboard (without text, and with NO paper-insert recess)."""
    # 1. Continuous Solid Yellow Signplate & Ornate Crown Web (Z = 0 .. WEB_Z = 4.20 mm)
    outer_top = sample_crown_half_profile(inset=0.0)
    outer_bot = sample_bottom_arch_half_profile(offset_y=0.0)
    web = build_symmetric_plate(outer_top, outer_bot, 0.0, WEB_Z)

    # 2. Raised Stepped Red Crown Border & Lower Spandrel Arch Border (Z = WEB_Z .. RED_TRIM_Z = 5.30 mm)
    BORDER_W = 1.68  # Exact 4 perimeters @ 0.42mm!
    inner_top = sample_crown_half_profile(inset=BORDER_W)
    inner_bot = sample_bottom_arch_half_profile(offset_y=BORDER_W)

    full_rim_plate = build_symmetric_plate(outer_top, outer_bot, WEB_Z - 0.2, RED_TRIM_Z)
    inner_cut_plate = build_symmetric_plate(inner_top, inner_bot, WEB_Z - 0.5, RED_TRIM_Z + 1.0)
    red_rim = full_rim_plate.cut(inner_cut_plate)

    shape = web.fuse(red_rim)

    # 3. Kempegowda Medallion + Gopura + Crescent + Twin Scroll Volutes
    medallion = make_kempegowda_medallion_and_gopura()
    vol_r = make_scroll_volute(1.0)
    vol_l = make_scroll_volute(-1.0)
    shape = shape.fuse(medallion).fuse(vol_r).fuse(vol_l)

    # 4. Fuse Twin Square Fluted Pillars (X = +/-40.60, Y = 5.20 .. 42.90, Z = 0.00 .. 7.20)
    for sx in (-1.0, 1.0):
        pcx = sx * PILLAR_CX
        shaft = Part.makeBox(
            PILLAR_W,
            CAP_Y0 - FOOT_TOTAL_H,
            PILLAR_Z,
            App.Vector(pcx - PILLAR_W / 2.0, FOOT_TOTAL_H, 0.0),
        )
        cap_lower = Part.makeBox(
            CAP_W - 0.8,
            0.80,
            CAP_Z - 0.4,
            App.Vector(pcx - (CAP_W - 0.8) / 2.0, CAP_Y0, 0.0),
        )
        cap_upper = Part.makeBox(
            CAP_W,
            CAP_Y1 - (CAP_Y0 + 0.80),
            CAP_Z,
            App.Vector(pcx - CAP_W / 2.0, CAP_Y0 + 0.80, 0.0),
        )
        dome_sph = Part.makeSphere(DOME_R, App.Vector(pcx, CAP_Y1 + 0.15, PILLAR_Z / 2.0))
        dome_mask = Part.makeBox(10.0, 6.0, CAP_Z, App.Vector(pcx - 5.0, CAP_Y1, 0.0))
        dome = dome_sph.common(dome_mask)

        tenon = Part.makeBox(
            TENON_W,
            TENON_LEN + 0.4,
            TENON_Z,
            App.Vector(pcx - TENON_W / 2.0, FOOT_TOTAL_H - TENON_LEN, 0.0),
        )

        pillar = shaft.fuse(cap_lower).fuse(cap_upper).fuse(dome).fuse(tenon)
        flute_cut = make_pill_slot_2d(
            pcx,
            8.40,
            8.40 + FLUTE_SLOT_H,
            FLUTE_SLOT_W,
            PILLAR_Z - FLUTE_SLOT_DEPTH,
            FLUTE_SLOT_DEPTH + 1.0,
        )
        pillar = pillar.cut(flute_cut)
        shape = shape.fuse(pillar)

    return shape.removeSplitter()


def build_arch_signboard(
    sign_text=DEFAULT_SIGN_TEXT,
    bold_offset=DEFAULT_BOLD_OFFSET,
    letter_height=DEFAULT_LETTER_HEIGHT,
    scale_pct=100,
    font_key="auto",
    return_details=False,
):
    """Builds Part 1 (`arch_signboard`) with fused 3D-bolded sign letters on Z=0, zero supports."""
    blank_board = build_arch_signboard_blank()
    letter_mp, metrics = shape_bold_word_polygons(
        text=sign_text,
        bold_offset=bold_offset,
        scale_pct=scale_pct,
        font_key=font_key,
    )
    h_let = max(0.40, min(3.00, float(letter_height)))
    letters_solid = polygons_to_freecad_solid(letter_mp, WEB_Z - 0.20, WEB_Z + h_let)
    fused_board = blank_board.fuse(letters_solid).removeSplitter()
    metrics["letter_height_mm"] = round(h_let, 2)
    metrics["letter_top_z_mm"] = round(WEB_Z + h_let, 2)
    if return_details:
        return fused_board, blank_board, letters_solid, metrics
    return fused_board


def export_custom_arch_stl_bytes(
    sign_text=DEFAULT_SIGN_TEXT,
    bold_offset=DEFAULT_BOLD_OFFSET,
    letter_height=DEFAULT_LETTER_HEIGHT,
    scale_pct=100,
    font_key="auto",
):
    """Builds a custom-word `arch_signboard.stl` in memory and returns `(stl_bytes, metrics)`."""
    board_flat, _, _, metrics = build_arch_signboard(
        sign_text=sign_text,
        bold_offset=bold_offset,
        letter_height=letter_height,
        scale_pct=scale_pct,
        font_key=font_key,
        return_details=True,
    )
    asm_mesh = Mesh.Mesh()
    for sol in board_flat.Solids:
        m = MeshPart.meshFromShape(Shape=sol, LinearDeflection=0.025, AngularDeflection=0.15, Relative=False)
        asm_mesh.addMesh(m)
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tf:
        tmp_path = tf.name
    try:
        asm_mesh.write(tmp_path)
        with open(tmp_path, "rb") as f:
            stl_bytes = f.read()
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    return stl_bytes, metrics


def build_single_pedestal_foot():
    """Builds ONE 2-tier stepped square pedestal foot centered at (0, 0) on Z = 0 .. 5.20 mm."""
    hw1 = FOOT_BOT_W / 2.0
    tier1 = Part.makeBox(FOOT_BOT_W, FOOT_BOT_W, FOOT_BOT_H, App.Vector(-hw1, -hw1, 0.0))

    hw2 = FOOT_TOP_W / 2.0
    tier2 = Part.makeBox(FOOT_TOP_W, FOOT_TOP_W, FOOT_TOP_H + 0.2, App.Vector(-hw2, -hw2, FOOT_BOT_H - 0.2))
    foot = tier1.fuse(tier2)

    sock_w = TENON_W + 2.0 * FIT_CLEARANCE
    sock_d = TENON_Z + 2.0 * FIT_CLEARANCE
    sock_h = TENON_LEN + 0.35
    sock_y0 = -PILLAR_Z / 2.0 - FIT_CLEARANCE
    socket = Part.makeBox(
        sock_w,
        sock_d,
        sock_h + 1.0,
        App.Vector(-sock_w / 2.0, sock_y0, FOOT_TOTAL_H - sock_h),
    )
    return foot.cut(socket).removeSplitter()


def build_pedestal_feet_plate():
    """Returns list of both left & right pedestal feet arranged flat on Z = 0 for slicing."""
    f_left = build_single_pedestal_foot()
    f_left.translate(App.Vector(-12.0, 0.0, 0.0))
    f_right = build_single_pedestal_foot()
    f_right.translate(App.Vector(12.0, 0.0, 0.0))
    return [f_left, f_right]


def build_single_pillar_flute_inlay():
    """Builds one rounded-end Traffic Red pillar flute inlay flat on Z = 0 .. FLUTE_INLAY_THICK."""
    return make_pill_slot_2d(0.0, 0.0, FLUTE_INLAY_H, FLUTE_INLAY_W, 0.0, FLUTE_INLAY_THICK)


def build_pillar_flutes_plate():
    """Returns list of both Traffic Red pillar flute inlays arranged flat on Z = 0 for a 90s print."""
    s1 = build_single_pillar_flute_inlay()
    s1.translate(App.Vector(-3.5, -FLUTE_INLAY_H / 2.0, 0.0))
    s2 = build_single_pillar_flute_inlay()
    s2.translate(App.Vector(3.5, -FLUTE_INLAY_H / 2.0, 0.0))
    return [s1, s2]


def save_shape_files(shape_or_list, name, fcstd_path, stl_path):
    solids_list = shape_or_list if isinstance(shape_or_list, list) else list(shape_or_list.Solids)
    doc = App.newDocument(name)
    for idx, sol in enumerate(solids_list):
        feat = doc.addObject("Part::Feature", f"{name}_{idx+1}")
        feat.Shape = sol
    doc.recompute()
    doc.saveAs(fcstd_path)

    asm_mesh = Mesh.Mesh()
    for sol in solids_list:
        m = MeshPart.meshFromShape(Shape=sol, LinearDeflection=0.025, AngularDeflection=0.15, Relative=False)
        asm_mesh.addMesh(m)
    asm_mesh.write(stl_path)
    bb = asm_mesh.BoundBox
    vol = sum(s.Volume for s in solids_list)
    print(f"[Exported] {os.path.basename(stl_path)} | BBox: {bb.XLength:.2f} x {bb.YLength:.2f} x {bb.ZLength:.2f} mm | Vol: {vol:.1f} mm^3")
    return asm_mesh


def render_studio_color_preview(out_dir, blank_board_flat, letters_flat, foot_l, foot_r, flute_l, flute_r):
    """Renders `previews/studio_render.png` in Blender showing the true 3D raised black letters,
    raised red border/Gopura/flutes, teal crescent, and bright yellow arch!
    """
    with tempfile.TemporaryDirectory() as tmpd:
        # Build upright sub-shapes for true multi-material 3D studio preview
        def _to_upright(sh):
            c = sh.copy()
            c.rotate(App.Vector(0, 0, 0), App.Vector(1, 0, 0), 90.0)
            c.translate(App.Vector(0.0, PILLAR_Z / 2.0, 0.0))
            return c

        # Separate decorative red & teal relief meshes purely for accurate color studio visualization
        outer_top = sample_crown_half_profile(inset=0.0)
        outer_bot = sample_bottom_arch_half_profile(offset_y=0.0)
        inner_top = sample_crown_half_profile(inset=1.68)
        inner_bot = sample_bottom_arch_half_profile(offset_y=1.68)
        red_rim = build_symmetric_plate(outer_top, outer_bot, WEB_Z - 0.05, RED_TRIM_Z + 0.02).cut(
            build_symmetric_plate(inner_top, inner_bot, WEB_Z - 0.2, RED_TRIM_Z + 0.5)
        )
        mcx, mcy, zb = 0.0, 49.0, WEB_Z - 0.05
        med_ring = Part.makeCylinder(7.55, RED_TRIM_Z - zb + 0.02, App.Vector(mcx, mcy, zb)).cut(
            Part.makeCylinder(6.05, RED_TRIM_Z - zb + 0.5, App.Vector(mcx, mcy, zb - 0.2))
        )
        hr = RED_TRIM_Z - zb + 0.02
        gop = (
            Part.makeBox(5.80, 1.25, hr, App.Vector(-2.90, 45.65, zb))
            .fuse(Part.makeBox(4.80, 1.15, hr, App.Vector(-2.40, 47.20, zb)))
            .fuse(Part.makeBox(3.80, 1.05, hr, App.Vector(-1.90, 48.70, zb)))
            .fuse(Part.makeBox(2.90, 4.80, hr, App.Vector(-1.45, 45.65, zb)))
            .fuse(Part.makeBox(3.10, 2.20, hr, App.Vector(-1.55, 49.70, zb)))
            .fuse(Part.makeCylinder(1.55, hr, App.Vector(0.0, 51.85, zb)))
            .fuse(Part.makeCylinder(0.65, hr, App.Vector(0.0, 53.65, zb)))
            .cut(make_pill_slot_2d(0.0, 50.35, 52.05, 1.05, WEB_Z + 0.15, 2.0))
        )
        red_decor_up = _to_upright(red_rim.fuse(med_ring).fuse(gop)).fuse(flute_l).fuse(flute_r)

        cres_ring = Part.makeCylinder(5.85, MID_RELIEF_Z - zb + 0.02, App.Vector(mcx, mcy, zb)).cut(
            Part.makeCylinder(4.55, MID_RELIEF_Z - zb + 0.5, App.Vector(mcx, mcy, zb - 0.2))
        )
        w_pts = [
            App.Vector(mcx, mcy + 0.5, zb - 0.2),
            App.Vector(mcx - 4.4, mcy + 7.5, zb - 0.2),
            App.Vector(mcx + 4.4, mcy + 7.5, zb - 0.2),
            App.Vector(mcx, mcy + 0.5, zb - 0.2),
        ]
        cres = cres_ring.cut(Part.Face(Part.makePolygon(w_pts)).extrude(App.Vector(0, 0, 5.0)))
        for sx in (-1.0, 1.0):
            cres = cres.fuse(Part.makeCylinder(0.75, MID_RELIEF_Z - zb + 0.02, App.Vector(sx * 3.15, mcy + 4.15, zb)))
        teal_up = _to_upright(cres)

        yellow_up = _to_upright(blank_board_flat).fuse(foot_l).fuse(foot_r)
        letters_up = _to_upright(letters_flat)
        # Nudge color overlay shells by 0.02mm forward (-Y) so Cycles has zero coplanar Z-fighting
        letters_up.translate(App.Vector(0, -0.02, 0))
        red_decor_up.translate(App.Vector(0, -0.02, 0))
        teal_up.translate(App.Vector(0, -0.02, 0))

        paths = {}
        for key, sh in [("yellow", yellow_up), ("red", red_decor_up), ("teal", teal_up), ("black", letters_up)]:
            p = os.path.join(tmpd, f"{key}.stl")
            mm = Mesh.Mesh()
            for sol in sh.Solids:
                mm.addMesh(MeshPart.meshFromShape(Shape=sol, LinearDeflection=0.02, AngularDeflection=0.12, Relative=False))
            mm.write(p)
            paths[key] = p

        out_png = os.path.join(out_dir, "previews", "studio_render.png")
        b_script = f"""
import bpy, math

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.samples = 56
scene.cycles.use_denoising = False
scene.render.resolution_x = 1200
scene.render.resolution_y = 950
scene.view_settings.view_transform = 'Standard'

world = bpy.data.worlds.new("StudioWorld")
scene.world = world
world.use_nodes = True
bg_node = world.node_tree.nodes.get("Background")
bg_node.inputs["Color"].default_value = (0.96, 0.95, 0.92, 1.0)
bg_node.inputs["Strength"].default_value = 0.82

def make_mat(name, rgba, rough=0.38):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = rgba
    bsdf.inputs["Roughness"].default_value = rough
    return m

mats = {{
    "yellow": make_mat("BrightYellowPLA", (0.97, 0.76, 0.06, 1.0), 0.34),
    "red": make_mat("TrafficRedPLA", (0.86, 0.16, 0.12, 1.0), 0.36),
    "teal": make_mat("TealAccent", (0.04, 0.58, 0.47, 1.0), 0.38),
    "black": make_mat("MatteBlackPLA", (0.04, 0.04, 0.04, 1.0), 0.44),
}}

for k, stl_p in {repr(paths)}.items():
    bpy.ops.wm.stl_import(filepath=stl_p)
    obj = bpy.context.selected_objects[0]
    obj.data.materials.append(mats[k])

# Studio backdrop floor & back wall
bpy.ops.mesh.primitive_plane_add(size=800, location=(0, 0, 0))
floor = bpy.context.active_object
floor_mat = make_mat("StudioFloor", (0.96, 0.95, 0.93, 1.0), 0.78)
floor.data.materials.append(floor_mat)

bpy.ops.mesh.primitive_plane_add(size=800, location=(0, 95, 180), rotation=(math.radians(90), 0, 0))
wall = bpy.context.active_object
wall.data.materials.append(floor_mat)

# Soft 3-point studio area lighting (angled slightly from side-top to cast crisp 3D shadow from raised letters!)
def add_area(name, loc, rot_deg, energy, size):
    ld = bpy.data.lights.new(name=name, type='AREA')
    ld.energy = energy
    ld.size = size
    lo = bpy.data.objects.new(name, ld)
    lo.location = loc
    lo.rotation_euler = tuple(math.radians(a) for a in rot_deg)
    bpy.context.collection.objects.link(lo)

add_area("KeyLight", (-95, -145, 130), (54, 0, -28), 52000, 125)
add_area("FillLight", (110, -135, 95), (62, 0, 38), 28000, 150)
add_area("TopRim", (0, -40, 185), (14, 0, 0), 22000, 140)

cam_d = bpy.data.cameras.new("StudioCam")
cam_d.lens = 62
cam = bpy.data.objects.new("StudioCam", cam_d)
cam.location = (-6.0, -205.0, 35.0)
bpy.context.collection.objects.link(cam)
scene.camera = cam

target = bpy.data.objects.new("Aim", None)
target.location = (0.0, 0.0, 29.5)
bpy.context.collection.objects.link(target)
tr = cam.constraints.new(type='TRACK_TO')
tr.target = target
tr.track_axis = 'TRACK_NEGATIVE_Z'
tr.up_axis = 'UP_Y'

scene.render.filepath = {repr(out_png)}
bpy.ops.render.render(write_still=True)
"""
        res = subprocess.run(["blender", "-b", "--python-expr", b_script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            print(f"[Warning] Studio render stderr: {res.stderr[-400:]}")
        else:
            print(f"[Rendered] {out_png}")


def main():
    parser = argparse.ArgumentParser(description="Parametric 3D Builder for Heritage BBMP Arch Signboard")
    parser.add_argument("--text", "--line1", dest="text", type=str, default=DEFAULT_SIGN_TEXT, help="Single-word Kannada or English sign text (default: ಬೆಂಗಳೂರು)")
    parser.add_argument("--bold-offset", type=float, default=DEFAULT_BOLD_OFFSET, help="Outward stroke thickening in mm for 0.4mm nozzle printability (default: 0.22)")
    parser.add_argument("--letter-height", type=float, default=DEFAULT_LETTER_HEIGHT, help="3D raised letter relief height in mm above signboard face (default: 1.25)")
    parser.add_argument("--scale", type=int, default=100, help="Relative text scale percentage (default: 100)")
    parser.add_argument("--font", type=str, default="auto", choices=list(FONT_PRESETS.keys()), help="Font preset")
    parser.add_argument("--out-stl", type=str, default="", help="Optional custom output path to export ONLY the customized arch_signboard STL")
    parser.add_argument("--render-previews", action="store_true", help="Regenerate 4-view diagnostics and 3D color studio render")
    args = parser.parse_args()

    out_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(os.path.join(out_dir, "previews"), exist_ok=True)

    print(f"1. Building Part 1: arch_signboard with 3D bold text '{args.text}' (flat on Z=0)...")
    board_flat, blank_flat, letters_flat, metrics = build_arch_signboard(
        sign_text=args.text,
        bold_offset=args.bold_offset,
        letter_height=args.letter_height,
        scale_pct=args.scale,
        font_key=args.font,
        return_details=True,
    )
    assert board_flat.isValid(), "arch_signboard B-Rep shape is invalid!"
    print(
        f"   -> 3D Text Metrics: '{metrics['text']}' | Span: {metrics['bbox_w_mm']} x {metrics['bbox_h_mm']} mm | "
        f"Mean Stroke: {metrics['mean_stroke_mm']} mm (~{metrics['walls_at_042']} walls @ 0.42mm) | "
        f"Relief: +{metrics['letter_height_mm']} mm (Z_top={metrics['letter_top_z_mm']} mm) | "
        f"Islands: {metrics['num_islands']}, Open Counters: {metrics['num_counters']}"
    )

    if args.out_stl:
        out_stl_abs = os.path.abspath(args.out_stl)
        os.makedirs(os.path.dirname(out_stl_abs), exist_ok=True)
        fcstd_custom = os.path.splitext(out_stl_abs)[0] + ".FCStd"
        save_shape_files(board_flat, "CustomArchSignboard", fcstd_custom, out_stl_abs)
        sys.stdout.flush()
        os._exit(0)

    print("2. Building Part 2: pedestal_feet (flat on Z=0)...")
    feet_plate = build_pedestal_feet_plate()

    print("3. Building Part 3: pillar_flutes_red (flat on Z=0)...")
    flutes_plate = build_pillar_flutes_plate()

    # ==========================================================================
    # ASSEMBLE UPRIGHT IN WORLD COORDINATES (Z_world = standing height 0..60.5mm,
    # X_world = -48..+48mm, Y_world = front-to-back depth -7.4..+7.4mm)
    # ==========================================================================
    board_up = board_flat.copy()
    board_up.rotate(App.Vector(0, 0, 0), App.Vector(1, 0, 0), 90.0)
    board_up.translate(App.Vector(0.0, PILLAR_Z / 2.0, 0.0))

    foot_l = build_single_pedestal_foot()
    foot_l.rotate(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 180.0)
    foot_l.translate(App.Vector(-PILLAR_CX, 0.0, 0.0))

    foot_r = build_single_pedestal_foot()
    foot_r.rotate(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 180.0)
    foot_r.translate(App.Vector(PILLAR_CX, 0.0, 0.0))

    flute_l = build_single_pillar_flute_inlay()
    flute_l.rotate(App.Vector(0, 0, 0), App.Vector(1, 0, 0), 90.0)
    flute_l.translate(App.Vector(-PILLAR_CX, -2.40, 8.40 + FIT_CLEARANCE))

    flute_r = build_single_pillar_flute_inlay()
    flute_r.rotate(App.Vector(0, 0, 0), App.Vector(1, 0, 0), 90.0)
    flute_r.translate(App.Vector(PILLAR_CX, -2.40, 8.40 + FIT_CLEARANCE))

    # ==========================================================================
    # MANDATORY PAIRWISE OPENCASCADE BOOLEAN COLLISION VERIFICATION
    # ==========================================================================
    print("4. Running pairwise OpenCASCADE Boolean collision checks on upright assembly...")
    parts_named = [
        ("arch_signboard", board_up),
        ("foot_left", foot_l),
        ("foot_right", foot_r),
        ("flute_left", flute_l),
        ("flute_right", flute_r),
    ]
    for i in range(len(parts_named)):
        for j in range(i + 1, len(parts_named)):
            n1, s1 = parts_named[i]
            n2, s2 = parts_named[j]
            inter = s1.common(s2)
            print(f"  Collision({n1} vs {n2}) = {inter.Volume:.6f} mm^3")
            assert inter.Volume == 0.0, f"Collision between {n1} and {n2}: {inter.Volume:.6f} mm^3!"
    print("PASS: 0.000000 mm^3 collision across all 10 part pairs!")

    save_shape_files(
        board_flat, "ArchSignboard",
        os.path.join(out_dir, "arch_signboard.FCStd"),
        os.path.join(out_dir, "arch_signboard.stl"),
    )
    save_shape_files(
        feet_plate, "PedestalFeet",
        os.path.join(out_dir, "pedestal_feet.FCStd"),
        os.path.join(out_dir, "pedestal_feet.stl"),
    )
    save_shape_files(
        flutes_plate, "PillarFlutesRed",
        os.path.join(out_dir, "pillar_flutes_red.FCStd"),
        os.path.join(out_dir, "pillar_flutes_red.stl"),
    )

    doc = App.newDocument("BBMPHeritageArchAssembly")
    for pname, pshape in parts_named:
        ft = doc.addObject("Part::Feature", pname)
        ft.Shape = pshape
    doc.recompute()
    doc.saveAs(os.path.join(out_dir, "model.FCStd"))

    asm_mesh = Mesh.Mesh()
    for _, pshape in parts_named:
        for sol in pshape.Solids:
            asm_mesh.addMesh(MeshPart.meshFromShape(Shape=sol, LinearDeflection=0.025, AngularDeflection=0.15, Relative=False))
    asm_mesh.write(os.path.join(out_dir, "model.stl"))
    bb = asm_mesh.BoundBox
    tot_vol_cm3 = sum(s.Volume for _, p in parts_named for s in p.Solids) / 1000.0
    print(f"[Exported] model.FCStd & model.stl | Standing BBox: {bb.XLength:.2f} x {bb.YLength:.2f} x {bb.ZLength:.2f} mm | Total Solid Vol: {tot_vol_cm3:.2f} cm^3 (~{tot_vol_cm3*1.24*0.65:.1f}g PLA)")

    if args.render_previews:
        repo_root = os.path.abspath(os.path.join(out_dir, "..", ".."))
        rv_script = os.path.join(repo_root, "tools", "render_views.py")
        subprocess.run([sys.executable, rv_script, os.path.join(out_dir, "model.stl"), os.path.join(out_dir, "previews", "diagnostic_views.png")], check=True)
        subprocess.run([sys.executable, rv_script, os.path.join(out_dir, "arch_signboard.stl"), os.path.join(out_dir, "previews", "diagnostic_arch_signboard.png")], check=True)
        subprocess.run([sys.executable, rv_script, os.path.join(out_dir, "pedestal_feet.stl"), os.path.join(out_dir, "previews", "diagnostic_pedestal_feet.png")], check=True)
        render_studio_color_preview(out_dir, blank_flat, letters_flat, foot_l, foot_r, flute_l, flute_r)

    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
