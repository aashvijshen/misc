# MapMaker 3D: Architecture, Specification & Progress

## 1. Executive Summary & Vision

**MapMaker 3D** is an open, modular software engine and design tool that transforms geographic data (Digital Elevation Models, OpenStreetMap 3D building vectors, and transit/travel routes) into precision, multi-part, 3D-printable terrain models.

The system is optimized for modern desktop FDM printers (with the **Bambu Lab A1** as the reference default profile), but **every single parameter**—from nozzle diameter and layer height to build volume, tiling dimensions, and joint tolerances—is fully configurable.

### Key Capabilities
- **Geocoding & Interactive Boundary Selection**: Search global locations by name or bounding box, with support for arbitrary framing shapes (rectangular, circular, elliptical, N-gon polygon, or natural territorial borders like coastlines).
- **Automated Parametric Tiling**: Seamlessly subdivide massive geographic prints (e.g., $1200 \times 900\text{ mm}$) into printable chunks sized to any target print bed, equipped with blind alignment dowels or framing joints.
- **Parametric Topography & Urban Extrusions**: Configurable vertical exaggeration (Z-scale) for mountains and terrain, plus OSM 3D building height extrusion.
- **Additive Manufacturing Verification**: Algorithmic nozzle-size printability audits (identifying thin walls, fragile spires, and non-printable details before slicing).
- **Dual-Mode Multi-Color & Path Assembly**:
  - *Mode A (Single Extruder Snap/Slide-In)*: Recessed negative channels with parameterized tolerance clearance ($0.15 - 0.25\text{ mm}$) for separate snap-in path strips.
  - *Mode B (Bambu AMS Multi-Color)*: Co-planar multi-body `.3mf` assemblies with distinct color metadata for zero-assembly multi-material prints.
- **Viewing Orientation Compensation**: Adaptive landmark pins and icons tailored for horizontal tabletop viewing or front-facing vertical wall-hanging displays.

---

## 2. Fully Configurable System Parameters

All dimensions in millimeters unless otherwise specified. Defaults are tuned for the Bambu Lab A1 with a standard $0.4\text{ mm}$ nozzle.

### 2.1 Hardware & Slicer Envelope Profile
| Parameter | Default Value | Description |
| :--- | :--- | :--- |
| `printer_name` | `"Bambu Lab A1"` | Target printer profile identifier |
| `bed_width` ($X$) | `256.0 mm` | Maximum physical bed width |
| `bed_depth` ($Y$) | `256.0 mm` | Maximum physical bed depth |
| `bed_height` ($Z$) | `256.0 mm` | Maximum printable build height |
| `bed_edge_buffer` | `3.0 mm` | Safety margin from physical bed edges |
| `effective_bed_x` | `250.0 mm` | $X$-dimension per tile (`bed_width - 2 * buffer`) |
| `effective_bed_y` | `250.0 mm` | $Y$-dimension per tile (`bed_depth - 2 * buffer`) |
| `nozzle_diameter` | `0.40 mm` | Nominal nozzle aperture diameter |
| `extrusion_line_width`| `0.42 mm` | Default sliced bead line width |
| `layer_height` | `0.16 mm` | Vertical layer resolution for Z contours |
| `min_printable_wall` | `0.84 mm` | $2 \times \text{line width}$; minimum self-supporting wall |

### 2.2 Assembly & Tolerancing Profiles (Parametric)
| Parameter | Default Value | Description |
| :--- | :--- | :--- |
| `joint_clearance` | `0.20 mm` | Per-side horizontal clearance for sliding/snap-in paths |
| `enable_dowels` | `true` | Enable subterranean alignment joints (toggleable) |
| `dowel_type` | `"flat_biscuit"`| Dowel geometry: `"flat_biscuit"` (for $\ge 3.5\text{mm}$) or `"round"` |
| `biscuit_thickness`| `1.60 mm` | Vertical thickness of flat alignment spline (8 layers @ 0.2mm) |
| `pocket_height` | `1.85 mm` | Vertical slot height in tile side wall ($+0.25\text{mm}$ clearance) |
| `biscuit_width` | `12.0 mm` | Lateral width of alignment spline |
| `pocket_width` | `14.0 mm` | Lateral slot width in tile side wall ($+2.0\text{mm}$ lateral float) |
| `biscuit_length` | `12.0 mm` | Total spline depth ($5.5\text{mm}$ per tile with $1.0\text{mm}$ safety margin) |
| `base_slab_height` | `4.0 mm` | Minimum solid floor underneath lowest terrain point |
| `chamfer_angle` | `45.0 deg` | Entry lead-in chamfer for sliding paths and sockets |

---

## 3. Core Functional Modules

```
 ┌───────────────────────┐      ┌─────────────────────────┐      ┌────────────────────────┐
 │   1. Location & GUI   │ ───► │  2. Geospatial Pipeline │ ───► │  3. Mesh Engine & CSG  │
 │  - Nominatim Search   │      │  - AWS Terrarium DEM    │      │  - Terrain Triangulation│
 │  - MapLibre / Viewport│      │  - OSM Overpass Vector  │      │  - Building Extrusion  │
 │  - Canvas & Base Crop │      │  - OSRM / Vector Paths  │      │  - Path Boolean Inset  │
 └───────────────────────┘      └─────────────────────────┘      └────────────────────────┘
                                                                              │
                                ┌─────────────────────────┐                   ▼
                                │  5. Slicer Deliverables │ ◄─── ┌────────────────────────┐
                                │  - Multi-body .3mf      │      │  4. Tiling & DFAM QA   │
                                │  - Individual .stl files│      │  - Grid Subdivision    │
                                │  - Clean CAD .step base │      │  - Dowel Socket Insets │
                                │  - 4-View Diagnostic PNG│      │  - Nozzle Wall Audit   │
                                └─────────────────────────┘      └────────────────────────┘
```

### Module 1: Location Discovery & Boundary Canvas
- **Geocoding & Viewport**: Nominatim search engine resolves queries to GPS coordinates and bounding boxes ($S, W, N, E$).
- **Canvas Sizing**: User sets physical target display dimensions ($W_{\text{canvas}} \times H_{\text{canvas}}$ in mm).
- **Base Geometry Modes**:
  1. *Geometric Primitive*: Rectangle, Square, Circle, Ellipse, Regular N-gon (hexagon, octagon, etc.).
  2. *Territorial Boundary*: Outer boundary conforms to the official coastline or geopolitical border (e.g. outline of Japan).
  3. *Custom Clipping*: Draggable cutting planes or polygonal clip loops (e.g., cutting off northern Manhattan above Sugar Hill).

### Module 2: Geospatial Acquisition Pipeline
- **Elevation (DEM)**: AWS Open Data Terrarium tiles decoded via:
  $$\text{Elevation (m)} = \left(R \times 256 + G + \frac{B}{256}\right) - 32768$$
- **Topography Controls**:
  - `topography_enabled`: `true` (3D relief) or `false` (flat map).
  - `vertical_exaggeration`: Open-ended continuous multiplier (e.g. $0.5\times, 1.0\times, 10\times, 100\times$, etc.) or direct millimeter target (`target_relief_height_mm`) to scale mountain elevation independently of horizontal distances.
- **Urban 3D Structures**:
  - OpenStreetMap Overpass API fetches building footprints (`way["building"]`).
  - Height resolved from: explicit `height` tag $\rightarrow$ `building:levels` $\times 3.0\text{ m}$ $\rightarrow$ default fallbacks.
  - Extruded vertically with independent, unconstrained `building_height_scale`.

### Module 3: Routing, Landmarks & Orientation Compensation
- **Path Generation**:
  - *Route Matching*: OSRM routing engine matches waypoints along streets/trails.
  - *Freehand Drag*: Interactive spline nodes dragged on top of the terrain mesh.
- **Landmark Highlights (POI)**:
  - Custom location pins, landmark badges, or icons.
- **Orientation Modes**:
  - `Horizontal (Tabletop)`: Vertical $+Z$ normal pins and upward-facing text.
  - `Vertical (Wall-Hanging)`: $45^\circ-60^\circ$ tilted or front-facing relief badges; integrated rear keyhole mounting slots for wall hanging.

### Module 4: Tiling & Slicing Quality Assurance (DFAM)
- **Automatic Matrix Calculation**:
  $$N_x = \left\lceil \frac{W_{\text{canvas}}}{\text{effective\_bed\_x}} \right\rceil, \quad N_y = \left\lceil \frac{H_{\text{canvas}}}{\text{effective\_bed\_y}} \right\rceil$$
  Every tile dimensions ($W_{\text{tile}} \times H_{\text{tile}}$) are dynamically scaled to be equal and strictly $\le \text{effective\_bed}$.
- **Printability & Nozzle Audit**:
  - Scans building footprints and wall segments against $\text{min\_printable\_wall}$.
  - Auto-dilates undersized geometry or flags warnings with exact geographic coordinates.
- **Joint Creation**:
  - Blind dowel sockets automatically bored into mating interior vertical faces.

---

## 4. Standard Project Deliverables

For every exported map generation:
1. `assembly.3mf`: Multi-body, color-coded 3MF package ready for Bambu Studio / AMS.
2. `tiles/tile_X_Y.stl`: Individual mesh files for each printable chunk.
3. `inlays/path_inlay.stl` & `pins/*.stl`: Separate slide-in accessories with tolerance clearance applied.
4. `base_plate.step`: High-precision solid model of the base and mounting brackets.
5. `previews/diagnostic_views.png`: 4-view orthographic and isometric diagnostic inspection sheet.

---

## 5. Development Roadmap & Progress Log

- [x] **Requirement Gathering & Discovery**: Raw ideas consolidated from user vision.
- [x] **Feasibility Verification**: Live verification of AWS Terrarium DEM, OSM Overpass, and Nominatim endpoints.
- [x] **Architecture Specification**: Parameterization schema and DFAM clearance rules established.
- [ ] **Phase 1: Geospatial Core Engine (`engine/geo.py`)**:
  - [ ] Bounding-box coordinate projection & scale calculations.
  - [ ] AWS Terrarium tile fetching and numpy height-matrix decoding.
  - [ ] OSM Overpass building footprint parser and level-to-height resolver.
- [ ] **Phase 2: Mesh Generation & Solidification (`engine/mesh.py`)**:
  - [ ] Regular Delaunay / grid heightfield meshing with solid skirt base.
  - [ ] Building extrusion and boolean union onto terrain.
  - [ ] Path negative channel carving with parameterized tolerance offsets.
- [ ] **Phase 3: Tiling & Assembly Engine (`engine/tiling.py`)**:
  - [ ] Grid splitting into printable sub-tiles.
  - [ ] Registration dowel pocket insertion.
- [ ] **Phase 4: Slicer Packaging & Validation (`engine/export.py`)**:
  - [ ] Bambu Studio `.3mf` multi-body exporter with filament assignments.
  - [ ] Automated 4-view diagnostic preview renderer.
- [ ] **Phase 5: Interactive GUI (Web / Desktop)**:
  - [ ] MapLibre interactive map selector, canvas bounds tool, and 3D preview.