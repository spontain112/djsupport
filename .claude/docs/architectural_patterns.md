# Architectural Patterns

Cross-file patterns that appear in 3+ modules. Reference this doc when adding new modules or refactoring existing ones.

## Persistent state management

`ConfigManager`, `MatchCache`, `FilePublicationStorage`, and
`FileTransferStorage` use versioned JSON persistence:

1. Class wraps a `Path` to a JSON file
2. `load()` is a no-op if the file is missing. Configuration may silently
   ignore an unknown version, but matching knowledge and authoritative state
   reject unsupported schemas so a later save cannot overwrite newer private
   data.
3. `save()` writes a `{"version": N, ...}` envelope via `json.dumps(data, indent=2)`
4. Version constant at module top (`CONFIG_VERSION`, `CACHE_VERSION`, `STATE_VERSION`)

Transfer persistence writes atomically and retains schema versions for durable
resume, publication manifests, Approval outcomes, and account-scoped Mirrors.
`ConfigManager` and `MatchCache` preserve their compatible local schemas and
migrations.

## Dataclass conventions

Frozen domain models vs mutable state containers:

- **Domain models** — `Track` and `Playlist` in `rekordbox.py` are plain data holders parsed from XML. `Track` uses `@property` for computed display. `Playlist` uses `field(default_factory=list)` for mutable defaults.
- **State containers** — `CacheEntry`, `TransferState`, `BatchState`, and
  `AppConfig` are dataclasses serialized to/from JSON via `asdict()`.
- **Report models** — `MatchedTrack`, `PlaylistReport`, `SyncReport` use `field(default_factory=list)` and `@property` for computed aggregates like `match_rate` and `total_matched`.

Files:
- `rekordbox.py:8-28` — `Track` (frozen domain model with `@property display`)
- `rekordbox.py:24-28` — `Playlist` with `field(default_factory=list)`
- `cache.py:17-26` — `CacheEntry` (mutable, serialized via `asdict`)
- `transfer.py` — durable Transfer, Batch, publication, Approval, and Mirror state
- `config.py:15-18` — `AppConfig` (mutable, serialized via `asdict`)
- `report.py:7-55` — `MatchedTrack`, `PlaylistReport`, `SyncReport` with computed `@property` methods

## Dependency injection via parameters

External dependencies are passed through Runtime Assembly, the Transfer
constructor, or function parameters—never global singletons.

- `match_track(sp, track, threshold)` — receives Spotify client as `sp`
- `match_track_cached(sp, track, cache, ...)` — receives both `sp` and `cache`
- `RuntimeAssembly` receives an injectable Spotify-adapter factory and selects
  paths, matching knowledge, persistence, guards, and local-audio adapters.
- CLI and Agent Client paths provide source and authorized phase facts to
  Runtime Assembly; the web adapter retains its direct construction seam.

Files:
- `matcher.py:154` — `match_track(sp, track, threshold)`
- `matcher.py:225-228` — `match_track_cached(sp, track, cache, ...)`
- `spotify.py:106-113` — `create_or_update_playlist(sp, ..., state_manager=None)`
- `spotify.py:176-183` — `incremental_update_playlist(sp, ..., state_manager=None)`
- `runtime.py` — private production graph assembly for CLI and Agent Clients

## Error handling

Four patterns used consistently:

1. **Safe file loads** — missing configuration/matching-knowledge files degrade
   safely; unsupported matching-knowledge and authoritative state schemas fail
   closed; Transfer/publication writes are atomic and validated.
2. **`(bool, str | None)` tuple returns** — Validation functions return success/error tuples (e.g., `validate_rekordbox_xml`).
3. **`click.ClickException`** — User-facing errors in CLI code use Click's exception for clean terminal output.
4. **`RateLimitError` for unsafe waits** — Transfer checkpoints and pauses on
   long rate limits; bounded retry handles safe transient failures.

Files:
- `config.py:26-39` — silent load with early returns
- `cache.py:34-45` — silent load with early returns
- `config.py:54` — `validate_rekordbox_xml() -> tuple[bool, str | None]`
- `cli.py:43-55` — `click.ClickException` for missing/invalid XML path
- `spotify.py:19-35` — `RateLimitError` exception class
- `spotify.py:50-72` — `_api_call_with_rate_limit` wrapper (applied to search, the hot path)
- `transfer.py` — bounded retry, checkpoint, pause, and resume policy

## Testing conventions

- **Factory functions per test file** — Each test module defines helpers to build test objects (e.g., `make_track()`, `_matched_result()`, `sample_state()`).
- **Class-grouped tests** — Related tests are grouped in classes (e.g., `TestPlaylistStateManager`).
- **`tmp_path` for persistence** — Fixtures use `tmp_path` for isolated durable
  Transfer, publication, matching-knowledge, migration, backup, and restore tests.
- **`MagicMock` for Spotify API** — All Spotify interactions are mocked; no real API calls in tests.
- **Shared fixtures in `conftest.py`** — `library_xml` fixture points to `tests/fixtures/library.xml`.

Files:
- `tests/test_matcher.py:20-30` — `make_track()` factory
- `tests/test_cache.py:11-12` — `_matched_result()` factory
- `tests/test_cache.py:15-17` — `tmp_path` fixture for `MatchCache`
- `tests/test_state.py:11-13` — `tmp_path` fixture for `PlaylistStateManager`
- `tests/test_transfer.py` — public Transfer behavior and persistence coverage
- `tests/test_matcher.py:3` — `MagicMock` import for Spotify mocking
- `tests/conftest.py:7-13` — shared `library_xml` fixture

## Cross-cutting conventions

- **`_normalize()` shared between matcher and cache** — `cache.py:8` imports `_normalize` from `matcher.py:12` for cache key generation.
- **`datetime.now().isoformat()` timestamps** — Used by local configuration,
  matching knowledge, Transfer state, publications, and Approval history.
- **`Path` objects everywhere** — All file paths are converted to `Path` early. Config/cache/state managers store `self.path` as `Path`.
- **`str | None` union syntax** — Python 3.10+ syntax used throughout instead of `Optional[str]`.
