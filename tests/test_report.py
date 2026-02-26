"""Tests for djsupport.report — dataclasses and computed properties."""

from datetime import datetime
from io import StringIO
from unittest.mock import patch

import pytest

from djsupport.report import MatchedTrack, PlaylistReport, SyncReport, save_report


def _matched(name="Track A", spotify_name="Track A", artist="Artist", score=95.0, match_type="exact"):
    return MatchedTrack(
        source_name=name,
        spotify_name=spotify_name,
        spotify_artist=artist,
        score=score,
        match_type=match_type,
    )


def _playlist(name="Test", path="Test", matched=(), unmatched=()):
    pl = PlaylistReport(name=name, path=path)
    pl.matched.extend(matched)
    pl.unmatched.extend(unmatched)
    return pl


def _report(playlists=(), threshold=80, dry_run=True, cache_enabled=False):
    r = SyncReport(timestamp=datetime(2024, 3, 15, 12, 0), threshold=threshold, dry_run=dry_run)
    r.playlists.extend(playlists)
    r.cache_enabled = cache_enabled
    return r


class TestMatchedTrack:
    def test_default_match_type_is_exact(self):
        m = MatchedTrack(source_name="A", spotify_name="A", spotify_artist="X", score=90.0)
        assert m.match_type == "exact"

    def test_fallback_match_type(self):
        m = MatchedTrack(
            source_name="A", spotify_name="A (Remix)", spotify_artist="X",
            score=85.0, match_type="fallback_version",
        )
        assert m.match_type == "fallback_version"


class TestPlaylistReport:
    def test_total_is_zero_when_empty(self):
        pl = PlaylistReport(name="PL", path="PL")
        assert pl.total == 0

    def test_total_counts_matched_and_unmatched(self):
        pl = _playlist(matched=[_matched()], unmatched=["B", "C"])
        assert pl.total == 3

    def test_match_rate_zero_when_empty(self):
        pl = PlaylistReport(name="PL", path="PL")
        assert pl.match_rate == 0.0

    def test_match_rate_100_when_all_matched(self):
        pl = _playlist(matched=[_matched(), _matched(name="B")])
        assert pl.match_rate == 100.0

    def test_match_rate_50_when_half_matched(self):
        pl = _playlist(matched=[_matched()], unmatched=["B"])
        assert pl.match_rate == 50.0

    def test_match_rate_zero_when_all_unmatched(self):
        pl = _playlist(unmatched=["A", "B"])
        assert pl.match_rate == 0.0

    def test_default_action_is_dry_run(self):
        pl = PlaylistReport(name="PL", path="PL")
        assert pl.action == "dry-run"


class TestSyncReport:
    def test_total_matched_zero_when_no_playlists(self):
        r = _report()
        assert r.total_matched == 0

    def test_total_unmatched_zero_when_no_playlists(self):
        r = _report()
        assert r.total_unmatched == 0

    def test_total_matched_sums_across_playlists(self):
        pl1 = _playlist(matched=[_matched(), _matched(name="B")])
        pl2 = _playlist(matched=[_matched(name="C")])
        r = _report(playlists=[pl1, pl2])
        assert r.total_matched == 3

    def test_total_unmatched_sums_across_playlists(self):
        pl1 = _playlist(unmatched=["X", "Y"])
        pl2 = _playlist(unmatched=["Z"])
        r = _report(playlists=[pl1, pl2])
        assert r.total_unmatched == 3

    def test_overall_match_rate_zero_when_empty(self):
        assert _report().overall_match_rate == 0.0

    def test_overall_match_rate_100_all_matched(self):
        pl = _playlist(matched=[_matched(), _matched(name="B")])
        r = _report(playlists=[pl])
        assert r.overall_match_rate == 100.0

    def test_overall_match_rate_50(self):
        pl = _playlist(matched=[_matched()], unmatched=["B"])
        r = _report(playlists=[pl])
        assert r.overall_match_rate == 50.0


class TestSaveReport:
    def test_creates_file(self, tmp_path):
        path = str(tmp_path / "report.md")
        r = _report(playlists=[_playlist(matched=[_matched()], unmatched=["B"])])
        save_report(r, path)
        assert (tmp_path / "report.md").exists()

    def test_file_contains_timestamp(self, tmp_path):
        path = str(tmp_path / "report.md")
        r = _report()
        save_report(r, path)
        content = (tmp_path / "report.md").read_text()
        assert "2024-03-15" in content

    def test_file_contains_threshold(self, tmp_path):
        path = str(tmp_path / "report.md")
        r = _report(threshold=85)
        save_report(r, path)
        content = (tmp_path / "report.md").read_text()
        assert "85" in content

    def test_file_contains_playlist_name(self, tmp_path):
        path = str(tmp_path / "report.md")
        pl = _playlist(name="Peak Time", path="My Playlists/Peak Time", matched=[_matched()])
        r = _report(playlists=[pl])
        save_report(r, path)
        content = (tmp_path / "report.md").read_text()
        assert "Peak Time" in content

    def test_file_contains_unmatched_tracks(self, tmp_path):
        path = str(tmp_path / "report.md")
        pl = _playlist(unmatched=["Obscure Track"])
        r = _report(playlists=[pl])
        save_report(r, path)
        content = (tmp_path / "report.md").read_text()
        assert "Obscure Track" in content

    def test_dry_run_mode_label(self, tmp_path):
        path = str(tmp_path / "report.md")
        save_report(_report(dry_run=True), path)
        content = (tmp_path / "report.md").read_text()
        assert "dry-run" in content

    def test_live_mode_label(self, tmp_path):
        path = str(tmp_path / "report.md")
        save_report(_report(dry_run=False), path)
        content = (tmp_path / "report.md").read_text()
        assert "live" in content

    def test_low_confidence_section_appears(self, tmp_path):
        path = str(tmp_path / "report.md")
        pl = _playlist(matched=[_matched(score=85.0, match_type="fallback_version")])
        r = _report(playlists=[pl])
        save_report(r, path)
        content = (tmp_path / "report.md").read_text()
        assert "Low Confidence" in content

    def test_no_low_confidence_section_for_high_scores(self, tmp_path):
        path = str(tmp_path / "report.md")
        pl = _playlist(matched=[_matched(score=95.0, match_type="exact")])
        r = _report(playlists=[pl])
        save_report(r, path)
        content = (tmp_path / "report.md").read_text()
        assert "Low Confidence" not in content
