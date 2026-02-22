"""Spotify API wrapper using spotipy."""

import spotipy
from spotipy.oauth2 import SpotifyOAuth


SCOPES = "playlist-modify-public playlist-modify-private"


def get_client() -> spotipy.Spotify:
    """Create an authenticated Spotify client.

    Expects SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, and
    SPOTIPY_REDIRECT_URI to be set in the environment (via .env).
    """
    auth_manager = SpotifyOAuth(scope=SCOPES)
    return spotipy.Spotify(auth_manager=auth_manager)


def search_track(
    sp: spotipy.Spotify, artist: str, title: str, album: str | None = None
) -> list[dict]:
    """Search Spotify for a track. Returns list of result dicts with uri, name, artist, album."""
    query = f"artist:{artist} track:{title}"
    if album:
        query += f" album:{album}"

    results = sp.search(q=query, type="track", limit=5)
    items = results.get("tracks", {}).get("items", [])

    return [
        {
            "uri": item["uri"],
            "name": item["name"],
            "artist": ", ".join(a["name"] for a in item["artists"]),
            "album": item["album"]["name"],
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


def create_or_update_playlist(
    sp: spotipy.Spotify,
    name: str,
    track_uris: list[str],
    existing_playlists: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Create a playlist or replace its tracks if it already exists.

    Returns (playlist_id, action) where action is "created" or "updated".
    """
    if existing_playlists is None:
        existing_playlists = get_user_playlists(sp)

    user_id = sp.current_user()["id"]

    if name in existing_playlists:
        playlist_id = existing_playlists[name]
        action = "updated"
    else:
        result = sp.user_playlist_create(user_id, name, public=False)
        playlist_id = result["id"]
        action = "created"

    # Replace all tracks (Spotify API accepts max 100 per call)
    if track_uris:
        sp.playlist_replace_items(playlist_id, track_uris[:100])
        for i in range(100, len(track_uris), 100):
            sp.playlist_add_items(playlist_id, track_uris[i : i + 100])
    else:
        sp.playlist_replace_items(playlist_id, [])

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
) -> tuple[str, str, dict]:
    """Update a playlist incrementally, only adding/removing the diff.

    Returns (playlist_id, action, diff_info) where diff_info has
    added/removed/unchanged counts.
    """
    if existing_playlists is None:
        existing_playlists = get_user_playlists(sp)

    if name not in existing_playlists:
        pid, action = create_or_update_playlist(sp, name, desired_uris, existing_playlists)
        return pid, action, {"added": len(desired_uris), "removed": 0, "unchanged": 0}

    playlist_id = existing_playlists[name]
    current_uris = get_playlist_tracks(sp, playlist_id)

    current_set = set(current_uris)
    desired_set = set(desired_uris)

    to_remove = current_set - desired_set
    to_add = desired_set - current_set
    unchanged = current_set & desired_set

    if not to_remove and not to_add:
        return playlist_id, "unchanged", {
            "added": 0, "removed": 0, "unchanged": len(unchanged),
        }

    # If more than 50% is changing, fall back to full replace
    if len(to_remove) + len(to_add) > len(desired_uris) * 0.5:
        sp.playlist_replace_items(playlist_id, desired_uris[:100])
        for i in range(100, len(desired_uris), 100):
            sp.playlist_add_items(playlist_id, desired_uris[i : i + 100])
        return playlist_id, "replaced", {
            "added": len(to_add), "removed": len(to_remove),
            "unchanged": len(unchanged),
        }

    if to_remove:
        remove_items = [{"uri": uri} for uri in to_remove]
        for i in range(0, len(remove_items), 100):
            sp.playlist_remove_all_occurrences_of_items(
                playlist_id, remove_items[i : i + 100],
            )

    if to_add:
        add_list = [uri for uri in desired_uris if uri in to_add]
        for i in range(0, len(add_list), 100):
            sp.playlist_add_items(playlist_id, add_list[i : i + 100])

    return playlist_id, "updated", {
        "added": len(to_add), "removed": len(to_remove),
        "unchanged": len(unchanged),
    }
