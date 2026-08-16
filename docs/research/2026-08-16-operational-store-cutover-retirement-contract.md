# Operational Store cutover and JSON-retirement contract

**Date:** 2026-08-16

**Current baseline:**
[`origin/main` at `3e6ae7f`](https://github.com/spontain112/djsupport/commit/3e6ae7f6157364eeedaa2667d2a1deabed9efcee)

**Scope:** implementation-readiness research for
[#144](https://github.com/spontain112/djsupport/issues/144),
[#145](https://github.com/spontain112/djsupport/issues/145),
[#146](https://github.com/spontain112/djsupport/issues/146), and
[#147](https://github.com/spontain112/djsupport/issues/147). No owner data,
live service, database, backup, credential, tag, release, or package was
accessed or changed.

**Contract precedence:** The ready-to-paste issue amendments are the proposed
normative execution delta; the preceding sections explain and source that delta.
Once an amendment is accepted into an issue, the issue body is authoritative.
Do not combine conflicting versions—reconcile the amendment first.

**Relationship to earlier research:** this note reuses, and does not edit, the
existing
[migration/backup/cutover](2026-08-16-sqlite-migration-backup-cutover-contract.md),
[concurrency/durability](2026-08-16-sqlite-concurrency-durability-contract.md),
and
[APSW integration](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/docs/research/2026-08-16-apsw-operational-store-integration-contract.md)
contracts. Where the older cutover note uses Python's standard-library
`sqlite3` API as an example, ADR-0005 and #165 now supersede that mechanism:
APSW 3.53.4.0 is the sole production binding and Python `sqlite3` must never
open an Operational Store
([ADR-0005](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/docs/adr/0005-use-one-local-transactional-operational-store.md)).

## Decision summary

The four issues have the right dependency order, but their current acceptance
criteria leave six production-significant decisions implicit. They should be
amended before implementation is claimed:

1. **Freeze the exact legacy input catalog and semantic projection.** The
   phrase “every documented supported JSON schema version” currently conflates
   the three canonical authorities with archive-only compatibility names and
   migration records. A count-only comparison or permissive `json.loads()` is
   not exact verification.
2. **Add one cross-process maintenance gate.** The three current files do not
   form one transaction. Preview can claim one coherent snapshot only if every
   JSON writer participates in a shared/exclusive gate and source bytes are
   revalidated before the exclusive lease is released.
3. **Make the authority selector a strict state machine, not an optional
   pointer.** “No pointer” cannot safely mean both “old installation” and
   “activated pointer was lost.” Ordinary 0.7 startup must never infer either
   legacy authority or a fresh empty store.
4. **Isolate retained JSON from old runtime paths.** Leaving byte-identical
   JSON at the 0.6 canonical filenames makes it inert only to new code; an old
   binary can still write it and create split authority. Cutover must retain
   the bytes in a rollback generation outside all legacy production paths.
5. **Define the rollback window as a compatibility boundary, not a deletion
   timer.** Support should span the complete 0.7.x release line. Expiry removes
   a support promise, never data. Cleanup is a separate Previewed and explicitly
   confirmed operation.
6. **Make crash evidence native and binding-specific.** APSW's Online Backup
   API, a test-only APSW VFS, subprocess hard exits, and native filesystem tests
   must cover the selected macOS, Linux, and Windows cells. An injected Python
   exception alone is not process-crash evidence.

The final authority rule is deliberately simple: before the final selector
replacement, legacy JSON remains the recoverable authority; after it, the
selected, validated SQLite generation is the only production authority. An
invalid, missing, unsupported, or ambiguous selector or generation is an
explicit recovery state—not permission to open JSON, create an empty database,
or select another generation.

## Current evidence and gaps

### Accepted foundation

- ADR-0005 fixes one SQLite Operational Store, one deep internal interface, no
  ORM, no dual-write, no silent fallback, one atomic selector, Online Backup
  API snapshots, inert retained JSON, and an Effect Journal around external
  effects
  ([ADR-0005](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/docs/adr/0005-use-one-local-transactional-operational-store.md)).
- The exact APSW 3.53.4.0 artifact and SQLite 3.53.4 runtime are admitted only
  for the versioned native cells from #166/#167. Qualification happens before
  any owner-data path is resolved; unavailable evidence has no JSON,
  rollback-journal, warning, configuration, or dual-binding fallback
  ([qualified runtime delivery](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/docs/sqlite-runtime-delivery.md)).
- Runtime Assembly is already the common CLI, web, and Agent Client
  construction seam, but it still constructs `MatchCache`,
  `FilePublicationStorage`, and `FileTransferStorage` from two paths and a
  derived third path
  ([current assembly](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/djsupport/runtime.py)).
- Current storage documentation records matching-knowledge versions 1–3,
  publication versions 1–7, Transfer-state versions 1–6, plus archive-only
  compatibility members and two version-1 migration records
  ([storage inventory](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/docs/storage.md)).

### Gaps visible in current code

- `MatchCache.load()` treats an initially missing file as empty and catches a
  JSON parse failure by returning without facts; its later
  `reload_strict()` is stricter. The migration path must not call the permissive
  initial loader or interpret malformed authority as empty
  ([matching reader](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/djsupport/cache.py)).
- Publication and Transfer files have independent write paths; only Transfer
  state owns a process/thread lock. There is no one lease honored by all three
  writers, so three sequential reads are not yet one coherent source snapshot
  ([file stores](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/djsupport/transfer.py)).
- `LocalDataBackup` is a JSON merge archive. It does not implement an APSW
  Online Backup snapshot, a closed standalone SQLite member, SQLite integrity
  checks, or generation activation. It is reusable behavior evidence, not the
  #145 implementation
  ([current backup](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/djsupport/backup.py)).
- Current behavior physically removes a revoked matching entry and an active
  Mirror relationship, while it retains Publication history, Approval outcomes,
  discarded/superseded Qualification Drafts, and abandoned publication history.
  Migration must preserve the resulting current facts; it cannot invent a
  tombstone or historical event that JSON never retained
  ([matching revocation](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/djsupport/cache.py),
  [Mirror removal and Qualification retention](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/djsupport/transfer.py)).
- No authority selector, transition state, rollback catalog, JSON quarantine,
  Operational Store bootstrap, or post-cutover fail-closed startup path exists
  yet. The merged Operational Store package currently contains only runtime
  qualification and delivery seams
  ([package interface](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/djsupport/operational_store/__init__.py)).

## Primary-source constraints

### APSW backup and failure mechanics

APSW reverses the standard-library-looking backup call: the **destination**
connection creates `destination.backup("main", source, "main")`. The source and
destination must be distinct; `Backup.step()` may raise `BusyError` or
`LockedError`; `finish()` commits a complete copy or rolls an incomplete copy
back; and the destination remains write-locked for the backup lifetime. APSW
also states that page-level backup copies free pages
([APSW 3.53.4.0 backup](https://rogerbinns.github.io/apsw/backup.html)).

SQLite's Online Backup API produces a consistent destination while allowing
incremental source access. Concurrent source writes can restart the copy, so an
application deadline is necessary to prevent an unbounded operation
([SQLite backup API](https://www.sqlite.org/backup.html)). A live main file must
not be copied independently of a hot WAL: SQLite identifies the Online Backup
API and `VACUUM INTO` as safe live-copy methods and warns that a mismatched or
deleted hot journal can lose committed data or corrupt recovery
([corruption hazards](https://www.sqlite.org/howtocorrupt.html)).

### WAL and store-family lifecycle

In WAL mode, committed transactions may live only in `-wal`; the main file,
WAL, and SHM are one live family. A clean final read/write close normally
checkpoints and removes sidecars, but a crash or final read-only close can leave
them. The WAL must remain paired with its database until SQLite performs
recovery
([WAL lifecycle](https://www.sqlite.org/wal.html#the_wal_file),
[WAL file format](https://www.sqlite.org/walformat.html#file_lifecycles)).
That is why backup produces a new, closed, DELETE-mode destination rather than
archiving any live member.

### Opening selected and restored databases

`sqlite3_open_v2()` supports `SQLITE_OPEN_NOFOLLOW`; `READWRITE` can historically
fall back to read-only when permissions prevent writing, so the caller must
verify the resulting mode. `READWRITE` without `CREATE` rejects a missing file.
URI parameters can alter mode, cache, locking, immutability, or VFS selection,
so production generation opens must not accept URI interpretation
([SQLite open flags](https://www.sqlite.org/c3ref/open.html),
[URI cautions](https://www.sqlite.org/uri.html)). APSW exposes those open flags
directly through `Connection`
([APSW connection](https://rogerbinns.github.io/apsw/connection.html)).

A restored database is untrusted input even when it claims DJ Support
provenance. SQLite recommends disabling trusted schema immediately and, for
sensitive readers, enabling defensive mode, reducing limits, disabling
memory-mapped I/O, and checking integrity before other work
([SQLite untrusted-database guidance](https://www.sqlite.org/security.html)).
`integrity_check` does not check foreign keys; `foreign_key_check` is separate
([SQLite pragmas](https://www.sqlite.org/pragma.html#pragma_integrity_check)).

### JSON, archives, and atomic replacement

Python's default JSON decoder accepts `NaN`/infinities and duplicate object
names, keeping only the last duplicate. `parse_constant` and
`object_pairs_hook` are therefore required for a fail-closed authority parser
([Python JSON compliance](https://docs.python.org/3.14/library/json.html#standard-compliance-and-interoperability)).
Python also warns that ZIP input can contain duplicate names, path surprises,
unsupported or corrupt members, resource-exhaustion payloads, and incomplete
extraction after interruption; restore must inspect and stream allowlisted
members rather than call `extractall()`
([Python `zipfile`](https://docs.python.org/3.14/library/zipfile.html)).

`os.replace()` cannot cross filesystems and provides atomic rename semantics
where the platform supplies them. `fsync()` flushes a file descriptor through
the platform API, but Python does not provide a portable multi-file power-loss
transaction
([Python `os.replace` and `fsync`](https://docs.python.org/3.14/library/os.html#os.replace)).
The selector protocol must therefore use one same-directory replacement as its
only activation point, validate after every restart, and prove native behavior;
it must not claim stronger hardware durability than the operating system.

### Logical deletion is not physical erasure

SQLite normally leaves deleted bytes in free pages. `secure_delete=ON` can
overwrite ordinary deleted table content, while `VACUUM` rebuilds a database;
APSW's Online Backup API copies free pages. A retained backup or old generation
may therefore contain facts deleted from the current logical state
([SQLite secure delete](https://www.sqlite.org/pragma.html#pragma_secure_delete),
[`VACUUM INTO`](https://www.sqlite.org/lang_vacuum.html),
[APSW backup](https://rogerbinns.github.io/apsw/backup.html)). Neither #145 nor
#147 should promise forensic erasure. A later erasure feature would need its own
scrubbed-generation, backup-retention, and verification contract.

## Shared authority and maintenance contract

All four tickets depend on one gate owned by Runtime Assembly and the
Operational Store interface:

- Ordinary JSON writers before cutover and all SQLite operations after cutover
  acquire a shared **operation lease** for the full high-level operation. An
  Effect Journal transaction may close around a Spotify call, but its enclosing
  operation lease remains held so cutover cannot split the intent and observed
  result across generations.
- Migration Preview, backup apply, restore apply, cutover, generation rollback,
  and old-version rollback acquire the exclusive **maintenance lease**. The
  exclusive path blocks new graphs, waits a bounded time for active operations,
  then requires every connection, cursor, backup, and pointer handle closed.
- The lease is process-crash-releasing and works natively on macOS, Linux, and
  Windows. A process-local mutex or the current Transfer-state lock alone is not
  sufficient.
- A failure to acquire or drain by the deadline returns a redacted busy/recovery
  outcome and performs no authority change. It never kills another process or
  bypasses the gate.

This is coordination, not authority. The selector determines authority; the
lease only prevents a client from retaining or writing through a stale
selection during a transition.

## #144 exact JSON-to-SQLite Preview contract

### Freeze the input catalog

The issue should name these inputs explicitly:

| Role | Canonical member | Supported versions | Migration treatment |
| --- | --- | --- | --- |
| Matching authority | `matching-knowledge.json` | 1, 2, 3 | Strict version codec into canonical Matching Knowledge facts. |
| Publication authority | `publication-manifests.json` | 1–7 | Strict version codec into manifests, ordered items, Approvals, active Mirrors, and retained publication facts. |
| Transfer authority | `publication-manifests.transfers.json` | 1–6 | Strict version codec into Transfers, Batches, Qualification Drafts, checkpoints, and incomplete-effect facts. |
| Ancillary legacy facts | `legacy-migration.json` | 1 | Import as explicit non-authorizing migration/relink/history facts. |
| Ancillary foundation fact | `foundation-migration.json` | 1 | Import the accepted stable-account migration fact; never a credential. |

`config.json`, environment values, Spotipy token storage, reports, source XML,
audio, and generated diagnostics are outside the importer. The backup-only
compatibility names `transfers.json` and `playlist-state.json` are not current
Runtime Assembly authorities. Their presence alongside canonical state is
ambiguous and must fail with a safe code unless an explicit supported legacy
normalization workflow first produces the canonical three-file family. This
distinction should be reflected in both #144 and `docs/storage.md`.

### Acquire one stable source snapshot

1. Qualify the exact APSW runtime and artifact before resolving a database path.
2. Acquire the exclusive maintenance lease; then acquire any existing
   per-file locks in one documented order.
3. Open only exact allowlisted regular files beneath the canonical private
   root. Reject symlinks, special files, aliases, duplicate logical inputs, and
   oversized input before parsing.
4. Read bounded bytes once, record a private presence bitmap, size, file
   identity, and SHA-256, and parse with duplicate-key, non-finite-number,
   unknown-version, shape, and domain validation. A file that is absent is
   distinct from a present empty document; cross-store references must still
   validate.
5. Import the typed snapshot into a uniquely created, non-selectable staging
   generation through one APSW `BEGIN IMMEDIATE` unit. Do not use a generic
   JSON merge or the permissive runtime cache loader.
6. Commit, run exact semantic verification plus application/schema/migration
   identity, schema fingerprint, full integrity, and foreign-key checks.
7. Re-stat and re-hash every present source before releasing the lease. Any
   replacement or byte change invalidates the Preview. Original bytes remain
   byte-identical.

### Freeze one semantic projection

Legacy codecs and both Operational Store adapters must produce the same
versioned canonical projection. The projection contract is executable test
data, not report output:

- a fixed category registry and field registry with explicit type tags;
- explicit distinction among absent, null, false, zero, and empty collection;
- deterministic logical-key ordering for maps and sets;
- zero-based ordinal for every ordered collection, with duplicate Source
  Occurrences emitted as separate records;
- exact integer/boolean/string values, finite floats represented by their exact
  binary value, and version-codec-defined timestamp semantics;
- imported revisions unchanged—migration itself does not consume an entity
  revision;
- relationships checked in both directions so an orphan, duplicate key, or
  silently dropped child fails;
- a fixed mapping for every legacy incomplete checkpoint into “not attempted,”
  “observed complete,” or “uncertain/review required”; no absence may be
  promoted to a completed effect; and
- zero fabricated Approval, Matching Knowledge, Effect Journal, or Operational
  Event history. A current JSON absence remains absent unless a documented
  version codec defines a semantic default.

Compare the complete typed sequences and per-category counts/digests from both
readers. A mismatch may be narrowed internally, but the public Preview exposes
only category, equality, bounded counts, and a stable reason code—not record
values, identifiers, paths, SQL, or raw exceptions.

The Preview token binds the source presence/digests, importer and projection
versions, target schema/migration identity, staging semantic digest, and an
expiry. It is not authority and cannot be used if any bound value changes. A
#144 staging file is structurally outside the generation directory selected by
Runtime Assembly and is deleted only when the current process proves it created
and never selected it; crash-orphaned staging is quarantined until the same
proof can be made.

## #145 APSW backup and restore contract

### Backup

1. Qualify the runtime before resolving the active private path. Acquire a
   shared operation lease and resolve the exact `sqlite` selector generation.
2. Create an unpredictable, exclusive, empty destination in the private
   same-filesystem staging root; close its creator handle before APSW opens it,
   which is required for portable Windows behavior.
3. Use distinct qualified APSW connections and
   `destination.backup("main", source, "main")`. Copy bounded page batches;
   retry `BusyError`/`LockedError` only within one injected monotonic deadline;
   always call `finish()` through the backup context.
4. Read store generation, authority revision, schema/migration identity, and
   canonical semantic digest from the completed destination—not from a value
   sampled before backup.
5. Convert the destination to `journal_mode=DELETE`, require the returned mode,
   close every handle, and require no destination WAL, SHM, or hot journal.
6. Reopen read-only with no URI, no create, no symlink following, trusted schema
   off, defensive limits, and no custom functions. Require exact identity,
   schema fingerprint, full integrity, empty foreign-key check, and the retained
   semantic digest.
7. Hash the closed bytes. Write one strict manifest and one database member to a
   new archive; stream and verify the complete archive before same-directory
   replacement. The manifest hash detects accidental mismatch, not malicious
   replacement of both manifest and database.

The manifest includes format version, database member, closed byte size/hash,
application ID, user version, migration-registry digest, schema fingerprint,
source store generation, authority revision, semantic digest, producing
DJ Support/APSW/SQLite versions, and UTC creation time. It contains no path,
credential, account, source, playlist, track, fingerprint, row, SQL, or error
text.

### Restore Preview and apply

Restore streams exactly the allowlisted manifest and database members after
rejecting duplicate names, directories, links/special files, encryption,
absolute/drive/UNC/backslash/parent paths, unknown fields, unsupported
compression, CRC/hash/length mismatch, resource limits, wrong identities,
corruption, and foreign-key violations. It never calls `extractall()`.

The restored database is never installed over an active file. Apply acquires
the exclusive maintenance lease, backs up and verifies the current authority,
revalidates the Preview token and current revision, copies the restored logical
state into a **new physical generation with a new store-generation ID**, verifies
it, and activates it through the selector protocol below. The backup manifest
retains the source generation ID; two independently restored physical files do
not masquerade as the same generation.

An Online Backup copy may contain deleted bytes in free pages. Backups, retained
generations, and rollback JSON are therefore private historical artifacts and
may retain facts absent from current logical authority. Restore/cleanup Preview
must say so without exposing those facts. Deleting a current row never claims to
erase an existing backup.

## #146 selector, cutover, and startup contract

### Strict selector states

Use one bounded, duplicate-key-rejecting JSON selector at a fixed private path.
It is a tagged union, not an arbitrary configuration file:

| State | Authority and permitted behavior |
| --- | --- |
| absent | Ordinary 0.7 clients return `store_initialization_required` or `migration_required`; they do not infer an empty store or open JSON. Only explicit initialize/migrate tooling may proceed after inspecting the private root. |
| `json` | Legacy JSON is authority during the #146 transition. It is accepted only by migration/rollback tooling after #147. |
| `transition` | JSON remains the recoverable authority, but ordinary work is stopped. The selector binds one transition ID, source digests, retained JSON generation, and intended SQLite generation so recovery can restore JSON paths or complete the same transition without guessing. |
| `sqlite` | The named SQLite generation and embedded store-generation ID are sole authority. |
| `legacy_rollback` | Byte-verified JSON has been explicitly rehydrated for an old binary. The 0.7 runtime refuses ordinary work until a fresh migration/cutover is completed. |

The steady `sqlite` variant contains only selector version, safe generation
basename, embedded generation ID, and monotonic activation sequence. It never
contains an external/absolute path, content hash, mutable authority revision,
or private domain value. Generation names match one fixed ASCII pattern and are
resolved beneath one fixed directory.

Selector reads reject a symlink/special file, non-UTF-8, oversize content,
duplicate/unknown/missing fields, unknown state/version, unsafe basename, and
generation mismatch. Writes create an exclusive same-directory temporary,
flush and sync it, replace the selector once, sync directory metadata where the
platform supports it, and read it back. A torn or missing selector after restart
fails closed; readback is not a claim of power-loss certification.

### Recoverable cutover sequence

1. Create/validate the `json` selector through explicit migration tooling and
   acquire the exclusive maintenance lease without changing selector state.
2. While `json` remains selected authority, create and verify a complete current
   JSON backup and the #144 exact Preview. Revalidate source bytes and the
   accepted staging candidate.
3. Only after backup, Preview, and candidate verification succeed, replace the
   selector with `transition`. Then move the byte-identical original JSON
   authorities and ancillary migration
   records, on the same filesystem, into the transition's private retained-JSON
   generation. Do not merge, rewrite, or delete them. This removes them from all
   canonical 0.6 production paths and prevents a later old binary from silently
   writing a second authority.
4. If any pre-activation step crashes, `transition` causes recovery-only
   startup. The recovery command uses the recorded digests to restore the whole
   JSON path family or resumes the same transition. It never selects the staged
   SQLite database implicitly.
5. Re-run semantic, identity, schema, integrity, and foreign-key checks; close
   and sync the new generation. The only activation point is one selector
   replacement from `transition` to `sqlite`.
6. Reopen through Runtime Assembly, require the same generation identity, and
   run the fail-closed startup sequence before releasing the lease. A
   post-activation reopen failure remains SQLite recovery; it does not restore
   JSON automatically.

The transition cannot technically stop a deliberately launched unmodified 0.6
binary from ignoring the new lease while maintenance is in progress. The
command and user documentation must require all old processes stopped. After
activation, removing the retained bytes from the legacy default paths prevents
accidental old-binary writes during ordinary operation.

### Fail-closed post-#147 startup

For CLI, web, and Agent Clients, the startup order is fixed:

1. qualify the exact APSW/runtime/artifact/native cell without resolving an
   owner-data path;
2. acquire the shared operation lease;
3. read and validate the selector; ordinary production accepts only `sqlite`;
4. resolve the safe basename inside the generation root and open APSW with
   `READWRITE`, private cache, extended codes, and `NOFOLLOW`, but without
   `CREATE`, URI interpretation, or a non-default VFS;
5. require `readonly("main") is False`, the selected generation ID, application
   ID, supported user version, exact migration registry/digests, schema
   fingerprint, WAL mode, foreign keys, trusted-schema/defensive settings, and
   the #139 integrity policy before the first write;
6. hold the lease for the complete high-level operation and close all APSW
   objects deterministically.

Missing selector/generation, wrong identity, unsupported schema, malformed
registry, read-only fallback, sidecar/recovery failure, corruption, failed
qualification, busy deadline, or unknown exception returns one redacted typed
failure. None may create a file, scan for another generation, choose the newest
timestamp, restore a backup, open JSON, or downgrade a binding automatically.
Fresh installation is an explicit initialization operation; ordinary open never
turns apparent data loss into a new empty authority.

## Exact 0.7 rollback window

The support window begins when the first `sqlite` selector is activated and
continues through the **entire 0.7.x release line**, including release
candidates. A later release may end support only through explicit upgrade and
recovery documentation plus its own review. There is no wall-clock deletion and
no automatic cleanup at the boundary.

Two rollback operations are distinct:

- **SQLite-generation rollback:** first back up the current generation, restore
  the chosen snapshot into a fresh generation, show redacted authority-revision
  and category-count differences, require explicit apply/data-loss acceptance,
  then use one `sqlite` selector replacement. The displaced generation and its
  verified backup remain retained.
- **0.6 binary rollback:** first back up current SQLite, show that the retained
  byte-identical JSON baseline cannot include post-cutover SQLite changes, and
  require explicit data-loss acceptance. Rehydrate the exact JSON family into
  legacy canonical paths and set `legacy_rollback`; 0.7 ordinary startup then
  refuses work. Returning to 0.7 requires a new #144 Preview, import into a new
  generation, and a new cutover. It must never reselect the stale pre-rollback
  SQLite generation.

The rollback catalog records only private generation/backup identities,
activation sequence, revisions, compatibility, hashes, and retention status.
It never authorizes deletion. After the support window, a separate cleanup
Preview enumerates artifact categories and dependencies, proves each candidate
is not selected, pending, or the only verified rollback, and requires explicit
confirmation. Code retirement in #147 is not that cleanup operation.

## Deletion and retention semantics

| Fact or artifact | Required 0.7 behavior |
| --- | --- |
| Matching proposal/failure/Approval/Correction/conflict | Import current typed facts exactly. A legacy revoked entry is absent; do not invent its history. Future explicit revocation may retain a non-authoritative event, but no cascade may delete related publication/Approval evidence. |
| Publication Manifest and Approval outcome | Retain as historical authority/evidence. Active replacement must not cascade-delete the prior Approval facts required by current behavior or recovery. |
| Active Mirror relationship | Import only the active relationship JSON retained. Explicit keep/delete/relink may end or replace the active row, while Publication/Approval/Effect Journal evidence remains. No pre-cutover removal tombstone is invented. |
| Transfer and Batch | Retain terminal and incomplete state needed for explanation, retry, and exact migration. Cleanup is not part of #144–#147. |
| Qualification Draft | Discard and supersession are status/link transitions, not row deletion. Both predecessor and successor remain exact and revisioned. |
| Effect Journal | Never delete an incomplete or uncertain effect as cleanup. Intent/attempt/observation facts remain until a separately specified reconciliation/retention policy can prove safe removal. |
| Operational Event | Non-authoritative and rebuildable. Explicit analytics-history deletion cannot cascade to or change authority. Migration fabricates no historical events. |
| Failed staging file | May be removed only after proving it was created by the current process, was never selected, and is not named by a transition/rollback record. Crash-orphaned stages are quarantined until proven. |
| Original JSON and migration records | Relocate byte-identically into a private retained generation at cutover. Keep for all 0.7.x rollback support; never rewrite or silently delete. |
| Active/superseded SQLite generation | Active is mutable authority. Superseded generations are immutable retained artifacts; restore always creates a fresh generation ID. Cleanup is explicit and cannot select by age alone. |
| Backup/archive | Immutable private historical artifact. It may retain logically deleted bytes. Current-state deletion never reaches backward into backups. |
| JSON writer code/locks/temp-name conventions | Remove from production interfaces in #147. Removing code does not remove user files or automatically unlink legacy lock/temp artifacts. |

Foreign keys must default to `RESTRICT`/explicit service operations for
authority-bearing relationships. Broad `ON DELETE CASCADE` from a convenience
parent to Approval, Effect Journal, Qualification, or migration evidence would
make deletion semantics implicit and fails the contract.

## Native crash and recovery matrix

Tests use only synthetic app-data roots and public/domain readers after restart.
Each named point is exercised both as an injected exception and as a child
process `os._exit()`/forced termination. A test-only APSW VFS derives from the
platform default and injects `FullError`/`IOError` at selected `xWrite`, `xSync`,
`xTruncate`, and `xDelete` calls; production connections continue to reject a
non-default VFS. SQLite itself uses modified VFS implementations for its crash
testing, and APSW exposes VFS and VFSFile overrides for this purpose
([SQLite atomic-commit crash testing](https://www.sqlite.org/atomiccommit.html#testing_atomic_commit_behavior),
[APSW VFS](https://rogerbinns.github.io/apsw/vfs.html)).

| Flow | Mandatory crash/fault points | Evidence after restart |
| --- | --- | --- |
| #144 JSON Preview | lease acquisition; every source read/hash; strict decode; each category import; before/after transaction commit; semantic/identity/integrity checks; source revalidation; token emission; staging cleanup | Every original input byte and presence state is unchanged; selector unchanged; no stage is selectable; result is exact success or a redacted failure. |
| #145 online backup | destination exclusive create/open; each `Backup.step`; busy/locked deadline; `finish`; DELETE-mode conversion; close; integrity/FK/semantic verification; hash; each archive member; archive sync and replace | Active generation remains usable; incomplete destination is rolled back/rejected; final archive name is absent, the prior complete archive, or one complete verified new archive. |
| #145 restore | archive directory/member validation; bounded stream; every identity/security/integrity check; new generation-ID transaction; current backup; before/after selector replacement; reopen | Archive and old generation unchanged; selector names one complete old or new generation; wrong/corrupt input never becomes selected. |
| #146 cutover | `json`→`transition`; current backup; each JSON relocation; staging revalidation; generation sync; temporary selector write/sync; immediately before/after `transition`→`sqlite`; Runtime Assembly reopen | Before final replacement, JSON is the recoverable authority and recovery can restore the whole path family. After it, only the complete SQLite generation is authority. No canonical JSON writer remains reachable. |
| #147 startup | absent/malformed/torn/symlink selector; unsafe basename; missing/symlink/read-only/wrong generation; unsupported migration; corrupt main/WAL; qualification revocation; busy and I/O faults | Stable redacted unavailable/recovery result; no file creation, fallback, generation scan, JSON read/write, or partial client graph. |
| Rollback | current backup; redacted diff; JSON rehydrate; every selector state replacement; forward re-migration | Exactly one explicit mode is selected. Post-cutover state is backed up, retained baseline unchanged, and returning to SQLite uses a new verified generation. |

Run the focused interface, backup, selector, and hard-exit suite on every native
OS/architecture shape claimed by #167: Ubuntu 24.04 x64/ARM64, macOS 15
Intel/Apple silicon, and Windows Server 2025 x64. Run Python 3.10 and 3.14 edge
jobs at minimum on Linux and run the focused Operational Store suite on all 25
qualified Python/OS/architecture cells before #149 freezes 0.7.0rc1. Native
tests must include Windows open-handle/replacement behavior, POSIX stale-open
handle behavior, same-filesystem selector replacement, concurrent WAL readers,
backup source writers, full disk, permission/read-only fallback, and paths with
spaces/non-ASCII characters.

Ordinary CI cannot certify arbitrary power loss or faulty storage hardware. It
can prove the application state machine under hard process exit, VFS I/O faults,
and native filesystem behavior. Reports record only platform/runtime identity,
fault-point name, reason code, and pass/fail—not private paths, SQL, rows, or
generated databases.

## Ready-to-paste issue amendments

These additions preserve the existing issue boundaries and dependency order.

### Amend #144

Add to acceptance criteria:

- [ ] The exact input catalog is frozen: canonical matching versions 1–3,
  publication versions 1–7, Transfer versions 1–6, and version-1 legacy and
  foundation migration facts. Configuration, credentials, reports, source
  files, and archive-only aliases are excluded; an ambiguous canonical/alias
  family fails closed.
- [ ] One exclusive maintenance lease is honored by every current JSON writer;
  Preview records and revalidates each source's presence, identity, bytes, size,
  and SHA-256 before releasing it.
- [ ] JSON parsing rejects duplicate keys, non-finite numbers, unsupported or
  unknown shapes, symlinks, special files, and bounded-resource violations; it
  does not use the permissive initial `MatchCache.load()` path.
- [ ] A versioned typed semantic projection compares all fields, explicit
  absence/null, logical relationships, revisions, ordered duplicates, and every
  incomplete-effect mapping; migration fabricates no authority, Effect Journal
  completion, or Operational Event history.
- [ ] The staging database uses only the qualified APSW runtime, is outside the
  selectable generation root, and cannot be activated by #144. The redacted,
  expiring Preview token binds all source, projection, and target-schema facts.

### Amend #145

Add to acceptance criteria:

- [ ] Backup uses APSW 3.53.4.0's destination-owned Online Backup API with
  distinct qualified connections, bounded step/deadline handling, mandatory
  `finish()`, and destination-derived revision/semantic facts.
- [ ] The archived database is closed, verified, `journal_mode=DELETE`, and has
  no WAL/SHM/hot journal. Restore opens it with no URI/create/symlink following,
  trusted schema off, defensive limits, full integrity, and foreign-key checks.
- [ ] Restore apply never overwrites the active file; it backs up current
  authority, creates a verified new physical generation with a new generation
  ID, and activates only through the shared selector protocol.
- [ ] The manifest/archive has an exact allowlist and resource limits. Reports
  are privacy-redacted, hashes are not described as authenticity, and users are
  told backups may retain logically deleted bytes.
- [ ] SQLite-generation and 0.6 rollback remain supported through all 0.7.x;
  expiry never deletes an artifact. Native hard-exit, APSW VFS-fault, hostile
  archive, and selector tests pass on every claimed platform shape.
- [ ] Update canonical `docs/storage.md` in the same change to replace its
  standard-library `Connection.backup()` example with the destination-owned APSW
  Online Backup mechanism. Research prose does not override canonical storage
  guidance.

### Amend #146

Add to acceptance criteria:

- [ ] The authority selector has explicit `json`, `transition`, `sqlite`, and
  `legacy_rollback` states. Missing/unknown/torn state never means JSON or a new
  empty database; ordinary startup and initialization are separate.
- [ ] Every high-level client operation shares the Runtime Assembly operation
  lease. Apply obtains its exclusive form, drains all clients, and closes all
  APSW objects before changing a selector.
- [ ] Before final activation, byte-identical JSON is moved into a verified
  retained generation outside every legacy runtime default path. A crash in the
  transition state restores the complete JSON family or resumes the exact bound
  transition; it never selects staging.
- [ ] The sole activation point is one same-directory selector replacement from
  `transition` to the complete verified `sqlite` generation. Before it JSON is
  recoverable authority; after it SQLite is sole authority. Reopen failure is
  SQLite recovery, never fallback.
- [ ] Runtime qualification precedes path resolution. Selected opens use APSW
  with no create/URI/non-default VFS, verify writable mode and every identity,
  and fail closed without scanning another generation.
- [ ] Old-version rollback requires a current SQLite backup and explicit
  post-cutover data-loss acknowledgement, selects `legacy_rollback`, and a
  return to 0.7 requires a fresh Preview and new generation.

### Amend #147

Add to acceptance criteria:

- [ ] Ordinary CLI, web, and Agent startup accepts only a valid `sqlite`
  selector and exact qualified generation. Missing/malformed/wrong/read-only/
  corrupt state returns a redacted recovery result and creates or selects
  nothing.
- [ ] Production exports no JSON writer, default JSON authority path, generic
  JSON adapter, hidden fallback, or client-specific selector. Strict versioned
  legacy codecs remain reachable only from explicit migrate/rollback tooling
  for the full 0.7.x support window.
- [ ] Removing writer/lock/temp-path code does not delete user files. Retained
  JSON remains byte-identical outside old runtime paths; legacy lock/temp
  artifacts are private and cleaned only through a separately Previewed action.
- [ ] Interface tests preserve the exact deletion/retention matrix: discarded
  and superseded drafts, Approval/publication history, incomplete Effect
  Journal facts, and rollback artifacts are retained; authority-bearing foreign
  keys do not disappear through broad cascades; Operational Event deletion
  cannot change authority.
- [ ] Native startup/crash tests prove no partial graph, old-generation writer,
  old-binary default-path authority, auto-created empty database, or JSON
  fallback after selector loss.

## Completion evidence required across #144–#147

Each PR must provide its own release-note record but no tag, release, package,
live provider, or owner-data action. Before merge, review the fixed-base diff for
exact scope and prove:

- the upstream ticket commits it depends on are accepted and idle;
- focused interface/conformance tests and the complete offline suite pass;
- APSW is imported only inside the private Operational Store adapter and Python
  `sqlite3` never opens a store;
- native runtime qualification remains fail closed before private-path access;
- repository privacy and built wheel/sdist inspection exclude database families,
  selectors, transition/rollback catalogs, JSON generations, snapshots,
  backups, staging, diagnostics, query exports, reports, and test output;
- every crash point yields one complete recognized authority or an explicit
  recovery state; and
- the issue body and user documentation state the exact 0.7.x retention and
  rollback behavior before code claims completion.

## Primary sources

- DJ Support:
  [ADR-0005](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/docs/adr/0005-use-one-local-transactional-operational-store.md),
  [storage model](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/docs/storage.md),
  [Runtime Assembly](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/djsupport/runtime.py),
  [current JSON adapters](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/djsupport/transfer.py),
  [runtime delivery](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/docs/sqlite-runtime-delivery.md),
  [#144](https://github.com/spontain112/djsupport/issues/144),
  [#145](https://github.com/spontain112/djsupport/issues/145),
  [#146](https://github.com/spontain112/djsupport/issues/146), and
  [#147](https://github.com/spontain112/djsupport/issues/147).
- APSW 3.53.4.0:
  [Backup](https://rogerbinns.github.io/apsw/backup.html),
  [Connection](https://rogerbinns.github.io/apsw/connection.html),
  [exceptions](https://rogerbinns.github.io/apsw/exceptions.html), and
  [VFS](https://rogerbinns.github.io/apsw/vfs.html).
- SQLite:
  [Online Backup API](https://www.sqlite.org/backup.html),
  [WAL](https://www.sqlite.org/wal.html),
  [WAL file lifecycle](https://www.sqlite.org/walformat.html),
  [open flags](https://www.sqlite.org/c3ref/open.html),
  [untrusted database guidance](https://www.sqlite.org/security.html),
  [integrity and secure-delete pragmas](https://www.sqlite.org/pragma.html),
  [`VACUUM INTO`](https://www.sqlite.org/lang_vacuum.html),
  [corruption hazards](https://www.sqlite.org/howtocorrupt.html), and
  [atomic-commit crash testing](https://www.sqlite.org/atomiccommit.html).
- Python:
  [`json`](https://docs.python.org/3.14/library/json.html),
  [`zipfile`](https://docs.python.org/3.14/library/zipfile.html),
  [`os`](https://docs.python.org/3.14/library/os.html), and
  [`hashlib`](https://docs.python.org/3.14/library/hashlib.html).
