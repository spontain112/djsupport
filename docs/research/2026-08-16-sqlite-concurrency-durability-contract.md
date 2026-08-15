# SQLite concurrency and durability contract for the Operational Store

**Date:** 2026-08-16

**Code baseline:** `main` at `6b04a70eb65681b97b104de8cc1eac6cef49713b`

**Status:** Read-only research for issues
[#138](https://github.com/spontain112/djsupport/issues/138)–[#143](https://github.com/spontain112/djsupport/issues/143). No production authority switch, owner-data access, or live Spotify/Beatport call was performed.

**Authority:** DJ Support repository requirements plus official SQLite and Python
standard-library documentation only. Each section separates sourced behavior from
the implementation and test implications inferred for DJ Support.

## Executive decision

DJ Support should use one local SQLite database, one connection per unit of work,
and explicit SQL transaction control that behaves the same on Python 3.10 through
3.14. Every connection should use a five-second busy timeout, `foreign_keys=ON`,
`synchronous=FULL`, and verified WAL mode. Writes should start with
`BEGIN IMMEDIATE`, contain only local database work, and commit or roll back before
any Spotify call. Entity writes should use revision-qualified `UPDATE` statements
and require exactly one affected row. Backups should use `Connection.backup()`, not
filesystem copies of the database or its sidecars.

There is one non-negotiable runtime gate. SQLite disclosed a rare WAL-reset race in
March 2026 affecting concurrent WAL connections through 3.51.2; upstream fixes are
3.51.3 and the 3.44.6/3.50.7 backports. The Python runtime used for this research
reports SQLite 3.43.1, which falls in the affected range. Issue #138 can build and
conformance-test a non-authoritative adapter, but #139 must not claim safe
concurrent production authority until the linked SQLite library is proven to carry
an upstream or downstream fix. SQLite itself says applications should upgrade.
([SQLite WAL-reset bug](https://sqlite.org/wal.html#the_wal_reset_bug),
[Python runtime version API](https://docs.python.org/3.10/library/sqlite3.html#sqlite3.sqlite_version))

## 1. Project requirements that constrain the database

The program decision is one SQLite Operational Store behind one internal interface,
shared by local CLI, web, and Agent Clients. Configuration and Spotipy credentials
stay outside it; external-effect intent and observations go in an Effect Journal;
Operational Events are private, compact, and non-authoritative; migration is
backup-first and Preview-first; production must not dual-write JSON and SQLite.
([program #125](https://github.com/spontain112/djsupport/issues/125),
[implementation map #128](https://github.com/spontain112/djsupport/issues/128))

The existing file model already distinguishes matching knowledge, publication
state, Transfer state, configuration, and credentials, and explicitly notes that
atomic replacement of one JSON file cannot make several files one transaction.
The Operational Store therefore earns its value only if one transaction can cover
the whole local authority change without moving policy out of `Transfer`.
([private-storage model](../storage.md#write-and-concurrency-behavior),
[architecture](../architecture.md#interfaces-and-adapters))

| Ticket | Database implication |
| --- | --- |
| [#138](https://github.com/spontain112/djsupport/issues/138) | Define one `OperationalStore` contract and a transaction/unit-of-work boundary. Make in-memory and SQLite adapters pass the same behavior tests. Preserve occurrence identity, explicit order, duplicates, proposals, failures, checkpoints, and events. Keep JSON as production authority in this ticket. |
| [#139](https://github.com/spontain112/djsupport/issues/139) | Qualify a patched SQLite runtime, then prove two independent connections/processes, bounded contention, optimistic revision conflicts, integrity checks, and crash atomicity. |
| [#140](https://github.com/spontain112/djsupport/issues/140) | Commit effect intent, close the transaction, call Spotify, then commit the observation. An intent without a conclusive observation is uncertain and must be reconciled, never silently replayed. |
| [#141](https://github.com/spontain112/djsupport/issues/141) | Check playlist/manifest heads and write Approval, publication state, matching authority, Corrections, conflicts, and the compact event in one local transaction. |
| [#142](https://github.com/spontain112/djsupport/issues/142) | Give each draft an optimistic revision. Discard plus successor creation is one transaction. Retain digests and account-scoped Local Audio Identity, never paths, filenames, or process handles. |
| [#143](https://github.com/spontain112/djsupport/issues/143) | Revision Mirror state and journal every Spotify effect. Orphan, Drift, relink, replacement, and removal remain explicit states/actions; absence never becomes deletion authority. |

## 2. WAL is a concurrency mode, not multi-writer execution

### Sourced facts

- WAL lets readers and a writer proceed concurrently, but there is still exactly
  one writer at a time. A reader sees a stable end mark for its transaction. WAL
  uses same-machine shared memory and is not suitable for clients on different
  hosts through a network filesystem.
  ([WAL concurrency](https://sqlite.org/wal.html#concurrency))
- `PRAGMA journal_mode=WAL` returns the resulting mode; success is the literal
  `wal`. WAL mode persists across connection closes and applies to every
  connection to that database.
  ([activating WAL](https://sqlite.org/wal.html#activating_and_configuring_wal_mode),
  [WAL persistence](https://sqlite.org/wal.html#persistence_of_wal_mode))
- A commit is represented by a commit record appended to the WAL. Checkpointing
  later transfers WAL pages into the main database. SQLite normally
  autocheckpoints at 1,000 pages. A long read transaction can prevent checkpoint
  completion and allow the WAL to grow.
  ([how WAL works](https://sqlite.org/wal.html#how_wal_works),
  [checkpoint behavior](https://sqlite.org/wal.html#checkpointing),
  [large-WAL causes](https://sqlite.org/wal.html#avoiding_excessively_large_wal_files))
- The `-wal` file is persistent database state when present; separating it from
  the main file can lose committed transactions or corrupt the database. The
  `-shm` file is the shared-memory index and may also remain after an unclean
  shutdown.
  ([WAL file lifecycle](https://sqlite.org/wal.html#the_wal_file),
  [WAL-mode files](https://sqlite.org/walformat.html#files_on_disk))

### Implementation implications (inference)

1. Put the database only in DJ Support's local application-data directory. Refuse
   an explicitly detected network filesystem rather than implying that cloud- or
   network-shared storage is supported.
2. Bootstrap a new database while no other DJ Support connection is active, run
   `PRAGMA journal_mode=WAL`, and require the returned value to be `wal`. Normal
   connections should query and verify the mode instead of silently accepting a
   fallback.
3. Leave the 1,000-page autocheckpoint enabled explicitly at first. Do not launch
   competing ad-hoc checkpoint workers. Keep read transactions short, consume or
   close cursors promptly, and expose WAL growth as a redacted diagnostic.
4. Treat `operational-store.sqlite3`, `operational-store.sqlite3-wal`, and
   `operational-store.sqlite3-shm` as one private state family for documentation,
   ignore rules, repository tests, packaging tests, backup staging, and support
   diagnostics. Never delete a sidecar to “repair” a database.

### Required tests

- New database, clean reopen, and crash reopen all report `journal_mode=wal`.
- Two independent connections can hold reads while a third commits distinct work.
- A deliberately held read snapshot remains stable until its transaction ends,
  then a new read sees the committed change.
- A held reader plus enough synthetic writes demonstrates that a checkpoint may be
  incomplete without treating this as corruption; ending the reader permits a
  later checkpoint to progress.
- Repository and wheel tests reject the database, `-wal`, `-shm`, copied snapshots,
  backup files, migration staging files, query exports, diagnostics, and reports.

## 3. Mandatory WAL runtime qualification

### Sourced fact

SQLite's current WAL documentation says the WAL-reset race is likely present from
3.7.0 through 3.51.2 and is fixed in 3.51.3. Upstream also published backports in
3.44.6 and 3.50.7. It requires at least two connections in different threads or
processes and a tightly timed write/checkpoint race, but can corrupt the database;
SQLite recommends upgrading.
([official WAL-reset advisory](https://sqlite.org/wal.html#the_wal_reset_bug))

Python exposes the runtime SQLite library separately from the Python module
version through `sqlite3.sqlite_version` and `sqlite3.sqlite_version_info`.
([Python 3.10 `sqlite3`](https://docs.python.org/3.10/library/sqlite3.html#sqlite3.sqlite_version))

### Implementation implication (inference)

Before #139 enables concurrent authority, the store should fail closed unless its
runtime is one of:

- SQLite 3.51.3 or later;
- the 3.50 line at 3.50.7 or later;
- the 3.44 line at 3.44.6 or later; or
- a downstream build whose maintainer explicitly documents the same fix, recorded
  in DJ Support's release qualification.

A simple `version >= 3.44.6` comparison is unsafe because upstream identifies the
intervening 3.45–3.49 lines and 3.51.0–3.51.2 as affected. The capability error
must report the runtime version without printing a database path. #138 may run its
single-process, non-authoritative conformance work on older versions, but the
multi-client capability must remain disabled.

### Required tests

- Unit-test the allow/deny matrix around 3.44.5/3.44.6, 3.45.x, 3.50.6/3.50.7,
  and 3.51.2/3.51.3.
- Record `sys.version` and `sqlite3.sqlite_version` as non-private CI metadata on
  macOS, Linux, and Windows, including the Python 3.10 and 3.14 Linux edges.
- Make the concurrent-persistence suite fail, not skip, if the release runtime is
  not proven patched. A downstream-backport exception requires explicit build
  evidence rather than a user toggle.

## 4. Cross-version Python connection contract

### Sourced facts

Python 3.10 opens implicit transactions unless `isolation_level=None`; that value
leaves SQLite in its native autocommit mode and permits explicit SQL transaction
control. `connect(timeout=...)` bounds the wait for a lock and defaults to five
seconds. A connection defaults to `check_same_thread=True`; using it from another
thread raises `ProgrammingError`, while disabling the check requires the caller to
serialize writes. `executescript()` implicitly commits a pending transaction.
([Python 3.10 connection and transaction control](https://docs.python.org/3.10/library/sqlite3.html#transaction-control))

Python 3.12 added the `autocommit` argument, and Python 3.14 still defaults it to
`LEGACY_TRANSACTION_CONTROL` while warning that the default will change. Code that
depends on that newer argument cannot run on Python 3.10.
([Python 3.14 transaction control](https://docs.python.org/3.14/library/sqlite3.html#transaction-control))

SQLite warns not to inherit an open database connection across `fork()`; the child
must open its own connection. Python's default thread check likewise favors
connection ownership by one thread.
([SQLite fork warning](https://sqlite.org/howtocorrupt.html#_carrying_an_open_database_connection_across_a_fork_),
[Python `check_same_thread`](https://docs.python.org/3.10/library/sqlite3.html#sqlite3.connect))

### Implementation implication (inference)

Use a connection factory, not one Runtime Assembly-owned connection:

```python
sqlite3.connect(
    database_path,
    timeout=5.0,
    isolation_level=None,
    check_same_thread=True,
)
```

Then configure and verify on **every** connection:

```sql
PRAGMA foreign_keys = ON;
PRAGMA synchronous = FULL;
PRAGMA wal_autocheckpoint = 1000;
```

Query and require `foreign_keys=1`, `synchronous=2`,
`wal_autocheckpoint=1000`, `busy_timeout=5000`, and `journal_mode=wal`. PRAGMAs
can be misspelled without an error, so setting without reading back is inadequate.
([PRAGMA behavior](https://sqlite.org/pragma.html#pragma_command_syntax))

Open a connection inside the thread/process that performs the unit of work and
close it at the boundary. Never pass it to another thread, cache it across a fork,
or expose it through the `OperationalStore` interface. This permits CLI, web, and
Agent Clients to share the database through SQLite's file locking without sharing
Python connection objects.

Do not pass the Python 3.12-only `autocommit` keyword while Python 3.10 remains
supported. Do not use `executescript()` inside migration transaction helpers;
execute the registered statements individually so Python cannot introduce an
implicit commit.

### Required tests

- The same connection-factory assertions run on Python 3.10 and 3.14.
- A connection used by a different thread fails in the test harness; production
  code creates a fresh connection in that thread instead.
- A subprocess opens its own connection after process creation. No fixture opens a
  parent connection and then forks.
- Every public store operation leaves `connection.in_transaction` false on success
  and on each injected exception.

## 5. Transaction modes and exact boundaries

### Sourced facts

SQLite permits many simultaneous read transactions but only one write transaction.
`BEGIN DEFERRED` does not acquire the write transaction until needed; upgrading an
older read snapshot can fail with `SQLITE_BUSY_SNAPSHOT`. `BEGIN IMMEDIATE` starts
the write transaction at once. If it succeeds, SQLite guarantees that later work
through the next commit will not fail with `SQLITE_BUSY`.
([transactions](https://sqlite.org/lang_transaction.html#deferred_immediate_and_exclusive_transactions),
[snapshot isolation](https://sqlite.org/isolation.html#isolation_and_concurrency),
[busy result](https://sqlite.org/rescode.html#busy))

In WAL mode, `BEGIN EXCLUSIVE` and `BEGIN IMMEDIATE` have the same locking effect.
Transactions created by `BEGIN` do not nest; savepoints provide nesting, but an
inner `RELEASE` is not durable until the outer transaction commits.
([transaction modes](https://sqlite.org/lang_transaction.html#deferred_immediate_and_exclusive_transactions),
[savepoints](https://sqlite.org/lang_savepoint.html))

### Implementation implication (inference)

Provide one store-owned transaction helper with this semantic shape:

```python
connection.execute("BEGIN IMMEDIATE")
try:
    # Pure SQLite reads, validation, and writes only.
    ...
    connection.execute("COMMIT")
except BaseException:
    if connection.in_transaction:
        connection.execute("ROLLBACK")
    raise
```

- Use autocommit for a single fully consumed `SELECT`.
- Use a short explicit `BEGIN` only when several reads must share one snapshot.
- Use `BEGIN IMMEDIATE` for every read-then-write authority operation, including
  migration, revision comparison, Approval, draft supersession, and Mirror change.
- Do not use `BEGIN EXCLUSIVE`; it adds no WAL benefit and communicates the wrong
  intent.
- Let the outer Operational Store unit of work own commit. Repository helpers may
  use savepoints only for local composition and must never imply that `RELEASE`
  made an external effect safe.
- Perform parsing, hashing, Spotify request construction, and other expensive pure
  computation before `BEGIN IMMEDIATE`; revalidate revision/head facts after the
  transaction starts.

### Issue-specific boundaries

Any Spotify read needed to form a playlist head, ordered review, or reconciliation
observation happens before Transaction A. The transaction then binds that exact
observed fact to the current local manifest/revision; it never performs the remote
read while holding the writer transaction.

| Operation | Transaction A | Outside any transaction | Transaction B |
| --- | --- | --- | --- |
| Preview/resume (#138) | Retain the complete local checkpoint, proposals/failures, and event | Nothing authority-bearing | Not needed |
| Snapshot publication (#140) | Insert immutable manifest/items plus effect intent | One bounded Spotify call | Retain observed response or conclusive failure and advance state |
| Approval (#141) | Compare exact heads/revisions and commit all Approval, publication, matching, Correction, conflict, and event changes together | Nothing | Not needed |
| Draft apply (#142) | Retain draft-application effect intent | One bounded Spotify call | Retain observation; playlist-scoped Approval remains a later act |
| Mirror replace/relink/remove (#143) | Retain expected Mirror revision and effect intent | One bounded Spotify call | Retain observation and advance/reconcile Mirror state |

No connection, cursor, generator-backed query result, or transaction context may
cross the Spotify adapter call.

## 6. Bounded busy handling and retry semantics

### Sourced facts

SQLite's busy timeout sleeps repeatedly until the configured accumulated duration,
then returns `SQLITE_BUSY`; each connection has only one busy handler. Python's
`timeout` parameter exposes this behavior and raises `OperationalError` after the
bound. SQLite distinguishes cross-connection `SQLITE_BUSY` from same-connection or
shared-cache `SQLITE_LOCKED`.
([SQLite busy timeout](https://sqlite.org/c3ref/busy_timeout.html),
[SQLite result codes](https://sqlite.org/rescode.html#busy),
[Python connection timeout](https://docs.python.org/3.10/library/sqlite3.html#sqlite3.connect))

### Implementation implication (inference)

- Production lock wait: five seconds, set once through `connect(timeout=5.0)` and
  verified via `PRAGMA busy_timeout`. Do not replace the handler later.
- Start writes with `BEGIN IMMEDIATE`. If it times out, roll back if necessary and
  return a typed, privacy-redacted `StoreBusy`/“retry later” outcome.
- Do not hide a second retry loop inside the adapter. A later user/client retry
  opens a fresh connection and fresh transaction. This makes the total wait
  bounded and prevents stale in-memory facts from surviving a retry.
- A revision conflict is not lock contention and must never be retried as busy; it
  returns reload-before-retry immediately.
- Recovery-opening `SQLITE_BUSY` is also bounded. Never delete `-wal`/`-shm` to
  force progress.

### Required tests

Inject a shorter test-only timeout (for example 50 ms), hold `BEGIN IMMEDIATE` on
connection A, and have independent connection B attempt the same. Coordinate with
process/thread events rather than sleeps. Assert B returns the typed busy outcome
within a generous finite ceiling, changes nothing, and succeeds with a fresh read
and transaction after A commits. Separately prove two connections can update
different entities sequentially without lost updates.

## 7. Optimistic revisions must be compare-and-swap writes

### Sourced facts

An SQLite `UPDATE` with a `WHERE` predicate affects only matching rows, and zero
matches is not itself a SQL error. Python `Cursor.rowcount` reports the number of
rows modified by `INSERT`, `UPDATE`, `DELETE`, and `REPLACE`.
([SQLite `UPDATE`](https://sqlite.org/lang_update.html),
[Python `rowcount`](https://docs.python.org/3.10/library/sqlite3.html#sqlite3.Cursor.rowcount))

### Implementation implication (inference)

Every mutable authority-bearing aggregate gets one integer revision. Preserve the
current file-adapter convention: a new caller state starts at revision 0, initial
retention creates revision 1, and each successful save increments by one.

```sql
UPDATE transfers
   SET state_json = ?, revision = revision + 1
 WHERE transfer_id = ? AND revision = ?;
```

Require `cursor.rowcount == 1`. A zero count means absent or stale and maps to one
fail-closed reload-before-retry outcome; more than one is an invariant failure.
Return a newly materialized revision after commit instead of mutating the caller's
object before durability is known.

- Transfers, Batches, matching-knowledge entities, Publication Manifests,
  Qualification Drafts, and Mirrors need revision scopes that match their
  independent user decisions.
- Inserts use unique stable identities. A duplicate insert is a conflict, not an
  update.
- Approval and draft supersession execute all required compare-and-swap statements
  inside one `BEGIN IMMEDIATE`; if any row count is not one, roll back every row.
- Never use unconditional `UPDATE`, last-write-wins `UPSERT`, or
  `INSERT OR REPLACE` for authority state.

### Required tests

- Two independently loaded copies at revision *n*: the first saves and returns
  *n+1*; the second fails closed and leaves the first result byte-for-byte
  equivalent at the domain projection level.
- Run that test for Transfer, Batch, one matching-knowledge entity, manifest/draft,
  and Mirror, not only one representative table.
- Inject failure after each statement in Approval and draft supersession; no table
  may retain a partial update and no input object's revision may change.
- The in-memory adapter must implement the same compare-and-swap semantics rather
  than serving as a permissive fake.

## 8. Relational constraints and ordered duplicates

### Sourced facts

SQLite foreign-key enforcement is disabled by default and must be enabled per
connection outside any active transaction. `PRAGMA foreign_key_check` returns one
row per violation. Parent keys must be primary/unique keys; indexes on child keys
are strongly recommended to avoid linear scans.
([foreign-key PRAGMA](https://sqlite.org/pragma.html#pragma_foreign_keys),
[foreign-key indexes](https://sqlite.org/foreignkeys.html#fk_indexes),
[foreign-key check](https://sqlite.org/pragma.html#pragma_foreign_key_check))

SQLite does not guarantee row order without `ORDER BY`. It can even reverse many
unordered queries under `PRAGMA reverse_unordered_selects` to reveal invalid
assumptions. SQLite's legacy primary-key behavior can permit `NULL` unless the key
is an `INTEGER PRIMARY KEY`, `WITHOUT ROWID`, `STRICT`, or explicitly `NOT NULL`.
([unordered result warning](https://sqlite.org/pragma.html#pragma_reverse_unordered_selects),
[primary-key `NULL` behavior](https://sqlite.org/lang_createtable.html#the_primary_key))

### Implementation implication (inference)

- Declare stable text identifiers `NOT NULL` even when they participate in a
  primary key. Use explicit `CHECK` constraints for revision non-negativity,
  ordinals, and closed state vocabularies where compatible with migrations.
- Give each Source Occurrence its own identity and a selection-local ordinal.
  `UNIQUE(source_selection_id, ordinal)` protects order; **do not** make track URI,
  source key, or metadata unique, because duplicate occurrences are valid.
- Give Publication Items the equivalent `UNIQUE(manifest_id, ordinal)` contract.
- Every ordered read uses `ORDER BY ordinal, occurrence_id` (or the corresponding
  stable tie-breaker), never insertion order or rowid.
- Use foreign keys for ownership relationships and index every child-key column.
  Default authority relationships to `ON DELETE RESTRICT`/`NO ACTION`; do not let
  a cascade turn source absence or aggregate deletion into playlist authority.
- Keep all Operational Store tables in one database. WAL transactions across
  attached databases are atomic per database, not as a set.
  ([WAL attached-database limit](https://sqlite.org/wal.html#overview))

### Required tests

Round-trip repeated source facts at different occurrence identities and positions;
turn on `reverse_unordered_selects` in a test connection; assert the public result
remains exact. Attempt orphan rows, duplicate ordinals, null identities, invalid
states, and deletion of referenced authority; each must fail and roll back.

## 9. Integrity checks and fail-closed recovery

### Sourced facts

`PRAGMA integrity_check` verifies low-level formatting, pages, index entries,
freelist use, and `UNIQUE`, `CHECK`, and `NOT NULL` constraints. Success is one row
containing `ok`. It does **not** check foreign keys; that requires
`PRAGMA foreign_key_check`. `quick_check` is O(N) but skips unique and index/table
consistency checks that full `integrity_check` performs in O(N log N).
([integrity check](https://sqlite.org/pragma.html#pragma_integrity_check),
[quick check](https://sqlite.org/pragma.html#pragma_quick_check))

### Implementation implication (inference)

Use explicit check levels rather than claiming every successful query proves
integrity:

| Boundary | Required checks |
| --- | --- |
| Every connection | Verify connection PRAGMAs, application schema registry, and supported runtime; fail on any SQLite corruption/schema error. |
| First adapter bootstrap and crash-recovery tests | `quick_check` plus `foreign_key_check`; fail closed on any row other than `ok`/empty violations. |
| Before and after migration, import verification, cutover, backup, and restore | Full `integrity_check` plus `foreign_key_check`, followed by domain counts/digests and revision/state invariants. |
| Maintainer diagnostic | Full checks on explicit request, with paths and user facts redacted from output. |

Do not auto-run `REINDEX`, delete sidecars, drop rows, disable constraints, or select a
newer-looking record when a check fails. Preserve the files, return a redacted
repair/restore requirement, and require explicit recovery.

## 10. Crash atomicity and durability

### Sourced facts

SQLite's recovery guarantee is that a crash in a transaction rolls back partial
work on next access. In WAL mode, `synchronous=FULL` adds a WAL sync after every
transaction commit and is ACID; `NORMAL` remains consistent but can lose a recent
transaction after power or operating-system failure. SQLite recommends FULL for
maximum reliability.
([synchronous modes](https://sqlite.org/pragma.html#pragma_synchronous),
[corruption and crash recovery](https://sqlite.org/howtocorrupt.html#overview))

Python's progress handler can run every *n* SQLite virtual-machine instructions,
which provides a standard-library-only subprocess seam for terminating execution
inside `COMMIT`.
([Python progress handler](https://docs.python.org/3.10/library/sqlite3.html#sqlite3.Connection.set_progress_handler))

### Implementation implication (inference)

Use `synchronous=FULL` on every connection. A transaction's domain projection must
have exactly two valid crash outcomes: the complete previous state or the complete
next state. “Next state” includes its revision and Operational Event; an event or
revision without the corresponding aggregate is partial corruption at the
application level even if SQLite's pages are structurally valid.

### Deterministic crash suite

Run each case in a subprocess and reopen from a new process:

1. Exit before `BEGIN IMMEDIATE`: require previous state.
2. `os._exit()` after all DML but before `COMMIT`: require previous state.
3. Install a progress handler with interval 1 immediately before executing
   `COMMIT`, then `os._exit()` at successive callback ordinals. First prove the
   runtime invokes the handler during `COMMIT`; exercise every observed ordinal.
   Accept complete previous or complete next state, never a mixture.
4. Exit immediately after `COMMIT` returns: require complete next state.
5. Repeat with a constraint error and an injected Python exception: require
   previous state and `in_transaction == false` after handled rollback.

After every reopen, run full integrity and foreign-key checks and compare a
canonical domain digest. This proves application-process crash behavior across the
supported OS/Python matrix. It does not pretend to simulate lying storage hardware;
the power-loss durability claim comes from WAL plus FULL and still depends on the
operating system honoring sync requests.

## 11. Effect Journal: database atomicity stops at Spotify

### Sourced fact

SQLite transactions are atomic only for database work; they cannot make a remote
Spotify mutation part of the commit. The project explicitly requires intent before
the call, observation afterward, and no transaction across the network.
([transactions](https://sqlite.org/lang_transaction.html),
[#140](https://github.com/spontain112/djsupport/issues/140),
[#142](https://github.com/spontain112/djsupport/issues/142),
[#143](https://github.com/spontain112/djsupport/issues/143))

### Implementation implication (inference)

Each effect needs a stable local identity, aggregate identity/revision, operation
kind, canonical request digest, state, and redacted observation. The minimum state
machine is:

```text
prepared -> observed_complete
         -> observed_failed
         -> uncertain -> reconciled_complete | reconciled_not_applied | review_required
```

- Commit `prepared` with the exact Publication Manifest/items before Spotify.
- Make one bounded call with no database transaction open.
- Commit only facts actually observed afterward.
- `observed_failed` is reserved for a response that proves the mutation did not
  occur; a timeout or disconnect after dispatch is `uncertain`.
- A crash after dispatch but before observation is `uncertain`, not “not attempted.”
- Stable publication/effect identity enables reconciliation; it does not itself
  prove Spotify applied or did not apply the request.
- Automatic retry is allowed only when reconciliation proves the effect was not
  applied or the remote operation is independently proven idempotent. Otherwise
  require review.
- Preview never inserts an effect intent.

### Required tests

At the before-call, after-call, and before-observation-retention boundaries, crash a
worker using a synthetic Spotify adapter. Assert deterministic resume categories,
no duplicate Snapshot creation, and no inferred authority. For #141, inject failure
at every local Approval statement and prove the entire local transaction rolls
back. For #143, exercise replace, description, relink, and explicit removal as
separate journaled effects.

## 12. Backup, snapshot, and restore contract

### Sourced facts

Copying a live SQLite file can capture old and new pages and produce a corrupt
backup. If a WAL exists, copying or moving the main file without its matched WAL can
lose committed transactions or corrupt the result. SQLite's Online Backup API makes
a consistent snapshot while other clients use the source, and Python exposes it as
`Connection.backup()`.
([unsafe and safe backup methods](https://sqlite.org/howtocorrupt.html#_backup_or_restore_while_a_transaction_is_active),
[SQLite Online Backup API](https://sqlite.org/backup.html),
[Python backup API](https://docs.python.org/3.10/library/sqlite3.html#sqlite3.Connection.backup))

### Implementation implication (inference)

1. Open the source through the Operational Store connection factory.
2. Open a fresh private destination file and call `source.backup(destination)` with
   bounded busy handling.
3. Close/reopen the destination, run full integrity and foreign-key checks, verify
   schema registry plus domain counts/digests, then hash it into the backup manifest.
4. Never copy or zip a live `.sqlite3`, `-wal`, and `-shm` set. Never copy just the
   main file after a manual checkpoint and infer quiescence.
5. Restore only while DJ Support clients are quiescent under an explicit recovery
   gate. Validate the candidate first, preserve the current store as a verified
   backup, then switch the database family. Do not replace an open database file.

## 13. Explicit schema migration registry

### Sourced facts

SQLite reserves `PRAGMA user_version` as an application-controlled integer and does
not interpret it. Python 3.10's `executescript()` can implicitly commit a pending
transaction, so it is unsuitable inside an outer migration helper unless the script
fully owns transaction control.
([user version](https://sqlite.org/pragma.html#pragma_user_version),
[Python transaction control](https://docs.python.org/3.10/library/sqlite3.html#transaction-control))

### Implementation implication (inference)

Use an explicit table as the canonical registry rather than an integer alone:

```sql
CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY CHECK (version > 0),
    name TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL
);
```

- Code owns an immutable ordered registry of `(version, name, sha256, statements)`.
- Bootstrap/migrate under `BEGIN IMMEDIATE`; execute each statement individually;
  insert the registry row last; commit once.
- Before applying, require a contiguous applied prefix and exact name/checksum
  matches. A gap, changed checksum, duplicate, or database version newer than the
  application fails closed.
- Concurrent starters serialize at `BEGIN IMMEDIATE`; the second re-reads the
  registry after acquiring the writer transaction.
- Take and validate the backup before starting migration. Run complete integrity,
  foreign-key, and domain verification after commit.
- If `PRAGMA user_version` is mirrored for tooling convenience, update and verify it
  in the same migration and treat disagreement with the registry as corruption.
  The table remains canonical because it can prove migration identity/checksum.
- No migration calls Spotify, reads owner source files, edits configuration, or
  deletes legacy JSON. #138 introduces the registry without production cutover.

### Required tests

Fresh bootstrap, every supported prefix, concurrent bootstrap, crash at every
statement, checksum drift, version gap, newer schema, repeated migration, and
backup/restore must all be covered. Reopening after a crash sees either the prior
complete registry/schema or the next complete registry/schema.

## 14. Deterministic conformance and scale verification

### Project scale requirements

[#138](https://github.com/spontain112/djsupport/issues/138) requires 100,000 Source
Occurrences and 10,000 Transfers; [#142](https://github.com/spontain112/djsupport/issues/142)
requires 1,000 Qualification Drafts. The parent schema ticket additionally requires
1,000,000 compact Operational Events.
([#127](https://github.com/spontain112/djsupport/issues/127))

### Implementation and test implications (inference)

- Generate exactly 10,000 Transfers with ten ordered occurrences each. Derive all
  IDs, account/source keys, timestamps, revisions, and facts arithmetically; do not
  use wall clock, UUID randomness, network data, or owner fixtures.
- Repeat the same synthetic track fact at planned adjacent ordinals so the test
  proves occurrences are not deduplicated.
- Derive 1,000 drafts and 1,000,000 events from stable transfer indices. Use fixed
  compact category vocabularies; events never become authority inputs.
- Exercise the public `OperationalStore` contract against both adapters and compare
  canonical projections/hashes, not SQLite file bytes, rowids, query plans, or WAL
  layout.
- Every projection query includes explicit ordering. Verify exact counts, ordered
  identity digests, duplicate positions, revision sums, checkpoint categories,
  and restart/reopen equality.
- Use deterministic bounded batches that mirror real units of work; do not wrap the
  entire million-row fixture in one production-style transaction merely to make the
  test fast.
- Avoid wall-clock pass/fail thresholds across operating systems. Record duration
  and file/WAL sizes as diagnostic evidence; correctness, bounded lock tests, and
  absence of unbounded growth are the assertions.
- After the scale load: close/reopen, read from a second connection, run full
  integrity and foreign-key checks, use the Online Backup API, restore the backup,
  and compare the same canonical digest.
- Run ordinary conformance on every CI cell; run the full scale and crash suites on
  the explicit macOS/Linux/Windows persistence matrix, with Python 3.10 and 3.14
  edges on Linux.

## 15. Rejected unsafe patterns

| Rejected pattern | Why it is unsafe | Required replacement |
| --- | --- | --- |
| Long database transaction across Spotify | Holds the sole WAL writer while waiting on an unbounded external system and still cannot make the remote mutation atomic. | Commit journal intent, close transaction, call Spotify, open a new transaction for the observation. |
| Copying the database and WAL files | A live filesystem copy can mix points in time; the WAL is matched persistent state and cannot safely be paired, omitted, or deleted by hand. | `Connection.backup()` to a fresh file, then integrity, foreign-key, schema, and domain verification. |
| Unbounded lock waits or hidden retry loops | One writer exists; an unbounded client can freeze CLI/web/Agent work and retain stale decisions. | One five-second SQLite busy timeout, typed busy result, then a later fresh-connection retry. |
| Silent stale overwrite | A valid SQL update can replace authority using an obsolete client view. | Revision-qualified compare-and-swap; require exactly one row; reload before retry. |
| `BEGIN DEFERRED` for read-then-write authority | Another writer can invalidate the snapshot and cause mid-transaction `BUSY_SNAPSHOT`. | `BEGIN IMMEDIATE`, then re-read and validate inside the acquired write transaction. |
| Shared Python connection across request threads or forked processes | Violates Python's default thread ownership and SQLite's fork safety contract. | One connection factory; open and close in the executing thread/process. |
| Foreign keys left at their default | The default is normally off and can be compile-time dependent, so relying on it can permit orphan authority rows. | Enable and verify on every connection; run separate foreign-key checks. |
| `executescript()` inside a migration helper | Python may commit the pending transaction before the script, breaking the promised atomic boundary. | Registered statements executed individually inside one explicit transaction. |
| Unordered `SELECT` used as source order | SQLite does not promise insertion/rowid order and optimizer versions may change it. | Explicit occurrence ordinal plus `ORDER BY`. |
| Concurrent WAL on an unqualified SQLite runtime | The official WAL-reset advisory identifies a rare corruption race in affected versions. | Patched-runtime gate and CI/release evidence before #139 activation. |

## 16. Definition of done by issue

### #138 — one non-authoritative Operational Store path

- One deep interface and unit-of-work contract; in-memory and SQLite conformance.
- WAL bootstrap, migration registry, connection PRAGMA verification, exact ordered
  duplicate round-trip, compact events, and deterministic 100k/10k scale evidence.
- Database/sidecar privacy and packaging coverage.
- Production runtime remains on existing JSON with no dual-write or cutover.

### #139 — concurrent authority safety

- Patched SQLite runtime is a release gate.
- Two independent connections and two independent processes pass distinct-work,
  stale-write, bounded-busy, crash, integrity, and recovery tests.
- Every mutable authority entity uses compare-and-swap revisions.
- No transaction spans an external call; public redaction behavior is unchanged.

### #140 — Snapshot Effect Journal

- Immutable ordered manifest/items and prepared effect commit before Spotify.
- Observation commit afterward; uncertain crash window requires reconciliation.
- Stable identity prevents duplicate creation only when remote completion is proven.
- Preview produces no effect intent.

### #141 — atomic Approval

- Exact account-scoped manifest and playlist head/revision checks inside
  `BEGIN IMMEDIATE`.
- Approval, publication, matching knowledge, Corrections, conflicts, and event
  commit once or roll back together.
- Repetition is idempotent; stale inputs fail closed.

### #142 — Qualification Draft lifecycle

- Revisioned choices remain non-authoritative.
- Discard and successor insert are one transaction; apply uses the Effect Journal.
- Digests and account-scoped audio associations round-trip without local paths or
  process handles; deterministic 1,000-draft verification passes.

### #143 — Mirror lifecycle

- Account/source/selection/playlist identity, ordered managed items, manifest,
  Mirror revision, and effect state remain linked by constrained rows.
- Replacement, description, relink, and removal recover through separate stable
  effects.
- Drift offers only explicit restore/revocation; orphan state never infers deletion.

## Official sources

- DJ Support: [program #125](https://github.com/spontain112/djsupport/issues/125),
  [schema/migration #127](https://github.com/spontain112/djsupport/issues/127),
  [implementation map #128](https://github.com/spontain112/djsupport/issues/128),
  [#138](https://github.com/spontain112/djsupport/issues/138),
  [#139](https://github.com/spontain112/djsupport/issues/139),
  [#140](https://github.com/spontain112/djsupport/issues/140),
  [#141](https://github.com/spontain112/djsupport/issues/141),
  [#142](https://github.com/spontain112/djsupport/issues/142), and
  [#143](https://github.com/spontain112/djsupport/issues/143).
- SQLite: [WAL](https://sqlite.org/wal.html),
  [transactions](https://sqlite.org/lang_transaction.html),
  [isolation](https://sqlite.org/isolation.html),
  [result codes](https://sqlite.org/rescode.html),
  [PRAGMAs](https://sqlite.org/pragma.html),
  [foreign keys](https://sqlite.org/foreignkeys.html),
  [savepoints](https://sqlite.org/lang_savepoint.html),
  [Online Backup API](https://sqlite.org/backup.html), and
  [corruption hazards](https://sqlite.org/howtocorrupt.html).
- Python: [`sqlite3` in Python 3.10](https://docs.python.org/3.10/library/sqlite3.html)
  and [`sqlite3` in Python 3.14](https://docs.python.org/3.14/library/sqlite3.html).
