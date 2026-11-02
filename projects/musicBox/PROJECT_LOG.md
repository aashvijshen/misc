# Kikkerland 15-Note Music Box Pattern Studio — Project Log

## Goal & Requirements
Build a local web application that lets the user:
1. Search songs over the internet (**Music Box Maniacs** `.mid` library + **The Session** ABC API + built-in classics + local `.mid`/`.abc` file upload).
2. Analyze the song's musical key/scale, warn when accidentals do not fit the **Kikkerland 15-note C Major diatonic scale**, and rank optimal semitone/octave transpositions.
3. Interactively select **which part of the song** (start/end slice + MIDI tracks) to use with visual piano-roll feedback, live paper-length budgeting, and in-browser **WebAudio music-box playback** (comparing original vs. 15-note quantized).
4. Export/guide punching in two paper workflows:
   - **Existing Kikkerland Blank Strip Mode** (4 sheets owned): step-by-step interactive row/column punch checklist mapped to the physical `C D E F G A B C D E F G A B C` strip with bold `E G B D F` treble-staff reference lines.
   - **Printable A4 Sheet Mode**: exact `1:1` millimeter PDF & SVG generator packing 4 strips (`41.0 mm` wide each) per A4 portrait sheet with cut lines, tapered feed tip, numbered glue tabs, `2.0 mm` punch circles, and a `50.0 mm` print-scale calibration ruler.

## Physical Hardware Specifications (Verified from User's Strip)
- **Model**: Kikkerland *Make Your Own Music Box Kit* (15-note hand-cranked movement).
- **Columns (15 notes, 2-octave C Major)**:
  - Printed labels: `C D E F G A B C D E F G A B C` (Columns 1–15).
  - Bold vertical reference lines: Columns **3 (`E`), 5 (`G`), 7 (`B`), 9 (`D`), 11 (`F`)** (standard 5-line treble staff).
- **Dimensions**:
  - Strip width: `41.0 mm`
  - Column pitch (center-to-center): `2.0 mm` (`28.0 mm` span across 15 columns, `6.5 mm` left/right edge margins)
  - Punch hole diameter: `2.0 mm`
  - Existing blank strip usable length: `~41.2 cm` (`412 mm`, configurable in UI; grid spacing `2.0 mm` / `4.0 mm` / `8.0 mm` configurable)
  - Minimum same-note longitudinal repeat distance: `~4.5 mm` (prevents star-wheel tooth skipping)
  - Recommended A4 print media: `180–220 gsm` cardstock (standard `80 gsm` office copy paper slips in the feed rollers)

## Component Breakdown
- `backend/kikkerland.py` — Physical strip constants, 15-note C-major pitch table, and bold-line definitions.
- `backend/music_engine.py` — MIDI & ABC parser, General MIDI 128 track analyzer, key/scale detector, optimal semitone/octave transposition solver, and mechanical repeat-distance checker.
- `backend/search_ranker.py` — Relevance scorer resolving generic single-word titles and compound `Song + Artist` queries.
- `backend/providers/` — Online search & artist catalog adapters (`musicboxmaniacs.py`, `freemidi.py`, `midiworld.py`, `thesession.py`, `builtin_library.py`).
- `backend/pdf_generator.py` — True-scale `1:1` millimeter A4 multi-strip PDF (`reportlab`) & SVG generator.
- `backend/app.py` — FastAPI local server and REST endpoints (`/api/hardware`, `/api/search`, `/api/artists`, `/api/artists/catalog`, `/api/load`, `/api/upload`, `/api/arrange`, `/api/export/pdf`, `/api/export/svg`).
- `frontend/` — Full-bleed 3-column **KIKKER-15** industrial console (`index.html`, `style.css`, `app.js`) with Artist Catalog Browser, CRT oscilloscope section slicer, WebAudio music-box synth, mouse-driven brass hand-crank, manual hole editor, Kikkerland Die-Punch HUD + checklist, and `1:1` A4 PDF/SVG export.
- `tests/` — Automated pytest suite (`11` tests) validating transposition, scale warnings, repeat collision checks, search ranking, artist catalog parsing, and `1:1` A4 PDF/SVG geometry.

## Current Status
- [x] Plan reviewed and approved by user; physical strip specs confirmed (`C..C` labels, `E G B D F` bold lines, `2 mm` spacing, `41.2 cm` usable length).
- [x] Implemented backend core engine, multi-provider online search + Artist Catalog Browser, and true-scale `1:1` A4 PDF/SVG generator.
- [x] Implemented full-screen 3-column **KIKKER-15** UI with WebAudio preview, rotatable hand-crank, section slicer, interactive strip hole editor, and Kikkerland punch checklist.
- [x] Verified with 11 automated pytest unit/integration tests and live end-to-end provider checks.

## Iteration Log & Learnings
- **Iteration 1 (2026-10-30)**: Verified outbound connectivity from workspace: `musicboxmaniacs.com` (`200 OK`, CloudFront `.mid` links available) and `thesession.org` (`200 OK`, JSON ABC API) work cleanly, while `bitmidi.com` returns `429` Cloudflare blocks. Confirmed physical Kikkerland strip uses treble-staff bold lines on `E G B D F` (columns 3, 5, 7, 9, 11).
- **Iteration 2 (2026-11-02)**:
  - Diagnosed why `"Holiday Green Day"` missed: Music Box Maniacs runs literal substring queries and lacked *Holiday*, while pop/rock MIDI archives (`freemidi.org`, `midiworld.com`) separate Artist from Song Title.
  - Added `freemidi.py` (multi-page artist catalog crawler + session-aware `.mid` fetcher), `midiworld.py`, and `search_ranker.py` (relevance scorer handling generic one-word song titles + compound `Song + Artist` queries).
  - Enriched `parse_midi_bytes` with General MIDI 128 instrument names and automatic bass-track de-prioritization on full-band rock/pop MIDIs.
  - Complete UI overhaul into **KIKKER-15 // Electro-Mechanical Punch-Tape Workbench** (gunmetal industrial console, recessed phosphor-cyan VFD readouts, CRT oscilloscope gate slicer, live vibrating 15-tine steel comb, interactive mouse-rotatable brass hand-crank, Die-Punch Operator HUD, and 1:1 A4 blueprint plotter).
- **Iteration 3 (2026-11-02)**:
  - Expanded layout to a full-bleed `100vw × 100vh` edge-to-edge **3-Column Workstation** (Left: Crate Digger + Oscilloscope Slicer & Scale Computer; Center: Full-height dynamically scaled 15-Tine Steel Comb + Hand-Crank + Interactive Strip; Right: Simultaneous Die-Punch Operator HUD & Row Log / 1:1 A4 Blueprint Plotter).
