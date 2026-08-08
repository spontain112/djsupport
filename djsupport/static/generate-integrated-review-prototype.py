"""PROTOTYPE: render selected private Transfer records into a local HTML review.

The output is private, read-only, and intentionally outside the repository.
No Spotify or Beatport calls are made by this generator.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


TEMPLATE = Path(__file__).with_name("integrated-review-prototype.html")
MARKER = "/*__REVIEW_CASES__*/"
PROJECT_ROOT = Path(__file__).parents[2]


def _walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _case_for(nodes: list[dict], track_id: str) -> dict:
    source = next(
        (node for node in nodes if node.get("track_id") == track_id), None,
    )
    proposals = [
        node for node in nodes if node.get("source_track_id") == track_id
    ]
    if source is None or not proposals:
        raise ValueError(f"Selected record not found: {track_id}")

    proposal = max(
        proposals,
        key=lambda node: sum(
            node.get(key) not in (None, "", 0)
            for key in (
                "spotify_uri", "spotify_name", "spotify_artist",
                "source_duration", "score",
            )
        ),
    )
    duration = int(source.get("duration") or proposal.get("source_duration") or 0)
    spotify_duration = int(
        (proposal.get("spotify_duration_ms") or proposal.get("duration_ms") or 0)
        / 1000
    )
    # The retained proposal often omits its duration. Equal source/proposal
    # duration is intentionally not inferred; the UI renders Unknown instead.
    return {
        "id": track_id,
        "sourceArtist": source.get("artist") or proposal.get("source_artist") or "Unknown",
        "sourceTitle": source.get("name") or proposal.get("source_title") or "Unknown",
        "sourceDuration": duration,
        "sourceRelease": source.get("album") or "Unknown",
        "sourceLabel": source.get("label") or "Unknown",
        "spotifyArtist": proposal.get("spotify_artist") or "Unknown",
        "spotifyTitle": proposal.get("spotify_name") or "Unknown",
        "spotifyDuration": spotify_duration,
        "spotifyRelease": proposal.get("spotify_album") or "Unknown",
        "spotifyUri": proposal.get("spotify_uri") or "",
        "score": float(proposal.get("score") or 0),
        "version": source.get("remixer") or "No version shown",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a private, read-only integrated review prototype.",
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--track-id", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--authorize-spotify-read",
        action="store_true",
        help="Make one bounded Spotify metadata call for selected proposals.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Optional private dotenv file used only for Spotify authentication.",
    )
    parser.add_argument(
        "--spotify-cache",
        type=Path,
        help="Optional existing private Spotipy token cache.",
    )
    args = parser.parse_args()

    output = args.output.resolve()
    if output.is_relative_to(PROJECT_ROOT.resolve()):
        raise ValueError(
            "Private prototype output must remain outside the repository",
        )

    nodes = list(_walk(json.loads(args.manifest.read_text(encoding="utf-8"))))
    cases = [_case_for(nodes, track_id) for track_id in args.track_id]
    external_calls = 0
    if args.authorize_spotify_read:
        sys.path.insert(0, str(PROJECT_ROOT))
        if args.env_file is not None:
            from dotenv import load_dotenv

            load_dotenv(args.env_file)
        if args.spotify_cache is not None:
            os.environ["SPOTIPY_CACHE_PATH"] = str(args.spotify_cache)
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth

        from djsupport.spotify import SCOPES

        spotify_ids = [
            case["spotifyUri"].split(":")[-1]
            for case in cases
            if case["spotifyUri"]
        ]
        auth = SpotifyOAuth(
            scope=SCOPES,
            cache_path=(str(args.spotify_cache) if args.spotify_cache else None),
            open_browser=False,
        )
        response = spotipy.Spotify(auth_manager=auth).tracks(spotify_ids)
        tracks = {
            track["uri"]: track
            for track in response.get("tracks", [])
            if track is not None
        }
        for case in cases:
            track = tracks.get(case["spotifyUri"])
            if track is None:
                continue
            case["spotifyDuration"] = int(track.get("duration_ms", 0) / 1000)
            case["spotifyRelease"] = track.get("album", {}).get("name") or "Unknown"
        external_calls = 1

    encoded = json.dumps(cases, ensure_ascii=True).replace("<", "\\u003c")
    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("classification: concept", "classification: internal", 1)
    html = html.replace(f"{MARKER}null", encoded)
    output.write_text(html, encoding="utf-8")
    print(f"Private prototype written to {output}")
    print(
        f"Selected records: {len(cases)}; "
        f"external calls made: {external_calls}; playlist writes made: 0"
    )


if __name__ == "__main__":
    main()
