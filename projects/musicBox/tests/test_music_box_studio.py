"""Automated unit & integration tests for Kikkerland 15-Note Music Box Studio."""

import io
import mido
from fastapi.testclient import TestClient

from backend.kikkerland import (
    COLUMNS,
    STRIP_WIDTH_MM,
    COLUMN_SPACING_MM,
    SIDE_MARGIN_MM,
    BOLD_COLUMN_INDICES,
)
from backend.music_engine import (
    parse_abc_string,
    parse_midi_bytes,
    arrange_song_slice,
)
from backend.pdf_generator import (
    compute_a4_strip_segments,
    generate_a4_pdf,
    generate_a4_svg,
)
from backend.search_ranker import rank_search_results
from backend.app import app


def test_kikkerland_hardware_geometry():
    assert len(COLUMNS) == 15
    assert [c.printed_label for c in COLUMNS] == [
        "C", "D", "E", "F", "G", "A", "B",
        "C", "D", "E", "F", "G", "A", "B",
        "C",
    ]
    # Bold lines must be E, G, B, D, F (indices 2, 4, 6, 8, 10)
    bold_labels = [COLUMNS[i].printed_label for i in BOLD_COLUMN_INDICES]
    assert bold_labels == ["E", "G", "B", "D", "F"]
    assert SIDE_MARGIN_MM == 6.5
    assert COLUMNS[0].x_mm == 6.5
    assert COLUMNS[-1].x_mm == 34.5
    assert round(COLUMNS[-1].x_mm + SIDE_MARGIN_MM, 3) == STRIP_WIDTH_MM
    for i in range(14):
        assert round(COLUMNS[i + 1].x_mm - COLUMNS[i].x_mm, 3) == COLUMN_SPACING_MM


def test_transposition_major_keys_to_c_major():
    # Happy Birthday in F Major (contains Bb) should cleanly transpose to C Major with 0 out-of-scale notes
    client = TestClient(app)
    res = client.post("/api/load", json={"song_id": "builtin:happy-birthday"})
    assert res.status_code == 200
    data = res.json()
    sc = data["arrangement"]["scale_analysis"]
    assert sc["status"] == "transposed_match"
    assert sc["chosen_eval"]["out_of_scale_count"] == 0
    assert sc["chosen_eval"]["in_scale_pct"] == 100.0


def test_chromatic_scale_warning_and_snap_modes():
    # Für Elise contains D# and G# alongside natural D and G -> impossible to make 100% diatonic in any shift!
    client = TestClient(app)
    res = client.post("/api/load", json={"song_id": "builtin:fur-elise"})
    assert res.status_code == 200
    arr_omit = res.json()["arrangement"]
    assert arr_omit["scale_analysis"]["status"] == "chromatic_warning"
    assert arr_omit["stats"]["dropped_accidentals"] > 0

    # Switching accidental_mode to snap_nearest should snap rather than drop those chromatic notes
    res_snap = client.post(
        "/api/arrange",
        json={
            "song_id": "builtin:fur-elise",
            "accidental_mode": "snap_nearest",
            "transpose_semitones": arr_omit["scale_analysis"]["chosen_shift"],
        },
    )
    assert res_snap.status_code == 200
    arr_snap = res_snap.json()
    assert arr_snap["stats"]["snapped_accidentals"] > 0
    assert arr_snap["stats"]["dropped_accidentals"] == 0
    assert arr_snap["stats"]["output_punches"] >= arr_omit["stats"]["output_punches"]


def test_mechanical_repeat_distance_protection():
    # Rapid 16th-note repeats on the same pitch C5 (at 8mm/beat, 1/4 beat = 2.0mm < 4.5mm threshold!)
    abc = """X:1
T:Rapid Repeats
M:4/4
L:1/16
K:C
c c c c G4 |]
"""
    song = parse_abc_string(abc, song_id="test:repeats")
    arr_auto = arrange_song_slice(song, mm_per_beat=8.0, auto_resolve_repeats=True)
    assert arr_auto["stats"]["repeat_collisions_resolved"] >= 2
    assert arr_auto["stats"]["repeat_collisions_remaining"] == 0

    arr_raw = arrange_song_slice(song, mm_per_beat=8.0, auto_resolve_repeats=False)
    assert arr_raw["stats"]["repeat_collisions_remaining"] >= 2
    assert any(p["repeat_warning"] for p in arr_raw["punches"])


def test_section_slicing_and_existing_strip_sheet_numbering():
    # Long melody spanning > 412 mm so it crosses from Sheet 1 to Sheet 2
    abc = "X:1\nT:Long Scale\nM:4/4\nL:1/4\nK:C\n" + ("C D E F | G A B c | " * 10) + "\n"
    song = parse_abc_string(abc, song_id="test:long")
    full_arr = arrange_song_slice(song, start_beat=0, end_beat=80, mm_per_beat=8.0, existing_strip_usable_mm=412.0)
    assert full_arr["stats"]["existing_strips_needed"] == 2
    sheet_nums = {r["sheet_number"] for r in full_arr["punch_rows"]}
    assert sheet_nums == {1, 2}

    # Slicing beats 0..20 (20 * 8mm = 160mm) must fit on a single Kikkerland sheet!
    sliced_arr = arrange_song_slice(song, start_beat=0, end_beat=20, mm_per_beat=8.0, existing_strip_usable_mm=412.0)
    assert sliced_arr["stats"]["existing_strips_needed"] == 1
    assert sliced_arr["stats"]["output_punches"] == 20


def test_a4_pdf_and_svg_true_scale_geometry():
    # Create punches spanning 1100 mm -> should require 5 strips -> 2 A4 pages (4 strips on page 1, 1 on page 2)
    punches = [
        {
            "col": i % 15,
            "col_num": (i % 15) + 1,
            "label": COLUMNS[i % 15].printed_label,
            "x_mm": COLUMNS[i % 15].x_mm,
            "y_mm": float(i * 20),
            "repeat_warning": False,
        }
        for i in range(56)  # max y_mm = 1100 mm
    ]
    segs = compute_a4_strip_segments(punches, mm_per_beat=8.0)
    assert len(segs) == 5
    assert segs[0]["total_pages"] == 2

    pdf_bytes = generate_a4_pdf("Geometry Test", "Scale 1:1", punches)
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 2500

    svg_page1 = generate_a4_svg("Geometry Test", "Scale 1:1", punches, page_index=0)
    assert 'width="210.0mm"' in svg_page1
    assert 'height="297.0mm"' in svg_page1
    assert 'CALIBRATION: Must measure 50.0 mm' in svg_page1


def test_midi_upload_and_export_endpoints():
    # Synthesize an in-memory MIDI file in G Major (G4 A4 B4 C5 D5 E5 F#5 G5)
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    for pitch in [67, 69, 71, 72, 74, 76, 78, 79]:
        tr.append(mido.Message("note_on", note=pitch, velocity=90, time=0))
        tr.append(mido.Message("note_off", note=pitch, velocity=0, time=480))
    buf = io.BytesIO()
    mid.save(file=buf)

    client = TestClient(app)
    up = client.post(
        "/api/upload",
        files={"file": ("g_major_scale.mid", buf.getvalue(), "audio/midi")},
    )
    assert up.status_code == 200
    bundle = up.json()
    song_id = bundle["song"]["song_id"]
    # G Major has F# (MIDI 78), so optimal shift should transpose cleanly to C Major (0 out-of-scale)
    assert bundle["arrangement"]["scale_analysis"]["chosen_eval"]["out_of_scale_count"] == 0

    pdf_res = client.post("/api/export/pdf", json={"song_id": song_id})
    assert pdf_res.status_code == 200
    assert pdf_res.headers["content-type"] == "application/pdf"
    assert pdf_res.content.startswith(b"%PDF-")


def test_online_search_endpoint():
    client = TestClient(app)
    res = client.get("/api/search?q=happy+birthday&source=all")
    assert res.status_code == 200
    payload = res.json()
    assert len(payload["results"]) >= 2
    sources = {r["source"] for r in payload["results"]}
    assert "builtin" in sources


def test_generic_song_title_relevance_ranking():
    mock_items = [
        {"id": "1", "title": "Happy Holidays Intro", "artist": "Someone", "source": "musicboxmaniacs", "is_native_k15": True},
        {"id": "2", "title": "Deadbeat Holiday", "artist": "Green Day", "source": "freemidi", "is_native_k15": False},
        {"id": "3", "title": "Holiday", "artist": "Madonna", "source": "midiworld", "is_native_k15": False},
        {"id": "4", "title": "Holiday", "artist": "Green Day", "source": "freemidi", "is_native_k15": False},
    ]
    # Both split ("Holiday" + "Green Day") and single-box ("Holiday Green Day") must rank id="4" #1!
    ranked_split = rank_search_results(mock_items, song_query="Holiday", artist_query="Green Day")
    assert ranked_split[0]["id"] == "4"
    assert ranked_split[1]["id"] == "2"

    ranked_single = rank_search_results(mock_items, song_query="Holiday Green Day", artist_query="")
    assert ranked_single[0]["id"] == "4"


def test_gm_instrument_labeling_and_bass_deprioritization():
    mid = mido.MidiFile(ticks_per_beat=480)

    # Track 0: Finger Bass (Program 33) playing 200 low bass notes
    tr_bass = mido.MidiTrack()
    tr_bass.name = "Bassline"
    tr_bass.append(mido.Message("program_change", program=33, channel=0, time=0))
    for _ in range(160):
        tr_bass.append(mido.Message("note_on", note=40, velocity=90, channel=0, time=0))
        tr_bass.append(mido.Message("note_off", note=40, velocity=0, channel=0, time=240))
    mid.tracks.append(tr_bass)

    # Track 1: Lead Vocal / Flute (Program 73) playing 160 melody notes
    tr_lead = mido.MidiTrack()
    tr_lead.name = "Vocals"
    tr_lead.append(mido.Message("program_change", program=73, channel=1, time=0))
    for _ in range(160):
        tr_lead.append(mido.Message("note_on", note=67, velocity=95, channel=1, time=0))
        tr_lead.append(mido.Message("note_off", note=67, velocity=0, channel=1, time=240))
    mid.tracks.append(tr_lead)

    buf = io.BytesIO()
    mid.save(file=buf)
    song = parse_midi_bytes(buf.getvalue(), song_id="test:gm")
    assert "Finger Bass" in song.tracks[0].name
    assert "Flute" in song.tracks[1].name
    assert song.tracks[0].default_selected is False
    assert song.tracks[1].default_selected is True


def test_artist_catalog_and_holiday_green_day_live():
    client = TestClient(app)
    art_res = client.get("/api/artists?q=Green+Day")
    assert art_res.status_code == 200
    artists = art_res.json()["artists"]
    assert len(artists) >= 1

    cat_res = client.get(f"/api/artists/catalog?artist_id={artists[0]['artist_id']}")
    assert cat_res.status_code == 200
    cat_data = cat_res.json()
    assert cat_data["song_count"] >= 20
    assert any(s["title"].lower() == "holiday" for s in cat_data["songs"])

    # Also verify single-box "Holiday Green Day" ranks exact "Holiday" #1
    s_res = client.get("/api/search?q=Holiday+Green+Day")
    assert s_res.status_code == 200
    top = s_res.json()["results"][0]
    assert top["title"].lower() == "holiday"

