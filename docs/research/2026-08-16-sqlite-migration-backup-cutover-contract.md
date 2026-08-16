# SQLite migration, backup, and cutover contract

**Date:** 2026-08-16

**Baseline:** `origin/main` at `6b04a70`

**Status:** Implementation research for issues
[#144](https://github.com/spontain112/djsupport/issues/144),
[#145](https://github.com/spontain112/djsupport/issues/145),
[#146](https://github.com/spontain112/djsupport/issues/146), and
[#147](https://github.com/spontain112/djsupport/issues/147). No production
data, live service, database, backup, or credential was accessed.

**Authority:** SQLite documentation and source, Python standard-library
documentation, and the DJ Support repository and issue contracts. Sourced
facts and DJ Support design inferences are identified separately.

## Decision

Implement one recoverable pipeline:

1. canonical legacy readers take a stable, read-only snapshot of the three
   supported JSON authorities;
2. one transaction imports that snapshot into a private staging database;
3. semantic verification proves exact equivalence, then SQLite structural and
   relational checks prove the staged file is internally valid;
4. SQLite backups use `sqlite3.Connection.backup()` into a fresh staging
   database, never a live-file copy;
5. backup and restore artifacts are closed, self-contained SQLite files with
   no WAL or SHM member;
6. activation swaps one small authority pointer between validated SQLite
   generations while every client is quiesced; and
7. legacy JSON and superseded SQLite generations remain retained, inert, and
   private for an explicitly documented rollback window.

The authority pointer is a selector, not a second state store. Before the
pointer exists, the accepted migration version may use JSON. Once it exists,
the referenced SQLite generation is the only runtime authority; a missing,
unsupported, or damaged generation stops the application. It must never cause
a fallback to JSON.

## Non-negotiable boundaries

- **Reject live-file copying.** A WAL-mode database can contain committed data
  in `-wal` that is not yet in the main file. SQLite says separating the main
  file from its WAL can lose committed transactions or corrupt the database,
  and lists the Online Backup API as a safe way to copy a live database
  ([WAL persistent state](https://www.sqlite.org/wal.html#the_wal_file),
  [corruption guidance](https://www.sqlite.org/howtocorrupt.html#_backup_or_restore_while_a_transaction_is_active)).
- **Reject WAL/SHM archival.** The WAL is persistent database state while it is
  live; SHM is a transient, native-byte-order coordination cache and is rebuilt
  from WAL. Neither is a portable backup member
  ([WAL-mode files and recovery](https://www.sqlite.org/walformat.html#files_on_disk)).
  Produce a new logical snapshot through SQLite instead.
- **Reject dual-write.** JSON and SQLite must never both accept production
  writes. There is no two-database atomic commit in this design, and SQLite
  explicitly notes that WAL transactions spanning attached databases are not
  atomic as a set
  ([WAL limitations](https://www.sqlite.org/wal.html#overview)).
- **Reject silent fallback.** A bad or missing activated database is a recovery
  condition, not permission to resurrect stale JSON. Fallback would make
  authority depend on damage timing and could overwrite newer state.
- **Reject partial-client cutover.** CLI, web, and Agent Clients must drain and
  close their store connections before activation, then all reopen through
  Runtime Assembly. A pointer swap without connection quiescence would leave
  some clients using the old generation.
- **Reject deletion as retention policy.** Original JSON, superseded database
  generations, and rollback backups are removed only by a later explicit,
  separately previewed cleanup. Expiry of the rollback window is not deletion
  authorization.

## Primary-source facts

### A logical backup is the safe snapshot seam

Python's `Connection.backup(target, pages=..., progress=..., name="main",
sleep=...)` works while other clients access the source. Positive `pages`
values copy incrementally; the target is another `Connection`
([Python 3.10 `sqlite3` backup](https://docs.python.org/3.10/library/sqlite3.html#sqlite3.Connection.backup)).
The underlying SQLite API holds a write transaction on the destination, takes
only step-sized read locks on the source, restarts when another connection
changes the source, and leaves a completed destination as a consistent
snapshot. Continuous source writes can repeatedly restart an incremental
backup, so completion needs an application deadline rather than an unbounded
retry loop
([SQLite Online Backup API](https://www.sqlite.org/c3ref/backup_finish.html),
[backup locking](https://www.sqlite.org/backup.html#file_and_database_connection_locking)).

This guarantee is consistency, not an application-defined event boundary. A
backup under concurrent writes may advance as SQLite restarts it. Therefore a
DJ Support backup manifest must read its generation/revision facts from the
completed destination, never assume the copy represents the instant at which
the command began.

### WAL and connection lifecycle matter

In WAL mode, a read transaction sees one fixed snapshot, readers can coexist
with a writer, and only one writer can commit at a time
([WAL concurrency](https://www.sqlite.org/wal.html#concurrency),
[SQLite transactions](https://www.sqlite.org/lang_transaction.html#read_transactions_versus_write_transactions)).
Committed frames may remain in `-wal` until checkpointed. A clean final
read/write connection normally checkpoints and removes WAL/SHM, but abnormal
or read-only shutdown can leave them behind
([WAL file lifecycle](https://www.sqlite.org/walformat.html#file_lifecycles)).
SQLite recommends converting a database to `journal_mode=DELETE` before
placing the image on read-only media
([read-only WAL guidance](https://www.sqlite.org/wal.html#read_only_databases)).

As of this research date, SQLite documents a rare WAL-reset corruption bug in
versions through 3.51.2, fixed in 3.51.3 with backports 3.44.6 and 3.50.7. The
trigger requires multiple connections with concurrent checkpoint/write timing
([SQLite WAL-reset notice](https://www.sqlite.org/wal.html#the_wal_reset_bug)).
Python exposes the linked runtime version as `sqlite3.sqlite_version` and
`sqlite3.sqlite_version_info`, which is distinct from the Python wrapper
version
([Python runtime-version constants](https://docs.python.org/3.10/library/sqlite3.html#sqlite3.sqlite_version)).

### File identity and schema identity are different

SQLite provides a 32-bit `application_id` for identifying an application file
format and an application-owned 32-bit `user_version`. SQLite does not interpret
`user_version`. By contrast, `schema_version` is SQLite's internal schema
cookie; writing it manually can yield stale statements, wrong results, or
corruption
([application and user identifiers](https://www.sqlite.org/pragma.html#pragma_application_id),
[database header](https://www.sqlite.org/fileformat.html#the_database_header),
[schema-version warning](https://www.sqlite.org/pragma.html#pragma_schema_version)).
SQLite's source includes the known application-ID assignments
([`magic.txt`](https://www.sqlite.org/src/file?name=magic.txt&ci=trunk)).

### Integrity and referential integrity are separate checks

Full `PRAGMA integrity_check` returns one row containing `ok` when SQLite finds
no low-level format, page, index, uniqueness, or constraint-consistency error.
It does **not** detect foreign-key violations; `PRAGMA foreign_key_check` must
also return no rows
([SQLite integrity pragmas](https://www.sqlite.org/pragma.html#pragma_integrity_check)).
Foreign-key enforcement is disabled by default for compatibility and must be
enabled separately on every connection
([SQLite foreign-key enablement](https://www.sqlite.org/foreignkeys.html#fk_enable)).

An opened restore candidate is an external file even if it originally came
from DJ Support. SQLite recommends `PRAGMA trusted_schema=OFF` immediately on
each connection so schema expressions cannot invoke unaudited functions or
virtual tables
([SQLite trusted-schema guidance](https://www.sqlite.org/security.html#untrusted_sqlite_database_files)).

### Archive and filesystem primitives have narrower guarantees than the product

Python warns that ZIP extraction needs prior inspection; archives may contain
absolute or parent-relative paths, duplicate names are possible, CRC/header
checking is only what `testzip()` provides, decompression bombs can exhaust
resources, and interrupted extraction leaves partial output
([Python `zipfile`](https://docs.python.org/3/library/zipfile.html#zipfile.ZipFile.extractall),
[`testzip`](https://docs.python.org/3/library/zipfile.html#zipfile.ZipFile.testzip),
[decompression pitfalls](https://docs.python.org/3/library/zipfile.html#decompression-pitfalls)).
SHA-256 is guaranteed by `hashlib`; use a streaming `sha256().update(...)` loop
because `hashlib.file_digest()` was added only in Python 3.11
([Python `hashlib`](https://docs.python.org/3/library/hashlib.html)).

`os.replace(src, dst)` overwrites a file across platforms, may fail across
filesystems, and is atomic if successful. `os.fsync()` flushes a file descriptor
on Unix and Windows, but Python does not promise that one call makes a
multi-file protocol power-loss atomic
([Python `os.replace`](https://docs.python.org/3/library/os.html#os.replace),
[`os.fsync`](https://docs.python.org/3/library/os.html#os.fsync)).
Windows and POSIX also differ around open names: Windows commonly rejects
removal of an in-use file, while POSIX may unlink the name while existing
handles keep the old object
([Python removal semantics](https://docs.python.org/3/library/os.html#os.remove)).
Python 3.10 additionally cannot reopen a still-open `NamedTemporaryFile` by
name on Windows, so named database staging must close the creator handle before
SQLite opens it
([Python 3.10 temporary-file semantics](https://docs.python.org/3.10/library/tempfile.html#tempfile.NamedTemporaryFile)).

## DJ Support implementation contract

The remainder of this document is a project design inference from those facts
and the issue acceptance criteria. It is normative for the four tickets unless
implementation evidence forces a recorded revision.

### Store and archive identifiers

The Operational Store contract must define and test these independent values:

| Identifier | Meaning | Validation rule |
| --- | --- | --- |
| `APPLICATION_ID` | “This is a DJ Support Operational Store” | Choose one stable signed 32-bit value not currently assigned in SQLite `magic.txt`; every create, open, import, backup, and restore requires an exact match. |
| `PRAGMA user_version` | Current relational schema version | Positive monotonic integer. Open only versions explicitly registered as current or migratable. Never substitute package version or `schema_version`. |
| Migration registry | Applied application migrations | One row per immutable migration ID and digest, with a uniqueness constraint. The sequence and digest set must match the release's registry. |
| Schema fingerprint | Canonical expected SQL objects | Compare normalized expected tables, indexes, triggers, and views; do not rely on `user_version` alone. Do not emit SQL in user reports. |
| Store generation | Stable identity/name for one database lifetime | Non-personal random ID retained inside store metadata, backup manifest, and authority pointer. It changes for restore/cutover generations, not for ordinary transactions. The selected generation's contents and authority revision continue to advance while it is active. |
| Authority revision | Monotonic application commit fact | Read from the completed backup destination and use for Preview freshness and audit; never infer it from wall-clock time. |

Every connection must set `foreign_keys=ON`, `trusted_schema=OFF`, the accepted
busy timeout, and the accepted journaling/synchronous policy before it crosses
the Operational Store interface. Opening a database with the wrong application
ID, schema version, migration registry, or schema fingerprint fails closed.

### #144 — read-only JSON migration Preview

The current authorities are the three canonical stores selected by
`RuntimePaths`: Matching Knowledge, Publication State, and Transfer State
([runtime paths](../../djsupport/runtime.py),
[matching schemas](../../djsupport/cache.py),
[publication and Transfer readers](../../djsupport/transfer.py)). The importer
must call their canonical strict readers for every version those readers
document as supported. It must not introduce a fourth, permissive JSON parser.
Configuration and Spotipy-managed credentials never enter the snapshot or
database.

Preview protocol:

1. Acquire one migration-maintenance lease that all three JSON writers and new
   Runtime Assembly graphs honor. Acquire any existing file locks in a fixed
   documented order underneath that lease.
2. Open every input read-only, reject symlinks and unexpected file types, read
   bounded bytes, and retain a SHA-256 plus size in private process memory.
   Missing optional sections are interpreted only by the canonical versioned
   reader. Unknown, malformed, ambiguous, or unsupported data stops the run.
3. Convert each supported legacy version into one typed canonical domain
   snapshot. Preserve identities, explicit nulls, ordered Source Occurrences,
   duplicate occurrences, account/source/playlist relationships, Approval and
   Mirror authority, revisions, evidence digests, checkpoints, and incomplete
   external-effect facts. Never manufacture a completed effect from absence.
4. Create a uniquely named database in a private staging directory. Create the
   schema and import all rows inside one transaction with foreign keys enabled.
   A failure rolls the transaction back; the database is never a runtime path.
5. Commit, then verify application ID, user version, migration registry, schema
   fingerprint, full `integrity_check`, empty `foreign_key_check`, and the exact
   semantic equivalence contract below.
6. Re-read source size and digest before releasing the maintenance lease. Any
   change invalidates the Preview. Remove or quarantine the staging database;
   never activate it.
7. Return only a redacted report: supported/unsupported state, aggregate counts
   by domain category, equality booleans, bounded stable error codes, and a
   short-lived Preview token bound to source digests, importer version, schema
   version, and staging-store digest. Do not include paths, credentials, source
   metadata, playlist/track/account IDs, fingerprints, SQL, row values, or raw
   exceptions.

Exact verification is semantic rather than a count-only check. Both the typed
legacy snapshot and SQLite adapter must project the same canonical sequence for
each category. Each sequence uses explicit type tags, field names, null markers,
and length-prefixed values; ordered collections include zero-based ordinal and
duplicates as separate records. Compare counts and SHA-256 digests in constant
shape, and on mismatch bisect internally to a stable category/error code without
putting identifiers in the report. At minimum verify:

- Matching Knowledge observations, associations, outcomes, revisions, and
  Approval conflicts;
- Publication Manifests and their ordered/duplicate managed occurrences;
- Approval and Mirror identities, relationships, revisions, orphan/relink
  state, and evidence;
- Transfers, Batches, Qualification Drafts, successors, decisions, revisions,
  and checkpoints;
- Effect Journal intent, attempt, observed-result, and unknown/incomplete state;
- absence as well as presence of optional evidence and incomplete effects; and
- zero configuration rows, credential rows, local paths, filenames, raw source
  metadata, or process-local audition handles.

### #145 — backup creation

Backup protocol:

1. Resolve the active generation through the authority pointer and validate its
   identity. Create a new private sibling staging directory/file; do not reuse
   an old destination.
2. Open a dedicated source connection and a dedicated destination connection.
   Call `source.backup(destination, pages=N, progress=..., sleep=...)` with
   bounded retry/time policy. On cancellation, timeout, `BUSY`, `LOCKED`, I/O,
   or disk-full failure, close both and publish nothing.
3. Read store generation, authority revision, application ID, and user version
   from the **destination**. With no other destination client, normalize the
   snapshot to `journal_mode=DELETE`, close it cleanly, and require that no
   destination `-wal`, `-shm`, or rollback journal remains. Never delete a live
   sidecar to force this condition.
4. Reopen the closed candidate in read-only mode with trusted schema disabled.
   Require the exact identifiers, schema fingerprint, migration registry,
   `integrity_check == "ok"`, and no `foreign_key_check` rows. Close it again.
5. Stream SHA-256 over the final closed bytes. Construct a strict, versioned
   manifest containing only: archive-format version, store application ID,
   store schema/user version, migration-registry digest, store generation,
   authority revision, database member name, byte length, SHA-256, UTC creation
   time, and producing DJ Support/Python/SQLite versions. No credential,
   machine path, user identifier, playlist identifier, or source fact belongs
   in the manifest.
6. Write exactly two unique, relative regular-file members to a temporary ZIP:
   `backup-manifest.json` and `operational-store.sqlite3`. Close it, reopen it,
   run CRC/header checks, parse the manifest strictly, and recheck the embedded
   database hash and size. Flush/fsync the archive, then `os.replace` it into
   the chosen destination on the same filesystem. A failed final replace leaves
   the previous archive untouched.

The hash detects accidental mismatch between manifest and database; because an
attacker could replace both, it is not an authenticity signature. Do not claim
tamper authentication without a separately designed key-management system.

### #145 — restore validation and Preview

Restore must not call `extractall()`. Inspect `ZipInfo` entries first and reject:

- any member set other than the two exact allowlisted names;
- duplicate names, directories, symlinks/special files, encrypted entries,
  NULs, absolute paths, drive/UNC prefixes, backslashes, `.` or `..` segments;
- unsupported compression, CRC/header failure, excess member count, excess
  compressed or uncompressed size, suspicious compression ratio, or insufficient
  staging disk budget; and
- an unknown manifest field/version, duplicate JSON key, noncanonical type,
  hash/length mismatch, unsupported application/schema/migration identity, or
  any credential/private identifier field.

Stream the database member into a newly created private staging file with a
hard byte limit. Close it before SQLite opens it. Then apply the same trusted
schema, application ID, user version, migration registry, schema fingerprint,
full integrity, and foreign-key checks used by backup. Reject a database that
creates or requires a WAL/SHM sidecar. A Preview contains only redacted schema,
generation, revision, age, size, compatibility, and validation results plus a
short-lived token bound to the archive digest and the current live authority
revision and canonical semantic digest. Apply revalidates those live freshness
facts after acquiring the maintenance lease; the token is not authority by
itself.

### #145/#146 — atomic activation

Use stable generation identities plus a small authority pointer, rather than
overwriting the active database path:

```text
private application data/
  operational-store.authority.json       # selector only
  operational-stores/
    <generation-a>.sqlite3                # active: stable identity, mutable state
    <generation-b>.sqlite3                # validated inactive candidate
```

The pointer contains only its format version, a generation basename, and the
expected store-generation ID—no database-content hash, authority revision,
path outside its fixed store directory, or user data. Its parser accepts only
a plain basename and reconstructs the path beneath the fixed private directory.
Runtime then opens that database and validates the matching store-generation
ID, application ID, supported user version, migration registry, and schema
fingerprint. The selected generation's bytes and authority revision are
expected to change during ordinary transactions, so startup must never compare
them with an activation-time value in the steady-state pointer.

Activation protocol:

1. Acquire a cross-process maintenance lease at the Runtime Assembly boundary;
   refuse new graphs, wait for active operations to finish, and close every CLI,
   web, and Agent Client connection. A bounded failure to quiesce aborts.
2. For migration, create and verify the complete current JSON backup before
   importing. For restore, create and verify an online backup of the currently
   active SQLite generation. Never continue if that rollback artifact fails.
3. Revalidate the source/active revision and all Preview-bound hashes. Import or
   extract into a unique generation in the fixed store directory, then run the
   full semantic, structural, and relational checks. Close all handles and
   fsync the generation.
4. Write and fsync a temporary pointer in the same directory as the authority
   pointer. The only activation point is `os.replace(temp_pointer,
   authority_pointer)`. Before it, the old pointer (or pre-cutover JSON mode)
   remains authority; after it, the new complete generation is authority.
   An unreferenced generation left by a crash is inert staging, not authority.
5. Reopen Runtime Assembly from the pointer, recheck the database identities
   and the activation-candidate revision retained by the in-progress apply
   operation (not by the steady-state pointer), and release the lease. If reopen
   fails after activation, stop in explicit recovery mode; do not write JSON or
   silently select the previous generation.

This pointer design avoids Windows replacement of an open database and POSIX
stale handles to an unlinked database. Quiescence remains mandatory because an
already-open connection would otherwise keep writing the previous generation
after the pointer swap.

For process-crash semantics, one atomic pointer replacement gives an observable
old-or-new authority. For power-loss durability, flush the database and pointer
and sync directory metadata where the OS supports it, but document that Python
and commodity filesystems cannot promise perfect storage hardware. Startup must
therefore validate the pointer format/basename and the selected database's
generation, application, and schema identities, and fail closed on missing or
torn state. Inactive staging/retained generations may be byte-hashed; the
selected active generation may not be treated as byte-immutable. The
cross-platform test matrix below is a release gate, not a substitute for that
recovery behavior.

### Rollback window and legacy JSON retention

The 0.7 release documentation must define the rollback window by a concrete
date or release boundary before #145/#146 ship. During the window:

- retain the byte-identical original JSON set, its verified pre-cutover backup,
  every authority pointer needed to identify the prior SQLite generation, and
  a verified backup of each generation being replaced;
- keep JSON outside Runtime Assembly after activation. “Readable for migration
  or rollback” is not a production adapter and must not become one;
- before a SQLite-to-SQLite rollback, backup the current generation, stage and
  validate the chosen prior generation, show the revision difference, require
  explicit apply, then use the same pointer-swap protocol;
- before a 0.7-to-0.6 version rollback, backup current SQLite and show that any
  post-cutover changes are absent from the retained JSON baseline. Require an
  explicit data-loss acknowledgement. The rollback tool may prepare legacy
  files for the old binary, but the 0.7 runtime must not start writing them; and
- when the window expires, report retained artifact categories and offer a
  separately confirmed cleanup/archive action. Never silently delete or
  overwrite the original JSON.

Legacy filenames, database files, WAL/SHM sidecars, generation pointers,
snapshots, backup ZIPs, extracted restores, staging files/directories, rollback
copies, integrity diagnostics, query exports, operational events, and reports
are private application data. They must be covered by repository ignore,
privacy scans, package-manifest exclusion, wheel/sdist inspection, and synthetic
tests. None belongs in Git or a distribution.

## Crash-injection contract

Use a subprocess and durable synthetic fixtures. At each numbered point, force
an exception and a hard process exit in separate tests; after restart, inspect
through public readers rather than trusting temporary-file presence. Every case
must yield one complete recognized authority and preserve the original inputs.

| Flow | Injection points | Required post-restart result |
| --- | --- | --- |
| JSON Preview | before lease; after each source open/read; after source digest; after schema create; between every domain import phase; immediately before/after staging commit; during exact verification; after report creation; during cleanup | JSON bytes and metadata-content digests unchanged; no authority pointer change; no staging database accepted as authority; malformed/partial stage is removable or quarantined. |
| SQLite backup | before destination create; during each backup progress callback; after backup completion; before/after destination close; during journal normalization; during integrity/FK checks; during hash; while writing each ZIP member; after ZIP close; after archive verification/fsync; immediately before/after final archive replace | Active generation remains usable; no partial archive at final name; an old archive at that name remains byte-identical or one complete new archive exists. |
| Restore Preview | before member inspection; during streamed extraction; after size/hash checks; during database open; during every identity/integrity check; after Preview token; during cleanup | Active pointer and generation unchanged; partial extraction is not opened by Runtime Assembly; source archive unchanged. |
| Migration/restore apply | before lease; while draining clients; after rollback backup; after source revalidation; between import phases; before/after staging commit; during semantic/integrity checks; after generation fsync; while writing/fsyncing temporary pointer; immediately before/after pointer replace; before Runtime Assembly reopen; after reopen before lease release | Before pointer replace: old authority only. After pointer replace: new generation only. An invalid selected generation causes recovery stop, never JSON fallback. Original JSON and verified rollback artifact remain. |
| Explicit rollback | before current-generation backup; after backup; after prior-generation validation; before/after pointer replace; before old-version JSON preparation | Current or chosen prior authority is complete and deterministic; post-cutover SQLite backup and original JSON remain retained; no automatic loss or deletion. |

The test harness must also crash while a source writer is committing and while a
reader holds a WAL snapshot. A bounded `BUSY`/`LOCKED`/deadline result is an
acceptable failed operation; a torn success is not.

## Cross-platform verification matrix

Run all tests with synthetic application data and a staging directory located
beside the active private store so pointer replacement cannot cross filesystems.
At minimum run Linux on Python 3.10 and 3.14 plus native macOS and Windows on a
supported Python. Record `sqlite3.sqlite_version` in CI evidence and reject a
known-vulnerable WAL build unless the platform vendor documents the relevant
backport.

| Verification | Linux | macOS | Windows | Pass evidence |
| --- | --- | --- | --- | --- |
| Online backup under concurrent WAL writes | Python 3.10 + 3.14 | Native runner | Native runner | Completed backup has accepted identity, exact internal revision, `integrity_check=ok`, no FK rows, and no WAL/SHM member; deadline failure publishes nothing. |
| Raw-copy negative control | Required | Required | Required | Put a committed marker in WAL, copy only the main file in test isolation, and prove it is not an accepted backup. This test documents why production never uses the path. |
| Backup cancellation/disk-full/I/O failure | Required | Required | Required | Existing archive and active store unchanged; temp artifacts private and non-authoritative. |
| Hostile restore archives | Required | Required | Required | Traversal, drive/UNC, backslash, duplicate, symlink/special, encrypted, oversized/bomb, bad CRC, bad hash, extra member, unknown manifest, wrong application/schema, corrupt page, and FK violation all fail before Preview/apply. |
| Same-directory pointer replacement | Native filesystem | APFS/default runner filesystem | NTFS/default runner filesystem | Repeated readers observe complete old or new pointer JSON, never partial; cross-volume candidate is rejected before apply. |
| Open-handle cutover guard | POSIX stale-handle scenario | POSIX stale-handle scenario | Sharing/replace-failure scenario | Activation refuses until all registered clients close; after success every new graph reports the new generation and no old graph can write. |
| Subprocess hard-exit matrix | Required | Required | Required | Every injection point satisfies the old-or-new table above over repeated runs. |
| 0.7 rollback-window round trip | Required | Required | Required | Pre-cutover JSON hash unchanged; current SQLite backed up; prior generation restored only after Preview; second restore can return to the later generation. |
| Privacy and packaging | Required | Required | Required | Git and built wheel/sdist contain none of the private artifact patterns or synthetic run output. |

Do not claim power-failure certification from ordinary CI. Process termination,
I/O fault injection, and native-filesystem tests prove the application state
machine. Filesystem/hardware durability remains bounded by the platform's
documented flush and rename behavior.

## Acceptance-criteria mapping

| Issue | Acceptance evidence produced by this contract |
| --- | --- |
| #144 | Canonical supported-version readers; one maintenance-stable read-only snapshot; all named matching/publication/Approval/Mirror/Transfer/Batch/Qualification/checkpoint/legacy facts; one-transaction staging import; typed semantic projections covering identity/order/duplicates/relationships/authority/revisions/evidence/incomplete effects; fail-closed source revalidation; redacted report; synthetic crash matrix; explicit credential/config exclusion; ticket-specific release record. |
| #145 | `Connection.backup` logical snapshot; closed DELETE-mode single-file artifact; strict two-member manifest/hash archive recording store schema and hash; hostile path/member/resource validation; trusted-schema/application/schema/integrity/FK gates; redacted Preview-bound revalidation; validated generation plus atomic pointer apply; retained prior backup and explicit 0.7 rollback policy; documented ignore/privacy/package matrix; native synthetic platform tests; ticket-specific release record. |
| #146 | Verified complete current-state backup before apply; exact #144 verification in staging; one pointer-replace activation point; Runtime Assembly lease and CLI/web/Agent reopen; pre-switch JSON versus post-switch SQLite determinism; no dual-write/partial-client/silent-fallback path; byte-identical legacy retention; configuration/credentials remain external; crash injection at every phase; live services and publication remain gated; ticket-specific release record. |
| #147 | Runtime and Transfer interfaces resolve only the SQLite generation selected by the pointer; JSON readers move to explicit migration/rollback tooling only; obsolete JSON writers/locks/temp paths/schema constants can be deleted; interface-level behavior tests replace adapter-specific tests without weaker coverage; ignore/privacy/package checks enumerate every database and transition artifact; canonical architecture/storage docs name SQLite as sole production authority; complete offline and package suites pass; ticket-specific release record. |

All four tickets remain fully synthetic and offline. They do not authorize
Spotify or Beatport calls, owner-data access, tags, releases, or package
publication. Each distributable ticket adds its own `.release-notes/*.md`
record; adding the record does not authorize consuming it into a release.

## Implementation order and review gates

1. Freeze the application ID, user-version registry, schema fingerprint, and
   canonical semantic projections before writing importer or backup code.
2. Build #144 without an activation API. Its staging path must be structurally
   impossible for Runtime Assembly to select.
3. Build #145 backup and hostile restore Preview. Prove the snapshot is
   self-contained and the pointer protocol works with synthetic stores before
   enabling restore apply.
4. Build #146 around one maintenance lease and one pointer replacement. Review
   the cached diff specifically for a JSON write, fallback, second activation
   flag, or client-specific store choice; any one of those blocks merge.
5. Keep the explicit rollback tool and supported legacy readers, then complete
   #147 by deleting production JSON writers and adapter-specific tests only
   after interface-level behavior coverage is equivalent.

Security, privacy, and packaging review must inspect generated artifacts, not
only source patterns. Release review must verify the native platform matrix and
the linked runtime SQLite versions. A green integrity check alone is not exact
migration proof, and a matching SHA-256 alone is not archive authenticity.

## Primary sources

- SQLite: [Online Backup API](https://www.sqlite.org/c3ref/backup_finish.html),
  [backup guide](https://www.sqlite.org/backup.html),
  [WAL](https://www.sqlite.org/wal.html),
  [WAL file format and lifecycle](https://www.sqlite.org/walformat.html),
  [database corruption hazards](https://www.sqlite.org/howtocorrupt.html),
  [transactions](https://www.sqlite.org/lang_transaction.html),
  [pragmas](https://www.sqlite.org/pragma.html),
  [foreign keys](https://www.sqlite.org/foreignkeys.html),
  [database file format](https://www.sqlite.org/fileformat.html),
  [untrusted database guidance](https://www.sqlite.org/security.html), and
  [`magic.txt`](https://www.sqlite.org/src/file?name=magic.txt&ci=trunk).
- Python: [3.10 `sqlite3`](https://docs.python.org/3.10/library/sqlite3.html),
  [`os`](https://docs.python.org/3/library/os.html),
  [`zipfile`](https://docs.python.org/3/library/zipfile.html),
  [`hashlib`](https://docs.python.org/3/library/hashlib.html), and
  [3.10 `tempfile`](https://docs.python.org/3.10/library/tempfile.html).
- DJ Support: [program #125](https://github.com/spontain112/djsupport/issues/125),
  [migration Preview #144](https://github.com/spontain112/djsupport/issues/144),
  [backup/restore #145](https://github.com/spontain112/djsupport/issues/145),
  [cutover #146](https://github.com/spontain112/djsupport/issues/146), and
  [JSON-writer retirement #147](https://github.com/spontain112/djsupport/issues/147).
