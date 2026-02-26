"""Tests for djsupport.spotify."""

from unittest.mock import MagicMock, call, patch

import pytest
import spotipy

from djsupport.spotify import (
    RateLimitError,
    _api_call_with_rate_limit,
    _parse_retry_after,
    create_or_update_playlist,
    incremental_update_playlist,
)


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


def _make_mock_sp(user_id="user1", existing_playlist_id=None):
    """Create a mock Spotify client for playlist tests."""
    sp = MagicMock()
    sp.current_user.return_value = {"id": user_id}
    sp.user_playlist_create.return_value = {"id": "new_pl_id"}
    sp.playlist.return_value = {"name": "whatever", "id": existing_playlist_id or "pl_id"}
    return sp


class TestCreateOrUpdatePlaylistDescription:
    @patch("djsupport.spotify.resolve_playlist_id", return_value=(None, "none"))
    @patch("djsupport.spotify.get_user_playlists", return_value={})
    def test_create_passes_description(self, _get, _resolve):
        sp = _make_mock_sp()
        create_or_update_playlist(
            sp, "Test", ["spotify:track:1"],
            description="Synced from Rekordbox by djsupport",
        )
        sp.user_playlist_create.assert_called_once_with(
            "user1", "Test", public=False,
            description="Synced from Rekordbox by djsupport",
        )

    @patch("djsupport.spotify.resolve_playlist_id", return_value=(None, "none"))
    @patch("djsupport.spotify.get_user_playlists", return_value={})
    def test_create_without_description(self, _get, _resolve):
        sp = _make_mock_sp()
        create_or_update_playlist(sp, "Test", ["spotify:track:1"])
        sp.user_playlist_create.assert_called_once_with(
            "user1", "Test", public=False,
        )

    @patch("djsupport.spotify._rename_if_needed")
    @patch("djsupport.spotify.resolve_playlist_id", return_value=("existing_id", "state"))
    @patch("djsupport.spotify.get_user_playlists", return_value={})
    def test_update_sets_description(self, _get, _resolve, _rename):
        sp = _make_mock_sp()
        create_or_update_playlist(
            sp, "Test", ["spotify:track:1"],
            description="Imported from Beatport by djsupport",
        )
        sp.playlist_change_details.assert_called_once_with(
            "existing_id", description="Imported from Beatport by djsupport",
        )

    @patch("djsupport.spotify._rename_if_needed")
    @patch("djsupport.spotify.resolve_playlist_id", return_value=("existing_id", "state"))
    @patch("djsupport.spotify.get_user_playlists", return_value={})
    def test_update_without_description_skips_change_details(self, _get, _resolve, _rename):
        sp = _make_mock_sp()
        create_or_update_playlist(sp, "Test", ["spotify:track:1"])
        sp.playlist_change_details.assert_not_called()


class TestIncrementalUpdatePlaylistDescription:
    @patch("djsupport.spotify.resolve_playlist_id", return_value=(None, "none"))
    @patch("djsupport.spotify.get_user_playlists", return_value={})
    def test_delegates_description_to_create(self, _get, _resolve):
        sp = _make_mock_sp()
        with patch("djsupport.spotify.create_or_update_playlist", return_value=("new_id", "created")) as mock_create:
            incremental_update_playlist(
                sp, "Test", ["spotify:track:1"],
                description="Synced from Rekordbox by djsupport",
            )
            mock_create.assert_called_once()
            assert mock_create.call_args.kwargs["description"] == "Synced from Rekordbox by djsupport"

    @patch("djsupport.spotify.get_playlist_tracks", return_value=["spotify:track:1"])
    @patch("djsupport.spotify._rename_if_needed")
    @patch("djsupport.spotify.resolve_playlist_id", return_value=("existing_id", "state"))
    @patch("djsupport.spotify.get_user_playlists", return_value={})
    def test_existing_playlist_sets_description(self, _get, _resolve, _rename, _tracks):
        sp = _make_mock_sp()
        incremental_update_playlist(
            sp, "Test", ["spotify:track:1"],
            description="Imported from Beatport by djsupport",
        )
        sp.playlist_change_details.assert_called_once_with(
            "existing_id", description="Imported from Beatport by djsupport",
        )

    @patch("djsupport.spotify.get_playlist_tracks", return_value=["spotify:track:1"])
    @patch("djsupport.spotify._rename_if_needed")
    @patch("djsupport.spotify.resolve_playlist_id", return_value=("existing_id", "state"))
    @patch("djsupport.spotify.get_user_playlists", return_value={})
    def test_existing_playlist_no_description_skips(self, _get, _resolve, _rename, _tracks):
        sp = _make_mock_sp()
        incremental_update_playlist(sp, "Test", ["spotify:track:1"])
        sp.playlist_change_details.assert_not_called()
