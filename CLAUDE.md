# CLAUDE.md

## Project overview

djsupport syncs Rekordbox playlists to Spotify. It parses a Rekordbox XML export, fuzzy-matches tracks against Spotify's catalog, and creates/updates Spotify playlists.

## Tech stack

- Python 3.10+ (uses `str | None` union syntax)
- Click for CLI
- spotipy for Spotify API
- rapidfuzz for fuzzy string matching
- python-dotenv for env config
- pytest, pytest-cov (in `[project.optional-dependencies] dev`)

## Project structure

```
djsupport/
  cli.py        # Click CLI entry point
  rekordbox.py  # XML parser — Track and Playlist dataclasses
  matcher.py    # Fuzzy matching logic against Spotify search
  spotify.py    # Spotify client wrapper (spotipy + OAuth)
  config.py     # Local config (saved Rekordbox XML path)
  cache.py      # Persistent match cache with retry logic
  state.py      # Playlist ID mapping for incremental sync
  report.py     # Post-sync terminal + Markdown reports
tests/          # pytest suite (169 tests)
docs/           # Plans, reports, and solution docs
  solutions/    # Documented problem solutions (YAML frontmatter, searchable)
  plans/        # Implementation and feature plans
```

## Key commands

```bash
pip install -e ".[dev]"    # Install in dev mode with test deps
djsupport list <xml>       # List playlists from Rekordbox XML
djsupport sync <xml>       # Sync playlists to Spotify
djsupport sync <xml> --dry-run  # Preview without modifying Spotify
djsupport library set <xml>     # Save default Rekordbox XML path
djsupport library show          # Show configured XML path

# Sync flags
djsupport sync --playlist "My Playlist"  # Sync a single playlist
djsupport sync --threshold 90            # Minimum match confidence (0-100, default 80)
djsupport sync --all                     # Combine all tracks into one playlist
djsupport sync --all-name "My Tracks"    # Custom name for combined playlist
djsupport sync --report report.md        # Save Markdown report
djsupport sync --no-cache                # Bypass match cache
djsupport sync --retry                   # Retry previously failed matches
djsupport sync --retry-days 3            # Auto-retry failures older than N days (default 7)
djsupport sync --cache-path my.json      # Custom cache file location
djsupport sync --prefix "dj"             # Prefix for Spotify playlist names
djsupport sync --no-prefix               # Disable playlist name prefix
djsupport sync --incremental             # Incremental playlist updates (default)
djsupport sync --state-path state.json   # Custom playlist state file location

# Testing
pytest                     # Run all tests
pytest --cov=djsupport     # Run with coverage
```

## Conventions

- CLI entry point is `djsupport.cli:cli`
- Spotify credentials come from `.env` (SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, SPOTIPY_REDIRECT_URI)
- `.env`, `*.xml`, `.spotipy_cache*`, `.djsupport_config.json`, `.djsupport_cache.json`, `.djsupport_playlists.json` are gitignored — never commit these
- Version tracked in `pyproject.toml` (`version = "0.2.0"`)
- Changelog follows Keep a Changelog format in `CHANGELOG.md`
- `docs/` contains plans, test plans, and reports
- `docs/solutions/` holds documented problem solutions with YAML frontmatter (created via `/compound` workflow)
- Update CLAUDE.md in the same PR when adding modules, CLI flags, or changing conventions

## Additional documentation

- [Architectural patterns](.claude/docs/architectural_patterns.md) — persistent state, dataclass conventions, DI, error handling (incl. RateLimitError), testing patterns
- [Rate limit handling solution](docs/solutions/integration-issues/spotify-rate-limit-handling.md) — graceful abort, cache save, resume
- [Gitignore drift solution](docs/solutions/integration-issues/outdated-claude-md-and-gitignore-drift.md) — framework for what to track vs gitignore
