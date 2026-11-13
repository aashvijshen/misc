"""Multi-part .3mf (Bambu Studio / AMS ready) and .zip archive exporter for MapMaker 3D.

Generates standard-compliant 3MF packages with named, color-tagged sub-objects
grouped into a single locked assembly so parts stay registered in 3D space when opened
in Bambu Studio, OrcaSlicer, PrusaSlicer, or Cura.
"""

import os
import zipfile
from typing import List, Dict, Any, Tuple
import numpy as np


CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
</Types>
"""

RELS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""


def _xml_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _deduplicate_mesh_vertices(vertices: np.ndarray, faces: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Welds coincident vertices (within 1e-4 mm) so 3MF topology is compact and strictly indexed."""
    if len(vertices) == 0 or len(faces) == 0:
        return vertices, faces
    quant = np.round(vertices.astype(np.float64) * 10000.0).astype(np.int64)
    _, unique_idx, inv_idx = np.unique(quant, axis=0, return_index=True, return_inverse=True)
    new_verts = vertices[unique_idx]
    new_faces = inv_idx[faces].astype(np.int32)
    # Filter degenerate triangles if any
    valid = (
        (new_faces[:, 0] != new_faces[:, 1])
        & (new_faces[:, 1] != new_faces[:, 2])
        & (new_faces[:, 2] != new_faces[:, 0])
    )
    return new_verts, new_faces[valid]


def export_3mf_assembly(
    filepath: str,
    parts: List[Dict[str, Any]],
    assembly_name: str = "MapMaker_3D_Memorabilia",
    bed_center_xy: Tuple[float, float] = (128.0, 128.0)
) -> str:
    """Writes a multi-part, color-tagged .3mf assembly archive.

    Args:
        filepath: Output .3mf path.
        parts: List of dicts: {'name': str, 'mesh': SolidMesh, 'color': '#RRGGBB'}.
        assembly_name: Root object name shown in Bambu Studio object tree.
        bed_center_xy: Build plate center (128, 128 for Bambu Lab A1 256x256mm).
    """
    valid_parts = [
        p for p in parts
        if p.get("mesh") is not None and len(p["mesh"].vertices) > 0 and len(p["mesh"].faces) > 0
    ]
    if not valid_parts:
        return ""

    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)

    # Shift global Z_min of combined assembly to 0.0 so assembly rests flat on build plate
    all_z_mins = [float(np.min(p["mesh"].vertices[:, 2])) for p in valid_parts]
    z_shift = -min(all_z_mins) if all_z_mins else 0.0

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
        'xmlns:m="http://schemas.microsoft.com/3dmanufacturing/material/2015/02">',
        f'  <metadata name="Title">{_xml_escape(assembly_name)}</metadata>',
        '  <metadata name="Application">MapMaker 3D</metadata>',
        '  <resources>',
        '    <basematerials id="1">',
    ]

    for p in valid_parts:
        cname = _xml_escape(p.get("name", "Part"))
        color_hex = p.get("color", "#E2E8F0").upper()
        if len(color_hex) == 7 and color_hex.startswith("#"):
            color_hex = color_hex + "FF"
        lines.append(f'      <base name="{cname}" displaycolor="{color_hex}"/>')

    lines.append('    </basematerials>')

    comp_ids = []
    for idx, p in enumerate(valid_parts):
        obj_id = idx + 2
        comp_ids.append(obj_id)
        pname = _xml_escape(p.get("name", f"Part_{idx + 1}"))
        verts, faces = _deduplicate_mesh_vertices(p["mesh"].vertices, p["mesh"].faces)

        lines.append(f'    <object id="{obj_id}" name="{pname}" type="model" pid="1" pindex="{idx}">')
        lines.append('      <mesh>')
        lines.append('        <vertices>')
        for vx, vy, vz in verts:
            lines.append(f'          <vertex x="{float(vx):.4f}" y="{float(vy):.4f}" z="{float(vz + z_shift):.4f}"/>')
        lines.append('        </vertices>')
        lines.append('        <triangles>')
        for f0, f1, f2 in faces:
            lines.append(f'          <triangle v1="{int(f0)}" v2="{int(f1)}" v3="{int(f2)}"/>')
        lines.append('        </triangles>')
        lines.append('      </mesh>')
        lines.append('    </object>')

    root_id = len(valid_parts) + 10
    lines.append(f'    <object id="{root_id}" name="{_xml_escape(assembly_name)}" type="model">')
    lines.append('      <components>')
    for cid in comp_ids:
        lines.append(f'        <component objectid="{cid}"/>')
    lines.append('      </components>')
    lines.append('    </object>')
    lines.append('  </resources>')
    bx, by = bed_center_xy
    lines.append('  <build>')
    lines.append(f'    <item objectid="{root_id}" transform="1 0 0 0 1 0 0 0 1 {bx:.2f} {by:.2f} 0"/>')
    lines.append('  </build>')
    lines.append('</model>')

    model_xml = "\n".join(lines).encode("utf-8")

    with zipfile.ZipFile(filepath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES_XML.strip().encode("utf-8"))
        zf.writestr("_rels/.rels", RELS_XML.strip().encode("utf-8"))
        zf.writestr("3D/3dmodel.model", model_xml)

    return filepath


def create_export_zip(export_dir: str, zip_filepath: str) -> str:
    """Bundles all generated STLs, 3MF, previews, and ASSEMBLY_GUIDE.md into a downloadable .zip."""
    abs_export = os.path.abspath(export_dir)
    abs_zip = os.path.abspath(zip_filepath)
    with zipfile.ZipFile(abs_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(abs_export):
            for fname in sorted(files):
                fpath = os.path.join(root, fname)
                if os.path.abspath(fpath) == abs_zip:
                    continue
                rel = os.path.relpath(fpath, abs_export)
                with open(fpath, "rb") as f_in:
                    zf.writestr(rel.replace("\\", "/"), f_in.read())
    return abs_zip
