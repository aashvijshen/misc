#!/usr/bin/env python3
"""Interactive 3D Bold Signboard Customizer for the Heritage Kempegowda BBMP Arch (`bbmp_signboard`).

Shapes single-word Kannada or English signs into nozzle-friendly bold 3D vector letterforms
(via HarfBuzz + FontTools + Shapely) and exports ready-to-slice `arch_signboard.stl` files
with the raised 3D letters fused directly onto the solid signboard face!

Usage:
  1. Launch Interactive Browser Studio (Live 3D-Bold Vector Preview + 1-Click STL Export):
       python3 projects/bbmp_signboard/sign_customizer.py --serve 8085

  2. Command-Line Custom 3D STL Export (Kannada or English):
       python3 projects/bbmp_signboard/sign_customizer.py \
         --text "ಇಂದಿರಾನಗರ" \
         --out projects/bbmp_signboard/custom_indiranagar.stl
"""

import argparse
import io
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageDraw

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from build_bbmp import (
    DEFAULT_BOLD_OFFSET,
    DEFAULT_LETTER_HEIGHT,
    DEFAULT_SIGN_TEXT,
    FONT_PRESETS,
    export_custom_arch_stl_bytes,
    shape_bold_word_polygons,
)


def render_arch_3d_bold_preview(
    text=DEFAULT_SIGN_TEXT,
    bold_offset=DEFAULT_BOLD_OFFSET,
    letter_height=DEFAULT_LETTER_HEIGHT,
    scale_pct=100,
    font_key="auto",
    dpi=240,
):
    """Renders a crisp architectural preview of the 96 x 60.5 mm Heritage Arch showing the
    exact 3D-bolded Shapely letter polygons fused directly onto the solid yellow signboard!
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

    # Continuous solid yellow signboard face (no rectangular paper-insert seam!)
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

    for w_mm, y0_m, y1_m in [(5.8, 45.65, 46.9), (4.8, 47.2, 48.35), (3.8, 48.7, 49.75), (3.1, 49.7, 52.0)]:
        d.rectangle([to_px(-w_mm / 2, y1_m), to_px(w_mm / 2, y0_m)], fill=red)
    dc = to_px(0, 51.9)
    dr = 1.55 * px_mm
    d.ellipse([dc[0] - dr, dc[1] - dr, dc[0] + dr, dc[1] + dr], fill=red)

    for sx in (-1.0, 1.0):
        pts = [(5.2, 41.5), (7.8, 43.3), (10.8, 43.4), (11.1, 41.3), (13.7, 41.5)]
        d.line([to_px(sx * x, y) for x, y in pts], fill=yellow_hi, width=max(3, int(1.6 * px_mm)))

    for sx in (-1.0, 1.0):
        pcx = sx * 40.60
        d.rectangle([to_px(pcx - 3.8, 40.8), to_px(pcx + 3.8, 5.2)], fill=yellow, outline=(210, 165, 16), width=2)
        d.rectangle([to_px(pcx - 4.7, 42.9), to_px(pcx + 4.7, 40.8)], fill=yellow_hi, outline=(210, 165, 16), width=1)
        dm = to_px(pcx, 42.9)
        dmr = 2.5 * px_mm
        d.pieslice([dm[0] - dmr, dm[1] - dmr, dm[0] + dmr, dm[1] + dmr], start=180, end=360, fill=yellow_hi)
        d.rounded_rectangle([to_px(pcx - 1.0, 38.0), to_px(pcx + 1.0, 8.4)], radius=int(1.0 * px_mm), fill=red)
        d.rectangle([to_px(pcx - 5.7, 5.2), to_px(pcx + 5.7, 2.8)], fill=yellow, outline=(205, 160, 14), width=1)
        d.rectangle([to_px(pcx - 7.4, 2.8), to_px(pcx + 7.4, 0.0)], fill=yellow, outline=(195, 150, 12), width=1)

    # Render exact 3D-extruded bold polygons (with realistic cast 3D shadow proportional to letter_height!)
    letter_mp, metrics = shape_bold_word_polygons(
        text=text,
        bold_offset=bold_offset,
        scale_pct=scale_pct,
        font_key=font_key,
    )
    metrics["letter_height_mm"] = round(float(letter_height), 2)
    metrics["layers_at_020"] = int(round(float(letter_height) / 0.20))

    sh_dx = 0.38 * float(letter_height)
    sh_dy = -0.45 * float(letter_height)

    # Pass 1: 3D relief drop shadow onto yellow signboard
    for poly in letter_mp.geoms:
        d.polygon([to_px(x + sh_dx, y + sh_dy) for x, y in poly.exterior.coords], fill=(184, 142, 10))
        for ir in poly.interiors:
            d.polygon([to_px(x + sh_dx, y + sh_dy) for x, y in ir.coords], fill=yellow)

    # Pass 2: Crisp raised bold 3D letter tops (with open counter holes)
    for poly in letter_mp.geoms:
        d.polygon([to_px(x, y) for x, y in poly.exterior.coords], fill=(22, 22, 20))
        for ir in poly.interiors:
            d.polygon([to_px(x, y) for x, y in ir.coords], fill=yellow)

    return img, metrics


HTML_UI = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>3D Bold BBMP Arch Signboard Studio</title>
<style>
  :root { --bg: #161513; --card: #22201c; --accent: #f4c618; --ok: #4ad66d; --text: #f3f1ec; }
  body { font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 28px; }
  .wrap { max-width: 1100px; margin: 0 auto; display: grid; grid-template-columns: 400px 1fr; gap: 28px; }
  .panel { background: var(--card); border-radius: 14px; padding: 22px; border: 1px solid #38332a; }
  h1 { font-size: 20px; margin: 0 0 6px; color: var(--accent); }
  p.sub { font-size: 13px; color: #a8a296; margin: 0 0 18px; line-height: 1.45; }
  label { display: block; font-size: 12px; font-weight: 600; color: #cfc9bc; margin: 13px 0 5px; text-transform: uppercase; letter-spacing: 0.04em; }
  input[type=text], select { width: 100%; box-sizing: border-box; padding: 10px 12px; border-radius: 8px; border: 1px solid #484136; background: #141310; color: #fff; font-size: 17px; }
  input[type=range] { width: 100%; accent-color: var(--accent); }
  .presets { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
  .chip { background: #2e2b24; color: #eee9de; border: 1px solid #484236; border-radius: 6px; padding: 5px 9px; font-size: 12px; cursor: pointer; }
  .chip:hover { border-color: var(--accent); color: var(--accent); }
  button.primary { width: 100%; margin-top: 20px; background: var(--accent); color: #161513; border: none; border-radius: 9px; padding: 13px 16px; font-weight: 800; cursor: pointer; font-size: 14px; }
  button.primary:disabled { opacity: 0.6; cursor: wait; }
  .preview-stage { display: flex; flex-direction: column; align-items: center; justify-content: center; }
  .preview-stage img { max-width: 100%; border-radius: 10px; box-shadow: 0 16px 36px rgba(0,0,0,0.45); }
  .metrics { margin-top: 16px; width: 100%; display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
  .metric-box { background: #171613; border: 1px solid #332f27; border-radius: 8px; padding: 10px 12px; text-align: center; }
  .metric-val { font-size: 16px; font-weight: 700; color: var(--ok); }
  .metric-lbl { font-size: 11px; color: #9c9689; margin-top: 3px; }
</style>
</head>
<body>
<div class="wrap">
  <div class="panel">
    <h1>3D Bold BBMP Arch Studio</h1>
    <p class="sub">Fuses bold 3D-printable Kannada or English letters directly onto <code>arch_signboard.stl</code> (0.40 mm nozzle, zero supports, no AMS required).</p>

    <label>Quick Single-Word Presets</label>
    <div class="presets">
      <span class="chip" onclick="setWord('ಬೆಂಗಳೂರು')">ಬೆಂಗಳೂರು (Original)</span>
      <span class="chip" onclick="setWord('ಜಯನಗರ')">ಜಯನಗರ</span>
      <span class="chip" onclick="setWord('ಇಂದಿರಾನಗರ')">ಇಂದಿರಾನಗರ</span>
      <span class="chip" onclick="setWord('ಮಲ್ಲೇಶ್ವರಂ')">ಮಲ್ಲೇಶ್ವರಂ</span>
      <span class="chip" onclick="setWord('ಕೋರಮಂಗಲ')">ಕೋರಮಂಗಲ</span>
      <span class="chip" onclick="setWord('BENGALURU')">BENGALURU</span>
      <span class="chip" onclick="setWord('INDIRANAGAR')">INDIRANAGAR</span>
    </div>

    <label>Sign Word (Kannada or English)</label>
    <input type="text" id="text" value="ಬೆಂಗಳೂರು" oninput="refresh()">

    <label>Font Style</label>
    <select id="font" onchange="refresh()">
      <option value="auto">Auto Signboard Heavy (Noto Kannada Bold / Lato Black)</option>
      <option value="arial_black">Arial Black (Ultra-Thick Block Sans)</option>
      <option value="lato_black">Lato Black (Rounded Signboard Sans)</option>
      <option value="kannada_sans">Noto Sans Kannada Bold</option>
      <option value="kannada_serif">Noto Serif Kannada Bold (Classic)</option>
    </select>

    <label>3D-Print Bold Thickening: +<span id="bVal">0.14</span> mm</label>
    <input type="range" id="bold_offset" min="0" max="38" value="14" oninput="document.getElementById('bVal').innerText=(this.value/100).toFixed(2); refresh()">

    <label>Raised 3D Letter Height: +<span id="hVal">1.25</span> mm</label>
    <input type="range" id="letter_height" min="60" max="220" step="5" value="125" oninput="document.getElementById('hVal').innerText=(this.value/100).toFixed(2); refresh()">

    <label>Word Scale (<span id="scVal">100</span>%)</label>
    <input type="range" id="scale" min="70" max="120" value="100" oninput="document.getElementById('scVal').innerText=this.value; refresh()">

    <button class="primary" id="dlBtn" onclick="downloadSTL()">Build &amp; Download 3D arch_signboard.stl</button>
  </div>

  <div class="panel preview-stage">
    <img id="prevImg" src="" alt="Live 3D Bold BBMP Arch Preview">
    <div class="metrics">
      <div class="metric-box">
        <div class="metric-val" id="mStroke">--</div>
        <div class="metric-lbl">Mean Stroke (0.42mm Walls)</div>
      </div>
      <div class="metric-box">
        <div class="metric-val" id="mSpan">--</div>
        <div class="metric-lbl">3D Text Span (W &times; H)</div>
      </div>
      <div class="metric-box">
        <div class="metric-val" id="mRelief">--</div>
        <div class="metric-lbl">3D Relief &amp; Open Counters</div>
      </div>
    </div>
  </div>
</div>

<script>
let timer = null;
function curCfg() {
  return {
    text: document.getElementById('text').value,
    font: document.getElementById('font').value,
    bold_offset: (parseInt(document.getElementById('bold_offset').value) / 100.0).toFixed(2),
    letter_height: (parseInt(document.getElementById('letter_height').value) / 100.0).toFixed(2),
    scale: parseInt(document.getElementById('scale').value)
  };
}
function setWord(w) {
  document.getElementById('text').value = w;
  refresh();
}
function refresh() {
  clearTimeout(timer);
  timer = setTimeout(async () => {
    const q = new URLSearchParams(curCfg()).toString();
    document.getElementById('prevImg').src = '/api/preview?' + q + '&_t=' + Date.now();
    const res = await fetch('/api/metrics?' + q);
    const m = await res.json();
    document.getElementById('mStroke').innerText = `${m.mean_stroke_mm} mm (~${m.walls_at_042}w)`;
    document.getElementById('mSpan').innerText = `${m.bbox_w_mm} × ${m.bbox_h_mm} mm`;
    document.getElementById('mRelief').innerText = `+${m.letter_height_mm} mm (${m.num_counters} holes)`;
  }, 110);
}
async function downloadSTL() {
  const btn = document.getElementById('dlBtn');
  btn.disabled = true;
  btn.innerText = 'Building Watertight 3D CAD Solid...';
  try {
    const cfg = curCfg();
    const res = await fetch('/api/stl', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(cfg)});
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    const slug = (cfg.text || 'bengaluru').trim().replace(/\\s+/g, '_').slice(0, 24);
    a.download = `arch_signboard_${slug}.stl`;
    a.click();
  } finally {
    btn.disabled = false;
    btn.innerText = 'Build & Download 3D arch_signboard.stl';
  }
}
refresh();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def _parse_cfg(self, qs):
        txt = qs.get("text", qs.get("line1", [DEFAULT_SIGN_TEXT]))[0]
        return {
            "text": txt,
            "bold_offset": float(qs.get("bold_offset", [str(DEFAULT_BOLD_OFFSET)])[0]),
            "letter_height": float(qs.get("letter_height", [str(DEFAULT_LETTER_HEIGHT)])[0]),
            "scale_pct": int(float(qs.get("scale", ["100"])[0])),
            "font_key": qs.get("font", ["auto"])[0],
        }

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_UI.encode("utf-8"))
        elif parsed.path == "/api/preview":
            cfg = self._parse_cfg(parse_qs(parsed.query))
            img, _ = render_arch_3d_bold_preview(**cfg, dpi=220)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(buf.getvalue())
        elif parsed.path == "/api/metrics":
            cfg = self._parse_cfg(parse_qs(parsed.query))
            _, metrics = shape_bold_word_polygons(
                text=cfg["text"],
                bold_offset=cfg["bold_offset"],
                scale_pct=cfg["scale_pct"],
                font_key=cfg["font_key"],
            )
            metrics["letter_height_mm"] = round(cfg["letter_height"], 2)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(metrics).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/stl":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            stl_bytes, _ = export_custom_arch_stl_bytes(
                sign_text=payload.get("text", DEFAULT_SIGN_TEXT),
                bold_offset=float(payload.get("bold_offset", DEFAULT_BOLD_OFFSET)),
                letter_height=float(payload.get("letter_height", DEFAULT_LETTER_HEIGHT)),
                scale_pct=int(float(payload.get("scale", 100))),
                font_key=payload.get("font", "auto"),
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/sla")
            self.end_headers()
            self.wfile.write(stl_bytes)


def main():
    parser = argparse.ArgumentParser(description="3D Bold Heritage Kempegowda BBMP Arch Signboard Customizer")
    parser.add_argument("--serve", type=int, default=0, help="Launch interactive 3D-Bold browser studio on port (e.g. 8085)")
    parser.add_argument("--text", "--line1", dest="text", type=str, default=DEFAULT_SIGN_TEXT, help="Single-word Kannada or English sign text")
    parser.add_argument("--bold-offset", type=float, default=DEFAULT_BOLD_OFFSET, help="Outward stroke thickening in mm (default: 0.22)")
    parser.add_argument("--letter-height", type=float, default=DEFAULT_LETTER_HEIGHT, help="Raised 3D letter height in mm (default: 1.25)")
    parser.add_argument("--scale", type=int, default=100, help="Word scale percentage (default: 100)")
    parser.add_argument("--font", type=str, default="auto", choices=list(FONT_PRESETS.keys()))
    parser.add_argument("--out", type=str, default="", help="Output STL path (e.g. projects/bbmp_signboard/custom_jayanagar.stl)")
    args = parser.parse_args()

    if args.serve > 0:
        print(f"3D Bold BBMP Arch Studio running at: http://localhost:{args.serve}")
        HTTPServer(("127.0.0.1", args.serve), Handler).serve_forever()
        return

    preview_img, metrics = render_arch_3d_bold_preview(
        text=args.text,
        bold_offset=args.bold_offset,
        letter_height=args.letter_height,
        scale_pct=args.scale,
        font_key=args.font,
        dpi=280,
    )
    mockup_path = os.path.join(SCRIPT_DIR, "inserts", "heritage_bengaluru_mockup.png")
    os.makedirs(os.path.dirname(mockup_path), exist_ok=True)
    preview_img.save(mockup_path, dpi=(280, 280))
    print(
        f"[Preview] {mockup_path} | '{metrics['text']}' ({metrics['bbox_w_mm']} x {metrics['bbox_h_mm']} mm, "
        f"mean stroke {metrics['mean_stroke_mm']} mm ~ {metrics['walls_at_042']} walls @ 0.42mm)"
    )

    if args.out:
        out_stl = os.path.abspath(args.out)
        if not out_stl.lower().endswith(".stl"):
            out_stl += ".stl"
        os.makedirs(os.path.dirname(out_stl), exist_ok=True)
        stl_bytes, _ = export_custom_arch_stl_bytes(
            sign_text=args.text,
            bold_offset=args.bold_offset,
            letter_height=args.letter_height,
            scale_pct=args.scale,
            font_key=args.font,
        )
        with open(out_stl, "wb") as f:
            f.write(stl_bytes)
        print(f"[Exported 3D STL] {out_stl} ({len(stl_bytes) / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
