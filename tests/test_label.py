"""Tests for Beatport label scraper."""

import json

import pytest
from unittest.mock import patch, MagicMock

from djsupport.label import (
    validate_label_url,
    fetch_label_tracks,
    search_labels,
    deduplicate_tracks,
    _parse_label_page,
    _parse_label_track,
    LabelParseError,
    InvalidLabelURL,
    LabelResult,
    PER_PAGE,
    LARGE_LABEL_THRESHOLD,
)
from djsupport.rekordbox import Track


class TestValidateLabelUrl:
    def test_valid_url(self):
        result = validate_label_url("https://www.beatport.com/label/drumcode/1")
        assert result == "https://www.beatport.com/label/drumcode/1"

    def test_valid_url_no_www(self):
        result = validate_label_url("https://beatport.com/label/drumcode/1")
        assert result == "https://beatport.com/label/drumcode/1"

    def test_valid_url_with_tracks_suffix(self):
        result = validate_label_url("https://www.beatport.com/label/drumcode/1/tracks")
        assert result == "https://www.beatport.com/label/drumcode/1"

    def test_strips_trailing_slash(self):
        result = validate_label_url("https://www.beatport.com/label/test/123/")
        assert not result.endswith("/")

    def test_strips_query_params(self):
        result = validate_label_url("https://www.beatport.com/label/test/123?page=1&per_page=150")
        assert "?" not in result

    def test_strips_tracks_suffix_and_query(self):
        result = validate_label_url("https://www.beatport.com/label/test/123/tracks?page=2")
        assert result == "https://www.beatport.com/label/test/123"

    def test_rejects_http(self):
        with pytest.raises(InvalidLabelURL):
            validate_label_url("http://www.beatport.com/label/test/123")

    def test_rejects_non_label_url(self):
        with pytest.raises(InvalidLabelURL):
            validate_label_url("https://www.beatport.com/chart/some-chart/12345")

    def test_rejects_track_url(self):
        with pytest.raises(InvalidLabelURL):
            validate_label_url("https://www.beatport.com/track/some-track/12345")

    def test_rejects_non_beatport_url(self):
        with pytest.raises(InvalidLabelURL):
            validate_label_url("https://example.com/label/foo/123")

    def test_rejects_labels_listing_page(self):
        with pytest.raises(InvalidLabelURL):
            validate_label_url("https://www.beatport.com/labels")

    def test_hyphenated_slug(self):
        result = validate_label_url("https://www.beatport.com/label/black-book-records/60197")
        assert result == "https://www.beatport.com/label/black-book-records/60197"


class TestParseLabelTrack:
    def test_basic_track(self):
        item = {
            "id": 12345,
            "name": "Acid Rain",
            "mix_name": "Original Mix",
            "artists": [{"name": "Adam Beyer"}],
            "release": {"name": "Acid Rain EP", "label": {"name": "Drumcode"}},
            "genre": {"name": "Techno (Peak Time / Driving)"},
            "length": "6:30",
            "publish_date": "2026-02-15",
        }
        track = _parse_label_track(item, 0)
        assert track.name == "Acid Rain"  # Original Mix omitted
        assert track.artist == "Adam Beyer"
        assert track.label == "Drumcode"
        assert track.duration == 390
        assert track.track_id == "bp-label-12345"
        assert track.date_added == "2026-02-15"
        assert track.genre == "Techno (Peak Time / Driving)"

    def test_remix_track(self):
        item = {
            "id": 67890,
            "name": "Vibe",
            "mix_name": "Radio Edit",
            "artists": [{"name": "Artist A"}, {"name": "Artist B"}],
            "release": {"name": "Vibe EP", "label": {"name": "Label X"}},
            "genre": {"name": "House"},
            "length": "3:30",
            "publish_date": "2026-01-10",
        }
        track = _parse_label_track(item, 1)
        assert track.name == "Vibe (Radio Edit)"
        assert track.artist == "Artist A, Artist B"
        assert track.duration == 210
        assert track.date_added == "2026-01-10"

    def test_original_mix_name_omitted(self):
        """Label pages use 'Original' instead of 'Original Mix' — both should be omitted."""
        item = {
            "id": 1,
            "name": "Contra Natura",
            "mix_name": "Original",
            "artists": [{"name": "VALON (SE)"}],
            "release": {"name": "EP", "label": {"name": "Label"}},
            "genre": {"name": "Techno"},
            "length": "5:00",
            "publish_date": "2025-11-21",
        }
        track = _parse_label_track(item, 0)
        assert track.name == "Contra Natura"  # "Original" omitted just like "Original Mix"

    def test_missing_publish_date_uses_new_release_date(self):
        item = {
            "id": 1,
            "name": "Test",
            "mix_name": "",
            "length": "3:00",
            "new_release_date": "2026-01-01",
        }
        track = _parse_label_track(item, 0)
        assert track.date_added == "2026-01-01"

    def test_no_date_fields(self):
        item = {"id": 1, "name": "Test", "mix_name": "", "length": "3:00"}
        track = _parse_label_track(item, 0)
        assert track.date_added == ""

    def test_missing_artists(self):
        item = {"id": 1, "name": "Test", "mix_name": "", "length": "3:00"}
        track = _parse_label_track(item, 0)
        assert track.artist == ""

    def test_malformed_artists(self):
        item = {"id": 1, "name": "Test", "artists": "not a list", "length": "3:00"}
        track = _parse_label_track(item, 0)
        assert track.artist == ""

    def test_missing_release_info(self):
        item = {"id": 1, "name": "Test", "mix_name": "", "length": "3:00"}
        track = _parse_label_track(item, 0)
        assert track.album == ""
        assert track.label == ""

    def test_position_used_as_fallback_id(self):
        item = {"name": "Test", "mix_name": "", "length": "3:00"}
        track = _parse_label_track(item, 5)
        assert track.track_id == "bp-label-5"

    def test_track_is_track_dataclass(self):
        item = {"id": 1, "name": "Test", "mix_name": "", "length": "3:00"}
        track = _parse_label_track(item, 0)
        assert isinstance(track, Track)


class TestParseLabelData:
    def _make_label_data(self, tracks=None, label_name="Test Label", total_count=None):
        """Build a minimal __NEXT_DATA__ structure for a label page."""
        if tracks is None:
            tracks = [
                {
                    "id": 1,
                    "name": "Track One",
                    "mix_name": "Original Mix",
                    "artists": [{"name": "Artist One"}],
                    "release": {"name": "EP One", "label": {"name": "Label One"}},
                    "genre": {"name": "Techno"},
                    "length": "5:00",
                    "publish_date": "2026-02-01",
                },
            ]
        if total_count is None:
            total_count = len(tracks)
        return {
            "props": {
                "pageProps": {
                    "label": {"name": label_name},
                    "dehydratedState": {
                        "queries": [
                            {
                                "state": {
                                    "data": {
                                        "results": tracks,
                                        "count": total_count,
                                    }
                                }
                            }
                        ]
                    },
                }
            }
        }

    def test_extracts_label_name(self):
        data = self._make_label_data(label_name="Drumcode")
        name, tracks, total = _parse_label_page(data)
        assert name == "Drumcode"

    def test_extracts_tracks(self):
        data = self._make_label_data()
        _, tracks, _ = _parse_label_page(data)
        assert len(tracks) == 1
        assert tracks[0].name == "Track One"
        assert tracks[0].artist == "Artist One"

    def test_extracts_total_count(self):
        data = self._make_label_data(total_count=500)
        _, _, total = _parse_label_page(data)
        assert total == 500

    def test_missing_top_level_keys(self):
        with pytest.raises(LabelParseError, match="missing key"):
            _parse_label_page({"props": {}})

    def test_empty_results_returns_empty_list(self):
        data = {
            "props": {
                "pageProps": {
                    "label": {"name": "Empty Label"},
                    "dehydratedState": {
                        "queries": [
                            {
                                "state": {
                                    "data": {
                                        "results": [],
                                        "count": 0,
                                    }
                                }
                            }
                        ]
                    },
                }
            }
        }
        name, tracks, total = _parse_label_page(data)
        assert name == "Empty Label"
        assert tracks == []
        assert total == 0

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
        with pytest.raises(LabelParseError, match="Could not locate"):
            _parse_label_page(data)

    def test_missing_label_metadata_uses_default(self):
        data = self._make_label_data()
        data["props"]["pageProps"].pop("label", None)
        name, _, _ = _parse_label_page(data)
        assert name == "Unknown Label"

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
                "publish_date": f"2026-02-{i + 1:02d}",
            }
            for i in range(5)
        ]
        data = self._make_label_data(tracks=tracks)
        _, parsed, _ = _parse_label_page(data)
        assert len(parsed) == 5
        assert [t.name for t in parsed] == ["Track 0", "Track 1", "Track 2", "Track 3", "Track 4"]


class TestDeduplicateTracks:
    def _make_track(self, name="Test", artist="Artist", date="2026-01-01"):
        return Track(
            track_id="1",
            name=name,
            artist=artist,
            album="Album",
            remixer="",
            label="Label",
            genre="House",
            date_added=date,
            duration=300,
        )

    def test_no_duplicates(self):
        tracks = [
            self._make_track("Track A", "Artist A"),
            self._make_track("Track B", "Artist B"),
        ]
        unique, removed = deduplicate_tracks(tracks)
        assert len(unique) == 2
        assert removed == 0

    def test_exact_duplicates_removed(self):
        tracks = [
            self._make_track("Acid Rain", "Adam Beyer", "2026-02-01"),
            self._make_track("Acid Rain", "Adam Beyer", "2025-06-01"),
        ]
        unique, removed = deduplicate_tracks(tracks)
        assert len(unique) == 1
        assert removed == 1
        # First occurrence (newest) is kept
        assert unique[0].date_added == "2026-02-01"

    def test_case_insensitive(self):
        tracks = [
            self._make_track("acid rain", "adam beyer"),
            self._make_track("Acid Rain", "Adam Beyer"),
        ]
        unique, removed = deduplicate_tracks(tracks)
        assert len(unique) == 1
        assert removed == 1

    def test_whitespace_stripped(self):
        tracks = [
            self._make_track("Track ", " Artist"),
            self._make_track("Track", "Artist"),
        ]
        unique, removed = deduplicate_tracks(tracks)
        assert len(unique) == 1
        assert removed == 1

    def test_different_mixes_kept_separate(self):
        tracks = [
            self._make_track("Acid Rain", "Adam Beyer"),
            self._make_track("Acid Rain (Dub Mix)", "Adam Beyer"),
        ]
        unique, removed = deduplicate_tracks(tracks)
        assert len(unique) == 2
        assert removed == 0

    def test_preserves_order(self):
        tracks = [
            self._make_track("Track C", "Artist C"),
            self._make_track("Track A", "Artist A"),
            self._make_track("Track B", "Artist B"),
            self._make_track("Track A", "Artist A"),  # duplicate
        ]
        unique, removed = deduplicate_tracks(tracks)
        assert len(unique) == 3
        assert removed == 1
        assert [t.name for t in unique] == ["Track C", "Track A", "Track B"]

    def test_empty_list(self):
        unique, removed = deduplicate_tracks([])
        assert unique == []
        assert removed == 0

    def test_same_track_different_artist_kept(self):
        tracks = [
            self._make_track("Acid Rain", "Adam Beyer"),
            self._make_track("Acid Rain", "Someone Else"),
        ]
        unique, removed = deduplicate_tracks(tracks)
        assert len(unique) == 2
        assert removed == 0


class TestFetchLabelTracks:
    def _mock_response(self, content, url="https://www.beatport.com/label/test/123/tracks", encoding="utf-8"):
        mock = MagicMock()
        mock.iter_content.return_value = [content.encode(encoding) if isinstance(content, str) else content]
        mock.encoding = encoding
        mock.url = url
        mock.raise_for_status = MagicMock()
        mock.close = MagicMock()
        return mock

    def _make_label_html(self, tracks=None, label_name="Test Label", total_count=None):
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
                    "publish_date": "2026-02-01",
                },
            ]
        if total_count is None:
            total_count = len(tracks)
        data = {
            "props": {
                "pageProps": {
                    "label": {"name": label_name},
                    "dehydratedState": {
                        "queries": [
                            {
                                "state": {
                                    "data": {
                                        "results": tracks,
                                        "count": total_count,
                                    }
                                }
                            }
                        ]
                    },
                }
            }
        }
        return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'

    @patch("djsupport.label.requests.get")
    def test_single_page_label(self, mock_get):
        html = self._make_label_html(total_count=1)
        mock_get.return_value = self._mock_response(html)

        name, tracks = fetch_label_tracks("https://www.beatport.com/label/test/123")
        assert name == "Test Label"
        assert len(tracks) == 1
        assert tracks[0].name == "Track One"

    @patch("djsupport.label.requests.get")
    def test_missing_next_data(self, mock_get):
        mock_get.return_value = self._mock_response("<html><body>No data</body></html>")
        with pytest.raises(LabelParseError, match="Could not find label data"):
            fetch_label_tracks("https://www.beatport.com/label/test/123")

    @patch("djsupport.label.requests.get")
    def test_anti_bot_detection(self, mock_get):
        mock_get.return_value = self._mock_response("<html>/human-test/start</html>")
        with pytest.raises(LabelParseError, match="anti-bot"):
            fetch_label_tracks("https://www.beatport.com/label/test/123")

    @patch("djsupport.label.requests.get")
    def test_redirect_to_non_label_rejected(self, mock_get):
        mock_get.return_value = self._mock_response(
            "<html></html>",
            url="https://www.beatport.com/login",
        )
        with pytest.raises(LabelParseError, match="redirected"):
            fetch_label_tracks("https://www.beatport.com/label/test/123")

    @patch("djsupport.label.requests.get")
    def test_response_too_large(self, mock_get):
        mock = MagicMock()
        mock.iter_content.return_value = [b"x" * (6 * 1024 * 1024)]
        mock.encoding = "utf-8"
        mock.url = "https://www.beatport.com/label/test/123/tracks"
        mock.raise_for_status = MagicMock()
        mock.close = MagicMock()
        mock_get.return_value = mock
        with pytest.raises(LabelParseError, match="too large"):
            fetch_label_tracks("https://www.beatport.com/label/test/123")

    @patch("djsupport.label.requests.get")
    def test_empty_label_returns_empty_list(self, mock_get):
        html = self._make_label_html(tracks=[], total_count=0)
        mock_get.return_value = self._mock_response(html)

        name, tracks = fetch_label_tracks("https://www.beatport.com/label/test/123")
        assert name == "Test Label"
        assert tracks == []

    @patch("djsupport.label.requests.get")
    def test_pagination_two_pages(self, mock_get):
        page1_tracks = [
            {
                "id": i,
                "name": f"Track {i}",
                "mix_name": "Original Mix",
                "artists": [{"name": "Artist"}],
                "release": {"name": "", "label": {"name": ""}},
                "genre": {"name": ""},
                "length": "3:00",
                "publish_date": "2026-02-01",
            }
            for i in range(PER_PAGE)
        ]
        page2_tracks = [
            {
                "id": PER_PAGE + i,
                "name": f"Track {PER_PAGE + i}",
                "mix_name": "Original Mix",
                "artists": [{"name": "Artist"}],
                "release": {"name": "", "label": {"name": ""}},
                "genre": {"name": ""},
                "length": "3:00",
                "publish_date": "2026-01-15",
            }
            for i in range(10)
        ]
        total = PER_PAGE + 10

        html1 = self._make_label_html(tracks=page1_tracks, total_count=total)
        html2 = self._make_label_html(tracks=page2_tracks, total_count=total)

        mock_get.side_effect = [
            self._mock_response(html1),
            self._mock_response(html2),
        ]

        name, tracks = fetch_label_tracks("https://www.beatport.com/label/test/123")
        assert len(tracks) == total

    @patch("djsupport.label.requests.get")
    def test_on_total_callback_abort(self, mock_get):
        html = self._make_label_html(total_count=2000)
        mock_get.return_value = self._mock_response(html)

        name, tracks = fetch_label_tracks(
            "https://www.beatport.com/label/test/123",
            on_total=lambda total: False,
        )
        assert name == "Test Label"
        assert tracks == []

    @patch("djsupport.label.requests.get")
    def test_on_total_callback_continue(self, mock_get):
        html = self._make_label_html(total_count=1)
        mock_get.return_value = self._mock_response(html)

        called_with = []
        name, tracks = fetch_label_tracks(
            "https://www.beatport.com/label/test/123",
            on_total=lambda total: called_with.append(total),
        )
        assert called_with == [1]
        assert len(tracks) == 1

    @patch("djsupport.label.requests.get")
    def test_on_page_callback(self, mock_get):
        html = self._make_label_html(total_count=1)
        mock_get.return_value = self._mock_response(html)

        pages = []
        name, tracks = fetch_label_tracks(
            "https://www.beatport.com/label/test/123",
            on_page=lambda p, t: pages.append((p, t)),
        )
        assert pages == [(1, 1)]

    @patch("djsupport.label.requests.get")
    def test_pagination_failure_returns_partial(self, mock_get):
        import requests as req

        page1_tracks = [
            {
                "id": i,
                "name": f"Track {i}",
                "mix_name": "Original Mix",
                "artists": [{"name": "Artist"}],
                "release": {"name": "", "label": {"name": ""}},
                "genre": {"name": ""},
                "length": "3:00",
                "publish_date": "2026-02-01",
            }
            for i in range(3)
        ]
        html1 = self._make_label_html(tracks=page1_tracks, total_count=PER_PAGE + 10)

        mock_get.side_effect = [
            self._mock_response(html1),
            req.RequestException("Network error"),
        ]

        name, tracks = fetch_label_tracks("https://www.beatport.com/label/test/123")
        assert len(tracks) == 3  # Only page 1 tracks


class TestSearchLabels:
    def _make_search_html(self, labels=None):
        if labels is None:
            labels = [
                {
                    "id": 1,
                    "name": "Drumcode",
                    "slug": "drumcode",
                    "track_count": 5000,
                    "last_release": {
                        "name": "Acid Rain",
                        "publish_date": "2026-02-15",
                    },
                },
            ]
        data = {
            "props": {
                "pageProps": {
                    "dehydratedState": {
                        "queries": [
                            {
                                "state": {
                                    "data": {
                                        "results": labels,
                                    }
                                }
                            }
                        ]
                    },
                }
            }
        }
        return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'

    def _mock_response(self, content, encoding="utf-8"):
        mock = MagicMock()
        mock.iter_content.return_value = [content.encode(encoding) if isinstance(content, str) else content]
        mock.encoding = encoding
        mock.url = "https://www.beatport.com/search/labels?q=drumcode"
        mock.raise_for_status = MagicMock()
        mock.close = MagicMock()
        return mock

    @patch("djsupport.label.requests.get")
    def test_search_returns_results(self, mock_get):
        html = self._make_search_html()
        mock_get.return_value = self._mock_response(html)

        results = search_labels("Drumcode")
        assert len(results) == 1
        assert results[0].name == "Drumcode"
        assert results[0].url == "https://www.beatport.com/label/drumcode/1"
        assert results[0].latest_release == "Acid Rain"
        assert results[0].latest_release_date == "2026-02-15"

    @patch("djsupport.label.requests.get")
    def test_search_no_results(self, mock_get):
        html = self._make_search_html(labels=[])
        mock_get.return_value = self._mock_response(html)

        results = search_labels("nonexistentlabel12345")
        assert results == []

    @patch("djsupport.label.requests.get")
    def test_search_multiple_results(self, mock_get):
        labels = [
            {
                "id": 1,
                "name": "Drumcode",
                "slug": "drumcode",
                "track_count": 5000,
                "last_release": {"name": "Track A", "publish_date": "2026-02-15"},
            },
            {
                "id": 456,
                "name": "Drumcode Limited",
                "slug": "drumcode-limited",
                "track_count": 200,
                "last_release": {"name": "Track B", "publish_date": "2025-11-03"},
            },
        ]
        html = self._make_search_html(labels=labels)
        mock_get.return_value = self._mock_response(html)

        results = search_labels("Drumcode")
        assert len(results) == 2
        assert results[0].name == "Drumcode"
        assert results[1].name == "Drumcode Limited"
        assert results[1].url == "https://www.beatport.com/label/drumcode-limited/456"

    @patch("djsupport.label.requests.get")
    def test_search_missing_last_release(self, mock_get):
        labels = [
            {
                "id": 1,
                "name": "New Label",
                "slug": "new-label",
                "track_count": 0,
            },
        ]
        html = self._make_search_html(labels=labels)
        mock_get.return_value = self._mock_response(html)

        results = search_labels("New Label")
        assert len(results) == 1
        assert results[0].latest_release == ""
        assert results[0].latest_release_date == ""

    @patch("djsupport.label.requests.get")
    def test_search_anti_bot_detection(self, mock_get):
        mock_get.return_value = self._mock_response("<html>/human-test/start</html>")
        with pytest.raises(LabelParseError, match="anti-bot"):
            search_labels("Drumcode")
