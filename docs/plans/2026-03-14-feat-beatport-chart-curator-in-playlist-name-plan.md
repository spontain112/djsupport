---
title: "feat: Prepend Beatport chart curator to Spotify playlist names"
type: feat
status: completed
date: 2026-03-14
---

# feat: Prepend Beatport chart curator to Spotify playlist names

## Overview

Beatport chart playlists synced to Spotify are currently named only by chart name (e.g. "Tech House Vibes"). The curator/DJ who created the chart is already extracted from Beatport's `__NEXT_DATA__` JSON but explicitly discarded in both `cli.py` and `service.py`. This feature prepends the curator name so the Spotify playlist becomes `"Adam Beyer - Tech House Vibes"` (with prefix: `"djsupport / Adam Beyer - Tech House Vibes"`).

**Scope:** Beatport charts only — label imports are not affected.

## Problem Statement / Motivation

When browsing Spotify playlists synced from Beatport, there's no way to tell who curated the chart. For DJs who follow specific artists' chart picks, the curator name is essential context. The data is already available — it's just being thrown away.

## Proposed Solution

1. Add a `compose_chart_playlist_name(chart_name, curator)` helper in `beatport.py`
2. Use it in both `cli.py` and `service.py` call sites

No state migration needed — existing Beatport playlists won't be re-synced. New syncs will use the curator-prefixed name going forward.

### Name composition rules

| Curator value | Result |
|---|---|
| `"Adam Beyer"` | `"Adam Beyer - Tech House Vibes"` |
| `"Unknown"` | `"Tech House Vibes"` (omit curator) |
| `""` or `None` | `"Tech House Vibes"` (omit curator) |

## Technical Considerations

### Cache keys — not affected

Cache keys are based on `artist||title` of individual tracks (cache.py line 57), not playlist names. No impact.

### State — no migration

Existing Beatport chart state entries remain keyed under the old name. Re-syncing the same chart URL would create a new playlist under the curator-prefixed name. This is acceptable — no re-sync of existing charts is planned.

## Acceptance Criteria

- [x] Beatport chart playlists include curator in name: `"Curator - Chart Name"`
- [x] Curator omitted when value is `"Unknown"`, empty, or `None`
- [x] `--dry-run` shows the new name format
- [x] Web UI sync produces the same curator-prefixed names
- [x] Label imports are unaffected
- [x] All existing tests pass; new tests cover name composition

## Implementation

### `djsupport/beatport.py` — add helper

```python
def compose_chart_playlist_name(chart_name: str, curator: str) -> str:
    """Compose playlist name from chart name and curator."""
    if curator and curator != "Unknown":
        return f"{curator} - {chart_name}"
    return chart_name
```

### `djsupport/service.py` — stop discarding curator (~line 185)

```python
# Before:
chart_name, _curator, tracks = fetch_chart(url)

# After:
chart_name, curator, tracks = fetch_chart(url)
playlist_name = compose_chart_playlist_name(chart_name, curator)
```

Pass `playlist_name` (instead of `chart_name`) to `match_and_sync_playlist()`.

### `djsupport/cli.py` — compose name in CLI flow (~line 395)

```python
# Already has: chart_name, curator, tracks = fetch_chart(url)
playlist_name = compose_chart_playlist_name(chart_name, curator)
```

Pass `playlist_name` to `_cli_match_and_sync()`. The display message at line 362 already shows `f"Chart: {chart_name} by {curator}"` — no change needed there.

### Tests — `tests/test_beatport.py`

```python
def test_compose_chart_playlist_name_with_curator():
    assert compose_chart_playlist_name("Vibes", "Adam Beyer") == "Adam Beyer - Vibes"

def test_compose_chart_playlist_name_unknown_curator():
    assert compose_chart_playlist_name("Vibes", "Unknown") == "Vibes"

def test_compose_chart_playlist_name_empty_curator():
    assert compose_chart_playlist_name("Vibes", "") == "Vibes"
```

## Files Changed

| File | Change |
|---|---|
| `djsupport/beatport.py` | Add `compose_chart_playlist_name()` |
| `djsupport/service.py` | Use curator in playlist name |
| `djsupport/cli.py` | Use curator in playlist name |
| `tests/test_beatport.py` | Tests for name composition |
| `CLAUDE.md` | Document new naming convention |
| `CHANGELOG.md` | Add entry under Unreleased |

## Sources

- Beatport `__NEXT_DATA__` curator extraction: `djsupport/beatport.py:127`
- Curator discarded in service: `djsupport/service.py:185`
- Curator displayed but unused in CLI: `djsupport/cli.py:350-362`
- Playlist name formatting: `djsupport/spotify.py:130-134`
