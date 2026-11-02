#!/usr/bin/env python3
"""Procedural 3D LEGO Botanicals CAD Engine for The Habit Tracker Tree.

Generates custom modular LEGO Botanicals-inspired habit trees based on:
- Style: 'zen_bonsai', 'sakura', 'ghibli_fruit', 'autumn_maple', 'geometric'
- Piece Count: any integer N in 14..100
- Random Seed: Controls organic variations.

Outputs are written to an untracked output directory:
- output/base_planter.stl
- output/parts/Day_001_....stl ... Day_N_....stl
- output/plates/plate1_....stl ... plateK_....stl
- output/habit_tree_master.step
- output/habit_tree_master.stl
- output/manifest.json
- output/habit_tree_pieces.zip
"""

import sys
import os
import math
import random
import json
import zipfile
import glob

FREECAD_LIB = "/usr/lib/freecad-python3/lib"
if FREECAD_LIB not in sys.path:
    sys.path.append(FREECAD_LIB)

import FreeCAD as App
import Part
import MeshPart
import Mesh

# ---------------------------------------------------------------------------
# LEGO BOTANICALS JOINT & SHAPE PRIMITIVES
# ---------------------------------------------------------------------------
def clean_solid(shape):
    """Retains only the largest primary solid, eliminating any Boolean cut slivers."""
    if len(shape.Solids) > 1:
        return max(shape.Solids, key=lambda s: s.Volume)
    return shape

def make_poly_wire(center, radius, z_offset=0.0, sides=8, rot=0.0):
    """Generates a planar closed polygon wire around center + (0, 0, z_offset)."""
    pts = []
    for i in range(sides):
        th = rot + i * 2.0 * math.pi / sides
        pts.append(App.Vector(center.x + radius * math.cos(th),
                              center.y + radius * math.sin(th),
                              center.z + z_offset))
    pts.append(pts[0])
    return Part.Wire([Part.makeLine(pts[i], pts[i+1]) for i in range(sides)])

def make_star_wire(center, r_outer, r_inner, z_offset=0.0, points=5, rot=0.0):
    """Generates a planar scalloped/star wire for botanical leaf plates and blossoms."""
    pts = []
    n = points * 2
    for i in range(n):
        th = rot + i * math.pi / points
        r = r_outer if (i % 2 == 0) else r_inner
        pts.append(App.Vector(center.x + r * math.cos(th),
                              center.y + r * math.sin(th),
                              center.z + z_offset))
    pts.append(pts[0])
    return Part.Wire([Part.makeLine(pts[i], pts[i+1]) for i in range(n)])

def make_lego_stud(center, r_base=2.1, r_top=1.85, h=1.8, embed=0.4, sides=8, rot=0.0):
    """Creates a tapered, chamfered LEGO-style drop-fit stud from center.z - embed to center.z + h."""
    w_bot = make_poly_wire(center, r_base, -embed, sides=sides, rot=rot)
    w_mid = make_poly_wire(center, r_base, h - 0.35, sides=sides, rot=rot)
    w_top = make_poly_wire(center, r_top, h, sides=sides, rot=rot)
    return Part.makeLoft([w_bot, w_mid, w_top], True, True)

def make_anti_stud_cutter(center, r_base=2.1, h=1.8, clr_radial=0.20, clr_depth=0.25, sides=12):
    """Creates a self-bridging female anti-stud recess with 0.20mm radial slip clearance."""
    r_cut = r_base + clr_radial
    h_cyl = h + clr_depth
    w_bot = make_poly_wire(center, r_cut, -0.25, sides=sides)
    w_mid = make_poly_wire(center, r_cut, h_cyl, sides=sides)
    w_top = make_poly_wire(center, 0.65, h_cyl + 0.55, sides=sides)
    return Part.makeLoft([w_bot, w_mid, w_top], True, True)

def make_bark_brick(p_bot, p_top, r_bot, r_top, sides=8, rot_bot=0.0, rot_top=0.0, lugs=None, with_top_stud=True, with_bot_socket=True):
    """Creates a slender LEGO Botanicals sculpted bark brick from p_bot to p_top."""
    h = p_top.z - p_bot.z
    p_mid = App.Vector((p_bot.x + p_top.x) * 0.5, (p_bot.y + p_top.y) * 0.5, p_bot.z + h * 0.5)
    r_mid = (r_bot + r_top) * 0.52
    w_b = make_poly_wire(p_bot, r_bot, 0.0, sides=sides, rot=rot_bot)
    w_m = make_poly_wire(p_mid, r_mid, 0.0, sides=sides, rot=(rot_bot + rot_top) * 0.5)
    w_t = make_poly_wire(p_top, r_top, 0.0, sides=sides, rot=rot_top)
    body = Part.makeLoft([w_b, w_m, w_t], True, True)

    if lugs:
        h_lug = min(3.6, h * 0.48)
        for az, r_lug in lugs:
            pt_lug = App.Vector(p_top.x + r_lug * math.cos(az),
                                p_top.y + r_lug * math.sin(az),
                                p_top.z)
            pt_lug_bot = App.Vector(p_top.x + (r_top * 0.45) * math.cos(az),
                                    p_top.y + (r_top * 0.45) * math.sin(az),
                                    p_top.z - h_lug)
            w_lb = make_poly_wire(pt_lug_bot, 2.8, 0.0, sides=8, rot=az)
            w_lt = make_poly_wire(pt_lug, 3.6, 0.0, sides=8, rot=az)
            lug_solid = Part.makeLoft([w_lb, w_lt], True, True)
            lug_stud = make_lego_stud(pt_lug, r_base=2.1, r_top=1.85, h=1.8, sides=8, rot=az)
            body = body.fuse(lug_solid).fuse(lug_stud)

    if with_top_stud:
        stud = make_lego_stud(p_top, r_base=2.1, r_top=1.85, h=1.8, sides=8, rot=rot_top)
        body = body.fuse(stud)

    if with_bot_socket:
        cutter = make_anti_stud_cutter(p_bot, r_base=2.1, h=1.8)
        body = clean_solid(body.cut(cutter))

    return clean_solid(body)

def make_root_slope_brick(p_mount, az, r_bot=4.0, r_top=3.4, height=5.2, inward_shift=-0.15, sides=8, with_top_stud=False):
    """Creates a sweeping LEGO Botanicals root-flare slope brick that hugs the trunk base."""
    p_bot = App.Vector(p_mount.x, p_mount.y, p_mount.z)
    p_mid = App.Vector(p_mount.x - inward_shift * 0.55 * math.cos(az),
                       p_mount.y - inward_shift * 0.55 * math.sin(az),
                       p_mount.z + height * 0.5)
    p_top = App.Vector(p_mount.x - inward_shift * math.cos(az),
                       p_mount.y - inward_shift * math.sin(az),
                       p_mount.z + height)
    w_b = make_poly_wire(p_bot, r_bot, 0.0, sides=sides, rot=az)
    w_m = make_poly_wire(p_mid, (r_bot + r_top) * 0.52, 0.0, sides=sides, rot=az)
    w_t = make_poly_wire(p_top, r_top, 0.0, sides=sides, rot=az)
    body = Part.makeLoft([w_b, w_m, w_t], True, True)
    if with_top_stud:
        body = body.fuse(make_lego_stud(p_top, r_base=2.1, r_top=1.85, h=1.8, sides=8, rot=az))
    cutter = make_anti_stud_cutter(p_mount, r_base=2.1, h=1.8)
    return clean_solid(body.cut(cutter)), p_top

def make_lego_branch(p_bot, p_top, r_collar_bot=3.6, r_collar_top=3.8, r_shaft=3.1, sides=8):
    """Creates a sturdy, compact LEGO Botanicals limb strictly inside p_bot.z <= Z <= p_top.z (+ top stud)."""
    p_mid = App.Vector((p_bot.x + p_top.x) * 0.5, (p_bot.y + p_top.y) * 0.5, (p_bot.z + p_top.z) * 0.5)
    w1 = make_poly_wire(p_bot, r_collar_bot, 0.0, sides=sides)
    w2 = make_poly_wire(p_mid, r_shaft, 0.0, sides=sides)
    w3 = make_poly_wire(p_top, r_collar_top, 0.0, sides=sides)
    body = Part.makeLoft([w1, w2, w3], True, True)
    stud = make_lego_stud(p_top, r_base=2.1, r_top=1.85, h=1.8, sides=8)
    body = body.fuse(stud)
    cutter = make_anti_stud_cutter(p_bot, r_base=2.1, h=1.8)
    return clean_solid(body.cut(cutter))

def make_lego_leaf_plate(style, center, radius=13.5, height=3.5, stud_offsets=None, with_center_stud=False, is_accent=False, add_deco_studs=True, rot_offset=0.0):
    """Creates a wide, lush LEGO Botanicals leaf plate / blossom / fruit / crystal with visible top studs."""
    if style == "sakura":
        w_b = make_poly_wire(center, max(3.6, radius * 0.58), 0.0, sides=10, rot=rot_offset)
        w_m = make_star_wire(center, radius * 1.06, radius * 0.76, height * 0.55, points=5, rot=0.2 + rot_offset)
        w_t = make_star_wire(center, radius * 0.96, radius * 0.74, height, points=5, rot=0.2 + rot_offset)
        body = Part.makeLoft([w_b, w_m, w_t], True, True)
    elif style == "autumn_maple":
        w_b = make_poly_wire(center, max(3.6, radius * 0.58), 0.0, sides=14, rot=rot_offset)
        w_m = make_star_wire(center, radius * 1.08, radius * 0.70, height * 0.52, points=7, rot=0.1 + rot_offset)
        w_t = make_star_wire(center, radius * 0.95, radius * 0.70, height, points=7, rot=0.1 + rot_offset)
        body = Part.makeLoft([w_b, w_m, w_t], True, True)
    elif style == "ghibli_fruit" and is_accent:
        # Plump faceted Ghibli apple with top LEGO studs
        w_b = make_poly_wire(center, max(3.5, radius * 0.68), 0.0, sides=8, rot=rot_offset)
        w_m = make_poly_wire(center, radius * 1.05, height * 0.55, sides=8, rot=math.pi/8 + rot_offset)
        w_t = make_poly_wire(center, radius * 0.72, height, sides=8, rot=rot_offset)
        body = Part.makeLoft([w_b, w_m, w_t], True, True)
    elif style == "geometric":
        w_b = make_poly_wire(center, max(3.6, radius * 0.64), 0.0, sides=6, rot=rot_offset)
        w_m = make_poly_wire(center, radius * 1.05, height * 0.52, sides=6, rot=math.pi/6 + rot_offset)
        w_t = make_poly_wire(center, radius * 0.88, height, sides=6, rot=rot_offset)
        body = Part.makeLoft([w_b, w_m, w_t], True, True)
    else: # zen_bonsai or ghibli_fruit leaf plate
        w_b = make_poly_wire(center, max(3.6, radius * 0.64), 0.0, sides=16, rot=rot_offset)
        w_m = make_star_wire(center, radius * 1.05, radius * 0.90, height * 0.55, points=8, rot=rot_offset)
        w_t = make_star_wire(center, radius * 0.96, radius * 0.86, height, points=8, rot=rot_offset)
        body = Part.makeLoft([w_b, w_m, w_t], True, True)

    if stud_offsets:
        for dx, dy in stud_offsets:
            s_pt = App.Vector(center.x + dx, center.y + dy, center.z + height)
            body = body.fuse(make_lego_stud(s_pt, r_base=2.1, r_top=1.85, h=1.8, sides=8))

    if with_center_stud:
        c_pt = App.Vector(center.x, center.y, center.z + height)
        body = body.fuse(make_lego_stud(c_pt, r_base=2.1, r_top=1.85, h=1.8, sides=8))
    elif add_deco_studs and not stud_offsets and radius >= 5.0:
        # Add 3 decorative LEGO studs on top of upper leaf/blossom rosettes
        r_deco = radius * 0.45
        for m_i in range(3):
            a_d = m_i * 2.0 * math.pi / 3.0 + 0.4 + rot_offset
            d_pt = App.Vector(center.x + r_deco * math.cos(a_d), center.y + r_deco * math.sin(a_d), center.z + height)
            body = body.fuse(make_lego_stud(d_pt, r_base=1.6, r_top=1.4, h=1.2, embed=0.3, sides=8))

    cutter = make_anti_stud_cutter(center, r_base=2.1, h=1.8)
    return clean_solid(body.cut(cutter))

# ---------------------------------------------------------------------------
# MAIN PROCEDURAL LEGO BOTANICALS GENERATION ENGINE
# ---------------------------------------------------------------------------
def generate_habit_tree(style="zen_bonsai", piece_count=30, seed=42, output_dir=None):
    """Procedurally generates a complete, 100% physically connected LEGO Botanicals 3D Habit Tracker Tree."""
    random.seed(seed)
    if output_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(base_dir, "output")

    parts_dir = os.path.join(output_dir, "parts")
    plates_dir = os.path.join(output_dir, "plates")
    os.makedirs(parts_dir, exist_ok=True)
    os.makedirs(plates_dir, exist_ok=True)

    # Clean previous run STLs
    for old_file in glob.glob(os.path.join(parts_dir, "*.stl")):
        try: os.remove(old_file)
        except OSError: pass
    for old_file in glob.glob(os.path.join(plates_dir, "*.stl")):
        try: os.remove(old_file)
        except OSError: pass

    print(f"=== GENERATING LEGO BOTANICALS HABIT TREE (Style: {style}, Pieces: {piece_count}, Seed: {seed}) ===")

    # 1. Distribute pieces across Zones: Trunk, Branches, Canopy (continuous for any N in 14..100)
    n_total = max(14, min(100, int(piece_count)))

    if n_total <= 22:
        n_spine = 4
        extra_trunk_stacks = []
        n_primary_boughs = 3
        n_secondary_twigs = 0
        n_tertiary_twigs = 0
        n_outer_pads = 3
        rem_canopy = n_total - 8
        n_crown = 3 if n_total == 14 else 2
        rem_pads = rem_canopy - n_crown
    elif n_total <= 38:
        n_spine = 5
        extra_trunk_stacks = [1, 1, 1] # 5 + 3 root-flare slopes = 8 trunk pieces
        n_primary_boughs = 4
        n_secondary_twigs = 3
        n_tertiary_twigs = 0
        n_outer_pads = 4
        rem_canopy = n_total - 16
        n_crown = 2
        rem_pads = rem_canopy - n_crown
    elif n_total <= 64:
        n_spine = 6
        extra_trunk_stacks = [2, 2, 2] # 6 + 6 root/buttress bricks = 12 trunk pieces
        n_primary_boughs = 7
        n_secondary_twigs = 6
        n_tertiary_twigs = 0
        n_outer_pads = 7
        rem_canopy = n_total - 26
        n_crown = 3
        rem_pads = rem_canopy - n_crown
    else: # 65..100
        n_spine = 7
        extra_trunk_stacks = [3, 3, 3, 3, 3, 3] # 7 + 18 root/secondary-stem bricks = 25 trunk pieces
        n_primary_boughs = 8
        n_secondary_twigs = 8
        n_tertiary_twigs = 8
        n_outer_pads = 8
        rem_canopy = n_total - 50
        n_crown = max(2, rem_canopy - 40)
        rem_pads = rem_canopy - n_crown

    p_base = rem_pads // n_outer_pads
    p_extra = rem_pads % n_outer_pads
    pad_sizes = [p_base + (1 if idx < p_extra else 0) for idx in range(n_outer_pads)]

    # Palettes
    style_palettes = {
        "zen_bonsai": { "base": "#2A2E33", "trunk": "#4E3629", "branch": "#6E4D36", "canopy": "#2E5D3F", "accent": "#73A96C" },
        "sakura": { "base": "#32353B", "trunk": "#3D271E", "branch": "#5A3D31", "canopy": "#F4A6BA", "accent": "#E85D75" },
        "ghibli_fruit": { "base": "#2B3A2C", "trunk": "#543D2B", "branch": "#7A583E", "canopy": "#4C8C4A", "accent": "#E63946" },
        "autumn_maple": { "base": "#2C2D30", "trunk": "#3A281E", "branch": "#523728", "canopy": "#E06D28", "accent": "#C1292E" },
        "geometric": { "base": "#1F2421", "trunk": "#495054", "branch": "#6C757D", "canopy": "#2A9D8F", "accent": "#E76F51" }
    }
    palette = style_palettes.get(style, style_palettes["zen_bonsai"])

    all_solids = {}
    parent_map = {}

    # -----------------------------------------------------------------------
    # 2. BUILD COMPACT LEGO BOTANICALS BASE PLANTER
    # -----------------------------------------------------------------------
    h_base = 13.5
    z_deck = 11.0
    sides_pot = 16 if style in ["zen_bonsai", "sakura", "ghibli_fruit"] else 8
    rx_b, ry_b = (38.0, 32.0) if style == "zen_bonsai" else (36.0, 36.0)
    pts_b, pts_t = [], []
    for i in range(sides_pot):
        th = i * 2.0 * math.pi / sides_pot + (math.pi / sides_pot if sides_pot == 8 else 0)
        pts_b.append(App.Vector(rx_b * 0.86 * math.cos(th), ry_b * 0.86 * math.sin(th), 0))
        pts_t.append(App.Vector(rx_b * math.cos(th), ry_b * math.sin(th), h_base))
    pts_b.append(pts_b[0]); pts_t.append(pts_t[0])
    wb = Part.Wire([Part.makeLine(pts_b[i], pts_b[i+1]) for i in range(sides_pot)])
    wt = Part.Wire([Part.makeLine(pts_t[i], pts_t[i+1]) for i in range(sides_pot)])
    base_solid = Part.makeLoft([wb, wt], True, True)

    # Recess soil bed to z_deck = 11.0
    pts_cut_b, pts_cut_t = [], []
    for i in range(sides_pot):
        th = i * 2.0 * math.pi / sides_pot + (math.pi / sides_pot if sides_pot == 8 else 0)
        pts_cut_b.append(App.Vector((rx_b - 3.8) * math.cos(th), (ry_b - 3.8) * math.sin(th), z_deck))
        pts_cut_t.append(App.Vector((rx_b - 3.4) * math.cos(th), (ry_b - 3.4) * math.sin(th), h_base + 1.0))
    pts_cut_b.append(pts_cut_b[0]); pts_cut_t.append(pts_cut_t[0])
    wcb = Part.Wire([Part.makeLine(pts_cut_b[i], pts_cut_b[i+1]) for i in range(sides_pot)])
    wct = Part.Wire([Part.makeLine(pts_cut_t[i], pts_cut_t[i+1]) for i in range(sides_pot)])
    soil_recess = Part.makeLoft([wcb, wct], True, True)
    base_solid = clean_solid(base_solid.cut(soil_recess))

    # Decorative LEGO 1x1 round pebble studs on outer soil ring
    for i in range(12):
        th_p = i * 2.0 * math.pi / 12.0 + 0.15
        r_px = (rx_b - 6.8) * math.cos(th_p)
        r_py = (ry_b - 6.8) * math.sin(th_p)
        pebble = make_lego_stud(App.Vector(r_px, r_py, z_deck), r_base=2.0, r_top=1.8, h=1.3, embed=0.3, sides=8)
        base_solid = base_solid.fuse(pebble)

    # Central spine mounting stud on planter deck
    base_solid = base_solid.fuse(make_lego_stud(App.Vector(0, 0, z_deck), r_base=2.1, r_top=1.85, h=1.8, sides=8))

    # Sample organic seed parameters (guaranteed collision-free across all 5 styles and durations)
    sway_az = random.uniform(0.0, 2.0 * math.pi)
    sway_flip = random.choice([-1.0, 1.0])
    sway_scale = random.uniform(0.80, 1.15)
    root_az_offset = random.uniform(0.0, 2.0 * math.pi)
    bough_az_offset = random.uniform(0.0, 2.0 * math.pi)
    fork_sign = random.choice([-1.0, 1.0])

    # Root-flare mounting studs snug around the trunk base (r = 12.6 mm)
    n_root_stacks = len(extra_trunk_stacks)
    root_base_pts = []
    r_root_ring = 12.6
    for r_i in range(n_root_stacks):
        az_r = r_i * 2.0 * math.pi / n_root_stacks + root_az_offset
        pt_r = App.Vector(r_root_ring * math.cos(az_r), r_root_ring * math.sin(az_r), z_deck)
        base_solid = base_solid.fuse(make_lego_stud(pt_r, r_base=2.1, r_top=1.85, h=1.8, sides=8))
        root_base_pts.append((pt_r, az_r))

    base_solid = clean_solid(base_solid)
    all_solids["BasePlanter"] = base_solid

    # -----------------------------------------------------------------------
    # 3. BUILD SLENDER STYLE-SPECIFIC TRUNK SPINE & SNUG ROOT-FLARE SLOPES
    # -----------------------------------------------------------------------
    day_idx = 1
    h_spine_brick = 7.2
    spine_pts = []
    spine_rads = []
    spine_rots = []

    for k in range(n_spine + 1):
        t = k / float(n_spine)
        z_k = z_deck + k * h_spine_brick
        # Keep k=0, 1 centered near (0,0) so root-flare bricks at r=12.6mm hug the base cleanly without colliding
        t_sway = max(0.0, (t - 0.20) / 0.80)
        if style == "zen_bonsai":
            xk_raw = 6.2 * math.sin(1.4 * math.pi * t_sway)
            yk_raw = 2.0 * math.sin(0.9 * math.pi * t_sway)
            rk = 6.8 * (1.0 - 0.34 * t)
            rot_k = 0.2 * t + sway_az * 0.25
        elif style == "sakura":
            xk_raw = 5.2 * (1.0 - math.cos(0.6 * math.pi * t_sway))
            yk_raw = 2.6 * math.sin(math.pi * t_sway)
            rk = 6.2 * (1.0 - 0.32 * t)
            rot_k = k * 0.42 * sway_flip + sway_az * 0.25
        elif style == "ghibli_fruit":
            xk_raw = 2.8 * math.sin(math.pi * t_sway)
            yk_raw = 1.4 * math.sin(0.8 * math.pi * t_sway)
            if k == 0: rk = 7.5
            elif k == 1: rk = 7.8
            else: rk = max(4.5, 6.4 - (k - 1) * 0.42)
            rot_k = 0.1 * k * sway_flip + sway_az * 0.25
        elif style == "autumn_maple":
            xk_raw = 5.8 * (t_sway ** 1.15)
            yk_raw = 2.0 * math.sin(math.pi * t_sway)
            rk = 6.3 * (1.0 - 0.32 * t)
            rot_k = 0.25 * k * sway_flip + sway_az * 0.25
        else: # geometric
            xk_raw = 4.0 * math.sin(1.3 * math.pi * t_sway)
            yk_raw = 1.8 * math.sin(0.9 * math.pi * t_sway)
            rk = 6.6 * (1.0 - 0.34 * t)
            rot_k = (k % 2) * (math.pi / 6.0) + sway_az
        sx = xk_raw * sway_scale
        sy = yk_raw * sway_flip * sway_scale
        xk = sx * math.cos(sway_az) - sy * math.sin(sway_az)
        yk = sx * math.sin(sway_az) + sy * math.cos(sway_az)
        spine_pts.append(App.Vector(xk, yk, z_k))
        spine_rads.append(max(4.4, rk))
        spine_rots.append(rot_k)

    # Assign primary boughs across top two spine bricks
    lower_bough_lugs = []
    upper_bough_lugs = []
    primary_mount_info = []
    r_lug_offset = 8.8

    for b_i in range(n_primary_boughs):
        az = b_i * 2.0 * math.pi / n_primary_boughs + bough_az_offset
        if n_primary_boughs == 3 or (b_i % 2 == 1 and not (n_primary_boughs == 4 and b_i == 3)):
            top_pt = spine_pts[n_spine]
            upper_bough_lugs.append((az, r_lug_offset))
            pt_m = App.Vector(top_pt.x + r_lug_offset * math.cos(az),
                              top_pt.y + r_lug_offset * math.sin(az),
                              top_pt.z)
            primary_mount_info.append((n_spine - 1, pt_m, az, True))
        else:
            top_pt = spine_pts[n_spine - 1]
            lower_bough_lugs.append((az, r_lug_offset))
            pt_m = App.Vector(top_pt.x + r_lug_offset * math.cos(az),
                              top_pt.y + r_lug_offset * math.sin(az),
                              top_pt.z)
            primary_mount_info.append((n_spine - 2, pt_m, az, False))

    spine_names = []
    sides_trunk = 6 if style == "geometric" else 8
    for k in range(n_spine):
        name = f"Day_{day_idx:03d}_Trunk_Spine_S{k+1}"
        lugs = None
        if k == n_spine - 2 and lower_bough_lugs:
            lugs = lower_bough_lugs
        elif k == n_spine - 1 and upper_bough_lugs:
            lugs = upper_bough_lugs
        brick = make_bark_brick(
            spine_pts[k], spine_pts[k+1],
            spine_rads[k], spine_rads[k+1],
            sides=sides_trunk, rot_bot=spine_rots[k], rot_top=spine_rots[k+1],
            lugs=lugs, with_top_stud=True, with_bot_socket=True
        )
        all_solids[name] = brick
        parent_map[name] = "BasePlanter" if k == 0 else spine_names[-1]
        spine_names.append(name)
        day_idx += 1

    # Build Snug Root-Flare Slopes & Secondary Buttress Bricks around Trunk Base
    for s_idx, stack_len in enumerate(extra_trunk_stacks):
        pt_curr, az_r = root_base_pts[s_idx]
        prev_r_name = "BasePlanter"
        for l_i in range(stack_len):
            has_next = (l_i < stack_len - 1)
            role = "TwinStem" if (style == "autumn_maple" and s_idx % 2 == 0) else "RootFlare"
            name = f"Day_{day_idx:03d}_Trunk_{role}_{s_idx+1}_{l_i+1}"
            inward = -0.8 if role == "TwinStem" else -0.15
            r_b = max(3.5, 4.1 - l_i * 0.25)
            r_t = max(3.4, 3.7 - l_i * 0.25) if has_next else 2.2
            r_brick, pt_next = make_root_slope_brick(
                pt_curr, az_r, r_bot=r_b, r_top=r_t, height=5.2,
                inward_shift=inward, sides=sides_trunk, with_top_stud=has_next
            )
            all_solids[name] = r_brick
            parent_map[name] = prev_r_name
            prev_r_name = name
            pt_curr = pt_next
            day_idx += 1

    # -----------------------------------------------------------------------
    # 4. BUILD COMPACT, STURDY LEGO BRANCH SKELETON
    # -----------------------------------------------------------------------
    primary_branch_names = []
    primary_branch_tips = []

    for i in range(n_primary_boughs):
        spine_idx, pb, az, is_upper = primary_mount_info[i]
        has_sec = (i < n_secondary_twigs)
        reach_jitter = random.uniform(0.95, 1.06)
        if not has_sec and n_secondary_twigs > 0:
            # Primary-only bough (e.g. b_i=3 in B2 or b_i=6 in B3) reaches further out on the lower tier
            step_p = 17.2 * reach_jitter
            dz_p = 4.5
        elif is_upper:
            step_p = 11.5 * reach_jitter
            dz_p = 10.5 if n_secondary_twigs > 0 else 7.5
        else:
            step_p = 11.5 * reach_jitter
            dz_p = 8.0
        pt = App.Vector(pb.x + step_p * math.cos(az),
                        pb.y + step_p * math.sin(az),
                        pb.z + dz_p)
        name = f"Day_{day_idx:03d}_Branch_Primary_B{i+1}"
        b_solid = make_lego_branch(pb, pt, r_collar_bot=3.5, r_collar_top=3.7, r_shaft=3.0, sides=8)
        all_solids[name] = b_solid
        parent_map[name] = spine_names[spine_idx]
        primary_branch_names.append(name)
        primary_branch_tips.append((pt, az, is_upper))
        day_idx += 1

    # Reserve day_idx for Center Leader Bough (built right after branch endpoints so we know exact max tip height)
    day_center = day_idx
    name_center = f"Day_{day_center:03d}_Branch_Center_Leader"
    day_idx += 1

    # Secondary Twigs (1:1 from Primary Boughs)
    used_primary_indices = set()
    secondary_branch_names = []
    secondary_branch_tips = []

    for i in range(n_secondary_twigs):
        p_idx = i
        used_primary_indices.add(p_idx)
        parent_b_name = primary_branch_names[p_idx]
        pb_s, az_p, is_upper = primary_branch_tips[p_idx]
        az_s = az_p + fork_sign * random.uniform(0.12, 0.18)
        step_sec = (9.0 if n_tertiary_twigs > 0 else 10.5) * random.uniform(0.95, 1.05)
        dz_s = 10.0 if is_upper else 7.5
        pt_s = App.Vector(pb_s.x + step_sec * math.cos(az_s),
                          pb_s.y + step_sec * math.sin(az_s),
                          pb_s.z + dz_s)
        name = f"Day_{day_idx:03d}_Branch_Secondary_T{i+1}"
        b_sec = make_lego_branch(pb_s, pt_s, r_collar_bot=3.5, r_collar_top=3.7, r_shaft=2.8, sides=8)
        all_solids[name] = b_sec
        parent_map[name] = parent_b_name
        secondary_branch_names.append(name)
        secondary_branch_tips.append((pt_s, az_s, is_upper))
        day_idx += 1

    # Tertiary Twigs (1:1 from Secondary Twigs when n_tertiary_twigs > 0)
    branch_endpoints = []
    if n_tertiary_twigs > 0:
        for i in range(n_tertiary_twigs):
            parent_sec_name = secondary_branch_names[i]
            pb_t, az_s, is_upper = secondary_branch_tips[i]
            az_t = az_s + fork_sign * random.uniform(0.10, 0.15)
            step_ter = 8.5 * random.uniform(0.95, 1.05)
            dz_t = 7.5 if is_upper else 6.0
            pt_t = App.Vector(pb_t.x + step_ter * math.cos(az_t),
                              pb_t.y + step_ter * math.sin(az_t),
                              pb_t.z + dz_t)
            name = f"Day_{day_idx:03d}_Branch_Tertiary_U{i+1}"
            b_ter = make_lego_branch(pb_t, pt_t, r_collar_bot=3.4, r_collar_top=3.6, r_shaft=2.6, sides=8)
            all_solids[name] = b_ter
            parent_map[name] = parent_sec_name
            branch_endpoints.append((pt_t, name, az_t))
            day_idx += 1
    else:
        for idx in range(len(secondary_branch_names)):
            pt_s, az_s, _ = secondary_branch_tips[idx]
            branch_endpoints.append((pt_s, secondary_branch_names[idx], az_s))
        for p_idx in range(n_primary_boughs):
            if p_idx not in used_primary_indices:
                pt_p, az_p, _ = primary_branch_tips[p_idx]
                branch_endpoints.append((pt_p, primary_branch_names[p_idx], az_p))

    # Build Center Leader Bough so its top is guaranteed >= 12.6 mm above the highest outer branch tip
    pb_c = spine_pts[n_spine]
    max_tip_z = max(ep[0].z for ep in branch_endpoints)
    pt_c = App.Vector(pb_c.x, pb_c.y, max(pb_c.z + 10.0, max_tip_z + 12.6))
    b_center = make_lego_branch(pb_c, pt_c, r_collar_bot=3.8, r_collar_top=4.2, r_shaft=3.3, sides=8)
    all_solids[name_center] = b_center
    parent_map[name_center] = spine_names[-1]

    # -----------------------------------------------------------------------
    # 5. BUILD LUSH, WIDE LEGO BOTANICALS FOLIAGE PADS & STUD-MOUNTED ROSETTES
    # -----------------------------------------------------------------------
    for pad_idx in range(n_outer_pads):
        tip_pos, b_parent_name, az = branch_endpoints[pad_idx % len(branch_endpoints)]
        p_count = pad_sizes[pad_idx]

        # 3 top studs arranged at 120 deg on the wide Base Leaf Plate at r = 6.8 mm with organic seed rotation & shuffle
        stud_r = 6.8
        pad_rot = random.uniform(0.0, 2.0 * math.pi)
        pad_stud_az = az + random.uniform(-0.38, 0.38)
        sub_stud_angles = [pad_stud_az, pad_stud_az + 2.0 * math.pi / 3.0, pad_stud_az + 4.0 * math.pi / 3.0]
        stud_offsets = [(stud_r * math.cos(a), stud_r * math.sin(a)) for a in sub_stud_angles]
        random.shuffle(stud_offsets)

        name_p1 = f"Day_{day_idx:03d}_Foliage_Cluster{pad_idx+1}_Base"
        h_plate = 3.5
        c1 = make_lego_leaf_plate(
            style, tip_pos, radius=13.2, height=h_plate,
            stud_offsets=stud_offsets, with_center_stud=False, is_accent=False,
            rot_offset=pad_rot
        )
        all_solids[name_p1] = c1
        parent_map[name_p1] = b_parent_name
        day_idx += 1

        tier_names = [name_p1]
        for t_idx in range(1, p_count):
            name_pt = f"Day_{day_idx:03d}_Foliage_Cluster{pad_idx+1}_Tier{chr(64+t_idx)}"
            sub_rot = random.uniform(0.0, 2.0 * math.pi)
            if t_idx <= 3:
                dx, dy = stud_offsets[t_idx - 1]
                pt_sub = App.Vector(tip_pos.x + dx, tip_pos.y + dy, tip_pos.z + h_plate)
                sub_solid = make_lego_leaf_plate(
                    style, pt_sub, radius=5.2, height=3.4,
                    stud_offsets=None, with_center_stud=(t_idx == 1), is_accent=(t_idx >= 2),
                    add_deco_studs=(t_idx != 1), rot_offset=sub_rot
                )
                all_solids[name_pt] = sub_solid
                parent_map[name_pt] = name_p1
            else:
                dx, dy = stud_offsets[0]
                pt_top = App.Vector(tip_pos.x + dx, tip_pos.y + dy, tip_pos.z + h_plate + 3.4)
                top_solid = make_lego_leaf_plate(
                    style, pt_top, radius=5.2, height=3.4,
                    stud_offsets=None, with_center_stud=False, is_accent=True,
                    add_deco_studs=True, rot_offset=sub_rot
                )
                all_solids[name_pt] = top_solid
                parent_map[name_pt] = tier_names[1]
            tier_names.append(name_pt)
            day_idx += 1

    # Central Crown Canopy Dome
    prev_crown_name = name_center
    curr_z_crown = pt_c.z
    for c_idx in range(n_crown):
        is_apex = (c_idx == n_crown - 1)
        name_crown = f"Day_{day_idx:03d}_Crown_Apex" if is_apex else f"Day_{day_idx:03d}_Crown_Tier{c_idx+1}"
        h_tier = 3.6
        rad = 6.8 if is_apex else max(7.5, 13.8 - c_idx * 0.85)
        pt_tier = App.Vector(pt_c.x, pt_c.y, curr_z_crown)
        c_shape = make_lego_leaf_plate(
            style, pt_tier, radius=rad, height=h_tier,
            stud_offsets=None, with_center_stud=(not is_apex), is_accent=is_apex, add_deco_studs=is_apex,
            rot_offset=random.uniform(0.0, 2.0 * math.pi)
        )
        all_solids[name_crown] = c_shape
        parent_map[name_crown] = prev_crown_name
        prev_crown_name = name_crown
        curr_z_crown += h_tier
        day_idx += 1

    # Build all_pieces list
    all_pieces = []
    for name, shape in all_solids.items():
        if name == "BasePlanter":
            continue
        day = int(name[4:7])
        zone = "trunk" if "Trunk" in name else ("branch" if "Branch" in name else "canopy")
        is_accent = ("Apex" in name) or ("TierB" in name) or ("TierC" in name) or ("TierD" in name)
        col = palette["accent"] if is_accent else (palette["canopy"] if zone == "canopy" else (palette["branch"] if zone == "branch" else palette["trunk"]))
        all_pieces.append((day, zone, name, shape, col))

    all_pieces.sort(key=lambda p: p[0])

    # -----------------------------------------------------------------------
    # 6. PHYSICAL AUDIT (Connectivity, Manifoldness, Collisions)
    # -----------------------------------------------------------------------
    print(f"\n--- AUDIT: 1 Base + {len(all_pieces)} Habit Pieces = {len(all_solids)} Solids ---")

    # Check manifolds
    for name, s in all_solids.items():
        assert s.isValid(), f"CAD FATAL: {name} is not a valid solid!"
        assert len(s.Solids) == 1, f"CAD FATAL: {name} contains {len(s.Solids)} sub-solids!"
        assert s.Volume > 15.0, f"CAD FATAL: {name} has abnormal volume {s.Volume:.2f} mm³"
    print("  Manifold Audit: PASSED! 100% of bodies are valid closed manifold solids.")

    # Check physical connectivity (dist <= 0.05 mm)
    max_gap = 0.0
    for child, parent in parent_map.items():
        s_c = all_solids[child]
        s_p = all_solids[parent] if parent in all_solids else base_solid
        dist = s_c.distToShape(s_p)[0]
        if dist > max_gap:
            max_gap = dist
        assert dist <= 0.05, f"FLOATING PART DETECTED: {child} is {dist:.4f} mm away from parent {parent}!"
    print(f"  Physical Connectivity Check: PASSED! 100% of parts touch their parents (Max gap: {max_gap:.6f} mm)")

    # Collision detection audit (pre-cache BoundBox once per solid)
    raw_solids = [("BasePlanter", base_solid)] + [(p[2], p[3]) for p in all_pieces]
    solids_list = [(n_s, s_obj, s_obj.BoundBox) for n_s, s_obj in raw_solids]
    collision_count = 0
    max_overlap = 0.0
    for i in range(len(solids_list)):
        n_i, s_i, bb_i = solids_list[i]
        for j in range(i + 1, len(solids_list)):
            n_j, s_j, bb_j = solids_list[j]
            if bb_i.intersect(bb_j):
                try:
                    c_vol = s_i.common(s_j).Volume
                    if c_vol > max_overlap:
                        max_overlap = c_vol
                    if c_vol > 0.08:
                        collision_count += 1
                        print(f"  [COLLISION] {n_i} and {n_j}: overlap = {c_vol:.3f} mm³")
                except Exception:
                    pass
    assert collision_count == 0, f"Collision check failed! Detected {collision_count} colliding part pairs!"
    print(f"  Collision Clearance Check: PASSED! Zero collisions detected (Max overlap: {max_overlap:.6f} mm³)")

    # -----------------------------------------------------------------------
    # 7. EXPORT STLs, STEP, AND MANIFEST
    # -----------------------------------------------------------------------
    manifest_parts = []
    piece_meshes = {}
    piece_bbs = {}

    # Save base planter
    base_stl = os.path.join(output_dir, "base_planter.stl")
    mesh_base = MeshPart.meshFromShape(base_solid, LinearDeflection=0.08, AngularDeflection=0.15)
    mesh_base.write(base_stl)

    # Save piece STLs and cache meshes + bounding boxes
    for day, zone, name, shape, col in all_pieces:
        stl_path = os.path.join(parts_dir, f"{name}.stl")
        mesh = MeshPart.meshFromShape(shape, LinearDeflection=0.08, AngularDeflection=0.15)
        mesh.write(stl_path)
        bb = shape.BoundBox
        piece_meshes[name] = mesh
        piece_bbs[name] = bb
        manifest_parts.append({
            "day": day,
            "zone": zone,
            "name": name,
            "filename": f"parts/{name}.stl",
            "color": col,
            "dimensions": {"x": round(bb.XLength, 2), "y": round(bb.YLength, 2), "z": round(bb.ZLength, 2)}
        })

    # Save master assembly STEP & STL
    master_doc = App.newDocument("HabitTreeMaster")
    ob_base = master_doc.addObject("Part::Feature", "BasePlanter")
    ob_base.Shape = base_solid
    export_objs = [ob_base]
    full_mesh = Mesh.Mesh()
    full_mesh.addMesh(mesh_base)

    for day, zone, name, shape, col in all_pieces:
        ob = master_doc.addObject("Part::Feature", name)
        ob.Shape = shape
        export_objs.append(ob)
        full_mesh.addMesh(piece_meshes[name])

    master_doc.recompute()
    master_step = os.path.join(output_dir, "habit_tree_master.step")
    master_stl = os.path.join(output_dir, "habit_tree_master.stl")
    Part.export(export_objs, master_step)
    full_mesh.write(master_stl)

    # Build print plates using cached meshes (all pieces sit flat on Z=0 with studs facing up!)
    manifest_plates = []
    def make_plate(items, plate_name, center_mesh=None):
        out_mesh = Mesh.Mesh()
        if center_mesh is not None:
            out_mesh.addMesh(center_mesh)
        n = len(items)
        cols = int(math.ceil(math.sqrt(n)))
        spacing = 30.0
        x_start = -((cols - 1) * spacing) / 2.0
        y_start = -((math.ceil(n / cols) - 1) * spacing) / 2.0
        for idx, (p_name, _) in enumerate(items):
            row = idx // cols
            col = idx % cols
            m_copy = piece_meshes[p_name].copy()
            bb = piece_bbs[p_name]
            cx = (bb.XMin + bb.XMax) / 2.0
            cy = (bb.YMin + bb.YMax) / 2.0
            if center_mesh is not None:
                th_p = idx * 2.0 * math.pi / n
                r_p = 64.0
                dx = -cx + r_p * math.cos(th_p)
                dy = -cy + r_p * math.sin(th_p)
            else:
                dx = -cx + x_start + col * spacing
                dy = -cy + y_start + row * spacing
            dz = -bb.ZMin
            mat = App.Matrix()
            mat.move(App.Vector(dx, dy, dz))
            m_copy.transform(mat)
            out_mesh.addMesh(m_copy)
        p_filename = f"{plate_name}.stl"
        p_path = os.path.join(plates_dir, p_filename)
        out_mesh.write(p_path)
        bb = out_mesh.BoundBox
        manifest_plates.append({
            "name": plate_name,
            "filename": f"plates/{p_filename}",
            "parts_count": n + (1 if center_mesh else 0),
            "dimensions": f"{bb.XLength:.1f} x {bb.YLength:.1f} x {bb.ZLength:.1f} mm"
        })

    trunk_items = [(p[2], p[3]) for p in all_pieces if p[1] == "trunk"]
    branch_items = [(p[2], p[3]) for p in all_pieces if p[1] == "branch"]
    canopy_items = [(p[2], p[3]) for p in all_pieces if p[1] == "canopy"]

    make_plate(trunk_items, "plate1_base_and_trunk", center_mesh=mesh_base)
    make_plate(branch_items, "plate2_branches")
    make_plate(canopy_items, "plate3_canopy")

    # ZIP All Pieces
    zip_path = os.path.join(output_dir, "habit_tree_pieces.zip")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(base_stl, arcname="base_planter.stl")
        for day, zone, name, shape, col in all_pieces:
            p_stl = os.path.join(parts_dir, f"{name}.stl")
            zipf.write(p_stl, arcname=f"parts/{name}.stl")

    total_vol = base_solid.Volume + sum(p[3].Volume for p in all_pieces)
    est_mass = (total_vol / 1000.0) * 0.45

    manifest = {
        "style": style,
        "piece_count": len(all_pieces),
        "seed": seed,
        "total_volume_cm3": round(total_vol / 1000.0, 2),
        "estimated_mass_grams": round(est_mass, 1),
        "palette": palette,
        "plates": manifest_plates,
        "parts": manifest_parts
    }

    manifest_path = os.path.join(output_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"=== GENERATION COMPLETE: {len(all_pieces)} pieces exported to {output_dir} ===")
    return manifest

if __name__ == "__main__":
    style = sys.argv[1] if len(sys.argv) > 1 else "zen_bonsai"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 42
    generate_habit_tree(style=style, piece_count=count, seed=seed)
