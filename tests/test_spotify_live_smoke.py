"""Offline behavior of the live Spotify smoke probe; no network is touched."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SPEC = importlib.util.spec_from_file_location(
    "spotify_live_smoke",
    Path(__file__).parents[1] / "scripts" / "spotify_live_smoke.py",
)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


def _search_payload(items):
    return {"tracks": {"items": items}}


def _item(uri="spotify:track:synthetic1", name="Synthetic Song", artist="Invented Artist"):
    return {
        "uri": uri,
        "name": name,
        "artists": [{"name": artist}],
        "album": {"name": "Invented Album"},
        "duration_ms": 321000,
    }


def test_missing_environment_names_every_absent_credential():
    assert smoke.missing_environment({}) == [
        "SPOTIPY_CLIENT_ID",
        "SPOTIPY_CLIENT_SECRET",
    ]
    assert smoke.missing_environment({"SPOTIPY_CLIENT_ID": "id"}) == [
        "SPOTIPY_CLIENT_SECRET"
    ]
    assert smoke.missing_environment(
        {"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"}
    ) == []


def test_main_exits_before_any_network_call_without_credentials(capsys):
    assert smoke.main({}) == 2

    captured = capsys.readouterr()
    assert "SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET" in captured.err
    assert captured.out == ""


def test_probe_search_summarizes_a_well_formed_search_response():
    client = MagicMock()
    client.search.return_value = _search_payload([_item(), _item(uri="spotify:track:b")])

    summary = smoke.probe_search(client)

    assert summary == {
        "results": 2,
        "top_name": "Synthetic Song",
        "top_artist": "Invented Artist",
    }
    client.search.assert_called_once_with(
        q="artist:Daft Punk track:One More Time", type="track", limit=5
    )


@pytest.mark.parametrize(
    "results, message",
    [
        ([], "no results"),
        ([{"uri": "spotify:track:x", "name": "n"}], "missing artist, album, duration_ms"),
        (
            [
                {
                    "uri": "spotify:episode:x",
                    "name": "n",
                    "artist": "a",
                    "album": "b",
                    "duration_ms": 1,
                }
            ],
            "not a Spotify track URI",
        ),
        (
            [
                {
                    "uri": "spotify:track:x",
                    "name": "",
                    "artist": "a",
                    "album": "b",
                    "duration_ms": 1,
                }
            ],
            "empty name or artist",
        ),
    ],
)
def test_validate_results_fails_closed_on_malformed_boundary_answers(results, message):
    with pytest.raises(smoke.SmokeCheckError, match=message):
        smoke.validate_results(results)


def test_main_reports_boundary_failures_without_leaking_details(monkeypatch, capsys):
    environ = {"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"}
    client = MagicMock()
    client.search.side_effect = smoke.spotipy.SpotifyException(
        500, -1, "https://api.spotify.com/v1/search?q=secret-looking-query"
    )
    monkeypatch.setattr(smoke, "build_client", lambda: client)

    assert smoke.main(environ) == 1

    captured = capsys.readouterr()
    assert captured.err.strip() == "Live smoke check failed with HTTP 500."
    assert "secret" not in captured.err


def test_main_prints_only_public_catalogue_facts_on_success(monkeypatch, capsys):
    environ = {"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"}
    client = MagicMock()
    client.search.return_value = _search_payload([_item()])
    monkeypatch.setattr(smoke, "build_client", lambda: client)

    assert smoke.main(environ) == 0

    captured = capsys.readouterr()
    assert captured.out.strip() == (
        "Live Spotify search boundary OK: 1 results; "
        "top result Invented Artist - Synthetic Song."
    )
    assert "secret" not in captured.out
