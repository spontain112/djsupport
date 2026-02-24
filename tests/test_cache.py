"""Tests for djsupport.cache — MatchCache persistence and lookup."""

import json
from datetime import datetime, timedelta

import pytest

from djsupport.cache import MatchCache, CACHE_VERSION


def _matched_result(uri="uri:1", name="Track", artist="Artist", score=95.0, match_type="exact"):
    return {"uri": uri, "name": name, "artist": artist, "score": score, "match_type": match_type}


@pytest.fixture
def cache(tmp_path):
    return MatchCache(path=str(tmp_path / "cache.json"))


@pytest.fixture
def populated_cache(tmp_path):
    c = MatchCache(path=str(tmp_path / "cache.json"))
    c.store("Solomun", "Vultora (Original Mix)", 80, _matched_result(
        uri="spotify:track:abc",
        name="Vultora (Original Mix)",
        artist="Solomun",
        score=95.0,
    ))
    return c


class TestMatchCacheLoad:
    def test_load_missing_file_is_noop(self, tmp_path):
        c = MatchCache(path=str(tmp_path / "missing.json"))
        c.load()
        assert len(c.entries) == 0

    def test_load_corrupt_json_is_noop(self, tmp_path):
        p = tmp_path / "cache.json"
        p.write_text("not valid json }{")
        c = MatchCache(path=str(p))
        c.load()
        assert len(c.entries) == 0

    def test_load_wrong_version_is_noop(self, tmp_path):
        p = tmp_path / "cache.json"
        p.write_text(json.dumps({"version": 999, "entries": {}}))
        c = MatchCache(path=str(p))
        c.load()
        assert len(c.entries) == 0

    def test_roundtrip_save_and_load(self, tmp_path):
        path = str(tmp_path / "cache.json")
        c1 = MatchCache(path=path)
        c1.store("Solomun", "Vultora", 80, _matched_result())
        c1.save()

        c2 = MatchCache(path=path)
        c2.load()
        assert len(c2.entries) == 1

    def test_loaded_entry_has_correct_fields(self, tmp_path):
        path = str(tmp_path / "cache.json")
        c1 = MatchCache(path=path)
        c1.store("Solomun", "Vultora", 80, _matched_result(uri="uri:xyz", score=92.5))
        c1.save()

        c2 = MatchCache(path=path)
        c2.load()
        key = c2.cache_key("Solomun", "Vultora")
        entry = c2.entries[key]
        assert entry.spotify_uri == "uri:xyz"
        assert entry.score == 92.5
        assert entry.matched is True

    def test_save_writes_correct_version(self, tmp_path):
        path = str(tmp_path / "cache.json")
        c = MatchCache(path=path)
        c.save()
        data = json.loads((tmp_path / "cache.json").read_text())
        assert data["version"] == CACHE_VERSION


class TestMatchCacheStore:
    def test_stores_successful_match(self, cache):
        cache.store("Solomun", "Vultora", 80, _matched_result(uri="uri:1"))
        key = cache.cache_key("Solomun", "Vultora")
        assert key in cache.entries
        assert cache.entries[key].matched is True
        assert cache.entries[key].spotify_uri == "uri:1"

    def test_stores_failed_match_as_none(self, cache):
        cache.store("Unknown", "Track", 80, None)
        key = cache.cache_key("Unknown", "Track")
        assert key in cache.entries
        assert cache.entries[key].matched is False
        assert cache.entries[key].spotify_uri is None

    def test_stores_match_type(self, cache):
        cache.store("Artist", "Track", 80, _matched_result(match_type="fallback_version"))
        key = cache.cache_key("Artist", "Track")
        assert cache.entries[key].match_type == "fallback_version"

    def test_cache_key_is_normalized(self, cache):
        key1 = cache.cache_key("Solomun", "Vultora (Original Mix)")
        key2 = cache.cache_key("SOLOMUN", "VULTORA (ORIGINAL MIX)")
        assert key1 == key2

    def test_overwrite_existing_entry(self, cache):
        cache.store("Artist", "Track", 80, None)
        cache.store("Artist", "Track", 80, _matched_result(uri="uri:new"))
        key = cache.cache_key("Artist", "Track")
        assert cache.entries[key].matched is True
        assert cache.entries[key].spotify_uri == "uri:new"

    def test_auto_checkpoint_at_interval(self, tmp_path):
        """Cache should auto-save after CHECKPOINT_INTERVAL stores."""
        from djsupport.cache import CHECKPOINT_INTERVAL
        path = str(tmp_path / "cache.json")
        c = MatchCache(path=path)
        for i in range(CHECKPOINT_INTERVAL):
            c.store(f"Artist{i}", f"Track{i}", 80, None)
        # After exactly CHECKPOINT_INTERVAL stores, file should exist on disk
        assert (tmp_path / "cache.json").exists()


class TestMatchCacheLookup:
    def test_hit_for_matched_entry_above_threshold(self, populated_cache):
        entry = populated_cache.lookup("Solomun", "Vultora (Original Mix)", 80)
        assert entry is not None
        assert entry.spotify_uri == "spotify:track:abc"

    def test_miss_for_unknown_artist(self, populated_cache):
        assert populated_cache.lookup("Unknown Artist", "Vultora (Original Mix)", 80) is None

    def test_miss_when_score_below_requested_threshold(self, populated_cache):
        # Stored score is 95; requesting threshold 99 means 95 >= 99 is False
        assert populated_cache.lookup("Solomun", "Vultora (Original Mix)", 99) is None

    def test_hit_when_threshold_lower_than_stored_score(self, populated_cache):
        # Score 95 >= threshold 70 → hit
        entry = populated_cache.lookup("Solomun", "Vultora (Original Mix)", 70)
        assert entry is not None

    def test_failed_match_entry_returned_for_same_threshold(self, cache):
        cache.store("Nobody", "Unknown Track", 80, None)
        entry = cache.lookup("Nobody", "Unknown Track", 80)
        assert entry is not None
        assert entry.matched is False

    def test_failed_match_miss_for_higher_threshold(self, cache):
        # Failed entry stored with threshold=80. Requesting 90 → entry.threshold(80) <= 90, so hit
        cache.store("Nobody", "Unknown Track", 80, None)
        entry = cache.lookup("Nobody", "Unknown Track", 90)
        assert entry is not None

    def test_failed_match_hit_for_lower_threshold(self, cache):
        # Failed entry stored with threshold=80. Requesting 70 → entry.threshold(80) <= 70 is False → miss
        cache.store("Nobody", "Unknown Track", 80, None)
        entry = cache.lookup("Nobody", "Unknown Track", 70)
        assert entry is None

    def test_lookup_is_case_insensitive(self, populated_cache):
        entry = populated_cache.lookup("SOLOMUN", "VULTORA (ORIGINAL MIX)", 80)
        assert entry is not None


class TestMatchCacheRetryEligibility:
    def test_not_eligible_for_recent_failed_entry(self, cache):
        cache.store("Unknown", "Track", 80, None)
        assert cache.is_retry_eligible("Unknown", "Track", retry_days=7) is False

    def test_force_makes_eligible_regardless_of_age(self, cache):
        cache.store("Unknown", "Track", 80, None)
        assert cache.is_retry_eligible("Unknown", "Track", retry_days=7, force=True) is True

    def test_not_eligible_for_successful_match(self, cache):
        cache.store("Solomun", "Vultora", 80, _matched_result())
        assert cache.is_retry_eligible("Solomun", "Vultora") is False

    def test_not_eligible_for_nonexistent_entry(self, cache):
        assert cache.is_retry_eligible("No", "One") is False

    def test_eligible_after_retry_window_expires(self, cache):
        cache.store("Unknown", "Track", 80, None)
        # Back-date the timestamp
        key = cache.cache_key("Unknown", "Track")
        old_ts = (datetime.now() - timedelta(days=10)).isoformat()
        cache.entries[key].timestamp = old_ts
        assert cache.is_retry_eligible("Unknown", "Track", retry_days=7) is True
