"""Smart relevance ranking and query tokenization for song + artist search."""

import re
from typing import List, Tuple

_STOP_NOISE = {"the", "a", "an", "by", "ost", "version", "ver", "intro", "midi"}


def normalize_text(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokenize(s: str) -> List[str]:
    norm = normalize_text(s)
    return [tok for tok in norm.split(" ") if tok]


def split_compound_title(raw_title: str, explicit_artist: str = "") -> Tuple[str, str]:
    """
    Extract `(song_part, artist_part)` when community titles look like
    `Green Day - Basket Case` or `Basket Case (Green Day)`.
    """
    t = (raw_title or "").strip()
    art = (explicit_artist or "").strip()

    if not art:
        paren = re.match(r"^(.+?)\s*\(([^()]+)\)\s*$", t)
        if paren:
            cand_title, cand_art = paren.group(1).strip(), paren.group(2).strip()
            if cand_art.lower() not in ("intro", "chorus", "short", "full", "high pitched", "ost"):
                return cand_title, cand_art

    if " - " in t:
        lhs, rhs = t.split(" - ", 1)
        return rhs.strip(), (art or lhs.strip())

    return t, art


def score_search_item(item: dict, song_query: str, artist_query: str = "") -> float:
    """
    Compute a relevance score that handles generic 1-word titles (like 'Holiday')
    and compound queries ('Holiday Green Day') cleanly without letting partial
    substring matches or unrelated K15 badges jump ahead of exact hits.
    """
    raw_title = item.get("title", "")
    raw_artist = item.get("artist", "") or ""
    subtitle = item.get("subtitle", "") or ""

    parsed_song, parsed_artist = split_compound_title(raw_title, raw_artist)
    norm_full_title = normalize_text(raw_title)
    norm_song = normalize_text(parsed_song)
    norm_artist = normalize_text(parsed_artist or subtitle)
    combined_doc = f"{norm_song} {norm_artist} {norm_full_title}".strip()
    doc_tokens = set(tokenize(combined_doc))
    song_doc_tokens = tokenize(norm_song)

    norm_sq = normalize_text(song_query)
    norm_aq = normalize_text(artist_query)
    sq_tokens = tokenize(norm_sq)
    aq_tokens = tokenize(norm_aq)
    all_q_tokens = sq_tokens + [t for t in aq_tokens if t not in sq_tokens]

    if not all_q_tokens:
        return 100.0 if item.get("is_native_k15") else 50.0

    # Token coverage across combined title + artist
    matched_all = sum(1 for t in all_q_tokens if t in doc_tokens)
    coverage = matched_all / len(all_q_tokens)

    # Also check prefix matches (e.g. typing "holid")
    if coverage < 1.0:
        prefix_hits = sum(
            1 for qt in all_q_tokens if any(dt.startswith(qt) for dt in doc_tokens)
        )
        coverage = max(coverage, (prefix_hits / len(all_q_tokens)) * 0.85)

    score = coverage * 300.0
    if coverage >= 0.99:
        # Prefer tighter exact matches ("Holiday" + "Green Day" over "Deadbeat Holiday" + "Green Day")
        extra_doc_tokens = max(0, len(song_doc_tokens) + len(tokenize(parsed_artist)) - len(all_q_tokens))
        score += max(0.0, 120.0 - extra_doc_tokens * 35.0)

    # Exact & tight title matching
    if norm_sq:
        if norm_song == norm_sq or norm_full_title == norm_sq:
            score += 650.0
        elif norm_full_title == f"{norm_aq} {norm_sq}".strip() or norm_full_title == f"{norm_sq} {norm_aq}".strip():
            score += 620.0
        elif sq_tokens and all(t in song_doc_tokens for t in sq_tokens):
            # Penalize extra filler words so "Holiday" beats "Deadbeat Holiday" or "Happy Holiday Intro"
            extra_words = max(0, len(song_doc_tokens) - len(sq_tokens))
            score += max(120.0, 420.0 - extra_words * 55.0)
        elif norm_sq in norm_song:
            score += 140.0

    # Explicit artist matching
    if norm_aq:
        if norm_aq == normalize_text(parsed_artist):
            score += 480.0
        elif aq_tokens and all(t in tokenize(norm_artist) for t in aq_tokens):
            score += 380.0
        elif aq_tokens and any(t in doc_tokens for t in aq_tokens):
            score += 90.0
        else:
            # Explicit artist requested, but result doesn't match artist -> strong penalty
            score -= 450.0

    # Native Kikkerland 15-note arrangement tie-breaker ONLY when relevance coverage is strong!
    if item.get("is_native_k15") and coverage >= 0.75:
        score += 55.0

    # Slight preference for clean music-box / curated sources over raw multi-track when tied
    src = item.get("source", "")
    if src == "musicboxmaniacs" and coverage >= 0.75:
        score += 18.0
    elif src == "freemidi" and coverage >= 0.75:
        score += 14.0

    return round(score, 2)


def rank_search_results(
    items: List[dict],
    song_query: str,
    artist_query: str = "",
    min_score: float = 40.0,
) -> List[dict]:
    """Deduplicate, score, filter out completely irrelevant hits, and sort descending."""
    seen_ids = set()
    scored = []
    has_query = bool(normalize_text(song_query) or normalize_text(artist_query))

    for it in items:
        iid = it.get("id")
        if not iid or iid in seen_ids:
            continue
        seen_ids.add(iid)
        s = score_search_item(it, song_query, artist_query)
        if has_query and s < min_score:
            continue
        enriched = {**it, "relevance_score": s}
        scored.append(enriched)

    scored.sort(key=lambda x: x["relevance_score"], reverse=True)
    return scored
