# Architectural Patterns

Cross-file patterns that appear in 3+ modules. Reference this doc when adding new modules or refactoring existing ones.

## Persistent state management

`ConfigManager`, `MatchCache`, and `PlaylistStateManager` follow an identical load/save/version JSON pattern:

1. Class wraps a `Path` to a JSON file
2. `load()` is a no-op if file is missing or has wrong version — silent degradation
3. `save()` writes a `{"version": N, ...}` envelope via `json.dumps(data, indent=2)`
4. Version constant at module top (`CONFIG_VERSION`, `CACHE_VERSION`, `STATE_VERSION`)

Files:
- `config.py:11-12` — `CONFIG_VERSION`, `DEFAULT_CONFIG_PATH`
- `config.py:21-44` — `ConfigManager.load()`/`save()`
- `cache.py:10-11` — `CACHE_VERSION`, `DEFAULT_CACHE_PATH`
- `cache.py:28-54` — `MatchCache.load()`/`save()`
- `state.py:8-9` — `STATE_VERSION`, `DEFAULT_STATE_PATH`
- `state.py:21-45` — `PlaylistStateManager.load()`/`save()`

## Dataclass conventions

Frozen domain models vs mutable state containers:

- **Domain models** — `Track` and `Playlist` in `rekordbox.py` are plain data holders parsed from XML. `Track` uses `@property` for computed display. `Playlist` uses `field(default_factory=list)` for mutable defaults.
- **State containers** — `CacheEntry`, `PlaylistState`, `AppConfig` are mutable dataclasses serialized to/from JSON via `asdict()`.
- **Report models** — `MatchedTrack`, `PlaylistReport`, `SyncReport` use `field(default_factory=list)` and `@property` for computed aggregates like `match_rate` and `total_matched`.

Files:
- `rekordbox.py:8-28` — `Track` (frozen domain model with `@property display`)
- `rekordbox.py:24-28` — `Playlist` with `field(default_factory=list)`
- `cache.py:17-26` — `CacheEntry` (mutable, serialized via `asdict`)
- `state.py:13-18` — `PlaylistState` (mutable, serialized via `asdict`)
- `config.py:15-18` — `AppConfig` (mutable, serialized via `asdict`)
- `report.py:7-55` — `MatchedTrack`, `PlaylistReport`, `SyncReport` with computed `@property` methods

## Dependency injection via parameters

External dependencies (Spotify client, cache, state manager) are passed as function parameters — never global singletons.

- `match_track(sp, track, threshold)` — receives Spotify client as `sp`
- `match_track_cached(sp, track, cache, ...)` — receives both `sp` and `cache`
- `create_or_update_playlist(sp, name, ..., state_manager=None)` — optional state manager
- `incremental_update_playlist(sp, name, ..., state_manager=None)` — same pattern
- CLI (`cli.py:162-178`) wires everything together: creates cache, state manager, Spotify client, then passes them into matcher and spotify functions

Files:
- `matcher.py:154` — `match_track(sp, track, threshold)`
- `matcher.py:225-228` — `match_track_cached(sp, track, cache, ...)`
- `spotify.py:106-113` — `create_or_update_playlist(sp, ..., state_manager=None)`
- `spotify.py:176-183` — `incremental_update_playlist(sp, ..., state_manager=None)`
- `cli.py:162-178` — wiring in `sync` command

## Error handling

Three patterns used consistently:

1. **Silent degradation for file loads** — `load()` methods return early on missing files, parse errors, or version mismatches. No exceptions raised.
2. **`(bool, str | None)` tuple returns** — Validation functions return success/error tuples (e.g., `validate_rekordbox_xml`).
3. **`click.ClickException`** — User-facing errors in CLI code use Click's exception for clean terminal output.

Files:
- `config.py:26-39` — silent load with early returns
- `cache.py:34-45` — silent load with early returns
- `state.py:26-37` — silent load with early returns
- `config.py:54` — `validate_rekordbox_xml() -> tuple[bool, str | None]`
- `cli.py:43-55` — `click.ClickException` for missing/invalid XML path

## Testing conventions

- **Factory functions per test file** — Each test module defines helpers to build test objects (e.g., `make_track()`, `_matched_result()`, `sample_state()`).
- **Class-grouped tests** — Related tests are grouped in classes (e.g., `TestPlaylistStateManager`).
- **`tmp_path` for state managers** — Fixtures use pytest's `tmp_path` to create isolated file-backed managers.
- **`MagicMock` for Spotify API** — All Spotify interactions are mocked; no real API calls in tests.
- **Shared fixtures in `conftest.py`** — `library_xml` fixture points to `tests/fixtures/library.xml`.

Files:
- `tests/test_matcher.py:20-30` — `make_track()` factory
- `tests/test_cache.py:11-12` — `_matched_result()` factory
- `tests/test_cache.py:15-17` — `tmp_path` fixture for `MatchCache`
- `tests/test_state.py:11-13` — `tmp_path` fixture for `PlaylistStateManager`
- `tests/test_state.py:27` — `TestPlaylistStateManager` class grouping
- `tests/test_matcher.py:3` — `MagicMock` import for Spotify mocking
- `tests/conftest.py:7-13` — shared `library_xml` fixture

## Cross-cutting conventions

- **`_normalize()` shared between matcher and cache** — `cache.py:8` imports `_normalize` from `matcher.py:12` for cache key generation.
- **`datetime.now().isoformat()` timestamps** — Used in `config.py:51`, `cache.py:83,94`, `state.py` (via `PlaylistState.last_synced`), `spotify.py:151`.
- **`Path` objects everywhere** — All file paths are converted to `Path` early. Config/cache/state managers store `self.path` as `Path`.
- **`str | None` union syntax** — Python 3.10+ syntax used throughout instead of `Optional[str]`.
