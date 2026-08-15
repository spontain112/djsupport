# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.6.0] - 2026-08-15

### Added

- A harness-neutral First Rekordbox Transfer guide with one structured next action at a time across readiness, bounded Preview, Qualification, publication, draft application, and separate playlist-scoped Approval.
- Thin `first-transfer --json` and `/rekordbox/first-transfer` adapters with deterministic non-interactive behavior and runtime input shapes.
- Preview-first migration of legacy current-directory Rekordbox configuration, with explicit apply and no source-file deletion.
- Least-privilege GitHub Actions CI for pull requests and `main`, covering the offline suite on Python 3.10 and 3.14 plus deterministic package validation.
- A canonical maintainer checklist that keeps release preparation, CI, tags, GitHub Releases, and package publication as separate gated operations.
- Rekordbox-only, attention-led Qualification Workspace with durable, non-authoritative drafts; explicit draft application remains separate from playlist-scoped Approval.
- Exact selected-source local audition through short-lived opaque handles, loopback-only no-store media streaming, and bounded byte ranges, independent of Chromaprint identity and durable matching knowledge.
- Rich retained source/Spotify release, version, duration, evidence, and authority facts, including zero-search Approved Match reuse by exact local audio identity.
- Opt-in, Rekordbox-only local Chromaprint evidence that can recover an exact, account-scoped Approved Match after XML metadata changes without another Spotify search.
- Versioned agent-native capability, bounded planning, separate authorization, non-interactive execution, stable resume, and privacy-redacted outcome contracts, exposed through `capabilities --json` and `sync --json`.
- Durable matching-knowledge schema 2, including private fingerprint observations and associations with backup, restore, and legacy-migration support.
- Transfer-state schema 4 for durable local-audio opt-in, evidence checkpoints, stable aggregate outcomes, and Qualification Drafts; schemas 1–3 remain readable.
- Transfer-state schema 5 for idempotent retained Qualification Approval outcomes; schemas 1–4 remain readable.

### Changed

- Qualification Approval now retains its aggregate outcome so repeated guide invocation is idempotent and does not repeat matching-authority writes.
- First-transfer readiness is derived consistently by CLI and web without opening token contents, and interrupted Approval fails closed for review rather than repeating uncertain authority writes.
- Rekordbox path configuration now lives in private platform application data, participates in versioned backup/restore, and requires an explicit restore choice on conflict.
- `main` now identifies as `0.6.0.dev0`, while installation guidance keeps `v0.5.0` as the Latest stable release and limits previews to exact candidates.
- Transfer checkpoints completed local observations and aggregate API/local evidence counts so resumed and repeated agent outcomes remain stable.
- Rekordbox XML intake retains each selected track's private `Location` solely for opted-in local calculation; reports and machine output omit it.
- Batch identity now binds the exact selected source content and effect scope; ambiguous legacy Batches must restart instead of resuming stale source data.
- The web API accepts the same explicit local-audio opt-in and reports the same aggregate local-evidence counters as other Transfer clients.

### Security

- Unsupported matching-knowledge schemas fail closed without rewriting private state, and changed Preview/publication scope cannot resume an earlier Batch.

### Fixed

- Materially shorter Spotify substitutes remain eligible for Approval but are identified for review with their duration difference instead of being labelled exact.

## [0.5.0] - 2026-08-02

### Added

- Typed Spotify playlist-head, ordered-item, page, and mutation facts.
- Durable mutation snapshots and completed 100-item chunk identities for
  resumable publication, with changed-head stop conditions.
- Private-playlist read consent using only `playlist-read-private` in addition
  to the existing playlist modification permissions.

### Changed

- Playlist creation uses Spotify's current-user route and item reads/writes use
  the current playlist-item contract.
- Approval verifies one stable playlist head around its complete ordered read.
- Publication and Approval preserve duplicate occurrences and explicitly
  classify null, local, episode, unsupported, restricted, and relinked items.
- Private publication state writes schema 5 and Transfer state writes schema 2;
  previous supported schemas remain readable and backup-compatible.

### Fixed

- Beatport chart curator provenance survives intake, durable resume, playlist
  title construction, manifests, and approved Snapshot or Mirror copy.
- Recovery markers are removed immediately after playlist ID retention, and
  settled descriptions no longer expose opaque Transfer IDs or timestamps.

## [0.4.0] - 2026-08-01

### Added

- Explicit, preview-first migration of known 0.3.0 working-directory cache and
  playlist-state files into versioned application data, with verified backup,
  atomic rollback, privacy-safe aggregate reporting, and idempotent apply.
- Durable Transfer orchestration for Rekordbox Batches and Beatport chart or
  label Snapshots, with resumable checkpoints, partial outcomes, safe failure
  handling, and optional recurring Beatport Mirrors.
- Provisional Playlist review, Approval, Rejection, Abandonment, and explicit
  Corrections supplied through editable review CSV files.
- Versioned, timestamped local-data backups with integrity validation,
  preview-first conflict handling, and atomic restore.
- Beatport label discovery and paginated ingestion, including interactive name
  search, URL validation, deduplication, and bounded pagination.
- Optional FastAPI web UI (`pip install djsupport[web]`) with Spotify OAuth,
  background Transfers, and progress events.
- Account-scoped publication state, reusable Approved Matches, and private
  Correction-derived matcher regression knowledge.
- Clickable Spotify proposals, stable source references, and editable review
  CSV files in Transfer reports.

### Changed

- Rekordbox Transfers require explicit playlist selection or an opt-in
  whole-library Batch and now provide lookup-cost preflight.
- Beatport charts and labels publish one-time Snapshots by default; `--mirror`
  opts into a recurring Mirror.
- Compatible CLI names and flags such as `sync`, `--dry-run`, `--no-cache`, and
  `--retry-days` remain available while documentation uses Transfer, Preview,
  Mirror, Snapshot, Approval, Correction, and Batch terminology.
- FastAPI and uvicorn moved to the optional `web` dependency group.
- Local user-derived reports and matcher evidence were removed from Git and are
  read from versioned private application storage instead.
- The obsolete `djsupport.service` orchestration layer was removed; CLI and web
  flows use the public Transfer interface.

### Fixed

- Current schema-v4 publication manifests can be validated and restored from a
  local-data backup, alongside supported 0.3.0-era schemas.
- Approval preserves unmatched source tracks so explicit Corrections can add
  missing Spotify targets without losing source order.
- Partial Match Collisions remain unresolved until every source mapping is
  explicitly corrected or rejected.
- Beatport chart curator metadata is retained for supported page-data shapes and
  used in playlist names when available.
- Label parsing handles the current and legacy search response shapes, validates
  returned URLs, caps pagination, and reports malformed page data safely.
- Matcher version recognition includes standalone Original and Interpretation
  descriptors.
- Matcher title comparison preserves one copy of immediately adjacent repeated
  parenthetical subtitles, without changing source or matching identities.

### Known limitations

- Some Beatport chart payload shapes do not expose curator metadata through the
  supported parser, so the playlist can fall back to the chart name alone (#60).
- Provisional Playlist descriptions retain an opaque Transfer marker and
  machine timestamp because crash recovery and duplicate-publication prevention
  currently depend on that marker (#61).
- Broader Spotify candidate recall, noisy-source cleanup, and ISRC-first lookup
  remain research work rather than release behavior (#31, #32, #39, #42).

## [0.3.0] - 2026-02-26

### Added

- `djsupport beatport <url>` command — import a Beatport DJ chart as a Spotify playlist
- `djsupport/beatport.py` module — scrapes Beatport chart pages via `__NEXT_DATA__` JSON extraction (no headless browser needed)
- Beatport-specific cache (`.djsupport_beatport_cache.json`) and state (`.djsupport_beatport_playlists.json`), fully isolated from Rekordbox
- `--retry` and `--retry-days` flags on `beatport` command (parity with `sync`)
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
- Solution docs in `docs/solutions/` with YAML frontmatter for searchability
- `.claude/docs/architectural_patterns.md` — extracted cross-file patterns (persistent state, dataclasses, DI, error handling, testing)

### Fixed

- Matcher now recognizes standalone version tags like `(Extended)`, `(Radio)`, `(Instrumental)` — previously only matched when combined with "Mix" (e.g., "Extended Mix")
- Reduced duration penalty from 10pts/30s (cap 30) to 5pts/30s (cap 15) — prevents extended DJ versions from being rejected when Spotify only has radio edits
- Duplicate tracks in Spotify playlists — different source entries resolving to the same Spotify URI are now deduplicated before playlist creation
- Eliminated redundant `_score_components` computation in `_select_best` (performance)

### Changed

- `PlaylistState.rekordbox_path` renamed to `source_path` (v1 state files migrated automatically)
- `MatchedTrack.rekordbox_name` renamed to `source_name` for source-agnostic reporting
- Extracted `_match_and_sync_playlist()` shared helper from `sync` command — both `sync` and `beatport` use it
- `STATE_VERSION` bumped to 2 with automatic v1 migration logic
- Early exit optimization in `match_track` — skips remaining search strategies when Strategy 1 finds a high-confidence exact match (score >= 95), reducing API calls by 40-60% on large library syncs
- Updated README with all current features, flags, and usage examples
- `CLAUDE.md` and `docs/` are now tracked in git for collaborator visibility

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
