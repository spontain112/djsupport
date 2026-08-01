# Playlist management roadmap after 0.4.0

**Status:** proposed

**Planning horizon:** 0.5.0–0.8.0

**Evidence base:** [playlist-management API review](../research/2026-08-01-playlist-management-api-review.md)

**Baseline:** DJ Support 0.4.0 at `5ad78c5894e9ff3eae640a81d7a63f8e9b767e87`

## Purpose and product boundary

DJ Support exists to let a DJ safely reproduce, review, and manage selected
Rekordbox playlists and Beatport charts or labels in Spotify. “Safely” means
the user can see what will happen, distinguish a source change from an edit
made in Spotify, approve matching knowledge deliberately, recover from partial
failure, and keep private music-library data out of the repository.

The durable `Transfer` domain remains the deep policy seam. It owns Preview,
matching and retained knowledge, Approval and Correction meaning, Mirror and
Snapshot publication, Playlist Drift choices, Orphaned Mirror disposition,
Batch cost policy, checkpoints, and recovery. Spotify, Rekordbox, and Beatport
integrations return typed facts and capability failures. CLI and web remain
thin adapters. A future Chrome extension may capture a Beatport selection and
present Preview, review, confirmation, and status, but it must call the same
Transfer authority; it must not port matching, Approval, publication, or
playlist state into a second client-side authority.

This roadmap summarizes API facts needed for sequencing. It deliberately does
not duplicate the maintained endpoint tables, contract audit, or official
source list in the [API review](../research/2026-08-01-playlist-management-api-review.md).

## Planning principles

1. Correctness and recovery precede convenience. Contract migration, stable
   identity, typed ordered reads, snapshot concurrency, and current known
   defects ship before broader playlist-management UX.
2. Read before writing. Every mutation is preceded by a Preview or explicit
   plan, an immediately fresh head check where concurrency matters, and user
   confirmation. No Drift, Correction, restore, metadata, or orphan decision is
   inferred.
3. Preserve occurrence and order. Duplicate Spotify URIs can represent valid
   source occurrences; backup, diff, restore, and repair must not deduplicate.
4. Spend the minimum scope and requests. Add `playlist-read-private` because
   current private-playlist reads require it. Do not add collaborative, image,
   library, playback, or other scopes until a separately accepted capability
   needs one.
5. Treat capability status as product truth. Official current Spotify
   endpoints may be used; deprecated routes require migration or an explicit
   compatibility boundary. Beatport page data is undocumented/inferred and its
   official API is restricted/partner-only. Rekordbox offers official XML
   interchange, not a public real-time playlist-management API. Spotify has no
   true playlist delete, folder API, snapshot history/rollback, atomic replace over
   100 items, or documented exact duplicate-occurrence removal.
6. Design for Development Mode. A Premium app owner and at most five allowlisted
   users, pooled developer-account quota, the undisclosed rolling 30-second
   rate window, `Retry-After`, and `QUOTA_EXCEEDED` are release constraints—not
   operational footnotes. Extended Quota is not assumed.
7. Research issues remain research. An umbrella or prototype supplies evidence;
   it does not authorize production implementation. Follow-up implementation
   tickets need bounded acceptance criteria and dependencies.

## Opportunity ranking

Scores use 5 as best for value and architectural fit; 1 as lowest/best for
effort, API cost, and risk. “Class” separates reliability/correctness (`R`),
convenience/UX (`U`), and speculative expansion (`S`).

| Rank | Opportunity | Class | Value | Fit | Effort | API cost | Risk | Roadmap disposition |
| ---: | --- | :---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | Current Spotify contract, scopes, and account identity | R | 5 | 5 | 3 | 1 | 2 | 0.5 foundation |
| 2 | Typed ordered playlist reader and snapshot-aware Drift | R | 5 | 5 | 3 | 1 | 2 | 0.5 tracer, completed in 0.6 |
| 3 | Approval snapshot guard and publication checkpoints | R | 5 | 5 | 3 | 1 | 3 | 0.5 |
| 4 | Read-only live QA | R | 4 | 5 | 2 | 2 | 2 | 0.6 |
| 5 | Exact private playlist backup and restore Preview | R | 5 | 5 | 4 | 4 | 3 | 0.6 |
| 6 | Confirmation-gated checkpointed restore | R | 5 | 5 | 4 | 4 | 5 | 0.7 |
| 7 | Minimal reorder/Correction planner | R | 4 | 4 | 4 | 2–5 | 4 | 0.7 |
| 8 | Review clarity defects (#56, #60, #61) | R/U | 4 | 5 | 2–3 | 1 | 2–3 | #60 in 0.5; #56/#61 in conditional 0.5.x |
| 9 | ISRC/market-aware validation and measured lookup | R/S | 4 | 4 | 3 | 3 | 2–4 | 0.8 only after #42 evidence |
| 10 | Conservative candidate/metadata recovery | U/S | 3 | 4 | 2–4 | 1–5 | 3 | 0.8 as separate evidence-backed slices |
| 11 | Opt-in metadata reconciliation | U | 3 | 4 | 2 | 1 | 4 | 0.8, if JC selects fields |
| 12 | Chrome capture/review/status adapter | U | 3 | 5 | 4 | same as Transfer | 3 | Separate workspace after stable service contract |
| 13 | Cover backup/upload | U/S | 2 | 2 | 3 | 2 | 4 | Deferred |
| 14 | Official Beatport API adapter | S | 4 | 4 | 5 | unknown | 4 | Blocked on written access and contract |

Effort and API-cost scores are comparative, not delivery estimates. The most
important ordering result is that read models and concurrency protection unlock
several later capabilities while adding little steady-state request cost.

## 0.5.0 — Trustworthy Spotify foundation

### Outcome and target user story

**Outcome:** DJ Support uses the current Spotify contract, identifies the
account durably, reads playlist contents correctly, and never approves or
continues publication across an unnoticed concurrent edit.

**User story:** “Before I rely on a Mirror or approve a Provisional Playlist, I
want DJ Support to understand the playlist Spotify actually returned and stop
safely if it changed under me.”

### Included capability slices

- Migrate the Spotify adapter to current-user creation and `/items` contracts;
  pin a verified client version and add adapter contract tests that reject
  accidental legacy `/users/{user_id}` creation and `/tracks` item routes.
- Add only `playlist-read-private`, with explicit re-consent and a clear
  capability error. Keep existing modify scopes. Do not request
  `playlist-read-collaborative`.
- Version-migrate stored profile `id` keys to current `account_id` for
  manifests, Transfer/Batch state, and account publication locks. Preserve
  resumability and redact identifiers from logs and reports.
- Introduce typed `PlaylistHead`, `PlaylistItem`, page, mutation-result, and
  capability-error facts behind the Spotify protocol. Read minimal fields;
  support current `item` and intentional legacy migration compatibility;
  preserve order and duplicate occurrences; classify null, local, episode or
  future item types, restriction/playability uncertainty, and relinking.
- Retain every returned mutation `snapshot_id`; checkpoint every add/replace
  chunk. Approval uses head → paginated ordered read → head: mismatched heads
  discard the read and require re-review rather than approving a mixed version.
- Distinguish ordinary 429 handling from `QUOTA_EXCEEDED`; checkpoint and pause
  with user guidance. Honor `Retry-After`, jitter bounded retries, and never
  sleep indefinitely.
- Fix curator retention through shared Beatport intake, Preview, publication,
  and resume for [#60](https://github.com/spontain112/djsupport/issues/60),
  beginning with a synthetic reproduction of the unhandled metadata shape.

### Conditional 0.5.x follow-ups

- Ship material-duration discrepancy classification
  [#56](https://github.com/spontain112/djsupport/issues/56) after JC defines
  the boundary, missing-duration behavior, visible reason, and tie-break.
- Ship human-readable Provisional Playlist descriptions
  [#61](https://github.com/spontain112/djsupport/issues/61) only after the
  durable publication-discovery replacement and final copy are decided and
  verified. These follow-ups are not part of the 0.5.0 release gate.

### Dependencies and sequencing

1. Adapter contract tests and pinned client.
2. Least-privilege scope migration.
3. Account identity schema migration.
4. Typed head/items reader.
5. Snapshot-aware Approval and publication checkpoints.
6. #60 shared intake correction; conditional #56/#61 work follows the relevant
   decision and recovery dependency.

#61 cannot remove the visible marker before a durable, account-scoped,
crash-safe way to find an interrupted publication has synthetic recovery tests.
#60 starts by creating a deliberately synthetic failing payload shape from the
specified behavior; it does not depend on receiving user page data. #56 needs
JC’s exact duration boundary and visible classification.

### API endpoints and scopes

- Official/current: current-user profile (`GET /me`), current-user playlists,
  current-user playlist creation, `GET /playlists/{id}`, and
  `GET /playlists/{id}/items`; add/replace item routes used by existing
  publication.
- Scope change: add `playlist-read-private`; retain
  `playlist-modify-private` and `playlist-modify-public` while public playlist
  behavior remains supported.
- Deprecated/legacy: user-specific playlist creation, playlist `/tracks`
  routes/shapes, and playlist-specific follow/unfollow must not be the basis of
  new promises. Removal semantics are deferred until a current supported
  contract is selected; “delete” must not claim erasure.

### Request cost and rate-limit impact

- Contract and identity changes add no steady-state calls beyond the needed
  current-user identity read.
- A head probe is one request. Unchanged heads avoid item pagination; changed or
  unknown heads cost `ceil(I/50)` item-page calls.
- Publication still costs one create plus one replace for the first 100 URIs
  and one add per subsequent 100. The difference is that snapshots and chunk
  identity are retained for safe resume. Because add/replace have no snapshot
  precondition, Transfer re-reads the head before each later chunk and compares
  it with the prior mutation result; a mismatch aborts. An external edit can
  still occur between that check and the write, so this narrows and detects many
  races but cannot provide atomic publication.
- Development Mode quota remains pooled across all client IDs. Tests must
  distinguish ordinary rolling-window rate limiting from quota exhaustion.

### Privacy, security, and migration risks

- OAuth re-consent is a user-visible migration. A denied read scope must degrade
  to a precise unavailable capability, never a broadened scope request.
- `account_id`, playlist IDs, ordered items, snapshots, and recovery keys are
  private application data under ADR-0001. Logs and repository fixtures remain
  redacted/synthetic.
- Identity and publication-state migration can strand resumable work if it is
  not idempotent, backup-first, and compatible with schema-v4 manifests.
- Null or unexpected items must be represented as facts; silently dropping
  them could make Approval or a later restore destructive.

### Validation strategy

- **Offline:** HTTP contract fakes for route/method/fields/scopes; synthetic
  current and legacy shapes; null/local/episode/relinked/restricted/duplicate
  ordered items; account-ID migration, crash/restart, snapshot mismatch,
  chunk-failure resume, `Retry-After`, and `QUOTA_EXCEEDED` tests. Synthetic
  curator parser fixtures for #60; conditional #56 uses synthetic boundary
  tests, while #61 uses publication discovery/recovery and copy assertions.
- **Live (separately gated):** one read-only allowlisted-account smoke test for
  `/me`, private playlist discovery, head, and paged items; one explicitly
  confirmed disposable-playlist publication/recovery test with a stated call
  budget. No live test is part of the default suite.

### Release gate

All supported Spotify calls have contract tests against current routes;
existing state migrates idempotently and remains resumable; Approval aborts on
either head mismatch around its paginated read; publication detects head
changes between its chunks, resumes without duplicate playlists or duplicate
chunks, and documents its irreducible race window; #60 passes shared intake,
Preview, publication, and resume tests; scopes are least-privilege; the full
offline suite and privacy checks pass. #56 and #61 remain explicit known
limitations until their conditional 0.5.x gates are met.

### Explicit non-goals

No Drift restoration, full-library backup, playlist restore, arbitrary reorder,
collaborative playlist support, true deletion claim, cover management, Chrome
extension, ISRC lookup, or new Beatport API integration.

## 0.6.0 — Explain and preserve playlist state

### Outcome and target user story

**Outcome:** a user can cheaply tell whether a Mirror changed, understand the
kind of change without mutation, inspect playlist health, and create an exact
private backup with a zero-mutation restore Preview.

**User story:** “Show me whether Spotify still represents my selection, why it
differs, and exactly what recovery would cost before anything changes.”

### Included capability slices

- Add a snapshot-aware Playlist Drift service inside Transfer. An unchanged
  snapshot returns a fast no-Drift result without item reads. A changed snapshot
  produces a read-only, ordered, occurrence-preserving classification of source
  change versus membership, order, availability, relinking, metadata, and
  unknown-item differences. Restore or Approved Match revocation remains an
  explicit later choice.
- Add read-only live QA through structured Transfer reports, exposed consistently
  in CLI and web: head/count/order, duplicates, null/local/episode items,
  unavailable or restricted items, relinking, marker/recovery identity, rename,
  ownership/account, and permission/capability errors.
- Add a versioned private playlist-backup schema and bounded selection. Preserve
  exact order, duplicate occurrences, intended and observed identity,
  provenance needed for recovery, snapshot, and minimal metadata. Do not store
  expiring image URLs or unnecessary catalog payloads.
- Add restore Preview only: validate the archive and destination ownership,
  compare the fresh head, produce the exact replace/add/reorder plan and request
  estimate, expose partial-failure boundaries, and make zero Spotify mutations.
- Improve Batch preflight with discovery/page/chunk estimates and a quota-aware
  pause projection. Broad backup requires explicit playlist selection or an
  explicit all-owned-playlists choice.

### Dependencies and sequencing

Typed head/items reader and stable account identity from 0.5 → Drift classifier
→ live QA → backup schema → restore Preview and cost estimator. Backup/Preview
must settle its schema before 0.7 adds a mutating restore.

### API endpoints and scopes

- Official/current read-only calls: current-user playlists,
  `GET /playlists/{id}`, filtered/paged `GET /playlists/{id}/items`, and only
  where necessary `GET /tracks/{id}`.
- Scope: `playlist-read-private`; no scope expansion.
- Capability labels: snapshot IDs are official opaque version identities, not
  a history API. Spotify has no server-side rollback. Local items, nulls, and
  removed Development Mode fields must remain explicit unknown/unrestorable
  facts rather than guessed metadata.

### Request cost and rate-limit impact

- No-Drift fast path: one head request per Mirror.
- Changed/unknown Drift or one exact backup: head plus `ceil(I/50)` item reads.
- Owned-playlist discovery: `ceil(P/50)` calls, then selected playlist reads.
- Per-track enrichment is avoided by default because multi-get track metadata
  is removed in the current Development Mode contract; any enrichment estimate
  must count one-track reads explicitly.
- All workflows checkpoint pagination and stop safely on rate/quota exhaustion.

### Privacy, security, and migration risks

- Playlist contents, order, names, IDs, snapshots, provenance, QA reports, and
  backup archives are private user data in versioned application storage.
- Backup retention is bounded and user-controlled. Exports require an explicit
  destination; repository paths are rejected or warned against. Logs use counts
  and redacted identifiers.
- A schema that drops duplicate occurrences, unknown items, or intended versus
  observed relink identity would make later restore unsafe and fails the gate.
- Read-only does not mean privacy-free: users must knowingly grant private
  playlist access and select broad discovery/backup.

### Validation strategy

- **Offline:** synthetic snapshots and ordered pages covering unchanged/changed
  heads, duplicate occurrences, null/local/episode/unavailable/relinked items,
  rename/ownership/permission cases, pagination boundaries (0/1/50/51/1001),
  backup round-trip, corrupt/unknown schema, and exact request estimates. Assert
  zero `POST`/`PUT`/`DELETE` calls in Drift, QA, backup, and restore Preview.
- **Live (separately gated):** bounded read-only QA and backup of explicitly
  selected owned test playlists, with redacted aggregate comparison and a
  declared maximum request count. No user playlist data enters Git.

### Release gate

Unchanged Drift uses only a head probe; changed Drift never chooses a remedy;
backup round-trips order and duplicates exactly; restore Preview makes zero
mutations and reports calls/risks; broad reads require explicit selection;
private data passes backup, privacy, and migration review.

### Explicit non-goals

No restore apply, automatic Drift repair/revocation, playlist deletion,
metadata overwrite, arbitrary duplicate removal, cover backup, catalog-wide
enrichment, matching expansion, or extension-side authority.

## 0.7.0 — Guarded recovery and minimal repair

### Outcome and target user story

**Outcome:** a user can explicitly restore or repair an owned playlist with
optimistic concurrency, checkpointed resume, and the smallest safe mutation.

**User story:** “After reviewing an exact plan, restore this playlist or repair
this approved difference—and stop if Spotify changed since I confirmed.”

### Included capability slices

- Apply a versioned backup only after explicit confirmation immediately before
  mutation and a fresh expected-head check. Replace the first 100 items, append
  ordered chunks of 100, retain each returned snapshot and operation identity,
  and resume idempotently after partial failure. Before each later chunk,
  compare a fresh head with the prior returned snapshot and abort on mismatch.
  Since add/replace accept no snapshot precondition, an external write between
  check and mutation remains an irreducible time-of-check/time-of-use window;
  verify the head after each write and report an uncertain partial outcome when
  the observed result is not the expected snapshot.
- Add a minimal repair planner owned by Transfer. Prefer contiguous range
  reorder with snapshot preconditions; use documented safe removal only where
  occurrence semantics are unambiguous; fall back to a fully Previewed and
  confirmed replace when duplicates or the current removal schema make a
  minimal plan unsafe.
- Route Correction application through the same plan/confirmation/head guard.
  Validate a proposed Spotify track read-only for current market playability,
  restrictions, relinking, identity, and available ISRC evidence before it can
  become an Approved Match. A relinked observed URI never silently replaces the
  intended Approved Match identity.
- Offer explicit Playlist Drift choices: restore playlist state or revoke the
  affected Approved Match. Neither is selected by default. Orphaned Mirror
  library removal likewise requires a fresh capability/head check and explicit
  confirmation, and UI language must not promise true deletion.
- Surface chunk progress, snapshot changes, pause reason, recovery instructions,
  and partial outcomes consistently in CLI and web.

### Dependencies and sequencing

0.6 backup schema and restore Preview + 0.6 Drift classifier → checkpointed
replace/add restore → range-reorder planner → safe Correction and Drift actions.
Minimal removal is optional until duplicate-occurrence behavior is documented
or avoidance is proven; full confirmed replace is the safe fallback.

### API endpoints and scopes

- Official/current mutations: replace/add items; reorder range with optional
  `snapshot_id`; documented remove-items only for unambiguous cases.
- Official/current reads: fresh playlist head/items and `GET /tracks/{id}` for
  Correction validation.
- Scopes: existing playlist modify scopes plus `playlist-read-private`; no new
  scope. Private/public ownership and collaborator permission failures are
  reported as capabilities.
- Unavailable/unsafe: no history rollback, no atomic >100 replace, no arbitrary
  bulk permutation, and no assumed position-targeted duplicate removal.

### Request cost and rate-limit impact

- A 1,001-item full restore costs at least one fresh head, one replace, and ten
  adds, plus any validation reads; it creates multiple snapshots and may
  partially complete.
- Reorder cost is one request per contiguous move; complex permutations can be
  more expensive than a replace. Preview compares both and includes risk, not
  only request count.
- Correction validation can add one track read per distinct proposed target.
- Checkpoint before every wait/exit. `QUOTA_EXCEEDED`, long `Retry-After`, head
  mismatch, permission loss, or unexpected response shape pauses rather than
  continuing.

### Privacy, security, and migration risks

- Restore archives and mutation journals contain private ordered playlist and
  account state; retain locally, version them, redact reports, and support
  backup-before-schema-migration.
- Replace is destructive to current membership and order. Confirmation must
  display destination, occurrence counts, loss/unknown-item risks, operation
  count, and the fresh expected head.
- Partial completion is inherent above 100 items. Idempotent operation/chunk
  identity and accurate status are release-critical.
- Corrections remain user intent. Validation may reject or request review but
  never infer the Correction or Approval.

### Validation strategy

- **Offline:** state-machine and adapter fakes for head races before and between
  chunks, duplicate and order preservation, every chunk boundary, retry/resume,
  ambiguous removal fallback, multi-move reorder, partial failure, permission
  loss, rate/quota pause, relinking/market restriction, and Approval Conflict.
  Assert no mutation occurs without an explicit confirmed plan.
- **Live (separately gated):** disposable owned playlist only; exact fixture
  with duplicates and >100 items; independently authorized confirmation;
  bounded mutation budget; verify final ordered state and recovery after one
  deliberately interrupted synthetic/fake run before any live interruption.

### Release gate

Every mutation has Preview, explicit confirmation, the strongest available
fresh-head checks, and durable recovery. Detectable head changes abort; the
irreducible add/replace race window is disclosed and an unexpected post-write
head becomes an uncertain partial outcome. Duplicate/order round-trip is exact.
Partial failure is truthful and resumable. Unsafe minimal repair falls back to
confirmed replace. No default or unattended destructive action exists.

### Explicit non-goals

No server-side rollback claim, atomic large restore claim, automatic conflict
resolution, collaborative playlist mutation, general-purpose playlist editor,
bulk delete/unfollow, cover upload, or extension-owned mutation workflow.

## 0.8.0 — Evidence-led matching and adapter readiness

### Outcome and target user story

**Outcome:** review becomes clearer and matching recall can improve only where
bounded evidence shows equal or better correctness at an acceptable request and
privacy cost; Transfer exposes a stable service contract for additional UIs.

**User story:** “Help me find difficult catalog representations and review them
from the interface I prefer, without weakening Approval or exposing my local
library.”

### Included capability slices

- Treat [#31](https://github.com/spontain112/djsupport/issues/31) as a research
  umbrella and [#42](https://github.com/spontain112/djsupport/issues/42) as its
  bounded evidence task. Phase A is synthetic. Any local Rekordbox/audio access
  and any live Spotify sampling require separate explicit authorization and
  aggregate-only reporting. Only an accepted result may produce a new,
  narrowly specified implementation ticket.
- If evidence supports it, add ISRC as secondary identity evidence after
  Approved Match and retained matching-knowledge reuse. Verify the returned
  ISRC and
  title/artist/version/duration/market behavior; classify multiple release
  instances, ambiguity, unplayability, relinking, and mismatch. No scope change.
  Local-file tag access remains a separate opt-in source capability, bounded to
  exact user-selected `file:` URIs; it never scans directories.
- Treat [#39](https://github.com/spontain112/djsupport/issues/39) as two measured
  candidate-recall experiments (candidate limit and fallback trigger). Promote
  independently only when synthetic or explicitly consented truth shows added
  correct matches without added wrong matches, with request counts reported.
- Treat [#32](https://github.com/spontain112/djsupport/issues/32) as an umbrella.
  A terminal audio-extension query variant may become a narrow ticket; missing
  artist parsing requires separate evidence; mastering/catalog/numbering cleanup
  remains unticketed until each grammar has paired positive/negative truth.
  Source intake and source identity remain lossless.
- Stabilize an adapter-neutral Transfer service contract for selection capture,
  Preview, review facts, explicit confirmation, progress/status, and results.
  CLI and web use it first. The historical Chrome plan is not implementation
  authority: if pursued in the dedicated extensions workspace, Chrome may
  capture visible Beatport selection data and render these service facts, but
  may not hold an independent matcher or matching-knowledge store, approve
  knowledge, or publish.
- Optionally add per-field playlist metadata reconciliation only after JC
  chooses supported fields and defaults. Each field change gets Preview and
  explicit confirmation; privacy/collaboration changes never ride implicitly
  with content repair.

### Dependencies and sequencing

0.5–0.7 typed facts, status, confirmation, and recovery → complete #42/#39/#32
evidence → create separate implementation tickets for accepted slices → expose
the already-authoritative Transfer service contract → optional adapter work in
its own workspace. Matching experiments do not block adapter contract work, and
the adapter does not justify matching duplication.

### API endpoints and scopes

- Matching/validation: official Search and, where justified, one-track reads.
  Search supports ISRC filtering; ISRC is evidence, not guaranteed unique
  Spotify object identity.
- Adapter status/Preview use the same current playlist endpoints and scopes as
  Transfer; a browser UI receives application facts rather than direct Spotify
  authority.
- Optional metadata: current playlist-details update, existing modify scope;
  no collaborative scope unless collaboration becomes a separately approved
  product capability.
- Beatport official API remains restricted/partner-only; current page parsing
  remains undocumented/inferred. Rekordbox remains explicit local XML/file
  intake, not live synchronization.

### Request cost and rate-limit impact

- Approved Match and retained matching knowledge remain zero-call first choices.
- A safe ISRC strategy costs at most one search per distinct normalized ISRC;
  an unsafe/no-hit result can add that call before fuzzy fallback. Measure
  `ISRC searches + fuzzy fallbacks - baseline fuzzy searches`, not a theoretical
  percentage.
- Raising Search results from five to ten adds payload/scoring cost but not an
  HTTP call. Broader fallback can add one request to an unresolved lookup.
- Chrome does not receive a separate quota budget: all calls remain subject to
  the same pooled Development Mode constraints through Transfer.

### Privacy, security, and migration risks

- Local audio tags, paths, raw ISRCs, search observations, Corrections, and
  matching truth are private user data. Repository fixtures are synthetic or
  explicitly exported, consented, and privacy-reviewed.
- Browser page data is untrusted. Render as text, minimize captured fields,
  bound retention, and never send Spotify content into an ML/AI model.
- A browser token or parallel matching-knowledge store would expand attack
  surface and
  split authority; this roadmap rejects that design.
- Metadata reconciliation can overwrite user-authored text or visibility, so it
  is opt-in per field and separately confirmed.

### Validation strategy

- **Offline:** #42 synthetic matrix; A/B matcher truth tables and request
  counters for #39; paired conservative/no-op metadata variants for #32;
  property/contract tests proving Approved Match / retained matching-knowledge
  precedence, ambiguity to
  review, and no source-identity rewrite. Adapter contract tests prove identical
  Transfer outcomes across CLI, web, and a fake capture/status client.
- **Live/private (each separately gated):** only bounded samples named in the
  relevant issue, with maximum request counts and aggregate/redacted results.
  Local-file and live-Spotify phases need independent approval. Any future
  Chrome end-to-end mutation test needs its own authorization and disposable
  playlist.

### Release gate

No research umbrella ships as behavior. Each matching change has an accepted
follow-up implementation ticket, truth-backed correctness comparison, explicit
request delta, privacy review, and no Approval bypass. The Transfer service
remains the sole policy/publication authority. Optional metadata fields and
Chrome pursuit have explicit JC decisions.

### Explicit non-goals

No aggressive “clean everything” normalization, `items[0]` ISRC acceptance,
automatic local-file access, live Rekordbox integration, independent browser
matcher/matching-knowledge/OAuth publication engine, public extension
distribution promise,
official Beatport adapter without written access, recommendations/audio
features, or cover management.

## Dependency map

```text
0.5 current-route contract + least-privilege scope
  ├── stable account identity migration
  │     ├── typed playlist head/items reader
  │     │     ├── snapshot-guarded Approval/publication
  │     │     ├── 0.6 snapshot-aware Playlist Drift
  │     │     │     ├── read-only live QA
  │     │     │     └── 0.7 Drift choices/minimal repair
  │     │     └── 0.6 exact private backup + restore Preview
  │     │           └── 0.7 checkpointed restore
  │     │                 └── minimal reorder/Correction planner
  │     └── durable publication discovery replacement
  │           └── #61 human-readable descriptions
  └── Transfer typed facts/status/confirmation contract
        ├── CLI and web parity
        └── 0.8 optional Chrome capture/review/status adapter

#42 evidence ──> possible ISRC implementation ticket ──> 0.8 matching slice
#39 evidence ──> separate candidate-limit/fallback tickets ──> 0.8 slices
#32 evidence ──> separate conservative query tickets ──> 0.8 slices
#56 decision + tests ──> 0.5 review classification
#60 synthetic reproduction ──> 0.5 shared Beatport intake fix
```

## Recommended next tracer bullet

Implement the **typed playlist head/items reader plus snapshot-aware unchanged
probe inside Transfer**, on top of a narrow current-route contract test.

It is the smallest end-to-end slice that proves the roadmap’s central seam:
Spotify returns current typed facts; Transfer decides whether an unchanged
Mirror needs further work; CLI and web only display the result. It provides
immediate user value (a safe, one-call “unchanged” answer), reduces quota cost,
exposes current `item`/null/order/relinking contract gaps early, and unlocks
Approval guarding, Drift classification, live QA, backup, restore, and repair.
Keep the first slice read-only: one expected snapshot, one unchanged result,
one changed result that pages ordered items and reports facts, with no remedy or
mutation. The broader 0.5 migration remains the release prerequisite even if
this vertical slice is built first to validate the design.

## Issue integration and ticket discipline

| Issue | Current role | Roadmap treatment | Promotion gate |
| --- | --- | --- | --- |
| [#31](https://github.com/spontain112/djsupport/issues/31) | Research umbrella | 0.8 evidence frontier; not implementation | Accepted #42 aggregate result and a new bounded ticket |
| [#32](https://github.com/spontain112/djsupport/issues/32) | Research umbrella | Separate conservative query hypotheses | Truth-backed grammar, precision/recall and call-count ticket |
| [#39](https://github.com/spontain112/djsupport/issues/39) | Human judgment/measurement | Separate candidate-limit and fallback experiments | Correctness A/B plus request cost; new ticket per accepted change |
| [#42](https://github.com/spontain112/djsupport/issues/42) | Bounded prototype | Evidence only; synthetic Phase A first | Separate approval for local and live phases; accepted redacted report |
| [#56](https://github.com/spontain112/djsupport/issues/56) | Bug needing product detail | Conditional 0.5.x review-correctness slice | Exact duration boundary, missing-duration rule, label/reason, tie-break |
| [#60](https://github.com/spontain112/djsupport/issues/60) | Specified bug | 0.5 source-intake slice | Synthetic reproduction plus shared intake/Preview/publication/resume tests |
| [#61](https://github.com/spontain112/djsupport/issues/61) | Bug needing recovery contract | Conditional 0.5.x recovery/UX slice | Replacement discovery/idempotence contract and desired copy |

Research findings may refine priorities, but their issue number must not be put
on a production PR as though it already specifies implementation.

## Confirmation, data-access, and scope boundaries

| Action | Read/mutation | Required user boundary |
| --- | --- | --- |
| Preview, head probe, Drift analysis, live QA, backup, track validation | Read-only Spotify access | OAuth consent for minimum read scope; explicit playlist/Batch selection for private or broad data; private storage and bounded retention |
| Read Rekordbox XML | Local private read | User-selected file and bounded playlist/Batch |
| Read local audio tags | Local private read | Separate explicit opt-in for exact selected `file:` URIs; no scanning |
| Create a Provisional Playlist or Snapshot/Mirror publication | Spotify mutation | Explicit command/action after Preview/cost visibility |
| Add, replace, remove, or reorder items | Spotify mutation | Explicit plan confirmation immediately before a fresh head check |
| Approval or Correction application | Spotify/local-authority mutation | Playlist-scoped Approval; Correction supplied explicitly; conflicts require review |
| Restore or Drift restoration | Destructive Spotify mutation | Exact Preview, destination/head confirmation, risk/cost display, resumable checkpoint |
| Revoke Approved Match | Local-authority mutation | Explicit Drift choice; never coupled silently to playlist change |
| Orphan library removal | Spotify mutation with non-delete semantics | Explicit disposition and current capability wording |
| Metadata/privacy/collaboration change | Spotify mutation | Per-field Preview and confirmation; additional scope only for separately accepted capability |
| Live API validation or user-derived evidence export | Gated operation | Separate stated authorization, bounds, redaction, and destination |

## Decision log

### Decisions already made

- Transfer is the sole deep policy seam; CLI, web, and future UI surfaces are
  adapters.
- A Transfer publishes a Mirror or Snapshot. Rekordbox defaults to Mirror;
  Beatport chart and label intake defaults to Snapshot.
- Preview never mutates Spotify playlists or publication manifests. Approval is
  playlist-scoped; Corrections and proposals become authoritative only through
  Approval.
- Playlist Drift, Orphaned Mirror disposition, relinking, broad Batch selection,
  and destructive mutation require explicit user choice.
- User-derived state and evidence stay in versioned private application storage
  under ADR-0001; repository fixtures are synthetic or explicitly consented.
- Development Mode is the supported planning baseline. Extended Quota, official
  Beatport access, live Rekordbox management, true delete, playlist folders, and
  server-side rollback are not assumed.
- The historical standalone Chrome architecture is out of this repository’s
  scope and is superseded as a product design. Any future extension is only a
  capture/review/status adapter to Transfer.
- OAuth scope growth is capability-driven and minimal; collaborative, image,
  library, and playback scopes are excluded from this horizon by default.

### Decisions requiring JC

1. **#56 classification policy:** exact material-duration boundary, boundary
   inclusivity, missing-duration behavior, user-facing label/reason, and
   closer-duration tie-break.
2. **#61 recovery and copy:** the replacement durable discovery contract and
   final human-readable Provisional Playlist description. This is architectural,
   because copy currently carries recovery identity.
3. **0.7 removal posture:** whether to omit selected-item removal until Spotify
   documents safe duplicate-occurrence semantics, or allow only provably
   unambiguous cases with confirmed full-replace fallback.
4. **0.8 metadata fields:** whether name, description, public/private state, or
   collaboration are supported, and which user edits should be considered
   authoritative. Recommendation: name/description Preview only first; defer
   privacy and collaboration.
5. **Chrome investment:** whether to fund a dedicated-workspace adapter after
   the Transfer service contract stabilizes. Recommendation: no browser work
   before 0.6 facts/status are stable; no independent Spotify authority.
6. **Research authorizations:** whether and when to authorize #42 local-file and
   live-Spotify phases and #39 controlled live verification. These are separate
   approvals with explicit bounds, not roadmap acceptance.
7. **Beatport official access:** whether to seek written partner approval. Until
   obtained, retain the existing parser as undocumented/inferred and design for
   expected breakage.
8. **Public/Extended Quota ambition:** whether the product remains personal and
   allowlisted or pursues broader distribution. No release here depends on
   Extended Quota.

## Roadmap success measure

The roadmap succeeds when a DJ can answer, before every write: what source
selection is represented, what differs, what calls and scopes are required,
what private data is read or retained, what exactly will mutate, and how to
recover if the operation stops. New UI surfaces or matching strategies count as
progress only when they preserve those answers through the same Transfer
authority.
