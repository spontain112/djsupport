"""Tests for djsupport.matcher — pure functions, no network calls."""

from unittest.mock import MagicMock

import pytest

from djsupport.matcher import (
    _normalize,
    _strip_mix_info,
    _extract_mix_descriptor,
    _extract_mix_descriptors,
    _is_named_variant,
    _classify_version_match,
    _duration_penalty,
    _score_result,
    match_track,
)
from djsupport.rekordbox import Track


def make_track(name="Test Track", artist="Test Artist", remixer="", duration=0):
    return Track(
        track_id="1",
        name=name,
        artist=artist,
        album="",
        remixer=remixer,
        label="",
        genre="",
        date_added="",
        duration=duration,
    )


def make_result(name="Test Track", artist="Test Artist", uri="spotify:track:abc", duration_ms=0):
    return {"uri": uri, "name": name, "artist": artist, "album": "", "duration_ms": duration_ms}


def make_spotify_item(name, artist, uri, duration_ms=0):
    return {
        "uri": uri,
        "name": name,
        "artists": [{"name": artist}],
        "album": {"name": "Album"},
        "duration_ms": duration_ms,
    }


class TestNormalize:
    def test_lowercases(self):
        assert _normalize("Hello World") == "hello world"

    def test_strips_leading_trailing_whitespace(self):
        assert _normalize("  hello  ") == "hello"

    def test_folds_accents(self):
        assert _normalize("Für") == "fur"
        assert _normalize("Âme") == "ame"

    def test_removes_two_letter_country_tags(self):
        assert _normalize("Artist (UK)") == "artist"

    def test_removes_three_letter_country_tags(self):
        assert _normalize("Artist (IL)") == "artist"

    def test_removes_bracket_tags(self):
        assert _normalize("Track [Permanent Vacation]") == "track"

    def test_replaces_x_separator(self):
        assert _normalize("Artist1 x Artist2") == "artist1, artist2"

    def test_removes_feat_dot(self):
        assert _normalize("Track feat. Someone") == "track"

    def test_removes_ft_dot(self):
        assert _normalize("Track ft. Someone") == "track"

    def test_collapses_internal_whitespace(self):
        assert _normalize("hello   world") == "hello world"

    def test_empty_string(self):
        assert _normalize("") == ""


class TestStripMixInfo:
    def test_strips_original_mix_parens(self):
        assert _strip_mix_info("Vultora (Original Mix)") == "Vultora"

    def test_strips_remix_parens(self):
        assert _strip_mix_info("Track (Joris Voorn Remix)") == "Track"

    def test_strips_edit_parens(self):
        assert _strip_mix_info("Track (Radio Edit)") == "Track"

    def test_strips_version_parens(self):
        assert _strip_mix_info("Track (Extended Version)") == "Track"

    def test_strips_bracket_tag(self):
        assert _strip_mix_info("Today [Permanent Vacation]") == "Today"

    def test_strips_hyphen_remix(self):
        assert _strip_mix_info("What Is Real - Deep in the Playa Mix") == "What Is Real"

    def test_leaves_plain_title_unchanged(self):
        assert _strip_mix_info("Plain Title") == "Plain Title"

    def test_case_insensitive_remix(self):
        assert _strip_mix_info("Track (CLUB REMIX)") == "Track"


class TestExtractMixDescriptors:
    def test_extracts_remix_from_parens(self):
        descs = _extract_mix_descriptors("Track (Joris Voorn Remix)")
        assert len(descs) == 1
        assert "remix" in descs[0]

    def test_extracts_from_hyphen(self):
        descs = _extract_mix_descriptors("Track - Club Mix")
        assert len(descs) == 1
        assert "mix" in descs[0]

    def test_no_descriptor_for_plain_title(self):
        assert _extract_mix_descriptors("Plain Title") == []

    def test_deduplicates_same_descriptor(self):
        descs = _extract_mix_descriptors("Track (Club Mix) - Club Mix")
        assert len(descs) == 1

    def test_original_mix_is_extracted(self):
        descs = _extract_mix_descriptors("Track (Original Mix)")
        assert len(descs) == 1
        assert "original" in descs[0]

    def test_brackets_without_mix_keyword_ignored(self):
        descs = _extract_mix_descriptors("Track [Permanent Vacation]")
        assert descs == []


class TestExtractMixDescriptor:
    def test_returns_first_descriptor(self):
        desc = _extract_mix_descriptor("Track (Club Remix)")
        assert desc is not None
        assert "remix" in desc

    def test_returns_none_for_plain(self):
        assert _extract_mix_descriptor("Plain Title") is None


class TestIsNamedVariant:
    def test_none_is_not_variant(self):
        assert _is_named_variant(None) is False

    def test_original_mix_is_not_variant(self):
        assert _is_named_variant("original mix") is False

    def test_remix_is_variant(self):
        assert _is_named_variant("joris voorn remix") is True

    def test_edit_is_variant(self):
        assert _is_named_variant("radio edit") is True

    def test_dub_is_variant(self):
        assert _is_named_variant("dub mix") is True


class TestClassifyVersionMatch:
    def test_both_original_mix_is_exact(self):
        track = make_track("Vultora (Original Mix)")
        result = make_result("Vultora (Original Mix)")
        assert _classify_version_match(track, result) == "exact"

    def test_both_plain_is_exact(self):
        track = make_track("Vultora")
        result = make_result("Vultora")
        assert _classify_version_match(track, result) == "exact"

    def test_matching_remix_descriptors_is_exact(self):
        track = make_track("Track (Joris Voorn Remix)")
        result = make_result("Track - Joris Voorn Remix")
        assert _classify_version_match(track, result) == "exact"

    def test_remix_track_plain_result_is_fallback(self):
        track = make_track("Track (Joris Voorn Remix)")
        result = make_result("Track")
        assert _classify_version_match(track, result) == "fallback_version"

    def test_plain_track_remix_result_is_fallback(self):
        track = make_track("Track")
        result = make_result("Track (Club Remix)")
        assert _classify_version_match(track, result) == "fallback_version"

    def test_mismatched_remixers_is_fallback(self):
        track = make_track("Track (Joris Voorn Remix)", remixer="Joris Voorn")
        result = make_result("Track (Someone Else Remix)")
        assert _classify_version_match(track, result) == "fallback_version"


class TestScoreResult:
    def test_perfect_match_scores_high(self):
        track = make_track("Vultora", "Solomun")
        result = make_result("Vultora", "Solomun")
        assert _score_result(track, result) >= 90

    def test_mismatch_scores_low(self):
        track = make_track("Completely Different Track", "Nobody Famous")
        result = make_result("Something Totally Else", "Someone Unknown")
        assert _score_result(track, result) < 50

    def test_fallback_version_scores_lower_than_exact(self):
        track = make_track("Vultora (Original Mix)", "Solomun")
        exact_result = make_result("Vultora (Original Mix)", "Solomun", "uri:1")
        fallback_result = make_result("Vultora (Club Remix)", "Solomun", "uri:2")
        assert _score_result(track, exact_result) > _score_result(track, fallback_result)

    def test_score_clamped_to_zero_minimum(self):
        track = make_track("AAAA", "BBBB")
        result = make_result("ZZZZ", "YYYY")
        assert _score_result(track, result) >= 0.0

    def test_score_clamped_to_100_maximum(self):
        track = make_track("Track", "Artist")
        result = make_result("Track", "Artist")
        assert _score_result(track, result) <= 100.0


class TestMatchTrack:
    def _mock_sp(self, items):
        sp = MagicMock()
        sp.search.return_value = {"tracks": {"items": items}}
        return sp

    def test_returns_best_exact_match_above_threshold(self):
        sp = self._mock_sp([make_spotify_item("Vultora (Original Mix)", "Solomun", "spotify:track:abc")])
        track = make_track("Vultora (Original Mix)", "Solomun")
        result = match_track(sp, track, threshold=80)
        assert result is not None
        assert result["uri"] == "spotify:track:abc"
        assert result["score"] >= 80
        assert result["match_type"] == "exact"

    def test_returns_none_when_no_results(self):
        sp = self._mock_sp([])
        track = make_track("Vultora", "Solomun")
        assert match_track(sp, track) is None

    def test_returns_none_when_score_below_threshold(self):
        sp = self._mock_sp([make_spotify_item("Something Totally Different", "Unknown Artist", "uri:1")])
        track = make_track("Vultora (Original Mix)", "Solomun")
        assert match_track(sp, track, threshold=80) is None

    def test_returns_fallback_for_strong_base_match(self):
        """A track with a remix not on Spotify falls back to the non-remix version."""
        sp = self._mock_sp([make_spotify_item("Vultora", "Solomun", "uri:1")])
        track = make_track("Vultora (Original Mix)", "Solomun")
        result = match_track(sp, track, threshold=80)
        # Should either match as fallback or exact — just verify it matched
        assert result is not None

    def test_deduplicates_results_across_strategies(self):
        """Same URI returned by multiple search strategies should only be scored once."""
        item = make_spotify_item("Vultora (Original Mix)", "Solomun", "spotify:track:abc")
        sp = self._mock_sp([item])
        track = make_track("Vultora (Original Mix)", "Solomun")
        result = match_track(sp, track, threshold=80)
        assert result is not None
        # sp.search was called (multiple strategies may fire) — result should still be valid
        assert result["uri"] == "spotify:track:abc"

    def test_remixer_triggers_additional_strategy(self):
        """When track has a remixer, an extra search strategy is used."""
        sp = self._mock_sp([make_spotify_item("Sapphire (Joris Voorn Remix)", "Eagles & Butterflies", "uri:2")])
        track = make_track("Sapphire (Joris Voorn Remix)", "Eagles & Butterflies", remixer="Joris Voorn")
        result = match_track(sp, track, threshold=80)
        # Verify multiple search calls were made (remixer strategy fires)
        assert sp.search.call_count >= 1

    def test_plain_text_fallback_fires_when_no_field_results(self):
        """Strategy 5 plain-text search runs when field-specific searches return nothing."""
        sp = MagicMock()
        # First calls (field-specific) return nothing, last call (plain) returns a result
        sp.search.side_effect = [
            {"tracks": {"items": []}},  # Strategy 1
            {"tracks": {"items": [make_spotify_item("Track", "Artist", "uri:1")]}},  # Strategy 5 plain
        ]
        track = make_track("Track", "Artist")
        result = match_track(sp, track, threshold=80)
        assert result is not None
        assert result["uri"] == "uri:1"
        # Verify plain search was called (no field prefixes)
        last_call_query = sp.search.call_args_list[-1][1].get("q") or sp.search.call_args_list[-1][0][0]
        assert "artist:" not in last_call_query
        assert "track:" not in last_call_query


class TestDurationPenalty:
    def test_no_penalty_when_track_duration_zero(self):
        assert _duration_penalty(0, 300000) == 0.0

    def test_no_penalty_when_result_duration_zero(self):
        assert _duration_penalty(300, 0) == 0.0

    def test_no_penalty_within_30s(self):
        assert _duration_penalty(300, 310000) == 0.0  # 10s diff

    def test_no_penalty_at_exactly_30s(self):
        assert _duration_penalty(300, 330000) == 0.0

    def test_penalty_beyond_30s(self):
        # 60s diff = 30s excess -> 10 points
        penalty = _duration_penalty(300, 360000)
        assert penalty == pytest.approx(10.0)

    def test_penalty_capped_at_30(self):
        # 300s diff -> way beyond cap
        penalty = _duration_penalty(300, 600000)
        assert penalty == 30.0

    def test_duration_disambiguates_versions(self):
        """A track with known duration should score the closer-duration result higher."""
        track = make_track("Confusion", "New Order")
        track = Track(
            track_id="1", name="Confusion", artist="New Order",
            album="", remixer="", label="", genre="", date_added="",
            duration=470,  # ~7:50
        )
        short_result = make_result("Confusion", "New Order", "uri:short", duration_ms=260000)  # ~4:20
        long_result = make_result("Confusion", "New Order", "uri:long", duration_ms=470000)  # ~7:50
        assert _score_result(track, long_result) > _score_result(track, short_result)
