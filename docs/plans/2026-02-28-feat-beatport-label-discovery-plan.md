---
title: Beatport Label Discovery
type: feat
status: active
date: 2026-02-28
---

# Beatport Label Discovery

## Overview

Add a `djsupport label` command that imports tracks from a Beatport record label into a Spotify playlist, sorted by release date (newest first). Supports both direct Beatport label URLs and name-based search with interactive selection.

## Problem Statement / Motivation

DJs frequently follow specific record labels to stay current with new releases. Spotify's app has no label browsing and the API removed the `label` field from album objects in February 2026. Beatport — already integrated into djsupport — has rich label data on every release. This feature bridges that gap: browse by label on Beatport, listen on Spotify.

## Proposed Solution

New module `djsupport/label.py` following the existing `beatport.py` pattern, with a new `label` CLI command. Two input modes:

1. **URL mode**: `djsupport label https://www.beatport.com/label/drumcode/1`
2. **Name mode**: `djsupport label "Drumcode"` — searches Beatport, presents matches for confirmation

Reuses all existing infrastructure: `Track` dataclass, `MatchCache`, `PlaylistStateManager`, `_match_and_sync_playlist()`, `report.py`, and rate limit handling.

## Technical Considerations

### Beatport Label Pages

Label track listings use the same `__NEXT_DATA__` embedded JSON as chart pages, with key differences:

| Aspect | Chart page | Label page |
|--------|-----------|------------|
| URL pattern | `beatport.com/chart/<slug>/<id>` | `beatport.com/label/<slug>/<id>/tracks` |
| Pagination | Single page | Multi-page (`?page=N&per_page=150`, up to 150 per page) |
| Track dates | Not present | `publish_date` field available |
| Track count | 10-50 | Potentially thousands |

### Pagination

Main new complexity vs. the chart scraper. Beatport supports `per_page=150` (max), which reduces HTTP requests significantly (a 500-track label = 4 pages instead of 20).

Approach:
- Fetch page 1 with `?page=1&per_page=150`, extract total count from response metadata
- If >1000 tracks, warn user and prompt for confirmation before fetching remaining pages
- Loop through subsequent pages with progress indicator, collecting tracks
- Handle mid-pagination failures gracefully (return what we have + error message)

### Track Deduplication

Labels often have the same track on multiple releases (original single, compilation, VA album). Deduplicate **before** Spotify matching to avoid wasted API calls:
- Key: normalized `(artist, track_name)` tuple (after stripping mix info)
- Keep the **earliest release** of each track (the original, not the compilation reissue)
- Log duplicates removed count in the report

### Label Name Search

Scrape Beatport search: `https://www.beatport.com/search/labels?q=<name>`
- Parse `__NEXT_DATA__` for label results
- Present top matches with: label name, latest release title, Beatport URL
- User selects via numbered prompt (default: 1)
- Then proceed with the standard URL-based flow

### Spotify API Impact

- Search pagination reduced to max 10 results per page (Feb 2026 change)
- Early exit optimization (score >= 95) already reduces API calls by 40-60%
- Rate limit handling is production-ready (graceful abort + cache save + resume)
- Large labels (500+ tracks) will benefit heavily from caching on re-runs

## Acceptance Criteria

- [x] `djsupport label <url>` imports tracks from a Beatport label page
- [x] `djsupport label "<name>"` searches Beatport and presents interactive selection
- [x] Label search shows label name + latest release as confirmation
- [x] Tracks ordered newest first by release date
- [x] Duplicate tracks across compilations are removed (keep earliest release)
- [x] Warning + confirmation prompt when label has >1000 tracks
- [x] All existing flags supported: `--dry-run`, `--threshold`, `--prefix`, `--no-prefix`, `--report`, `--no-cache`, `--retry`, `--retry-days`, `--cache-path`, `--state-path`, `--incremental`
- [x] Separate cache file (`.djsupport_label_cache.json`) and state file (`.djsupport_label_playlists.json`)
- [x] Playlist description set to Beatport label URL
- [x] Rate limit errors handled gracefully (cache saved, partial report printed)
- [x] CLAUDE.md updated with new command, flags, module, and gitignored files
- [x] CHANGELOG.md updated
- [x] Tests cover URL validation, pagination, track parsing, deduplication, name search

## Success Metrics

- Importing a 100-track label completes without rate limit issues
- Re-running the same label uses cache and completes significantly faster
- Match rate comparable to existing Beatport chart imports (~85%+)
- Duplicate tracks correctly removed (verified via `--dry-run`)

## Implementation Plan

### Phase 1: Label Page Scraping (`djsupport/label.py`)

New module following `beatport.py` patterns:

**URL validation:**
- `BEATPORT_LABEL_PATTERN` regex for `beatport.com/label/<slug>/<id>`
- `validate_label_url(url)` — normalize URL, strip query params, validate format
- Accept both `beatport.com/label/foo/123` and `beatport.com/label/foo/123/tracks`

**Label page fetching:**
- `fetch_label_tracks(url)` → `(label_name: str, tracks: list[Track])`
- Same HTTP approach as `beatport.py`: custom User-Agent, timeout, size limit, anti-bot detection
- Pagination loop: fetch `?page=1&per_page=150`, iterate until all pages fetched
- Return tracks in Beatport's default order (newest first by release date)

**Track parsing:**
- Reuse `_parse_duration()` from `beatport.py` (import or extract to shared util)
- Populate `Track.date_added` with `publish_date` from Beatport
- `Track.track_id` prefixed with `bp-label-` for cache key uniqueness

**Track deduplication:**
- `_deduplicate_tracks(tracks)` — key on normalized `(artist, title)`, keep first occurrence (newest, since list is newest-first)
- Return `(unique_tracks, duplicates_removed_count)`

**Label search:**
- `search_labels(query)` → `list[LabelResult]` where `LabelResult` has `name`, `url`, `latest_release`
- Scrape Beatport search page at `beatport.com/search/labels?q=<query>`
- Parse `__NEXT_DATA__` for label results

### Phase 2: CLI Command (`djsupport/cli.py`)

New `label` command following the `beatport` command pattern:

```
@cli.command()
@click.argument("url_or_name")
@click.option("--dry-run", ...)
@click.option("--threshold", ...)
# ... same options as beatport command
def label(url_or_name, ...):
```

**Input detection:**
- If input looks like a URL (contains `beatport.com/label/`): validate and use directly
- Otherwise: treat as label name, run search, present results, get selection

**Interactive selection (name mode):**
```
Found labels:
  1. Drumcode — latest: "Track Name" (2026-02-15)
     https://www.beatport.com/label/drumcode/1
  2. Drumcode Limited — latest: "Other Track" (2025-11-03)
     https://www.beatport.com/label/drumcode-limited/456

Select label [1]:
```

**Large label warning:**
- After fetching page 1, check total track count
- If >1000: print warning with count, prompt for confirmation
- User can Ctrl+C or type "n" to abort

**Flow (after URL resolved):**
1. Fetch all label tracks with pagination + progress bar
2. Deduplicate tracks, report count removed
3. Initialize cache (`DEFAULT_LABEL_CACHE_PATH`)
4. Initialize state manager (`DEFAULT_LABEL_STATE_PATH`)
5. Call `_match_and_sync_playlist()` with `source_type="label"`
6. Handle `RateLimitError` (save cache, partial report, exit 1)
7. Save cache + state, print/save report

### Phase 3: Tests (`tests/test_label.py`)

Follow `test_beatport.py` patterns:

- `TestValidateLabelUrl` — valid URLs, invalid URLs, normalization
- `TestParseLabelTrack` — track field mapping, duration parsing, date_added population
- `TestParseLabelData` — `_make_label_data()` helper, multi-page data, empty results
- `TestFetchLabelTracks` — mock HTTP responses, pagination, error handling, anti-bot detection
- `TestDeduplicateTracks` — same track on multiple releases, case sensitivity, mix variant handling
- `TestSearchLabels` — name search parsing, no results, multiple matches
- CLI integration tests via Click's `CliRunner` — URL mode, name mode, large label warning, dry-run

### Phase 4: Documentation & Cleanup

- Update `CLAUDE.md`: add `label.py` to module list, document `label` command and all flags, add gitignored files
- Update `CHANGELOG.md`: add entry under `## [Unreleased]`
- Update `.gitignore`: add `.djsupport_label_cache.json` and `.djsupport_label_playlists.json`
- Bump version in `pyproject.toml` if releasing

## Edge Cases

| Scenario | Handling |
|----------|----------|
| Label has 0 tracks | Print "No tracks found for label" and exit |
| Label search returns 0 results | Print "No labels found matching '<name>'" and exit |
| Pagination fails mid-way (network error) | Return tracks collected so far + warning, continue with partial set |
| Track has no `publish_date` | Sort to end of list, use empty string for `date_added` |
| Same track, different mixes (Original vs Remix) | Treat as separate tracks (different titles after normalization) |
| Label URL with `/tracks` suffix vs without | Normalize to include `/tracks` for the fetch |
| `--dry-run` with name search | Still show interactive selection, skip Spotify modifications |
| User Ctrl+C during pagination | Catch `KeyboardInterrupt`, save cache if any matching started |

## Dependencies & Risks

- **Beatport page structure**: Label pages use `__NEXT_DATA__` like chart pages, but the JSON shape may differ. Need to inspect a real label page during implementation to confirm paths.
- **Anti-bot detection**: Beatport has bot detection (`/human-test/`). Existing mitigation (User-Agent, size limits) should carry over. Large labels with many pages may increase detection risk.
- **Beatport search page**: The search endpoint structure needs verification. If `__NEXT_DATA__` isn't available on search pages, may need an alternative parsing approach.
- **Rate limiting on large labels**: A 500-track label = ~500 Spotify API calls minimum (with early exit). The existing rate limit handling + caching makes this manageable but first-run imports of very large labels should be tested.

## Sources & References

- Existing Beatport scraper: `djsupport/beatport.py`
- CLI patterns: `djsupport/cli.py` (beatport command, lines 356-483)
- Track dataclass: `djsupport/rekordbox.py:8-22`
- Rate limit handling: `docs/solutions/integration-issues/spotify-rate-limit-handling.md`
- Deduplication pattern: `docs/solutions/logic-errors/duplicate-spotify-uris-in-playlists-CLI-20260225.md`
- Version tag handling: `docs/solutions/logic-errors/beatport-fuzzy-matcher-version-tags-and-duration-penalty.md`
- Early exit optimization: `docs/solutions/performance-issues/spotify-api-calls-early-exit-optimization.md`
