# Third-party Spotify Playlist Watchlist feasibility

**Date:** 2026-08-01

**Status:** Read-only research; no Spotify calls were made.

**Question:** Can DJ Support monitor roughly 50 playlists curated by other
people, detect newly added tracks, and surface those tracks in a private
Discovery Feed without mutating Spotify?

## Decision summary

Not with DJ Support's realistic Spotify access today. Under the current
Development Mode contract, DJ Support may discover a followed playlist and
observe playlist-level metadata such as `snapshot_id`, but it cannot read the
items of a playlist unless the authenticated user owns or collaborates on it.
That blocks the core promise: identifying which tracks were newly added to
third-party playlists.

Treat **Playlist Watchlist** as **fog**, represented by one bounded Wayfinder
research/prototype ticket rather than next-release scope. A useful thin
experiment could watch known playlist URLs for a changed `snapshot_id` and
offer **Open in Spotify**. It must not claim to produce a new-track feed. The
full feed becomes feasible only if Spotify restores suitable Development Mode
access, DJ Support later qualifies for Extended Quota, or the user deliberately
copies/shares tracks into an owned intake source.

## Confirmed facts

- In Development Mode, `GET /playlists/{id}/items` is limited to playlists the
  authenticated user owns or collaborates on; other playlists return `403`.
  This is the direct blocker for finding additions in third-party playlists
  ([February 2026 migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide),
  [Get Playlist Items](https://developer.spotify.com/documentation/web-api/reference/get-playlists-items)).
- `GET /me/playlists` enumerates playlists the user owns or follows. It is
  paginated with a maximum page size of 50 and returns simplified playlist
  facts including `snapshot_id` and item count. Private playlist discovery uses
  `playlist-read-private`; the arbitrary-user playlist endpoint was removed
  from Development Mode in February 2026
  ([current-user playlists](https://developer.spotify.com/documentation/web-api/reference/get-a-list-of-current-users-playlists),
  [February 2026 changes](https://developer.spotify.com/documentation/web-api/references/changes/february-2026)).
- `GET /playlists/{id}` still exposes playlist-level metadata including
  `snapshot_id`, but its item content is available only for owned or
  collaborative playlists. Consequently, a known public playlist can provide
  a change signal without revealing the changed tracks
  ([Get Playlist](https://developer.spotify.com/documentation/web-api/reference/get-playlist)).
- Spotify now represents saving/following playlists through generic library
  endpoints. Saving or checking playlist URIs supports up to 40 items per
  request, while enumeration remains `GET /me/playlists`
  ([Save Library Items](https://developer.spotify.com/documentation/web-api/reference/save-library-items),
  [Check Library Items](https://developer.spotify.com/documentation/web-api/reference/check-library-contains)).
- Development Mode requires a Premium app owner and supports at most five
  allowlisted users. Extended Quota has higher rate limits and unlimited users
  ([quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)).
- Rate limiting uses an unpublished, mode-dependent rolling 30-second window.
  Clients must honor `429` and `Retry-After`; Spotify recommends caching
  `snapshot_id` to avoid unnecessary item downloads
  ([rate limits](https://developer.spotify.com/documentation/web-api/concepts/rate-limits)).
- Spotify's Developer Terms prohibit robots, spiders, and retrieval tools used
  to retrieve, duplicate, or index Spotify service content, explicitly
  including playlist data. A browser extension or server-side scraper is not a
  safe workaround. Displayed Spotify metadata also carries attribution,
  link-back, privacy, and security obligations; Spotify content may not be
  ingested into an AI/ML model
  ([Developer Terms](https://developer.spotify.com/terms),
  [Developer Policy](https://developer.spotify.com/policy)).

## Conditional cases

- Spotify says Extended Quota integrations are unaffected by the February 2026
  restrictions, so third-party public playlist-item reads should remain
  available there. Access is not a viable planning assumption for a personal
  tool: applications are organization-only and require an established legal
  entity, a launched service, at least 250,000 monthly active users, broad
  market availability, commercial viability, and Spotify review
  ([migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide),
  [quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)).
- A Development Mode **change alert** appears technically possible: the user
  supplies or follows a playlist, DJ Support periodically compares its cached
  `snapshot_id`, then offers to open changed playlists in Spotify. Before this
  becomes a promise, a synthetic read-only contract test should confirm that
  arbitrary public playlist metadata is consistently accessible.
- A true item feed is possible when the source playlist is owned or
  collaborative. One lawful habit is to share or copy candidate tracks into an
  owned intake playlist, which DJ Support can then read. This changes the
  workflow from passive monitoring to explicit capture.
- Equivalent discovery may come from curators, labels, or providers offering an
  official API, RSS feed, notification, or licensed export. That is a separate
  provider-by-provider research branch, not a Spotify workaround.

## Unknowns

- Spotify publishes no numerical safe polling interval and no webhook or push
  contract for playlist changes was found. A polling design therefore needs a
  bounded request budget, backoff, caching, and explicit validation.
- The documentation does not guarantee that every arbitrary public playlist's
  metadata will remain readable in Development Mode. Do not infer product
  coverage until tested without user-derived evidence.
- User-supplied playlist URLs solve selection and identity, not item access.
  Export or notification workflows depend on what the curator or another
  provider officially offers.

## Fit with DJ Support

The existing [playlist-management API review](2026-08-01-playlist-management-api-review.md)
already records the owner/collaborator item-read boundary, pooled quotas,
snapshot caching, and the need to migrate DJ Support's adapter and scopes. The
current adapter requests only modification scopes and has no third-party
playlist reader ([Spotify adapter](../../djsupport/spotify.py)). Any future
watcher should return read-only discovery facts to a Discovery Feed; it is not
a Mirror, Snapshot, Transfer, Approval, or Spotify publication action.

## Recommended Wayfinder ticket

**Research/prototype: validate a read-only Spotify playlist change alert.**

Answer only whether Development Mode can reliably read `snapshot_id` for a
small synthetic set of non-owned public playlist URLs, what request budget is
safe, and whether “this playlist changed—open it” is useful enough without
track-level additions. Keep the richer third-party new-track feed in fog until
the access condition changes. Do not scrape Spotify and do not place this in
the next release's committed scope.

## Next user question

If DJ Support could only tell you **which watched playlists changed** and open
them in Spotify—not show the new tracks—would that still save you enough time
to be worth building?
