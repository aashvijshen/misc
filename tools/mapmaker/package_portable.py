#!/usr/bin/env python3
"""Creates a clean, lightweight cross-OS / Windows portable .zip archive (`dist/MapMaker3D_Windows_Portable.zip`).

Includes only source code, GUI, launchers (with Windows CRLF line endings on .bat files),
tests, and documentation — excluding heavy generated STL/3MF exports and caches.
"""

import os
import zipfile

ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
DIST_DIR = os.path.join(ROOT_DIR, "dist")

INCLUDE_FILES = [
    "app.py",
    "mapmaker_cli.py",
    "package_portable.py",
    "requirements.txt",
    "run_mapmaker.bat",
    "mapmaker_cli.bat",
    "build_windows_exe.bat",
    "run_mapmaker.sh",
    "README_WINDOWS.md",
    "PROJECT_LOG.md",
    "Thoughts.md",
    "gui/index.html",
]

INCLUDE_DIRS = [
    "engine",
    "tests",
]


def build_portable_zip(output_zip: str = "") -> str:
    os.makedirs(DIST_DIR, exist_ok=True)
    if not output_zip:
        output_zip = os.path.join(DIST_DIR, "MapMaker3D_Windows_Portable.zip")

    entries = []
    for rel in INCLUDE_FILES:
        full = os.path.join(ROOT_DIR, rel)
        if os.path.exists(full):
            entries.append((full, f"MapMaker3D/{rel}"))

    for d in INCLUDE_DIRS:
        d_full = os.path.join(ROOT_DIR, d)
        if not os.path.exists(d_full):
            continue
        for r_dir, subdirs, files in os.walk(d_full):
            subdirs[:] = [
                s for s in sorted(subdirs)
                if s not in ("__pycache__", "output", "output_tiling") and not s.startswith(".")
            ]
            for fn in sorted(files):
                if fn.endswith(".py"):
                    fp = os.path.join(r_dir, fn)
                    rel_p = os.path.relpath(fp, ROOT_DIR).replace("\\", "/")
                    entries.append((fp, f"MapMaker3D/{rel_p}"))

    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for src_path, arc_name in entries:
            with open(src_path, "rb") as f:
                raw = f.read()
            # Ensure Windows .bat files always have standard CRLF line endings!
            if src_path.lower().endswith(".bat"):
                raw = raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            zf.writestr(arc_name, raw)

    size_kb = os.path.getsize(output_zip) / 1024.0
    print(f"[✓] Built portable Windows/Cross-OS bundle: {output_zip} ({size_kb:.1f} KB, {len(entries)} files)")
    return output_zip


if __name__ == "__main__":
    build_portable_zip()
