---
title: "Spotify API rate limit causing silent 22-hour hang"
date: 2026-02-24
category: integration-issues
tags:
  - spotify-api
  - rate-limiting
  - error-handling
  - spotipy
  - resilience
modules:
  - spotify.py
  - cli.py
severity: high
status: resolved
symptoms:
  - CLI hangs silently on 429 rate limit with long Retry-After
  - No user feedback during extended wait
  - No way to resume sync after interruption
  - Progress lost when user kills hung process
---

# Spotify API Rate Limit Causing Silent 22-Hour Hang

## Problem Statement

When syncing a large Rekordbox library (3,655 tracks, 167 playlists) to Spotify, the CLI exhausted Spotify's daily API quota. Spotify returned HTTP 429 with `Retry-After: 79166` (~22 hours). Spotipy's built-in retry mechanism silently called `time.sleep(79166)` with no user feedback, no cache save, and no way to resume.

The tool appeared completely hung. Users had to kill the process, losing all matching progress.

## Investigation

1. User ran `djsupport sync --dry-run` on all 167 playlists — up to ~18,000 API calls (5 search strategies per track)
2. After ~40 playlists, Spotify's daily quota was exhausted
3. Spotipy's default behavior: sleep for the full `Retry-After` duration, no upper bound
4. Initial fix set `retries=0` on spotipy client + custom wrapper, but code review (6 parallel agents) found 8 issues:
   - `retries=0` broke resilience for transient 5xx errors
   - Unprotected double-429 on retry (crash instead of graceful error)
   - No defensive parsing of `Retry-After` header (non-numeric values cause ValueError)
   - Misleading error message claiming cache was saved (exception doesn't know about cache)
   - Missing type hints, unused imports, dead variables
   - Zero test coverage for rate limit handling

## Root Cause

Spotipy's built-in retry has no upper bound on sleep duration. When Spotify returns `Retry-After: 79166`, spotipy calls `time.sleep(79166)` — approximately 22 hours of silent waiting with no user feedback or interrupt mechanism.

## Solution

Three commits across `spotify.py`, `cli.py`, and `tests/test_spotify.py`:

### 1. `RateLimitError` exception with human-readable formatting

```python
MAX_RATE_LIMIT_WAIT = 60  # seconds — abort if Spotify asks us to wait longer

class RateLimitError(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        # Formats as "22h 6m", "2m 5s", or "45s"
        super().__init__(f"Spotify rate limit exceeded. Retry after {wait_str}. ...")
```

### 2. `_api_call_with_rate_limit` wrapper

```python
def _api_call_with_rate_limit(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return func(*args, **kwargs)
    except spotipy.SpotifyException as e:
        if e.http_status == 429:
            retry_after = _parse_retry_after(e)
            if retry_after <= MAX_RATE_LIMIT_WAIT:
                time.sleep(retry_after)
                try:
                    return func(*args, **kwargs)
                except spotipy.SpotifyException as e2:
                    if e2.http_status == 429:
                        raise RateLimitError(_parse_retry_after(e2)) from e2
                    raise
            raise RateLimitError(retry_after) from e
        raise
```

Key design decisions:
- Short waits (<=60s) retried automatically — transparent to caller
- Long waits raise `RateLimitError` — CLI handles abort
- Double-429 protected — retry failure raises controlled error, not crash
- Applied to `search_track` (the hot path); spotipy's built-in retries cover playlist ops

### 3. Defensive `Retry-After` parsing

```python
def _parse_retry_after(exc: spotipy.SpotifyException) -> int:
    try:
        raw = exc.headers.get("Retry-After", 0) if exc.headers else 0
        return max(int(raw), 1)  # floor at 1s to avoid busy-loop
    except (ValueError, TypeError):
        return 1
```

Handles: non-numeric RFC 7231 date strings, negative values, missing headers, `None` headers dict.

### 4. CLI graceful abort

```python
except RateLimitError as e:
    click.echo(f"\n{e}", err=True)
    if cache is not None:
        cache.save()
        click.echo(f"Cache saved to {cache_path} ({len(cache.entries)} entries).", err=True)
    print_report(report)
    sys.exit(1)
```

On rate limit: saves cache, prints partial report, exits non-zero.

### 5. Restored default spotipy retries

Removed `retries=0` — spotipy's built-in retry (default 3) handles transient 5xx errors on all API calls. The custom wrapper adds rate limit control on top for search operations.

## Prevention Strategies

- **Cache aggressively**: `--dry-run` saves cache without modifying Spotify. Resume later with cached matches.
- **Sync incrementally**: Use `--playlist "Name"` to sync smaller batches instead of all 167 playlists at once.
- **Monitor progress**: Progress bar shows track count and ETA. Rate limit errors show exact wait time.
- **Implemented**: Early exit in `match_track` when Strategy 1 finds a high-confidence exact match (score >= 95) skips remaining strategies, reducing API calls by 40-60%. See `EARLY_EXIT_THRESHOLD` in `matcher.py`.

## Test Coverage

17 tests in `tests/test_spotify.py`:

- `TestRateLimitError` (4 tests): seconds/minutes/hours formatting, no cache mention in message
- `TestApiCallWithRateLimit` (8 tests): short retry, long abort, double-429, zero floor, non-429 passthrough, success, missing headers, non-numeric headers
- `TestParseRetryAfter` (5 tests): numeric, zero, negative, non-numeric, None headers

## Related Documentation

- [Architectural patterns](.claude/docs/architectural_patterns.md) — `RateLimitError` is the 4th error handling pattern
- [CHANGELOG.md](CHANGELOG.md) — Documented under [Unreleased]
- [Gitignore drift solution](docs/solutions/integration-issues/outdated-claude-md-and-gitignore-drift.md) — Related project documentation framework

## Commits

- `b7859ac` — Core rate limit handling, tests, code cleanup
- `9a6cdf6` — Architectural docs update
- `ea11e4e` — Defensive Retry-After header parsing
