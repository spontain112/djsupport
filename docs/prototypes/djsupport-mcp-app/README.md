---
classification: concept
artifact: DJ Support MCP App prototype index
---

# DJ Support MCP App prototype

This folder contains the current neutral wireframe prototype for operating DJ Support as an inline MCP App.

## Status and use

This is captured throwaway design evidence. Keep this prototype branch out of
`main`, and do not copy its mock implementation into production. Future work
should implement the validated interaction decisions through DJ Support's real
Transfer policy and use the Pencil source, component contract, and language map
as primary-source guidance.

Issue #184 is a post-prototype product decision: unresolved songs must
distinguish **Wait for Spotify** from **Stop looking** before that part of the
journey is implemented. The frozen screens predate that decision.

## Start here

- `djsupport-mcp-app-wireframes.pen` — Pencil source with the presentation board, editable component sources, and all journey screens.
- `djsupport-mcp-app-component-library.md` — reusable component, token, sizing, and composition contract.
- `djsupport-mcp-app-language-map.md` — translation from the canonical domain model to plain user language.
- `exports/` — current PNG exports for review and implementation handoff.
- `archive/` — superseded PNGs and the earlier HTML fallback preserved as
  non-runnable source text; retained for history, not current design guidance.

## Current journey

1. Choose a Rekordbox file.
2. Prepare the playlists.
3. Choose one playlist.
4. Confirm a read-only Spotify match check.
5. See match results.
6. Review uncertain songs.
7. Compare Spotify versions when needed.
8. Confirm the exact private Spotify playlist result.
9. Optionally remember confirmed matches.
10. Open the completed playlist or copy another.

The compact inline card is the default surface. Playlist browsing earns a medium surface; version comparison earns a wide surface; only multi-song review earns the large workspace.

## Current visual source

Open `00 · DJ Support MCP App — Component Library` first for the reviewed presentation, then `00A · Editable Component Sources` for the 16 native reusable primitives. The numbered journey frames preserve the exact reviewed state as linked image fills from `exports/`; use the editable primitives and the component contract when translating them into implementation. `99 · Archived Alternative — Fullscreen Onboarding` remains only as a rejected comparison.

## Validation

- 16 reusable Pencil components.
- 10 active journey screens plus one archived alternative.
- No Pencil layout warnings in the component library or full document.
- No unverified claim that ChatGPT cannot see an uploaded file.
- User-facing screens avoid the internal terms Transfer, Qualification, Mirror, Approval, and durable matching authority.
