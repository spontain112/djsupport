# Reference — djsupport-chrome (Chrome extension, folded 2026-08-15)

The Chrome-extension sibling of djsupport was folded into this project as **reference** on 2026-08-15 (JC verdict, project cull follow-up): the extension overlaps the CLI work, so it lives on as prior art rather than a live sibling.

## Where it is

- **Repo:** `spontain112/djsupport-chrome` (GitHub, archived/read-only)
- **Local clone:** `~/code/archive/djsupport-chrome`
- **WIP branch:** `wip/sidepanel-refactor` (pushed) — snapshot commit `0279750`, a popup→sidepanel refactor in progress when the fold happened

## What it is

A Manifest V3 Chrome extension (TypeScript, WXT/Vite, Preact, Tailwind) that generates Spotify playlists from Beatport pages, fully client-side:

- **Shared lineage:** it ports djsupport's Python matching/parsing logic to TypeScript — `fuzzball` stands in for rapidfuzz. If the matching algorithm evolves here, the extension's `src/lib/` is the comparison point for how it translated.
- **Content script** extracts `__NEXT_DATA__` from Beatport pages (SPA-aware).
- **Tab-based Spotify OAuth (PKCE)** — worked around `chrome.identity` popup restrictions; pinned extension ID; `WXT_` env prefix. The auth flow went through a security-hardening pass (`1ea25da`).
- **Sidepanel direction (the WIP):** moving the UI from popup to Chrome side panel so the playlist view survives tab navigation — the main unfinished thread.

## If reviving

Start from `wip/sidepanel-refactor`, not `main`. Un-archive the GitHub repo first (archive toggle in repo settings). The extension expects its own Spotify app credentials via `.env` (`WXT_` prefix).
