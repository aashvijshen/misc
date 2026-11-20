#!/usr/bin/env python3
"""Scans 3D projects in ../../projects/ to compute STL volumes, surface areas,
estimated sliced filament weights (g), Bambu A1 print times (hrs), and media assets.
"""

import json
import math
import os
import struct
from typing import Dict, List, Tuple

SHOWCASE_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_ROOT = os.path.abspath(os.path.join(SHOWCASE_DIR, "..", ".."))
PROJECTS_DIR = os.path.join(WORKSPACE_ROOT, "projects")
CATALOG_PATH = os.path.join(SHOWCASE_DIR, "catalog_data.json")

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIDEO_EXTS = {".mp4", ".webm", ".mov"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS
PLA_DENSITY_G_CM3 = 1.24


def compute_stl_metrics(stl_path: str) -> Tuple[float, float, float]:
    """Returns (solid_cm3, area_cm2, est_sliced_grams) for a binary or ASCII STL."""
    size = os.path.getsize(stl_path)
    if size < 84:
        return 0.0, 0.0, 0.0

    with open(stl_path, "rb") as f:
        f.read(80)
        tri_count = struct.unpack("<I", f.read(4))[0]
        expected_binary_size = 84 + tri_count * 50

        vol_mm3 = 0.0
        area_mm2 = 0.0

        if expected_binary_size == size:
            data = f.read()
            for i in range(tri_count):
                off = i * 50 + 12
                x1, y1, z1, x2, y2, z2, x3, y3, z3 = struct.unpack(
                    "<9f", data[off : off + 36]
                )
                vol_mm3 += (
                    x1 * (y2 * z3 - y3 * z2)
                    - y1 * (x2 * z3 - x3 * z2)
                    + z1 * (x2 * y3 - x3 * y2)
                ) / 6.0
                ux, uy, uz = x2 - x1, y2 - y1, z2 - z1
                vx, vy, vz = x3 - x1, y3 - y1, z3 - z1
                cx = uy * vz - uz * vy
                cy = uz * vx - ux * vz
                cz = ux * vy - uy * vx
                area_mm2 += 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)
        else:
            f.seek(0)
            verts = []
            for raw in f:
                line = raw.decode("utf-8", errors="ignore").strip()
                if line.startswith("vertex "):
                    parts = line.split()
                    if len(parts) >= 4:
                        verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
                        if len(verts) == 3:
                            (x1, y1, z1), (x2, y2, z2), (x3, y3, z3) = verts
                            verts = []
                            vol_mm3 += (
                                x1 * (y2 * z3 - y3 * z2)
                                - y1 * (x2 * z3 - x3 * z2)
                                + z1 * (x2 * y3 - x3 * y2)
                            ) / 6.0
                            ux, uy, uz = x2 - x1, y2 - y1, z2 - z1
                            vx, vy, vz = x3 - x1, y3 - y1, z3 - z1
                            cx = uy * vz - uz * vy
                            cy = uz * vx - ux * vz
                            cz = ux * vy - uy * vx
                            area_mm2 += 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)

    vol_mm3 = abs(vol_mm3)
    shell_mm3 = min(vol_mm3, area_mm2 * 0.90)
    sliced_mm3 = shell_mm3 + max(0.0, vol_mm3 - shell_mm3) * 0.15
    solid_cm3 = round(vol_mm3 / 1000.0, 2)
    area_cm2 = round(area_mm2 / 100.0, 2)
    est_grams = round((sliced_mm3 / 1000.0) * PLA_DENSITY_G_CM3, 1)
    return solid_cm3, area_cm2, est_grams


def classify_media_kind(ext: str, folder: str) -> str:
    if ext in VIDEO_EXTS:
        return "video"
    if ext == ".gif":
        return "gif"
    return "photo" if folder == "photos" else "render"


def media_url_exists(url: str) -> bool:
    parts = [p for p in url.split("/") if p]
    if len(parts) < 4 or parts[0] != "media":
        return False
    target = os.path.join(PROJECTS_DIR, parts[1], parts[2], *parts[3:])
    return os.path.isfile(target)


def list_project_media(proj_dir: str, slug: str) -> List[Dict]:
    """Discovers photos/ first, then non-diagnostic previews/."""
    media = []
    for folder in ("photos", "previews"):
        sub = os.path.join(proj_dir, folder)
        if not os.path.isdir(sub):
            continue
        for fn in sorted(os.listdir(sub)):
            ext = os.path.splitext(fn)[1].lower()
            if ext not in MEDIA_EXTS:
                continue
            is_diag = folder == "previews" and (
                "diagnostic" in fn.lower() or "coupon" in fn.lower()
            )
            media.append(
                {
                    "url": f"/media/{slug}/{folder}/{fn}",
                    "label": os.path.splitext(fn)[0].replace("_", " ").title(),
                    "kind": classify_media_kind(ext, folder),
                    "isDiagnostic": is_diag,
                }
            )

    media.sort(
        key=lambda m: (
            1 if m["isDiagnostic"] else 0,
            0 if m["url"].startswith(f"/media/{slug}/photos/") else 1,
        )
    )
    return media


def scan_single_project(slug: str) -> Dict:
    """Scans STL parts and media inside projects/<slug>."""
    proj_dir = os.path.join(PROJECTS_DIR, slug)
    stl_parts = []
    if os.path.isdir(proj_dir):
        candidates = []
        for fn in sorted(os.listdir(proj_dir)):
            if fn.lower().endswith(".stl"):
                low = fn.lower()
                if any(
                    skip in low
                    for skip in ("full_assembly", "reference", "model.stl", "monolithic")
                ):
                    continue
                candidates.append(fn)

        if not candidates and os.path.isfile(os.path.join(proj_dir, "model.stl")):
            candidates = ["model.stl"]

        for fn in candidates:
            full = os.path.join(proj_dir, fn)
            solid_cm3, area_cm2, est_g = compute_stl_metrics(full)
            stl_parts.append(
                {
                    "file": fn,
                    "solidCm3": solid_cm3,
                    "areaCm2": area_cm2,
                    "estGrams": est_g,
                }
            )

    total_g = round(sum(p["estGrams"] for p in stl_parts), 1)
    est_hours = (
        round(max(0.5, total_g / 22.0 + len(stl_parts) * 0.12), 1) if total_g > 0 else 1.5
    )
    media = list_project_media(proj_dir, slug)
    return {
        "slug": slug,
        "scannedParts": stl_parts,
        "scannedGrams": total_g,
        "scannedPrintHours": est_hours,
        "discoveredMedia": media,
    }


def sync_catalog_with_disk(catalog: Dict) -> Dict:
    """Updates scanned STL stats & newly added photos without resurrecting deleted previews."""
    if not os.path.isdir(PROJECTS_DIR):
        return catalog

    existing_by_slug = {item["slug"]: item for item in catalog.get("items", [])}

    for slug in sorted(os.listdir(PROJECTS_DIR)):
        proj_dir = os.path.join(PROJECTS_DIR, slug)
        if not os.path.isdir(proj_dir) or slug.startswith(".") or slug == "lamps":
            continue

        scan = scan_single_project(slug)
        if slug in existing_by_slug:
            item = existing_by_slug[slug]
            item["scannedParts"] = scan["scannedParts"]
            item["scannedGrams"] = scan["scannedGrams"]
            item["scannedPrintHours"] = scan["scannedPrintHours"]

            excluded = set(item.get("excludedMedia", []))
            kept_media = [
                m
                for m in item.get("media", [])
                if m["url"] not in excluded and media_url_exists(m["url"])
            ]
            known_urls = {m["url"] for m in kept_media} | excluded

            new_items = [
                m
                for m in scan["discoveredMedia"]
                if m["url"] not in known_urls and not m["isDiagnostic"]
            ]
            real_new = [m for m in new_items if "/photos/" in m["url"]]
            render_new = [m for m in new_items if "/photos/" not in m["url"]]
            item["media"] = real_new + kept_media + render_new
        else:
            non_diag = [m for m in scan["discoveredMedia"] if not m["isDiagnostic"]]
            if scan["scannedParts"] or non_diag:
                pretty = slug.replace("_", " ").title()
                new_item = {
                    "id": slug,
                    "slug": slug,
                    "name": pretty,
                    "summary": "",
                    "category": "Drafts",
                    "inDeck": False,
                    "dimensions": "—",
                    "filamentGrams": scan["scannedGrams"] or 60.0,
                    "filamentRatePerKg": catalog.get("settings", {}).get(
                        "defaultFilamentPerKg", 1350
                    ),
                    "printHours": scan["scannedPrintHours"] or 2.5,
                    "plateSwaps": max(1, len(scan["scannedParts"])),
                    "assemblyMins": 10,
                    "paintingMins": 0,
                    "batchSize": 1,
                    "bom": [],
                    "price": 799,
                    "swatches": ["matte-cream", "charcoal-slate"],
                    "media": non_diag[:4] if non_diag else scan["discoveredMedia"][:2],
                    "excludedMedia": [],
                    "variants": [],
                    "scannedParts": scan["scannedParts"],
                    "scannedGrams": scan["scannedGrams"],
                    "scannedPrintHours": scan["scannedPrintHours"],
                }
                catalog.setdefault("items", []).append(new_item)

    return catalog


if __name__ == "__main__":
    if os.path.isfile(CATALOG_PATH):
        with open(CATALOG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        updated = sync_catalog_with_disk(data)
        with open(CATALOG_PATH, "w", encoding="utf-8") as f:
            json.dump(updated, f, indent=2, ensure_ascii=False)
        print(f"Synced {len(updated.get('items', []))} projects in {CATALOG_PATH}")
