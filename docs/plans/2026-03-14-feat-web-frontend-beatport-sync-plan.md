---
title: "feat: Web frontend for Beatport playlist sync"
type: feat
status: completed
date: 2026-03-14
---

# Web Frontend for Beatport Playlist Sync

## Overview

Build a responsive web UI for djsupport that lets you paste a Beatport chart or label URL and sync it to Spotify — replacing the CLI workflow with a browser-based experience. Runs locally as a personal tool, with the architecture designed to support additional sources (Rekordbox, etc.) as they're added.

## Problem Statement / Motivation

The CLI works well but requires terminal familiarity and remembering flags. A web UI provides:
- Faster workflow: paste URL → click sync → done
- Visual progress feedback instead of terminal output
- Clickable Spotify playlist links in results
- A foundation for adding more sources without CLI flag complexity

## Proposed Solution

**FastAPI backend** wrapping the existing Python modules + **single HTML page frontend** styled with Tailwind CSS. The backend serves the HTML and exposes a small API. Progress streams via Server-Sent Events (SSE).

### Architecture

```
Browser (localhost:8000)
  │
  ├── GET /                → Serves index.html (Tailwind + vanilla JS)
  ├── GET /auth/status     → Check if Spotify token exists
  ├── GET /auth/login      → Redirect to Spotify OAuth
  ├── GET /auth/callback   → Receive OAuth code, store token
  ├── POST /sync           → Start sync job, returns {job_id}
  ├── GET /sync/{id}/progress → SSE stream of progress events
  └── GET /sync/{id}/result   → Final sync results as JSON
  │
FastAPI (Python)
  │
  ├── service.py (NEW)     → Extracted sync orchestration from cli.py
  ├── spotify.py            → Modified get_client() to accept web OAuth
  ├── beatport.py           → Unchanged (stateless parser)
  ├── label.py              → Unchanged (already has callback hooks)
  ├── matcher.py            → Unchanged (DI-based)
  ├── cache.py              → Unchanged (file-based, single user)
  ├── state.py              → Unchanged (file-based, single user)
  └── report.py             → Add spotify_playlist_id to PlaylistReport
```

### Data Flow

```
User pastes URL
  → POST /sync {url: "https://beatport.com/chart/..."}
  → Backend validates URL (beatport.validate_url / label.validate_label_url)
  → Spawns sync in background thread (asyncio.to_thread)
  → Returns {job_id: "abc123"}

Frontend connects to GET /sync/abc123/progress (SSE)
  → Backend streams: {phase: "fetching", detail: "Fetching chart..."}
  → Backend streams: {phase: "matching", current: 3, total: 25, track: "Adam Beyer - Drum Machine"}
  → Backend streams: {phase: "syncing", detail: "Creating playlist..."}
  → Backend streams: {phase: "complete"}

Frontend fetches GET /sync/abc123/result
  → Returns full SyncReport as JSON (matched, unmatched, playlist URL)
```

## Technical Considerations

### Spotify OAuth for Web Context

The current `get_client()` uses `SpotifyOAuth` with file-based token caching. For the web:

- **Redirect URI**: Set `SPOTIPY_REDIRECT_URI=http://localhost:8000/auth/callback`
- **Token storage**: Reuse spotipy's file-based `.spotipy_cache` (single user, so this works)
- **Flow**: `/auth/login` → Spotify → `/auth/callback` → store token → redirect to `/`
- **Token refresh**: Spotipy handles this automatically via the cached refresh token
- Modify `spotify.py:get_client()` to accept an optional `cache_path` or auth manager, keeping CLI compatibility

### Background Sync with Progress

- Existing sync code is synchronous (requests, spotipy) — run in `asyncio.to_thread`
- Extract `_match_and_sync_playlist()` from `cli.py` into `service.py`, replacing `click.progressbar` with a `progress_callback: Callable[[ProgressEvent], None]`
- Progress events pushed to a `queue.Queue` (thread-safe), drained by SSE endpoint
- Enforce single sync at a time — return HTTP 409 if a job is already running

### Rate Limit Handling

Per existing `RateLimitError` pattern (`docs/solutions/integration-issues/spotify-rate-limit-handling.md`):
- Short waits (≤60s): auto-retry (existing behavior)
- Long waits (>60s): abort, save cache, stream error event with `retry_after` seconds
- Frontend shows: "Rate limited by Spotify. Try again in X minutes. Your progress has been saved."

### Frontend Design

Single responsive HTML page with three states:

1. **Input state**: URL text field + "Sync" button. Auto-detects URL type on input (chart vs label). Shows auth status indicator.
2. **Progress state**: Progress bar + current track name + running count of matched/unmatched.
3. **Results state**: Summary stats, matched tracks table, unmatched tracks list, "Open in Spotify" button.

Vanilla JS with `EventSource` for SSE. Tailwind via CDN for styling. No build step.

## Acceptance Criteria

- [x]`pip install -e ".[dev]"` installs FastAPI + uvicorn as new dependencies
- [x]`djsupport web` command starts the server on `localhost:8000`
- [x]Browser shows a single-page UI with URL input field
- [x]Pasting a Beatport chart URL and clicking sync creates/updates a Spotify playlist
- [x]Pasting a Beatport label URL works the same way
- [x]Invalid URLs show inline validation errors
- [x]Real-time progress bar updates during sync via SSE
- [x]Results page shows matched tracks, unmatched tracks, and Spotify playlist link
- [x]Spotify OAuth flow works via browser redirect (no terminal interaction)
- [x]Rate limit errors display gracefully with retry-after time
- [x]Existing CLI commands continue to work unchanged
- [x]All existing tests pass (no regressions)
- [x]New tests cover: API endpoints, service layer, OAuth callback

## Implementation Phases

### Phase 1: Service Layer Extraction

Extract sync orchestration from `cli.py` into `djsupport/service.py`:
- `sync_beatport_chart(url, sp, cache, state_mgr, threshold, prefix, on_progress) -> SyncReport`
- `sync_beatport_label(url, sp, cache, state_mgr, threshold, prefix, on_progress) -> SyncReport`
- Add `spotify_playlist_id: str | None = None` to `PlaylistReport` in `report.py`
- Update CLI to use the new service layer (both CLI and web call the same code)
- Tests for service layer functions

**Files:**
- `djsupport/service.py` (new)
- `djsupport/report.py` (add playlist ID field)
- `djsupport/cli.py` (refactor to use service.py)
- `tests/test_service.py` (new)

### Phase 2: FastAPI Backend + OAuth

- Add `fastapi`, `uvicorn` to `pyproject.toml` dependencies
- Create `djsupport/web.py` with API routes
- Implement Spotify OAuth endpoints (`/auth/login`, `/auth/callback`, `/auth/status`)
- Implement sync endpoints (`POST /sync`, `GET /sync/{id}/progress`, `GET /sync/{id}/result`)
- Add `djsupport web` CLI command to start uvicorn
- Background sync via `asyncio.to_thread` + `queue.Queue` for progress
- Single-job enforcement (409 on concurrent sync)

**Files:**
- `djsupport/web.py` (new)
- `djsupport/cli.py` (add `web` command)
- `pyproject.toml` (add dependencies)
- `tests/test_web.py` (new)

### Phase 3: Frontend

- Create `djsupport/static/index.html` — single page with Tailwind CDN
- URL input with auto-detection (chart vs label validation)
- SSE-powered progress display
- Results view with matched/unmatched tracks and Spotify link
- Responsive design (works on phone too, for quick mobile use)
- Auth status indicator + login flow

**Files:**
- `djsupport/static/index.html` (new)
- `djsupport/static/app.js` (new — optional, could be inline)

## Success Metrics

- Paste-to-playlist workflow completes in the browser without touching the terminal
- Existing CLI tests remain green
- Sub-second page load (single HTML file, CDN assets)

## Dependencies & Risks

| Risk | Mitigation |
|------|-----------|
| Spotipy OAuth may not work cleanly in web redirect flow | Prototype OAuth flow first; spotipy supports custom redirect URIs natively |
| Background thread + SSE may drop events | Use bounded queue with backpressure; SSE auto-reconnects |
| Beatport scraping can fail (anti-bot) | Same risk as CLI — surface error clearly in UI |
| Adding FastAPI increases dependency footprint | Acceptable for a personal tool; FastAPI + uvicorn are lightweight |
| `_match_and_sync_playlist` extraction may break CLI | Phase 1 focuses entirely on this refactor with full test coverage before touching web code |

## Deferred to Future Iterations

- Label name search (requires multi-step selection UI)
- Rekordbox XML upload
- Advanced options (threshold, prefix, dry-run, retry)
- Sync history / past results
- Cancel running sync
- Deploy to cloud (auth, multi-user)
- Sync queue (multiple jobs)

## Sources & References

- Existing architecture: `djsupport/cli.py:61-157` (`_match_and_sync_playlist`)
- Spotify OAuth: `djsupport/spotify.py:40-47` (`get_client`)
- Rate limit handling: `docs/solutions/integration-issues/spotify-rate-limit-handling.md`
- Architectural patterns: `.claude/docs/architectural_patterns.md`
- Label callback hooks: `djsupport/label.py` (`on_total`, `on_page`, `on_page_error`)
