"""Core music parsing, scale/key detection, optimal 15-note transposition, and strip layout engine."""

import io
import math
import re
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Tuple
import mido

from backend.kikkerland import (
    COLUMNS,
    SEMITONE_TO_COLUMN,
    WRITTEN_BASE_MIDI,
    SOUNDING_BASE_MIDI,
    MIN_SAME_NOTE_REPEAT_MM,
    DEFAULT_MM_PER_BEAT,
    DEFAULT_EXISTING_STRIP_USABLE_MM,
    DEFAULT_EXISTING_GRID_SPACING_MM,
)

PITCH_CLASS_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
C_MAJOR_PCS = {0, 2, 4, 5, 7, 9, 11}

# Krumhansl-Schmuckler key profiles for musical key estimation
MAJOR_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MINOR_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


@dataclass
class TrackInfo:
    index: int
    name: str
    note_count: int
    min_midi: int
    max_midi: int
    avg_midi: float
    is_drum: bool
    default_selected: bool


@dataclass
class NoteEvent:
    track_idx: int
    midi: int
    start_beat: float
    duration_beats: float
    velocity: int = 90


@dataclass
class ParsedSong:
    song_id: str
    title: str
    source: str
    bpm: float
    beats_per_bar: float
    total_beats: float
    declared_key: Optional[str]
    tracks: List[TrackInfo]
    notes: List[NoteEvent]
    metadata: dict

    def to_summary_dict(self) -> dict:
        return {
            "song_id": self.song_id,
            "title": self.title,
            "source": self.source,
            "bpm": round(self.bpm, 1),
            "beats_per_bar": self.beats_per_bar,
            "total_beats": round(self.total_beats, 3),
            "total_bars": max(1, math.ceil(self.total_beats / max(1.0, self.beats_per_bar))),
            "total_seconds": round(self.total_beats * 60.0 / max(20.0, self.bpm), 2),
            "declared_key": self.declared_key,
            "tracks": [asdict(t) for t in self.tracks],
            "note_preview": [
                {
                    "t": n.track_idx,
                    "m": n.midi,
                    "b": round(n.start_beat, 3),
                    "d": round(n.duration_beats, 3),
                }
                for n in self.notes[:4000]
            ],
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# MIDI Parsing
# ---------------------------------------------------------------------------

# General MIDI Program Names (0-indexed 0..127) for labeling full-band MIDI tracks
GM_PROGRAM_NAMES = [
    "Acoustic Grand Piano", "Bright Piano", "Electric Grand", "Honky-tonk Piano",
    "Electric Piano 1", "Electric Piano 2", "Harpsichord", "Clavinet",
    "Celesta", "Glockenspiel", "Music Box", "Vibraphone", "Marimba", "Xylophone", "Tubular Bells", "Dulcimer",
    "Drawbar Organ", "Percussive Organ", "Rock Organ", "Church Organ", "Reed Organ", "Accordion", "Harmonica", "Tango Accordion",
    "Nylon Guitar", "Steel Guitar", "Jazz Guitar", "Clean Guitar", "Muted Guitar", "Overdriven Guitar", "Distortion Guitar", "Guitar Harmonics",
    "Acoustic Bass", "Finger Bass", "Picked Bass", "Fretless Bass", "Slap Bass 1", "Slap Bass 2", "Synth Bass 1", "Synth Bass 2",
    "Violin", "Viola", "Cello", "Contrabass", "Tremolo Strings", "Pizzicato Strings", "Orchestral Harp", "Timpani",
    "String Ensemble 1", "String Ensemble 2", "Synth Strings 1", "Synth Strings 2", "Choir Aahs", "Voice Oohs", "Synth Voice", "Orchestra Hit",
    "Trumpet", "Trombone", "Tuba", "Muted Trumpet", "French Horn", "Brass Section", "Synth Brass 1", "Synth Brass 2",
    "Soprano Sax", "Alto Sax", "Tenor Sax", "Baritone Sax", "Oboe", "English Horn", "Bassoon", "Clarinet",
    "Piccolo", "Flute", "Recorder", "Pan Flute", "Blown Bottle", "Shakuhachi", "Whistle", "Ocarina",
    "Synth Lead (Square)", "Synth Lead (Saw)", "Synth Lead (Calliope)", "Synth Lead (Chiff)",
    "Synth Lead (Charang)", "Synth Lead (Voice)", "Synth Lead (Fifths)", "Synth Lead (Bass+Lead)",
    "Synth Pad (New Age)", "Synth Pad (Warm)", "Synth Pad (Polysynth)", "Synth Pad (Choir)",
    "Synth Pad (Bowed)", "Synth Pad (Metallic)", "Synth Pad (Halo)", "Synth Pad (Sweep)",
    "FX Rain", "FX Soundtrack", "FX Crystal", "FX Atmosphere", "FX Brightness", "FX Goblins", "FX Echoes", "FX Sci-Fi",
    "Sitar", "Banjo", "Shamisen", "Koto", "Kalimba", "Bagpipe", "Fiddle", "Shanai",
    "Tinkle Bell", "Agogo", "Steel Drums", "Woodblock", "Taiko Drum", "Melodic Tom", "Synth Drum", "Reverse Cymbal",
    "Guitar Fret Noise", "Breath Noise", "Seashore", "Bird Tweet", "Telephone", "Helicopter", "Applause", "Gunshot",
]


def parse_midi_bytes(
    midi_bytes: bytes,
    song_id: str = "upload:midi",
    title: str = "Imported MIDI",
    source: str = "upload",
    metadata: Optional[dict] = None,
) -> ParsedSong:
    """Parse standard MIDI file bytes into beat-aligned NoteEvents and TrackInfo."""
    mid = mido.MidiFile(file=io.BytesIO(midi_bytes))
    tpb = max(1, mid.ticks_per_beat)

    bpm = 120.0
    beats_per_bar = 4.0
    declared_key: Optional[str] = None
    found_tempo = False

    tracks_out: List[TrackInfo] = []
    track_programs: Dict[int, Optional[int]] = {}
    all_notes: List[NoteEvent] = []

    for t_idx, track in enumerate(mid.tracks):
        abs_ticks = 0
        track_name = track.name.strip() if track.name else ""
        active: Dict[Tuple[int, int], Tuple[int, int]] = {}
        track_notes: List[NoteEvent] = []
        channels_used = set()
        first_program: Optional[int] = None

        for msg in track:
            abs_ticks += msg.time
            if msg.type == "set_tempo" and not found_tempo and msg.tempo > 0:
                bpm = max(30.0, min(260.0, mido.tempo2bpm(msg.tempo)))
                found_tempo = True
            elif msg.type == "time_signature":
                beats_per_bar = msg.numerator * (4.0 / max(1, msg.denominator))
            elif msg.type == "key_signature" and not declared_key:
                declared_key = msg.key
            elif msg.type == "program_change" and first_program is None and getattr(msg, "channel", 0) != 9:
                first_program = msg.program
            elif msg.type == "note_on" and msg.velocity > 0:
                channels_used.add(msg.channel)
                key = (msg.channel, msg.note)
                if key in active:
                    st_tick, st_vel = active.pop(key)
                    dur_beats = max(0.125, (abs_ticks - st_tick) / tpb)
                    track_notes.append(NoteEvent(t_idx, msg.note, st_tick / tpb, dur_beats, st_vel))
                active[key] = (abs_ticks, msg.velocity)
            elif msg.type in ("note_off", "note_on") and (msg.type == "note_off" or msg.velocity == 0):
                key = (msg.channel, msg.note)
                if key in active:
                    st_tick, st_vel = active.pop(key)
                    dur_beats = max(0.125, (abs_ticks - st_tick) / tpb)
                    track_notes.append(NoteEvent(t_idx, msg.note, st_tick / tpb, dur_beats, st_vel))

        for (ch, pitch), (st_tick, st_vel) in active.items():
            dur_beats = max(0.25, (abs_ticks - st_tick) / tpb)
            track_notes.append(NoteEvent(t_idx, pitch, st_tick / tpb, dur_beats, st_vel))

        if not track_notes:
            continue

        is_drum = (channels_used == {9}) or ("drum" in track_name.lower())
        gm_name = GM_PROGRAM_NAMES[first_program] if (first_program is not None and 0 <= first_program < 128 and not is_drum) else ""
        if is_drum:
            display_name = track_name or "Drums / Percussion"
        elif track_name and gm_name and gm_name.lower() not in track_name.lower():
            display_name = f"{track_name} · {gm_name}"
        elif track_name:
            display_name = track_name
        elif gm_name:
            display_name = f"Ch {len(tracks_out) + 1} · {gm_name}"
        else:
            display_name = f"Track {len(tracks_out) + 1}"

        pitches = [n.midi for n in track_notes]
        track_programs[t_idx] = first_program
        t_info = TrackInfo(
            index=t_idx,
            name=display_name,
            note_count=len(track_notes),
            min_midi=min(pitches),
            max_midi=max(pitches),
            avg_midi=round(sum(pitches) / len(pitches), 1),
            is_drum=is_drum,
            default_selected=not is_drum,
        )
        tracks_out.append(t_info)
        all_notes.extend(track_notes)

    if not all_notes:
        raise ValueError("MIDI file contains no playable note events.")

    min_beat = min(n.start_beat for n in all_notes)
    if min_beat > 0.0:
        for n in all_notes:
            n.start_beat = round(n.start_beat - min_beat, 4)

    # Smart default track selection for multi-track pop/rock arrangements (avoid bass & chord-pad mud)
    non_drum = [t for t in tracks_out if not t.is_drum]
    total_non_drum_notes = sum(t.note_count for t in non_drum)
    if len(non_drum) >= 2 and total_non_drum_notes > 260:
        def _melody_rank(t: TrackInfo) -> Tuple[int, int, float, float]:
            prog = track_programs.get(t.index)
            is_bass = (prog is not None and 32 <= prog <= 39) or ("bass" in t.name.lower()) or (t.avg_midi < 50)
            lead_kw = any(
                k in t.name.lower()
                for k in ("melody", "vocal", "voice", "lead", "flute", "ocarina", "music box", "sax", "violin", "solo")
            )
            return (
                0 if is_bass else 1,
                1 if lead_kw else 0,
                t.avg_midi,
                -abs(t.note_count - 220),
            )

        scored = sorted(non_drum, key=_melody_rank, reverse=True)
        keep_ids = {scored[0].index}
        if len(scored) > 1 and scored[1].avg_midi >= 56 and "bass" not in scored[1].name.lower():
            keep_ids.add(scored[1].index)
        for t in tracks_out:
            t.default_selected = (t.index in keep_ids)

    all_notes.sort(key=lambda n: (n.start_beat, n.midi))
    total_beats = max(n.start_beat + n.duration_beats for n in all_notes)

    return ParsedSong(
        song_id=song_id,
        title=title,
        source=source,
        bpm=bpm,
        beats_per_bar=beats_per_bar,
        total_beats=total_beats,
        declared_key=declared_key,
        tracks=tracks_out,
        notes=all_notes,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# ABC Notation Parsing
# ---------------------------------------------------------------------------

# Key signature sharps/flats mapped by diatonic letter ("C".."B") -> semitone adjustment (-1, 0, +1)
_SHARP_ORDER = ["F", "C", "G", "D", "A", "E", "B"]
_FLAT_ORDER = ["B", "E", "A", "D", "G", "C", "F"]

_KEY_FIFTHS: Dict[str, int] = {
    "C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F#": 6, "C#": 7,
    "F": -1, "BB": -2, "EB": -3, "AB": -4, "DB": -5, "GB": -6, "CB": -7,
    "AM": 0, "EM": 1, "BM": 2, "F#M": 3, "C#M": 4, "G#M": 5, "D#M": 6,
    "DM": -1, "GM": -2, "CM": -3, "FM": -4, "BBM": -5, "EBM": -6,
    # Modes (Dorian, Mixolydian)
    "DDOR": 0, "ADOR": 1, "EDOR": 2, "BDOR": 3, "GDOR": -1, "CDOR": -2,
    "GMIX": 0, "DMIX": 1, "AMIX": 2, "EMIX": 3, "CMIX": -1, "FMIX": -2,
}

_LETTER_BASE_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _parse_key_accidentals(key_str: str) -> Dict[str, int]:
    s = key_str.strip()
    if not s:
        return {}
    m = re.match(r"^([A-Ga-g])([#b]?)\s*(.*)$", s)
    if not m:
        return {}
    tonic = m.group(1).upper() + m.group(2).upper()
    mode_raw = m.group(3).strip().lower()
    if mode_raw.startswith("min") or mode_raw == "m":
        lookup = tonic + "M"
    elif mode_raw.startswith("dor"):
        lookup = tonic + "DOR"
    elif mode_raw.startswith("mix"):
        lookup = tonic + "MIX"
    else:
        lookup = tonic

    fifths = _KEY_FIFTHS.get(lookup, 0)
    acc: Dict[str, int] = {}
    if fifths > 0:
        for ch in _SHARP_ORDER[:fifths]:
            acc[ch] = 1
    elif fifths < 0:
        for ch in _FLAT_ORDER[: -fifths]:
            acc[ch] = -1
    return acc


def _parse_fraction(s: str, default: float = 1.0) -> float:
    s = s.strip()
    if not s:
        return default
    if "/" in s:
        parts = s.split("/", 1)
        num = float(parts[0]) if parts[0] else 1.0
        den_str = parts[1]
        if not den_str:
            den = 2.0
        else:
            den = float(den_str)
        return num / max(0.001, den)
    return float(s)


def parse_abc_string(
    abc_text: str,
    song_id: str = "upload:abc",
    fallback_title: str = "ABC Tune",
    source: str = "abc",
    metadata: Optional[dict] = None,
) -> ParsedSong:
    """Parse standard ABC notation into a beat-aligned ParsedSong."""
    title = fallback_title
    unit_len_quarters = 0.5  # Default L:1/8 = 0.5 quarter-note beats
    beats_per_bar = 4.0
    bpm = 120.0
    declared_key = "C"
    key_acc: Dict[str, int] = {}

    body_lines: List[str] = []
    for raw_line in abc_text.splitlines():
        line = raw_line.split("%", 1)[0].strip()
        if not line:
            continue
        if len(line) >= 2 and line[1] == ":" and line[0].isalpha():
            hdr, val = line[0].upper(), line[2:].strip()
            if hdr == "T" and title == fallback_title:
                title = val
            elif hdr == "M":
                if val.upper() == "C":
                    beats_per_bar = 4.0
                elif val.upper() == "C|":
                    beats_per_bar = 4.0
                elif "/" in val:
                    n_s, d_s = val.split("/", 1)
                    beats_per_bar = float(n_s) * (4.0 / float(d_s))
            elif hdr == "L":
                unit_len_quarters = _parse_fraction(val, 0.125) * 4.0
            elif hdr == "Q":
                if "=" in val:
                    lhs, rhs = val.split("=", 1)
                    ref_quarters = _parse_fraction(lhs, 0.25) * 4.0
                    bpm = float(re.sub(r"[^\d.]", "", rhs) or 120.0) * ref_quarters
                else:
                    bpm = float(re.sub(r"[^\d.]", "", val) or 120.0)
            elif hdr == "K":
                declared_key = val
                key_acc = _parse_key_accidentals(val)
            continue
        body_lines.append(line)

    body = " ".join(body_lines)
    # Remove guitar chord annotations "Am" and decorations !trill!
    body = re.sub(r'"[^"]*"', "", body)
    body = re.sub(r"![^!]*!", "", body)

    token_re = re.compile(
        r"(?P<bar>\|+|:\||\|:|\[1|\[2|\[\||\|\])"
        r"|(?P<chord>\[[A-Ga-g^_=,'0-9/]+\][0-9/]*)"
        r"|(?P<note>(?:\^{1,2}|_{1,2}|=)?[A-Ga-g][,']*[0-9/]*)"
        r"|(?P<rest>[zZxX][0-9/]*)"
        r"|(?P<broken>[<>]+)"
        r"|(?P<tie>-)"
    )

    notes: List[NoteEvent] = []
    cur_beat = 0.0
    bar_acc: Dict[str, int] = {}
    pending_broken_mul = 1.0
    next_broken_mul = 1.0
    tie_prev = False

    def decode_single_pitch(tok: str) -> Tuple[int, str]:
        m = re.match(r"^(\^{1,2}|_{1,2}|=)?([A-Ga-g])([,']*)(.*)$", tok)
        if not m:
            return 60, ""
        acc_str, letter, oct_str, dur_str = m.groups()
        upper = letter.upper()
        base_octave = 4 if letter.isupper() else 5
        octave_shift = oct_str.count("'") - oct_str.count(",")
        octave = base_octave + octave_shift

        if acc_str:
            if acc_str == "=":
                alter = 0
            elif acc_str.startswith("^"):
                alter = len(acc_str)
            else:
                alter = -len(acc_str)
            bar_acc[f"{upper}{octave}"] = alter
        elif f"{upper}{octave}" in bar_acc:
            alter = bar_acc[f"{upper}{octave}"]
        else:
            alter = key_acc.get(upper, 0)

        midi_num = (octave + 1) * 12 + _LETTER_BASE_PC[upper] + alter
        return max(12, min(108, midi_num)), dur_str

    tokens = list(token_re.finditer(body))
    for i, m in enumerate(tokens):
        kind = m.lastgroup
        txt = m.group(0)
        if kind == "bar":
            bar_acc.clear()
        elif kind == "broken":
            if ">" in txt:
                k = len(txt)
                # Retroactively lengthen previous note if exists and shorten next
                if notes:
                    extra = notes[-1].duration_beats * (1.0 - 0.5 ** k)
                    notes[-1].duration_beats += extra
                    cur_beat += extra
                next_broken_mul = 0.5 ** k
            elif "<" in txt:
                k = len(txt)
                if notes:
                    cut = notes[-1].duration_beats * (1.0 - 0.5 ** k)
                    notes[-1].duration_beats -= cut
                    cur_beat -= cut
                next_broken_mul = 2.0 - (0.5 ** (k - 1)) if k == 1 else 1.5
        elif kind == "tie":
            tie_prev = True
        elif kind == "rest":
            dur_str = re.sub(r"^[zZxX]", "", txt)
            dur = _parse_fraction(dur_str, 1.0) * unit_len_quarters * next_broken_mul
            next_broken_mul = 1.0
            tie_prev = False
            cur_beat += dur
        elif kind == "note":
            midi_num, dur_str = decode_single_pitch(txt)
            dur = _parse_fraction(dur_str, 1.0) * unit_len_quarters * next_broken_mul
            next_broken_mul = 1.0
            if tie_prev and notes and notes[-1].midi == midi_num:
                notes[-1].duration_beats += dur
            else:
                notes.append(NoteEvent(0, midi_num, round(cur_beat, 4), round(dur, 4), 92))
            tie_prev = False
            cur_beat += dur
        elif kind == "chord":
            inner_m = re.match(r"^\[([^\]]+)\]([0-9/]*)$", txt)
            if not inner_m:
                continue
            inner, outer_dur_str = inner_m.groups()
            sub_notes = re.findall(r"(?:\^{1,2}|_{1,2}|=)?[A-Ga-g][,']*[0-9/]*", inner)
            outer_mul = _parse_fraction(outer_dur_str, 1.0) * next_broken_mul
            next_broken_mul = 1.0
            max_dur = 0.0
            for sn in sub_notes:
                midi_num, dur_str = decode_single_pitch(sn)
                dur = _parse_fraction(dur_str, 1.0) * unit_len_quarters * outer_mul
                max_dur = max(max_dur, dur)
                notes.append(NoteEvent(0, midi_num, round(cur_beat, 4), round(dur, 4), 90))
            tie_prev = False
            cur_beat += max_dur

    if not notes:
        raise ValueError("ABC notation contained no playable notes.")

    pitches = [n.midi for n in notes]
    track = TrackInfo(
        index=0,
        name="Melody",
        note_count=len(notes),
        min_midi=min(pitches),
        max_midi=max(pitches),
        avg_midi=round(sum(pitches) / len(pitches), 1),
        is_drum=False,
        default_selected=True,
    )
    total_beats = max(n.start_beat + n.duration_beats for n in notes)

    return ParsedSong(
        song_id=song_id,
        title=title,
        source=source,
        bpm=max(40.0, min(240.0, bpm)),
        beats_per_bar=beats_per_bar,
        total_beats=total_beats,
        declared_key=declared_key,
        tracks=[track],
        notes=notes,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Key / Scale Detection & Optimal 15-Note Arrangement Engine
# ---------------------------------------------------------------------------

def detect_key_signature(notes: List[NoteEvent]) -> Dict[str, object]:
    """Estimate musical key & mode using duration-weighted pitch-class correlation."""
    pc_weights = [0.0] * 12
    for n in notes:
        pc_weights[n.midi % 12] += max(0.2, n.duration_beats)

    total_w = sum(pc_weights) or 1.0
    best_score = -1e9
    best_tonic = 0
    best_mode = "Major"

    for tonic in range(12):
        maj_score = sum(pc_weights[(tonic + i) % 12] * MAJOR_PROFILE[i] for i in range(12))
        min_score = sum(pc_weights[(tonic + i) % 12] * MINOR_PROFILE[i] for i in range(12))
        if maj_score > best_score:
            best_score = maj_score
            best_tonic = tonic
            best_mode = "Major"
        if min_score > best_score:
            best_score = min_score
            best_tonic = tonic
            best_mode = "Minor"

    native_c_ratio = sum(pc_weights[pc] for pc in C_MAJOR_PCS) / total_w
    return {
        "tonic_pc": best_tonic,
        "tonic_name": PITCH_CLASS_NAMES[best_tonic],
        "mode": best_mode,
        "key_name": f"{PITCH_CLASS_NAMES[best_tonic]} {best_mode}",
        "native_c_major_ratio": round(native_c_ratio, 4),
    }


def _evaluate_shift(notes: List[NoteEvent], shift: int) -> dict:
    """Score a candidate semitone shift against Kikkerland's 15-note C4..C6 (60..84) comb."""
    total = len(notes)
    if total == 0:
        return {
            "shift": shift,
            "in_scale_count": 0,
            "in_range_count": 0,
            "direct_playable_count": 0,
            "in_scale_pct": 100.0,
            "in_range_pct": 100.0,
            "score": 0.0,
        }

    in_scale = 0
    in_range = 0
    direct_playable = 0

    for n in notes:
        rel = (n.midi + shift) - WRITTEN_BASE_MIDI
        is_c_maj = (rel % 12) in C_MAJOR_PCS
        is_span = 0 <= rel <= 24
        if is_c_maj:
            in_scale += 1
        if is_span:
            in_range += 1
        if is_c_maj and is_span:
            direct_playable += 1

    in_scale_ratio = in_scale / total
    in_range_ratio = in_range / total
    direct_ratio = direct_playable / total

    # Primary priority: diatonic C-major purity, secondary: 2-octave range fit, tertiary: minimal shift
    score = (
        in_scale_ratio * 1000.0
        + direct_ratio * 320.0
        + in_range_ratio * 120.0
        - abs(shift) * 0.35
    )

    semis_mod = shift % 12
    octaves = int(round(shift / 12.0))
    return {
        "shift": shift,
        "semitone_mod": semis_mod if semis_mod <= 6 else semis_mod - 12,
        "octave_approx": octaves,
        "in_scale_count": in_scale,
        "in_range_count": in_range,
        "direct_playable_count": direct_playable,
        "out_of_scale_count": total - in_scale,
        "out_of_range_count": total - in_range,
        "in_scale_pct": round(in_scale_ratio * 100.0, 1),
        "in_range_pct": round(in_range_ratio * 100.0, 1),
        "direct_pct": round(direct_ratio * 100.0, 1),
        "score": round(score, 3),
    }


def _snap_semitone_to_c_major(rel_semi: int) -> int:
    """Snap a chromatic relative semitone to the nearest C-major white key."""
    pc = rel_semi % 12
    if pc in C_MAJOR_PCS:
        return rel_semi
    # Prefer stepping down on sharp-4/flat-7, up on leading tone if needed; +/-1 is always white!
    down = rel_semi - 1
    up = rel_semi + 1
    if (down % 12) in C_MAJOR_PCS and (up % 12) in C_MAJOR_PCS:
        # Musical heuristic: F#(6)->G(7), C#(1)->D(2), G#(8)->A(9), Bb(10)->A(9), Eb(3)->E(4)
        if pc in (1, 3, 6, 8):
            return up
        return down
    return down if (down % 12) in C_MAJOR_PCS else up


def _fold_into_two_octaves(rel_semi: int) -> int:
    """Fold a diatonic relative semitone into [0..24] by octave shifts."""
    while rel_semi < 0:
        rel_semi += 12
    while rel_semi > 24:
        rel_semi -= 12
    return rel_semi


def arrange_song_slice(
    song: ParsedSong,
    selected_tracks: Optional[List[int]] = None,
    start_beat: float = 0.0,
    end_beat: Optional[float] = None,
    transpose_semitones: Optional[int] = None,
    accidental_mode: str = "omit",          # "omit" | "snap_nearest"
    range_mode: str = "fold_octave",        # "fold_octave" | "clip"
    mm_per_beat: float = DEFAULT_MM_PER_BEAT,
    grid_snap_mm: float = DEFAULT_EXISTING_GRID_SPACING_MM,
    existing_strip_usable_mm: float = DEFAULT_EXISTING_STRIP_USABLE_MM,
    existing_grid_spacing_mm: float = DEFAULT_EXISTING_GRID_SPACING_MM,
    auto_resolve_repeats: bool = True,
    manual_edits: Optional[List[dict]] = None,
) -> dict:
    """
    Analyze scale compatibility, determine optimal transposition (or apply user shift),
    quantize to Kikkerland 15-note punch coordinates, check repeat collisions, and
    generate row-by-row punch instructions.
    """
    if selected_tracks is None:
        selected_tracks = [t.index for t in song.tracks if t.default_selected]
        if not selected_tracks and song.tracks:
            selected_tracks = [song.tracks[0].index]
    track_set = set(selected_tracks)

    max_song_beat = max(1.0, song.total_beats)
    s_beat = max(0.0, min(start_beat, max_song_beat - 0.25))
    e_beat = max_song_beat if end_beat is None else max(s_beat + 0.5, min(end_beat, max_song_beat))

    slice_notes = [
        n for n in song.notes
        if (n.track_idx in track_set) and (s_beat - 1e-4 <= n.start_beat < e_beat - 1e-4)
    ]

    key_info = detect_key_signature(slice_notes) if slice_notes else {
        "tonic_pc": 0, "tonic_name": "C", "mode": "Major", "key_name": "C Major", "native_c_major_ratio": 1.0
    }

    # Evaluate all candidate shifts in [-36, +36]
    candidates = [_evaluate_shift(slice_notes, sh) for sh in range(-36, 37)]
    ranked_candidates = sorted(candidates, key=lambda c: c["score"], reverse=True)
    best_candidate = ranked_candidates[0]

    # Deduplicate top candidates by distinct pitch-class / octave behavior for clean UI chips
    top_candidates = ranked_candidates[:6]

    chosen_shift = best_candidate["shift"] if transpose_semitones is None else int(transpose_semitones)
    chosen_eval = _evaluate_shift(slice_notes, chosen_shift)
    zero_eval = _evaluate_shift(slice_notes, 0)

    # Determine clear user-facing scale status & warning message
    if not slice_notes:
        scale_status = "empty"
        scale_message = "No notes in the selected section/tracks. Expand the time range or enable another track."
    elif zero_eval["out_of_scale_count"] == 0 and chosen_shift % 12 == 0:
        scale_status = "native_match"
        scale_message = (
            f"Detected {key_info['key_name']} — matches Kikkerland's C Major scale natively "
            f"with 100% diatonic accuracy."
        )
    elif chosen_eval["out_of_scale_count"] == 0:
        scale_status = "transposed_match"
        sign = "+" if chosen_shift > 0 else ""
        scale_message = (
            f"Original slice is in {key_info['key_name']} ({zero_eval['out_of_scale_count']} sharp/flat notes "
            f"would fall outside C Major). Shifting by {sign}{chosen_shift} semitones maps 100% of notes "
            f"cleanly onto your C Major strip!"
        )
    else:
        scale_status = "chromatic_warning"
        sign = "+" if chosen_shift > 0 else ""
        action_desc = "omitted" if accidental_mode == "omit" else "snapped to the nearest C-major note"
        scale_message = (
            f"Scale Warning: Song ({key_info['key_name']}) uses non-diatonic accidentals! "
            f"At shift {sign}{chosen_shift} semitones, {chosen_eval['out_of_scale_count']} of {len(slice_notes)} "
            f"notes ({round(100 - chosen_eval['in_scale_pct'], 1)}%) are sharps/flats not on the Kikkerland comb "
            f"and are currently {action_desc}."
        )
        if best_candidate["in_scale_pct"] > chosen_eval["in_scale_pct"] + 0.5:
            b_sign = "+" if best_candidate["shift"] > 0 else ""
            scale_message += (
                f" Tip: Shift {b_sign}{best_candidate['shift']} achieves {best_candidate['in_scale_pct']}% in-scale."
            )

    # Map notes to Kikkerland punch coordinates
    # Track original slice notes for side-by-side "Original Audio" comparison
    original_audio_notes = [
        {
            "midi": n.midi,
            "beat": round(n.start_beat - s_beat, 4),
            "dur": round(n.duration_beats, 4),
        }
        for n in slice_notes
    ]

    raw_punches: Dict[Tuple[int, float], dict] = {}
    dropped_accidentals = 0
    snapped_accidentals = 0
    folded_octaves = 0
    clipped_range = 0

    # Normalize start offset inside slice so first punch begins right at y_mm = 0 (or beat offset)
    first_note_beat = min((n.start_beat for n in slice_notes), default=s_beat)
    beat_origin = s_beat  # Keep musical bar alignment from slice start

    for n in slice_notes:
        rel_semi = (n.midi + chosen_shift) - WRITTEN_BASE_MIDI
        was_accidental = (rel_semi % 12) not in C_MAJOR_PCS

        if was_accidental:
            if accidental_mode == "omit":
                dropped_accidentals += 1
                continue
            rel_semi = _snap_semitone_to_c_major(rel_semi)
            snapped_accidentals += 1

        was_folded = False
        if rel_semi < 0 or rel_semi > 24:
            if range_mode == "clip":
                clipped_range += 1
                continue
            rel_semi = _fold_into_two_octaves(rel_semi)
            folded_octaves += 1
            was_folded = True

        col_idx = SEMITONE_TO_COLUMN.get(rel_semi)
        if col_idx is None:
            continue

        y_mm = (n.start_beat - beat_origin) * mm_per_beat
        if grid_snap_mm and grid_snap_mm > 0:
            y_mm = round(y_mm / grid_snap_mm) * grid_snap_mm
        y_mm = round(max(0.0, y_mm), 3)

        key = (col_idx, y_mm)
        if key not in raw_punches:
            col_spec = COLUMNS[col_idx]
            raw_punches[key] = {
                "col": col_idx,
                "col_num": col_spec.number,
                "label": col_spec.printed_label,
                "octave_label": col_spec.octave_label,
                "is_bold": col_spec.is_bold,
                "sounding_midi": col_spec.sounding_midi,
                "x_mm": col_spec.x_mm,
                "y_mm": y_mm,
                "beat": round(y_mm / max(0.5, mm_per_beat), 4),
                "was_snapped": was_accidental,
                "was_folded": was_folded,
                "is_manual": False,
                "repeat_warning": False,
            }

    # Apply manual hole edits from interactive canvas ({action: "add"|"remove", col: int, y_mm: float})
    for edit in (manual_edits or []):
        c_idx = int(edit.get("col", -1))
        if not (0 <= c_idx < 15):
            continue
        e_y = float(edit.get("y_mm", 0.0))
        if grid_snap_mm and grid_snap_mm > 0:
            e_y = round(e_y / grid_snap_mm) * grid_snap_mm
        e_y = round(max(0.0, e_y), 3)
        action = edit.get("action")
        if action == "remove":
            # Remove exact or closest within half grid step
            tol = max(0.6, (grid_snap_mm or 1.0) * 0.55)
            to_del = [k for k in raw_punches if k[0] == c_idx and abs(k[1] - e_y) <= tol]
            for k in to_del:
                raw_punches.pop(k, None)
        elif action == "add":
            col_spec = COLUMNS[c_idx]
            raw_punches[(c_idx, e_y)] = {
                "col": c_idx,
                "col_num": col_spec.number,
                "label": col_spec.printed_label,
                "octave_label": col_spec.octave_label,
                "is_bold": col_spec.is_bold,
                "sounding_midi": col_spec.sounding_midi,
                "x_mm": col_spec.x_mm,
                "y_mm": e_y,
                "beat": round(e_y / max(0.5, mm_per_beat), 4),
                "was_snapped": False,
                "was_folded": False,
                "is_manual": True,
                "repeat_warning": False,
            }

    # Sort punches chronologically then left-to-right across the 15 columns
    punches = sorted(raw_punches.values(), key=lambda p: (p["y_mm"], p["col"]))

    # Mechanical same-column repeat distance verification
    resolved_punches: List[dict] = []
    last_y_by_col: Dict[int, float] = {}
    repeat_collisions_resolved = 0
    repeat_collisions_remaining = 0

    for p in punches:
        c = p["col"]
        y = p["y_mm"]
        if c in last_y_by_col and (y - last_y_by_col[c]) < MIN_SAME_NOTE_REPEAT_MM - 1e-4:
            if auto_resolve_repeats and not p["is_manual"]:
                repeat_collisions_resolved += 1
                continue
            p["repeat_warning"] = True
            repeat_collisions_remaining += 1
        last_y_by_col[c] = y
        resolved_punches.append(p)

    # Calculate pattern length and strip requirements
    max_y_mm = max((p["y_mm"] for p in resolved_punches), default=0.0)
    tail_margin_mm = 12.0
    total_pattern_mm = round(max_y_mm + (tail_margin_mm if resolved_punches else 0.0), 1)

    usable_existing = max(50.0, existing_strip_usable_mm)
    existing_strips_needed = max(1, math.ceil((max_y_mm + 4.0) / usable_existing)) if resolved_punches else 0

    # Group into row-by-row Punch Instructions for Existing Kikkerland Blank Strips
    grid_step = max(0.5, existing_grid_spacing_mm)
    rows_map: Dict[int, List[dict]] = {}
    for p in resolved_punches:
        row_zero_idx = int(round(p["y_mm"] / grid_step))
        rows_map.setdefault(row_zero_idx, []).append(p)

    punch_rows: List[dict] = []
    prev_sheet_num = 0
    prev_local_row = 0

    for row_idx in sorted(rows_map.keys()):
        row_y_mm = round(row_idx * grid_step, 2)
        sheet_num = int(row_y_mm // usable_existing) + 1
        local_y_mm = round(row_y_mm - (sheet_num - 1) * usable_existing, 2)
        local_row_num = int(round(local_y_mm / grid_step)) + 1

        if sheet_num != prev_sheet_num:
            spaces_before = max(0, local_row_num - 1)
        else:
            spaces_before = max(0, local_row_num - prev_local_row - 1)
        prev_sheet_num = sheet_num
        prev_local_row = local_row_num

        row_punches = sorted(rows_map[row_idx], key=lambda x: x["col"])
        punch_rows.append({
            "global_row": row_idx + 1,
            "sheet_number": sheet_num,
            "sheet_row": local_row_num,
            "global_y_mm": row_y_mm,
            "sheet_y_mm": local_y_mm,
            "is_space": False,
            "spaces_before": spaces_before,
            "punches": [
                {
                    "col": rp["col"],
                    "col_num": rp["col_num"],
                    "label": rp["label"],
                    "octave_label": rp["octave_label"],
                    "is_bold": rp["is_bold"],
                    "landmark_hint": COLUMNS[rp["col"]].landmark_hint,
                    "repeat_warning": rp["repeat_warning"],
                }
                for rp in row_punches
            ],
        })

    # Build full sequential strip_lines (every grid line 1..N including blank "space" rows)
    strip_lines: List[dict] = []
    if rows_map:
        max_row_idx = max(rows_map.keys())
        punched_by_global_row = {pr["global_row"]: pr for pr in punch_rows}
        for row_idx in range(max_row_idx + 1):
            g_row = row_idx + 1
            if g_row in punched_by_global_row:
                pr = punched_by_global_row[g_row]
                strip_lines.append({
                    **pr,
                    "space_index": 0,
                    "space_run_total": 0,
                })
            else:
                row_y_mm = round(row_idx * grid_step, 2)
                sheet_num = int(row_y_mm // usable_existing) + 1
                local_y_mm = round(row_y_mm - (sheet_num - 1) * usable_existing, 2)
                local_row_num = int(round(local_y_mm / grid_step)) + 1
                strip_lines.append({
                    "global_row": g_row,
                    "sheet_number": sheet_num,
                    "sheet_row": local_row_num,
                    "global_y_mm": row_y_mm,
                    "sheet_y_mm": local_y_mm,
                    "is_space": True,
                    "spaces_before": 0,
                    "space_index": 1,
                    "space_run_total": 1,
                    "punches": [],
                })

        # Annotate contiguous blank-space runs (per sheet) with 1-based space_index & space_run_total
        i = 0
        n_lines = len(strip_lines)
        while i < n_lines:
            if not strip_lines[i]["is_space"]:
                i += 1
                continue
            run_sheet = strip_lines[i]["sheet_number"]
            j = i
            while j < n_lines and strip_lines[j]["is_space"] and strip_lines[j]["sheet_number"] == run_sheet:
                j += 1
            run_len = j - i
            for k in range(run_len):
                strip_lines[i + k]["space_index"] = k + 1
                strip_lines[i + k]["space_run_total"] = run_len
            i = j

    # Estimate A4 strip columns & pages (each A4 portrait page holds 4 strips of ~232 mm usable length)
    a4_usable_per_strip_mm = 230.0
    a4_strips_needed = max(1, math.ceil(max(1.0, max_y_mm + 8.0) / a4_usable_per_strip_mm)) if resolved_punches else 1
    a4_pages_needed = math.ceil(a4_strips_needed / 4)

    return {
        "song_id": song.song_id,
        "title": song.title,
        "bpm": round(song.bpm, 1),
        "beats_per_bar": song.beats_per_bar,
        "slice": {
            "start_beat": round(s_beat, 3),
            "end_beat": round(e_beat, 3),
            "duration_beats": round(e_beat - s_beat, 3),
            "duration_seconds": round((e_beat - s_beat) * 60.0 / max(20.0, song.bpm), 1),
        },
        "scale_analysis": {
            "detected_key": key_info["key_name"],
            "declared_key": song.declared_key,
            "status": scale_status,
            "message": scale_message,
            "chosen_shift": chosen_shift,
            "chosen_eval": chosen_eval,
            "best_shift": best_candidate["shift"],
            "top_candidates": top_candidates,
        },
        "stats": {
            "input_slice_notes": len(slice_notes),
            "output_punches": len(resolved_punches),
            "dropped_accidentals": dropped_accidentals,
            "snapped_accidentals": snapped_accidentals,
            "folded_octaves": folded_octaves,
            "clipped_range": clipped_range,
            "repeat_collisions_resolved": repeat_collisions_resolved,
            "repeat_collisions_remaining": repeat_collisions_remaining,
            "pattern_length_mm": total_pattern_mm,
            "pattern_length_cm": round(total_pattern_mm / 10.0, 1),
            "existing_strips_needed": existing_strips_needed,
            "existing_strips_owned": 4,
            "exceeds_owned_strips": existing_strips_needed > 4,
            "a4_strips_needed": a4_strips_needed,
            "a4_pages_needed": a4_pages_needed,
        },
        "settings": {
            "selected_tracks": selected_tracks,
            "accidental_mode": accidental_mode,
            "range_mode": range_mode,
            "mm_per_beat": mm_per_beat,
            "grid_snap_mm": grid_snap_mm,
            "existing_strip_usable_mm": usable_existing,
            "existing_grid_spacing_mm": grid_step,
            "auto_resolve_repeats": auto_resolve_repeats,
        },
        "punches": resolved_punches,
        "punch_rows": punch_rows,
        "strip_lines": strip_lines,
        "original_audio_notes": original_audio_notes,
    }
