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
    sp: spotipy.Spotify,
    artist: str,
    title: str,
    album: str | None = None,
    use_field_filters: bool = True,
) -> list[dict]:
    """Search Spotify for a track. Returns list of result dicts with uri, name, artist, album."""
    if use_field_filters:
        query = f"artist:{artist} track:{title}"
        if album:
            query += f" album:{album}"
    else:
        query = f"{artist} {title}"

    results = sp.search(q=query, type="track", limit=10)
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
