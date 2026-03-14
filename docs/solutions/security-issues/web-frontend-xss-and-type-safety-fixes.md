---
title: Web Frontend XSS and Type Safety Fixes
date: 2026-03-14
category: security-issues
tags:
  - security
  - xss
  - type-safety
  - error-handling
  - fastapi
  - vanilla-js
severity: critical
components:
  - djsupport/web.py
  - djsupport/static/index.html
  - djsupport/cli.py
  - djsupport/service.py
symptoms:
  - XSS vulnerabilities in innerHTML interpolations
  - Auth callback reflected XSS via unescaped error parameter
  - Raw exception messages leaked to HTTP clients
  - Type safety lost through **kwargs in wrapper functions
  - Dead DOM element references causing runtime errors
  - Deprecated asyncio API usage
root_cause: Web frontend feature introduced unsafe DOM manipulation, improper exception handling, and type safety regressions
resolution_type: code-review-fixes
---

# Web Frontend XSS and Type Safety Fixes

## Problem

After building a FastAPI web frontend for djsupport (PR #10), a multi-agent code review identified 18 findings across security, type safety, and code quality. The P1 (critical) and P2 (important) findings required immediate fixes before merge.

## Root Cause

The frontend used `innerHTML` with template literals to render server data (playlist names, track names, artist names) without HTML escaping. The backend had gaps in exception handling and type safety that could leak internal details or crash on edge cases.

## Solution

### 1. XSS Prevention in Frontend

Added an HTML escape helper and applied it to all dynamic innerHTML interpolations:

```javascript
function esc(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

// Applied to all dynamic data in showResults():
// Playlist info
`<h2>${esc(pl.name)}</h2>`
`${esc(pl.action)} &middot; ...`
`<a href="${esc(pl.spotify_url)}" ...>`

// Matched tracks table
`<td>${esc(m.source_name)}</td>`
`<td>${esc(m.spotify_artist)} - ${esc(m.spotify_name)}</td>`

// Unmatched tracks list
`<li>- ${esc(t)}</li>`
```

### 2. Auth Callback Reflected XSS

```python
# Before: raw error param in HTML
return HTMLResponse(f"<p>{error}</p>", status_code=400)

# After: escaped with html.escape()
from html import escape
return HTMLResponse(f"<p>{escape(error)}</p>", status_code=400)
```

### 3. Exception Leak Prevention

```python
# Before: raw exception to client
except Exception as e:
    job.error = str(e)

# After: log internally, generic message to client
except Exception as e:
    logger.exception("Sync failed")
    job.error = "An unexpected error occurred during sync"
```

### 4. Type Safety Restoration

Replaced `**kwargs` in `_cli_match_and_sync` with explicit keyword-only parameters:

```python
def _cli_match_and_sync(
    tracks: list[Track],
    playlist_name: str,
    playlist_path: str,
    *,
    sp: spotipy.Spotify,
    cache: MatchCache | None,
    state_mgr: PlaylistStateManager | None,
    existing_playlists: dict[str, str] | None,
    threshold: int,
    dry_run: bool,
    incremental: bool,
    prefix: str | None,
    retry_days: int = 7,
    retry: bool = False,
    source_type: str = "rekordbox",
) -> PlaylistReport:
```

Used `from __future__ import annotations` with `TYPE_CHECKING` to avoid circular imports.

### 5. Other Fixes

- **Deprecated asyncio**: `asyncio.get_event_loop()` → `asyncio.get_running_loop()`
- **Auth refresh crash**: Wrapped `refresh_access_token()` in try/except
- **load_dotenv timing**: Moved to FastAPI `lifespan` context manager
- **Dead DOM refs**: Removed `getElementById('matched-count')` / `getElementById('unmatched-count')` from `resetUI()`
- **Type hint**: `state_mgr: PlaylistStateManager` → `state_mgr: PlaylistStateManager | None`

## Prevention

### innerHTML Safety

- Always use `esc()` when interpolating dynamic data into innerHTML
- Prefer `.textContent` for plain text content
- Quick check: `grep "\.innerHTML.*\${" djsupport/static/` — every match should use `esc()`

### Exception Handling Pattern

- Log full tracebacks with `logger.exception()` for debugging
- Return hardcoded/generic error messages to clients
- Quick check: `grep "detail=str(e)" djsupport/` should return no results

### Type Safety in Wrappers

- Avoid `**kwargs` when the forwarded parameters are known — use explicit params
- Use `TYPE_CHECKING` for import-heavy type annotations
- Quick check: `grep "\*\*kwargs" djsupport/` — each use should be justified

## Related Documentation

- [Rate limit handling](../integration-issues/spotify-rate-limit-handling.md) — related error handling patterns
- [Architectural patterns](../../.claude/docs/architectural_patterns.md) — error handling conventions
- [Web frontend plan](../plans/2026-03-14-feat-web-frontend-beatport-sync-plan.md) — feature context
