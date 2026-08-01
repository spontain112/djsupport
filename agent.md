# agent.md

## Scope Guard
- This repo is for djsupport only. Do NOT build Claude Code skills, slash commands, hooks, or other extensions here.
- If the user asks to build something that is not djsupport-specific, STOP and redirect them to their dedicated Claude Code extensions workspace.

## Project overview

djsupport Transfers Rekordbox playlists, Beatport DJ charts, and Beatport record labels to Spotify as Mirrors or Snapshots.

## Tech stack

- Python 3.10+ (uses `str | None` union syntax)
- Click for CLI
- FastAPI + uvicorn for web UI (optional: `pip install djsupport[web]`)
- spotipy for Spotify API
- rapidfuzz for fuzzy string matching
- requests for Beatport HTTP fetching
- python-dotenv for env config
- pytest, pytest-cov, httpx (in `[project.optional-dependencies] dev`)

## Project structure

```
djsupport/
  cli.py        # Click CLI entry point
  web.py        # Thin FastAPI adapter (OAuth, durable Transfer endpoints, SSE progress)
  rekordbox.py  # XML parser — Track and Playlist dataclasses
  beatport.py   # Beatport chart scraper — __NEXT_DATA__ extraction, curator name composition
  label.py      # Beatport label scraper — paginated track fetching + label search
  matcher.py    # Fuzzy matching logic against Spotify search
  spotify.py    # Spotify client wrapper (spotipy + OAuth)
  config.py     # Local config (saved Rekordbox XML path)
  cache.py      # Persistent match cache with retry logic
  regression.py # Local regression loader for live accuracy checks
  report.py     # Transfer outcome terminal, Markdown, and Correction CSV reports
  transfer.py   # Durable Transfer/Batch orchestration, checkpoints, and publication
  backup.py     # Versioned local-data backup, preview, merge, and atomic restore
  migration.py  # Explicit preview/apply migration of known 0.3.0 local data
  static/       # Web frontend (index.html with Tailwind CSS)
tests/          # pytest suite
docs/           # Plans, reports, and solution docs
  solutions/    # Documented problem solutions (YAML frontmatter, searchable)
  plans/        # Implementation and feature plans
```

## Key commands

```bash
pip install -e ".[dev]"    # Install in dev mode with test deps
pip install -e ".[dev,web]" # Install with test deps + web UI (FastAPI/uvicorn)
djsupport list <xml>       # List playlists from Rekordbox XML
djsupport sync <xml> --playlist "My Playlist"  # Transfer one Rekordbox Mirror
djsupport sync <xml> --whole-library            # Explicit whole-library Batch
djsupport sync <xml> --dry-run  # Preview without modifying Spotify
djsupport library set <xml>     # Save default Rekordbox XML path
djsupport library show          # Show configured XML path
djsupport beatport <url>       # Create a Beatport Snapshot
djsupport label <url-or-name> # Create a Beatport label Snapshot
djsupport web                   # Start web UI at localhost:8000
djsupport web --port 3000       # Custom port
djsupport backup                # Create a timestamped local-data archive
djsupport restore <archive>     # Validate and preview an archive
djsupport restore <archive> --apply  # Apply a conflict-free restore
djsupport migrate-0-3 <directory>    # Preview 0.3.0 local-data migration
djsupport migrate-0-3 <directory> --apply  # Back up, verify, and apply migration

# Rekordbox Transfer flags
djsupport sync --playlist "My Playlist"  # Select a playlist (repeat for a Batch)
djsupport sync --whole-library            # Explicitly select the whole library
djsupport sync --threshold 90            # Minimum match confidence (0-100, default 80)
djsupport sync --report report.md        # Save Markdown report
djsupport sync --no-cache                # Bypass matching knowledge (compatible flag)
djsupport sync --retry                   # Retry previously failed matches
djsupport sync --retry-days 3            # Compatibility-only; use --retry explicitly
djsupport sync --cache-path my.json      # Matching-knowledge path (compatible flag)
djsupport sync --prefix "dj"             # Prefix for Spotify playlist names
djsupport sync --no-prefix               # Disable playlist name prefix
djsupport sync --state-path state.json   # Custom playlist state file location

# Beatport flags
djsupport beatport <url> --dry-run                  # Preview matches
djsupport beatport <url> --threshold 90              # Minimum match confidence
djsupport beatport <url> --no-cache                  # Bypass Beatport match cache
djsupport beatport <url> --retry                     # Retry previously failed matches
djsupport beatport <url> --retry-days 3              # Compatibility-only; use --retry explicitly
djsupport beatport <url> --cache-path my.json        # Custom Beatport cache file
djsupport beatport <url> --state-path my.json        # Custom publication manifest file
djsupport beatport <url> --prefix "dj"               # Prefix for playlist name
djsupport beatport <url> --no-prefix                 # No prefix
djsupport beatport <url> --report report.md          # Save Markdown report
djsupport approve <spotify-playlist-id>              # Approve one reviewed Provisional Playlist
djsupport approve <spotify-playlist-id> --review-csv review.csv  # Apply Corrections while approving
djsupport beatport <url> --incremental               # Incremental updates (default)
djsupport beatport <url> --mirror                    # Explicit recurring Mirror (Snapshot is default)
djsupport beatport <url> --resume <transfer-id>      # Resume a paused Transfer
djsupport beatport <url> --abandon <transfer-id>     # Explicitly abandon a Transfer

# Label flags
djsupport label <url>                                # Snapshot by Beatport label URL
djsupport label "Drumcode"                           # Search Beatport by label name
djsupport label <url-or-name> --dry-run              # Preview matches
djsupport label <url-or-name> --threshold 90         # Minimum match confidence
djsupport label <url-or-name> --no-cache             # Bypass label match cache
djsupport label <url-or-name> --retry                # Retry previously failed matches
djsupport label <url-or-name> --retry-days 3         # Compatibility-only; use --retry explicitly
djsupport label <url-or-name> --cache-path my.json   # Custom label cache file
djsupport label <url-or-name> --state-path my.json   # Custom label state file
djsupport label <url-or-name> --prefix "dj"          # Prefix for playlist name
djsupport label <url-or-name> --no-prefix            # No prefix
djsupport label <url-or-name> --report report.md     # Save Markdown report
djsupport label <url-or-name> --incremental          # Incremental updates (default)
djsupport label <url-or-name> --mirror               # Explicit recurring Mirror (Snapshot is default)
djsupport label <url-or-name> --resume <transfer-id> # Resume a paused Transfer
djsupport label <url-or-name> --abandon <transfer-id> # Explicitly abandon a Transfer

# Testing
pytest                     # Run all tests
pytest --cov=djsupport     # Run with coverage
```

## Conventions

- CLI entry point is `djsupport.cli:cli`
- Spotify credentials come from `.env` (SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, SPOTIPY_REDIRECT_URI)
- `.env`, `*.xml`, `.spotipy_cache*`, `.djsupport_config.json`, `.djsupport_cache*`, `.djsupport_playlists*`, `.djsupport_beatport_cache*`, `.djsupport_beatport_playlists*`, `.djsupport_label_cache*`, `.djsupport_label_playlists*` are gitignored — never commit these
- Generated reports, review CSVs, local regression exports, matching knowledge,
  credentials, local paths, and playlist state stay in private application
  storage. Repository matcher tests are synthetic unless a user explicitly
  exports and consents to a privacy-reviewed contribution.
- Version tracked in `pyproject.toml` (`version = "0.4.0"`)
- Changelog follows Keep a Changelog format in `CHANGELOG.md`
- `docs/` contains plans, test plans, and reports
- `docs/solutions/` holds documented problem solutions with YAML frontmatter (created via `/compound` workflow)
- Update `agent.md` in the same PR when adding modules, CLI flags, or changing conventions

## Additional documentation

- [Architectural patterns](.claude/docs/architectural_patterns.md) — persistent state, dataclass conventions, DI, error handling (incl. RateLimitError), testing patterns
- [Rate limit handling solution](docs/solutions/integration-issues/spotify-rate-limit-handling.md) — graceful abort, cache save, resume
- [Gitignore drift solution](docs/solutions/integration-issues/outdated-claude-md-and-gitignore-drift.md) — framework for what to track vs gitignore

## Agent skills

### Issue tracker

Issues and PRDs are tracked in GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default five-role triage vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository. See `docs/agents/domain.md`.
