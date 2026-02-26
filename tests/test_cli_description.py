"""Tests for playlist description threading in CLI sync."""

from unittest.mock import MagicMock, patch

from djsupport.cli import _match_and_sync_playlist
from djsupport.rekordbox import Track


def _make_track(artist="Artist", name="Song"):
    return Track(
        track_id="1", name=name, artist=artist,
        album="Album", remixer="", label="", genre="", date_added="",
    )


def _make_match_result():
    return {
        "uri": "spotify:track:abc",
        "name": "Song",
        "artist": "Artist",
        "score": 95,
        "match_type": "exact",
    }


class TestMatchAndSyncDescription:
    @patch("djsupport.cli.incremental_update_playlist", return_value=("pl_id", "created", {"added": 1, "removed": 0, "unchanged": 0}))
    @patch("djsupport.cli.match_track", return_value=_make_match_result())
    def test_rekordbox_description(self, _match, mock_sync):
        sp = MagicMock()
        _match_and_sync_playlist(
            [_make_track()], "My Playlist", "/path",
            sp=sp, cache=None, state_mgr=None,
            existing_playlists={}, threshold=80,
            dry_run=False, incremental=True, prefix=None,
            source_type="rekordbox",
        )
        mock_sync.assert_called_once()
        assert mock_sync.call_args.kwargs["description"] == "Synced from Rekordbox by djsupport"

    @patch("djsupport.cli.incremental_update_playlist", return_value=("pl_id", "created", {"added": 1, "removed": 0, "unchanged": 0}))
    @patch("djsupport.cli.match_track", return_value=_make_match_result())
    def test_beatport_description(self, _match, mock_sync):
        sp = MagicMock()
        _match_and_sync_playlist(
            [_make_track()], "My Chart", "https://beatport.com/chart/1",
            sp=sp, cache=None, state_mgr=None,
            existing_playlists={}, threshold=80,
            dry_run=False, incremental=True, prefix=None,
            source_type="beatport",
        )
        mock_sync.assert_called_once()
        assert mock_sync.call_args.kwargs["description"] == "Imported from Beatport by djsupport"

    @patch("djsupport.cli.create_or_update_playlist", return_value=("pl_id", "created"))
    @patch("djsupport.cli.match_track", return_value=_make_match_result())
    def test_non_incremental_passes_description(self, _match, mock_sync):
        sp = MagicMock()
        _match_and_sync_playlist(
            [_make_track()], "My Playlist", "/path",
            sp=sp, cache=None, state_mgr=None,
            existing_playlists={}, threshold=80,
            dry_run=False, incremental=False, prefix=None,
            source_type="rekordbox",
        )
        mock_sync.assert_called_once()
        assert mock_sync.call_args.kwargs["description"] == "Synced from Rekordbox by djsupport"

    @patch("djsupport.cli.match_track", return_value=_make_match_result())
    def test_dry_run_skips_description(self, _match):
        sp = MagicMock()
        report = _match_and_sync_playlist(
            [_make_track()], "My Playlist", "/path",
            sp=sp, cache=None, state_mgr=None,
            existing_playlists={}, threshold=80,
            dry_run=True, incremental=True, prefix=None,
            source_type="rekordbox",
        )
        assert report.action == "dry-run"
