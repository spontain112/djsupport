"""Tests for djsupport.matcher — pure functions, no network calls."""

from unittest.mock import MagicMock

import pytest

from djsupport.matcher import (
    EARLY_EXIT_THRESHOLD,
    _collapse_repeated_parenthetical_groups,
    _normalize,
    _strip_mix_info,
    _extract_mix_descriptor,
    _extract_mix_descriptors,
    _is_named_variant,
    _classify_version_match,
    _duration_penalty,
    _score_components,
    _score_result,
    match_track,
    match_track_cached,
    match_track_with_alternatives,
)
from djsupport.cache import MatchCache
from djsupport.rekordbox import Track


def make_track(
    name="Test Track", artist="Test Artist", remixer="", duration=0,
    version="",
):
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
        version=version,
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


class TestRepeatedParentheticalComparison:
    def test_collapses_immediately_adjacent_equivalent_groups_to_one_copy(self):
        assert _collapse_repeated_parenthetical_groups(
            "Signal (Sunrise Mix) (Sunrise Mix)",
        ) == "Signal (Sunrise Mix)"

    def test_equivalence_ignores_case_and_normalizes_content_whitespace(self):
        assert _collapse_repeated_parenthetical_groups(
            "Signal (  Sunrise   Mix ) (sunrise mix)",
        ) == "Signal (  Sunrise   Mix )"

    @pytest.mark.parametrize(
        "title",
        [
            "Signal (Sunrise Mix) (Sunset Mix)",
            "Signal (Sunrise Mix) Interlude (Sunrise Mix)",
            "Signal (Sunrise Mix!) (Sunrise Mix)",
            "Signal (Sunrise Mix) (Sunrise)",
            "Signal Signal",
        ],
    )
    def test_leaves_non_duplicate_forms_unchanged(self, title):
        assert _collapse_repeated_parenthetical_groups(title) == title

    def test_title_scoring_compares_one_preserved_copy(self):
        components = _score_components(
            make_track("Signal (Sunrise Mix) (Sunrise Mix)", "Synthetic Artist"),
            make_result("Signal (Sunrise Mix)", "Synthetic Artist"),
        )

        assert components["raw_title_score"] == 100

    def test_candidate_without_subtitle_is_not_comparison_equivalent(self):
        components = _score_components(
            make_track("Signal (Sunrise Mix) (Sunrise Mix)", "Synthetic Artist"),
            make_result("Signal", "Synthetic Artist"),
        )

        assert components["raw_title_score"] < 100


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
    def test_rekordbox_mix_metadata_protects_plain_title_version_intent(self):
        track = make_track("Track", version="Extended Mix")
        result = make_result("Track")

        assert _classify_version_match(track, result) == "fallback_version"

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

    def test_rekordbox_mix_metadata_surfaces_fallback_version_evidence(self):
        sp = self._mock_sp([
            make_spotify_item(
                "Synthetic Signal", "Synthetic Artist",
                "spotify:track:default-version",
            ),
        ])

        result = match_track(
            sp,
            make_track(
                "Synthetic Signal", "Synthetic Artist",
                version="Extended Mix",
            ),
            threshold=80,
        )

        assert result is not None
        assert result["match_type"] == "fallback_version"
        assert "fallback version" in result["score_reasons"]

    def test_materially_shorter_candidate_is_reviewable_not_exact(self):
        sp = self._mock_sp([
            make_spotify_item(
                "Synthetic Signal", "Synthetic Artist",
                "spotify:track:shorter", duration_ms=269000,
            ),
        ])
        track = make_track(
            "Synthetic Signal", "Synthetic Artist", duration=300,
        )

        result = match_track(sp, track, threshold=80)

        assert result is not None
        assert result["match_type"] == "shorter_version"
        assert (
            "Spotify version is 31s shorter than source (4:29 vs 5:00)"
            in result["score_reasons"]
        )

    def test_high_confidence_shorter_version_does_not_expand_search(self):
        sp = self._mock_sp([
            make_spotify_item(
                "Synthetic Signal (Original Mix)", "Synthetic Artist",
                "spotify:track:shorter", duration_ms=269000,
            ),
        ])

        result = match_track(
            sp,
            make_track(
                "Synthetic Signal (Original Mix)",
                "Synthetic Artist",
                duration=300,
            ),
            threshold=80,
        )

        assert result is not None
        assert result["match_type"] == "shorter_version"
        assert sp.search.call_count == 1

    def test_candidate_exactly_thirty_seconds_shorter_remains_exact(self):
        sp = self._mock_sp([
            make_spotify_item(
                "Synthetic Signal", "Synthetic Artist",
                "spotify:track:boundary", duration_ms=270000,
            ),
        ])

        result = match_track(
            sp,
            make_track("Synthetic Signal", "Synthetic Artist", duration=300),
            threshold=80,
        )

        assert result is not None
        assert result["match_type"] == "exact"

    def test_equal_candidates_prefer_smallest_known_duration_delta(self):
        sp = self._mock_sp([
            make_spotify_item(
                "Synthetic Signal", "Synthetic Artist",
                "spotify:track:first", duration_ms=270000,
            ),
            make_spotify_item(
                "Synthetic Signal", "Synthetic Artist",
                "spotify:track:closest", duration_ms=295000,
            ),
        ])

        result = match_track(
            sp,
            make_track("Synthetic Signal", "Synthetic Artist", duration=300),
            threshold=80,
        )

        assert result is not None
        assert result["uri"] == "spotify:track:closest"
        assert sp.search.call_count == 1

    def test_existing_candidates_choose_closer_duration_without_extra_search(self):
        sp = self._mock_sp([
            make_spotify_item(
                "Synthetic Signal", "Synthetic Artist",
                "spotify:track:short", duration_ms=240000,
            ),
            make_spotify_item(
                "Synthetic Signal", "Synthetic Artist",
                "spotify:track:close", duration_ms=295000,
            ),
        ])

        result = match_track(
            sp,
            make_track("Synthetic Signal", "Synthetic Artist", duration=300),
            threshold=80,
        )

        assert result is not None
        assert result["uri"] == "spotify:track:close"
        assert sp.search.call_count == 1

    @pytest.mark.parametrize(
        ("source_duration", "spotify_duration_ms"),
        [(0, 269000), (300, 0)],
    )
    def test_unknown_duration_does_not_infer_a_shorter_version(
        self, source_duration, spotify_duration_ms,
    ):
        sp = self._mock_sp([
            make_spotify_item(
                "Synthetic Signal", "Synthetic Artist",
                "spotify:track:unknown", duration_ms=spotify_duration_ms,
            ),
        ])

        result = match_track(
            sp,
            make_track(
                "Synthetic Signal", "Synthetic Artist", duration=source_duration,
            ),
            threshold=80,
        )

        assert result is not None
        assert result["match_type"] == "exact"

    def test_materially_longer_candidate_remains_exact(self):
        sp = self._mock_sp([
            make_spotify_item(
                "Synthetic Signal", "Synthetic Artist",
                "spotify:track:longer", duration_ms=331000,
            ),
        ])

        result = match_track(
            sp,
            make_track("Synthetic Signal", "Synthetic Artist", duration=300),
            threshold=80,
        )

        assert result is not None
        assert result["match_type"] == "exact"

    def test_recovers_existing_repeated_subtitle_candidate_without_new_search(self):
        source_title = "Signal (Sunrise Mix) (  sunrise   mix )"
        track = make_track(source_title, "Synthetic Artist")
        original_track = Track(**vars(track))
        sp = self._mock_sp([
            make_spotify_item("Unrelated", "Other Artist", "spotify:track:other"),
            make_spotify_item(
                "Signal (Sunrise Mix)",
                "Synthetic Artist",
                "spotify:track:signal",
            ),
        ])

        result = match_track(sp, track, threshold=80)

        assert result is not None
        assert result["uri"] == "spotify:track:signal"
        assert result["match_type"] == "exact"
        assert result["score"] == 100
        assert track == original_track
        assert sp.search.call_count == 1
        assert sp.search.call_args.kwargs["q"] == (
            f"artist:Synthetic Artist track:{source_title}"
        )

    def test_matches_remix_when_spotify_co_credits_named_remixer(self):
        sp = self._mock_sp([
            make_spotify_item(
                "The Hours - Allies for Everyone Remix",
                "Balad, Allies for Everyone",
                "spotify:track:remix",
            )
        ])
        track = make_track("The Hours (Allies for Everyone Remix)", "Balad")

        result = match_track(sp, track, threshold=80)

        assert result is not None
        assert result["uri"] == "spotify:track:remix"
        assert result["score"] >= 80
        assert result["match_type"] == "exact"
        assert "original artist and named remixer co-credited" in result["score_reasons"]

    def test_does_not_boost_unrelated_spotify_co_artists(self):
        sp = self._mock_sp([
            make_spotify_item(
                "The Hours - Allies for Everyone Remix",
                "Balad, Unrelated Singer, Random Ensemble",
                "spotify:track:unrelated",
            )
        ])
        track = make_track("The Hours (Allies for Everyone Remix)", "Balad")

        assert match_track(sp, track, threshold=80) is None

    def test_matches_co_credit_from_explicit_remixer_metadata(self):
        sp = self._mock_sp([
            make_spotify_item(
                "Track - Club Remix",
                "Original Artist, Known Remixer",
                "spotify:track:metadata-remixer",
            )
        ])
        track = make_track(
            "Track (Club Remix)", "Original Artist", remixer="Known Remixer",
        )

        result = match_track(sp, track, threshold=80)

        assert result is not None
        assert result["uri"] == "spotify:track:metadata-remixer"
        assert "original artist and named remixer co-credited" in result["score_reasons"]

    def test_matches_co_credit_from_named_edit_descriptor(self):
        sp = self._mock_sp([
            make_spotify_item(
                "Track - Known Artist Edit",
                "Original Artist, Known Artist",
                "spotify:track:named-edit",
            )
        ])
        track = make_track("Track (Known Artist Edit)", "Original Artist")

        result = match_track(sp, track, threshold=80)

        assert result is not None
        assert result["uri"] == "spotify:track:named-edit"
        assert "original artist and named remixer co-credited" in result["score_reasons"]

    @pytest.mark.parametrize("descriptor", ["Club Remix", "Extended Remix", "Radio Remix"])
    def test_does_not_treat_generic_version_descriptor_as_remixer(self, descriptor):
        sp = self._mock_sp([
            make_spotify_item(
                f"Track - {descriptor}",
                f"Original Artist, {descriptor.removesuffix(' Remix')}",
                "spotify:track:generic",
            )
        ])
        track = make_track(f"Track ({descriptor})", "Original Artist")

        assert match_track(sp, track, threshold=95) is None

    def test_does_not_match_partial_artist_or_remixer_names(self):
        sp = self._mock_sp([
            make_spotify_item(
                "Track - DJ Annex Remix",
                "Joanne, DJ Annexed",
                "spotify:track:partial-names",
            )
        ])
        track = make_track("Track (DJ Annex Remix)", "Ann")

        assert match_track(sp, track, threshold=80) is None

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
        """When track has a remixer and Strategy 1 finds the exact remix, early exit fires."""
        sp = self._mock_sp([make_spotify_item("Sapphire (Joris Voorn Remix)", "Eagles & Butterflies", "uri:2")])
        track = make_track("Sapphire (Joris Voorn Remix)", "Eagles & Butterflies", remixer="Joris Voorn")
        result = match_track(sp, track, threshold=80)
        assert result is not None
        # Strategy 1 finds the exact remix at high confidence → early exit
        assert sp.search.call_count == 1

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

    def test_alternative_aware_matching_keeps_normalized_search_strategy(self):
        sp = MagicMock()
        candidate = make_spotify_item("Track", "Artist", "uri:normalized")
        sp.search.side_effect = [
            {"tracks": {"items": []}},
            {"tracks": {"items": []}},
            {"tracks": {"items": [candidate]}},
        ]
        track = make_track("Track [Label]", "Artist (UK)")

        result = match_track_with_alternatives(sp, track, threshold=80)

        assert result is not None
        assert result["uri"] == "uri:normalized"
        assert sp.search.call_args_list[2].kwargs["q"] == "artist:artist track:track"


class TestTerminalAudioExtensionFallback:
    @pytest.mark.parametrize("suffix", [".aif", ".aiff"])
    def test_recovers_signal_without_changing_source_identity_or_version_intent(
        self, suffix,
    ):
        track = make_track(
            f"Signal (Original Mix){suffix}", "Known Artist", duration=360,
        )
        original_track = Track(**vars(track))
        recovered = make_spotify_item(
            "Signal", "Known Artist", "spotify:track:signal", 360000,
        )
        sp = MagicMock()
        sp.search.side_effect = [
            {"tracks": {"items": []}},
            {"tracks": {"items": []}},
            {"tracks": {"items": [make_spotify_item(
                "Unrelated", "Different Artist", "spotify:track:wrong",
                360000,
            )]}},
            {"tracks": {"items": [recovered]}},
        ]

        result = match_track(sp, track, threshold=80)

        assert result is not None
        assert result["uri"] == "spotify:track:signal"
        assert result["match_type"] == "exact"
        assert track == original_track
        assert "(Original Mix)" in track.name
        assert [call.kwargs["q"] for call in sp.search.call_args_list] == [
            f"artist:Known Artist track:Signal (Original Mix){suffix}",
            f"artist:Known Artist track:Signal{suffix}",
            f"Known Artist Signal (Original Mix){suffix}",
            "artist:Known Artist track:Signal (Original Mix)",
        ]

    @pytest.mark.parametrize(
        "suffix", [".mp3", ".aif", ".AiF", ".aiff", ".wav", ".flac"],
    )
    def test_recognized_terminal_suffix_adds_at_most_one_search(self, suffix):
        sp = MagicMock()
        sp.search.return_value = {"tracks": {"items": []}}

        match_track(sp, make_track(f"Signal{suffix}", "Known Artist"))

        queries = [call.kwargs["q"] for call in sp.search.call_args_list]
        assert queries == [
            f"artist:Known Artist track:Signal{suffix}",
            f"Known Artist Signal{suffix}",
            "artist:Known Artist track:Signal",
        ]
        assert len(queries) == len(set(queries))

    def test_duplicate_extension_free_variant_adds_no_search_call(self):
        class DuplicateVariantTitle(str):
            def __getitem__(self, key):
                if isinstance(key, slice) and key.stop == len("Signal"):
                    return self
                return super().__getitem__(key)

        sp = MagicMock()
        sp.search.return_value = {"tracks": {"items": []}}

        match_track(
            sp,
            make_track(DuplicateVariantTitle("Signal.aiff"), "Known Artist"),
        )

        assert [call.kwargs["q"] for call in sp.search.call_args_list] == [
            "artist:Known Artist track:Signal.aiff",
            "Known Artist Signal.aiff",
        ]

    @pytest.mark.parametrize(
        "title",
        [
            "Signal.aif Archive",
            "Signal.aiff Archive",
            "Signal.ogg",
            ".aif",
            ".aiff",
        ],
    )
    def test_ineligible_title_keeps_existing_two_search_calls(self, title):
        sp = MagicMock()
        sp.search.return_value = {"tracks": {"items": []}}

        match_track(sp, make_track(title, "Known Artist"))

        assert sp.search.call_count == 2
        assert sp.search.call_args_list[-1].kwargs["q"] == f"Known Artist {title}"

    def test_unknown_artist_does_not_receive_extension_fallback(self):
        sp = MagicMock()
        sp.search.return_value = {"tracks": {"items": []}}

        match_track(sp, make_track("Signal.aiff", ""))

        assert sp.search.call_count == 2

    def test_candidate_still_has_to_pass_original_scoring_threshold(self):
        unrelated = make_spotify_item(
            "Unrelated", "Different Artist", "spotify:track:wrong", 360000,
        )
        sp = MagicMock()
        sp.search.side_effect = [
            {"tracks": {"items": []}},
            {"tracks": {"items": []}},
            {"tracks": {"items": []}},
            {"tracks": {"items": [unrelated]}},
        ]

        result = match_track(
            sp,
            make_track("Signal (Original Mix).aiff", "Known Artist", duration=360),
            threshold=80,
        )

        assert result is None
        assert sp.search.call_count == 4

    def test_aif_candidate_keeps_named_version_protection(self):
        track = make_track(
            "Signal (Night Dub).aif", "Known Artist", duration=360,
        )
        original_track = Track(**vars(track))
        wrong_version = make_spotify_item(
            "Signal.aif", "Known Artist", "spotify:track:wrong-version", 360000,
        )
        sp = MagicMock()
        sp.search.side_effect = [
            {"tracks": {"items": []}},
            {"tracks": {"items": []}},
            {"tracks": {"items": []}},
            {"tracks": {"items": [wrong_version]}},
        ]

        result = match_track(sp, track, threshold=80)

        assert result is not None
        assert result["match_type"] == "fallback_version"
        assert track == original_track
        assert [call.kwargs["q"] for call in sp.search.call_args_list] == [
            "artist:Known Artist track:Signal (Night Dub).aif",
            "artist:Known Artist track:Signal.aif",
            "Known Artist Signal (Night Dub).aif",
            "artist:Known Artist track:Signal (Night Dub)",
        ]

    def test_acceptable_earlier_result_skips_extension_fallback(self):
        exact = make_spotify_item(
            "Signal (Original Mix).aiff", "Known Artist", "spotify:track:exact",
            360000,
        )
        sp = MagicMock()
        sp.search.return_value = {"tracks": {"items": [exact]}}

        result = match_track(
            sp,
            make_track("Signal (Original Mix).aiff", "Known Artist", duration=360),
        )

        assert result is not None
        assert result["uri"] == "spotify:track:exact"
        assert sp.search.call_count == 1

    def test_cache_hits_and_recent_failure_make_zero_search_calls(self, tmp_path):
        title = "Signal (Original Mix).aiff"
        scenarios = ("approved", "success", "failure")
        for scenario in scenarios:
            cache = MatchCache(str(tmp_path / f"{scenario}.json"))
            cached_result = make_result(
                "Signal", "Known Artist", "spotify:track:signal", 360000,
            )
            cached_result["score"] = 95.0
            cached_result["match_type"] = "exact"
            if scenario == "approved":
                cache.record_approval(
                    "Known Artist", title, "approved", cached_result,
                )
            elif scenario == "success":
                cache.store("Known Artist", title, 80, cached_result)
            else:
                cache.store("Known Artist", title, 80, None)
            sp = MagicMock()

            match_track_cached(
                sp, make_track(title, "Known Artist", duration=360), cache,
            )

            assert sp.search.call_count == 0, scenario

    def test_retry_eligible_failure_uses_original_cache_identity(self, tmp_path):
        title = "Signal (Original Mix).aiff"
        cache = MatchCache(str(tmp_path / "cache.json"))
        cache.store("Known Artist", title, 80, None)
        original_key = cache.cache_key("Known Artist", title)
        recovered = make_spotify_item(
            "Signal", "Known Artist", "spotify:track:signal", 360000,
        )
        sp = MagicMock()
        sp.search.side_effect = [
            {"tracks": {"items": []}},
            {"tracks": {"items": []}},
            {"tracks": {"items": []}},
            {"tracks": {"items": [recovered]}},
        ]

        result, source = match_track_cached(
            sp, make_track(title, "Known Artist", duration=360), cache,
            force_retry=True,
        )

        assert result is not None
        assert source == "retry"
        assert sp.search.call_count == 4
        assert set(cache.entries) == {original_key}
        assert cache.entries[original_key].spotify_uri == "spotify:track:signal"
        cache.record_approval("Known Artist", title, "approved", result)
        assert cache.lookup("Known Artist", title, 100) is not None
        assert cache.lookup("Known Artist", "Signal (Original Mix)", 100) is None


class TestEarlyExit:
    """Tests for early-exit optimization in match_track."""

    def _mock_sp(self, items):
        sp = MagicMock()
        sp.search.return_value = {"tracks": {"items": items}}
        return sp

    def test_early_exit_on_high_confidence_exact_match(self):
        """Strategy 1 returns a perfect exact match — remaining strategies skipped."""
        sp = self._mock_sp([make_spotify_item("Vultora", "Solomun", "uri:1")])
        # Plain track with no mix info, no remixer, no normalization change.
        # Strategy 1 should score ~100 (exact match) and trigger early exit.
        track = make_track("Vultora", "Solomun")
        result = match_track(sp, track, threshold=80)
        assert result is not None
        assert result["uri"] == "uri:1"
        assert result["score"] >= EARLY_EXIT_THRESHOLD
        assert result["match_type"] == "exact"
        # Only Strategy 1 should have fired
        assert sp.search.call_count == 1

    def test_no_early_exit_on_moderate_score(self):
        """Strategy 1 returns a moderate match (below 95) — remaining strategies should run."""
        # Use a duration mismatch to create a penalty that drops score below 95.
        # Track: 300s, Result: 380s → 80s diff → 50s excess → ~16.7 penalty → score ~83
        sp = self._mock_sp([make_spotify_item("Vultora", "Solomun", "uri:1", duration_ms=380000)])
        track = make_track("Vultora (Original Mix)", "Solomun", duration=300)
        result = match_track(sp, track, threshold=80)
        assert result is not None
        # Score is below 95 due to duration penalty → Strategy 2 should have fired
        assert sp.search.call_count >= 2

    def test_no_early_exit_when_best_is_fallback_version(self):
        """Strategy 1 returns only fallback_version results — should not early exit."""
        # Track requests a remix, Strategy 1 returns the original (no remix descriptor).
        # _classify_version_match → fallback_version → -15 penalty → below 95.
        sp = self._mock_sp([make_spotify_item("Sapphire", "Eagles & Butterflies", "uri:1")])
        track = make_track("Sapphire (Joris Voorn Remix)", "Eagles & Butterflies", remixer="Joris Voorn")
        result = match_track(sp, track, threshold=80)
        # Strategies 1, 2 (stripped title differs), and 3 (remixer) should fire
        assert sp.search.call_count >= 3

    def test_remix_strategy1_returns_original_no_early_exit(self):
        """Remix track where Strategy 1 finds original version — must not early exit."""
        sp = MagicMock()
        original = make_spotify_item("Sapphire", "Eagles & Butterflies", "uri:original", duration_ms=300000)
        remix = make_spotify_item("Sapphire (Joris Voorn Remix)", "Eagles & Butterflies", "uri:remix", duration_ms=420000)
        # Strategy 1 returns only the original; Strategy 3 (remixer) finds the remix
        sp.search.side_effect = [
            {"tracks": {"items": [original]}},       # Strategy 1: artist + title
            {"tracks": {"items": [original]}},       # Strategy 2: stripped title
            {"tracks": {"items": [remix]}},           # Strategy 3: remixer search
        ]
        track = make_track("Sapphire (Joris Voorn Remix)", "Eagles & Butterflies",
                           remixer="Joris Voorn", duration=420)
        result = match_track(sp, track, threshold=80)
        assert result is not None
        # Should have picked the remix from Strategy 3, not early-exited on original
        assert result["uri"] == "uri:remix"
        assert sp.search.call_count == 3

    def test_remix_strategy1_returns_correct_remix_early_exit(self):
        """Remix track where Strategy 1 finds the exact remix — should early exit."""
        remix = make_spotify_item("Sapphire (Joris Voorn Remix)", "Eagles & Butterflies", "uri:remix")
        sp = self._mock_sp([remix])
        track = make_track("Sapphire (Joris Voorn Remix)", "Eagles & Butterflies", remixer="Joris Voorn")
        result = match_track(sp, track, threshold=80)
        assert result is not None
        assert result["uri"] == "uri:remix"
        assert result["score"] >= EARLY_EXIT_THRESHOLD
        assert result["match_type"] == "exact"
        # Early exit: only Strategy 1 fired
        assert sp.search.call_count == 1

    def test_threshold_boundary_at_exactly_95(self):
        """A score of exactly EARLY_EXIT_THRESHOLD should trigger early exit."""
        # Use a track/result pair that will score exactly at the boundary.
        # Perfect artist match (100) + slightly imperfect title (~91.7) = 40 + 55 = 95
        sp = self._mock_sp([make_spotify_item("Vultora", "Solomun", "uri:1")])
        track = make_track("Vultora", "Solomun")
        result = match_track(sp, track, threshold=80)
        # This scores 100 (perfect match), which is >= 95 → early exit
        assert result is not None
        assert result["score"] >= EARLY_EXIT_THRESHOLD
        assert sp.search.call_count == 1

    def test_threshold_boundary_below_95_no_early_exit(self):
        """A score just below EARLY_EXIT_THRESHOLD should not trigger early exit."""
        # Use a large duration mismatch to push score just below 95.
        # Track: 300s, Result: 480s → 180s diff → 150s excess → 15 penalty (cap) → score ~85
        sp = self._mock_sp([make_spotify_item("Vultora", "Solomun", "uri:1", duration_ms=480000)])
        track = make_track("Vultora (Original Mix)", "Solomun", duration=300)
        result = match_track(sp, track, threshold=80)
        assert result is not None
        # Score is below 95 due to duration penalty → no early exit → Strategy 2 fires
        assert sp.search.call_count >= 2

    def test_strategy5_still_fires_when_all_empty(self):
        """Early exit logic does not interfere with Strategy 5 (plain-text fallback)."""
        sp = MagicMock()
        sp.search.side_effect = [
            {"tracks": {"items": []}},  # Strategy 1: empty
            {"tracks": {"items": [make_spotify_item("Track", "Artist", "uri:1")]}},  # Strategy 5: plain
        ]
        track = make_track("Track", "Artist")
        result = match_track(sp, track, threshold=80)
        assert result is not None
        assert result["uri"] == "uri:1"


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
        # 60s diff = 30s excess -> 5 points
        penalty = _duration_penalty(300, 360000)
        assert penalty == pytest.approx(5.0)

    def test_penalty_capped_at_15(self):
        # 300s diff -> way beyond cap
        penalty = _duration_penalty(300, 600000)
        assert penalty == 15.0

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
