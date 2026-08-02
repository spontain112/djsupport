"""Spotify API wrapper using spotipy."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import spotipy
from spotipy.oauth2 import SpotifyOAuth

SCOPES = "playlist-read-private playlist-modify-public playlist-modify-private"

MAX_RATE_LIMIT_WAIT = 60  # seconds — abort if Spotify asks us to wait longer


class RateLimitError(Exception):
    """Raised when Spotify rate limit wait exceeds MAX_RATE_LIMIT_WAIT."""

    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        minutes = retry_after // 60
        hours = retry_after // 3600
        if hours > 0:
            wait_str = f"{hours}h {(retry_after % 3600) // 60}m"
        elif minutes > 0:
            wait_str = f"{minutes}m {retry_after % 60}s"
        else:
            wait_str = f"{retry_after}s"
        super().__init__(
            f"Spotify rate limit exceeded. Retry after {wait_str}. "
            f"Aborting — resume later to continue where you left off."
        )


class QuotaExceededError(Exception):
    """Spotify account quota is exhausted; retrying cannot make progress."""


class SpotifyCapabilityError(Exception):
    """A required Spotify permission or account capability is unavailable."""

    def __init__(self, capability: str):
        self.capability = capability
        super().__init__(
            f"Spotify capability unavailable: {capability}. Re-consent with "
            "playlist-read-private; DJ Support will not broaden permissions."
        )


def get_client() -> spotipy.Spotify:
    """Create an authenticated Spotify client.

    Expects SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, and
    SPOTIPY_REDIRECT_URI to be set in the environment (via .env).
    """
    auth_manager = SpotifyOAuth(scope=SCOPES)
    return spotipy.Spotify(auth_manager=auth_manager)


def _parse_retry_after(exc: spotipy.SpotifyException) -> int:
    """Extract Retry-After seconds from a 429 response, with defensive parsing."""
    try:
        raw = exc.headers.get("Retry-After", 0) if exc.headers else 0
        return max(int(raw), 1)  # floor at 1s to avoid busy-loop
    except (ValueError, TypeError):
        return 1


def _api_call_with_rate_limit(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Execute a Spotify API call, handling rate limits gracefully.

    Short waits (<=MAX_RATE_LIMIT_WAIT) are retried automatically.
    Long waits raise RateLimitError so the CLI can save cache and exit.
    """
    try:
        return func(*args, **kwargs)
    except spotipy.SpotifyException as e:
        if e.http_status == 429:
            if "QUOTA_EXCEEDED" in str(e).upper():
                raise QuotaExceededError(
                    "Spotify quota exhausted; Transfer checkpointed and paused"
                ) from e
            retry_after = _parse_retry_after(e)
            if retry_after <= MAX_RATE_LIMIT_WAIT:
                time.sleep(retry_after)
                try:
                    return func(*args, **kwargs)
                except spotipy.SpotifyException as e2:
                    if e2.http_status == 429:
                        raise RateLimitError(_parse_retry_after(e2)) from e2
                    raise
            raise RateLimitError(retry_after) from e
        if e.http_status == 403:
            raise SpotifyCapabilityError("playlist-read-private") from e
        raise


def search_track(
    sp: spotipy.Spotify, artist: str, title: str, album: str | None = None,
    plain: bool = False,
) -> list[dict]:
    """Search Spotify for a track. Returns list of result dicts with uri, name, artist, album.

    If plain=True, search without field prefixes (more forgiving of misspellings).
    """
    if plain:
        query = f"{artist} {title}"
    else:
        query = f"artist:{artist} track:{title}"
    if album:
        query += f" album:{album}"

    results = _api_call_with_rate_limit(sp.search, q=query, type="track", limit=5)
    items = results.get("tracks", {}).get("items", [])

    return [
        {
            "uri": item["uri"],
            "name": item["name"],
            "artist": ", ".join(a["name"] for a in item["artists"]),
            "album": item["album"]["name"],
            "duration_ms": item.get("duration_ms", 0),
        }
        for item in items
    ]
