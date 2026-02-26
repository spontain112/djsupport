"""Tests for Beatport chart scraper."""

import json

import pytest
from unittest.mock import patch, MagicMock

from djsupport.beatport import (
    validate_url,
    fetch_chart,
    _parse_chart_data,
    _parse_track,
    _parse_duration,
    BeatportParseError,
    InvalidBeatportURL,
)
from djsupport.rekordbox import Track


class TestValidateUrl:
    def test_valid_url(self):
        result = validate_url("https://www.beatport.com/chart/garage-go-tos/815070")
        assert result == "https://www.beatport.com/chart/garage-go-tos/815070"

    def test_valid_url_no_www(self):
        result = validate_url("https://beatport.com/chart/garage-go-tos/815070")
        assert result == "https://beatport.com/chart/garage-go-tos/815070"

    def test_strips_trailing_slash(self):
        result = validate_url("https://www.beatport.com/chart/test/123/")
        assert not result.endswith("/")

    def test_strips_query_params(self):
        result = validate_url("https://www.beatport.com/chart/test/123?utm_source=share")
        assert "?" not in result

    def test_rejects_http(self):
        with pytest.raises(InvalidBeatportURL):
            validate_url("http://www.beatport.com/chart/test/123")

    def test_rejects_non_chart_url(self):
        with pytest.raises(InvalidBeatportURL):
            validate_url("https://www.beatport.com/track/some-track/12345")

    def test_rejects_non_beatport_url(self):
        with pytest.raises(InvalidBeatportURL):
            validate_url("https://example.com/chart/foo/123")

    def test_rejects_chart_listing_page(self):
        with pytest.raises(InvalidBeatportURL):
            validate_url("https://www.beatport.com/charts")


class TestParseDuration:
    def test_minutes_seconds(self):
        assert _parse_duration("4:44") == 284

    def test_hours_minutes_seconds(self):
        assert _parse_duration("1:04:30") == 3870

    def test_empty_string(self):
        assert _parse_duration("") == 0

    def test_no_colon(self):
        assert _parse_duration("284") == 0

    def test_invalid_numbers(self):
        assert _parse_duration("4:ab") == 0

    def test_single_part(self):
        assert _parse_duration("4:") == 0

    def test_four_parts(self):
        assert _parse_duration("1:2:3:4") == 0


class TestParseTrack:
    def test_basic_track(self):
        item = {
            "id": 12345,
            "name": "Sinkhole",
            "mix_name": "Original Mix",
            "artists": [{"name": "Pearson Sound"}],
            "release": {"name": "Sinkhole EP", "label": {"name": "Hessle Audio"}},
            "genre": {"name": "UK Garage / Bassline"},
            "bpm": 129,
            "length": "4:44",
        }
        track = _parse_track(item, 0)
        assert track.name == "Sinkhole"  # Original Mix omitted
        assert track.artist == "Pearson Sound"
        assert track.label == "Hessle Audio"
        assert track.duration == 284
        assert track.track_id == "bp-12345"
        assert track.genre == "UK Garage / Bassline"

    def test_remix_track(self):
        item = {
            "id": 67890,
            "name": "Vibe",
            "mix_name": "Radio Edit",
            "artists": [{"name": "Artist A"}, {"name": "Artist B"}],
            "release": {"name": "Vibe EP", "label": {"name": "Label X"}},
            "genre": {"name": "House"},
            "length": "3:30",
        }
        track = _parse_track(item, 1)
        assert track.name == "Vibe (Radio Edit)"
        assert track.artist == "Artist A, Artist B"
        assert track.duration == 210

    def test_missing_artists(self):
        item = {"id": 1, "name": "Test", "mix_name": "", "length": "3:00"}
        track = _parse_track(item, 0)
        assert track.artist == ""

    def test_malformed_artists(self):
        item = {"id": 1, "name": "Test", "artists": "not a list", "length": "3:00"}
        track = _parse_track(item, 0)
        assert track.artist == ""

    def test_missing_release_info(self):
        item = {"id": 1, "name": "Test", "mix_name": "", "length": "3:00"}
        track = _parse_track(item, 0)
        assert track.album == ""
        assert track.label == ""

    def test_position_used_as_fallback_id(self):
        item = {"name": "Test", "mix_name": "", "length": "3:00"}
        track = _parse_track(item, 5)
        assert track.track_id == "bp-5"

    def test_empty_mix_name_not_appended(self):
        item = {"id": 1, "name": "Track", "mix_name": "", "length": "3:00"}
        track = _parse_track(item, 0)
        assert track.name == "Track"

    def test_track_is_track_dataclass(self):
        item = {"id": 1, "name": "Test", "mix_name": "", "length": "3:00"}
        track = _parse_track(item, 0)
        assert isinstance(track, Track)
        assert track.display == " - Test"  # empty artist


class TestParseChartData:
    def _make_chart_data(self, tracks=None, chart_name="Test Chart", curator="DJ Test"):
        """Build a minimal __NEXT_DATA__ structure."""
        if tracks is None:
            tracks = [
                {
                    "id": 1,
                    "name": "Track One",
                    "mix_name": "Original Mix",
                    "artists": [{"name": "Artist One"}],
                    "release": {"name": "EP One", "label": {"name": "Label One"}},
                    "genre": {"name": "House"},
                    "length": "5:00",
                },
            ]
        return {
            "props": {
                "pageProps": {
                    "chart": {"name": chart_name, "dj": {"name": curator}},
                    "dehydratedState": {
                        "queries": [
                            {
                                "state": {
                                    "data": {
                                        "results": tracks,
                                    }
                                }
                            }
                        ]
                    },
                }
            }
        }

    def test_extracts_chart_name_and_curator(self):
        data = self._make_chart_data(chart_name="Peak Time", curator="Ben UFO")
        name, curator, tracks = _parse_chart_data(data, "https://example.com")
        assert name == "Peak Time"
        assert curator == "Ben UFO"

    def test_extracts_tracks(self):
        data = self._make_chart_data()
        _, _, tracks = _parse_chart_data(data, "https://example.com")
        assert len(tracks) == 1
        assert tracks[0].name == "Track One"
        assert tracks[0].artist == "Artist One"

    def test_missing_top_level_keys(self):
        with pytest.raises(BeatportParseError, match="missing key"):
            _parse_chart_data({"props": {}}, "https://example.com")

    def test_empty_queries(self):
        data = {"props": {"pageProps": {"dehydratedState": {"queries": []}}}}
        with pytest.raises(BeatportParseError, match="Could not locate"):
            _parse_chart_data(data, "https://example.com")

    def test_queries_without_track_results(self):
        data = {
            "props": {
                "pageProps": {
                    "dehydratedState": {
                        "queries": [
                            {"state": {"data": {"results": [{"no_artists_key": True}]}}},
                        ]
                    }
                }
            }
        }
        with pytest.raises(BeatportParseError, match="Could not locate"):
            _parse_chart_data(data, "https://example.com")

    def test_missing_chart_metadata_uses_defaults(self):
        data = self._make_chart_data()
        # Remove chart metadata
        data["props"]["pageProps"].pop("chart", None)
        name, curator, _ = _parse_chart_data(data, "https://example.com")
        assert name == "Unknown Chart"
        assert curator == "Unknown"

    def test_multiple_tracks_preserved_in_order(self):
        tracks = [
            {
                "id": i,
                "name": f"Track {i}",
                "mix_name": "Original Mix",
                "artists": [{"name": f"Artist {i}"}],
                "release": {"name": "", "label": {"name": ""}},
                "genre": {"name": ""},
                "length": "3:00",
            }
            for i in range(5)
        ]
        data = self._make_chart_data(tracks=tracks)
        _, _, parsed = _parse_chart_data(data, "https://example.com")
        assert len(parsed) == 5
        assert [t.name for t in parsed] == ["Track 0", "Track 1", "Track 2", "Track 3", "Track 4"]


class TestFetchChart:
    def _mock_response(self, content, url="https://www.beatport.com/chart/test/123", encoding="utf-8", status_code=200):
        mock = MagicMock()
        mock.iter_content.return_value = [content.encode(encoding) if isinstance(content, str) else content]
        mock.encoding = encoding
        mock.url = url
        mock.raise_for_status = MagicMock()
        mock.close = MagicMock()
        mock.status_code = status_code
        return mock

    @patch("djsupport.beatport.requests.get")
    def test_missing_next_data(self, mock_get):
        mock_get.return_value = self._mock_response("<html><body>No data</body></html>")
        with pytest.raises(BeatportParseError, match="Could not find chart data"):
            fetch_chart("https://www.beatport.com/chart/test/123")

    @patch("djsupport.beatport.requests.get")
    def test_anti_bot_detection(self, mock_get):
        mock_get.return_value = self._mock_response("<html>/human-test/start</html>")
        with pytest.raises(BeatportParseError, match="anti-bot"):
            fetch_chart("https://www.beatport.com/chart/test/123")

    @patch("djsupport.beatport.requests.get")
    def test_anti_bot_detection_findproof(self, mock_get):
        mock_get.return_value = self._mock_response("<html>findProof()</html>")
        with pytest.raises(BeatportParseError, match="anti-bot"):
            fetch_chart("https://www.beatport.com/chart/test/123")

    @patch("djsupport.beatport.requests.get")
    def test_redirect_to_non_chart_rejected(self, mock_get):
        mock_get.return_value = self._mock_response(
            "<html></html>",
            url="https://www.beatport.com/login",
        )
        with pytest.raises(BeatportParseError, match="redirected"):
            fetch_chart("https://www.beatport.com/chart/test/123")

    @patch("djsupport.beatport.requests.get")
    def test_response_too_large(self, mock_get):
        mock = MagicMock()
        # Simulate a response larger than MAX_RESPONSE_SIZE
        mock.iter_content.return_value = [b"x" * (6 * 1024 * 1024)]
        mock.encoding = "utf-8"
        mock.url = "https://www.beatport.com/chart/test/123"
        mock.raise_for_status = MagicMock()
        mock.close = MagicMock()
        mock_get.return_value = mock
        with pytest.raises(BeatportParseError, match="too large"):
            fetch_chart("https://www.beatport.com/chart/test/123")

    @patch("djsupport.beatport.requests.get")
    def test_successful_parse(self, mock_get):
        chart_data = {
            "props": {
                "pageProps": {
                    "chart": {"name": "Garage Go-Tos", "dj": {"name": "DJ Test"}},
                    "dehydratedState": {
                        "queries": [
                            {
                                "state": {
                                    "data": {
                                        "results": [
                                            {
                                                "id": 100,
                                                "name": "Test Track",
                                                "mix_name": "Original Mix",
                                                "artists": [{"name": "Test Artist"}],
                                                "release": {"name": "Test EP", "label": {"name": "Test Label"}},
                                                "genre": {"name": "House"},
                                                "length": "5:30",
                                            }
                                        ]
                                    }
                                }
                            }
                        ]
                    },
                }
            }
        }
        html = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(chart_data)}</script></html>'
        mock_get.return_value = self._mock_response(html)
        name, curator, tracks = fetch_chart("https://www.beatport.com/chart/test/123")
        assert name == "Garage Go-Tos"
        assert curator == "DJ Test"
        assert len(tracks) == 1
        assert tracks[0].name == "Test Track"
        assert tracks[0].artist == "Test Artist"
        assert tracks[0].duration == 330
