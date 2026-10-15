"""Configuration schema and hardware parameterization for MapMaker 3D.

All dimensions are in millimeters unless otherwise specified.
Defaults are pre-configured for the Bambu Lab A1 with a 0.4mm nozzle,
but all fields are fully customizable.
"""

from dataclasses import dataclass, field, asdict
import json
import math
from typing import Dict, Any, List, Tuple, Optional


@dataclass
class PrinterProfile:
    """Hardware and slicer envelope parameters."""
    name: str = "Bambu Lab A1"
    bed_width: float = 256.0        # Physical bed width (X)
    bed_depth: float = 256.0        # Physical bed depth (Y)
    bed_height: float = 256.0       # Max printable Z height
    edge_buffer: float = 3.0        # Safety border margin from physical bed edges
    nozzle_diameter: float = 0.40   # Nominal nozzle diameter
    line_width: float = 0.42        # Sliced extrusion bead width
    layer_height: float = 0.16      # Vertical layer resolution
    min_printable_wall: float = 0.84 # Minimum wall thickness (2x line width)

    @property
    def effective_bed_x(self) -> float:
        """Usable X build width per tile."""
        return max(10.0, self.bed_width - (2.0 * self.edge_buffer))

    @property
    def effective_bed_y(self) -> float:
        """Usable Y build depth per tile."""
        return max(10.0, self.bed_depth - (2.0 * self.edge_buffer))


@dataclass
class DowelProfile:
    """Subterranean alignment joint parameters for multi-tile maps."""
    enabled: bool = True
    dowel_type: str = "flat_biscuit"  # "flat_biscuit", "round", or "none"
    
    # Flat biscuit / spline dowel parameters (Default for low-profile & thin maps >= 3.5mm)
    biscuit_thickness: float = 1.60   # Vertical thickness (8 layers @ 0.2mm)
    pocket_height: float = 1.85       # Vertical slot height (+0.25mm clearance)
    biscuit_width: float = 12.0       # Lateral spline width
    pocket_width: float = 14.0        # Lateral slot width (+2.0mm lateral float)
    biscuit_length: float = 12.0      # Total spline length across seam
    pocket_depth: float = 6.5         # Depth of slot bored into each tile (1mm safety gap)
    lead_in_chamfer: float = 0.40     # Entry lead-in chamfer for smooth insertion
    
    # Round cylindrical dowel parameters (Optional for thick relief maps >= 6.5mm)
    round_diameter: float = 4.0
    round_pocket_diameter: float = 4.30
    round_length: float = 14.0
    round_pocket_depth: float = 8.0


@dataclass
class ToleranceProfile:
    """Tolerances for single-extruder slide-in parts and landmark pins."""
    path_joint_clearance: float = 0.20  # Per-side horizontal clearance for slide-in paths
    path_entry_chamfer: float = 0.40    # Lead-in chamfer on negative slot edges
    path_default_width: float = 2.0     # Default travel route strip width (mm)
    path_default_depth: float = 1.6     # Inset depth into terrain base (mm)
    path_top_offset: float = 0.40       # Height path protrudes above terrain for tactile feel
    pin_socket_clearance: float = 0.15  # Radial clearance for landmark pin sockets


@dataclass
class BoundingBox:
    """Geographic WGS84 bounding box (south, west, north, east)."""
    south: float
    west: float
    north: float
    east: float

    @property
    def lat_span(self) -> float:
        return abs(self.north - self.south)

    @property
    def lon_span(self) -> float:
        return abs(self.east - self.west)

    @property
    def center(self) -> Tuple[float, float]:
        return ((self.south + self.north) / 2.0, (self.west + self.east) / 2.0)


@dataclass
class CanvasConfig:
    """Physical target canvas and map styling configuration."""
    width_mm: float = 250.0          # Target physical print width (X)
    depth_mm: float = 250.0          # Target physical print depth (Y)
    rotation_deg: float = 0.0        # Geographic orientation rotation angle in degrees (0 to 360)
    base_shape: str = "rectangle"     # "rectangle", "circle", "ellipse", "polygon", "natural_border"
    base_sides: int = 6              # Number of sides if base_shape == "polygon" (e.g. 6 for hexagon)
    base_height_mm: float = 4.0      # Solid base slab thickness underneath lowest point
    topography_enabled: bool = True  # Enable 3D elevation relief
    vertical_exaggeration: float = 2.0 # Elevation multiplier (any positive float: 0.5x, 1.0x, 15x, 100x, etc.)
    target_relief_height_mm: Optional[float] = None # Optional: auto-calculates scale so highest peak matches exact mm
    blocks_enabled: bool = False     # Extrude tactile urban blocks and street network relief
    block_min_height_mm: float = 2.0 # Minimum extruded block height
    block_max_height_mm: float = 6.0 # Maximum extruded block height
    block_groove_width_mm: float = 1.2 # Recessed street channel width (mm) on print bed
    buildings_enabled: bool = False  # Legacy alias
    building_height_scale: float = 1.0 # Scale multiplier for building heights (any positive float)
    viewing_orientation: str = "tabletop" # "tabletop" (+Z pins) or "wall_hanging" (tilted relief with rear keyholes)
    keyhole_hanger: bool = True      # Embed rear wall-mounting keyhole slots when wall_hanging is selected
    path_waypoints: List[Tuple[float, float]] = field(default_factory=list) # Waypoints for slide-in path
    landmarks: List[Dict[str, Any]] = field(default_factory=list) # List of POI landmark pins {name, lat, lon}
    boundary_geojson: Optional[Dict[str, Any]] = None # High-precision GeoJSON territorial / coastline boundary polygon


@dataclass
class TileSlice:
    """Represents a single printable tile within an NxM tiled canvas."""
    col_idx: int                     # Column index (0 to Nx-1)
    row_idx: int                     # Row index (0 to Ny-1)
    x_min_mm: float                  # X start coordinate on physical canvas
    x_max_mm: float                  # X end coordinate on physical canvas
    y_min_mm: float                  # Y start coordinate on physical canvas
    y_max_mm: float                  # Y end coordinate on physical canvas
    width_mm: float
    depth_mm: float
    bbox: BoundingBox                # Corresponding geographic sub-bounding box


@dataclass
class MapMakerConfig:
    """Complete unified project configuration."""
    printer: PrinterProfile = field(default_factory=PrinterProfile)
    dowel: DowelProfile = field(default_factory=DowelProfile)
    tolerances: ToleranceProfile = field(default_factory=ToleranceProfile)
    canvas: CanvasConfig = field(default_factory=CanvasConfig)
    bbox: Optional[BoundingBox] = None
    location_name: str = ""

    def calculate_tiling_grid(self) -> Tuple[int, int]:
        """Calculates the minimum required tile matrix (cols_x, rows_y) to fit the bed."""
        eff_x = self.printer.effective_bed_x
        eff_y = self.printer.effective_bed_y
        cols = max(1, math.ceil(self.canvas.width_mm / eff_x))
        rows = max(1, math.ceil(self.canvas.depth_mm / eff_y))
        return cols, rows

    def generate_tile_slices(self) -> List[TileSlice]:
        """Generates the list of individual printable tile partitions."""
        cols, rows = self.calculate_tiling_grid()
        tile_w = self.canvas.width_mm / cols
        tile_d = self.canvas.depth_mm / rows

        slices = []
        for r in range(rows):
            for c in range(cols):
                x0 = c * tile_w
                x1 = (c + 1) * tile_w
                y0 = r * tile_d
                y1 = (r + 1) * tile_d

                # Interpolate sub-bounding box if global bbox exists
                if self.bbox:
                    lon_min = self.bbox.west + (c / cols) * self.bbox.lon_span
                    lon_max = self.bbox.west + ((c + 1) / cols) * self.bbox.lon_span
                    # Latitude increases from south to north (row 0 is south)
                    lat_min = self.bbox.south + (r / rows) * self.bbox.lat_span
                    lat_max = self.bbox.south + ((r + 1) / rows) * self.bbox.lat_span
                    sub_bbox = BoundingBox(south=lat_min, west=lon_min, north=lat_max, east=lon_max)
                else:
                    sub_bbox = BoundingBox(south=0.0, west=0.0, north=0.0, east=0.0)

                slices.append(TileSlice(
                    col_idx=c,
                    row_idx=r,
                    x_min_mm=x0,
                    x_max_mm=x1,
                    y_min_mm=y0,
                    y_max_mm=y1,
                    width_mm=tile_w,
                    depth_mm=tile_d,
                    bbox=sub_bbox
                ))
        return slices

    def to_json(self) -> str:
        """Serializes configuration to JSON string."""
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> 'MapMakerConfig':
        """Deserializes configuration from JSON string."""
        data = json.loads(json_str)
        printer = PrinterProfile(**data.get("printer", {}))
        dowel = DowelProfile(**data.get("dowel", {}))
        tolerances = ToleranceProfile(**data.get("tolerances", {}))
        canvas = CanvasConfig(**data.get("canvas", {}))
        bbox_data = data.get("bbox")
        bbox = BoundingBox(**bbox_data) if bbox_data else None
        return cls(
            printer=printer,
            dowel=dowel,
            tolerances=tolerances,
            canvas=canvas,
            bbox=bbox,
            location_name=data.get("location_name", "")
        )
