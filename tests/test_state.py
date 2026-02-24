"""Tests for djsupport.state — PlaylistStateManager."""

import json
from pathlib import Path

import pytest

from djsupport.state import PlaylistStateManager, PlaylistState, STATE_VERSION


@pytest.fixture
def state_mgr(tmp_path):
    return PlaylistStateManager(path=str(tmp_path / "state.json"))


@pytest.fixture
def sample_state():
    return PlaylistState(
        spotify_id="playlist:abc123",
        spotify_name="djsupport / Peak Time",
        rekordbox_path="My Playlists/Peak Time",
        last_synced="2024-01-15T12:00:00",
        prefix_used="djsupport",
    )


class TestPlaylistStateManager:
    def test_empty_on_init(self, state_mgr):
        assert state_mgr.is_empty() is True

    def test_get_nonexistent_returns_none(self, state_mgr):
        assert state_mgr.get("Nonexistent Playlist") is None

    def test_set_and_get(self, state_mgr, sample_state):
        state_mgr.set("Peak Time", sample_state)
        retrieved = state_mgr.get("Peak Time")
        assert retrieved is not None
        assert retrieved.spotify_id == "playlist:abc123"

    def test_not_empty_after_set(self, state_mgr, sample_state):
        state_mgr.set("Peak Time", sample_state)
        assert state_mgr.is_empty() is False

    def test_overwrite_existing_entry(self, state_mgr, sample_state):
        state_mgr.set("Peak Time", sample_state)
        updated = PlaylistState(
            spotify_id="playlist:newid",
            spotify_name="djsupport / Peak Time",
            rekordbox_path="My Playlists/Peak Time",
            last_synced="2024-06-01T10:00:00",
            prefix_used="djsupport",
        )
        state_mgr.set("Peak Time", updated)
        assert state_mgr.get("Peak Time").spotify_id == "playlist:newid"

    def test_save_and_load_roundtrip(self, tmp_path, sample_state):
        path = str(tmp_path / "state.json")

        m1 = PlaylistStateManager(path=path)
        m1.set("Peak Time", sample_state)
        m1.save()

        m2 = PlaylistStateManager(path=path)
        m2.load()
        state = m2.get("Peak Time")
        assert state is not None
        assert state.spotify_id == "playlist:abc123"
        assert state.spotify_name == "djsupport / Peak Time"
        assert state.prefix_used == "djsupport"

    def test_saved_file_has_correct_version(self, tmp_path, sample_state):
        path = tmp_path / "state.json"
        m = PlaylistStateManager(path=str(path))
        m.set("Peak Time", sample_state)
        m.save()
        data = json.loads(path.read_text())
        assert data["version"] == STATE_VERSION

    def test_load_nonexistent_file_is_noop(self, state_mgr):
        state_mgr.load()
        assert state_mgr.is_empty()

    def test_load_corrupt_json_is_noop(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text("}{not valid json")
        m = PlaylistStateManager(path=str(p))
        m.load()
        assert m.is_empty()

    def test_load_wrong_version_is_noop(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text(json.dumps({"version": 999, "entries": {}}))
        m = PlaylistStateManager(path=str(p))
        m.load()
        assert m.is_empty()

    def test_multiple_playlists(self, state_mgr):
        s1 = PlaylistState(
            spotify_id="id:1", spotify_name="PL1", rekordbox_path="PL1",
            last_synced="2024-01-01T00:00:00", prefix_used=None,
        )
        s2 = PlaylistState(
            spotify_id="id:2", spotify_name="PL2", rekordbox_path="PL2",
            last_synced="2024-01-02T00:00:00", prefix_used=None,
        )
        state_mgr.set("PL1", s1)
        state_mgr.set("PL2", s2)
        assert state_mgr.get("PL1").spotify_id == "id:1"
        assert state_mgr.get("PL2").spotify_id == "id:2"

    def test_prefix_used_none_preserved(self, tmp_path):
        path = str(tmp_path / "state.json")
        m1 = PlaylistStateManager(path=path)
        m1.set("PL", PlaylistState(
            spotify_id="id:1", spotify_name="PL", rekordbox_path="PL",
            last_synced="2024-01-01T00:00:00", prefix_used=None,
        ))
        m1.save()
        m2 = PlaylistStateManager(path=path)
        m2.load()
        assert m2.get("PL").prefix_used is None
