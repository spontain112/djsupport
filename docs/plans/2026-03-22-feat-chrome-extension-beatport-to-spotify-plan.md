---
title: "feat: Chrome Extension - Beatport to Spotify Playlist Generator"
type: feat
status: out-of-scope
date: 2026-03-22
reason: Extension work belongs in the dedicated extensions workspace under the repository scope guard.
---

# Chrome Extension: Beatport to Spotify Playlist Generator

## Overview

Build a standalone Chrome extension (Manifest V3) that lets you generate Spotify playlists directly from any Beatport page showing tracks. When you're browsing a Beatport chart, label, release, or search results page, click the extension icon to see matched tracks, adjust settings, and create a Spotify playlist — all without any backend server.

This ports the core matching and parsing logic from the existing Python djsupport project into a fully client-side TypeScript Chrome extension.

## Problem Statement / Motivation

The current djsupport tool requires running a Python CLI or local FastAPI server. This works for power-user library management but creates friction for the most common use case: "I'm looking at a Beatport chart right now and I want it as a Spotify playlist." A Chrome extension eliminates all setup — install it once, authenticate with Spotify, and you're one click away from any Beatport page becoming a playlist.

## Proposed Solution

A Manifest V3 Chrome extension built with:
- **WXT** (Vite-based extension framework) with TypeScript
- **Preact** for the popup UI (4 KB, React-compatible API)
- **fuzzball** for fuzzy string matching (direct port of rapidfuzz algorithms)
- **Spotify PKCE OAuth** via `chrome.identity.launchWebAuthFlow`
- **Content script** that extracts `__NEXT_DATA__` from Beatport pages
- **chrome.storage.local** for match caching and settings persistence

### Architecture

```
[Beatport Page]
      |
      v
[Content Script] -- reads __NEXT_DATA__ from DOM
      |
      | chrome.runtime.sendMessage
      v
[Service Worker] -- orchestrates matching
      |
      |-- Spotify Search API (fuzzy match each track)
      |-- chrome.storage.local (cache lookups/writes)
      |
      v
[Popup UI (Preact)] -- displays results, user controls
      |
      | User confirms
      v
[Service Worker] -- Spotify Create Playlist API
```

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Architecture | Fully client-side | No server needed = zero setup, installable by anyone |
| Build framework | WXT | Active maintenance, TypeScript-first, HMR, file-based entrypoints |
| UI framework | Preact | 4 KB gzipped, React-compatible, fast popup load |
| Fuzzy matching | fuzzball | Direct port of Python's fuzzywuzzy/rapidfuzz algorithms (token_sort_ratio, etc.) |
| OAuth | PKCE via launchWebAuthFlow | Mandatory for Spotify since Nov 2025; no client secret in extension |
| Caching | chrome.storage.local | Persistent across sessions, 10 MB default (expandable) |
| Beatport parsing | Content script DOM reading | __NEXT_DATA__ is already in the page — no HTTP request needed |

## Technical Approach

### Phase 1: Project Scaffolding & Spotify Auth

**Goal:** New WXT project with working Spotify authentication.

**Tasks:**
- [ ] Initialize WXT project with Preact template in `djsupport-chrome/`
- [ ] Configure `manifest.json` (Manifest V3):
  - `host_permissions`: `https://api.spotify.com/*`, `https://accounts.spotify.com/*`
  - `permissions`: `storage`, `activeTab`
  - `content_scripts`: match `https://www.beatport.com/*`
  - `action`: popup entry point
- [ ] Implement Spotify PKCE OAuth module (`src/lib/spotify-auth.ts`):
  - Code verifier generation via `crypto.getRandomValues()`
  - SHA-256 code challenge computation
  - `chrome.identity.launchWebAuthFlow()` integration
  - Token exchange (POST to `/api/token`)
  - Token refresh logic
  - Store refresh token in `chrome.storage.local`, access token in `chrome.storage.session`
- [ ] Register `https://<extension-id>.chromiumapp.org/` as redirect URI in Spotify Developer Dashboard
- [ ] Build minimal popup with "Connect Spotify" button to verify auth flow works
- [ ] Implement Spotify API client (`src/lib/spotify-api.ts`):
  - Search tracks (`/v1/search?type=track&limit=5`)
  - Create playlist (`/v1/users/{user_id}/playlists`)
  - Add tracks to playlist (`/v1/playlists/{id}/tracks`)
  - Get current user (`/v1/me`)
  - Rate limit handling (429 + Retry-After, exponential backoff)
  - Auto-refresh expired tokens before API calls

**Key files:**
```
djsupport-chrome/
  src/
    entrypoints/
      popup/          # Preact popup app
      background.ts   # Service worker
    lib/
      spotify-auth.ts
      spotify-api.ts
  wxt.config.ts
```

### Phase 2: Beatport Page Extraction

**Goal:** Content script that reads track data from any Beatport page.

**Tasks:**
- [ ] Implement content script (`src/entrypoints/content.ts`):
  - Extract `__NEXT_DATA__` via `document.getElementById('__NEXT_DATA__')`
  - Parse JSON and send to service worker via `chrome.runtime.sendMessage`
  - Handle client-side navigation (Next.js App Router) via URL change detection with `webNavigation` API or MutationObserver
- [ ] Implement Beatport parser (`src/lib/beatport-parser.ts`):
  - Port `_parse_chart_data` logic: find the query in `dehydratedState.queries` whose `state.data.results` contains dicts with `"artists"` key
  - Port `_parse_track` logic: extract artist, title, mix_name, duration, album, label, genre
  - Handle mix_name: append non-"Original Mix" / non-"Original" descriptors in parentheses
  - Parse duration strings ("4:32", "1:04:30") to seconds
  - Extract page metadata (chart name + curator, label name) for playlist naming
- [ ] Support multiple page types by detecting URL pattern:
  - `/chart/<slug>/<id>` — chart pages (metadata at `pageProps.chart`)
  - `/label/<slug>/<id>` — label pages (metadata at `pageProps.label`)
  - `/release/<slug>/<id>` — release pages
  - `/top-100`, `/search` — listing pages
  - Fallback: generic track extraction from any `results` array with `artists` key
- [ ] Define Track interface (`src/lib/types.ts`):
  ```typescript
  interface Track {
    trackId: string;
    name: string;
    artist: string;
    album: string;
    remixer: string;
    label: string;
    genre: string;
    dateAdded: string;
    duration: number; // seconds
  }
  ```
- [ ] Handle label page pagination:
  - First page extracted from DOM (already loaded)
  - Subsequent pages fetched via HTTP from service worker (same __NEXT_DATA__ extraction from HTML)
  - Or: detect if the page has a "load more" / pagination mechanism and re-read DOM after navigation

**Label pagination decision:** For the extension MVP, extract only what's visible on the current page. Label pages show ~150 tracks per page. Multi-page fetching can be a Phase 4 enhancement since it requires HTTP requests from the service worker (mimicking the Python label.py pagination).

### Phase 3: Fuzzy Matching Engine

**Goal:** Port the Python matcher to TypeScript with identical scoring behavior.

**Tasks:**
- [ ] Install `fuzzball` npm package (provides `token_sort_ratio`, `ratio`)
- [ ] Implement text normalization (`src/lib/normalize.ts`):
  - Unicode NFKD decomposition + strip combining characters (use `String.prototype.normalize('NFKD')` + regex)
  - Lowercase + trim
  - Remove country tags: `/\s*\([A-Z]{2,3}\)/gi`
  - Remove bracket tags: `/\s*\[.*?\]/g`
  - Replace "x" separator: `/\s+x\s+/g` -> `", "`
  - Remove feat/ft: `/\b(feat\.?|ft\.?)\s+.*/i`
  - Collapse whitespace: `/\s+/g` -> `" "`
- [ ] Implement mix info handling (`src/lib/mix-info.ts`):
  - `stripMixInfo(title)`: remove parenthetical/bracket/hyphen remix descriptors
  - `extractMixDescriptors(title)`: extract all version descriptors, deduplicated
  - `isNamedVariant(descriptor)`: true if descriptor exists and doesn't contain "original"
  - `classifyVersionMatch(track, result)`: return `"exact"` or `"fallback_version"` using same logic as Python
- [ ] Implement scoring (`src/lib/scorer.ts`):
  - `durationPenalty(trackDuration, spotifyDurationMs)`: 0 if <=30s diff, then 5 per 30s, capped at 15
  - `scoreResult(track, result)`:
    - artist_score = fuzzball.token_sort_ratio(normalize(track.artist), normalize(result.artist))
    - raw_title_score = fuzzball.token_sort_ratio(normalize(track.name), normalize(result.name))
    - stripped_title_score = fuzzball.token_sort_ratio(normalize(stripMixInfo(track.name)), normalize(stripMixInfo(result.name)))
    - title_score = max(raw, stripped)
    - penalty = (fallback_version ? 15 : 0) + durationPenalty
    - final = clamp(artist_score * 0.4 + title_score * 0.6 - penalty, 0, 100)
- [ ] Implement multi-strategy search (`src/lib/matcher.ts`):
  - Strategy 1: `artist:{artist} track:{title}` (always)
  - Early exit: if best >= 95 and exact match, return immediately
  - Strategy 2: `artist:{artist} track:{strippedTitle}` (if different)
  - Strategy 3: `artist:{artist} {remixer} track:{title}` (if remixer exists)
  - Strategy 4: `artist:{cleanArtist} track:{cleanTitle}` (if normalization changed anything)
  - Strategy 5: `{artist} {title}` plain text (if no results from 1-4)
  - `selectBest(track, results, threshold)`:
    - First pass: exact version matches >= threshold
    - Second pass: fallback version if base_score >= threshold AND stripped_title >= 90 AND artist >= 70
- [ ] Write unit tests for normalization, scoring, and matching against known examples from the Python test suite

### Phase 4: Match Caching

**Goal:** Persistent match cache in chrome.storage.local, following the same structure as Python cache.py.

**Tasks:**
- [ ] Implement cache module (`src/lib/cache.ts`):
  - Cache key: `normalize(artist) + "||" + normalize(title)`
  - CacheEntry: `{ spotifyUri, spotifyName, spotifyArtist, score, matched, timestamp, threshold, matchType }`
  - `lookup(artist, title, threshold)`: same threshold-aware logic as Python
  - `store(artist, title, entry)`: write to storage
  - Batch read/write to minimize chrome.storage IPC calls
  - Auto-checkpoint every 50 writes (batch pending writes to storage)
- [ ] Cache storage format in chrome.storage.local:
  ```json
  { "matchCache": { "version": 1, "entries": { "key": {...} } } }
  ```
- [ ] Retry logic: `isRetryEligible(artist, title, retryDays, force)` — same age-based logic as Python
- [ ] Storage monitoring: warn user if cache approaches 10 MB (or request `unlimitedStorage` permission)

### Phase 5: Popup UI — Full Control Interface

**Goal:** Power-user popup with track preview, match editing, and playlist controls.

**Tasks:**
- [ ] Design popup layout (target: 700x500px) with these sections:
  1. **Header bar**: Beatport page title, Spotify auth status, settings gear icon
  2. **Track list**: scrollable list showing each track with:
     - Checkbox (select/deselect for playlist)
     - Track: artist - title
     - Match result: Spotify track name + score badge (color-coded: green >= 90, yellow >= 80, red < 80)
     - Match type indicator: "exact" vs "fallback" tag
     - "No match" state for unmatched tracks
  3. **Controls bar**:
     - Threshold slider (0-100, default 80)
     - Playlist name input (pre-filled from chart/label name)
     - "Create Playlist" button
  4. **Status/progress**: matching progress bar during search, success/error messages

- [ ] Implement popup state management:
  - Popup communicates with service worker via `chrome.runtime.sendMessage` / `onMessage`
  - Service worker holds the matching state (tracks, results, progress)
  - Popup re-fetches state from service worker on open (since popups re-initialize each time)
  - Store last session state in `chrome.storage.session` so reopening the popup shows previous results

- [ ] Implement matching workflow:
  1. User opens popup on a Beatport page
  2. Popup requests track data from content script (via service worker relay)
  3. Service worker receives tracks, starts matching (checking cache first, then Spotify API)
  4. Progress updates sent to popup in real-time
  5. Results displayed as they arrive (streaming UX, not all-or-nothing)

- [ ] Track list interactions:
  - Click to select/deselect individual tracks
  - "Select all matched" / "Deselect all" buttons
  - Re-match button for individual failed tracks
  - Threshold change triggers re-evaluation of cached scores (no API calls needed — just re-filter)

- [ ] Playlist creation flow:
  1. User reviews matches, adjusts selection
  2. User edits playlist name if desired
  3. Click "Create Playlist"
  4. Service worker creates playlist via Spotify API
  5. Success: show Spotify playlist link (opens in new tab)
  6. Error: show error message with retry option

- [ ] Settings panel (gear icon):
  - Default threshold
  - Default playlist name prefix (optional)
  - Cache management: view size, clear cache button
  - Spotify: disconnect / reconnect

- [ ] Style with Tailwind CSS (purged for minimal bundle)

### Phase 6: Polish & Edge Cases

**Goal:** Handle real-world Beatport page variations and improve UX.

**Tasks:**
- [ ] Handle Beatport client-side navigation:
  - Next.js App Router may not re-render `__NEXT_DATA__` on soft navigation
  - Use `webNavigation.onHistoryStateUpdated` to detect URL changes on Beatport
  - Re-extract page data when URL changes while popup is open
- [ ] Handle anti-bot / challenge pages:
  - Detect "human-test" or "findProof" in page content
  - Show friendly message: "Beatport is showing a verification page. Please complete it and try again."
- [ ] Handle empty/invalid pages:
  - No tracks found on page
  - Not a Beatport page (disable extension icon or show message)
  - Page still loading (wait for `__NEXT_DATA__` to appear)
- [ ] Extension icon badge:
  - Show track count on the extension icon when on a Beatport page (e.g., "42")
  - Gray out icon when not on Beatport
- [ ] Rate limit handling:
  - If Spotify returns 429, show "Rate limited — retrying in Xs" in popup
  - Pause matching, resume after Retry-After period
  - Never silently fail
- [ ] Error boundaries in Preact UI — catch and display errors gracefully
- [ ] Label page multi-page support (enhancement):
  - For labels with 150+ tracks, offer "Load more pages" button
  - Service worker fetches additional pages via HTTP (same parsing logic)

## System-Wide Impact

### Interaction Graph

User clicks extension icon -> popup mounts -> sends `getPageData` message to service worker -> service worker sends `extractTracks` to content script -> content script reads DOM `__NEXT_DATA__` -> parsed tracks flow back through service worker to popup -> user triggers matching -> service worker calls Spotify Search API per track (with cache checks) -> results stream to popup -> user confirms -> service worker calls Spotify Create Playlist + Add Tracks APIs.

### Error & Failure Propagation

- **Content script extraction fails**: service worker returns `{ error: "no_tracks" }` to popup, UI shows "No tracks found on this page"
- **Spotify auth expired**: API call returns 401 -> auto-refresh token -> retry once -> if still fails, prompt re-auth in popup
- **Spotify rate limit (429)**: pause matching, show countdown in popup, resume automatically
- **chrome.storage quota exceeded**: warn user, offer cache clear option
- **Network offline**: Spotify API calls fail -> show offline message, suggest retrying later

### State Lifecycle Risks

- **Popup re-initialization**: popup state is lost on close. Mitigated by storing session state in `chrome.storage.session`.
- **Service worker termination**: Chrome may kill idle service workers. All in-progress matching state must be recoverable — store partial results in `chrome.storage.session` and resume on wake.
- **Token expiry mid-matching**: handled by wrapping all Spotify calls with auto-refresh logic.
- **Cache corruption**: validate cache version on load, reset to empty if invalid.

### API Surface Parity

This is a new, independent project. No existing APIs are affected. The matching algorithm should produce identical scores to the Python version — validated via shared test cases.

### Integration Test Scenarios

1. **Full flow**: extract tracks from a real Beatport chart page snapshot -> match against Spotify -> create playlist. Verify playlist contains expected tracks.
2. **Cache hit**: match a track, close/reopen extension, verify cached result is returned without API call.
3. **Auth refresh**: start matching with an expired token, verify it auto-refreshes and continues.
4. **Rate limit**: mock 429 response mid-matching, verify matching pauses and resumes.
5. **Page navigation**: navigate between two Beatport charts, verify track data updates correctly.

## Acceptance Criteria

### Functional Requirements

- [ ] Extension activates on any `beatport.com` page showing tracks
- [ ] Extracts tracks from chart, label, release, search, and top-100 pages
- [ ] Spotify OAuth via PKCE — authenticate once, stay logged in across sessions
- [ ] Fuzzy matching produces scores within +/- 2 points of the Python matcher for the same inputs
- [ ] Popup shows all tracks with match scores, match types, and select/deselect controls
- [ ] User can adjust match threshold via slider, re-filtering results without new API calls
- [ ] User can rename the playlist before creation
- [ ] Creates a private Spotify playlist with selected matched tracks
- [ ] Shows Spotify playlist link on success
- [ ] Match cache persists across browser sessions via `chrome.storage.local`
- [ ] Handles rate limiting gracefully with visible countdown

### Non-Functional Requirements

- [ ] Popup loads in < 200ms (keep bundle small — Preact + Tailwind purged)
- [ ] Matching 20 tracks completes in < 15 seconds (with cache misses)
- [ ] Extension bundle < 500 KB total
- [ ] Works on Chrome 120+ (Manifest V3 baseline)

### Quality Gates

- [ ] Unit tests for normalization, scoring, mix info handling, cache logic
- [ ] Matching parity tests: same inputs as Python test suite, same expected scores
- [ ] Manual testing on 5+ different Beatport page types (chart, label, release, search, top-100)

## Success Metrics

- One-click playlist creation from any Beatport track listing page
- Match accuracy parity with the Python djsupport matcher
- No external server dependency — fully self-contained in the browser

## Dependencies & Prerequisites

| Dependency | Purpose | Notes |
|-----------|---------|-------|
| WXT | Extension build framework | `npm create wxt@latest` |
| Preact | Popup UI | ~4 KB gzipped |
| fuzzball | Fuzzy matching | rapidfuzz equivalent for JS |
| Tailwind CSS | Popup styling | Purged for minimal bundle |
| Spotify Developer App | API credentials | Existing app, add chrome extension redirect URI |
| Chrome 120+ | Manifest V3 runtime | |

## Risk Analysis & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Beatport changes `__NEXT_DATA__` structure | Medium | High | Generic track detection heuristic (find arrays with `artists` key), not hardcoded paths |
| Spotify PKCE adds new requirements | Low | High | Follow official docs; `chrome.identity` handles most complexity |
| fuzzball scoring differs from rapidfuzz | Medium | Medium | Matching parity tests; both use Levenshtein-based token_sort_ratio |
| Service worker killed mid-matching | Medium | Medium | Store partial results in chrome.storage.session, resume on wake |
| Beatport anti-bot blocks content script | Low | Medium | Content script reads DOM (not making HTTP requests), so unlikely; detect and show message if it happens |

## Future Considerations

- **Rekordbox integration**: import Rekordbox XML playlists via file picker in the extension (no server needed)
- **Playlist management**: view/update previously created playlists
- **Multi-page label support**: fetch all pages for large labels
- **Firefox/Safari**: WXT supports cross-browser builds
- **Chrome Web Store**: publish for other DJs (would need Spotify extended quota approval for >25 users)

## Learnings Carried Forward from djsupport (Python)

These are hard-won lessons from the Python project that must be respected in the Chrome extension. Each links to the original solution doc.

### Matching Accuracy

1. **Version tag regex must be comprehensive** — The original regex only matched `mix|remix|edit|version|dub`. Missing `extended|radio|instrumental|short` caused `_strip_mix_info` to fail on tracks like "Night Drive (Extended)", returning 0 search results. Match rate jumped from 77.8% to 82.7% just by fixing this.
   - Source: `docs/solutions/logic-errors/beatport-fuzzy-matcher-version-tags-and-duration-penalty.md`

2. **Duration penalty must be gentle (5pts/30s, cap 15)** — Beatport tracks are usually extended DJ versions; Spotify has shorter radio edits. The original penalty (10pts/30s, cap 30) was so aggressive that perfect artist+title matches were rejected on duration alone. Reducing to 5/30/15 brought matching from 82.7% to 97.5%.
   - Source: `docs/solutions/logic-errors/beatport-fuzzy-matcher-version-tags-and-duration-penalty.md`
   - **Key principle:** Separate search breadth (strip version tags for recall) from scoring precision (penalties should inform, not dominate).

3. **Early exit threshold of 95 is safe** — The double penalty layer (version mismatch: -15, duration mismatch: -15 max) means wrong versions score 55-65, never near 95. This optimization cut API calls from ~4.9/track to ~0.87/track. Critical for a browser extension where Spotify rate limits are a bigger concern.
   - Source: `docs/solutions/performance-issues/spotify-api-calls-early-exit-optimization.md`

4. **Deduplicate at Spotify URI level, not source level** — Multiple Beatport tracks (e.g., remix variants) can resolve to the same Spotify URI. The Python project had 37 duplicate tracks in a 2,842-track playlist before this was caught. Always deduplicate matched URIs before playlist creation.
   - Source: `docs/solutions/logic-errors/duplicate-spotify-uris-in-playlists-CLI-20260225.md`

### Beatport Scraping Resilience

5. **Beatport changes API response formats without warning** — The label search API silently renamed fields (`name` -> `label_name`, `results` -> `data`). The scraper returned 0 results instead of erroring. Solution: always try multiple field name variants, fail with clear errors, and maintain test fixtures for both old and new response formats.
   - Source: `docs/solutions/integration-issues/beatport-search-api-format-change.md`
   - **Key principle:** Beatport has no versioned API. Minimize impact via dual-format parsing and centralized extraction logic.

### Spotify API Handling

6. **Rate limit: cap wait at 60s, save state, abort** — Spotify sometimes returns Retry-After values of 22+ hours. Never wait that long. Cap at 60s, retry once on short waits, raise error on long waits. Always save cache/state before aborting so work isn't lost.
   - Source: `docs/solutions/integration-issues/spotify-rate-limit-handling.md`
   - **Chrome extension adaptation:** Show a countdown timer in the popup UI. Pause matching, resume after Retry-After. Save partial results to `chrome.storage.session`.

### Security

7. **Never render API data as raw HTML** — Beatport track/artist names are untrusted input. The Python web frontend had XSS vulnerabilities from using `innerHTML` with template literals. Preact's JSX escapes by default (safe), but never use `dangerouslySetInnerHTML` with Beatport/Spotify data.
   - Source: `docs/solutions/security-issues/web-frontend-xss-and-type-safety-fixes.md`

### Architectural Patterns to Preserve

8. **Dependency injection over globals** — The Python project passes Spotify client, cache, and state managers as function parameters, never global singletons. The Chrome extension should follow the same pattern: pass dependencies into functions, don't rely on module-level state (especially important since service workers are ephemeral).
   - Source: `.claude/docs/architectural_patterns.md`

9. **Silent degradation for file/storage loads** — If cache is missing or has wrong version, start fresh instead of crashing. Same for `chrome.storage.local`: if data is corrupt or missing, initialize empty and continue.
   - Source: `.claude/docs/architectural_patterns.md`

10. **Versioned storage envelopes** — All persistent JSON uses `{"version": N, ...}` wrapper. Check version on load, migrate or reset if mismatched. Essential for the Chrome extension cache as the format will evolve.
    - Source: `.claude/docs/architectural_patterns.md`

## Sources & References

### Internal References

- Matching algorithm: `djsupport/matcher.py` (normalization, scoring, multi-strategy search, selection)
- Beatport parsing: `djsupport/beatport.py` (__NEXT_DATA__ extraction, track composition)
- Label parsing: `djsupport/label.py` (pagination, deduplication)
- Spotify client: `djsupport/spotify.py` (search, playlist CRUD, rate limiting)
- Cache format: `djsupport/cache.py` (key generation, lookup/store, retry eligibility)
- Track dataclass: `djsupport/rekordbox.py` (shared Track interface)

### External References

- [Chrome Manifest V3 docs](https://developer.chrome.com/docs/extensions/develop/migrate/what-is-mv3)
- [chrome.identity API](https://developer.chrome.com/docs/extensions/reference/api/identity)
- [chrome.storage API](https://developer.chrome.com/docs/extensions/reference/api/storage)
- [Spotify PKCE Authorization](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow)
- [Spotify Rate Limits](https://developer.spotify.com/documentation/web-api/concepts/rate-limits)
- [WXT Framework](https://wxt.dev/)
- [fuzzball.js](https://github.com/nol13/fuzzball.js)
- [Spotify OAuth migration (Nov 2025)](https://developer.spotify.com/blog/2025-10-14-reminder-oauth-migration-27-nov-2025)

### Related Work

- Previous plan: `docs/plans/2026-02-26-feat-beatport-chart-import-plan.md`
- Previous plan: `docs/plans/2026-03-14-feat-web-frontend-beatport-sync-plan.md`
