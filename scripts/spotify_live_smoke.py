#!/usr/bin/env python3
"""Probe the live Spotify search boundary with application credentials.

The scheduled live smoke workflow and maintainers run this from a shell. It is
never part of the offline suite. It uses the client-credentials flow, so it
covers application authentication and the search path that matching relies
on. User-scoped playlist operations need interactive consent and stay outside
this check.

Requires SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET in the environment. The
probe reads no user-derived data, keeps the token in memory only, and prints
no token or secret.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping

import requests
import spotipy
from spotipy.cache_handler import MemoryCacheHandler
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOauthError

from djsupport.spotify import (
    QuotaExceededError,
    RateLimitError,
    SpotifyCapabilityError,
    search_track,
)

REQUIRED_ENVIRONMENT = ("SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET")
PROBE_ARTIST = "Daft Punk"
PROBE_TITLE = "One More Time"
RESULT_KEYS = ("uri", "name", "artist", "album", "duration_ms")
TRACK_URI_PREFIX = "spotify:track:"
REQUEST_TIMEOUT_SECONDS = 15


class SmokeCheckError(RuntimeError):
    """The live boundary answered, but not with a usable search result."""


def missing_environment(environ: Mapping[str, str]) -> list[str]:
    return [name for name in REQUIRED_ENVIRONMENT if not environ.get(name)]


def validate_results(results: list[dict]) -> None:
    if not results:
        raise SmokeCheckError("search returned no results for the public probe track")
    for result in results:
        absent = [key for key in RESULT_KEYS if key not in result]
        if absent:
            raise SmokeCheckError(f"search result is missing {', '.join(absent)}")
        if not str(result["uri"]).startswith(TRACK_URI_PREFIX):
            raise SmokeCheckError("search result uri is not a Spotify track URI")
        if not result["name"] or not result["artist"]:
            raise SmokeCheckError("search result has an empty name or artist")


def probe_search(client: spotipy.Spotify) -> dict[str, object]:
    results = search_track(client, PROBE_ARTIST, PROBE_TITLE)
    validate_results(results)
    top = results[0]
    return {"results": len(results), "top_name": top["name"], "top_artist": top["artist"]}


def build_client() -> spotipy.Spotify:
    auth_manager = SpotifyClientCredentials(cache_handler=MemoryCacheHandler())
    return spotipy.Spotify(
        auth_manager=auth_manager, requests_timeout=REQUEST_TIMEOUT_SECONDS
    )


def main(environ: Mapping[str, str] | None = None) -> int:
    environ = os.environ if environ is None else environ
    absent = missing_environment(environ)
    if absent:
        print(
            f"Live smoke check needs {', '.join(absent)} in the environment.",
            file=sys.stderr,
        )
        return 2
    try:
        summary = probe_search(build_client())
    except SpotifyOauthError:
        print("Live smoke check could not obtain an application token.", file=sys.stderr)
        return 1
    except spotipy.SpotifyException as exc:
        print(f"Live smoke check failed with HTTP {exc.http_status}.", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(
            f"Live smoke check could not reach Spotify: {type(exc).__name__}.",
            file=sys.stderr,
        )
        return 1
    except (RateLimitError, QuotaExceededError, SpotifyCapabilityError, SmokeCheckError) as exc:
        print(f"Live smoke check failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"Live Spotify search boundary OK: {summary['results']} results; "
        f"top result {summary['top_artist']} - {summary['top_name']}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
