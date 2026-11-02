"""FastAPI server for the KIKKER-15 Mechanical Punch-Tape Studio."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
from typing import Dict, List, Optional
import uuid
import requests

from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.kikkerland import (
    get_hardware_spec_dict,
    DEFAULT_MM_PER_BEAT,
    DEFAULT_EXISTING_STRIP_USABLE_MM,
    DEFAULT_EXISTING_GRID_SPACING_MM,
)
from backend.music_engine import (
    ParsedSong,
    parse_midi_bytes,
    parse_abc_string,
    arrange_song_slice,
)
from backend.providers.builtin_library import search_builtin, get_builtin_by_id
from backend.providers.musicboxmaniacs import (
    search_musicboxmaniacs,
    search_mbm_artist_collection,
    fetch_mbm_artist_catalog,
    fetch_musicboxmaniacs_midi,
)
from backend.providers.freemidi import (
    search_freemidi_artists,
    search_freemidi_songs,
    fetch_freemidi_artist_catalog,
    fetch_freemidi_midi,
)
from backend.providers.midiworld import (
    search_midiworld,
    fetch_midiworld_midi,
)
from backend.providers.thesession import search_thesession, fetch_thesession_abc
from backend.search_ranker import rank_search_results, tokenize
from backend.pdf_generator import generate_a4_pdf, generate_a4_svg

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(
    title="KIKKER-15 // Mechanical Punch-Tape Studio",
    description="Search melodies & artist catalogs, transpose scales, audition slices, and punch or print A4 strips.",
    version="2.0.0",
)

_SONG_STORE: Dict[str, ParsedSong] = {}


def _store_song(song: ParsedSong) -> None:
    if len(_SONG_STORE) > 60:
        oldest_key = next(iter(_SONG_STORE))
        _SONG_STORE.pop(oldest_key, None)
    _SONG_STORE[song.song_id] = song


class LoadSongRequest(BaseModel):
    song_id: Optional[str] = None
    abc_text: Optional[str] = None
    midi_url: Optional[str] = None


class ArrangeRequest(BaseModel):
    song_id: str
    selected_tracks: Optional[List[int]] = None
    start_beat: float = 0.0
    end_beat: Optional[float] = None
    transpose_semitones: Optional[int] = None
    accidental_mode: str = "omit"
    range_mode: str = "fold_octave"
    mm_per_beat: float = DEFAULT_MM_PER_BEAT
    grid_snap_mm: float = DEFAULT_EXISTING_GRID_SPACING_MM
    existing_strip_usable_mm: float = DEFAULT_EXISTING_STRIP_USABLE_MM
    existing_grid_spacing_mm: float = DEFAULT_EXISTING_GRID_SPACING_MM
    auto_resolve_repeats: bool = True
    manual_edits: Optional[List[dict]] = None
    page_index: int = 0


@app.get("/api/hardware")
def api_hardware() -> dict:
    return get_hardware_spec_dict()


def _search_freemidi_with_artist_fallback(song_q: str, artist_q: str) -> List[dict]:
    """
    Search FreeMIDI intelligently:
    1) If `artist_q` is provided, look up that artist's catalog and return matching songs!
    2) If `artist_q` is empty and `song_q` has >=2 words (e.g. 'Holiday Green Day'),
       run direct song search AND also test trailing/leading word splits as an artist lookup!
    """
    items: List[dict] = []
    if artist_q:
        artists = search_freemidi_artists(artist_q, limit=3)
        if artists:
            cat = fetch_freemidi_artist_catalog(artists[0]["artist_id"])
            items.extend(cat.get("songs", []))
        if song_q:
            items.extend(search_freemidi_songs(song_q, limit=12))
        return items

    # Single-box query: run direct song search first
    items.extend(search_freemidi_songs(song_q, limit=14))
    words = tokenize(song_q)
    if len(words) >= 2:
        # Try splitting e.g. "Holiday Green Day" -> artist="Green Day" or "Green Day Holiday" -> artist="Green Day"
        candidate_artist_phrases = []
        if len(words) >= 3:
            candidate_artist_phrases.append(" ".join(words[1:]))
            candidate_artist_phrases.append(" ".join(words[:-1]))
        else:
            candidate_artist_phrases.extend([words[1], words[0]])

        for cand_art in candidate_artist_phrases[:2]:
            if len(cand_art) < 3:
                continue
            found_arts = search_freemidi_artists(cand_art, limit=2)
            for fa in found_arts[:1]:
                # Verify artist name tokens actually appear in user's query
                art_toks = set(tokenize(fa["name"]))
                if art_toks and art_toks.issubset(set(words)):
                    cat = fetch_freemidi_artist_catalog(fa["artist_id"], max_pages=5)
                    items.extend(cat.get("songs", []))
                    return items
    return items


@app.get("/api/search")
def api_search(
    q: str = Query("", description="Song title search query"),
    artist: str = Query("", description="Optional artist/band filter"),
    source: str = Query("all", description="all | musicboxmaniacs | freemidi | midiworld | thesession | builtin"),
) -> dict:
    song_q = q.strip()
    artist_q = artist.strip()
    warnings: List[str] = []
    raw_results: List[dict] = []

    if not song_q and not artist_q:
        return {"query": "", "artist": "", "results": search_builtin(""), "warnings": []}

    combined_q = f"{song_q} {artist_q}".strip()

    tasks = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        if source in ("all", "builtin"):
            tasks["builtin"] = pool.submit(search_builtin, song_q or artist_q)
        if source in ("all", "musicboxmaniacs"):
            tasks["musicboxmaniacs"] = pool.submit(search_musicboxmaniacs, song_q, artist_q, 20)
        if source in ("all", "freemidi"):
            tasks["freemidi"] = pool.submit(_search_freemidi_with_artist_fallback, song_q, artist_q)
        if source in ("all", "midiworld"):
            tasks["midiworld"] = pool.submit(search_midiworld, artist_q or song_q, 16)
        if source in ("all", "thesession") and not artist_q:
            tasks["thesession"] = pool.submit(search_thesession, song_q, 8)

        for provider_name, fut in tasks.items():
            try:
                raw_results.extend(fut.result(timeout=12))
            except Exception as exc:
                warnings.append(f"{provider_name}: {exc}")

    ranked = rank_search_results(raw_results, song_query=song_q, artist_query=artist_q)
    return {
        "query": song_q,
        "artist": artist_q,
        "results": ranked[:40],
        "warnings": warnings,
    }


@app.get("/api/artists")
def api_search_artists(q: str = Query(..., description="Artist or band name")) -> dict:
    query = q.strip()
    if not query:
        return {"query": "", "artists": [], "warnings": []}

    artists: List[dict] = []
    warnings: List[str] = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_fm = pool.submit(search_freemidi_artists, query, 12)
        f_mbm = pool.submit(search_mbm_artist_collection, query)
        try:
            artists.extend(f_fm.result(timeout=10))
        except Exception as exc:
            warnings.append(f"freemidi: {exc}")
        try:
            mbm_card = f_mbm.result(timeout=10)
            if mbm_card:
                artists.append(mbm_card)
        except Exception as exc:
            warnings.append(f"musicboxmaniacs: {exc}")

    return {"query": query, "artists": artists, "warnings": warnings}


@app.get("/api/artists/catalog")
def api_artist_catalog(artist_id: str = Query(..., description="Artist identifier")) -> dict:
    aid = artist_id.strip()
    try:
        if aid.startswith("freemidi_artist:"):
            return fetch_freemidi_artist_catalog(aid)
        if aid.startswith("mbm_artist:"):
            return fetch_mbm_artist_catalog(aid)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch artist catalog: {exc}") from exc
    raise HTTPException(status_code=400, detail=f"Unknown artist_id provider: {aid}")


def _resolve_or_load_song(song_id: str) -> ParsedSong:
    if song_id in _SONG_STORE:
        return _SONG_STORE[song_id]

    if song_id.startswith("builtin:"):
        item = get_builtin_by_id(song_id)
        if not item:
            raise HTTPException(status_code=404, detail=f"Built-in song not found: {song_id}")
        song = parse_abc_string(
            item["abc"],
            song_id=song_id,
            fallback_title=item["title"],
            source="builtin",
            metadata={"artist": item["artist"], "badge": item["badge"]},
        )
        _store_song(song)
        return song

    if song_id.startswith("mbm:"):
        try:
            midi_bytes, meta = fetch_musicboxmaniacs_midi(song_id)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to download from Music Box Maniacs: {exc}") from exc
        song = parse_midi_bytes(
            midi_bytes, song_id=song_id, title=meta.get("title", song_id), source="musicboxmaniacs", metadata=meta
        )
        _store_song(song)
        return song

    if song_id.startswith("freemidi:"):
        try:
            midi_bytes, meta = fetch_freemidi_midi(song_id)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to download from FreeMIDI: {exc}") from exc
        song = parse_midi_bytes(
            midi_bytes, song_id=song_id, title=meta.get("title", song_id), source="freemidi", metadata=meta
        )
        _store_song(song)
        return song

    if song_id.startswith("midiworld:"):
        try:
            midi_bytes, meta = fetch_midiworld_midi(song_id)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to download from MidiWorld: {exc}") from exc
        song = parse_midi_bytes(
            midi_bytes, song_id=song_id, title=meta.get("title", song_id), source="midiworld", metadata=meta
        )
        _store_song(song)
        return song

    if song_id.startswith("session:"):
        try:
            abc_text, meta = fetch_thesession_abc(song_id)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to download from The Session: {exc}") from exc
        song = parse_abc_string(
            abc_text, song_id=song_id, fallback_title=meta.get("title", song_id), source="thesession", metadata=meta
        )
        _store_song(song)
        return song

    raise HTTPException(status_code=404, detail=f"Song session expired or unknown ID: {song_id}")


@app.post("/api/load")
def api_load_song(req: LoadSongRequest) -> dict:
    if req.song_id:
        song = _resolve_or_load_song(req.song_id)
    elif req.abc_text:
        sid = f"custom:abc:{uuid.uuid4().hex[:8]}"
        try:
            song = parse_abc_string(req.abc_text, song_id=sid, fallback_title="Custom ABC Melody", source="custom_abc")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid ABC notation: {exc}") from exc
        _store_song(song)
    elif req.midi_url:
        try:
            r = requests.get(req.midi_url.strip(), timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            sid = f"url:midi:{uuid.uuid4().hex[:8]}"
            guessed_name = req.midi_url.rstrip("/").split("/")[-1] or "Remote MIDI"
            song = parse_midi_bytes(r.content, song_id=sid, title=guessed_name, source="midi_url")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Could not fetch/parse MIDI URL: {exc}") from exc
        _store_song(song)
    else:
        raise HTTPException(status_code=400, detail="Provide song_id, abc_text, or midi_url.")

    initial_end_beat = min(song.total_beats, 64.0) if song.total_beats > 72.0 else song.total_beats
    arrangement = arrange_song_slice(song, start_beat=0.0, end_beat=initial_end_beat)
    return {
        "song": song.to_summary_dict(),
        "arrangement": arrangement,
    }


@app.post("/api/upload")
async def api_upload_file(file: UploadFile = File(...)) -> dict:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    filename = file.filename or "uploaded_song"
    lower = filename.lower()
    sid = f"upload:{uuid.uuid4().hex[:8]}"
    clean_title = re.sub(r"\.(mid|midi|abc|txt)$", "", filename, flags=re.IGNORECASE)

    try:
        if lower.endswith((".abc", ".txt")):
            song = parse_abc_string(raw.decode("utf-8", errors="replace"), song_id=sid, fallback_title=clean_title)
        else:
            song = parse_midi_bytes(raw, song_id=sid, title=clean_title, source="upload")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse '{filename}': {exc}") from exc

    _store_song(song)
    initial_end_beat = min(song.total_beats, 64.0) if song.total_beats > 72.0 else song.total_beats
    arrangement = arrange_song_slice(song, start_beat=0.0, end_beat=initial_end_beat)
    return {
        "song": song.to_summary_dict(),
        "arrangement": arrangement,
    }


@app.post("/api/arrange")
def api_arrange(req: ArrangeRequest) -> dict:
    song = _resolve_or_load_song(req.song_id)
    return arrange_song_slice(
        song=song,
        selected_tracks=req.selected_tracks,
        start_beat=req.start_beat,
        end_beat=req.end_beat,
        transpose_semitones=req.transpose_semitones,
        accidental_mode=req.accidental_mode,
        range_mode=req.range_mode,
        mm_per_beat=req.mm_per_beat,
        grid_snap_mm=req.grid_snap_mm,
        existing_strip_usable_mm=req.existing_strip_usable_mm,
        existing_grid_spacing_mm=req.existing_grid_spacing_mm,
        auto_resolve_repeats=req.auto_resolve_repeats,
        manual_edits=req.manual_edits,
    )


def _build_export_subtitle(arr: dict) -> str:
    sc = arr["scale_analysis"]
    shift = sc["chosen_shift"]
    sign = f"+{shift}" if shift > 0 else str(shift)
    return (
        f"Key: {sc['detected_key']} (Shift {sign} st -> C Major)  |  "
        f"Beats {arr['slice']['start_beat']:.1f}-{arr['slice']['end_beat']:.1f}  |  "
        f"{arr['stats']['output_punches']} holes ({arr['stats']['pattern_length_cm']} cm)"
    )


@app.post("/api/export/pdf")
def api_export_pdf(req: ArrangeRequest) -> Response:
    song = _resolve_or_load_song(req.song_id)
    arr = arrange_song_slice(
        song=song,
        selected_tracks=req.selected_tracks,
        start_beat=req.start_beat,
        end_beat=req.end_beat,
        transpose_semitones=req.transpose_semitones,
        accidental_mode=req.accidental_mode,
        range_mode=req.range_mode,
        mm_per_beat=req.mm_per_beat,
        grid_snap_mm=req.grid_snap_mm,
        existing_strip_usable_mm=req.existing_strip_usable_mm,
        existing_grid_spacing_mm=req.existing_grid_spacing_mm,
        auto_resolve_repeats=req.auto_resolve_repeats,
        manual_edits=req.manual_edits,
    )
    pdf_bytes = generate_a4_pdf(
        title=song.title,
        subtitle=_build_export_subtitle(arr),
        punches=arr["punches"],
        mm_per_beat=req.mm_per_beat,
        grid_line_mm=max(2.0, req.existing_grid_spacing_mm),
    )
    safe_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", song.title).strip("_")[:40] or "music_box_strip"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_slug}_kikkerland_A4.pdf"'},
    )


@app.post("/api/export/svg")
def api_export_svg(req: ArrangeRequest) -> Response:
    song = _resolve_or_load_song(req.song_id)
    arr = arrange_song_slice(
        song=song,
        selected_tracks=req.selected_tracks,
        start_beat=req.start_beat,
        end_beat=req.end_beat,
        transpose_semitones=req.transpose_semitones,
        accidental_mode=req.accidental_mode,
        range_mode=req.range_mode,
        mm_per_beat=req.mm_per_beat,
        grid_snap_mm=req.grid_snap_mm,
        existing_strip_usable_mm=req.existing_strip_usable_mm,
        existing_grid_spacing_mm=req.existing_grid_spacing_mm,
        auto_resolve_repeats=req.auto_resolve_repeats,
        manual_edits=req.manual_edits,
    )
    svg_text = generate_a4_svg(
        title=song.title,
        subtitle=_build_export_subtitle(arr),
        punches=arr["punches"],
        mm_per_beat=req.mm_per_beat,
        grid_line_mm=max(2.0, req.existing_grid_spacing_mm),
        page_index=req.page_index,
    )
    safe_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", song.title).strip("_")[:40] or "music_box_strip"
    return Response(
        content=svg_text.encode("utf-8"),
        media_type="image/svg+xml",
        headers={"Content-Disposition": f'attachment; filename="{safe_slug}_page{req.page_index + 1}_A4.svg"'},
    )


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def serve_index() -> FileResponse:
        return FileResponse(str(FRONTEND_DIR / "index.html"))
