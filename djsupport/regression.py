"""Local matcher regression knowledge for live accuracy checks."""

from pathlib import Path

from djsupport.cache import MatchCache


def load_local_regressions(path: str | Path) -> list[dict]:
    """Load user-approved regression cases from local matching knowledge."""
    cache = MatchCache(str(path))
    cache.load()
    cases = []
    required = ("source_artist", "source_title", "spotify_uri")
    for row_number, regression in enumerate(cache.local_regressions, start=1):
        if not all(regression.get(field) for field in required):
            raise ValueError(
                f"Invalid local regression row {row_number}: "
                "source artist, source title, and Spotify URI are required"
            )
        cases.append({
            "artist": regression["source_artist"],
            "song": regression["source_title"],
            "expected_uri": regression["spotify_uri"],
            "duration": int(regression.get("source_duration", 0) or 0),
        })
    return cases
