"""FreeMIDI (freemidi.org) artist catalog browser, song search, and MIDI downloader."""

from concurrent.futures import ThreadPoolExecutor
import re
from typing import Dict, List, Tuple
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://freemidi.org"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

_ARTIST_CATALOG_CACHE: Dict[str, dict] = {}
_MIDI_BYTES_CACHE: Dict[str, Tuple[bytes, dict]] = {}


def _extract_songs_from_html(html: str, artist_name: str = "") -> List[dict]:
    soup = BeautifulSoup(html, "html.parser")
    songs: List[dict] = []
    seen = set()

    for a in soup.select('a[href*="download"]'):
        href = (a.get("href") or "").strip().lstrip("/")
        m = re.match(r"^(download\d*-(\d+)-[a-zA-Z0-9_-]+)$", href)
        if not m:
            continue
        slug, num_id = m.group(1), m.group(2)
        if num_id in seen:
            continue
        title = " ".join(a.stripped_strings).strip()
        if not title or title.lower() in ("download", "add midi"):
            continue
        seen.add(num_id)

        subtitle = f"FreeMIDI · {artist_name}" if artist_name else "FreeMIDI · Multi-Track MIDI"
        songs.append({
            "id": f"freemidi:{slug}",
            "title": title,
            "artist": artist_name,
            "subtitle": subtitle,
            "source": "freemidi",
            "badge": "Pop/Rock MIDI",
            "is_native_k15": False,
            "url": f"{BASE_URL}/{slug}",
        })
    return songs


def search_freemidi_artists(query: str, limit: int = 12) -> List[dict]:
    """Search FreeMIDI for matching artists/bands."""
    q = query.strip()
    if not q:
        return []

    resp = requests.get(
        f"{BASE_URL}/search",
        params={"q": q},
        headers=HEADERS,
        timeout=8,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    artists: List[dict] = []
    seen = set()
    for a in soup.select('a[href*="artist-"]'):
        href = (a.get("href") or "").strip()
        m = re.search(r"(artist-(\d+)-[a-zA-Z0-9_-]+)", href)
        if not m:
            continue
        slug, art_id = m.group(1), m.group(2)
        if "-P-" in slug or art_id in seen:
            continue
        name = " ".join(a.stripped_strings).strip()
        if not name:
            continue
        seen.add(art_id)
        artists.append({
            "artist_id": f"freemidi_artist:{slug}",
            "name": name,
            "source": "freemidi",
            "badge": "Artist Catalog",
            "url": f"{BASE_URL}/{slug}",
        })
        if len(artists) >= limit:
            break
    return artists


def search_freemidi_songs(query: str, limit: int = 14) -> List[dict]:
    """Search FreeMIDI directly by song title."""
    q = query.strip()
    if not q:
        return []

    resp = requests.get(
        f"{BASE_URL}/search",
        params={"q": q},
        headers=HEADERS,
        timeout=8,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    songs: List[dict] = []
    seen = set()
    for row in soup.select(".search-song-container, div"):
        a_song = row.find("a", href=re.compile(r"download\d*-\d+-"))
        if not a_song:
            continue
        href = (a_song.get("href") or "").strip().lstrip("/")
        m = re.match(r"^(download\d*-(\d+)-[a-zA-Z0-9_-]+)$", href)
        if not m:
            continue
        slug, num_id = m.group(1), m.group(2)
        if num_id in seen:
            continue
        title = " ".join(a_song.stripped_strings).strip()
        if not title:
            continue
        seen.add(num_id)

        a_art = row.find("a", href=re.compile(r"artist-\d+-"))
        artist_name = " ".join(a_art.stripped_strings).strip() if a_art else ""
        subtitle = f"FreeMIDI · {artist_name}" if artist_name else "FreeMIDI"

        songs.append({
            "id": f"freemidi:{slug}",
            "title": title,
            "artist": artist_name,
            "subtitle": subtitle,
            "source": "freemidi",
            "badge": "Pop/Rock MIDI",
            "is_native_k15": False,
            "url": f"{BASE_URL}/{slug}",
        })
        if len(songs) >= limit:
            break
    return songs


def fetch_freemidi_artist_catalog(artist_id_str: str, max_pages: int = 6) -> dict:
    """Fetch and cache the full multi-page song catalog for a FreeMIDI artist."""
    slug = artist_id_str.removeprefix("freemidi_artist:").strip("/")
    if slug in _ARTIST_CATALOG_CACHE:
        return _ARTIST_CATALOG_CACHE[slug]

    first_url = f"{BASE_URL}/{slug}"
    resp = requests.get(first_url, headers=HEADERS, timeout=8)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    h1 = soup.select_one("h1")
    artist_name = " ".join(h1.stripped_strings).strip() if h1 else slug.split("-", 2)[-1].replace("-", " ").title()
    artist_name = re.sub(r"\s*(?:Midi)?(?:\s*band\s*info)?\s*$", "", artist_name, flags=re.IGNORECASE).strip()

    # Discover pagination slugs (e.g. artist-508-green-day-P-1 .. -P-5)
    extra_slugs: List[str] = []
    seen_pages = {slug}
    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip().lstrip("/")
        if href.startswith(f"{slug}-P-") and href not in seen_pages:
            seen_pages.add(href)
            extra_slugs.append(href)

    extra_slugs = sorted(extra_slugs)[: max(0, max_pages - 1)]
    all_songs = _extract_songs_from_html(resp.text, artist_name=artist_name)

    if extra_slugs:
        def _fetch_subpage(sub_slug: str) -> List[dict]:
            r = requests.get(f"{BASE_URL}/{sub_slug}", headers=HEADERS, timeout=8)
            r.raise_for_status()
            return _extract_songs_from_html(r.text, artist_name=artist_name)

        with ThreadPoolExecutor(max_workers=4) as pool:
            for page_songs in pool.map(_fetch_subpage, extra_slugs):
                all_songs.extend(page_songs)

    # Deduplicate while preserving catalog order, then sort alphabetically by title
    dedup: Dict[str, dict] = {}
    for s in all_songs:
        dedup.setdefault(s["id"], s)
    catalog_list = sorted(dedup.values(), key=lambda x: x["title"].lower())

    result = {
        "artist_id": f"freemidi_artist:{slug}",
        "artist_name": artist_name,
        "source": "freemidi",
        "song_count": len(catalog_list),
        "songs": catalog_list,
    }
    if len(_ARTIST_CATALOG_CACHE) > 40:
        _ARTIST_CATALOG_CACHE.clear()
    _ARTIST_CATALOG_CACHE[slug] = result
    return result


def fetch_freemidi_midi(song_id_str: str) -> Tuple[bytes, dict]:
    """Download binary MIDI file from FreeMIDI using session cookies + Referer."""
    slug = song_id_str.removeprefix("freemidi:").strip("/")
    if slug in _MIDI_BYTES_CACHE:
        return _MIDI_BYTES_CACHE[slug]

    m = re.match(r"^download\d*-(\d+)-(.+)$", slug)
    if not m:
        raise ValueError(f"Invalid FreeMIDI song slug: {slug}")
    num_id, rest = m.group(1), m.group(2)

    sess = requests.Session()
    sess.headers.update(HEADERS)
    page_url = f"{BASE_URL}/{slug}"
    page_resp = sess.get(page_url, timeout=10)
    page_resp.raise_for_status()

    soup = BeautifulSoup(page_resp.text, "html.parser")
    h1 = soup.select_one("h1")
    title = " ".join(h1.stripped_strings).strip() if h1 else rest.replace("-", " ").title()

    midi_resp = sess.get(
        f"{BASE_URL}/getter-{num_id}",
        headers={"Referer": page_resp.url},
        timeout=10,
    )
    midi_resp.raise_for_status()
    midi_bytes = midi_resp.content

    if not midi_bytes.startswith(b"MThd"):
        # Retry getter once in case session cookie required warm-up
        midi_resp = sess.get(f"{BASE_URL}/getter-{num_id}", headers={"Referer": page_resp.url}, timeout=10)
        midi_bytes = midi_resp.content
    if not midi_bytes.startswith(b"MThd"):
        raise ValueError("FreeMIDI did not return a valid MIDI binary stream.")

    meta = {
        "id": f"freemidi:{slug}",
        "title": title,
        "source": "freemidi",
        "source_url": page_url,
    }
    if len(_MIDI_BYTES_CACHE) > 50:
        _MIDI_BYTES_CACHE.clear()
    _MIDI_BYTES_CACHE[slug] = (midi_bytes, meta)
    return midi_bytes, meta
