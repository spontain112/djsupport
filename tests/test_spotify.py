"""Tests for djsupport.spotify."""

from unittest.mock import MagicMock, patch

import pytest
import spotipy

from djsupport.spotify import (
    RateLimitError,
    SCOPES,
    _api_call_with_rate_limit,
    _parse_retry_after,
)
from djsupport.transfer import SpotifyMatcher, SpotifyItemKind


def _make_429(retry_after: int) -> spotipy.SpotifyException:
    """Create a mock 429 SpotifyException with Retry-After header."""
    exc = spotipy.SpotifyException(429, -1, "rate limited")
    exc.http_status = 429
    exc.headers = {"Retry-After": str(retry_after)}
    return exc


def _make_500() -> spotipy.SpotifyException:
    """Create a mock 500 SpotifyException."""
    exc = spotipy.SpotifyException(500, -1, "server error")
    exc.http_status = 500
    exc.headers = {}
    return exc


class TestRateLimitError:
    def test_seconds_format(self):
        e = RateLimitError(45)
        assert "45s" in str(e)
        assert e.retry_after == 45

    def test_minutes_format(self):
        e = RateLimitError(125)
        assert "2m 5s" in str(e)

    def test_hours_format(self):
        e = RateLimitError(3725)
        assert "1h 2m" in str(e)

    def test_message_does_not_mention_cache(self):
        e = RateLimitError(60)
        assert "cache" not in str(e).lower()


class TestApiCallWithRateLimit:
    @patch("djsupport.spotify.time.sleep")
    def test_short_429_retries_successfully(self, mock_sleep):
        func = MagicMock(side_effect=[_make_429(5), "ok"])
        result = _api_call_with_rate_limit(func)
        assert result == "ok"
        mock_sleep.assert_called_once_with(5)

    @patch("djsupport.spotify.time.sleep")
    def test_long_429_raises_rate_limit_error(self, mock_sleep):
        func = MagicMock(side_effect=_make_429(3600))
        with pytest.raises(RateLimitError) as exc_info:
            _api_call_with_rate_limit(func)
        assert exc_info.value.retry_after == 3600
        mock_sleep.assert_not_called()

    @patch("djsupport.spotify.time.sleep")
    def test_double_429_raises_rate_limit_error(self, mock_sleep):
        func = MagicMock(side_effect=[_make_429(5), _make_429(7200)])
        with pytest.raises(RateLimitError) as exc_info:
            _api_call_with_rate_limit(func)
        assert exc_info.value.retry_after == 7200
        mock_sleep.assert_called_once_with(5)

    @patch("djsupport.spotify.time.sleep")
    def test_retry_after_zero_floors_to_1s(self, mock_sleep):
        func = MagicMock(side_effect=[_make_429(0), "ok"])
        result = _api_call_with_rate_limit(func)
        assert result == "ok"
        mock_sleep.assert_called_once_with(1)

    def test_non_429_exception_reraises(self):
        func = MagicMock(side_effect=_make_500())
        with pytest.raises(spotipy.SpotifyException) as exc_info:
            _api_call_with_rate_limit(func)
        assert exc_info.value.http_status == 500

    def test_success_on_first_call(self):
        func = MagicMock(return_value={"tracks": {"items": []}})
        result = _api_call_with_rate_limit(func)
        assert result == {"tracks": {"items": []}}
        func.assert_called_once()

    @patch("djsupport.spotify.time.sleep")
    def test_missing_headers_defaults_to_1s(self, mock_sleep):
        exc = spotipy.SpotifyException(429, -1, "rate limited")
        exc.http_status = 429
        exc.headers = None
        func = MagicMock(side_effect=[exc, "ok"])
        result = _api_call_with_rate_limit(func)
        assert result == "ok"
        mock_sleep.assert_called_once_with(1)

    @patch("djsupport.spotify.time.sleep")
    def test_non_numeric_retry_after_defaults_to_1s(self, mock_sleep):
        exc = spotipy.SpotifyException(429, -1, "rate limited")
        exc.http_status = 429
        exc.headers = {"Retry-After": "Fri, 31 Dec 2026 23:59:59 GMT"}
        func = MagicMock(side_effect=[exc, "ok"])
        result = _api_call_with_rate_limit(func)
        assert result == "ok"
        mock_sleep.assert_called_once_with(1)


class TestParseRetryAfter:
    def test_numeric_value(self):
        exc = spotipy.SpotifyException(429, -1, "rate limited")
        exc.http_status = 429
        exc.headers = {"Retry-After": "30"}
        assert _parse_retry_after(exc) == 30

    def test_zero_floors_to_1(self):
        exc = spotipy.SpotifyException(429, -1, "rate limited")
        exc.http_status = 429
        exc.headers = {"Retry-After": "0"}
        assert _parse_retry_after(exc) == 1
    def test_negative_floors_to_1(self):
        exc = spotipy.SpotifyException(429, -1, "rate limited")
        exc.http_status = 429
        exc.headers = {"Retry-After": "-5"}
        assert _parse_retry_after(exc) == 1

    def test_non_numeric_defaults_to_1(self):
        exc = spotipy.SpotifyException(429, -1, "rate limited")
        exc.http_status = 429
        exc.headers = {"Retry-After": "Fri, 31 Dec 2026 23:59:59 GMT"}
        assert _parse_retry_after(exc) == 1

    def test_none_headers_defaults_to_1(self):
        exc = spotipy.SpotifyException(429, -1, "rate limited")
        exc.http_status = 429
        exc.headers = None
        assert _parse_retry_after(exc) == 1


def test_private_playlist_read_is_the_only_new_read_scope():
    assert set(SCOPES.split()) == {
        "playlist-read-private",
        "playlist-modify-public",
        "playlist-modify-private",
    }


def test_spotify_adapter_uses_current_account_and_playlist_contracts():
    client = MagicMock()
    client.current_user.return_value = {"id": "stable-account"}
    client.current_user_playlist_create.return_value = {"id": "playlist-1"}

    adapter = SpotifyMatcher(client)
    created = adapter.create_playlist("Name", "Description")

    assert adapter.account_id() == "stable-account"
    assert created == "playlist-1"
    client.current_user_playlist_create.assert_called_once_with(
        "Name", public=False, description="Description",
    )
    client.user_playlist_create.assert_not_called()


def test_ordered_playlist_facts_preserve_duplicates_and_unknown_shapes():
    client = MagicMock()
    client.playlist.return_value = {"snapshot_id": "head-1"}
    client.playlist_items.return_value = {
        "items": [
            {"track": {"type": "track", "uri": "spotify:track:one"}},
            {"track": {"type": "track", "uri": "spotify:track:one"}},
            {"track": None},
            {"track": {"type": "episode", "uri": "spotify:episode:e"}},
            {"track": {"type": "future", "uri": "spotify:future:f"}},
        ],
        "next": None,
    }

    adapter = SpotifyMatcher(client)

    assert adapter.playlist_head("playlist-1").snapshot_id == "head-1"
    page = adapter.ordered_playlist_items("playlist-1")
    assert [item.position for item in page.items] == [0, 1, 2, 3, 4]
    assert [item.kind for item in page.items] == [
        SpotifyItemKind.TRACK,
        SpotifyItemKind.TRACK,
        SpotifyItemKind.NULL,
        SpotifyItemKind.EPISODE,
        SpotifyItemKind.UNSUPPORTED,
    ]
    assert [item.uri for item in page.items[:2]] == [
        "spotify:track:one", "spotify:track:one",
    ]
