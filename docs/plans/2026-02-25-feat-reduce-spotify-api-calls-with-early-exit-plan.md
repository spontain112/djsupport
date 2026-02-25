---
title: "feat: Reduce Spotify API calls with early exit in match_track"
type: feat
status: completed
date: 2026-02-25
---

# feat: Reduce Spotify API calls with early exit in match_track

## Overview

Reduce Spotify API call volume by short-circuiting `match_track()` when an early search strategy returns a high-confidence exact match. Currently, every track triggers 2-5 sequential Spotify search API calls regardless of result quality. For large libraries (1000+ tracks), this leads to rate limiting (HTTP 429) and sync aborts. The optimization targets the common case where Strategy 1 already finds the correct track.

## Problem Statement / Motivation

`match_track()` (`matcher.py:173-244`) runs up to 5 search strategies sequentially:

| Strategy | Condition | Query |
|---|---|---|
| 1: artist + title | Always | `artist:X track:Y` |
| 2: stripped title | Title has mix/remix info | `artist:X track:Y_stripped` |
| 3: include remixer | Track has remixer field | `artist:X remixer track:Y` |
| 4: normalized names | Normalization changes strings | `artist:X_clean track:Y_clean` |
| 5: plain-text fallback | All previous returned empty | `X Y` (no field prefixes) |

**All conditional strategies fire even when Strategy 1 returns a perfect match.** For a typical DJ library with remixes and special characters, the average is ~3-5 API calls per track. A 1000-track initial sync makes 3000-5000 Spotify API calls, frequently triggering rate limits.

The [rate limit solution doc](../solutions/integration-issues/spotify-rate-limit-handling.md) already identifies this as the primary future optimization:

> "Future optimization: Early exit in `match_track` when strategy 1 finds a high-confidence match could reduce API calls by 40-60%."

## Proposed Solution

Add a single early-exit check after Strategy 1's results are scored. If the best **exact-version** match scores >= `EARLY_EXIT_THRESHOLD` (95), return immediately and skip Strategies 2-5.

### Why 95?

- At 95+, `_score_result` indicates near-perfect artist + title fuzzy match with minimal penalty
- The -15 penalty for `fallback_version` matches (`matcher.py:163`) means wrong-version results naturally cap at ~85, well below 95 — preventing early exit on version mismatches
- The duration penalty (`_duration_penalty`, up to -30 points) provides a second safety layer — even if version classification misses a mismatch, a significant duration difference (e.g., radio edit vs extended mix) will drop the score well below 95
- Combined worst case: -15 (version) + -30 (duration) = -45 penalty → score ~55 for a wrong version with wrong duration
- Remix tracks where Strategy 1 returns the original version are safely handled: `_classify_version_match` classifies these as `fallback_version`, the -15 penalty drops the score below 95, and Strategies 2-4 still fire
- A score of 92 (e.g., title with "(Original Mix)" vs Spotify's bare title) correctly falls below 95, allowing Strategy 2 to find the exact match

### Design: single check after Strategy 1, not per-strategy re-evaluation

A per-strategy evaluation after each of Strategies 2-4 adds complexity for marginal benefit. Strategy 1 is the most common success case. Keeping the optimization as a single `if` block is simpler to implement, test, and reason about.

### What changes

**`djsupport/matcher.py`:**

1. Add module-level constant `EARLY_EXIT_THRESHOLD = 95`
2. In `match_track()`, after Strategy 1 results are collected (~line 183), score those results and check for an early exit:
   - Score Strategy 1 results using existing `_score_result` and `_classify_version_match`
   - If the best exact-version match scores >= 95, return it immediately
   - Otherwise, continue with Strategies 2-5 as before
3. Refactor the scoring/selection logic (currently at lines 207-244) into a helper function so it can be called both for the early-exit check and the final selection

**No changes to:**
- `spotify.py` — `search_track` and rate limit handling unchanged
- `cache.py` — cache stores whatever `match_track` returns, no format changes
- `cli.py` — sync loop unchanged, `match_track` contract unchanged
- `report.py` — no reporting changes in v1

## Technical Considerations

### Match quality safety — double penalty layer

Two existing penalty mechanisms make the 95 threshold safe:

1. **Version mismatch penalty (-15):** `_classify_version_match` (`matcher.py:101-130`) detects remix/edit descriptor mismatches. Wrong-version results are classified as `fallback_version` and penalized by 15 points.

2. **Duration mismatch penalty (up to -30):** `_duration_penalty` (`matcher.py:133-146`) compares Rekordbox track duration against the Spotify result. Differences >30s are penalized at 10 points per additional 30s, capped at 30 points. This catches version mismatches even when title/artist look identical — e.g., a radio edit (3:30) vs extended mix (7:00) gets a ~25-point penalty.

Both penalties are applied in `_score_result` (`matcher.py:159-166`). For a wrong version, the combined penalty can be -35 to -45 points, dropping the score to ~55-65 — nowhere near the 95 early-exit threshold.

**Example — remix track `"Sapphire (Joris Voorn Remix)"`:**

- If Strategy 1 returns the **original** "Sapphire" (different duration, no remix tag): `fallback_version` (-15) + duration penalty (-10 to -25) → score ~60-75 → well below 95 → **no early exit** → Strategy 3 runs and finds the remix
- If Strategy 1 returns the **correct remix** (matching duration, matching descriptor): `exact` classification → no version penalty → no duration penalty → score ~98 → **early exit** → correct result returned faster

This double-layer validation means a score of 95+ is a very strong signal that both the track identity AND version are correct.

### Tracks that don't benefit

Plain tracks without mix info, remixer, or special characters already make only 1 API call (Strategies 2-4 conditions are false, Strategy 5 is conditional on empty results). The optimization has zero impact on these — and that's fine.

### Cache interaction

The cache key (`artist||title`) and format are unchanged. An early-exit result at score 96 gets cached identically to a full-search result at score 96. The only theoretical difference: a full search might have found a 100-score result from a later strategy. In practice, if Strategy 1 already found a 96+ exact-version match, it's the correct track — later strategies would find the same Spotify track (same URI) or a negligibly different score.

### Strategy 5 preservation

Strategy 5's guard (`if not all_results:`) is unaffected. Early exit only triggers when `all_results` is non-empty AND contains a high-scoring exact match. Strategy 5 fires only when all_results is empty.

## Acceptance Criteria

### Functional

- [x] `match_track()` returns early when Strategy 1 finds an exact-version match scoring >= 95
- [x] `match_track()` runs all strategies as before when Strategy 1 score is < 95
- [x] `match_track()` runs all strategies as before when Strategy 1 only finds fallback_version matches
- [x] Remix/remixer tracks correctly fall through to Strategy 3 when Strategy 1 returns the wrong version
- [x] Strategy 5 (plain-text fallback) still fires when all field-based strategies return empty
- [x] `EARLY_EXIT_THRESHOLD` is a module-level constant in `matcher.py`
- [x] Return value format is unchanged: `dict | None` with `uri`, `name`, `artist`, `score`, `match_type` keys

### Testing

- [x] New test: early exit skips remaining strategies on 98-scoring exact match (assert `sp.search.call_count == 1`)
- [x] New test: no early exit on 88-scoring result (assert `sp.search.call_count > 1`)
- [x] New test: no early exit when best is fallback_version (assert strategies 2+ fire)
- [x] New test: remix track — Strategy 1 returns original → no early exit → Strategy 3 fires
- [x] New test: remix track — Strategy 1 returns correct remix at 97 → early exit
- [x] New test: threshold boundary — score exactly 95.0 triggers early exit
- [x] New test: threshold boundary — score 94.9 does not trigger early exit
- [x] Strengthen existing `test_remixer_triggers_additional_strategy` with exact call count assertion
- [x] All 169 existing tests continue to pass

### Documentation

- [x] Update CHANGELOG.md with the optimization under `### Changed`
- [x] Update rate limit solution doc to mark the "future optimization" as implemented

## Success Metrics

- **API calls per track (first run):** Reduce from ~3-5 average to ~1-2 for libraries where >50% of tracks are common/popular
- **Rate limit incidents:** Fewer 429 errors on initial syncs of 1000+ track libraries
- **Match quality:** Zero regressions — the live accuracy test suite (`tests/test_match_accuracy.py` with 19 ground-truth tracks) should produce identical results before and after

## Dependencies & Risks

**Dependencies:** None — this is a self-contained change to `matcher.py` with new tests.

**Risks:**

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Edge case where early exit caches a worse match | Low | Medium | The -15 fallback_version penalty prevents wrong-version early exits. Add explicit regression tests for remix tracks. |
| Early-exit threshold too aggressive (misses better results) | Low | Low | 95 is conservative. Can be tuned later without API/cache changes. |
| Early-exit threshold too conservative (rarely triggers) | Low | Low | Data from solution doc suggests Strategy 1 frequently returns 95+ for straightforward tracks. |

## Sources & References

- Rate limit solution: `docs/solutions/integration-issues/spotify-rate-limit-handling.md` — identifies this optimization, documents ~18,000 API calls for 3,655 tracks
- ISRC plan: `docs/plans/isrc-mutagen-plan.md` — complementary future optimization (Strategy 0 via ISRC lookup)
- Architectural patterns: `.claude/docs/architectural_patterns.md` — DI conventions, testing patterns
- Existing matcher tests: `tests/test_matcher.py:226-292` — TestMatchTrack class
- Live accuracy suite: `tests/test_match_accuracy.py` — 19 ground-truth tracks for regression testing
