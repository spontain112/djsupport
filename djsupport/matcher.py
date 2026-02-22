"""Fuzzy matching between Rekordbox tracks and Spotify search results."""

import re

from rapidfuzz import fuzz

from djsupport.rekordbox import Track
from djsupport.spotify import search_track


def _normalize(text: str) -> str:
    """Lowercase, strip whitespace, and remove common noise."""
    text = text.lower().strip()
    # Remove country tags like (IL), (UA), (UK)
    text = re.sub(r"\s*\([A-Z]{2,3}\)", "", text, flags=re.IGNORECASE)
    # Remove bracket tags like [Permanent Vacation], [Label Name]
    text = re.sub(r"\s*\[.*?\]", "", text)
    # Replace "x" as artist separator with comma
    text = re.sub(r"\s+x\s+", ", ", text)
    # Remove "feat." / "ft." and everything after within the string
    text = re.sub(r"\b(feat\.?|ft\.?)\s+.*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_mix_info(title: str) -> str:
    """Remove parenthetical remix/mix info and bracket tags from a title.

    e.g. 'Vultora (Original Mix)' -> 'Vultora'
         'Today [Permanent Vacation]' -> 'Today'
    """
    title = re.sub(r"\s*\(.*?(mix|remix|edit|version|dub)\)", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*\[.*?\]", "", title)
    return title.strip()


def _score_result(track: Track, result: dict) -> float:
    """Score a Spotify result against a Rekordbox track (0-100)."""
    artist_score = fuzz.token_sort_ratio(
        _normalize(track.artist), _normalize(result["artist"])
    )
    # Score title both raw and with mix info stripped, take the better one
    norm_title = _normalize(track.name)
    norm_result = _normalize(result["name"])
    title_score = fuzz.token_sort_ratio(norm_title, norm_result)
    stripped_score = fuzz.token_sort_ratio(
        _normalize(_strip_mix_info(track.name)),
        _normalize(_strip_mix_info(result["name"])),
    )
    title_score = max(title_score, stripped_score)
    # Weight title slightly more since artist names vary in format
    return artist_score * 0.4 + title_score * 0.6


def match_track(sp, track: Track, threshold: int = 80) -> dict | None:
    """Try to find a Spotify match for a Rekordbox track.

    Runs all search strategies and picks the best result across all of them.
    Returns the best matching Spotify result dict (with uri, name, artist, album)
    or None if no match meets the threshold.
    """
    all_results: list[dict] = []

    # Strategy 1: search with artist + title
    all_results.extend(search_track(sp, track.artist, track.name))

    # Strategy 2: strip mix info from title
    stripped = _strip_mix_info(track.name)
    if stripped != track.name:
        all_results.extend(search_track(sp, track.artist, stripped))

    # Strategy 3: include remixer as part of artist search
    if track.remixer:
        all_results.extend(search_track(sp, f"{track.artist} {track.remixer}", track.name))

    # Strategy 4: clean artist (strips country tags) + stripped title
    clean_artist = _normalize(track.artist)
    clean_title = _normalize(stripped)
    if clean_artist != track.artist.lower().strip() or clean_title != stripped.lower().strip():
        all_results.extend(search_track(sp, clean_artist, clean_title))

    if not all_results:
        return None

    # Dedupe by URI, score all, pick the best
    seen: set[str] = set()
    unique: list[dict] = []
    for r in all_results:
        if r["uri"] not in seen:
            seen.add(r["uri"])
            unique.append(r)

    scored = [(r, _score_result(track, r)) for r in unique]
    scored.sort(key=lambda x: x[1], reverse=True)

    best, best_score = scored[0]
    if best_score >= threshold:
        return {**best, "score": best_score}

    return None
