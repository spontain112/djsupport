"""Tests for djsupport.spotify rate limit handling."""

from unittest.mock import MagicMock, patch

import pytest
import spotipy

from djsupport.spotify import RateLimitError, _api_call_with_rate_limit


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
        mock_sleep.assert_called_once_with(1)  # floor of max(0, 1)
