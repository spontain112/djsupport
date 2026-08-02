# DJ Support 0.5.0 — Trustworthy Spotify Foundation

DJ Support 0.5.0 updates the Spotify boundary while keeping `Transfer` as the
sole publication and Approval authority.

Spotify sign-in now asks for `playlist-read-private` alongside the existing
public/private playlist modification permissions. This is required to inspect
private Provisional Playlists; DJ Support does not request collaborative,
library, playback, image, or other permissions.

Approval reads a playlist head, every ordered item page, and the head again. A
changed head stops Approval without retaining Approved Matches. Ordered facts
preserve duplicate occurrences and classify null, local, episode, unsupported,
restricted, unavailable, and relinked shapes rather than silently dropping
them.

Publication replaces the first 100 items and adds later chunks in order. Every
returned mutation snapshot and completed chunk identity is retained before the
next operation, and an unexpected head pauses the Transfer. Spotify provides no
atomic multi-chunk mutation, so an external edit can still occur between a
fresh head check and the following write; 0.5.0 does not claim otherwise.

A recovery marker exists only during the narrow playlist-create checkpoint.
After the Spotify playlist ID is durable, the marker is replaced by clean
provisional copy. Approval applies durable Snapshot or managed Mirror copy.
Beatport chart title, curator, and source URL survive Preview, resume,
publication, and Approval.

Private publication data now writes schema 5 and durable Transfer data writes
schema 2. Older supported schemas remain readable and backup-compatible. Back
up local data before the first publication after upgrading.

The default test suite is offline and synthetic. The separately gated live
Spotify smoke test still requires explicit authorization, an allowlisted owner
account, a disposable private playlist, and a fixed request budget; it is not
run automatically.
