"""Spotify API wrapper using spotipy."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from djsupport.state import PlaylistState, PlaylistStateManager


SCOPES = "playlist-modify-public playlist-modify-private"

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


def get_user_playlists(sp: spotipy.Spotify) -> dict[str, str]:
    """Get all playlists owned by the current user. Returns {name: playlist_id}."""
    user_id = sp.current_user()["id"]
    playlists: dict[str, str] = {}
    offset = 0

    while True:
        batch = sp.current_user_playlists(limit=50, offset=offset)
        for item in batch["items"]:
            if item["owner"]["id"] == user_id:
                playlists[item["name"]] = item["id"]
        if batch["next"] is None:
            break
        offset += 50

    return playlists


def format_playlist_name(name: str, prefix: str | None = None) -> str:
    """Return prefixed playlist name, e.g. 'djsupport / My Playlist'."""
    if prefix:
        return f"{prefix} / {name}"
    return name


def resolve_playlist_id(
    sp: spotipy.Spotify,
    name: str,
    prefix: str | None,
    existing_playlists: dict[str, str],
    state_manager: PlaylistStateManager | None = None,
) -> tuple[str | None, str]:
    """Look up a Spotify playlist ID for a Rekordbox playlist.

    Returns (playlist_id | None, found_by) where found_by is one of:
    "state" or "none".  Only state-tracked playlists are valid update
    targets — name-based matching is intentionally disabled for safety.
    """
    # 1. Check state for stored ID
    if state_manager is not None:
        state = state_manager.get(name)
        if state is not None:
            try:
                sp.playlist(state.spotify_id, fields="id")
                return state.spotify_id, "state"
            except spotipy.SpotifyException:
                pass  # playlist deleted, fall through

    return None, "none"


def _rename_if_needed(sp: spotipy.Spotify, playlist_id: str, expected_name: str) -> None:
    """Rename a Spotify playlist if its current name differs from expected_name."""
    current = sp.playlist(playlist_id, fields="name")
    if current["name"] != expected_name:
        sp.playlist_change_details(playlist_id, name=expected_name)


def create_or_update_playlist(
    sp: spotipy.Spotify,
    name: str,
    track_uris: list[str],
    existing_playlists: dict[str, str] | None = None,
    prefix: str | None = None,
    state_manager: PlaylistStateManager | None = None,
    source_path: str | None = None,
    source_type: str = "rekordbox",
) -> tuple[str, str]:
    """Create a playlist or replace its tracks if it already exists.

    Returns (playlist_id, action) where action is "created" or "updated".
    """
    if existing_playlists is None:
        existing_playlists = get_user_playlists(sp)

    user_id = sp.current_user()["id"]

    playlist_id, found_by = resolve_playlist_id(
        sp, name, prefix, existing_playlists, state_manager,
    )

    if playlist_id is not None:
        action = "updated"
        # Rename if the Spotify name doesn't match the expected formatted name
        formatted = format_playlist_name(name, prefix)
        _rename_if_needed(sp, playlist_id, formatted)
    else:
        display_name = format_playlist_name(name, prefix)
        result = sp.user_playlist_create(user_id, display_name, public=False)
        playlist_id = result["id"]
        action = "created"

    # Replace all tracks (Spotify API accepts max 100 per call)
    if track_uris:
        sp.playlist_replace_items(playlist_id, track_uris[:100])
        for i in range(100, len(track_uris), 100):
            sp.playlist_add_items(playlist_id, track_uris[i : i + 100])
    else:
        sp.playlist_replace_items(playlist_id, [])

    if state_manager is not None:
        state_manager.set(name, PlaylistState(
            spotify_id=playlist_id,
            spotify_name=format_playlist_name(name, prefix),
            source_path=source_path or name,
            last_synced=datetime.now().isoformat(),
            prefix_used=prefix,
            source_type=source_type,
        ))

    return playlist_id, action


def get_playlist_tracks(sp: spotipy.Spotify, playlist_id: str) -> list[str]:
    """Get all track URIs currently in a playlist."""
    uris: list[str] = []
    offset = 0
    while True:
        batch = sp.playlist_tracks(
            playlist_id, offset=offset, limit=100,
            fields="items.track.uri,next",
        )
        for item in batch["items"]:
            if item["track"]:
                uris.append(item["track"]["uri"])
        if batch["next"] is None:
            break
        offset += 100
    return uris


def incremental_update_playlist(
    sp: spotipy.Spotify,
    name: str,
    desired_uris: list[str],
    existing_playlists: dict[str, str] | None = None,
    prefix: str | None = None,
    state_manager: PlaylistStateManager | None = None,
    source_path: str | None = None,
    source_type: str = "rekordbox",
) -> tuple[str, str, dict]:
    """Update a playlist incrementally, only adding/removing the diff.

    Returns (playlist_id, action, diff_info) where diff_info has
    added/removed/unchanged counts.
    """
    if existing_playlists is None:
        existing_playlists = get_user_playlists(sp)

    playlist_id, found_by = resolve_playlist_id(
        sp, name, prefix, existing_playlists, state_manager,
    )

    if playlist_id is None:
        pid, action = create_or_update_playlist(
            sp, name, desired_uris, existing_playlists,
            prefix=prefix, state_manager=state_manager,
            source_path=source_path, source_type=source_type,
        )
        return pid, action, {"added": len(desired_uris), "removed": 0, "unchanged": 0}

    # Rename if the Spotify name doesn't match the expected formatted name
    formatted = format_playlist_name(name, prefix)
    _rename_if_needed(sp, playlist_id, formatted)

    current_uris = get_playlist_tracks(sp, playlist_id)

    current_set = set(current_uris)
    desired_set = set(desired_uris)

    to_remove = current_set - desired_set
    to_add = desired_set - current_set
    unchanged = current_set & desired_set

    def _save_state(pid: str, action: str) -> None:
        if state_manager is not None:
            state_manager.set(name, PlaylistState(
                spotify_id=pid,
                spotify_name=format_playlist_name(name, prefix),
                source_path=source_path or name,
                last_synced=datetime.now().isoformat(),
                prefix_used=prefix,
                source_type=source_type,
            ))

    if not to_remove and not to_add:
        _save_state(playlist_id, "unchanged")
        return playlist_id, "unchanged", {
            "added": 0, "removed": 0, "unchanged": len(unchanged),
        }

    # If more than 50% is changing, fall back to full replace
    if len(to_remove) + len(to_add) > len(desired_uris) * 0.5:
        sp.playlist_replace_items(playlist_id, desired_uris[:100])
        for i in range(100, len(desired_uris), 100):
            sp.playlist_add_items(playlist_id, desired_uris[i : i + 100])
        _save_state(playlist_id, "replaced")
        return playlist_id, "replaced", {
            "added": len(to_add), "removed": len(to_remove),
            "unchanged": len(unchanged),
        }

    if to_remove:
        remove_items = list(to_remove)
        for i in range(0, len(remove_items), 100):
            sp.playlist_remove_all_occurrences_of_items(
                playlist_id, remove_items[i : i + 100],
            )

    if to_add:
        add_list = [uri for uri in desired_uris if uri in to_add]
        for i in range(0, len(add_list), 100):
            sp.playlist_add_items(playlist_id, add_list[i : i + 100])

    _save_state(playlist_id, "updated")
    return playlist_id, "updated", {
        "added": len(to_add), "removed": len(to_remove),
        "unchanged": len(unchanged),
    }
