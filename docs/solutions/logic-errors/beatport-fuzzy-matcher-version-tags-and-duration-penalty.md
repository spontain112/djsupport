---
title: Beatport chart import matching failures from standalone version tags and aggressive duration penalty
date: 2026-02-26
category: logic-errors
severity: high
module: matcher.py
tags:
  - beatport
  - fuzzy-matching
  - version-tags
  - duration-penalty
  - track-scoring
  - multi-source
symptoms: |
  Beatport chart import had 22% match failure rate (63/81 tracks).
  Tracks with standalone version tags like (Extended) returned 0 Spotify results.
  Tracks with large duration differences (DJ extended 5-7min vs radio edit 3-4min)
  scored below 80 threshold despite perfect artist+title matches.
root_cause: |
  1. _strip_mix_info regex only recognized "mix|remix|edit|version|dub" but not
     "extended|radio|instrumental|short", so bare (Extended) was passed to Spotify
     search as-is, yielding 0 results.
  2. Duration penalty (10pts/30s, capped at 30) was too aggressive for Beatport's
     extended DJ versions vs Spotify's radio edits.
status: resolved
---

# Beatport Fuzzy Matcher: Version Tags and Duration Penalty

## Problem

During real-world testing of a Beatport chart import (81 tracks, "Best New Melodic H&T: February 2026"), the match rate was only 77.8% (63/81). Investigation revealed two separate issues in `djsupport/matcher.py`.

### Issue 1: Standalone Version Tags Not Stripped from Search Queries

**Symptom**: Tracks like "Niki Sadeki - Night Drive (Extended)" returned 0 Spotify results.

**Investigation**:
- `search_track(sp, "Niki Sadeki", "Night Drive (Extended)")` sent query `artist:Niki Sadeki track:Night Drive (Extended)` to Spotify API -> 0 results
- `search_track(sp, "Niki Sadeki", "Night Drive")` -> found the track immediately with score 80.0
- Strategy 2 in `match_track` strips mix info via `_strip_mix_info` before searching, but the regex only matched parentheticals containing "mix|remix|edit|version|dub"
- Beatport commonly uses bare `(Extended)` without "Mix" appended -- this pattern wasn't recognized, so Strategy 2 never fired

**Root cause**: `_strip_mix_info` and `_extract_mix_descriptors` regexes did not include "extended|radio|instrumental|short" in their alternation.

### Issue 2: Duration Penalty Rejecting Valid Matches

**Symptom**: Gumm - "Who Got?" and Fahlberg - "It's All Good" both found on Spotify with perfect artist+title scores, but rejected for falling below the 80-point threshold.

**Investigation**:
- Gumm: Beatport 326s (5:26), Spotify 217s (3:37). Diff: 109s. Penalty: 26.3. Score: 73.7.
- Fahlberg: Beatport 444s (7:24), Spotify 290s (4:50). Diff: 154s. Penalty: 30.0 (capped). Score: 70.0.
- Both classified as `match_type="exact"` (no version tags on either side), so they only went through the first pass in `_select_best` where `exact_score >= threshold` was required
- The penalty was designed for Rekordbox where durations are accurate. Beatport tracks are almost always extended DJ versions; Spotify often only has shorter radio edits.

**Root cause**: Duration penalty formula (10pts per 30s excess, capped at 30) allowed duration alone to reject an otherwise perfect match.

## Solution

### Fix 1: Expand Version Tag Recognition

Added "extended|radio|instrumental|short" to both version-related regex patterns in `matcher.py`:

```python
# _strip_mix_info: broadened alternation
title = re.sub(
    r"\s*\(.*?(mix|remix|edit|version|dub|extended|radio|instrumental|short)\)",
    "", title, flags=re.IGNORECASE,
)

# _extract_mix_descriptors: same expansion for version classification
if re.search(
    r"\b(mix|remix|edit|version|dub|extended|radio|instrumental|short)\b",
    c, flags=re.IGNORECASE,
):
```

This ensures Strategy 2 strips `(Extended)` from search queries (broadening recall) while `_extract_mix_descriptors` correctly classifies it as a version tag for scoring.

### Fix 2: Reduce Duration Penalty

Changed `_duration_penalty` from 10pts/30s (cap 30) to 5pts/30s (cap 15):

```python
def _duration_penalty(track_duration_s: int, result_duration_ms: int) -> float:
    if track_duration_s <= 0 or result_duration_ms <= 0:
        return 0.0
    result_duration_s = result_duration_ms / 1000
    diff = abs(track_duration_s - result_duration_s)
    if diff <= 30:
        return 0.0
    excess = diff - 30
    return min(15.0, (excess / 30) * 5)  # was min(30.0, (excess / 30) * 10)
```

Duration still informs scoring (disambiguates radio vs. extended when both exist) but cannot single-handedly sink an otherwise perfect match below threshold.

## Results

Applied sequentially on the same 81-track chart:

| Stage | Matched | Rate |
|-------|---------|------|
| Baseline | 63/81 | 77.8% |
| After Fix 1 (version tags) | 67/81 | 82.7% |
| After Fix 2 (duration penalty) | 79/81 | 97.5% |

The 2 remaining unmatched tracks are genuinely not available on Spotify.

## Key Insight: Search Queries vs. Scoring

This bug illustrates the importance of separating **search breadth** from **scoring precision**:

- **Search queries** should be broad -- strip version tags to maximize recall from Spotify's API
- **Scoring** should be precise -- penalize mismatches to rank candidates, but never so aggressively that a single factor rejects an otherwise perfect match
- **Threshold** is the final gate -- penalties should push wrong matches below it, not push right matches below it

When adding a new source, both the query generation and scoring logic must be tested against that source's metadata conventions.

## Prevention

### When Adding a New Source

1. **Audit version tags**: Sample 10-15 tracks and extract all parenthetical/bracket tags. Add any new patterns to `_strip_mix_info` and `_extract_mix_descriptors`.
2. **Check duration distributions**: Compare source durations against Spotify results. If the source skews toward extended versions, verify the duration penalty doesn't reject valid matches.
3. **Run a test batch**: Import a real chart with `--dry-run` and check the unmatched list before tuning.

### Testing Strategy

- Test fixtures should include tracks from each integrated source
- Add regression tests: identical track with different version tags should produce comparable scores
- Validate that no single penalty factor can drop a perfect artist+title match below threshold

## Related Documentation

- [Early exit optimization](../performance-issues/spotify-api-calls-early-exit-optimization.md) -- Established the double-penalty safety layer (version -15 + duration -30). This fix adjusted the duration component.
- [Duplicate URI deduplication](./duplicate-spotify-uris-in-playlists-CLI-20260225.md) -- Related sync logic for many-to-one track mapping.
- [Spotify rate limit handling](../integration-issues/spotify-rate-limit-handling.md) -- Context for why reducing API calls via better matching matters.
- [Beatport feature plan](../../plans/2026-02-26-feat-beatport-chart-import-plan.md) -- Full implementation plan including ISRC as future Strategy 0.

## Files Modified

- `djsupport/matcher.py`: `_strip_mix_info()`, `_extract_mix_descriptors()`, `_duration_penalty()`
- `tests/test_matcher.py`: Updated duration penalty test expectations
