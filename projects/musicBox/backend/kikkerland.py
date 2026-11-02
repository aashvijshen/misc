"""Physical and musical specifications for the Kikkerland 15-Note Music Box Kit."""

from dataclasses import dataclass, asdict
from typing import List, Dict

# Physical geometry (millimeters)
STRIP_WIDTH_MM: float = 41.0
NUM_COLUMNS: int = 15
COLUMN_SPACING_MM: float = 2.0
TRACK_SPAN_MM: float = (NUM_COLUMNS - 1) * COLUMN_SPACING_MM  # 28.0 mm
SIDE_MARGIN_MM: float = (STRIP_WIDTH_MM - TRACK_SPAN_MM) / 2.0  # 6.5 mm
HOLE_DIAMETER_MM: float = 2.0

# Existing Kikkerland blank strip defaults
DEFAULT_EXISTING_STRIP_USABLE_MM: float = 412.0  # ~41.2 cm usable grid length
DEFAULT_EXISTING_GRID_SPACING_MM: float = 2.0    # 2.0 mm grid spacing reported on strip
DEFAULT_MM_PER_BEAT: float = 8.0                 # 8.0 mm per quarter-note beat (4 rows of 2mm)

# Mechanical star-wheel recovery threshold along the same column
MIN_SAME_NOTE_REPEAT_MM: float = 4.5

# A4 Page Dimensions (mm)
A4_WIDTH_MM: float = 210.0
A4_HEIGHT_MM: float = 297.0

# Musical mapping: 2-octave C Major diatonic scale
# Printed labels on Kikkerland strip: C D E F G A B C D E F G A B C
PRINTED_LABELS: List[str] = [
    "C", "D", "E", "F", "G", "A", "B",
    "C", "D", "E", "F", "G", "A", "B",
    "C",
]

# Bold vertical reference lines on the physical strip correspond to the
# 5-line Treble Clef staff: E, G, B, D, F (0-based indices 2, 4, 6, 8, 10)
BOLD_COLUMN_INDICES: List[int] = [2, 4, 6, 8, 10]

# Semitone offsets from Column 0 (Low C = 0 .. Top C = 24)
RELATIVE_SEMITONES: List[int] = [
    0, 2, 4, 5, 7, 9, 11,
    12, 14, 16, 17, 19, 21, 23,
    24,
]

SEMITONE_TO_COLUMN: Dict[int, int] = {
    semi: idx for idx, semi in enumerate(RELATIVE_SEMITONES)
}

# Sounding MIDI pitches (music boxes sound 1 octave above treble staff: C5=72 .. C7=96)
SOUNDING_BASE_MIDI: int = 72
WRITTEN_BASE_MIDI: int = 60  # Middle C (C4) corresponds to Col 0 relative to E4-F5 treble staff


@dataclass(frozen=True)
class ColumnSpec:
    index: int              # 0..14
    number: int             # 1..15
    printed_label: str      # Exact label on Kikkerland strip ("C".."C")
    octave_label: str       # Disambiguated label ("C1", "D1", ..., "C2", ..., "C3")
    is_bold: bool           # True on E, G, B, D, F treble staff lines
    semitone_offset: int    # 0..24 above Low C
    sounding_midi: int      # 72..96 (C5..C7) for realistic WebAudio music box playback
    x_mm: float             # Center X coordinate from left strip edge (6.5..34.5 mm)
    landmark_hint: str      # Quick visual guide relative to bold E-G-B-D-F lines


LANDMARK_HINTS: List[str] = [
    "Leftmost line (2 left of Bold E)",
    "1 left of Bold E",
    "ON Bold Line 1 (E)",
    "Space between Bold E & G",
    "ON Bold Line 2 (G)",
    "Space between Bold G & B",
    "ON Bold Line 3 (Center B)",
    "Space between Bold B & D (Mid C)",
    "ON Bold Line 4 (D)",
    "Space between Bold D & F",
    "ON Bold Line 5 (F)",
    "1 right of Bold F",
    "2 right of Bold F",
    "3 right of Bold F",
    "Rightmost line (Top C)",
]

OCTAVE_LABELS: List[str] = [
    "C (Low)", "D (Low)", "E (Low)", "F (Low)", "G (Low)", "A (Low)", "B (Low)",
    "C (Mid)", "D (High)", "E (High)", "F (High)", "G (High)", "A (High)", "B (High)",
    "C (Top)",
]

COLUMNS: List[ColumnSpec] = [
    ColumnSpec(
        index=i,
        number=i + 1,
        printed_label=PRINTED_LABELS[i],
        octave_label=OCTAVE_LABELS[i],
        is_bold=(i in BOLD_COLUMN_INDICES),
        semitone_offset=RELATIVE_SEMITONES[i],
        sounding_midi=SOUNDING_BASE_MIDI + RELATIVE_SEMITONES[i],
        x_mm=round(SIDE_MARGIN_MM + i * COLUMN_SPACING_MM, 3),
        landmark_hint=LANDMARK_HINTS[i],
    )
    for i in range(NUM_COLUMNS)
]


def get_hardware_spec_dict() -> dict:
    """Return JSON-serializable hardware specification for the frontend."""
    return {
        "strip_width_mm": STRIP_WIDTH_MM,
        "num_columns": NUM_COLUMNS,
        "column_spacing_mm": COLUMN_SPACING_MM,
        "side_margin_mm": SIDE_MARGIN_MM,
        "hole_diameter_mm": HOLE_DIAMETER_MM,
        "default_existing_strip_usable_mm": DEFAULT_EXISTING_STRIP_USABLE_MM,
        "default_existing_grid_spacing_mm": DEFAULT_EXISTING_GRID_SPACING_MM,
        "default_mm_per_beat": DEFAULT_MM_PER_BEAT,
        "min_same_note_repeat_mm": MIN_SAME_NOTE_REPEAT_MM,
        "bold_column_indices": BOLD_COLUMN_INDICES,
        "printed_labels": PRINTED_LABELS,
        "columns": [asdict(c) for c in COLUMNS],
    }
