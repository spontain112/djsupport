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
tests/          # pytest suite (143 tests)
docs/           # Plans and reports
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
djsupport sync --report report.md        # Save Markdown report
djsupport sync --no-cache                # Bypass match cache
djsupport sync --retry                   # Retry previously failed matches
djsupport sync --prefix "dj"             # Prefix for Spotify playlist names
djsupport sync --incremental             # Incremental playlist updates (default)

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
