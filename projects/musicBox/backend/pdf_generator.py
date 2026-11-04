"""True-scale 1:1 millimeter A4 multi-strip PDF and SVG generator for Kikkerland 15-Note Music Box."""

import io
import math
from typing import List, Dict
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors

from backend.kikkerland import (
    A4_WIDTH_MM,
    A4_HEIGHT_MM,
    STRIP_WIDTH_MM,
    SIDE_MARGIN_MM,
    COLUMN_SPACING_MM,
    HOLE_DIAMETER_MM,
    COLUMNS,
)

# A4 Multi-strip layout geometry (in exact millimeters)
STRIPS_PER_PAGE = 4
STRIP_GAP_MM = 4.0  # Gap between adjacent 41mm strips for clean scissor cutting
TOTAL_ROW_WIDTH_MM = STRIPS_PER_PAGE * STRIP_WIDTH_MM + (STRIPS_PER_PAGE - 1) * STRIP_GAP_MM  # 176.0 mm
LEFT_PAGE_MARGIN_MM = (A4_WIDTH_MM - TOTAL_ROW_WIDTH_MM) / 2.0  # 17.0 mm safe printer margin

HEADER_TOP_MARGIN_MM = 10.0
HEADER_HEIGHT_MM = 20.0
STRIP_TOP_Y_FROM_TOP_MM = HEADER_TOP_MARGIN_MM + HEADER_HEIGHT_MM  # 30.0 mm from top edge
STRIP_TOTAL_HEIGHT_MM = 254.0  # Ends at 284.0 mm (13.0 mm safe bottom printer margin on 297mm A4)

LEAD_IN_TIP_MM = 16.0          # Tapered feed tip + column labels on Strip 1
GLUE_TAB_MM = 14.0             # Overlap glue/tape tab + column labels on Strips 2..N
BOTTOM_SPLICE_MARGIN_MM = 6.0  # Clean margin at bottom of strip before cut/splice line


def compute_a4_strip_segments(punches: List[dict], mm_per_beat: float = 8.0) -> List[dict]:
    """Slice a continuous punch pattern (y_mm >= 0) into A4-sized vertical strip segments."""
    max_y = max((p["y_mm"] for p in punches), default=0.0)
    total_music_mm = max(20.0, max_y + 8.0)

    segments: List[dict] = []
    cursor_mm = 0.0
    strip_idx = 0

    while cursor_mm < total_music_mm - 1e-4 or strip_idx == 0:
        header_mm = LEAD_IN_TIP_MM if strip_idx == 0 else GLUE_TAB_MM
        usable_mm = STRIP_TOTAL_HEIGHT_MM - header_mm - BOTTOM_SPLICE_MARGIN_MM  # ~232-234 mm
        seg_start = cursor_mm
        seg_end = cursor_mm + usable_mm

        seg_punches = [
            {
                **p,
                "local_y_mm": round(p["y_mm"] - seg_start, 3),
            }
            for p in punches
            if seg_start - 1e-4 <= p["y_mm"] < seg_end - 1e-4
        ]

        segments.append({
            "strip_number": strip_idx + 1,
            "page_index": strip_idx // STRIPS_PER_PAGE,
            "slot_on_page": strip_idx % STRIPS_PER_PAGE,
            "is_first": (strip_idx == 0),
            "header_mm": header_mm,
            "usable_mm": usable_mm,
            "start_y_mm": round(seg_start, 2),
            "end_y_mm": round(seg_end, 2),
            "mm_per_beat": mm_per_beat,
            "punches": seg_punches,
        })
        cursor_mm = seg_end
        strip_idx += 1

    for seg in segments:
        seg["total_strips"] = len(segments)
        seg["total_pages"] = math.ceil(len(segments) / STRIPS_PER_PAGE)
    return segments


def _pdf_safe_text(text: str) -> str:
    """Ensure text only contains glyphs supported by ReportLab's built-in WinAnsi Helvetica on Windows."""
    cleaned = (
        str(text)
        .replace("—", "-")
        .replace("–", "-")
        .replace("▲", "^")
        .replace("▼", "v")
        .replace("■", "#")
    )
    return cleaned.encode("cp1252", errors="replace").decode("cp1252")


def generate_a4_pdf(
    title: str,
    subtitle: str,
    punches: List[dict],
    mm_per_beat: float = 8.0,
    grid_line_mm: float = 4.0,
) -> bytes:
    """Render an exact 1:1 millimeter A4 PDF ready to print at 100% Actual Size."""
    safe_title = _pdf_safe_text(title)
    safe_subtitle = _pdf_safe_text(subtitle)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(A4_WIDTH_MM * mm, A4_HEIGHT_MM * mm))
    c.setTitle(f"{safe_title} - Kikkerland 15-Note A4 Strip Pattern")

    segments = compute_a4_strip_segments(punches, mm_per_beat=mm_per_beat)
    total_pages = segments[0]["total_pages"]
    total_strips = segments[0]["total_strips"]

    # Helper to convert top-down millimeter coordinates (x_mm, y_from_top_mm) to ReportLab bottom-up points
    def pt_xy(x_m: float, y_top_m: float):
        return x_m * mm, (A4_HEIGHT_MM - y_top_m) * mm

    def draw_up_triangle(cx_m: float, cy_top_m: float, half_w_m: float = 1.0, h_m: float = 1.6):
        tri = c.beginPath()
        tri.moveTo(*pt_xy(cx_m, cy_top_m - h_m / 2.0))
        tri.lineTo(*pt_xy(cx_m - half_w_m, cy_top_m + h_m / 2.0))
        tri.lineTo(*pt_xy(cx_m + half_w_m, cy_top_m + h_m / 2.0))
        tri.close()
        c.drawPath(tri, stroke=0, fill=1)

    for page_idx in range(total_pages):
        page_segs = [s for s in segments if s["page_index"] == page_idx]

        # --- Page Header & 50.0 mm Calibration Ruler ---
        c.setFillColor(colors.HexColor("#1C1917"))
        c.setFont("Helvetica-Bold", 11)
        c.drawString(
            LEFT_PAGE_MARGIN_MM * mm,
            (A4_HEIGHT_MM - 14.0) * mm,
            f"{safe_title[:52]}  -  Kikkerland 15-Note Strip (Page {page_idx + 1}/{total_pages})",
        )
        c.setFont("Helvetica", 7.5)
        c.setFillColor(colors.HexColor("#57534E"))
        c.drawString(
            LEFT_PAGE_MARGIN_MM * mm,
            (A4_HEIGHT_MM - 18.5) * mm,
            f"{safe_subtitle}  |  IMPORTANT: Print at 100% / Actual Size (Disable 'Fit to Page') on 180-220 gsm cardstock.",
        )

        # 50.0 mm Calibration Ruler at top-right
        ruler_x0 = A4_WIDTH_MM - LEFT_PAGE_MARGIN_MM - 50.0
        ruler_y_top = 24.5
        c.setStrokeColor(colors.HexColor("#1C1917"))
        c.setLineWidth(0.7)
        x1, y1 = pt_xy(ruler_x0, ruler_y_top)
        x2, y2 = pt_xy(ruler_x0 + 50.0, ruler_y_top)
        c.line(x1, y1, x2, y2)
        for tick_mm in range(0, 51, 5):
            tick_h = 2.6 if tick_mm % 10 == 0 else 1.4
            tx, ty0 = pt_xy(ruler_x0 + tick_mm, ruler_y_top)
            _, ty1 = pt_xy(ruler_x0 + tick_mm, ruler_y_top - tick_h)
            c.line(tx, ty0, tx, ty1)
        c.setFont("Helvetica-Bold", 6.5)
        c.setFillColor(colors.HexColor("#1C1917"))
        c.drawString(
            ruler_x0 * mm,
            (A4_HEIGHT_MM - 27.3) * mm,
            "CALIBRATION CHECK: Must measure exactly 50.0 mm",
        )

        # Also draw a light strip-width check note on top-left
        c.setFont("Helvetica", 6.8)
        c.setFillColor(colors.HexColor("#44403C"))
        c.drawString(
            LEFT_PAGE_MARGIN_MM * mm,
            (A4_HEIGHT_MM - 24.5) * mm,
            f"Strip width: 41.0 mm  |  Hole pitch: 2.0 mm  |  Total strips: {total_strips}  |  Cut along outer solid border, tape sequentially.",
        )

        # --- Render up to 4 Strips on this Page ---
        for seg in page_segs:
            slot = seg["slot_on_page"]
            sx = LEFT_PAGE_MARGIN_MM + slot * (STRIP_WIDTH_MM + STRIP_GAP_MM)
            sy_top = STRIP_TOP_Y_FROM_TOP_MM
            sy_bot = sy_top + STRIP_TOTAL_HEIGHT_MM
            header_mm = seg["header_mm"]
            music_start_top = sy_top + header_mm
            music_end_top = sy_bot - BOTTOM_SPLICE_MARGIN_MM

            # 1. Outer 41.0 mm Cut Outline
            c.setStrokeColor(colors.HexColor("#292524"))
            c.setLineWidth(0.65)
            if seg["is_first"]:
                # Tapered feed-in tip on Strip 1 (diagonal corners 8mm tall so it slides smoothly into Kikkerland slot!)
                taper_h = 7.5
                taper_inset = 7.5
                p = c.beginPath()
                p.moveTo(*pt_xy(sx + taper_inset, sy_top))
                p.lineTo(*pt_xy(sx + STRIP_WIDTH_MM - taper_inset, sy_top))
                p.lineTo(*pt_xy(sx + STRIP_WIDTH_MM, sy_top + taper_h))
                p.lineTo(*pt_xy(sx + STRIP_WIDTH_MM, sy_bot))
                p.lineTo(*pt_xy(sx, sy_bot))
                p.lineTo(*pt_xy(sx, sy_top + taper_h))
                p.close()
                c.drawPath(p, stroke=1, fill=0)

                # Feed direction vector arrows + label in the lead-in tip
                c.setFillColor(colors.HexColor("#292524"))
                c.setFont("Helvetica-Bold", 6.2)
                c.drawCentredString(
                    (sx + STRIP_WIDTH_MM / 2.0) * mm,
                    (A4_HEIGHT_MM - (sy_top + 5.2)) * mm,
                    "FEED THIS END FIRST (STRIP 1)",
                )
                draw_up_triangle(sx + 5.5, sy_top + 4.5, half_w_m=0.85, h_m=1.4)
                draw_up_triangle(sx + STRIP_WIDTH_MM - 5.5, sy_top + 4.5, half_w_m=0.85, h_m=1.4)
            else:
                # Rectangular strip with shaded Glue/Tape alignment tab at top
                c.setFillColor(colors.HexColor("#F5F5F4"))
                rx, ry = pt_xy(sx, sy_top + 8.5)
                c.rect(rx, ry, STRIP_WIDTH_MM * mm, 8.5 * mm, stroke=0, fill=1)

                rx_full, ry_full = pt_xy(sx, sy_bot)
                c.rect(rx_full, ry_full, STRIP_WIDTH_MM * mm, STRIP_TOTAL_HEIGHT_MM * mm, stroke=1, fill=0)

                # Dashed splice line below glue tab
                c.saveState()
                c.setDash(2, 2)
                c.setLineWidth(0.4)
                c.setStrokeColor(colors.HexColor("#78716C"))
                c.line(*pt_xy(sx, sy_top + 8.5), *pt_xy(sx + STRIP_WIDTH_MM, sy_top + 8.5))
                c.restoreState()

                c.setFillColor(colors.HexColor("#44403C"))
                c.setFont("Helvetica-Bold", 5.6)
                c.drawCentredString(
                    (sx + STRIP_WIDTH_MM / 2.0) * mm,
                    (A4_HEIGHT_MM - (sy_top + 5.3)) * mm,
                    f"GLUE / TAPE UNDER END OF STRIP {seg['strip_number'] - 1}  (STRIP {seg['strip_number']}/{total_strips})",
                )

            # 2. Column Labels: C D E F G A B C D E F G A B C
            label_y_top = music_start_top - 2.2
            for col in COLUMNS:
                cx = sx + col.x_mm
                c.setFont("Helvetica-Bold" if col.is_bold else "Helvetica", 5.2)
                c.setFillColor(colors.HexColor("#1C1917") if col.is_bold else colors.HexColor("#57534E"))
                c.drawCentredString(cx * mm, (A4_HEIGHT_MM - label_y_top) * mm, col.printed_label)

            # 3. Horizontal Timing Grid Lines
            step_mm = max(2.0, grid_line_mm)
            num_grid = int(math.floor(seg["usable_mm"] / step_mm)) + 1
            for g_i in range(num_grid):
                gy_top = music_start_top + g_i * step_mm
                global_y = seg["start_y_mm"] + g_i * step_mm
                is_beat_line = abs((global_y / max(1.0, mm_per_beat)) - round(global_y / max(1.0, mm_per_beat))) < 0.05
                c.setStrokeColor(colors.HexColor("#A8A29E") if is_beat_line else colors.HexColor("#E7E5E4"))
                c.setLineWidth(0.35 if is_beat_line else 0.18)
                c.line(
                    *pt_xy(sx + SIDE_MARGIN_MM, gy_top),
                    *pt_xy(sx + STRIP_WIDTH_MM - SIDE_MARGIN_MM, gy_top),
                )

            # 4. 15 Vertical Note Lines (with BOLD E-G-B-D-F lines matching Kikkerland strip!)
            for col in COLUMNS:
                cx = sx + col.x_mm
                if col.is_bold:
                    c.setStrokeColor(colors.HexColor("#44403C"))
                    c.setLineWidth(0.65)
                else:
                    c.setStrokeColor(colors.HexColor("#A8A29E"))
                    c.setLineWidth(0.25)
                c.line(*pt_xy(cx, music_start_top), *pt_xy(cx, music_end_top))

            # 5. Punch Holes (Exact 2.0 mm diameter = 1.0 mm radius circles + center dot)
            hole_r_pt = (HOLE_DIAMETER_MM / 2.0) * mm
            for p in seg["punches"]:
                px = sx + p["x_mm"]
                py_top = music_start_top + p["local_y_mm"]
                cx_pt, cy_pt = pt_xy(px, py_top)

                # White knockout halo + bold crisp black 2.0mm ring + pinpoint center dot
                c.setFillColor(colors.white)
                c.setStrokeColor(colors.HexColor("#B91C1C") if p.get("repeat_warning") else colors.HexColor("#111827"))
                c.setLineWidth(0.75)
                c.circle(cx_pt, cy_pt, hole_r_pt, stroke=1, fill=1)

                c.setFillColor(colors.HexColor("#111827"))
                c.circle(cx_pt, cy_pt, 0.28 * mm, stroke=0, fill=1)

            # 6. Bottom splice / end footer inside strip
            c.saveState()
            c.setDash(2, 2)
            c.setLineWidth(0.35)
            c.setStrokeColor(colors.HexColor("#78716C"))
            c.line(*pt_xy(sx, music_end_top), *pt_xy(sx + STRIP_WIDTH_MM, music_end_top))
            c.restoreState()

            footer_label = (
                f"v  ATTACH STRIP {seg['strip_number'] + 1} HERE  v"
                if seg["strip_number"] < total_strips
                else f"--- END OF SONG (STRIP {seg['strip_number']}/{total_strips}) ---"
            )
            c.setFillColor(colors.HexColor("#57534E"))
            c.setFont("Helvetica", 5.3)
            c.drawCentredString(
                (sx + STRIP_WIDTH_MM / 2.0) * mm,
                (A4_HEIGHT_MM - (sy_bot - 1.8)) * mm,
                footer_label,
            )

        c.showPage()

    c.save()
    return buf.getvalue()


def generate_a4_svg(
    title: str,
    subtitle: str,
    punches: List[dict],
    mm_per_beat: float = 8.0,
    grid_line_mm: float = 4.0,
    page_index: int = 0,
) -> str:
    """Render an exact 1:1 millimeter A4 SVG sheet (for browser preview or vector cutters/printing)."""
    segments = compute_a4_strip_segments(punches, mm_per_beat=mm_per_beat)
    total_pages = segments[0]["total_pages"]
    total_strips = segments[0]["total_strips"]
    p_idx = max(0, min(page_index, total_pages - 1))
    page_segs = [s for s in segments if s["page_index"] == p_idx]

    esc = lambda s: (
        str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{A4_WIDTH_MM}mm" height="{A4_HEIGHT_MM}mm" '
        f'viewBox="0 0 {A4_WIDTH_MM} {A4_HEIGHT_MM}" font-family="sans-serif">',
        f'<rect x="0" y="0" width="{A4_WIDTH_MM}" height="{A4_HEIGHT_MM}" fill="#FFFFFF"/>',
        f'<text x="{LEFT_PAGE_MARGIN_MM}" y="14" font-size="3.8" font-weight="700" fill="#1C1917">'
        f'{esc(title[:52])} — Kikkerland 15-Note Strip (Page {p_idx + 1}/{total_pages})</text>',
        f'<text x="{LEFT_PAGE_MARGIN_MM}" y="18.5" font-size="2.5" fill="#57534E">'
        f'{esc(subtitle)} | Print at 100% Actual Size on 180-220 gsm cardstock</text>',
    ]

    # 50.0 mm Calibration Ruler
    rx0 = A4_WIDTH_MM - LEFT_PAGE_MARGIN_MM - 50.0
    ry = 24.5
    lines.append(f'<line x1="{rx0}" y1="{ry}" x2="{rx0 + 50.0}" y2="{ry}" stroke="#1C1917" stroke-width="0.3"/>')
    for t_mm in range(0, 51, 5):
        th = 2.5 if t_mm % 10 == 0 else 1.3
        lines.append(
            f'<line x1="{rx0 + t_mm}" y1="{ry}" x2="{rx0 + t_mm}" y2="{ry - th}" stroke="#1C1917" stroke-width="0.25"/>'
        )
    lines.append(
        f'<text x="{rx0}" y="27.3" font-size="2.2" font-weight="700" fill="#1C1917">'
        f'CALIBRATION: Must measure 50.0 mm</text>'
    )

    for seg in page_segs:
        slot = seg["slot_on_page"]
        sx = LEFT_PAGE_MARGIN_MM + slot * (STRIP_WIDTH_MM + STRIP_GAP_MM)
        sy_top = STRIP_TOP_Y_FROM_TOP_MM
        sy_bot = sy_top + STRIP_TOTAL_HEIGHT_MM
        music_start = sy_top + seg["header_mm"]
        music_end = sy_bot - BOTTOM_SPLICE_MARGIN_MM

        if seg["is_first"]:
            pts = (
                f"{sx + 7.5},{sy_top} {sx + STRIP_WIDTH_MM - 7.5},{sy_top} "
                f"{sx + STRIP_WIDTH_MM},{sy_top + 7.5} {sx + STRIP_WIDTH_MM},{sy_bot} "
                f"{sx},{sy_bot} {sx},{sy_top + 7.5}"
            )
            lines.append(f'<polygon points="{pts}" fill="none" stroke="#292524" stroke-width="0.3"/>')
            lines.append(
                f'<text x="{sx + STRIP_WIDTH_MM / 2}" y="{sy_top + 5.2}" text-anchor="middle" '
                f'font-size="2.1" font-weight="700" fill="#292524">▲ FEED FIRST (STRIP 1) ▲</text>'
            )
        else:
            lines.append(f'<rect x="{sx}" y="{sy_top}" width="{STRIP_WIDTH_MM}" height="8.5" fill="#F5F5F4"/>')
            lines.append(
                f'<rect x="{sx}" y="{sy_top}" width="{STRIP_WIDTH_MM}" height="{STRIP_TOTAL_HEIGHT_MM}" '
                f'fill="none" stroke="#292524" stroke-width="0.3"/>'
            )
            lines.append(
                f'<line x1="{sx}" y1="{sy_top + 8.5}" x2="{sx + STRIP_WIDTH_MM}" y2="{sy_top + 8.5}" '
                f'stroke="#78716C" stroke-width="0.2" stroke-dasharray="1,1"/>'
            )
            lines.append(
                f'<text x="{sx + STRIP_WIDTH_MM / 2}" y="{sy_top + 5.2}" text-anchor="middle" '
                f'font-size="1.9" font-weight="700" fill="#44403C">'
                f'GLUE UNDER STRIP {seg["strip_number"] - 1} ({seg["strip_number"]}/{total_strips})</text>'
            )

        # Column labels
        for col in COLUMNS:
            cx = sx + col.x_mm
            fw = "700" if col.is_bold else "400"
            lines.append(
                f'<text x="{cx}" y="{music_start - 1.8}" text-anchor="middle" font-size="1.9" '
                f'font-weight="{fw}" fill="#1C1917">{col.printed_label}</text>'
            )

        # Horizontal timing lines
        step_mm = max(2.0, grid_line_mm)
        num_grid = int(math.floor(seg["usable_mm"] / step_mm)) + 1
        for g_i in range(num_grid):
            gy = music_start + g_i * step_mm
            global_y = seg["start_y_mm"] + g_i * step_mm
            is_beat = abs((global_y / max(1.0, mm_per_beat)) - round(global_y / max(1.0, mm_per_beat))) < 0.05
            col_hex = "#A8A29E" if is_beat else "#E7E5E4"
            sw = "0.18" if is_beat else "0.1"
            lines.append(
                f'<line x1="{sx + SIDE_MARGIN_MM}" y1="{gy:.3f}" x2="{sx + STRIP_WIDTH_MM - SIDE_MARGIN_MM}" '
                f'y2="{gy:.3f}" stroke="{col_hex}" stroke-width="{sw}"/>'
            )

        # Vertical note lines (bold on E G B D F)
        for col in COLUMNS:
            cx = sx + col.x_mm
            sw = "0.32" if col.is_bold else "0.12"
            sc = "#44403C" if col.is_bold else "#A8A29E"
            lines.append(
                f'<line x1="{cx:.3f}" y1="{music_start}" x2="{cx:.3f}" y2="{music_end}" '
                f'stroke="{sc}" stroke-width="{sw}"/>'
            )

        # 2.0 mm Punch Circles
        r_mm = HOLE_DIAMETER_MM / 2.0
        for p in seg["punches"]:
            px = sx + p["x_mm"]
            py = music_start + p["local_y_mm"]
            ring_color = "#B91C1C" if p.get("repeat_warning") else "#111827"
            lines.append(
                f'<circle cx="{px:.3f}" cy="{py:.3f}" r="{r_mm:.3f}" fill="#FFFFFF" '
                f'stroke="{ring_color}" stroke-width="0.32"/>'
            )
            lines.append(f'<circle cx="{px:.3f}" cy="{py:.3f}" r="0.22" fill="#111827"/>')

        footer_txt = (
            f"▼ ATTACH STRIP {seg['strip_number'] + 1} ▼"
            if seg["strip_number"] < total_strips
            else f"■ END ({seg['strip_number']}/{total_strips}) ■"
        )
        lines.append(
            f'<text x="{sx + STRIP_WIDTH_MM / 2}" y="{sy_bot - 1.6}" text-anchor="middle" '
            f'font-size="1.8" fill="#57534E">{footer_txt}</text>'
        )

    lines.append("</svg>")
    return "\n".join(lines)
