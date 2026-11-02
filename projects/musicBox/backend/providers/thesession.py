"""The Session (thesession.org) public JSON API provider for traditional/folk ABC tunes."""

from typing import List, Dict, Tuple
import requests

BASE_URL = "https://thesession.org"
HEADERS = {"User-Agent": "KikkerlandMusicBoxStudio/1.0"}

_ABC_CACHE: Dict[str, Tuple[str, dict]] = {}


def search_thesession(query: str, limit: int = 10) -> List[dict]:
    """Search The Session tune database via its public JSON API."""
    q = query.strip()
    if not q:
        return []

    resp = requests.get(
        f"{BASE_URL}/tunes/search",
        params={"q": q, "format": "json", "perpage": limit},
        headers=HEADERS,
        timeout=8,
    )
    resp.raise_for_status()
    data = resp.json()

    results: List[dict] = []
    for tune in data.get("tunes", [])[:limit]:
        tune_id = tune.get("id")
        name = tune.get("name", f"Tune {tune_id}")
        tune_type = (tune.get("type") or "folk").capitalize()
        results.append({
            "id": f"session:{tune_id}",
            "title": name,
            "subtitle": f"The Session · {tune_type}",
            "source": "thesession",
            "badge": f"{tune_type} (ABC)",
            "is_native_k15": False,
            "url": tune.get("url") or f"{BASE_URL}/tunes/{tune_id}",
        })
    return results


def fetch_thesession_abc(tune_id_str: str) -> Tuple[str, dict]:
    """Fetch full ABC notation for a tune ID on The Session."""
    clean_id = tune_id_str.removeprefix("session:").strip()
    if clean_id in _ABC_CACHE:
        return _ABC_CACHE[clean_id]

    url = f"{BASE_URL}/tunes/{clean_id}"
    resp = requests.get(url, params={"format": "json"}, headers=HEADERS, timeout=8)
    resp.raise_for_status()
    data = resp.json()

    settings = data.get("settings") or []
    if not settings:
        raise ValueError(f"No ABC settings found for tune {clean_id}")

    first = settings[0]
    title = data.get("name", f"Tune {clean_id}")
    tune_type = data.get("type", "reel")
    key_raw = first.get("key", "Cmajor")
    abc_body = first.get("abc", "")

    # Map The Session key names (e.g. "Gmajor", "Eminor", "Adorian", "Dmixolydian") to ABC K: header
    key_header = (
        key_raw.replace("major", "maj")
        .replace("minor", "min")
        .replace("dorian", "dor")
        .replace("mixolydian", "mix")
    )
    meter = "6/8" if tune_type in ("jig", "slip jig", "slide") else ("3/4" if tune_type == "waltz" else "4/4")

    full_abc = (
        f"X:1\n"
        f"T:{title}\n"
        f"M:{meter}\n"
        f"L:1/8\n"
        f"Q:1/4=120\n"
        f"K:{key_header}\n"
        f"{abc_body}\n"
    )
    meta = {
        "id": f"session:{clean_id}",
        "title": title,
        "source": "thesession",
        "source_url": f"{BASE_URL}/tunes/{clean_id}",
        "declared_key": key_raw,
    }
    if len(_ABC_CACHE) > 64:
        _ABC_CACHE.clear()
    _ABC_CACHE[clean_id] = (full_abc, meta)
    return full_abc, meta
