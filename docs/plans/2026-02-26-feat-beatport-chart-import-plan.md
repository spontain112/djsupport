---
title: "feat: Add Beatport DJ chart import"
type: feat
status: completed
date: 2026-02-26
deepened: 2026-02-26
---

# feat: Add Beatport DJ chart import

New CLI command `djsupport beatport <chart-url>` that scrapes a Beatport DJ chart page, extracts track metadata, fuzzy-matches tracks against Spotify, and creates a playlist.

Beatport chart pages embed all track data as server-rendered JSON in a `__NEXT_DATA__` script tag — no headless browser needed. A simple `requests` + `json` + regex approach works. `robots.txt` allows scraping (`Allow: /`).

## Enhancement Summary

**Deepened on:** 2026-02-26
**Sections enhanced:** 7
**Research agents used:** web scraping best practices, cache architecture, Python reviewer, security sentinel, architecture strategist, performance oracle, code simplicity reviewer, spec flow analyzer, pattern recognition, Beatport page structure validator

### Key Improvements from Original Plan
1. **Separate cache and state files** — Beatport uses its own `.djsupport_beatport_cache.json` and `.djsupport_beatport_playlists.json`, fully isolated from Rekordbox
2. **Drop BeautifulSoup dependency** — regex extraction of `__NEXT_DATA__` is simpler and eliminates a dependency
3. **Fix validate_url** — use domain exception instead of `click.BadParameter` (separation of concerns)
4. **Defensive JSON traversal** — wrap deep key access in try/except with actionable `BeatportParseError` messages
5. **Robust duration parsing** — handle H:MM:SS, invalid input, and extraction to a testable function
6. **Anti-bot detection awareness** — Beatport has a custom anti-bot system; plan includes detection and clear user messaging
7. **Shared pipeline helper** — extract `_match_and_sync_playlist()` from `sync` to avoid ~80 lines of duplication
8. **Source-agnostic state model** — rename `rekordbox_path` → `source_path`, add `source_type`, bump STATE_VERSION to 2

### New Considerations Discovered
- Beatport has a custom anti-bot system (proof-of-work + CAPTCHA) that may block requests; the [Beatporter](https://github.com/rootshellz/Beatporter) project uses Selenium as a workaround
- Beatport has an API v4 (`api.beatport.com/v4/`) but it requires Beatport account auth — scraping is simpler for v1
- If Beatport migrates from Next.js Pages Router to App Router (RSC), `__NEXT_DATA__` disappears; detection + clear error messaging needed
- `MatchedTrack.rekordbox_name` and `SyncReport` Markdown headers are Rekordbox-specific — need renaming for source-agnostic reports

---

## Acceptance Criteria

- [x] `djsupport beatport <url>` accepts a Beatport DJ chart URL (e.g., `https://www.beatport.com/chart/garage-go-tos/815070`)
- [x] Validates URL is a `beatport.com/chart/` path before fetching (HTTPS enforced)
- [x] Extracts track metadata from `__NEXT_DATA__` JSON: artist(s), title, mix name, label, genre, BPM, key, ISRC, duration
- [x] Converts tracks to existing `Track` dataclass (reuses `matcher.py` as-is)
- [x] Creates Spotify playlist named using existing prefix convention (e.g., `djsupport / Garage Go-Tos`)
- [x] Preserves chart track ordering in the Spotify playlist
- [x] Shows chart metadata before matching: "Chart: {name} by {curator}. {count} tracks."
- [x] Supports flags: `--dry-run`, `--threshold`, `--no-cache`, `--prefix`, `--no-prefix`, `--report`, `--cache-path`, `--state-path`, `--incremental`
- [x] Handles errors gracefully: invalid URL, 404, network timeout, changed page structure, anti-bot challenge
- [x] Uses **separate** cache (`.djsupport_beatport_cache.json`) and state (`.djsupport_beatport_playlists.json`) from Rekordbox
- [x] Reports matched/unmatched tracks with chart positions for unmatched
- [x] Tests cover parser, URL validation, error handling, duration parsing, and CLI integration
- [x] Re-importing the same chart URL updates the existing Spotify playlist (via state lookup by chart URL)
- [x] `.gitignore` updated for new Beatport files
- [x] `CLAUDE.md` updated with new module, command, and files

---

## Context

- **Data access**: Beatport embeds track data as JSON in `<script id="__NEXT_DATA__">`. Path: `props.pageProps.dehydratedState.queries[N].state.data.results` (array of track objects). Each track has `name`, `mix_name`, `artists[]`, `release.label`, `genre`, `bpm`, `key`, `isrc`, `publish_date`, `length`. Confirmed live on 2026-02-26.
- **No new matching logic needed**: `matcher.py` is already source-agnostic. Beatport tracks go through the same 5-strategy fuzzy matching pipeline.
- **ISRC available but deferred**: Beatport provides ISRC codes per track. These could enable exact Spotify lookups (Strategy 0), but that's a separate enhancement — v1 uses fuzzy matching only. This is the single highest-impact future optimization (could reduce API calls by 80-90%).
- **Dependencies**: Add `requests>=2.28` to `pyproject.toml`. No BeautifulSoup needed — regex extraction is sufficient.
- **Rate limits**: Spotify rate limit handling already exists (`RateLimitError`). For Beatport: single-page fetch per invocation, well within any implicit limits.
- **Flags not applicable**: `--all`, `--all-name`, `--playlist`, `--retry`, `--retry-days` don't apply to single-chart import — omit from the beatport command.
- **Anti-bot measures**: Beatport has a custom anti-bot system with proof-of-work challenges and image CAPTCHA. Single-page fetches with a realistic User-Agent are expected to work, but the code must detect and report challenge pages clearly.
- **Beatport API v4**: Exists at `api.beatport.com/v4/` but requires Beatport account authentication — not viable for v1. Documented as a fallback path.
- **robots.txt**: Confirmed `Allow: /` with no `Disallow` rules. Scraping is permitted.

---

## Preparatory Refactoring (before Beatport feature)

These changes make the codebase source-agnostic, benefiting both the existing Rekordbox workflow and the new Beatport feature.

### 1. Rename `PlaylistState.rekordbox_path` → `source_path` + add `source_type`

```python
# state.py
STATE_VERSION = 2  # bumped from 1

@dataclass
class PlaylistState:
    spotify_id: str
    spotify_name: str
    source_path: str            # was: rekordbox_path
    last_synced: str
    prefix_used: str | None
    source_type: str = "rekordbox"  # "rekordbox" | "beatport"
```

Add v1 migration in `load()`:
```python
def load(self) -> None:
    # ... existing file read ...
    version = data.get("version")
    if version == 1:
        for key, entry in data.get("entries", {}).items():
            if "rekordbox_path" in entry:
                entry["source_path"] = entry.pop("rekordbox_path")
                entry.setdefault("source_type", "rekordbox")
            self.entries[key] = PlaylistState(**entry)
        return
    if version != STATE_VERSION:
        return
    # ... normal v2 load ...
```

Update `spotify.py` — `create_or_update_playlist` and `incremental_update_playlist` pass `source_path=name, source_type="rekordbox"` (backward-compatible default).

### 2. Rename `MatchedTrack.rekordbox_name` → `source_name`

```python
# report.py
@dataclass
class MatchedTrack:
    source_name: str          # was: rekordbox_name
    spotify_name: str
    spotify_artist: str
    score: float
    match_type: str = "exact"
```

Add `source_label` to `SyncReport` for Markdown headers:
```python
@dataclass
class SyncReport:
    # ... existing fields ...
    source_label: str = "Rekordbox"  # "Rekordbox" or "Beatport"
```

Update `save_report` table header: `| {report.source_label} | Spotify Match | ...`

### 3. Extract shared matching pipeline in `cli.py`

```python
def _match_and_sync_playlist(
    tracks: list[Track],
    playlist_name: str,
    playlist_path: str,
    *,
    sp,
    cache: MatchCache | None,
    state_mgr: PlaylistStateManager,
    existing_playlists: dict[str, str] | None,
    threshold: int,
    dry_run: bool,
    incremental: bool,
    prefix: str | None,
    cache_path: str,
    source_type: str = "rekordbox",
) -> PlaylistReport:
    """Match tracks to Spotify and create/update a playlist. Returns report."""
    # Progress bar, matching loop, URI dedup, playlist creation, RateLimitError handling
    # Extracted from sync command lines 195-280
```

Both `sync` and `beatport` call this helper. The `sync` command resolves track IDs to `Track` objects first; `beatport` passes tracks directly.

---

## MVP Implementation

### djsupport/beatport.py

```python
"""Beatport DJ chart scraper."""

import json
import re

import requests

from djsupport.rekordbox import Track

BEATPORT_CHART_URL_PREFIX = "beatport.com/chart/"
BEATPORT_CHART_PATTERN = re.compile(
    r"^https://(www\.)?beatport\.com/chart/[\w-]+/\d+/?$"
)
USER_AGENT = "Mozilla/5.0 (compatible; djsupport/0.3.0)"
REQUEST_TIMEOUT = (5, 30)  # (connect, read) seconds
MAX_RESPONSE_SIZE = 5 * 1024 * 1024  # 5 MB


class BeatportParseError(Exception):
    """Raised when chart page structure cannot be parsed."""


class InvalidBeatportURL(ValueError):
    """Raised when a URL is not a valid Beatport chart URL."""


def validate_url(url: str) -> str:
    """Validate and normalize a Beatport chart URL.

    Raises InvalidBeatportURL if the URL doesn't match the expected pattern.
    """
    url = url.split("?")[0].rstrip("/")  # strip query params and trailing slash
    if not BEATPORT_CHART_PATTERN.match(url):
        raise InvalidBeatportURL(
            f"Not a valid Beatport chart URL: {url}\n"
            "Expected: https://www.beatport.com/chart/<name>/<id>"
        )
    return url


def fetch_chart(url: str) -> tuple[str, str, list[Track]]:
    """Fetch and parse a Beatport DJ chart page.

    Returns (chart_name, curator, tracks) where tracks are ordered by chart position.
    Raises BeatportParseError on structure issues, requests.RequestException on network issues.
    """
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
        stream=True,
    )
    response.raise_for_status()

    # Read with size limit
    chunks = []
    size = 0
    for chunk in response.iter_content(chunk_size=8192, decode_unicode=False):
        size += len(chunk)
        if size > MAX_RESPONSE_SIZE:
            response.close()
            raise BeatportParseError("Response too large — does not look like a chart page.")
        chunks.append(chunk)
    html = b"".join(chunks).decode(response.encoding or "utf-8")

    # Validate final URL after redirects
    final_url = response.url
    if BEATPORT_CHART_URL_PREFIX not in final_url:
        raise BeatportParseError(
            f"Beatport redirected to an unexpected URL: {final_url}"
        )

    # Extract __NEXT_DATA__ JSON via regex (no BeautifulSoup needed)
    match = re.search(
        r'<script\s+id="__NEXT_DATA__"\s*[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        # Detect anti-bot challenge page
        if "/human-test/" in html or "findProof" in html:
            raise BeatportParseError(
                "Beatport returned an anti-bot challenge page. "
                "This may be temporary — try again in a few minutes."
            )
        raise BeatportParseError(
            "Could not find chart data on page. "
            "Beatport may have changed their page structure."
        )

    data = json.loads(match.group(1))
    return _parse_chart_data(data, url)


def _parse_chart_data(data: dict, url: str) -> tuple[str, str, list[Track]]:
    """Extract chart info and tracks from __NEXT_DATA__ JSON."""
    try:
        queries = data["props"]["pageProps"]["dehydratedState"]["queries"]
    except (KeyError, TypeError) as e:
        raise BeatportParseError(
            f"Unexpected page data structure (missing key: {e}). "
            "Beatport may have changed their page format."
        ) from e

    # Find the query containing track results
    track_query = None
    for q in queries:
        if not isinstance(q, dict):
            continue
        results = q.get("state", {}).get("data", {}).get("results")
        if isinstance(results, list) and results and isinstance(results[0], dict):
            if "artists" in results[0]:
                track_query = q
                break

    if not track_query:
        raise BeatportParseError(
            f"Could not locate track data in chart page queries. "
            f"Found {len(queries)} queries but none contained track results."
        )

    results = track_query["state"]["data"]["results"]

    # Extract chart metadata from page props
    page_props = data["props"]["pageProps"]
    chart_name = page_props.get("chart", {}).get("name", "Unknown Chart")
    curator = page_props.get("chart", {}).get("dj", {}).get("name", "Unknown")

    tracks = [_parse_track(item, i) for i, item in enumerate(results)]
    return chart_name, curator, tracks


def _parse_duration(length_str: str) -> int:
    """Parse a duration string like '4:44' or '1:04:30' to seconds.

    Returns 0 on unparseable input.
    """
    if not length_str or ":" not in length_str:
        return 0
    parts = length_str.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        return 0
    return 0


def _parse_track(item: dict, position: int) -> Track:
    """Convert a Beatport track JSON object to a Track dataclass."""
    raw_artists = item.get("artists", [])
    if not isinstance(raw_artists, list):
        raw_artists = []
    artists = ", ".join(
        a["name"] for a in raw_artists
        if isinstance(a, dict) and "name" in a
    )

    mix_name = item.get("mix_name", "")
    title = item.get("name", "")

    # Append mix name if it's not "Original Mix" (adds noise to matching)
    if mix_name and mix_name != "Original Mix":
        title = f"{title} ({mix_name})"

    return Track(
        track_id=f"bp-{item.get('id', position)}",
        name=title,
        artist=artists,
        album=item.get("release", {}).get("name", ""),
        remixer="",
        label=item.get("release", {}).get("label", {}).get("name", ""),
        genre=item.get("genre", {}).get("name", ""),
        date_added="",
        duration=_parse_duration(item.get("length", "")),
    )
```

### Research Insights: beatport.py

**Best Practices Applied:**
- `InvalidBeatportURL` is a domain exception, not `click.BadParameter` — keeps `beatport.py` independent of CLI framework
- `_parse_duration()` extracted as a testable function handling M:SS, H:MM:SS, and invalid input
- Type guards on `artists` list and `results[0]` dict protect against malformed JSON
- `stream=True` with 5MB size limit prevents memory exhaustion from malicious responses
- Redirect validation after request prevents SSRF via redirect following
- Anti-bot challenge detection provides a clear, actionable error message
- Tuple timeout `(5, 30)` — fast failure on DNS/connection issues, patient for response

**Edge Cases Handled:**
- URL with query parameters (stripped before validation)
- URL with trailing slash (stripped)
- Beatport redirect to non-chart page (detected and reported)
- Anti-bot challenge page (detected via `/human-test/` marker)
- Missing or malformed artists list (type guard)
- Duration in H:MM:SS format (3-part split)
- Non-numeric duration values (try/except returns 0)
- `__NEXT_DATA__` missing entirely (Next.js migration detection)

**Performance Notes:**
- BeautifulSoup replaced with regex — eliminates dependency, ~100ms faster (though network dominates)
- Single HTTP request per invocation — no session pooling needed
- Charts are 10-100 tracks — the existing early exit optimization handles this comfortably

---

### djsupport/cli.py (new command)

```python
DEFAULT_BEATPORT_CACHE_PATH = ".djsupport_beatport_cache.json"
DEFAULT_BEATPORT_STATE_PATH = ".djsupport_beatport_playlists.json"

@cli.command()
@click.argument("url")
@click.option("--dry-run", is_flag=True, help="Preview without modifying Spotify.")
@click.option("--threshold", "-t", default=80, show_default=True, help="Minimum match confidence (0-100).")
@click.option("--no-cache", is_flag=True, help="Bypass match cache.")
@click.option("--cache-path", default=DEFAULT_BEATPORT_CACHE_PATH, show_default=True, help="Path to Beatport match cache.")
@click.option("--state-path", default=DEFAULT_BEATPORT_STATE_PATH, show_default=True, help="Path to Beatport playlist state.")
@click.option("--report", "report_path", type=click.Path(), default=None, help="Save Markdown report.")
@click.option("--prefix", default="djsupport", show_default=True, help="Prefix for Spotify playlist name.")
@click.option("--no-prefix", is_flag=True, help="Disable playlist name prefix.")
@click.option("--incremental/--no-incremental", default=True, show_default=True, help="Use incremental playlist updates.")
def beatport(
    url: str,
    dry_run: bool,
    threshold: int,
    no_cache: bool,
    cache_path: str,
    state_path: str,
    report_path: str | None,
    prefix: str,
    no_prefix: bool,
    incremental: bool,
) -> None:
    """Create a Spotify playlist from a Beatport DJ chart.

    URL is a Beatport chart page, e.g.:
    https://www.beatport.com/chart/garage-go-tos/815070
    """
    from djsupport.beatport import validate_url, fetch_chart, BeatportParseError, InvalidBeatportURL

    try:
        url = validate_url(url)
    except InvalidBeatportURL as e:
        raise click.BadParameter(str(e))

    click.echo("Fetching chart from Beatport...")
    try:
        chart_name, curator, tracks = fetch_chart(url)
    except BeatportParseError as e:
        raise click.ClickException(str(e))
    except requests.RequestException as e:
        if hasattr(e, 'response') and e.response is not None and e.response.status_code == 404:
            raise click.ClickException("Chart not found — check the URL.")
        raise click.ClickException(f"Failed to fetch chart: {e}")

    if not tracks:
        click.echo(f"Chart '{chart_name}' has no tracks.")
        return

    click.echo(f"Chart: {chart_name} by {curator}. {len(tracks)} tracks.")

    # Initialize cache (separate from Rekordbox)
    cache = None
    if not no_cache:
        from djsupport.cache import MatchCache
        cache = MatchCache(cache_path)
        cache.load()
        if cache.entries:
            click.echo(f"Loaded {len(cache.entries)} cached Beatport matches from {cache_path}")

    # Resolve prefix
    actual_prefix = None if no_prefix else prefix

    # Initialize Beatport-specific playlist state
    from djsupport.state import PlaylistStateManager
    state_mgr = PlaylistStateManager(state_path)
    state_mgr.load()

    # Spotify client
    sp = get_client()
    existing = get_user_playlists(sp) if not dry_run else None

    # Match and sync via shared helper
    report = SyncReport(
        timestamp=datetime.now(),
        threshold=threshold,
        dry_run=dry_run,
        cache_enabled=cache is not None,
        source_label="Beatport",
    )

    pl_report = _match_and_sync_playlist(
        tracks=tracks,
        playlist_name=chart_name,
        playlist_path=url,  # chart URL as the source path
        sp=sp,
        cache=cache,
        state_mgr=state_mgr,
        existing_playlists=existing,
        threshold=threshold,
        dry_run=dry_run,
        incremental=incremental,
        prefix=actual_prefix,
        cache_path=cache_path,
        source_type="beatport",
    )
    report.playlists.append(pl_report)

    # Save cache
    if cache is not None:
        cache.save()

    # Save state
    if not dry_run:
        state_mgr.save()

    print_report(report)
    if report_path:
        save_report(report, report_path)
        click.echo(f"\nDetailed report saved to {report_path}")
```

### Research Insights: CLI Command

**Flags dropped from original plan:**
- `--retry` / `--retry-days` — These retry previously failed cache entries. For a first Beatport import there are no failures to retry, and on re-import `--no-cache` is the simpler UX. Can be added later if needed.

**Separate file defaults:**
- Cache: `.djsupport_beatport_cache.json` (not shared with Rekordbox)
- State: `.djsupport_beatport_playlists.json` (not shared with Rekordbox)
- User can still override with `--cache-path` / `--state-path`

**Re-import behavior:**
- Same chart URL → `state_mgr.get(chart_name)` finds the existing Spotify playlist ID → incremental update adds new tracks, removes stale ones
- Different chart URL → creates a new playlist

**Edge cases handled:**
- Empty chart (0 tracks) — early return with message
- 404 from Beatport — special-cased error message: "Chart not found — check the URL"
- All tracks unmatched — playlist still created (empty or with 0 tracks, consistent with sync)

---

### tests/test_beatport.py

```python
"""Tests for Beatport chart scraper."""

import json
import pytest
from unittest.mock import patch, MagicMock

from djsupport.beatport import (
    validate_url,
    fetch_chart,
    _parse_chart_data,
    _parse_track,
    _parse_duration,
    BeatportParseError,
    InvalidBeatportURL,
)
from djsupport.rekordbox import Track


class TestValidateUrl:
    def test_valid_url(self):
        assert validate_url("https://www.beatport.com/chart/garage-go-tos/815070")

    def test_valid_url_no_www(self):
        assert validate_url("https://beatport.com/chart/garage-go-tos/815070")

    def test_strips_trailing_slash(self):
        result = validate_url("https://www.beatport.com/chart/test/123/")
        assert not result.endswith("/")

    def test_strips_query_params(self):
        result = validate_url("https://www.beatport.com/chart/test/123?utm_source=share")
        assert "?" not in result

    def test_rejects_http(self):
        with pytest.raises(InvalidBeatportURL):
            validate_url("http://www.beatport.com/chart/test/123")

    def test_rejects_non_chart_url(self):
        with pytest.raises(InvalidBeatportURL):
            validate_url("https://www.beatport.com/track/some-track/12345")

    def test_rejects_non_beatport_url(self):
        with pytest.raises(InvalidBeatportURL):
            validate_url("https://example.com/chart/foo/123")

    def test_rejects_chart_listing_page(self):
        with pytest.raises(InvalidBeatportURL):
            validate_url("https://www.beatport.com/charts")


class TestParseDuration:
    def test_minutes_seconds(self):
        assert _parse_duration("4:44") == 284

    def test_hours_minutes_seconds(self):
        assert _parse_duration("1:04:30") == 3870

    def test_empty_string(self):
        assert _parse_duration("") == 0

    def test_no_colon(self):
        assert _parse_duration("284") == 0

    def test_invalid_numbers(self):
        assert _parse_duration("4:ab") == 0

    def test_trailing_colon(self):
        assert _parse_duration("4:") == 0


class TestParseTrack:
    def test_basic_track(self):
        item = {
            "id": 12345,
            "name": "Sinkhole",
            "mix_name": "Original Mix",
            "artists": [{"name": "Pearson Sound"}],
            "release": {"name": "Sinkhole EP", "label": {"name": "Hessle Audio"}},
            "genre": {"name": "UK Garage / Bassline"},
            "bpm": 129,
            "length": "4:44",
        }
        track = _parse_track(item, 0)
        assert track.name == "Sinkhole"  # Original Mix omitted
        assert track.artist == "Pearson Sound"
        assert track.label == "Hessle Audio"
        assert track.duration == 284
        assert track.track_id == "bp-12345"

    def test_remix_track(self):
        item = {
            "id": 67890,
            "name": "Vibe",
            "mix_name": "Radio Edit",
            "artists": [{"name": "Artist A"}, {"name": "Artist B"}],
            "release": {"name": "Vibe EP", "label": {"name": "Label X"}},
            "genre": {"name": "House"},
            "length": "3:30",
        }
        track = _parse_track(item, 1)
        assert track.name == "Vibe (Radio Edit)"
        assert track.artist == "Artist A, Artist B"
        assert track.duration == 210

    def test_missing_artists(self):
        item = {"id": 1, "name": "Test", "mix_name": "", "length": "3:00"}
        track = _parse_track(item, 0)
        assert track.artist == ""

    def test_malformed_artists(self):
        item = {"id": 1, "name": "Test", "artists": "not a list", "length": "3:00"}
        track = _parse_track(item, 0)
        assert track.artist == ""


class TestParseChartData:
    def test_missing_top_level_keys(self):
        with pytest.raises(BeatportParseError, match="missing key"):
            _parse_chart_data({"props": {}}, "https://example.com")

    def test_empty_queries(self):
        data = {"props": {"pageProps": {"dehydratedState": {"queries": []}}}}
        with pytest.raises(BeatportParseError, match="Could not locate"):
            _parse_chart_data(data, "https://example.com")


class TestFetchChart:
    @patch("djsupport.beatport.requests.get")
    def test_missing_next_data(self, mock_get):
        mock_response = MagicMock()
        mock_response.iter_content.return_value = [b"<html><body>No data</body></html>"]
        mock_response.encoding = "utf-8"
        mock_response.url = "https://www.beatport.com/chart/test/123"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        with pytest.raises(BeatportParseError, match="Could not find chart data"):
            fetch_chart("https://www.beatport.com/chart/test/123")

    @patch("djsupport.beatport.requests.get")
    def test_anti_bot_detection(self, mock_get):
        mock_response = MagicMock()
        mock_response.iter_content.return_value = [b"<html>/human-test/start</html>"]
        mock_response.encoding = "utf-8"
        mock_response.url = "https://www.beatport.com/chart/test/123"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        with pytest.raises(BeatportParseError, match="anti-bot"):
            fetch_chart("https://www.beatport.com/chart/test/123")

    @patch("djsupport.beatport.requests.get")
    def test_redirect_to_non_chart_rejected(self, mock_get):
        mock_response = MagicMock()
        mock_response.iter_content.return_value = [b"<html></html>"]
        mock_response.encoding = "utf-8"
        mock_response.url = "https://www.beatport.com/login"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        with pytest.raises(BeatportParseError, match="redirected"):
            fetch_chart("https://www.beatport.com/chart/test/123")
```

### Research Insights: Testing

**Test fixture strategy:** Save a real Beatport chart page's `__NEXT_DATA__` JSON as `tests/fixtures/beatport_chart_data.json` for integration-level parser tests. This gives fast, reliable, offline tests. Strip any user-session data before committing.

**Structure validation tests:** Add `TestFixtureStructure` class that validates the fixture matches expected JSON paths — serves as an early warning when Beatport changes their page structure.

**State migration tests:** Add tests for v1 → v2 `PlaylistState` migration (rename `rekordbox_path` → `source_path`, add `source_type` default).

---

### pyproject.toml changes

```toml
dependencies = [
    # ... existing deps ...
    "requests>=2.28",
]
```

No `beautifulsoup4` needed.

### .gitignore additions

```
.djsupport_beatport_cache.json
.djsupport_beatport_playlists.json
```

---

## Security Considerations

| Finding | Severity | Mitigation |
|---------|----------|------------|
| Unbounded response size | Medium | `stream=True` + 5MB limit |
| Redirect following to arbitrary hosts | Medium | Validate `response.url` contains `beatport.com/chart/` |
| HTTP allowed (not just HTTPS) | Low | Enforce `https://` in regex |
| Anti-bot challenge page | Low | Detect `/human-test/` marker, clear error message |
| JSON traversal KeyError | Low | try/except → `BeatportParseError` with context |
| Track metadata from untrusted source | Low | Terminal escape sequences are cosmetic risk for local CLI |

---

## Performance Assessment

| Area | Verdict | Notes |
|------|---------|-------|
| HTML parsing | Non-issue | Regex extraction ~1ms vs BS4 ~100ms; network dominates |
| JSON parsing | Non-issue | 50-200KB blob, ~10ms |
| HTTP requests | Non-issue | Single request per invocation |
| Spotify API calls | Low concern | 10-100 tracks, early exit handles well; cold cache ~75 calls for 50 tracks |
| Memory | Non-issue | Peak ~3MB for large chart page |
| Cache warm-up | UX concern | Add progress bar; first run 30-60s for 50-track chart |

**Highest-impact future optimization:** ISRC-based Spotify lookup (Strategy 0) — would reduce API calls by 80-90% for Beatport tracks since ISRCs are available in the JSON.

---

## Implementation Order

1. **Prep commit: source-agnostic refactoring**
   - Rename `PlaylistState.rekordbox_path` → `source_path`, add `source_type`, bump STATE_VERSION to 2 with migration
   - Rename `MatchedTrack.rekordbox_name` → `source_name`, add `SyncReport.source_label`
   - Update `spotify.py` to pass `source_path` and `source_type` to `PlaylistState`
   - Update `cli.py` sync command to pass `source_name=track.display` and `source_label="Rekordbox"`
   - Update all tests for field renames
   - Extract `_match_and_sync_playlist()` helper from `sync` command

2. **Feature commit: Beatport chart import**
   - Add `djsupport/beatport.py`
   - Add `beatport` command to `cli.py`
   - Add `tests/test_beatport.py`
   - Add `requests>=2.28` to `pyproject.toml`
   - Update `.gitignore` with Beatport files

3. **Housekeeping commit**
   - Update `CLAUDE.md` with new module, command, and conventions
   - Update `CHANGELOG.md`

---

## Deferred Enhancements (not in v1)

- **ISRC-based matching (Strategy 0)** — Exact Spotify lookup before fuzzy matching. Highest-impact optimization.
- **Extract `Track` to `models.py`** — Cleaner semantics than importing from `rekordbox.py`, but not blocking.
- **Beatport API v4 fallback** — If anti-bot measures start blocking `requests`, switch to authenticated API.
- **Multiple chart URLs in one command** — `djsupport beatport <url1> <url2>` for batch import.
- **Remixer extraction from Beatport artist data** — Beatport artist objects have a `type` field (e.g., "remixer"). Populating `Track.remixer` would improve Strategy 3 accuracy.
- **XDG-compliant file paths** — Move dotfiles to `~/.cache/djsupport/` and `~/.local/state/djsupport/` via `platformdirs`.
- **`--retry` / `--retry-days` flags** — Add if users need to retry cached failures from Beatport imports.

---

## Sources

- Beatport chart page analysis: `__NEXT_DATA__` JSON confirmed live (2026-02-26)
- `robots.txt` at beatport.com: `Allow: /`, no Disallow rules
- Beatport API v4: `api.beatport.com/v4/docs/` (requires auth, not viable for v1)
- Beatport anti-bot system: custom proof-of-work + image CAPTCHA ([BuiltWith](https://builtwith.com/beatport.com))
- [Beatporter project](https://github.com/rootshellz/Beatporter): uses Selenium + BeautifulSoup (similar use case)
- [beatportdl](https://github.com/unspok3n/beatportdl): uses API v4 with auth
- [Scraping Next.js sites in 2025](https://www.trickster.dev/post/scraping-nextjs-web-sites-in-2025/): `__NEXT_DATA__` reliability and App Router migration risks
- Existing patterns: `djsupport/rekordbox.py`, `djsupport/matcher.py`, `djsupport/cache.py`, `djsupport/state.py`
- Rate limit handling: `docs/solutions/integration-issues/spotify-rate-limit-handling.md`
- Early exit optimization: `docs/solutions/performance-issues/spotify-api-calls-early-exit-optimization.md`
- URI deduplication: `docs/solutions/logic-errors/duplicate-spotify-uris-in-playlists-CLI-20260225.md`
