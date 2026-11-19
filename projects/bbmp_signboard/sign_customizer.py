#!/usr/bin/env python3
"""Interactive Kannada & English Customizer for the Heritage Kempegowda BBMP Arch (`bbmp_signboard`).

Generates exact 1:1 millimeter-calibrated graphic inserts (63.20 x 13.80 mm @ 600 DPI PNG +
True-Scale A4 PDF sheet packing up to 14 custom signs + 50.0mm calibration ruler) engineered
to drop flush into the 63.60 x 14.20 mm recessed bay on `arch_signboard.stl`.

Usage:
  1. Launch Interactive Browser Studio (with Live Heritage Arch Preview!):
       python3 projects/bbmp_signboard/sign_customizer.py --serve 8085

  2. Command-Line Export (Kannada or English):
       python3 projects/bbmp_signboard/sign_customizer.py \
         --line1 "ಬೆಂಗಳೂರು" \
         --out projects/bbmp_signboard/inserts/bengaluru
"""

import argparse
import io
import json
import math
import os
import random
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageDraw, ImageFilter, ImageFont


# ==============================================================================
# EXACT PHYSICAL INSERT DIMENSIONS MATCHED TO `build_bbmp.py` (`63.60 x 14.20 mm` Bay)
# ==============================================================================
CARD_W_MM = 63.20                 # 0.20mm/side slip clearance inside 63.60mm bay
CARD_H_MM = 13.80                 # 0.20mm/side slip clearance inside 14.20mm bay

A4_W_MM = 210.0
A4_H_MM = 297.0

FONT_CANDIDATES_KN = [
    "/usr/share/fonts/truetype/noto/NotoSansKannada-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansKannadaUI-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerifKannada-Bold.ttf",
]
FONT_CANDIDATES_EN = [
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]

THEMES = {
    "heritage_yellow": {
        "label": "Heritage Kempegowda Yellow & Black (Matches original.webp)",
        "bg": (244, 198, 24),
        "text": (20, 20, 18),
    },
    "white_black": {
        "label": "White / Clear-Sticker Printable (Black Text on White)",
        "bg": (255, 255, 255),
        "text": (16, 16, 16),
    },
    "bbmp_green": {
        "label": "Municipal BBMP Green & White",
        "bg": (25, 78, 59),
        "text": (246, 246, 242),
    },
    "rajyotsava_red": {
        "label": "Karnataka Red & Yellow Text",
        "bg": (204, 42, 34),
        "text": (248, 208, 32),
    },
}


def pick_font_path(text):
    has_kn = any("\u0c80" <= ch <= "\u0cff" for ch in text)
    pool = FONT_CANDIDATES_KN if has_kn else (FONT_CANDIDATES_EN + FONT_CANDIDATES_KN)
    for p in pool:
        if os.path.exists(p):
            return p
    return FONT_CANDIDATES_KN[0]


def load_font(text, px_size):
    return ImageFont.truetype(pick_font_path(text), max(10, int(round(px_size))))


def fit_font_size(draw, text, max_w_px, max_h_px, start_px):
    sz = int(round(start_px))
    while sz > 12:
        f = load_font(text, sz)
        bb = draw.textbbox((0, 0), text, font=f)
        if (bb[2] - bb[0]) <= max_w_px and (bb[3] - bb[1]) <= max_h_px:
            return f
        sz -= 2
    return load_font(text, 12)


def apply_patina(img, amount=0.12, seed=42):
    if amount <= 0.01:
        return img
    rng = random.Random(seed)
    w, h = img.size
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    for _ in range(int(w * h * 0.0016 * amount)):
        x, y = rng.randint(0, w - 1), rng.randint(0, h - 1)
        r = rng.randint(1, max(2, int(w * 0.0015)))
        col = (45, 32, 18, int(52 * amount)) if rng.random() < 0.6 else (255, 248, 220, int(40 * amount))
        od.ellipse([x - r, y - r, x + r, y + r], fill=col)
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


def render_insert_card(
    line1="ಬೆಂಗಳೂರು",
    line2="",
    theme_key="heritage_yellow",
    scale_pct=100,
    weathering=0.10,
    dpi=600,
):
    """Renders the exact 63.20 x 13.80 mm printable insert card."""
    px_mm = dpi / 25.4
    cw = int(round(CARD_W_MM * px_mm))
    ch = int(round(CARD_H_MM * px_mm))
    theme = THEMES.get(theme_key, THEMES["heritage_yellow"])
    scale = max(60, min(145, int(scale_pct))) / 100.0

    card = Image.new("RGB", (cw, ch), theme["bg"])
    draw = ImageDraw.Draw(card)

    l1 = line1.strip()
    l2 = line2.strip()
    max_w = (CARD_W_MM - 5.0) * px_mm

    if l1 and l2:
        f1 = fit_font_size(draw, l1, max_w, ch * 0.50, 5.8 * px_mm * scale)
        f2 = fit_font_size(draw, l2, max_w, ch * 0.40, 4.3 * px_mm * scale)
        b1 = draw.textbbox((0, 0), l1, font=f1)
        b2 = draw.textbbox((0, 0), l2, font=f2)
        h1, h2 = b1[3] - b1[1], b2[3] - b2[1]
        gap = max(2, int(0.9 * px_mm))
        tot = h1 + gap + h2
        y0 = (ch - tot) / 2.0
        draw.text(((cw - (b1[2] - b1[0])) / 2.0 - b1[0], y0 - b1[1]), l1, font=f1, fill=theme["text"])
        draw.text(((cw - (b2[2] - b2[0])) / 2.0 - b2[0], y0 + h1 + gap - b2[1]), l2, font=f2, fill=theme["text"])
    elif l1 or l2:
        txt = l1 or l2
        f1 = fit_font_size(draw, txt, max_w, ch * 0.82, 8.8 * px_mm * scale)
        b1 = draw.textbbox((0, 0), txt, font=f1)
        draw.text(
            ((cw - (b1[2] - b1[0])) / 2.0 - b1[0], (ch - (b1[3] - b1[1])) / 2.0 - b1[1]),
            txt,
            font=f1,
            fill=theme["text"],
        )

    card = apply_patina(card, amount=float(weathering))
    # Hairline light-grey scissor trim border around outer pixel
    ImageDraw.Draw(card).rectangle([0, 0, cw - 1, ch - 1], outline=(185, 175, 145), width=max(1, int(0.12 * px_mm)))
    return card


def render_arch_mockup(line1="ಬೆಂಗಳೂರು", line2="", theme_key="heritage_yellow", scale_pct=100, weathering=0.10, dpi=220):
    """Renders a full-color 2D architectural preview of the 96 x 60.5 mm Heritage Kempegowda Arch
    with the custom insert seated in the center bay!
    """
    px_mm = dpi / 25.4
    margin_mm = 6.0
    W = int(round((96.0 + 2 * margin_mm) * px_mm))
    H = int(round((60.5 + 2 * margin_mm) * px_mm))
    img = Image.new("RGB", (W, H), (236, 234, 228))
    d = ImageDraw.Draw(img)

    def to_px(x_mm, y_mm):
        return (
            (48.0 + margin_mm + x_mm) * px_mm,
            (60.5 + margin_mm - y_mm) * px_mm,
        )

    yellow = (244, 198, 24)
    yellow_hi = (252, 214, 58)
    red = (218, 62, 52)
    teal = (14, 158, 136)

    # Crown & Bottom Arch Profiles (matching `build_bbmp.py`)
    crown_r = [
        (0.00, 60.50), (1.60, 59.95), (3.20, 58.40), (4.80, 56.20), (6.20, 54.40),
        (8.20, 53.65), (10.00, 52.30), (11.40, 50.60), (14.50, 50.25), (15.60, 45.70),
        (19.50, 44.45), (25.80, 44.10), (26.60, 41.30), (37.00, 41.30),
    ]
    bot_r = [
        (0.00, 22.20), (29.20, 22.20), (31.50, 21.60), (33.50, 20.10),
        (34.80, 18.00), (35.40, 16.80), (35.40, 15.20), (37.00, 15.20),
    ]
    poly_mm = [(-x, y) for x, y in reversed(crown_r[1:])] + crown_r + list(reversed(bot_r)) + [(-x, y) for x, y in bot_r[1:]]
    d.polygon([to_px(x, y) for x, y in poly_mm], fill=red)

    # Inset yellow field (1.68mm border)
    crown_in = [(0.0, 58.3)] + [(max(0.0, x - 1.5), y - 1.65) for x, y in crown_r[1:-1]] + [(36.8, 39.62)]
    bot_in = [(x, y + 1.68) for x, y in bot_r[:-1]] + [(36.8, 16.88)]
    poly_in = [(-x, y) for x, y in reversed(crown_in[1:])] + crown_in + list(reversed(bot_in)) + [(-x, y) for x, y in bot_in[1:]]
    d.polygon([to_px(x, y) for x, y in poly_in], fill=yellow)

    # Medallion Ring, Crescent, & Kempegowda Gopura
    mcx, mcy = to_px(0.0, 49.0)
    r_med = 7.5 * px_mm
    r_med_in = 6.0 * px_mm
    d.ellipse([mcx - r_med, mcy - r_med, mcx + r_med, mcy + r_med], fill=red)
    d.ellipse([mcx - r_med_in, mcy - r_med_in, mcx + r_med_in, mcy + r_med_in], fill=yellow)
    r_cr = 5.75 * px_mm
    d.arc([mcx - r_cr, mcy - r_cr, mcx + r_cr, mcy + r_cr], start=320, end=220, fill=teal, width=max(3, int(1.3 * px_mm)))

    # 3-Tier Gopura in center
    for w_mm, y0_m, y1_m in [(5.8, 45.65, 46.9), (4.8, 47.2, 48.35), (3.8, 48.7, 49.75), (3.1, 49.7, 52.0)]:
        p0 = to_px(-w_mm / 2, y1_m)
        p1 = to_px(w_mm / 2, y0_m)
        d.rectangle([p0, p1], fill=red)
    dc = to_px(0, 51.9)
    dr = 1.55 * px_mm
    d.ellipse([dc[0] - dr, dc[1] - dr, dc[0] + dr, dc[1] + dr], fill=red)

    # Scroll Volutes
    for sx in (-1.0, 1.0):
        pts = [(5.2, 41.5), (7.8, 43.3), (10.8, 43.4), (11.1, 41.3), (13.7, 41.5)]
        d.line([to_px(sx * x, y) for x, y in pts], fill=yellow_hi, width=max(3, int(1.6 * px_mm)))

    # Twin Pillars + Stepped Pedestal Feet + Red Flutes
    for sx in (-1.0, 1.0):
        pcx = sx * 40.60
        # Shaft
        d.rectangle([to_px(pcx - 3.8, 40.8), to_px(pcx + 3.8, 5.2)], fill=yellow, outline=(210, 165, 16), width=2)
        # Capital & Dome
        d.rectangle([to_px(pcx - 4.7, 42.9), to_px(pcx + 4.7, 40.8)], fill=yellow_hi, outline=(210, 165, 16), width=1)
        dm = to_px(pcx, 42.9)
        dmr = 2.5 * px_mm
        d.pieslice([dm[0] - dmr, dm[1] - dmr, dm[0] + dmr, dm[1] + dmr], start=180, end=360, fill=yellow_hi)
        # Red Flute
        d.rounded_rectangle([to_px(pcx - 1.0, 38.0), to_px(pcx + 1.0, 8.4)], radius=int(1.0 * px_mm), fill=red)
        # 2-Step Pedestal Foot
        d.rectangle([to_px(pcx - 5.7, 5.2), to_px(pcx + 5.7, 2.8)], fill=yellow, outline=(205, 160, 14), width=1)
        d.rectangle([to_px(pcx - 7.4, 2.8), to_px(pcx + 7.4, 0.0)], fill=yellow, outline=(195, 150, 12), width=1)

    # Paste the custom rendered insert card into the exact `63.20 x 13.80 mm` bay!
    card = render_insert_card(line1=line1, line2=line2, theme_key=theme_key, scale_pct=scale_pct, weathering=weathering, dpi=dpi)
    bx, by = to_px(-CARD_W_MM / 2.0, 25.2 + CARD_H_MM)
    img.paste(card, (int(round(bx)), int(round(by))))
    return img


def build_a4_pdf_bytes(sign_configs, dpi=300):
    """Packs up to 14 custom BBMP Heritage Inserts (2 cols x 7 rows) onto one 1:1 A4 PDF!"""
    px_mm = dpi / 25.4
    pw = int(round(A4_W_MM * px_mm))
    ph = int(round(A4_H_MM * px_mm))
    page = Image.new("RGB", (pw, ph), (255, 255, 255))
    draw = ImageDraw.Draw(page)

    tf = load_font("BBMP", 3.5 * px_mm)
    sf = load_font("BBMP", 2.7 * px_mm)
    draw.text(
        (int(14 * px_mm), int(11 * px_mm)),
        "Heritage Kempegowda BBMP Signboard Inserts (63.2 x 13.8 mm) — Print on A4 at '100% / Actual Size'",
        font=tf,
        fill=(25, 25, 25),
    )

    col_x_mm = [28.0, 28.0 + CARD_W_MM + 16.0]
    row_y0_mm = 26.0
    row_step_mm = CARD_H_MM + 18.0

    for idx, cfg in enumerate(sign_configs[:14]):
        col = idx % 2
        row = idx // 2
        x_px = int(round(col_x_mm[col] * px_mm))
        y_px = int(round((row_y0_mm + row * row_step_mm) * px_mm))

        c_img = render_insert_card(
            line1=cfg.get("line1", ""),
            line2=cfg.get("line2", ""),
            theme_key=cfg.get("theme", "heritage_yellow"),
            scale_pct=cfg.get("scale", 100),
            weathering=cfg.get("weathering", 0.10),
            dpi=dpi,
        )
        page.paste(c_img, (x_px, y_px))
        cw, ch = c_img.size
        tk = int(2.2 * px_mm)
        for cx, cy in [(x_px, y_px), (x_px + cw, y_px), (x_px, y_px + ch), (x_px + cw, y_px + ch)]:
            draw.line([(cx - tk, cy), (cx + tk, cy)], fill=(110, 110, 110), width=1)
            draw.line([(cx, cy - tk), (cx, cy + tk)], fill=(110, 110, 110), width=1)

    # 50.0 mm calibration check bar
    ry = int(round(281.0 * px_mm))
    rx0 = int(round(14.0 * px_mm))
    rx1 = rx0 + int(round(50.0 * px_mm))
    draw.line([(rx0, ry), (rx1, ry)], fill=(0, 0, 0), width=3)
    draw.line([(rx0, ry - 12), (rx0, ry + 12)], fill=(0, 0, 0), width=3)
    draw.line([(rx1, ry - 12), (rx1, ry + 12)], fill=(0, 0, 0), width=3)
    draw.text(
        (rx1 + int(3 * px_mm), ry - int(1.8 * px_mm)),
        "<-- Verify this bar measures exactly 50.0 mm with a ruler before cutting & gluing into arch_signboard.stl",
        font=sf,
        fill=(45, 45, 45),
    )

    buf = io.BytesIO()
    page.save(buf, format="PDF", resolution=float(dpi))
    return buf.getvalue()


HTML_UI = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Heritage Kempegowda BBMP Arch Customizer</title>
<style>
  :root { --bg: #161513; --card: #22201c; --accent: #f4c618; --red: #da3e34; --text: #f3f1ec; }
  body { font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 28px; }
  .wrap { max-width: 1080px; margin: 0 auto; display: grid; grid-template-columns: 390px 1fr; gap: 28px; }
  .panel { background: var(--card); border-radius: 14px; padding: 22px; border: 1px solid #38332a; }
  h1 { font-size: 20px; margin: 0 0 6px; color: var(--accent); }
  p.sub { font-size: 13px; color: #a8a296; margin: 0 0 18px; }
  label { display: block; font-size: 12px; font-weight: 600; color: #cfc9bc; margin: 12px 0 5px; text-transform: uppercase; letter-spacing: 0.04em; }
  input[type=text], select { width: 100%; box-sizing: border-box; padding: 10px 12px; border-radius: 8px; border: 1px solid #484136; background: #141310; color: #fff; font-size: 16px; }
  input[type=range] { width: 100%; }
  .presets { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
  .chip { background: #2e2b24; color: #eee9de; border: 1px solid #484236; border-radius: 6px; padding: 5px 9px; font-size: 12px; cursor: pointer; }
  .chip:hover { border-color: var(--accent); color: var(--accent); }
  .btns { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 18px; }
  button.primary { background: var(--accent); color: #161513; border: none; border-radius: 8px; padding: 11px 14px; font-weight: 700; cursor: pointer; font-size: 13px; }
  button.secondary { background: #332e26; color: #fff; border: 1px solid #524a3d; border-radius: 8px; padding: 11px 14px; font-weight: 600; cursor: pointer; font-size: 13px; }
  .preview-stage { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 360px; }
  .preview-stage img { max-width: 100%; border-radius: 10px; box-shadow: 0 16px 36px rgba(0,0,0,0.45); }
  .queue-list { margin-top: 14px; width: 100%; font-size: 13px; }
  .queue-item { display: flex; justify-content: space-between; background: #171613; padding: 7px 11px; border-radius: 6px; margin-top: 5px; }
</style>
</head>
<body>
<div class="wrap">
  <div class="panel">
    <h1>Kempegowda BBMP Arch Studio</h1>
    <p class="sub">1:1 Inserts (<code>63.2 &times; 13.8 mm</code>) for the <code>96 &times; 60.5 mm</code> Heritage Arch</p>

    <label>Quick Presets</label>
    <div class="presets">
      <span class="chip" onclick="setPreset('ಬೆಂಗಳೂರು','')">ಬೆಂಗಳೂರು (Original)</span>
      <span class="chip" onclick="setPreset('ಜಯನಗರ','')">ಜಯನಗರ</span>
      <span class="chip" onclick="setPreset('ಇಂದಿರಾನಗರ','')">ಇಂದಿರಾನಗರ</span>
      <span class="chip" onclick="setPreset('ಮಲ್ಲೇಶ್ವರಂ','')">ಮಲ್ಲೇಶ್ವರಂ</span>
      <span class="chip" onclick="setPreset('೧೨ನೇ ಮುಖ್ಯ ರಸ್ತೆ','ಇಂದಿರಾನಗರ')">2-Line KN</span>
      <span class="chip" onclick="setPreset('BENGALURU','')">BENGALURU (EN)</span>
    </div>

    <label>Line 1 (Kannada or English)</label>
    <input type="text" id="line1" value="ಬೆಂಗಳೂರು" oninput="refresh()">

    <label>Line 2 (Optional Sub-Line — Leave Blank for Bold Single Line)</label>
    <input type="text" id="line2" value="" oninput="refresh()">

    <label>Insert Background Style</label>
    <select id="theme" onchange="refresh()">
      <option value="heritage_yellow">Heritage Yellow &amp; Black (Matches original.webp)</option>
      <option value="white_black">White / Clear-Sticker Printable (Black Text)</option>
      <option value="bbmp_green">Municipal BBMP Green &amp; White</option>
      <option value="rajyotsava_red">Karnataka Red &amp; Yellow</option>
    </select>

    <label>Text Size (<span id="scVal">100</span>%)</label>
    <input type="range" id="scale" min="65" max="135" value="100" oninput="document.getElementById('scVal').innerText=this.value; refresh()">

    <label>Subtle Street Patina (<span id="wVal">0.10</span>)</label>
    <input type="range" id="weathering" min="0" max="50" value="10" oninput="document.getElementById('wVal').innerText=(this.value/100).toFixed(2); refresh()">

    <div class="btns">
      <button class="secondary" onclick="addToSheet()">+ Queue Sign (<span id="qCount">0</span>/14)</button>
      <button class="primary" onclick="downloadPDF()">Download 1:1 A4 PDF</button>
    </div>
  </div>

  <div class="panel preview-stage">
    <img id="prevImg" src="" alt="Live Heritage BBMP Arch Preview">
    <p class="sub" style="margin-top:14px;">Pack up to 14 custom Kannada &amp; English inserts onto a single A4 page!</p>
    <div class="queue-list" id="qList"></div>
  </div>
</div>

<script>
let queue = [];
let timer = null;
function curCfg() {
  return {
    line1: document.getElementById('line1').value,
    line2: document.getElementById('line2').value,
    theme: document.getElementById('theme').value,
    scale: parseInt(document.getElementById('scale').value),
    weathering: parseInt(document.getElementById('weathering').value) / 100.0
  };
}
function setPreset(l1, l2) {
  document.getElementById('line1').value = l1;
  document.getElementById('line2').value = l2;
  refresh();
}
function refresh() {
  clearTimeout(timer);
  timer = setTimeout(() => {
    const q = new URLSearchParams(curCfg()).toString();
    document.getElementById('prevImg').src = '/api/preview?' + q + '&_t=' + Date.now();
  }, 100);
}
function addToSheet() {
  if (queue.length >= 14) return alert('A4 page holds up to 14 signs!');
  queue.push(curCfg());
  renderQueue();
}
function removeIdx(i) { queue.splice(i, 1); renderQueue(); }
function renderQueue() {
  document.getElementById('qCount').innerText = queue.length;
  document.getElementById('qList').innerHTML = queue.map((c, i) =>
    `<div class="queue-item"><span>#${i+1}: ${c.line1}${c.line2 ? ' / ' + c.line2 : ''}</span><span style="cursor:pointer;color:#f77" onclick="removeIdx(${i})">Remove</span></div>`
  ).join('');
}
async function downloadPDF() {
  const items = queue.length > 0 ? queue : [curCfg()];
  const res = await fetch('/api/pdf', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({items})});
  const blob = await res.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'bbmp_heritage_inserts_a4.pdf';
  a.click();
}
refresh();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_UI.encode("utf-8"))
        elif parsed.path == "/api/preview":
            qs = parse_qs(parsed.query)
            img = render_arch_mockup(
                line1=qs.get("line1", [""])[0],
                line2=qs.get("line2", [""])[0],
                theme_key=qs.get("theme", ["heritage_yellow"])[0],
                scale_pct=int(float(qs.get("scale", ["100"])[0])),
                weathering=float(qs.get("weathering", ["0.10"])[0]),
                dpi=200,
            )
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(buf.getvalue())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/pdf":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            pdf_bytes = build_a4_pdf_bytes(payload.get("items", []), dpi=300)
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.end_headers()
            self.wfile.write(pdf_bytes)


def main():
    parser = argparse.ArgumentParser(description="Heritage Kempegowda BBMP Arch Insert Customizer")
    parser.add_argument("--serve", type=int, default=0, help="Launch interactive browser studio on port (e.g. 8085)")
    parser.add_argument("--line1", type=str, default="ಬೆಂಗಳೂರು")
    parser.add_argument("--line2", type=str, default="")
    parser.add_argument("--theme", type=str, default="heritage_yellow", choices=list(THEMES.keys()))
    parser.add_argument("--scale", type=int, default=100)
    parser.add_argument("--weathering", type=float, default=0.10)
    parser.add_argument("--out", type=str, default="")
    args = parser.parse_args()

    if args.serve > 0:
        print(f"Heritage BBMP Arch Studio running at: http://localhost:{args.serve}")
        HTTPServer(("127.0.0.1", args.serve), Handler).serve_forever()
        return

    out_prefix = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "inserts", "heritage_bengaluru")
    os.makedirs(os.path.dirname(os.path.abspath(out_prefix)), exist_ok=True)

    insert_img = render_insert_card(args.line1, args.line2, args.theme, args.scale, args.weathering, dpi=600)
    mockup_img = render_arch_mockup(args.line1, args.line2, args.theme, args.scale, args.weathering, dpi=280)
    insert_img.save(f"{out_prefix}_insert.png", dpi=(600, 600))
    mockup_img.save(f"{out_prefix}_mockup.png", dpi=(280, 280))

    starter_pack = [
        {"line1": "ಬೆಂಗಳೂರು", "line2": "", "theme": "heritage_yellow", "scale": 105, "weathering": 0.10},
        {"line1": "ಜಯನಗರ", "line2": "", "theme": "heritage_yellow", "scale": 105, "weathering": 0.10},
        {"line1": "ಇಂದಿರಾನಗರ", "line2": "", "theme": "heritage_yellow", "scale": 100, "weathering": 0.10},
        {"line1": "ಮಲ್ಲೇಶ್ವರಂ", "line2": "", "theme": "heritage_yellow", "scale": 100, "weathering": 0.10},
        {"line1": "೧೨ನೇ ಮುಖ್ಯ ರಸ್ತೆ", "line2": "ಇಂದಿರಾನಗರ", "theme": "heritage_yellow", "scale": 100, "weathering": 0.10},
        {"line1": "BENGALURU", "line2": "", "theme": "heritage_yellow", "scale": 100, "weathering": 0.10},
    ]
    with open(f"{out_prefix}_a4.pdf", "wb") as f:
        f.write(build_a4_pdf_bytes(starter_pack, dpi=300))

    print(f"[Generated] {out_prefix}_insert.png (600 DPI exact 63.2 x 13.8 mm)")
    print(f"[Generated] {out_prefix}_mockup.png (Heritage Arch mockup preview)")
    print(f"[Generated] {out_prefix}_a4.pdf (True 1:1 A4 Sheet with 6 Bengaluru presets + 50mm ruler)")


if __name__ == "__main__":
    main()
