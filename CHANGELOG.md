# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `djsupport library set` and `djsupport library show` commands to save and inspect a default Rekordbox XML path
- Local config file (`.djsupport_config.json`) for storing the default Rekordbox XML path
- Match classification in reports (`exact` vs `fallback_version`) to distinguish remix/version substitutions
- Version fallback counts in sync summaries and match type columns in Markdown reports

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
