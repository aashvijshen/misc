# Standing Instructions for 3D Design & 3D Printing

You are working in the 3D design workspace for functional 3D printing (using FreeCAD, Blender, and the Bambu Lab A1 printer).

## Mandatory Project Workflow & Tracking Rules

Whenever starting, updating, or iterating on a project in `~/playground/3d/projects/<project_name>/`:

1. **Maintain `PROJECT_LOG.md`**:
   - Every project folder **MUST** contain a `PROJECT_LOG.md` tracking:
     - **Goal & Requirements**: What the part is for, target dimensions, mating components.
     - **Component Breakdown**: Splitting complex assemblies into manageable parametric parts.
     - **Printer & Slicer Profile**: Target printer (Bambu A1), nozzle size (default: 0.4mm), line width (0.42mm), clearances/tolerances (e.g. 0.15mm–0.25mm).
     - **Current Status**: What is modeled, verified, sliced, or printed.
     - **Iteration Log & Learnings**: Record changes made in each iteration, physical fit test results, slicer notes, and learnings so any new agent can instantly pick up where the previous one stopped.

2. **Mandatory Multi-Part Assembly & Collision Simulation**:
   - For all multi-part assemblies, interlocking components, mating lids, or kinematic hinges:
     - **NEVER rely on visual estimation alone.**
     - **ALWAYS run programmatic 3D CAD collision and interference simulations** using OpenCASCADE Boolean intersection:
       ```python
       intersection = partA.common(partB)
       assert intersection.Volume == 0.0, f"Collision detected: {intersection.Volume:.2f} mm³"
       ```
     - For moving/tilting joints (e.g. hinges, sliders), simulate the assembly across the **entire operational range of motion** (e.g. $0^\circ, 15^\circ, 30^\circ, 45^\circ, 60^\circ, 75^\circ$) to guarantee zero mechanical interference before exporting deliverables.

3. **Standard Output Deliverables**:
   For every completed iteration of a part, generate the following standard artifacts by default:
   - `model.FCStd`: The native FreeCAD source file with full parametric history.
   - `model.stl` (or `.3mf`): Slicer-ready triangle mesh.
   - `previews/diagnostic_views.png`: 4-view orthographic and isometric diagnostic preview sheet.
   - *(Note: Do **NOT** generate `.step` files by default. Only export `.step` files when the user specifically asks for them.)*

4. **Design for 3D Printing Principles (Bambu A1)**:
   - **Tolerances**: Parameterize all clearances (e.g. `clearance = 0.20 mm`) as top-level variables.
   - **Wall Thicknesses**: Size walls in multiples of line width (e.g. 2 perimeters = 0.84mm, 3 perimeters = 1.26mm, 4 perimeters = 1.68mm).
   - **Overhangs**: Prefer 45° chamfers over 90° overhangs to eliminate the need for support material.
   - **Bed Adhesion & Orientation**: Design parts with a clear, flat primary face for optimal print bed contact.
   - **Manifoldness**: Ensure geometry is 100% watertight with zero self-intersections.

5. **Mandatory Maker's Mark / Brand Signature (`~/playground/3d/tools/maker_mark.py`)**:
   - Every 3D print project **MUST** incorporate the Maker Logo on at least one primary component using `~/playground/3d/tools/maker_mark.py` (or `~/playground/3d/tools/maker_logo.svg` for custom workflows).
   - **Intentional Placement & Mode Selection (Propose in Plan)**: Do **not** blindly default to the underside. Evaluate each design's aesthetics, function, and print orientation, and explicitly propose the best insertion mode and target face in your design plan:
     - **`additive` (Raised Emboss)**: Ideal for visible top decks, mechanical frames, angled plinths, side walls (`maker_mark.py` automatically adds `45°` support-free lower ramps on vertical walls when `depth_mm >= 0.45`), or top-layer pause-at-height color swaps. **Never** place an `additive` mark on a `Z = 0` print-bed adhesion face.
     - **`subtractive` (Engraved Deboss)**: Ideal for `Z = 0` undersides when exterior sculptural surfaces should remain pure, flush resting trays/coasters where items sit flat, or crisp shallow architectural engravings (`0.40–0.60 mm`).
     - **`cartouche` (Flush Raised Emblem in Recessed Stadium Pocket)**: Ideal when you want a positive tactile/paintable raised mark that remains flush with the surrounding surface (including `Z = 0` bases, side walls, or smooth inset badges on Fuzzy-Skin / organic meshes).
   - **Post-Mark Verification**: Always apply the Maker's Mark **before** running OpenCASCADE Boolean collision checks and watertight manifold audits so the signature never interferes with mating parts or introduces non-manifold edges.
