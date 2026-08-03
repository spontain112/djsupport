# Chrome discovery-to-Spotify workflow

**Date:** 2026-08-01

**Chrome baseline:** `e26bdcacdbe6d66725fad489ff29690e42dea808`. The Chrome working tree was read only; only committed source is treated as durable evidence here.

**Status:** Primary-source code research only. No extension build, live Beatport/Spotify call, user-derived data inspection, or production change was made.

## Executive summary

The Chrome project embodies a compelling personal workflow: encounter a useful Beatport page while browsing, click the extension in place, see that it understands the page, run matching with visible progress, review exceptions, create a private Spotify playlist, and open the result. Its strength is contextual immediacy rather than breadth. The active tab supplies both source and intent, the page title supplies a usable playlist name, and the user remains in one persistent side panel through discovery, review, and handoff.

The extension is currently a separate client-side implementation, not an adapter to DJ Support's durable `Transfer`. It directly parses Beatport, owns a second matching/cache implementation, authenticates to Spotify, and creates playlists itself. That makes it an excellent interaction reference but a poor second policy authority. The roadmap opportunity is to preserve its low-friction capture and feedback while moving durable execution, matching knowledge, Approval, Mirror/Snapshot choice, recovery, and playlist mutation behind the core Transfer seam.

This evidence does **not** justify reviving the dropped standalone Mirror/Drift UX study or PR #76. The useful question is broader and plainer: how can a discovery made in the browser become a trustworthy Transfer without losing the extension's momentum?

## The workflow it currently embodies

1. **Recognition before action.** On completed Beatport navigation, the extension extracts tracks and puts the count on its badge, giving a small signal that the current page is actionable before the user opens anything (`djsupport-chrome/src/entrypoints/background.ts`, lines 28–41). It also watches Beatport's single-page navigation, invalidates stale extraction, and refreshes the result (`src/entrypoints/content.ts`, lines 25–38, 42–95).
2. **Context is the input.** Clicking the extension opens a side panel; the active tab is queried and its Beatport data becomes the job. There is no URL form, import wizard, or separate source-selection step (`src/entrypoints/background.ts`, lines 13–15, 47–60; `src/entrypoints/sidepanel/App.tsx`, lines 26–49).
3. **A short readiness check.** The panel asks for Spotify connection when needed, otherwise shows the detected page title, track count, a prefilled editable playlist name, and one primary “Match Tracks” action (`src/entrypoints/sidepanel/App.tsx`, lines 146–215). If the context is unsupported, it simply asks the user to navigate to a Beatport page with tracks (lines 161–169).
4. **Visible work, not a frozen button.** Matching changes into a dedicated progress phase with count, progress bar, and current artist/track (`src/entrypoints/sidepanel/App.tsx`, lines 66–108, 217–289). Per-track progress comes from the background worker for both cached and API results (`src/entrypoints/background.ts`, lines 100–170).
5. **Review defaults toward completion.** Every successful match begins selected. The results screen shows source and Spotify identities, score, fallback marker, unmatched items, totals, select-all/none, and per-track checkboxes before mutation (`src/entrypoints/sidepanel/App.tsx`, lines 89–102, 292–355, 432–489).
6. **Immediate publication and handoff.** Confirmation creates a new private playlist, adds selected tracks in order-preserving deduplicated batches, reports success, and offers “Open in Spotify” or “Start over” (`src/entrypoints/background.ts`, lines 173–181; `src/lib/spotify-api.ts`, lines 128–181; `src/entrypoints/sidepanel/App.tsx`, lines 359–390).

The observable state path is:

`loading -> connect or ready -> matching -> review results -> creating -> done`

with explicit unsupported-context and error states (`src/entrypoints/sidepanel/App.tsx`, lines 5–14, 395–409). This is a useful behavioral spine for Wayfinder: recognition, one purposeful action, continuous feedback, review, publication, handoff.

## Sources and actions actually supported

- The content script runs only on `beatport.com` (`src/entrypoints/content.ts`, lines 8–10). The parser classifies chart, label, release, search, and top pages, with `unknown` as a fallback (`src/lib/beatport-parser.ts`, lines 16–28; `src/lib/types.ts`, lines 14–19).
- Track extraction is heuristic over Beatport's undocumented `__NEXT_DATA__`, supporting both `results` and `data` shapes and tolerating parse failure (`src/lib/beatport-parser.ts`, lines 30–63, 171–196). The repository guide explicitly warns that Beatport changes fields without notice (`CLAUDE.md`, lines 74–85).
- The only source action is extract the tracks represented by the current page. Artist pages, arbitrary URLs, following artists/labels, saved discoveries, scheduled refreshes, and non-Beatport sites are not modeled.
- The Spotify actions are search, current-user lookup, create a private playlist, and add/replace its items (`src/lib/spotify-api.ts`, lines 81–181). There is no update of an existing managed playlist, durable source relationship, Approval lifecycle, Correction, resume UI, or scheduled follow-up.

## Relationship to core DJ Support

The Chrome code says it ports Python DJ Support's parsing and matching into a fully client-side TypeScript extension (`djsupport-chrome/CLAUDE.md`, lines 3–15). Matching is required by convention to produce the same results, and several operational lessons are copied across, including version handling, duration penalties, deduplication, rate-limit bounds, and versioned storage (`CLAUDE.md`, lines 69–85). Its local match cache is threshold-aware and versioned (`src/lib/cache.ts`, lines 4–22, 28–89).

There is nevertheless **no runtime integration with core DJ Support**. The service worker owns extraction, matching, cache writes, Spotify OAuth, and playlist publication (`src/entrypoints/background.ts`, lines 45–181). Core DJ Support defines a Transfer as the complete attempt, with Transfer owning policy and publishing either a Mirror or Snapshot (`CONTEXT.md`, lines 7–16; `djsupport/transfer.py`, lines 1–5 and 1119–1147). Today, a playlist created by Chrome therefore bypasses durable Transfer identity, retained cross-source matching knowledge, Provisional Playlist/Approval behavior, publication checkpoints, account-level publishing serialization, and Mirror/Snapshot semantics.

That boundary should inform—not dictate—the eventual architecture:

- **Keep in Chrome:** recognize the current browser context; capture explicit user intent; show lightweight source facts and Transfer status; deep-link to review or Spotify.
- **Keep in Transfer:** source identity; mode and publication policy; matching/Corrections/Approved Matches; Preview and Approval; Spotify mutation; checkpoints, resume, concurrency, and outcome reporting.
- **Do not silently infer:** following, recurrence, Mirror status, Approval, source relinking, or destructive playlist intent from one extension click.

## Why it feels close to the desired personal workflow

- **It begins where discovery happens.** The user does not have to remember a URL or switch to a command-line workflow.
- **It answers “will this work?” early.** Badge count, detected title, and track count turn a vague page into a concrete possible playlist before costly matching.
- **It compresses setup.** Page context proposes the source and playlist name; cached results reduce repeated work.
- **It maintains momentum without hiding uncertainty.** Progress is visible; questionable or absent matches remain reviewable; publication is a separate explicit action.
- **It ends at the natural next place.** “Open in Spotify” closes the loop instead of asking the user to locate the output.

These are interaction principles, not a mandate to preserve the current screens or expose technical controls. In particular, the raw numeric match-threshold slider (`src/entrypoints/sidepanel/App.tsx`, lines 180–193) is implementation language and may be less useful than a stable product policy plus exception review.

## Constraints exposed by the code

1. **Beatport-only and structurally fragile.** Supported page categories are broader than chart/label, but all depend on undocumented page internals. Anti-bot and stale SPA states are expected and explicitly handled (`src/entrypoints/content.ts`, lines 42–95).
2. **Two authorities will drift.** Parsing, matching, cache schema, rate-limit behavior, and Spotify contracts are duplicated in TypeScript and Python. “Same result” is a convention, not a shared durable implementation.
3. **Current Spotify creation is legacy-shaped.** Chrome calls `/users/{userId}/playlists` and playlist `/tracks` routes (`src/lib/spotify-api.ts`, lines 128–181); the playlist API review identifies `/me/playlists`, `/items`, scopes, stable `account_id`, and snapshot/concurrency work as required foundations (`docs/research/2026-08-01-playlist-management-api-review.md`, sections 1 and 6).
4. **The happy path is synchronous and panel-bound.** Progress messages are live, but the UI does not reattach to a durable job after the panel/browser lifecycle. Rate limiting saves the cache and returns an error with progress, not a resumable Transfer (`src/entrypoints/background.ts`, lines 147–170).
5. **Local state includes sensitive credentials and derived music data.** Refresh tokens and match cache live in extension-local storage (`src/lib/spotify-auth.ts`, lines 174–214; `src/lib/cache.ts`, lines 28–52). Any core handoff must define minimal payloads, ownership, retention, and migration; none should enter Git or telemetry by accident.
6. **Publication means “new private Snapshot-like playlist,” but is unnamed as such.** It never updates an existing playlist or retains a relationship. The product must not reinterpret that click as a recurring Mirror without asking.
7. **Selection is URI-set based.** The UI's `Set` and publication deduplication intentionally collapse many-to-one matches (`src/entrypoints/sidepanel/App.tsx`, lines 18–20, 89–92; `src/lib/spotify-api.ts`, lines 149–165). This fits current matching publication but must not leak into future exact backup/restore, where duplicate occurrences and order are facts.

## Wayfinder opportunity frontier

These are decision areas, not feature commitments:

1. **Capture contract:** What is the smallest browser-to-Transfer request that preserves explicit intent—current URL, detected source kind and title, or a normalized immutable source reference? What can be recomputed safely server/core-side?
2. **Immediate versus saved intent:** Does clicking normally start a Preview/Transfer now, save a discovery for later, or make that choice explicit? The current workflow strongly supports immediate action; following artists/labels introduces durable subscriptions and therefore needs a separate explicit act.
3. **Supported discovery objects:** Which encountered things deserve first-class intake: Beatport chart, label, release, search result, artist, or a playlist on another site? Each needs a truthful source identity and refresh contract before UI expansion.
4. **Mode at capture:** Is an encountered page a one-time Snapshot by default, with Mirror/following offered only when the source is durably re-readable? Do not infer recurrence from “label” or “artist.”
5. **Review placement:** Which facts must remain in the side panel, and when should Chrome hand off to DJ Support's fuller review? Preserve selected/unmatched visibility and avoid exposing domain terms before they help a decision.
6. **Durable progress:** How should the side panel reconnect to a prepared Transfer after closure, auth, rate limit, or browser restart? The current progress experience is valuable but not durable.
7. **Matching authority migration:** Can Chrome stop owning a second matcher/cache while retaining its responsive progress? If an offline/browser-only mode remains, how are result parity, Corrections, and Approved Matches reconciled without silent divergence?
8. **Feedback and completion:** Should success open Spotify, DJ Support's report/review, or offer both based on state? “Open in Spotify” is a proven finish for completed publication; paused or approval-needed work needs a different truthful destination.
9. **Follow discovery:** For artists and labels, what constitutes “new and relevant,” how often is checked, which sources are legally/reliably queryable, and is the output an inbox, a proposed Transfer, or a managed Mirror? This is a new domain capability, not merely another page parser.
10. **Metadata enrichment:** When discovery reveals missing label, release, date, mix, or identifier data, where may suggestions be retained and reviewed? Never silently rewrite Rekordbox, audio tags, Spotify metadata, or Approved Matches.

## Recommended next map question

Before choosing screens or a release number, decide the default meaning of the extension click in plain personal terms:

> When I find something worth keeping while browsing, do I want DJ Support to make a playlist now, remember it for later, or let me choose each time?

That decision separates the proven immediate-conversion journey from the new capture/following opportunity, while leaving Mirror, Snapshot, Approval, and recovery policy with Transfer.
