# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `djsupport beatport <url>` command — import a Beatport DJ chart as a Spotify playlist
- `djsupport/beatport.py` module — scrapes Beatport chart pages via `__NEXT_DATA__` JSON extraction (no headless browser needed)
- Beatport-specific cache (`.djsupport_beatport_cache.json`) and state (`.djsupport_beatport_playlists.json`), fully isolated from Rekordbox
- Anti-bot challenge detection with clear user messaging
- Security hardening: HTTPS-only URL validation, 5MB response size limit, redirect validation
- `requests>=2.28` dependency for Beatport HTTP fetching
- 44 new tests for Beatport module (URL validation, duration parsing, track parsing, chart data extraction, fetch error handling)
- `source_type` field on `PlaylistState` to distinguish Rekordbox and Beatport sources
- `source_label` field on `SyncReport` for dynamic Markdown table headers
- Duration-based tie-breaking in matcher scoring — disambiguates original/radio/extended versions using Rekordbox `TotalTime` and Spotify `duration_ms`
- Plain-text fallback search strategy (Strategy 5) — runs without `artist:`/`track:` field prefixes when field-specific searches return nothing, improving matches for misspelled artist/track names
- `duration` field on `Track` dataclass, parsed from Rekordbox XML `TotalTime` attribute
- `duration_ms` included in Spotify search result dicts
- `plain` parameter on `search_track` for field-prefix-free queries
- Graceful rate limit handling — aborts with a clear message, saves cache, and exits non-zero instead of hanging for hours
- Defensive `Retry-After` header parsing — handles non-numeric (RFC 7231 date), negative, and missing values
- `tests/test_spotify.py` — unit tests for rate limit handling (17 tests)
- Solution doc: `docs/solutions/integration-issues/spotify-rate-limit-handling.md`
- `tests/fixtures/match_test_data.csv` — ground truth matching test data (19 tracks from "Afro inspired" playlist with verified Spotify URLs)
- `docs/solutions/` directory for documented problem solutions with YAML frontmatter
- First solution doc: `docs/solutions/integration-issues/outdated-claude-md-and-gitignore-drift.md`
- `.claude/docs/architectural_patterns.md` — extracted cross-file patterns (persistent state, dataclasses, DI, error handling, testing)
- "Additional documentation" section in `CLAUDE.md` for progressive disclosure

### Fixed

- Duplicate tracks in Spotify playlists — different Rekordbox entries (e.g., remixes) resolving to the same Spotify URI are now deduplicated before playlist creation

### Changed

- `PlaylistState.rekordbox_path` renamed to `source_path` (v1 state files migrated automatically)
- `MatchedTrack.rekordbox_name` renamed to `source_name` for source-agnostic reporting
- Extracted `_match_and_sync_playlist()` shared helper from `sync` command — both `sync` and `beatport` use it
- `STATE_VERSION` bumped to 2 with automatic v1 migration logic

- Early exit optimization in `match_track` — skips remaining search strategies when Strategy 1 finds a high-confidence exact match (score >= 95), reducing API calls by 40-60% on large library syncs
- Updated README with all current features, flags, and usage examples
- Updated `CLAUDE.md` to reflect v0.2.0 project state (new modules, test suite, all CLI flags, conventions)
- `CLAUDE.md` and `docs/` are now tracked in git for collaborator visibility
- Removed `CLAUDE.md` and `docs/` from `.gitignore`
- Added `.claude/docs/` exception to `.gitignore` so architectural docs are tracked
- Added `docs/solutions/` and `docs/plans/` to project structure in `CLAUDE.md`
- Added convention: update `CLAUDE.md` in the same PR when changing modules, CLI flags, or conventions

## [0.2.1] - 2026-02-22

### Added

- `djsupport library set` and `djsupport library show` commands to save and inspect a default Rekordbox XML path
- Local config file (`.djsupport_config.json`) for storing the default Rekordbox XML path
- Match classification in reports (`exact` vs `fallback_version`) to distinguish remix/version substitutions
- Version fallback counts in sync summaries and match type columns in Markdown reports
- pytest test suite with 143 tests across all modules

### Changed

- `djsupport list` and `djsupport sync` can now use the saved Rekordbox XML path when no XML path argument is provided
- Matcher now treats remix/version identity as a first-class signal and prefers exact-version matches before fallback versions
- Matcher now recognizes Spotify hyphen-style version names (e.g. `Track - XYZ Remix`) in addition to parenthetical mix names
- Matcher normalization now folds diacritics (e.g. `För` -> `For`) to improve cross-catalog matching

### Fixed

- Incremental playlist updates now pass URI strings correctly to Spotify item-removal calls

## [0.2.0] - 2026-02-22

### Added

- Persistent match cache (`.djsupport_cache.json`) with auto-checkpoint every 50 tracks
- Automatic retry of previously unmatched tracks after 7 days (configurable with `--retry-days`)
- `--retry` flag to force retry all failed matches immediately
- `--no-cache` flag to bypass cache (original behavior)
- `--incremental/--no-incremental` flag for diff-based playlist updates
- `--cache-path` option to set custom cache file location
- Cache statistics in sync report (hits, API calls, retries)
- Incremental playlist updates: only add/remove changed tracks instead of full replace

### Changed

- Matcher now tries all search strategies and picks the best result across all of them
- Normalization strips country tags (IL), (UA), bracket labels [Label], and `x` artist separators
- Title scoring compares both raw and mix-stripped versions, taking the better score
- `--all` flag to combine all tracks into a single Spotify playlist instead of per-folder
- `--all-name` option to set a custom name for the combined playlist (default: "Rekordbox All")
- Combined playlist is sorted by Rekordbox date added (oldest first)
- `DateAdded` field parsed from Rekordbox XML

## [0.1.0] - 2026-02-17

### Added

- Rekordbox XML library parser with support for nested folder structures
- Multi-strategy fuzzy matching against Spotify catalog (artist+title, stripped mix info, remixer fallback)
- `djsupport sync` command to create and update Spotify playlists from Rekordbox exports
- `djsupport list` command to preview playlists and track counts
- Dry-run mode (`--dry-run`) for previewing matches without modifying Spotify
- Configurable match confidence threshold (`-t` / `--threshold`, default 80)
- Single-playlist filtering (`-p` / `--playlist`)
- `.env`-based configuration for Spotify API credentials
