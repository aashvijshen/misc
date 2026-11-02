"""Music Box Maniacs search, virtual artist collection, and MIDI fetcher."""

import re
from typing import List, Dict, Optional, Tuple
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://musicboxmaniacs.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

INSTRUMENT_LABELS = {
    "K15": "Kikkerland 15-Note (Native)",
    "GI20": "20-Note Diatonic",
    "WG20": "20-Note Diatonic",
    "GI30": "30-Note Chromatic",
    "GI30F": "30-Note Chromatic",
    "FR60": "Full-Range MIDI (60-Note)",
}

_MIDI_CACHE: Dict[str, Tuple[bytes, dict]] = {}


def _run_raw_mbm_query(q: str, limit: int = 24) -> List[dict]:
    resp = requests.get(
        f"{BASE_URL}/explore/",
        params={"q": q},
        headers=HEADERS,
        timeout=8,
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    results: List[dict] = []
    seen_slugs = set()

    for panel in soup.select(".panel"):
        link = panel.select_one('a[href*="/explore/melody/"]')
        if not link:
            continue
        href = link.get("href", "")
        m = re.search(r"/explore/melody/([^/]+)/?", href)
        if not m:
            continue
        slug = m.group(1)
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        title = " ".join(link.stripped_strings) or slug
        tokens = list(panel.stripped_strings)

        box_code = None
        for tok in tokens[1:5]:
            if re.match(r"^[A-Z]{1,4}\d{2}[A-Z]?$", tok):
                box_code = tok
                break

        author = None
        if "by" in tokens:
            idx = tokens.index("by")
            if idx + 1 < len(tokens):
                author = tokens[idx + 1]

        parsed_artist = ""
        if " - " in title:
            parsed_artist = title.split(" - ", 1)[0].strip()

        badge = INSTRUMENT_LABELS.get(box_code, box_code or "Music Box")
        subtitle_parts = ["Music Box Maniacs"]
        if author:
            subtitle_parts.append(f"arr. {author}")

        results.append({
            "id": f"mbm:{slug}",
            "title": title,
            "artist": parsed_artist,
            "subtitle": " · ".join(subtitle_parts),
            "source": "musicboxmaniacs",
            "badge": badge,
            "is_native_k15": (box_code == "K15"),
            "url": f"{BASE_URL}/explore/melody/{slug}/",
        })
        if len(results) >= limit:
            break
    return results


def search_musicboxmaniacs(query: str, artist: str = "", limit: int = 20) -> List[dict]:
    """
    Search Music Box Maniacs with fallback query expansion to overcome MBM's
    literal-substring `ILIKE '%...%'` search limitation.
    """
    q = query.strip()
    art = artist.strip()
    if not q and not art:
        return []

    queries_to_try: List[str] = []
    if q and art:
        queries_to_try.extend([f"{art} - {q}", q, art])
    elif q:
        queries_to_try.append(q)
        words = [w for w in re.split(r"\s+", q) if len(w) >= 3]
        if len(words) >= 2:
            # Also try reversed halves in case user typed "Basket Case Green Day"
            mid = len(words) // 2
            queries_to_try.append(" ".join(words[:mid]))
            queries_to_try.append(" ".join(words[mid:]))
    else:
        queries_to_try.append(art)

    combined: Dict[str, dict] = {}
    for idx, sub_q in enumerate(queries_to_try):
        if not sub_q:
            continue
        hits = _run_raw_mbm_query(sub_q, limit=limit)
        for h in hits:
            combined.setdefault(h["id"], h)
        # If first exact query already yielded plenty of matches, avoid extra round-trips
        if idx == 0 and len(combined) >= 6:
            break

    return list(combined.values())[:limit]


def search_mbm_artist_collection(artist_query: str) -> Optional[dict]:
    """Return a virtual artist collection card if Music Box Maniacs has arrangements for this artist/franchise."""
    q = artist_query.strip()
    if not q:
        return None
    hits = _run_raw_mbm_query(q, limit=30)
    if not hits:
        return None
    return {
        "artist_id": f"mbm_artist:{q}",
        "name": f"{q.title()} (Music Box Arrangements)",
        "source": "musicboxmaniacs",
        "badge": f"{len(hits)}+ Music Box Tracks",
        "url": f"{BASE_URL}/explore/?q={q}",
    }


def fetch_mbm_artist_catalog(artist_id_str: str) -> dict:
    q = artist_id_str.removeprefix("mbm_artist:").strip()
    songs = _run_raw_mbm_query(q, limit=40)
    return {
        "artist_id": f"mbm_artist:{q}",
        "artist_name": f"{q.title()} (Music Box Maniacs)",
        "source": "musicboxmaniacs",
        "song_count": len(songs),
        "songs": songs,
    }


def fetch_musicboxmaniacs_midi(slug: str) -> Tuple[bytes, dict]:
    """Download the MIDI file and metadata for a Music Box Maniacs melody slug."""
    clean_slug = slug.removeprefix("mbm:").strip("/")
    if clean_slug in _MIDI_CACHE:
        return _MIDI_CACHE[clean_slug]

    melody_url = f"{BASE_URL}/explore/melody/{clean_slug}/"
    resp = requests.get(melody_url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    html = resp.text

    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one("h1")
    title = " ".join(h1.stripped_strings) if h1 else clean_slug

    midi_match = re.search(r'https?://[^\s"\'<>]+?\.mid', html, flags=re.IGNORECASE)
    if not midi_match:
        raise ValueError(f"No downloadable MIDI file found on melody page: {melody_url}")

    midi_url = midi_match.group(0)
    mp3_match = re.search(r'https?://[^\s"\'<>]+?\.mp3', html, flags=re.IGNORECASE)
    mp3_url: Optional[str] = mp3_match.group(0) if mp3_match else None

    midi_resp = requests.get(midi_url, headers=HEADERS, timeout=10)
    midi_resp.raise_for_status()
    midi_bytes = midi_resp.content

    meta = {
        "id": f"mbm:{clean_slug}",
        "title": title,
        "source": "musicboxmaniacs",
        "source_url": melody_url,
        "midi_url": midi_url,
        "mp3_url": mp3_url,
    }
    if len(_MIDI_CACHE) > 64:
        _MIDI_CACHE.clear()
    _MIDI_CACHE[clean_slug] = (midi_bytes, meta)
    return midi_bytes, meta
