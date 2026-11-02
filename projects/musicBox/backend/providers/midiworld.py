"""MidiWorld (midiworld.com) song/artist search and binary MIDI downloader."""

import re
from typing import Dict, List, Tuple
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.midiworld.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

_MW_CACHE: Dict[str, Tuple[bytes, dict]] = {}


def search_midiworld(query: str, limit: int = 14) -> List[dict]:
    """Search MidiWorld for songs or artists (returns entries formatted `Song (Artist)`)."""
    q = query.strip()
    if not q:
        return []

    resp = requests.get(
        f"{BASE_URL}/search/",
        params={"q": q},
        headers=HEADERS,
        timeout=8,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    results: List[dict] = []
    seen = set()

    for li in soup.select("li"):
        a = li.find("a", href=re.compile(r"/download/\d+"))
        if not a:
            continue
        href = a.get("href", "")
        m = re.search(r"/download/(\d+)", href)
        if not m:
            continue
        dl_id = m.group(1)
        if dl_id in seen:
            continue
        seen.add(dl_id)

        raw_text = " ".join(li.stripped_strings)
        # Format is typically: "Basket Case (Green Day) - download Please install flash..."
        raw_head = raw_text.split(" - download")[0].strip()
        art_match = re.match(r"^(.+?)\s*\(([^()]+)\)\s*$", raw_head)
        if art_match:
            song_title = art_match.group(1).strip()
            artist_name = art_match.group(2).strip()
        else:
            song_title = raw_head or f"Track {dl_id}"
            artist_name = ""

        subtitle = f"MidiWorld · {artist_name}" if artist_name else "MidiWorld"
        results.append({
            "id": f"midiworld:{dl_id}:{re.sub(r'[^a-zA-Z0-9_-]+', '_', song_title)[:36]}",
            "title": song_title,
            "artist": artist_name,
            "subtitle": subtitle,
            "source": "midiworld",
            "badge": "Classic MIDI",
            "is_native_k15": False,
            "url": f"{BASE_URL}/download/{dl_id}",
        })
        if len(results) >= limit:
            break
    return results


def fetch_midiworld_midi(song_id_str: str) -> Tuple[bytes, dict]:
    """Download binary .mid file from MidiWorld."""
    parts = song_id_str.split(":", 2)
    if len(parts) < 2:
        raise ValueError(f"Invalid MidiWorld ID: {song_id_str}")
    dl_id = parts[1]
    label_hint = parts[2].replace("_", " ") if len(parts) > 2 else f"MidiWorld {dl_id}"

    if dl_id in _MW_CACHE:
        return _MW_CACHE[dl_id]

    dl_url = f"{BASE_URL}/download/{dl_id}"
    resp = requests.get(dl_url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    midi_bytes = resp.content
    if not midi_bytes.startswith(b"MThd"):
        raise ValueError("MidiWorld response was not a valid MIDI file.")

    meta = {
        "id": song_id_str,
        "title": label_hint,
        "source": "midiworld",
        "source_url": dl_url,
    }
    if len(_MW_CACHE) > 50:
        _MW_CACHE.clear()
    _MW_CACHE[dl_id] = (midi_bytes, meta)
    return midi_bytes, meta
