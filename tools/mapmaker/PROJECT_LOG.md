# Project Log: MapMaker 3D

## 1. Goal & Requirements
- **Goal**: Develop a specialized 3D design and fabrication tool that converts geographic elevation (DEM), building footprints (OSM), and travel routes into precision multi-tile 3D-printable terrain models.
- **Key Requirements**:
  - Full parameterization of printer hardware (nozzle size, bed volume, line widths, tolerances).
  - Support arbitrary canvas sizes with automated grid subdivision into printable sub-tiles.
  - Multi-part fabrication: Focus on single-extruder slide-in/snap-in paths and pins with 0.20mm tolerance offset (no AMS required).
  - Standalone desktop application architecture.
  - Subterranean alignment dowels (with toggle to disable for direct glue-up).
  - Additive manufacturing nozzle analysis (detecting features $< 2 \times \text{line width}$).
  - Tabletop (horizontal) vs wall-hanging (vertical) landmark orientation adaptation.

## 2. Component Breakdown
1. **`engine/config.py`**: Central dataclass and JSON/YAML configuration defining hardware profiles (Bambu A1 default, fully editable), tolerances, and canvas settings.
2. **`engine/geo.py`**: Coordinates, geocoding (Nominatim), AWS Terrarium DEM fetcher, and OSM Overpass 3D building parser.
3. **`engine/mesh.py`**: Solid terrain mesh generation, building extrusion, path boolean cavities, and alignment dowel pocket carving.
4. **`engine/tiling.py`**: Matrix tiling calculation and boundary mesh slicing.
5. **`engine/export.py`**: Exporting per-tile `.stl`, path/pin inlay `.stl`, and CAD `.step` base plates.
6. **`engine/preview.py`**: Automated 4-view orthographic and isometric diagnostic view rendering.
7. **`gui/`**: Standalone Desktop Application frontend (interactive map, boundaries, 3D viewport).

## 3. Printer & Slicer Profiles (Parametric)
- **Reference Default**: Bambu Lab A1 (256x256x256 mm build volume)
- **Default Nozzle**: 0.4 mm (Line width: 0.42 mm, Layer height: 0.16 mm)
- **Clearance / Tolerances**:
  - Horizontal slide-in clearance: `0.20 mm`
  - Alignment dowel clearance: `0.15 mm`
  - Minimum printable wall threshold: `0.84 mm` (2 perimeters)

## 4. Current Status
- [x] Initial thoughts, architecture, and DFAM specification consolidated in `Thoughts.md`.
- [x] Data endpoints verified (AWS Terrarium DEM, OSM Overpass, Nominatim).
- [x] Architectural decisions confirmed: Standalone Desktop App, single-extruder slide-in priority, subterranean flat biscuit dowel mechanism.
- [x] Phase 1 implementation completed: Configuration schema (`config.py`) & Geospatial engine (`geo.py`) verified via `test_geo.py`.
- [x] Phase 2 implementation completed: 3D Mesh Generation, Building Extrusion, and Slide-in Path Carving (`mesh.py`) verified via `test_mesh.py` and 4-view diagnostic preview sheet.
- [x] Phase 4 implementation completed: End-to-End Orchestrator CLI (`mapmaker_cli.py`) & Standalone Desktop Application UI (`app.py` & `gui/`).

## 5. Iteration Log & Learnings
- **Iteration 0 (2026-10-09)**: Project initiated. Formalized specification from raw brainstorming. Verified that AWS Terrarium provides free global DEM without API tokens. Identified that dense terrain must be handled as watertight meshes (`.stl` / `.3mf`) rather than CAD B-Rep (`.step`) to prevent CAD kernel freezing. Confirmed all printer parameters must remain user-editable.
- **Iteration 1 (2026-10-09)**: Scope alignment with user:
  1. Priority is 100% on single-extruder fabrication with negative channels and slide-in parts (no AMS required).
  2. MapMaker will be developed as a standalone desktop application.
  3. Evaluated subterranean alignment dowels. User recognized that $4\text{mm}$ round dowels fail on thin $3-5\text{mm}$ prints, proposing $2\text{mm}$ flat dowels instead. Modeled and verified the $1.6-2.0\text{mm}$ flat biscuit/spline dowel with $+2.0\text{mm}$ lateral float.
- **Iteration 2 (2026-10-09)**: Phase 1 Core Engine Implemented:
  1. `engine/config.py`: Full parametric dataclasses for printer envelope (Bambu A1 default, fully editable), flat biscuit profiles, slide-in clearances, and auto-tiling grid matrix calculation.
  2. `engine/geo.py`: Nominatim geocoding, AWS Terrarium DEM fetcher & metric height decoder, and OSM Overpass 3D building vector parser with height tag resolution.
  3. `tests/test_geo.py`: Integration test verified live on Mount Fuji (fetching real DEM up to $3749.6\text{m}$) and Manhattan (extracting Empire State Building at $443.2\text{m}$ height). All tests passed.
- **Iteration 3 (2026-10-09)**: Phase 2 Mesh Generation Implemented:
  1. Clarified with user that vertical scaling is completely unconstrained (open-ended float, no arbitrary $1\times-20\times$ clamp). Added `target_relief_height_mm` for direct millimeter height targeting.
  2. `engine/mesh.py`: Implemented watertight solid terrain generation (flat print bed base at $Z=0$, vertical perimeter skirt walls, top elevation grid), 3D building footprint extrusion with nozzle threshold audit ($< 0.84\text{mm}$), flat biscuit dowel mesh generation, and swept path ribbon + negative cavity cutter with $+0.20\text{mm}$ clearance.
  3. `tests/test_mesh.py`: All 4 mesh tests passed. Generated binary STLs and verified geometry integrity via headless Blender 4-view diagnostic preview sheet (`previews/diagnostic_views.png`).
- **Iteration 4 (2026-10-09)**: Phase 3 Tiling & Assembly Engine Implemented:
  1. `engine/tiling.py`: Implemented canvas partitioning into printable bed sub-tiles with shared border elevation interpolation (zero seam gap). Guaranteed global minimum elevation datum across all tiles so mating elevations match perfectly.
  2. Subterranean biscuit placement calculation and automated batch biscuit layout generation on a single print plate (`accessories/biscuit_splines.stl`).
  3. Automated `ASSEMBLY_GUIDE.md` generation providing grid layout matrix and slicing advice for Bambu Lab A1.
  4. `tests/test_tiling.py`: Verified $500\times 500\text{mm}$ canvas split into a $2\times 2$ grid (4 tiles of $250\times 250\text{mm}$ each, fitting Bambu A1 bed), and 8 alignment biscuits in one batch. All tests passed.
- **Iteration 5 (2026-10-09)**: Phase 4 CLI & Desktop App Implemented:
  1. `mapmaker_cli.py`: Unified one-command generator for any geographic landmark or coordinates.
  2. `gui/index.html` & `app.py`: Interactive desktop application featuring 2D Leaflet boundary tool and 3D WebGL (Three.js) real-time terrain preview.
  3. Automated Chrome Remote Desktop integration: `setup_display_env()` detects active Wayland/X11 sockets (`WAYLAND_DISPLAY=wayland-0`, `DISPLAY=:0`, `XAUTHORITY`), launching a native chromeless desktop window directly onto the user's remote desktop. Fully verified.
- **Iteration 6 (2026-10-09)**: UI Overhaul & Feature Alignment from Thoughts.md:
  1. Replaced canvas sliders with pure numeric input cells (default $250 \times 250\text{mm}$).
  2. Overhauled 2D map bounding box: search now zooms out with a 35% margin (`pad(0.35)`) for geographic context, rendering a distinct interactive bounding box with 4 corner resize handles and a center drag handle. Panning the map does not alter the selection box.
  3. Integrated Base Shape selector: Square/Rectangle, Circular base, Elliptical base, Regular Polygon (N-Gon with sides count, e.g. 6 for Hexagon), and No Base (Natural Coastline/Borders).
  4. Added interactive Travel Route path drawing tool (vivid orange spline with draggable waypoints for slide-in inlay strips) and Landmark Highlight POI pin placer.
  5. Added Display Mode selector: Tabletop (Horizontal $+Z$ pins) vs Wall-Hanging (Vertical Frame with rear keyhole hanger).
  6. Verified live on `India` and Mount Fuji queries. Server running live at `http://127.0.0.1:8765`.
- **Iteration 7 (2026-10-12)**: Ergonomics, Road Routing, & Robust 3D Viewport:
  1. **Sidebar Layout & Sizing Polish**: Fixed oversized numeric input cells by setting `overflow-x: hidden` on `aside`, `min-width: 0; box-sizing: border-box;` on inputs, eliminating horizontal scrolling completely. Locked labels to single-line height and aligned Relief Height and Z-Scale Multiplier inputs to the exact same horizontal baseline.
  2. **Follow Roads vs Straight Line Routing**: Added a Route Mode selector (`select-route-mode`: "Follow Roads (OSRM)" vs "Straight Line (Direct)"). Implemented `calculate_route()` in `engine/geo.py` and `/api/route` in `app.py` querying OpenStreetMap OSRM routing engine. Snaps waypoints to real highways/streets (verified live on Mumbai-Pune expressway with 2,600 road points) while maintaining draggable anchor markers on the 2D map.
  3. **Robust 3D WebGL Terrain Viewport**: Fixed the 3D preview black screen by:
     - Automatically syncing container dimensions (`w`, `h`) upon tab switch, updating WebGL renderer size and camera aspect ratio.
     - Setting `camera3d.up.set(0, 0, 1)` matching standard CAD/3D printing Z-up orientation and preventing `OrbitControls` gimbal lock.
     - Adding `THREE.DoubleSide` lighting with dual directional sun/fill lights and ambient illumination.
     - Clamping ocean bathymetry ($\le -50\text{m}$) to $0\text{m}$ sea level for large bounding boxes (e.g. India) to ensure land elevation isn't squashed.
     - Implemented automated camera framing (`Box3.setFromObject`) to center and focus any canvas size immediately.
     - Added a centered loading indicator overlay (`#loading-3d`) with animated spinner during elevation decoding and mesh synthesis.

- **Iteration 8 (2026-10-13)**: 3D Visualization Polish, Texture Mapping, & Scale-Adaptive Block LOD:
  1. **Camera Angle Persistence & 2D/3D Synchronization**: Synchronized 2D map rotation and 3D camera azimuth, preserving user camera angle across tab toggles without resets.
  2. **POI Pins & Route Rendering in 3D**: Rendered user-defined landmark pins with vertical indicator stalks and extruded 3D travel routes directly conforming to the undulating terrain mesh.
  3. **Elevation Hypsometric Tinting & 2D Map Texture Overlay**: Replaced relative percentage coloring with true elevation in feet. Added seamless 2D OpenStreetMap tile mosaic texture overlay projected onto the 3D terrain mesh. Changed building extrusion material to light slate grey (`#e2e8f0`) with dark edge outlines for optimal contrast.
  4. **Scale-Adaptive Highway LOD**: Dynamically selected highway hierarchy based on canvas span: neighborhood scale ($\le 10\text{ km}$) includes residential streets, metro scale ($10-45\text{ km}$) uses arterials/collectors, and regional scale ($> 45\text{ km}$) uses major arterial corridors, preventing suburban block dropouts (e.g. Uttarahalli in Bengaluru).
- **Iteration 9 (2026-10-14)**: Water Exclusion Filter & Stochastic Height Simplification:
  1. **Eliminated Water Block Extrusion**: Fixed coastal/river water bodies (Tokyo Bay, Upper/Lower NY Bay, Hudson River, Jamaica Bay, Long Island Sound) being extruded as solid blocks via a 3-tier exclusion filter:
     - *Tier 1 (OSM Tags)*: Expanded Overpass query to include `waterway~riverbank|dock|canal`, `natural~water|bay`, `water=*`, `landuse=reservoir`, and `leisure~park|marina`.
     - *Tier 2 (Coastal DEM Bathymetry Filter)*: In coastal regions (`min_elev <= 0m`), sampled a $128 \times 128$ DEM grid; blocks with centroid elevation $\le 0.0\text{m}$ (or $\le 1.5\text{m}$ for parcels $> 0.05\text{ km}^2$) are identified as water and excluded.
     - *Tier 3 (Maximum Area Cap)*: Capped parcels at $\le 2.5\text{ km}^2$ (and $\le 2.5\%$ of bbox area) to eliminate uncarved open sounds, bays, and wilderness parcels.
     - *Verification*: Verified Tokyo (1,466 blocks, 0 water blocks) and New York (638 blocks, 0 water blocks); verified Lower NY Bay ($492\text{ km}^2$), Upper NY Bay, Hudson River, and Tokyo Bay are 100% flat at water level.
  2. **Removed "Density & Arterial Trend"**: Completely removed the trend dropdown from UI and backend; block heights now strictly follow pure stochastic variation between user-selected Min and Max heights.
- **Iteration 10 (2026-10-14)**: Precision Cartographic Water Mask & Global Multi-Terrain Verification:
  1. **Cartographic Raster Water Mask**: Integrated high-resolution pre-rendered OpenStreetMap Carto tile raster sampling (`fetch_map_texture(bbox, target_size=512)`) into `fetch_urban_blocks`. For each candidate block, color values at both `centroid` and `representative_point()` are sampled to identify water signatures (`(b > r + 8 and g > r + 8) or (b > 175 and b > r + 15) or (r < 135 and b > r + 6 and g > r + 4)`). Solves DEM resolution edge artifacts where narrow rivers (e.g. East River, Harlem River, Seine, Thames) interpolate positive elevations between steep riverbanks.
  2. **Calibrated Block Area Cap**: Lowered maximum parcel threshold from $2.5\text{ km}^2$ to $1.5\text{ km}^2$ (and $\le 1.5\%$ of bbox area), successfully pruning uncarved wetlands, coastal flats, and rural sound boundaries.
  3. **Overpass Query Disk Caching**: Added persistent disk caching (`~/.cache/mapmaker3d/overpass/`) keyed by MD5 hash of the Overpass query string, reducing repeat query execution from 15-30s down to $<0.01$s.
  4. **Multi-Terrain Global Verification**: Executed automated test suite across diverse global geographies with 100% pass rate:
     - **New York**: 550 blocks generated; 0 water hits across 9 key test points (East River, Harlem River, Hudson River, Upper NY Bay, Lower NY Bay, Jamaica Bay, Newark Bay, Hackensack River, Wallabout Bay).
     - **London**: 531 blocks generated; 0 water hits across 4 test points (Thames at Westminster, Tower Bridge, Greenwich, Surrey Quays Dock).
     - **Paris**: 614 blocks generated; 0 water hits across 3 test points (Seine at Pont Neuf, Eiffel Tower, Bercy).
     - **San Francisco**: 69 blocks generated; 0 water hits across 3 test points (SF Bay, Pacific Ocean, Golden Gate Strait).
     - **Mount Fuji (Mountain Peak)**: 0 spurious urban blocks extruded on mountain peak/slopes.
     - **Venice, Italy (Lagoon Island City)**: 39 settlement blocks generated; 0 water hits across 3 test points (North Lagoon, South Lagoon, Giudecca Canal).
     - **Honolulu, Hawaii (Island Archipelago & Volcanic Ridges)**: 209 blocks generated; 0 water hits across 3 test points (Mamala Bay/Waikiki, Pearl Harbor Channel, Keehi Lagoon).
- **Iteration 11 (2026-10-14)**: Scale-Bounded Street Buffers, Maritime BBox Bloat Elimination, & High-Fidelity River/Nature Masks:
  1. **Scale-Bounded Road Buffers (Manhattan Restoration)**:
     - Fixed Manhattan appearing completely flat when querying "New York". At regional scale ($50\text{ km}$ across $250\text{ mm}$ canvas), a $1.2\text{ mm}$ groove mapped to $240-360\text{ m}$ in real life, completely overlapping and swallowing Manhattan's $60\text{ m} \times 150\text{ m}$ street grid.
     - Implemented `max_buffer_deg = 20.0 / 111139.0` and clamped `base_buffer_deg = min(max_buffer_deg, ...)` in `engine/blocks.py`.
     - *Result*: New York block count increased from 550 to **2,050 blocks** with **497 blocks across Manhattan**. All landmarks (Empire State Building, Rockefeller Center, Chrysler Building, Columbia University, One World Trade Center) are fully preserved.
  2. **Bi-directional Aspect-Ratio Normalization (San Francisco Maritime Bloat Elimination)**:
     - Fixed San Francisco containing ~70% empty Pacific Ocean due to Farallon Islands (30 miles west at $-123.00^\circ$ inside SF County).
     - Replaced latitude-only check with `effective_span = max(lat_span, lon_span * cos_lat)` in `engine/geo.py`. If span $> 0.50^\circ$, bounding box automatically centers on the urban peninsula ($22\text{ km} \times 22\text{ km}$).
     - *Result*: Generated **655 clean blocks** across San Francisco, eliminating 40 miles of empty ocean.
  3. **Cartographic Nature & Wilderness Filter (Kudremukh & Mountain Peak Fix)**:
     - Added `_is_green_nature_pixel` to identify natural forest, woodland, and national park pixels (`g > r + 10 and g > b + 4` or vivid meadow greens) from OSM Carto tiles.
     - Pruned non-water rural parcels located in wilderness and national parks.
     - *Result*: **Kudremukh produces 0 artificial blocks** (100% clean natural mountain topography preserved). Mount Fuji produces **0 blocks**.
  4. **High-Fidelity River Mask with 4x4 Interior Grid Sampling (London & Paris River Fix)**:
     - Upgraded raster mask sampling to `target_size=1024` and introduced a fast $4 \times 4$ interior bounding grid test (`np.linspace`) inside candidate polygons.
     - Catches narrow diagonal river segments between bridge crossings (Thames and Seine) in $< 0.4\text{s}$ without dropping real urban blocks.
  5. **100% Automated Multi-Terrain Test Suite Pass**:
     - Verified all 8 diverse test cases in `tests/test_cities_suite.py` with 100% success: New York (2,050 blocks, 9/9 water points clean), London (1,079 blocks, 4/4 water points clean), Paris (647 blocks, 3/3 water points clean), San Francisco (655 blocks, 3/3 water points clean), Mount Fuji (0 blocks), Kudremukh (0 blocks), Venice (127 blocks, 3/3 water points clean), Honolulu (328 blocks, 3/3 water points clean).
- **Iteration 12 (2026-10-15)**: Bounding Box Pointer Pass-Through & Drawing/Pin Interaction Decoupling:
  1. **Route Drawing & Landmark Pin Pass-Through**:
     - Fixed issue where clicks inside the bounding box were swallowed by `bboxRect.on('mousedown')` with `stopPropagation()`, preventing route drawing and pin dropping.
     - Added dynamic `.mode-drawing` and `.mode-pin` UI classes setting `pointer-events: none !important;` on `.draggable-bbox`, `.blocks-layer`, and handles during active tool modes.
     - Created unified `handleMapClick(latlng)` wired to `map.on('click')` with direct fallbacks on `bboxRect.on('click')` and urban block polygons.
  2. **Bounding Box Drag Threshold in Normal Mode**:
     - Added a $5\text{px}$ movement threshold for bounding box dragging; stationary clicks in normal mode no longer trigger bounding box updates, re-renders, or block re-queries.
  3. **Verified Corner Handles & Dimension Resizing**:
     - Verified that all 4 corner resize handles (NW, NE, SE, SW), center move handle (`✥`), and rotation handle (`⟳`) remain 100% functional with distinct cursor feedback (`nwse-resize`, `nesw-resize`).
     - Verified via headless Chrome CDP integration test suite confirming 100% pass across waypoint drawing, pin dropping, and corner dimension resizing.
- **Iteration 13 (2026-10-15)**: Parallel Tile Download Engine & 3D Preview Timeout Resilience:
  1. **Parallelized Geospatial Tile Downloads (`engine/geo.py`)**:
     - Introduced `concurrent.futures.ThreadPoolExecutor(max_workers=min(12, max(2, len(tile_jobs))))` into both `fetch_map_texture` and `fetch_elevation_grid`.
     - Replaced single-threaded sequential HTTPS tile downloads with concurrent threaded fetching, slashing cold multi-tile DEM downloads from 15-20s down to $< 1.5\text{s}$ (and cached queries $< 0.05\text{s}$).
  2. **60-Second Client Timeout & Informative Error Propagation (`gui/index.html`)**:
     - Extended client-side fetch timeout in `render3DScene()` from 15s to 60s to accommodate large multi-degree continental bounding boxes over high-latency networks.
     - Provided explicit error message to `controller.abort(new Error("Elevation fetch timed out (60s network latency)..."))`, eliminating the cryptic browser `"signal is aborted without reason"` `DOMException`.
  3. **Distinguished Network Timeouts from WebGL Driver Errors**:
     - Separated network fetch aborts (`AbortError`) from WebGL graphics initialization crashes in the 3D viewport error boundary, displaying a dedicated "Elevation Network Timeout" card with retry button instead of the misleading Chrome Remote Desktop WebGL flag warning.
  4. **Server Daemon & Endpoint Verification**:
     - Verified live `/api/elevation` endpoint response time on nationwide spans (0.032s response).
     - Verified MapMaker server daemon running stably on port 8765.
- **Iteration 14 (2026-10-15)**: Full Implementation & Verification of "No Base (Coastline / Borders)" Geometry Engine:
  1. **Geocoding & High-Resolution Territorial Vector Extraction (`engine/geo.py`, `app.py`)**:
     - Configured Nominatim queries with `polygon_geojson=1&polygon_threshold=0.005` and persistent disk caching in `~/.cache/mapmaker3d/nominatim/`.
     - Preserved true regional extents for states, provinces, and countries (`is_large_territory`), preventing incorrect 22km city bounding box clamping on large entities like Texas and Karnataka.
     - Pruned micro-islets and unprintable sub-millimeter rocks ($< 0.2\%$ of area) via Shapely while preserving home island archipelagos (Japan's Honshu, Hokkaido, Kyushu, Shikoku; India's mainland and Andaman/Nicobar; Texas and Karnataka mainland borders).
     - Added `/api/boundary` and updated `/api/geocode` to return boundary GeoJSON.
  2. **Watertight 2-Manifold Solid Mesh Engine (`engine/mesh.py`, `engine/tiling.py`)**:
     - Implemented `base_shape == "natural_border"` in `generate_terrain_mesh` and `TilingEngine`.
     - Projected boundary polygon coordinates into physical canvas millimeters $(X, Y)$, sampled interior grid points, and triangulated via `scipy.spatial.Delaunay`.
     - Connected vertical perimeter skirt walls along exact top boundary edges (`top_boundary_edges`) and inverted bottom floor at $Z=0$.
     - Programmatically verified 0 unmatched directed edges across India, Japan, Karnataka, and Texas (100% watertight 2-manifold solid ready for Bambu Studio).
  3. **3D WebGL Viewport Preview & REST Synthesis (`engine/mesh.py`, `app.py`, `gui/index.html`)**:
     - Implemented `generate_boundary_preview_mesh` and `/api/boundary_mesh` endpoint generating Three.js compatible buffer data in $< 0.15\text{s}$.
     - When "No Base (Coastline / Borders)" is selected, 3D viewport renders the true organic shape of the country/state with vertical drop walls and no surrounding rectangular base slab.
  4. **2D Map Vector Visualization & Dynamic Fallback (`gui/index.html`)**:
     - Replaced rectangular outline with `L.geoJSON(state.boundaryGeoJSON)` on Leaflet map when in `natural_border` mode.
     - Added automatic background boundary fetching when switching dropdown on an existing search.
  5. **100% Automated Test Suite & Browser Verification**:
     - Verified `tests/test_natural_border.py` passed with 0 non-manifold edges across all locations.
     - Verified interactive browser UI via headless Chrome CDP test across India, Karnataka, Texas, and Japan.
- **Iteration 15 (2026-10-15)**: Cache Freshness, TTL Expiration, HTTP 304 Validation, & Force Refresh Control:
  1. **Automatic TTL Cache Expiration & Resilient Offline Fallback (`engine/geo.py`, `engine/blocks.py`)**:
     - Added `_is_cache_fresh(filepath, max_age_days)` to validate cached file timestamps (`mtime`).
     - Configured a **30-day TTL** on Overpass urban block vectors (`_fetch_overpass_cached`) and OpenStreetMap Carto map tiles (`fetch_osm_tile`), a **60-day TTL** on Nominatim boundary geocoding (`geocode_location`), and kept **AWS Terrarium DEM elevation tiles permanently cached** (since terrain topography does not change on human timescales).
     - Preserved offline-first resilience: if a cached entry expires or `force_refresh=True` is requested while offline or rate-limited, the engine gracefully falls back to the existing local disk cache.
  2. **HTTP 304 Conditional Validation on Map Tiles (`engine/geo.py`)**:
     - When a cached OSM map tile exceeds its 30-day TTL, `fetch_osm_tile` sends an `If-Modified-Since` HTTP header with the file's UTC modification timestamp.
     - If the OpenStreetMap server responds with `304 Not Modified`, the local tile's `mtime` is updated via `os.utime(tile_path, None)` to reset the 30-day window with **0 bytes of image data re-downloaded**.
  3. **`force_refresh=true` REST API & UI Header Button (`app.py`, `gui/index.html`)**:
     - Added `force_refresh=true` query and POST parameter support across `/api/geocode`, `/api/boundary`, `/api/boundary_mesh`, `/api/map_texture`, and `/api/blocks`.
     - Added the **↻ Refresh Data** button (`#btn-force-refresh`) in the application header bar, allowing one-click cache bypass and live refresh of OpenStreetMap vectors, boundaries, and map textures.
  4. **Automated Test Verification (`tests/test_cache_freshness.py`)**:
     - Added unit tests covering `_is_cache_fresh`, Overpass TTL expiry, `force_refresh=True` bypass, offline network fallback, and HTTP 304 `If-Modified-Since` tile validation. All tests pass 100%.
- **Iteration 16 (2026-10-15)**: Full Cross-OS Native Compatibility (Windows, macOS, Linux):
  1. **Cross-Platform Display & Browser Window Launcher (`app.py`)**:
     - Guarded `setup_display_env()` with `sys.platform.startswith("linux") and hasattr(os, "getuid")`, eliminating the `AttributeError: module 'os' has no attribute 'getuid'` crash on Windows (`win32`).
     - Updated `launch_desktop_window()` to detect Windows Chrome/Edge (`%ProgramFiles%\Google\Chrome\Application\chrome.exe`, `msedge.exe`), macOS Chrome (`/Applications/Google Chrome.app/...`), and Linux Chrome/Chromium, with automatic fallback to `webbrowser.open()`.
  2. **Explicit UTF-8 File & Console Encoding (`engine/tiling.py`, `engine/mesh.py`, `app.py`, `mapmaker_cli.py`)**:
     - Added explicit `encoding="utf-8"` to `ASSEMBLY_GUIDE.md` and ASCII STL file writes so non-Latin characters (e.g., `日本`, `✓`) never trigger `cp1252` `UnicodeEncodeError` on Windows.
     - Configured `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` on startup for Windows `cmd.exe` and PowerShell compatibility.
  3. **Cross-OS Packaging & Launchers (`requirements.txt`, `run_mapmaker.bat`, `run_mapmaker.sh`)**:
     - Added `requirements.txt` and one-click launchers for Windows (`run_mapmaker.bat`) and Linux/macOS (`run_mapmaker.sh`).
     - Added and verified `tests/test_cross_os.py` (5/5 tests passing).
- **Iteration 17 (2026-10-15)**: Multi-Tile Boundary Partitioning, Global Elevation Datum, & Subterranean Biscuit Dowel Pockets (`engine/mesh.py`, `engine/tiling.py`):
  1. **True Geographic Tile Clipping & Seam Subdivision (`engine/mesh.py`)**:
     - Fixed `generate_terrain_mesh()` to intersect `boundary_geojson` against each tile's geographic bounding box `box(bbox.west, bbox.south, bbox.east, bbox.north)` (`geom.intersection(tile_bbox_poly)`) and subdivide straight cut seams via `shapely.segmentize(sh_poly, max_segment_length=3.5)` so terrain relief tracks smoothly along internal seam boundaries.
     - Added `tile_clip_box_norm` clipping for `circle`, `ellipse`, and `polygon` base shapes across multi-tile grids.
  2. **Unified Global Elevation Datum & World-Space Tile Placement (`engine/tiling.py`)**:
     - Passed unified `global_min_elev` and `global_z_scale` from `TilingEngine.process_and_export_all()` into `generate_terrain_mesh()` so elevation relief across all tiles shares a single continuous Z-scale and zero-step seam transitions.
     - Translated each exported tile mesh by `(tile.x_min_mm, tile.y_min_mm)` so opening all tiles simultaneously in FreeCAD or Blender automatically places them side-by-side in their exact $2 \times 2$ quadrants.
  3. **2-Manifold Subterranean Biscuit Dowel Pockets (`_emit_skirt_walls_with_biscuit_pockets` in `engine/mesh.py`)**:
     - Embedded 100% watertight 2-manifold negative biscuit dowel pockets ($14.0\text{ mm}$ wide $\times 1.85\text{ mm}$ tall $\times 6.5\text{ mm}$ deep at $Z \in [1.0, 2.85]\text{ mm}$) into active interior tile seam walls (`south`, `east`, `north`, `west`), automatically positioned at $1/3$ and $2/3$ of the shared land seam span (`[s_min, s_max]`) so opposing tiles align coaxially to $0.000\text{ mm}$ and never place pockets in empty ocean space.
     - Generated matching positive spline batch `accessories/biscuit_splines.stl` ($13.6\text{ mm} \times 12.6\text{ mm} \times 1.68\text{ mm}$, 8 splines for a $2 \times 2$ grid).
  4. **Verification (`tests/test_tiling.py`, `exports/latest_export/`)**:
     - Regenerated all 4 India (`500 x 500 mm`) STL tiles (`tile_col0_row0.stl` through `tile_col1_row1.stl`) and `accessories/biscuit_splines.stl` with `0` non-manifold edges and verified distinct quadrant geometry and coaxial pocket alignment.
- **Iteration 18 (2026-10-15)**: FreeCAD 1.1 Auto-Framing, Origin-Centered Individual Tiles, Assembly STLs, & Mainland Polygon Geocoding (`engine/tiling.py`, `engine/geo.py`, `InitGui.py`):
  1. **Origin-Centered Individual Tile STLs + `full_assembly.stl` & `exploded_assembly.stl` (`engine/tiling.py`)**:
     - Centered each exported individual tile STL (`tiles/tile_col0_row0.stl` through `tiles/tile_col1_row1.stl`) at `(X = 0, Y = 0)` so opening any individual tile in FreeCAD or Bambu Studio places the landmass directly at the origin `(0, 0)`.
     - Added automatic export of `full_assembly.stl` (all tiles assembled at their exact world coordinates centered around `(0, 0)`) and `exploded_assembly.stl` (all tiles separated by a `20.0 mm` gap with positive biscuit splines aligned in-line between opposing subterranean pockets).
  2. **Mainland Polygon Selection for Island-Spanning Prefectures/Cities (`engine/geo.py`)**:
     - Updated `geocode_location()` so when a city/prefecture `MultiPolygon` (such as Tokyo `東京都` with distant Ogasawara islands) exceeds `0.85°` effective span or `0.35°` center offset, it selects the mainland polygon component closest to `(lon, lat)` (`35.48°N–35.90°N, 138.94°E–139.92°E` for Tokyo) and uses its exact polygon boundary and bounding box instead of an inner $0.20^\circ$ square.
  3. **FreeCAD 1.1 Automatic 3D View Framing (`~/.local/share/FreeCAD/v1-1/Mod/JetskiBridge/InitGui.py`)**:
     - Diagnosed that FreeCAD 1.1.3 initializes new STL views with an `OrthographicCamera` at `(0, 0, 1)` and `height = 4.1421356` (`4.14 mm × 4.14 mm` window) without calling `fitAll()`, and uses ` ~/.local/share/FreeCAD/v1-1/Mod/` (`App.getUserAppDataDir()`).
     - Installed the `JetskiBridge` auto-fit observer & timer in `~/.local/share/FreeCAD/v1-1/Mod/JetskiBridge/InitGui.py` with `UseNavigationAnimations = False` so opening any `.stl` file automatically calls `v.fitAll()` to frame the entire 3D model immediately.
  4. **Verification**:
     - Verified automatic FreeCAD 1.1.3 framing on `tile_col0_row1.stl` and `exploded_assembly.stl`, verified Tokyo's 4 natural-border tiles + subterranean biscuit pockets, and confirmed 100% pass across `test_tiling.py` and `test_natural_border.py`.








