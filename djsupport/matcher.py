"""Fuzzy matching between Rekordbox tracks and Spotify search results."""

import re

from rapidfuzz import fuzz

from djsupport.rekordbox import Track
from djsupport.spotify import search_track


def _normalize(text: str) -> str:
    """Lowercase, strip whitespace, and remove common noise."""
    text = text.lower().strip()
    # Remove "feat." / "ft." variations
    text = re.sub(r"\b(feat\.?|ft\.?)\b", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_mix_info(title: str) -> str:
    """Remove parenthetical remix/mix info from a title.

    e.g. 'Vultora (Original Mix)' -> 'Vultora'
    """
    return re.sub(r"\s*\(.*?(mix|remix|edit|version|dub)\)", "", title, flags=re.IGNORECASE).strip()


def _score_result(track: Track, result: dict) -> float:
    """Score a Spotify result against a Rekordbox track (0-100)."""
    artist_score = fuzz.token_sort_ratio(
        _normalize(track.artist), _normalize(result["artist"])
    )
    title_score = fuzz.token_sort_ratio(
        _normalize(track.name), _normalize(result["name"])
    )
    # Weight title slightly more since artist names vary in format
    return artist_score * 0.4 + title_score * 0.6


def match_track(sp, track: Track, threshold: int = 80) -> dict | None:
    """Try to find a Spotify match for a Rekordbox track.

    Returns the best matching Spotify result dict (with uri, name, artist, album)
    or None if no match meets the threshold.
    """
    # Strategy 1: search with artist + title
    results = search_track(sp, track.artist, track.name)

    if not results:
        # Strategy 2: strip mix info from title
        stripped = _strip_mix_info(track.name)
        if stripped != track.name:
            results = search_track(sp, track.artist, stripped)

    if not results and track.remixer:
        # Strategy 3: include remixer as part of artist search
        results = search_track(sp, f"{track.artist} {track.remixer}", track.name)

    if not results:
        return None

    # Score and pick the best result
    scored = [(r, _score_result(track, r)) for r in results]
    scored.sort(key=lambda x: x[1], reverse=True)

    best, best_score = scored[0]
    if best_score >= threshold:
        return {**best, "score": best_score}

    return None
