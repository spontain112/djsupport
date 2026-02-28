---
title: "Beatport label search API response format change breaks label discovery"
date: "2026-02-28"
module: "djsupport/label.py"
severity: "high"
tags:
  - beatport-api
  - label-search
  - response-parsing
  - backwards-compatibility
  - web-scraping
status: "resolved"
---

# Beatport Search API Format Change

## Problem Statement

The `djsupport label "Blindfold Recordings"` command returned 0 search results despite the label existing on Beatport with 148 tracks. The label was reachable via direct URL (`https://www.beatport.com/label/blindfold-recordings/43599`), but the name-based search produced no matches.

The root cause was a silent breaking change in Beatport's search API response structure. The `search_labels()` function expected results under `state.data.results` with fields `name`, `slug`, and `id`. Beatport changed this to `state.data.data` with fields `label_name` and `label_id`, dropping the `slug` field entirely.

## Root Cause Analysis

Beatport uses server-rendered Next.js pages with a `__NEXT_DATA__` JSON blob embedded in HTML. The label search response changed between formats:

**Old format (pre-February 2026):**
```json
{
  "state": {
    "data": {
      "results": [
        {"id": 43599, "name": "Blindfold Recordings", "slug": "blindfold-recordings"}
      ]
    }
  }
}
```

**New format (February 2026):**
```json
{
  "state": {
    "data": {
      "data": [
        {"label_id": 43599, "label_name": "Blindfold Recordings"}
      ]
    }
  }
}
```

Three breaking changes:
1. Results key moved from `results` to `data` (nested one level deeper)
2. Field `id` renamed to `label_id`
3. Field `name` renamed to `label_name`
4. Field `slug` removed entirely

The old code only checked `state_data.get("results")` and silently returned an empty list.

## What Was Tried

1. Ran `djsupport label "Blindfold Recordings"` — 0 results returned
2. Verified the label exists via direct URL fetch — 148 tracks found
3. Inspected the actual Beatport search response with Python debugging
4. Discovered the new response structure with renamed keys and fields
5. Implemented dual-format detection with field name fallbacks
6. Ran code review which identified 5 additional hardening fixes

## Solution

### 1. Dual-Format Detection (label.py)

Updated `search_labels()` to check both response keys:

```python
# Try new format first, fall back to old
candidates = state_data.get("data") or state_data.get("results")
if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict):
    if "label_name" in candidates[0] or "name" in candidates[0]:
        items = candidates
        break
```

Field extraction with fallbacks:

```python
label_id = item.get("label_id") or item.get("id", "")
name = item.get("label_name") or item.get("name", "Unknown")
slug = item.get("slug") or _slugify(name)
```

### 2. Slug Derivation (label.py)

Added `_slugify()` to generate URL slugs when Beatport no longer provides them:

```python
def _slugify(name: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", name.lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-")
```

### 3. Hardening Fixes (code review follow-up)

- **Removed `import click` from library code** — replaced with `on_page_error` callback to keep the scraper decoupled from the CLI framework
- **URL re-validation** — search result URLs are re-validated via `validate_label_url()` before fetching, closing a trust boundary gap
- **Pagination cap** — added `MAX_PAGES = 100` (15,000 track limit) to prevent runaway requests from corrupted `count` values
- **URL fragment stripping** — `validate_label_url()` now strips `#` fragments so browser-pasted URLs work
- **JSON error wrapping** — `_extract_next_data()` wraps `JSONDecodeError` in `LabelParseError` for consistent error reporting

## Prevention Strategies

### Why this will recur

Beatport scraping is inherently fragile — there is no versioned API contract. The `__NEXT_DATA__` structure is an internal Next.js implementation detail that can change without notice. Both `beatport.py` (charts) and `label.py` (labels) are vulnerable.

### How to minimize impact

1. **Dual-format parsing** — always check both old and new field names with fallbacks. The current code handles both v1 and v2 formats transparently.

2. **Centralize extraction logic** — the `_extract_next_data()` function and HTTP fetch patterns are duplicated between `beatport.py` and `label.py`. Extracting shared utilities would reduce the blast radius of future format changes.

3. **Fail with clear errors** — wrap JSON parsing errors, validate constructed URLs, and report which structure was expected vs. found.

4. **Test both formats** — maintain test fixtures for old and new response formats. When a new format appears, add it to the test matrix rather than replacing the old one.

### How to detect format changes early

- If `search_labels()` returns 0 results for a known label, the format likely changed
- The `_extract_next_data()` function will raise `LabelParseError` if the page structure changes more drastically (e.g., `__NEXT_DATA__` removed entirely)
- Consider adding a periodic live integration test that hits a known label search

## Testing

67 tests cover the label module including:
- 5 tests for new-format search responses
- 5 tests for old-format search responses (backward compatibility)
- 4 tests for `_slugify()` edge cases
- 2 tests for URL fragment stripping
- 1 test for JSON error handling in `_extract_next_data()`
- 2 tests for `on_page_error` callback
- 1 test for `MAX_PAGES` pagination cap

## Related Documentation

- [Beatport fuzzy matcher: version tags and duration penalty](../logic-errors/beatport-fuzzy-matcher-version-tags-and-duration-penalty.md) — version tag handling patterns shared between chart and label imports
- [Spotify rate limit handling](./spotify-rate-limit-handling.md) — rate limit protection applies to label imports (500+ tracks = 500+ API calls)
- [Beatport label discovery plan](../../plans/2026-02-28-feat-beatport-label-discovery-plan.md) — feature specification
- [Beatport chart import plan](../../plans/2026-02-26-feat-beatport-chart-import-plan.md) — established `__NEXT_DATA__` extraction patterns

## Key Commits

- `a9264ab` — fix: update label search to handle new Beatport API response format
- `4badcd6` — fix: harden label scraper based on code review findings
