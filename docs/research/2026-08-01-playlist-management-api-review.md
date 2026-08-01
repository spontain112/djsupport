# Playlist-management API review

**Date:** 2026-08-01

**Code baseline:** released `main` at `d7c84f5f144b18920b0edcf32799b5bb8169bd46`

**Status:** Read-only research; no Spotify or Beatport API calls were made.

**Authority:** Repository source plus official Spotify, Beatport, and rekordbox documentation only.

## Executive summary

DJ Support can safely deepen playlist management, but compatibility and concurrency hardening should precede new product capabilities. Spotify's February 2026 Development Mode contract replaced legacy playlist `/tracks` resources with `/items`, replaced `POST /users/{user_id}/playlists` with `POST /me/playlists`, reduced Search's maximum page size to 10, and renamed playlist response fields. Extended Quota Mode apps were not forced to migrate, and Spotify postponed endpoint-access changes for existing Development Mode integrations on March 9; code should therefore feature-detect and contract-test rather than infer behavior from app age. In May 2026 Spotify added immutable `account_id` and explicitly directed integrations to use it instead of `id` for account linking. The current adapter still uses Spotipy methods associated with old routes and persists `current_user()["id"]` ([adapter](../../djsupport/transfer.py#L904), [scopes](../../djsupport/spotify.py#L12)).

The strongest post-roadmap capabilities are snapshot-aware read-only Drift detection, exact versioned playlist backup with an Approval-gated restore, read-only live QA for order/availability/null items/relinking, and minimal reorder/Correction planning. Beatport's official API is **restricted/partner-only**, requiring approval and an API key; the repository instead parses undocumented `__NEXT_DATA__` page internals ([chart intake](../../djsupport/beatport.py#L48), [label intake](../../djsupport/label.py#L62)). rekordbox publishes an XML interchange format and import/export workflow, not a public playlist-management web API. Policy must remain in the deep `Transfer` seam; adapters should expose capabilities and facts, not decide Preview, Approval, Drift, restore, or deletion policy ([Spotify protocol](../../djsupport/transfer.py#L458), [Transfer](../../djsupport/transfer.py#L1119)).

## 1. Current external endpoints and OAuth scopes

| Category | Repository call | Official endpoint/behavior | Scope and current-contract note |
|---|---|---|---|
| Read/search | `sp.search(type="track", limit=5)` ([source](../../djsupport/spotify.py#L78)) | `GET /search`; current Development Mode maximum 10 results | Catalog search; optional market. One to several searches per uncached source track. |
| Read membership/order | `playlist_items`, paged with `next` ([source](../../djsupport/transfer.py#L964)) | Current `GET /playlists/{id}/items`; owner/collaborator only under the current Development Mode contract; default/max 20/50 | Official reference lists `playlist-read-private`. Current requested scopes omit it, so private Provisional Playlist review is a scope gap. |
| Read playlist discovery | `current_user_playlists(limit=50)`, paged ([source](../../djsupport/transfer.py#L947)) | `GET /me/playlists`, max 50; private playlists need `playlist-read-private`, collaborative playlists need `playlist-read-collaborative` | Current scopes omit both read scopes; marker discovery can miss private playlists. |
| Playlist creation | `user_playlist_create(user_id, ..., public=False)` ([source](../../djsupport/transfer.py#L918)) | Legacy `POST /users/{user_id}/playlists` removed for the new Development Mode contract; use `POST /me/playlists` | `playlist-modify-private` for private creation. Names are non-unique; Spotify documents a general limit of 11,000 playlists/user. |
| Membership/order mutation | `playlist_replace_items` first 100, then `playlist_add_items` in 100-item chunks ([source](../../djsupport/transfer.py#L933), [repair](../../djsupport/transfer.py#L982)) | Current `PUT/POST /playlists/{id}/items`; maximum 100 URIs/request; replace overwrites, add preserves submitted order and can take a position | `playlist-modify-public` or `playlist-modify-private`. Each chunk is a separate mutation/snapshot and can partially complete. |
| Unfollow/removal | `current_user_unfollow_playlist` for provisional and Mirror deletion ([source](../../djsupport/transfer.py#L958)) | Playlist-specific follow/unfollow routes are deprecated in the new contract; generic library removal is `DELETE /me/library` | Spotify exposes no true playlist-delete endpoint. “Delete” must not promise erasure or history removal. |
| Metadata | `track(uri)` validates Corrections ([source](../../djsupport/transfer.py#L991)); Search reads name/artists/album/duration ([source](../../djsupport/spotify.py#L93)) | `GET /tracks/{id}` and `GET /search` | `external_ids` was restored in March 2026, enabling cautious ISRC-assisted matching. |
| Account identity | `current_user()["id"]` ([source](../../djsupport/transfer.py#L910)) | `GET /me`; since May 2026 use immutable `account_id` for linking | DJ Support needs no email. Migrate persisted state versionedly from `id` to `account_id`. |
| Recovery/rate limit | 429 `Retry-After`; one retry in simple wrapper ([source](../../djsupport/spotify.py#L46)); bounded 429/5xx/network retries in Transfer ([source](../../djsupport/transfer.py#L256)) | Undisclosed rolling 30-second rate limit; 429 normally supplies seconds in `Retry-After` | Spotify recommends backoff, batching, filtered/lazy reads, and cached `snapshot_id`. Endpoint-specific limits can apply. |
| Beatport intake | HTTPS GET chart/label pages; parse embedded `__NEXT_DATA__` ([chart](../../djsupport/beatport.py#L48), [label](../../djsupport/label.py#L98)) | **Undocumented page behavior**, not an official public API contract | No API key is used. Page structure, `per_page=150`, ordering, counts and anti-bot behavior are inferred and unstable. |
| rekordbox intake | Local XML parsing of `COLLECTION`, playlist `NODE`, ordered `TRACK Key` references ([source](../../djsupport/rekordbox.py#L32)) | Official XML export/import format, local file only | No OAuth, network call, remote mutation, snapshot/version API, or live-write API. |

The configured scope string is only `playlist-modify-public playlist-modify-private` ([source](../../djsupport/spotify.py#L12)). Add only scopes required by implemented features; do not request playback, email, top-items, library, collaborative, or image-upload access pre-emptively.

## 2. Official but unused Spotify capabilities

| Capability | Official endpoint | What it enables | Safety/fit |
|---|---|---|---|
| Playlist head/version | `GET /me/playlists`, `GET /playlists/{id}` | Cheap `snapshot_id`, count and metadata probes before downloading items | Excellent for Drift, resume, QA, and request reduction. Read-only but personal-data-bearing. |
| Filtered ordered items | `GET /playlists/{id}/items?fields=...` | Exact order, item type, null/unavailable/local status, added metadata and market-aware playability | Foundation for Approval, Drift, backup, restore Preview and live QA. |
| Remove selected items | `DELETE /playlists/{id}/items` | Minimal membership Correction | Current schema does not document position targeting; duplicate-occurrence semantics must not be assumed. Mutation and confirmation required. |
| Reorder a range | `PUT /playlists/{id}/items` with `range_start`, `insert_before`, `range_length`, optional `snapshot_id` | Minimal order-only Mirror repair or Correction | Good concurrency fit; complex permutations can require many moves. Mutation and confirmation required. |
| Change details | `PUT /playlists/{id}` | Reconcile managed name, description, privacy and collaboration state | User-visible policy; owner only; confirmation required. |
| Track metadata/ISRC | `GET /tracks/{id}`; Search returns `external_ids` where available | Stronger Correction validation and ISRC-assisted matching/live QA | Read-only. ISRC is evidence, not a uniqueness guarantee; relinking complicates durable identity. |
| Cover read/upload | `GET/PUT /playlists/{id}/images` | Reference backup and optional managed artwork | Upload needs `ugc-image-upload`, owner control, JPEG <=256 KB and can have custom throttling. Low priority. |
| Generic library save/remove | `PUT/DELETE /me/library` | Follow/unfollow replacement, potentially orphan disposition | Extra scopes and library mutation; not equivalent to deleting a playlist. Poor fit unless explicitly requested. |

There is no official endpoint to enumerate historical snapshots, restore an arbitrary historical snapshot, manage playlist folders, or truly delete a playlist. “Backup/restore” must mean DJ Support stores ordered facts privately, previews a diff, then performs new approved mutations.

## 3. Candidate-to-domain behavior

| Domain behavior | Useful capability | Result and boundary |
|---|---|---|
| Preview | Head/item reads plus a mutation plan | Show exact calls, additions/removals/moves, visibility changes and estimated request count; never call Spotify mutations. |
| Snapshot | Create plus replace/add chunks | Existing publication remains appropriate; retain each returned snapshot and checkpoint between chunks. |
| Mirror | Snapshot-head probe, ordered items, guarded reorder/replace | Skip unchanged heads; distinguish source changes from manual Spotify Drift before publication. |
| Approval | Ordered items read at an expected snapshot | Compare the reviewed Provisional Playlist with its manifest without racing a later edit; changed head requires re-review. |
| Correction | `GET /tracks/{id}`/ISRC validation; planned remove/reorder/replace | Validate availability and identity read-only first. Apply only through Approval after confirmation. |
| Drift | Cached `snapshot_id`, filtered items | Fast no-drift path; classify membership, order, availability, relinking and metadata drift. Never auto-restore or auto-revoke. |
| Orphaned Mirror | Playlist head/read plus local relationship facts | Confirm Spotify existence, then offer keep/relink/library-remove. Removal remains explicit. |
| Batch | Head preflight, estimator, checkpointed pagination/chunks | Improve expensive-Batch confirmation ([planning](../../djsupport/transfer.py#L1223)); pause safely on rate limits. |
| Backup/restore | Paged ordered reads; approved replace first 100 + append chunks | Exact private backup including occurrences/order/provenance. Restore creates a new version, not history rollback. |
| Live QA | Read-only head/items/track metadata | Detect null items, episodes/local items, unavailable/restricted tracks, wrong order, duplicates, renamed playlists and stale markers without mutation. |

## 4. Unavailable, restricted, deprecated, or unsafe

- **Spotify removed/deprecated for the new Development Mode contract:** legacy playlist `/tracks` paths/fields, `POST /users/{user_id}/playlists`, other-user playlist/profile reads, multi-get tracks/albums, and playlist-specific follow/unfollow. Recommendation, Audio Features and Audio Analysis access was removed for new Development Mode apps in November 2024. Extended Quota Mode and postponed existing-app enforcement make feature detection and contract tests essential.
- **Spotify unavailable:** playlist folders; true delete; snapshot-history listing or server-side rollback; atomic replacement beyond 100 items; arbitrary bulk permutation; guaranteed exact duplicate-occurrence removal under the current documented remove schema.
- **Spotify restricted/unsafe:** Development Mode is limited personal experimentation with a Premium app owner and up to five allowlisted users. As of July 23, 2026, a developer may create up to 25 client IDs, but all share one developer-account quota; quota exhaustion returns 429 with `reason: "QUOTA_EXCEEDED"`. Playlist items are owner/collaborator-only in the current contract. Spotify content cannot be downloaded, artwork cannot be altered, metadata/art require Spotify attribution and links, and Spotify content cannot be used to train or be ingested into an ML/AI model.
- **Beatport restricted:** the [official API terms](https://support.beatport.com/hc/en-us/articles/4414997837716-Terms-and-Conditions) describe approved licensees, issued API keys, approved uses and possible throttling/change. The [developer portal](https://api.beatport.com/v4/docs/v4/catalog/search/) is login-gated. No official public endpoint contract should be recommended for production until access is approved. Existing page parsing is **undocumented/inferred**, not API entitlement.
- **rekordbox local-only:** the [developer page](https://rekordbox.com/en/support/developer/) and [official XML format list](https://cdn.rekordbox.com/files/20200410160904/xml_format_list.pdf) document XML interchange. They provide no public live playlist-management API. DJ Support may improve XML validation/export compatibility but must not claim live rekordbox synchronization or version recovery.

## 5. Rate, pagination, snapshots, ordering, market and cost

- Spotify rate limits use an undisclosed rolling 30-second window; Development and Extended Quota differ. Development Mode quota is pooled across a developer's client IDs, and quota exhaustion is distinguishable by the 429 body. Honor `Retry-After`, inspect `reason`, jitter retries, and checkpoint before sleeping/exiting. Cover upload can have a separate limit ([rate-limit guide](https://developer.spotify.com/documentation/web-api/concepts/rate-limits), [July 2026 quota update](https://developer.spotify.com/blog/2026-07-23-web-api-quota-updates)).
- Playlist discovery costs `ceil(P/50)` calls; one full item read costs `ceil(I/50)`. Search returns at most 10 in the new contract but DJ Support requests 5. Full backup costs discovery plus head/item pages for every included owned playlist. Removal of multi-get track metadata makes enrichment expensive.
- Add and replace accept at most 100 URIs. A 1,001-item restore needs one replace plus ten adds, produces multiple snapshots and can partially complete. Persist operation/chunk identity for idempotent resume.
- `snapshot_id` is opaque version identity. Reorder and removal accept a snapshot precondition; documented add/replace do not. Read the head immediately before dangerous replace, serialize publishing by account (already present at [guard](../../djsupport/transfer.py#L297)), and abort on changed heads.
- Order is significant and duplicate occurrences are valid. Add preserves submitted order; replace overwrites all items; reorder moves a contiguous range using zero-based indexes. Never deduplicate during backup/restore.
- With a user token, account country takes priority over an explicit market. Without usable user country or market, content is considered unavailable. Relinking can return a playable alternative URI; February 2026 removed `linked_from` and `available_markets` from current Development Mode shapes. Store observed and intended identity separately, tolerate unknown restriction reasons, and never silently replace an Approved Match.

## 6. Code assumptions versus current official contracts

1. `user_playlist_create(self.account_id(), ...)` assumes the legacy user-specific route ([code](../../djsupport/transfer.py#L929)); migrate to current-user creation while retaining compatibility only where intentionally supported.
2. Spotipy `playlist_*_items` methods can map to old `/tracks` routes depending on the installed version; add adapter contract tests asserting `/items` and pin a verified client release ([dependency](../../pyproject.toml#L19)).
3. `current_user()["id"]` is durable account identity ([code](../../djsupport/transfer.py#L910)); current guidance requires `account_id`. Migrate manifests, locks and Transfer state versionedly.
4. Read scopes are absent although Approval, Drift and marker discovery read private playlists ([scope](../../djsupport/spotify.py#L12)). Add `playlist-read-private`; add `playlist-read-collaborative` only if collaboration becomes supported.
5. Item parsing expects `item["track"]` ([code](../../djsupport/transfer.py#L973)); current shape renamed it `item`, may return null and may include episodes/future types. A nonempty playlist can be misclassified as empty.
6. Playlist unfollow is labeled delete ([code](../../djsupport/transfer.py#L958)); the endpoint is deprecated in the new contract and its semantics are not true deletion.
7. Publication writes ignore returned `snapshot_id` and cannot detect concurrent edits between 100-item chunks ([code](../../djsupport/transfer.py#L933)).
8. Correction track lookup does not request/check market playability, restrictions, relinking or ISRC ([code](../../djsupport/transfer.py#L991)).
9. Beatport `per_page=150`, `__NEXT_DATA__` keys, ordering, counts and anti-bot markers are undocumented assumptions ([code](../../djsupport/label.py#L19), [parser](../../djsupport/beatport.py#L102)). Treat breakage as expected.
10. rekordbox parsing supports a narrow attribute subset and assumes `Type="0"` folders / `Type="1"` playlists ([code](../../djsupport/rekordbox.py#L71)); validate product/version and report unsupported nodes rather than claiming full-format support.
11. Current 429 handling inspects status and `Retry-After`, not the July 2026 response-body reason ([simple wrapper](../../djsupport/spotify.py#L46), [Transfer retry policy](../../djsupport/transfer.py#L256)). `QUOTA_EXCEEDED` should pause as quota exhaustion with user guidance rather than enter the ordinary rate-limit retry path.
12. Spotify still exposes `external_ids.isrc`, but Beatport chart and label parsers do not retain an ISRC field ([chart mapping](../../djsupport/beatport.py#L158), [label mapping](../../djsupport/label.py#L174)). ISRC-assisted work therefore requires an explicit source-model/schema change and must not be described as already available from Beatport intake.

## 7. Ranked post-roadmap capabilities

Scores: value and fit 5=best; effort, API cost and privacy/security risk 1=lowest/best.

| Rank | Capability | Value | Effort | API cost | Risk | Fit | Recommendation |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | Current-contract/scopes/account-ID migration | 5 | 3 | 1 | 2 | 5 | Required foundation before new product promises. |
| 2 | Snapshot-aware Drift and unchanged fast path | 5 | 3 | 1 | 2 | 5 | Best Mirror correctness and cost improvement. |
| 3 | Read-only live QA | 4 | 2 | 2 | 2 | 5 | Immediate confidence; reuse Transfer reports. |
| 4 | Exact playlist backup + restore Preview | 5 | 4 | 4 | 3 | 5 | Store privately; ship read/Preview before mutation. |
| 5 | Approval-gated checkpointed restore | 5 | 4 | 4 | 5 | 5 | High value/risk; depends on ranks 1, 2 and 4. |
| 6 | Minimal reorder/Correction planner | 4 | 4 | 2–5 | 4 | 4 | Prefer ranges; approved replace fallback; protect duplicates. |
| 7 | ISRC-assisted validation/matching | 4 | 3 | 3 | 2 | 4 | Secondary evidence, never sole identity. |
| 8 | Playlist metadata reconciliation | 3 | 2 | 1 | 4 | 4 | Opt-in per field; never silently overwrite user edits. |
| 9 | Cover backup/upload | 2 | 3 | 2 | 4 | 2 | Defer: more scope, branding rules, expiring URLs/custom throttle. |
| 10 | Official Beatport API adapter | 4 | 5 | unknown | 4 | 4 | Blocked on written approval and accessible official contract. |

## 8. Proposed issue sequence

1. **Spotify current-contract audit and adapter migration.** Acceptance: pinned client maps create/read/add/remove/update to current `/me` and `/items`; legacy response shapes fail contract tests; no live test. Dependencies: none.
2. **OAuth least-privilege migration.** Acceptance: private reads work with `playlist-read-private`; re-consent explicit; collaborative/image/library/playback scopes absent unless enabled. Dependencies: 1.
3. **Stable account identity migration.** Acceptance: new state uses `account_id`; old `id`-keyed manifests/transfers/locks migrate and remain resumable; identifiers never appear in logs/reports. Dependencies: 1–2.
4. **Typed playlist head/items reader.** Acceptance: pagination, `item`/legacy migration compatibility, null items, episodes, local items, duplicates, restrictions and order have synthetic tests; fields minimized. Dependencies: 1–2.
5. **Snapshot-aware Drift service in Transfer.** Acceptance: unchanged snapshot avoids item reads; changed snapshot yields a read-only classified diff; restore/revoke stays a Transfer-owned choice. Dependencies: 3–4.
6. **Live QA command/web view.** Acceptance: zero mutations; reports snapshot/count/order/null/unavailable/relinked/marker/account mismatches with redacted output and cost estimate. Dependencies: 4–5.
7. **Private playlist backup schema and Preview.** Acceptance: versioned storage preserves ordered duplicates/minimal metadata; ADR-0001 applies; restore Preview reports operations/cost with zero mutations. Dependencies: 3–4.
8. **Checkpointed, Approval-gated restore.** Acceptance: confirmation immediately precedes replace; head mismatch aborts; first 100 replace then ordered chunks; snapshots/chunks checkpoint for idempotent resume; partial failure reported. Dependencies: 5, 7.
9. **Minimal reorder/remove planner.** Acceptance: range moves use snapshot preconditions; duplicate cases do not rely on undocumented position removal; ambiguous plans fall back to confirmed full replace; Transfer owns policy. Dependencies: 5, 8.
10. **ISRC and market-aware Correction validation.** Acceptance: ISRC secondary evidence; playability/restriction/relinking shown; relink never silently changes Approved Match identity. Dependencies: 4.
11. **Opt-in metadata reconciliation.** Acceptance: Preview per changed field; privacy/collaboration changes require confirmation; permission failures non-destructive. Dependencies: 5.
12. **Beatport official-access decision.** Acceptance: record approval/license status and accessible official endpoint contract, or explicitly retain scraper as unsupported/inferred with breakage telemetry; no reverse-engineered endpoint list. Dependencies: external approval.

## Confirmation and mutation boundaries

Every Spotify `POST`, `PUT`, or `DELETE` is a user-account mutation. Creating a Provisional Playlist; adding, replacing, removing or reordering its items; changing metadata/privacy/collaboration; uploading a cover; saving/removing library items; restore; Drift restoration; orphan removal; and Correction application require an explicit user-approved action. Destructive or broad Batch actions require final confirmation after a fresh head check. Preview, Drift analysis, backup, live QA, track validation and snapshot probes are read-only but expose personal playlist data, so they still require least-privilege scopes, redacted logs, private storage and bounded retention. Approval remains the only path by which Corrections or surviving proposals become authoritative matching knowledge.

Adapters should return typed facts such as `PlaylistHead`, ordered items, mutation result snapshot and permission/capability errors. `Transfer` must continue to own Preview suppression, confirmation, Approval/Correction meaning, Drift choices, Orphaned Mirror disposition, Batch cost policy, checkpoints and recovery. This preserves the established deep seam ([protocol](../../djsupport/transfer.py#L458), [orchestrator](../../djsupport/transfer.py#L1119)).

## Official sources

- Spotify: [February 2026 changelog](https://developer.spotify.com/documentation/web-api/references/changes/february-2026), [migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide), [March 2026 field restoration](https://developer.spotify.com/documentation/web-api/references/changes/march-2026), [May 2026 account ID](https://developer.spotify.com/documentation/web-api/references/changes/may-2026), [July 2026 quota update](https://developer.spotify.com/blog/2026-07-23-web-api-quota-updates), [playlist concepts/snapshots](https://developer.spotify.com/documentation/web-api/concepts/playlists), [rate limits](https://developer.spotify.com/documentation/web-api/concepts/rate-limits), [track relinking](https://developer.spotify.com/documentation/web-api/concepts/track-relinking), [current-user profile](https://developer.spotify.com/documentation/web-api/reference/get-current-users-profile), [current-user playlists](https://developer.spotify.com/documentation/web-api/reference/get-a-list-of-current-users-playlists), [create playlist](https://developer.spotify.com/documentation/web-api/reference/create-playlist), [playlist items](https://developer.spotify.com/documentation/web-api/reference/get-playlists-items), [add items](https://developer.spotify.com/documentation/web-api/reference/add-items-to-playlist), [remove items](https://developer.spotify.com/documentation/web-api/reference/remove-items-playlist), [replace/reorder](https://developer.spotify.com/documentation/web-api/reference/reorder-or-replace-playlists-items), [remove library items](https://developer.spotify.com/documentation/web-api/reference/remove-library-items), [change details](https://developer.spotify.com/documentation/web-api/reference/change-playlist-details), [November 2024 changes](https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api), [February 2026 access update](https://developer.spotify.com/blog/2026-02-06-update-on-developer-access-and-platform-security), and [quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes).
- Beatport: [official API terms](https://support.beatport.com/hc/en-us/articles/4414997837716-Terms-and-Conditions) and [login-gated developer portal](https://api.beatport.com/v4/docs/v4/catalog/search/).
- rekordbox: [developer/XML guidance](https://rekordbox.com/en/support/developer/), [official XML format list](https://cdn.rekordbox.com/files/20200410160904/xml_format_list.pdf), and [current instruction manual](https://cdn.rekordbox.com/files/20251202174516/rekordbox7.2.8_manual_EN.pdf).
