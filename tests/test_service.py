"""Tests for the service layer (sync orchestration)."""

from unittest.mock import MagicMock, patch

import pytest

from djsupport.rekordbox import Track
from djsupport.service import (
    ProgressEvent,
    match_and_sync_playlist,
    sync_beatport_chart,
    sync_beatport_label,
)


def _make_track(track_id="1", artist="Artist", name="Song"):
    return Track(
        track_id=track_id, name=name, artist=artist,
        album="Album", remixer="", label="", genre="", date_added="",
    )


def _make_match(uri="spotify:track:abc"):
    return {
        "uri": uri,
        "name": "Song",
        "artist": "Artist",
        "score": 95.0,
        "match_type": "exact",
    }


class TestMatchAndSyncPlaylist:
    @patch("djsupport.service.match_track", return_value=_make_match())
    @patch("djsupport.service.incremental_update_playlist", return_value=("pid1", "created", {"added": 1}))
    def test_basic_match_and_sync(self, mock_update, mock_match):
        sp = MagicMock()
        report = match_and_sync_playlist(
            [_make_track()], "Test", "/path",
            sp=sp, cache=None, state_mgr=None,
            existing_playlists={}, threshold=80,
            dry_run=False, incremental=True, prefix=None,
        )
        assert len(report.matched) == 1
        assert report.matched[0].spotify_name == "Song"
        assert report.action == "created"
        assert report.spotify_playlist_id == "pid1"

    @patch("djsupport.service.match_track", return_value=None)
    def test_unmatched_track(self, mock_match):
        sp = MagicMock()
        report = match_and_sync_playlist(
            [_make_track()], "Test", "/path",
            sp=sp, cache=None, state_mgr=None,
            existing_playlists={}, threshold=80,
            dry_run=True, incremental=True, prefix=None,
        )
        assert len(report.unmatched) == 1
        assert len(report.matched) == 0

    @patch("djsupport.service.match_track", return_value=_make_match())
    def test_dry_run_skips_playlist_creation(self, mock_match):
        sp = MagicMock()
        report = match_and_sync_playlist(
            [_make_track()], "Test", "/path",
            sp=sp, cache=None, state_mgr=None,
            existing_playlists={}, threshold=80,
            dry_run=True, incremental=True, prefix=None,
        )
        assert report.action == "dry-run"
        assert report.spotify_playlist_id is None

    @patch("djsupport.service.match_track", return_value=_make_match())
    @patch("djsupport.service.incremental_update_playlist", return_value=("pid1", "created", {"added": 1}))
    def test_progress_callback_fires(self, mock_update, mock_match):
        sp = MagicMock()
        events = []
        match_and_sync_playlist(
            [_make_track(), _make_track(track_id="2")], "Test", "/path",
            sp=sp, cache=None, state_mgr=None,
            existing_playlists={}, threshold=80,
            dry_run=False, incremental=True, prefix=None,
            on_progress=events.append,
        )
        matching_events = [e for e in events if e.phase == "matching"]
        assert len(matching_events) == 2
        assert matching_events[0].current == 1
        assert matching_events[1].current == 2
        syncing_events = [e for e in events if e.phase == "syncing"]
        assert len(syncing_events) == 1

    @patch("djsupport.service.match_track", side_effect=[_make_match("spotify:track:a"), _make_match("spotify:track:a")])
    @patch("djsupport.service.incremental_update_playlist", return_value=("pid1", "created", {"added": 1}))
    def test_deduplicates_uris(self, mock_update, mock_match):
        sp = MagicMock()
        report = match_and_sync_playlist(
            [_make_track(track_id="1"), _make_track(track_id="2")], "Test", "/path",
            sp=sp, cache=None, state_mgr=None,
            existing_playlists={}, threshold=80,
            dry_run=False, incremental=True, prefix=None,
        )
        # Both tracks matched, but same URI deduplicated in playlist
        assert len(report.matched) == 2
        call_args = mock_update.call_args
        uris = call_args[0][2]  # third positional arg is matched_uris
        assert len(uris) == 1

    @patch("djsupport.service.match_track_cached")
    @patch("djsupport.service.incremental_update_playlist", return_value=("pid1", "updated", {"added": 0}))
    def test_cache_hits_tracked(self, mock_update, mock_cached):
        mock_cached.return_value = (_make_match(), "cache")
        sp = MagicMock()
        cache = MagicMock()
        report = match_and_sync_playlist(
            [_make_track()], "Test", "/path",
            sp=sp, cache=cache, state_mgr=None,
            existing_playlists={}, threshold=80,
            dry_run=False, incremental=True, prefix=None,
        )
        assert report.cache_hits == 1
        assert report.api_lookups == 0


class TestSyncBeatportChart:
    @patch("djsupport.service.get_user_playlists", return_value={})
    @patch("djsupport.service.match_and_sync_playlist")
    @patch("djsupport.beatport.fetch_chart")
    @patch("djsupport.beatport.validate_url", return_value="https://www.beatport.com/chart/test/123")
    def test_chart_sync_flow(self, mock_validate, mock_fetch, mock_sync, mock_playlists):
        from djsupport.report import PlaylistReport
        mock_fetch.return_value = ("Test Chart", "DJ", [_make_track()])
        mock_sync.return_value = PlaylistReport(name="Test Chart", path="url")
        sp = MagicMock()
        events = []
        report = sync_beatport_chart(
            "https://www.beatport.com/chart/test/123",
            sp=sp, cache=None, state_mgr=MagicMock(),
            on_progress=events.append,
        )
        assert len(report.playlists) == 1
        fetching = [e for e in events if e.phase == "fetching"]
        assert len(fetching) >= 1
        complete = [e for e in events if e.phase == "complete"]
        assert len(complete) == 1

    @patch("djsupport.beatport.fetch_chart", return_value=("Empty", "DJ", []))
    @patch("djsupport.beatport.validate_url", return_value="https://www.beatport.com/chart/test/123")
    def test_empty_chart(self, mock_validate, mock_fetch):
        sp = MagicMock()
        report = sync_beatport_chart(
            "https://www.beatport.com/chart/test/123",
            sp=sp, cache=None, state_mgr=MagicMock(),
        )
        assert len(report.playlists) == 1
        assert report.playlists[0].total == 0


class TestSyncBeatportLabel:
    @patch("djsupport.service.get_user_playlists", return_value={})
    @patch("djsupport.service.match_and_sync_playlist")
    @patch("djsupport.label.deduplicate_tracks", return_value=([_make_track()], 0))
    @patch("djsupport.label.fetch_label_tracks", return_value=("Test Label", [_make_track()]))
    @patch("djsupport.label.validate_label_url", return_value="https://www.beatport.com/label/test/1")
    def test_label_sync_flow(self, mock_validate, mock_fetch, mock_dedup, mock_sync, mock_playlists):
        from djsupport.report import PlaylistReport
        mock_sync.return_value = PlaylistReport(name="Test Label", path="url")
        sp = MagicMock()
        events = []
        report = sync_beatport_label(
            "https://www.beatport.com/label/test/1",
            sp=sp, cache=None, state_mgr=MagicMock(),
            on_progress=events.append,
        )
        assert len(report.playlists) == 1
        complete = [e for e in events if e.phase == "complete"]
        assert len(complete) == 1

    @patch("djsupport.label.fetch_label_tracks", return_value=("Empty Label", []))
    @patch("djsupport.label.validate_label_url", return_value="https://www.beatport.com/label/test/1")
    def test_empty_label(self, mock_validate, mock_fetch):
        sp = MagicMock()
        report = sync_beatport_label(
            "https://www.beatport.com/label/test/1",
            sp=sp, cache=None, state_mgr=MagicMock(),
        )
        assert len(report.playlists) == 1
        assert report.playlists[0].total == 0
