# KIKKER-15 // Kikkerland 15-Note Music Box Studio

Full-screen electro-mechanical punch-tape web studio for turning online or local melodies into ready-to-punch patterns for the **Kikkerland Make Your Own Music Box Kit** (15-note C Major comb).

## Quick Start

### Windows 10 / 11 (One-Click)
1. Install **Python 3.10+** from [python.org/downloads/windows](https://www.python.org/downloads/windows/) (during setup, check **"Add python.exe to PATH"** or keep the default `py` Python Launcher enabled).
2. Double-click **`run_windows.bat`** in File Explorer (or run `.\run_windows.ps1` in PowerShell).
3. On first launch, the script automatically creates `.venv`, installs `requirements.txt`, picks an open local port (`8000` by default, auto-falling back if busy), and opens **`http://127.0.0.1:8000`** in your browser. Subsequent launches skip `pip install` automatically via `.venv\.deps_stamp`.

```powershell
# Optional PowerShell flags:
.\run_windows.ps1 -Port 8080 -NoBrowser
```

### Linux / macOS
```bash
./run.sh
```
*(Automatically creates `.venv` and installs `requirements.txt` on first run, then opens **http://127.0.0.1:8000**.)*

## Features

- **Multi-Source Song Search & Artist Catalog Browser**:
  - Searches **Music Box Maniacs** (`.mid`), **FreeMIDI** (`freemidi.org` rock/pop catalogs & `.mid`), **MidiWorld** (`midiworld.com`), **The Session** (folk `.abc` API), and built-in classics in parallel.
  - Dedicated **Artist Catalog Browser** lets you look up an artist (e.g., *Green Day*, *Queen*, *Radiohead*) and browse/filter every song in their catalog, paired with relevance ranking (`backend/search_ranker.py`) so generic one-word song titles sort cleanly.
  - Also supports local `.mid` / `.abc` file upload and direct URL import.
- **Scale Match, GM Track Filtering & Smart Transposition**:
  - Automatically detects musical key/scale, labels all 128 General MIDI instruments (de-prioritizing bass/percussion tracks on full-band MIDIs), and ranks optimal semitone/octave shifts (`-36..+36`) into the 15-note C Major range (`C4–C6`).
  - Warns clearly when non-diatonic chromatic notes exist, with modes to omit accidentals, snap to the nearest white key, or manually toggle punch holes directly on the strip.
  - Enforces a `< 4.5 mm` same-note repeat guard to prevent star-wheel tooth skipping.
- **3-Column KIKKER-15 Workstation UI**:
  - **Left Bay**: Crate Digger search/artist catalog + phosphor-green CRT oscilloscope section slicer & scale computer.
  - **Center Bay**: Full-height interactive punch strip, animated 15-tine steel comb, WebAudio music-box synthesizer, mouse-rotatable brass hand-crank, and `Q`–`C` computer-keyboard tine plucking (`Space` to play/stop).
  - **Right Bay**: Simultaneous **Die-Punch Operator HUD** + row-by-row checklist and **1:1 A4 Blueprint Plotter**.
- **Two Paper Output Workflows**:
  1. **Existing Kikkerland Blank Paper Mode**: Step-by-step interactive row/column punch guide mapped to the physical `C D E F G A B C D E F G A B C` strip and its bold `E G B D F` treble-staff lines (`41.0 mm` width, `2.0 mm` column pitch, `412 mm` usable length). Displays **empty grid spaces** explicitly (`ALL LINES + SPACES` 1-line-per-Spacebar mode or `NOTES + GAP COUNT` mode with visual space meters) so you never need to read or subtract line numbers.
  2. **Printable A4 Sheet Mode**: Exact `1:1` millimeter PDF & SVG generator packing 4 strips (`41.0 mm` wide each) per A4 portrait sheet (`180–220 gsm` cardstock recommended) with cut lines, a tapered feed tip on Strip 1, numbered glue tabs on Strips 2..N, `2.0 mm` punch circles, and a `50.0 mm` print-scale calibration ruler.

## Project Structure

- `launch.py` — Cross-platform UTF-8 server entrypoint with automatic port fallback and browser auto-open.
- `run_windows.bat` / `run_windows.ps1` — One-click Windows CMD/Explorer and PowerShell launchers with automatic `.venv` provisioning.
- `run.sh` — Linux/macOS launcher with automatic `.venv` provisioning.
- `backend/kikkerland.py` — Physical strip geometry (`41.0 mm` width, `2.0 mm` spacing, `6.5 mm` margins, bold `E G B D F` landmarks).
- `backend/music_engine.py` — MIDI & ABC parser, GM instrument analyzer, key detector, transposition optimizer, repeat-distance guard, and checklist builder.
- `backend/search_ranker.py` — Relevance scorer for compound `Song + Artist` and generic single-word title queries.
- `backend/providers/` — Online search & artist catalog adapters (`freemidi.py`, `midiworld.py`, `musicboxmaniacs.py`, `thesession.py`, `builtin_library.py`).
- `backend/pdf_generator.py` — True-scale `1:1` millimeter A4 multi-strip PDF (`reportlab`) and SVG generator.
- `backend/app.py` — FastAPI local server and REST API endpoints.
- `frontend/` — Full-bleed 3-column KIKKER-15 workbench UI (`index.html`, `style.css`, `app.js`).
- `tests/test_music_box_studio.py` — Automated pytest suite covering transposition, scale warnings, repeat guards, search ranking, artist parsing, and `1:1` A4 PDF/SVG geometry.

## Running Tests

```bash
.venv/bin/pytest -v
```
