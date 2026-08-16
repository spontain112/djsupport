# Use one local transactional Operational Store

DJ Support will replace its three authoritative JSON stores with one local
SQLite Operational Store behind one deep internal interface, with SQLite and
in-memory adapters. This concentrates transactions, optimistic revisions,
schema migration, integrity checks, recovery, the Effect Journal, and derived
local diagnostics while Transfer remains the sole policy authority;
configuration and Spotipy-managed credentials remain outside the store.

Before verified activation, JSON is the sole production authority. Activation
atomically replaces one small selector after all clients quiesce; the selector
names a stable generation identity, while the selected generation remains
mutable operational state. After activation, SQLite is the sole production
authority. Runtime dual-write, partial-client cutover, and silent JSON fallback
are rejected. Retained JSON is inert, read-only input to explicit migration or
rollback workflows.

Migration is backup-first and Preview-first. Active SQLite backups use the
binding's SQLite Online Backup API into a fresh closed and verified destination;
a live database/WAL/SHM family is never copied or archived as a backup. Database
transactions never span Spotify calls: the Effect Journal retains intent before
the bounded effect and its observed result afterward so resume can reconcile
rather than infer or repeat authority.

Operational Events are compact, private, and append-only during ordinary
recording. They and their rebuildable projections are never authority-bearing
inputs, and explicit analytics-history deletion cannot alter authority-bearing
state. Concurrent WAL authority fails closed unless the exact selected Python
binding artifact and SQLite runtime pass the maintained qualification policy;
withdrawn, affected, revoked, and unknown builds are unavailable.

APSW 3.53.4.0 is the sole production SQLite Python binding, remains private to
the Operational Store adapter, and is used without an ORM. Python's standard
`sqlite3` never opens the production Operational Store. The accepted decision
is recorded in
[issue #165](https://github.com/spontain112/djsupport/issues/165); #166 owns the
versioned fail-closed runtime qualification and revocation policy, while #167
owns pinned artifact delivery, native platform evidence, dependency provenance,
open-source credits and notices, and update or withdrawal monitoring. Only
Python 3.10–3.14 installations on macOS, Linux, and Windows whose exact
OS/architecture/artifact combinations are proved by #167 are supported. There
is no dual-binding, rollback-journal, checkpoint-scheduling bypass,
user-configurable override, warning-only path, or JSON fallback.
Application-level encryption is deferred in favor of operating-system account
and disk protections. The 0.7 release line retains verified rollback through a
documented window and never silently deletes legacy state.

The maintained implementation contracts are the
[APSW integration research](../research/2026-08-16-apsw-operational-store-integration-contract.md),
the
[concurrency and durability research](../research/2026-08-16-sqlite-concurrency-durability-contract.md)
and the
[migration, backup, and cutover research](../research/2026-08-16-sqlite-migration-backup-cutover-contract.md).
