---
module: CLI
date: 2026-02-25
problem_type: logic_error
component: tooling
symptoms:
  - "Duplicate tracks appearing in Spotify playlists"
  - "Different Rekordbox remixes resolving to the same Spotify URI added multiple times"
  - "37 extra tracks across 32 duplicate Spotify URIs in combined playlist"
root_cause: logic_error
resolution_type: code_fix
severity: medium
tags: [deduplication, spotify-uri, playlist-sync, cli]
---

# Troubleshooting: Duplicate Tracks in Spotify Playlists

## Problem
Spotify playlists created by `djsupport sync --all` contained duplicate tracks. Different Rekordbox entries (e.g., remix variants with different titles) resolved to the same Spotify URI, and all were added to the playlist without deduplication.

## Environment
- Module: CLI (`djsupport/cli.py`)
- Python Version: 3.10+
- Affected Component: `sync` command playlist creation
- Date: 2026-02-25

## Symptoms
- Duplicate tracks visible in Spotify playlist (e.g., "Love Tonight (Edit)" by Shouse appearing at positions #2107 and #2109)
- Different Rekordbox entries for remix variants all resolving to the same Spotify track
- 37 extra tracks across 32 duplicate Spotify URIs in a 2,842-track "Rekordbox All" playlist
- Most common duplicates: remixes that Spotify maps to the same canonical track (e.g., "Sascha Braemer - No Home" had 4 remix variants all resolving to one URI)

## What Didn't Work

**Direct solution:** The problem was identified and fixed on the first attempt after analyzing the cache data to confirm the root cause.

## Solution

Added URI deduplication in `cli.py` after matching and before sending track URIs to the Spotify API. The deduplication preserves insertion order (first occurrence wins).

**Code changes:**

```python
# Before (broken) — cli.py line 252:
# matched_uris was passed directly to create_or_update_playlist / incremental_update_playlist
# with no URI-level deduplication
if not dry_run and matched_uris:
    ...

# After (fixed) — cli.py lines 252-260:
# Deduplicate URIs (different Rekordbox tracks can resolve to the same Spotify track)
seen_uris: set[str] = set()
unique_uris: list[str] = []
for uri in matched_uris:
    if uri not in seen_uris:
        seen_uris.add(uri)
        unique_uris.append(uri)
matched_uris = unique_uris

if not dry_run and matched_uris:
    ...
```

## Why This Works

1. **Root cause:** The `combine_all` code deduplicates by Rekordbox track ID (preventing the same Rekordbox entry from appearing twice), but different Rekordbox track IDs can have different artist/title combinations that all fuzzy-match to the same Spotify track. For example, "Shouse - Love Tonight (Mike Simonetti Remix)", "Shouse - Love Tonight (Oliver Huntemann Remix)", and "Shouse - Love Tonight (Vintage Culture Remix)" are three distinct Rekordbox tracks that all resolve to `spotify:track:6OufwUcCqo81guU2jAlDVP`.

2. **Why the fix works:** By deduplicating on Spotify URI after matching but before playlist creation, we ensure each Spotify track appears only once regardless of how many Rekordbox entries map to it. Order-preserving dedup means the first-matched variant (by date added sort order) wins.

3. **Underlying issue:** The deduplication was operating at the wrong abstraction level — Rekordbox track ID instead of Spotify URI. These are a many-to-one relationship that wasn't accounted for.

## Prevention

- When building lists of external resource identifiers (like Spotify URIs), always deduplicate at the target system's ID level, not the source system's ID level
- Consider adding a metric to the sync report showing how many duplicates were removed, to make this visible
- The `incremental_update_playlist` function already uses `set()` for diff computation, so incremental updates were partially protected — but full replacements and new playlist creation were not

## Related Issues

- See also: [Spotify API Calls Early Exit Optimization](../performance-issues/spotify-api-calls-early-exit-optimization.md) — related matcher optimization that also affects sync behavior
