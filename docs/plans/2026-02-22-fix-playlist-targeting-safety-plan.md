---
title: "fix: Remove name-based playlist targeting fallback"
type: fix
status: completed
date: 2026-02-22
origin: LOCAL_HANDOVER_playlist-safety-v0.3.md
---

# fix: Remove name-based playlist targeting fallback

## Overview

The app can currently fall back to updating Spotify playlists by **name** when local state is missing. This risks overwriting manually curated Spotify playlists that happen to share a name with a Rekordbox playlist. This is especially dangerous when a coding agent runs the tool, where defaults must be safe under ambiguity.

**Safety invariant**: *This app never modifies a Spotify playlist unless it is explicitly marked as app-managed (tracked by `spotify_id` in local state).*

## Problem Statement / Motivation

Two unsafe code paths exist:

1. **`resolve_playlist_id()` in `spotify.py:95-102`** — after checking state, falls back to matching by formatted name (`djsupport / My Playlist`) then bare name (`My Playlist`). If either matches an existing Spotify playlist, that playlist becomes the update target — even if it was manually created.

2. **First-run migration in `cli.py:119-138`** — when state is empty, auto-adopts existing Spotify playlists by name into state without user confirmation. This silently claims ownership of playlists that may not be app-managed.

Both paths violate the safety invariant.

## Proposed Solution

Remove the two unsafe code paths and enforce state-only playlist targeting:

1. **Strip name-based fallback from `resolve_playlist_id()`** — only return a playlist ID when found via state. Return `None` otherwise, triggering the create-new path.

2. **Remove first-run auto-adoption from `cli.py`** — delete the migration block. New playlists will be created on first sync and state will populate naturally.

3. **Preserve all other behavior** — state saves after create/update, cache loading, XML-authoritative track membership, non-destructive handling of playlists removed from XML.

## Technical Considerations

### Change 1: `djsupport/spotify.py` — `resolve_playlist_id()`

**Remove lines 95-102** (name-based fallback):

```python
# REMOVE: formatted name lookup
formatted = format_playlist_name(name, prefix)
if formatted in existing_playlists:
    return existing_playlists[formatted], "name"

# REMOVE: bare name fallback
if prefix and name in existing_playlists:
    return existing_playlists[name], "name"
```

After the change, this function returns either `(spotify_id, "state")` or `(None, "none")`. The `"name"` return value is eliminated entirely.

**Consider**: The `existing_playlists` parameter and the call to `get_user_playlists()` that populates it may now be unnecessary. However, per the handover: keep the PR narrow. Leave the parameter in place — it can be cleaned up in a follow-up.

**Edge case — 403 vs 404**: The current code catches all `SpotifyException` when verifying a state-based ID (line 91). A 403 (access revoked) is different from a 404 (deleted). For this PR, the existing catch-all behavior is acceptable — both trigger recreate. Document this as a known simplification for follow-up.

### Change 2: `djsupport/cli.py` — first-run migration

**Remove lines 119-138** (auto-adoption block):

```python
# REMOVE: entire first-run migration block
if not dry_run and existing and state_mgr.is_empty():
    ...
```

No replacement needed. The sync loop will naturally create new playlists and save state entries.

### Change 3: CLI output clarity

When a new playlist is created (because state is missing and name-based adoption is gone), ensure the CLI output makes this clear. The existing `create_or_update_playlist()` already logs creation. Verify that `--dry-run` output accurately reflects "would create new playlist" rather than "would update existing".

### No changes required

- **`djsupport/state.py`** — `PlaylistState` schema is sufficient. No migration needed.
- **`djsupport/cache.py`** — match cache behavior stays intact. No format changes.
- **`create_or_update_playlist()`** — continues to work correctly. When `resolve_playlist_id()` returns `None`, it creates a new playlist and saves state. No change needed.
- **`incremental_update_playlist()`** — same: `None` resolution delegates to `create_or_update_playlist()`. No change needed.

## System-Wide Impact

- **Interaction graph**: `resolve_playlist_id()` is called by both `create_or_update_playlist()` (line 131) and `incremental_update_playlist()` (line 200). Removing the name fallback affects both paths uniformly.
- **Error propagation**: No new error paths introduced. Existing SpotifyException handling in state verification is unchanged.
- **State lifecycle risks**: None — state writes after playlist creation are already in place (lines 154-161 in `create_or_update_playlist()`). The only risk is the pre-existing one: non-atomic state writes. Out of scope for this PR.
- **API surface parity**: `--dry-run` must reflect the new behavior. No other interfaces affected.

## Acceptance Criteria

- [x] `resolve_playlist_id()` only returns a playlist ID from state — never by name
- [x] First-run migration block is removed from `cli.py`
- [x] Name collision scenario: existing Spotify playlist with same name is NOT overwritten; app creates new managed playlist
- [x] Managed update: app updates exact `spotify_id` from state
- [x] Deleted managed playlist: app recreates with new ID, updates state, no name adoption
- [x] Manual track removal: tracks restored on next sync (XML authoritative)
- [x] Playlist removed from XML: Spotify playlist NOT deleted
- [x] Match cache still loads/saves and reduces API lookups on second run
- [x] `--dry-run` output accurately shows "create" vs "update" behavior
- [x] `--no-prefix` does not weaken ownership enforcement
- [x] No new CLI flags introduced
- [x] No state schema changes

## Success Metrics

- Zero instances of name-based playlist adoption in default sync path
- All 6 test scenarios from the handover pass manual verification

## Dependencies & Risks

**Accepted tradeoffs (per handover)**:
- First-run users may get duplicate playlists if same names already exist on Spotify — this is safer than auto-adoption
- No explicit adopt-existing workflow yet — planned for follow-up PR
- Less convenient than auto-migration, but safer

**Known simplifications for follow-up**:
- 403 vs 404 distinction when verifying state-based IDs
- `existing_playlists` parameter cleanup (may become unused)
- State file atomic writes
- User-facing warning when creating a playlist that has a name collision

## Sources & References

- **Origin handover**: [LOCAL_HANDOVER_playlist-safety-v0.3.md](../../LOCAL_HANDOVER_playlist-safety-v0.3.md) — defines the safety invariant, behavior contract, and PR boundaries
- Unsafe name resolution: `djsupport/spotify.py:95-102`
- Unsafe first-run adoption: `djsupport/cli.py:119-138`
- State management: `djsupport/state.py` (no changes needed)
- Cache: `djsupport/cache.py` (no changes needed)
