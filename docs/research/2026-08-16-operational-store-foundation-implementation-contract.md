# Operational Store foundation implementation contract

**Date:** 2026-08-16

**Code baseline:** `origin/main` at
`3e6ae7f6157364eeedaa2667d2a1deabed9efcee`

**Status:** Implementation-ready research for
[#138](https://github.com/spontain112/djsupport/issues/138) and
[#139](https://github.com/spontain112/djsupport/issues/139). It does not
authorize owner-data access, a production authority switch, a live Spotify call,
or a release. #138 remains blocked by its human gate in #136, and #139 remains
blocked by #138.

**Authority and method:** The merged
[ADR-0005](../adr/0005-use-one-local-transactional-operational-store.md),
the current issues and repository code, and primary APSW, SQLite, and Python
documentation. Statements phrased as “must” are the DJ Support implementation
contract inferred from those sources; they are not descriptions of library
defaults.

**Contract precedence:** The ready-to-paste issue amendments are the proposed
normative execution delta; the preceding sections explain and source that delta.
Once an amendment is accepted into an issue, the issue body is authoritative.
Do not combine conflicting versions—reconcile the amendment first.

## Outcome

Implement #138 and #139 as one deep Operational Store Module with one small
Interface and exactly two conforming Implementations: a strict pure-Python
in-memory Adapter and the private APSW 3.53.4.0 Adapter. Transfer continues to
own policy. Runtime Assembly selects and qualifies an Adapter; callers never
coordinate matching, Transfer, Batch, checkpoint, and event stores themselves.
The Interface contains no SQL, cursor, connection, transaction, path, PRAGMA,
APSW object, or APSW exception.

The first SQLite schema is normalized around selected occurrences and mutable
aggregates. Source order is an explicit zero-based position, duplicate source
tracks are separate occurrence rows, and no provider item, source entity, or
Spotify URI is incorrectly made unique. Every mutable Transfer, Batch, and
matching-knowledge aggregate uses compare-and-swap revisions. A successful
change commits its aggregate rows, compact Operational Events, and one store
commit sequence atomically.

Before any owner-data path is resolved, created, statted, locked, opened, or
logged, the already-merged #166/#167 runtime gate must accept the exact APSW
artifact and embedded SQLite runtime. Every qualified APSW connection uses WAL,
short transactions, a five-second busy timeout, foreign keys, full synchronous
durability, and read-back verification. Unsupported runtime, schema, migration,
integrity, contention, stale revision, I/O, or corruption conditions fail closed
through stable binding-neutral store errors.

Production JSON remains the sole authority throughout #138 and #139. These
issues create no production selector, no dual write, no JSON fallback, and no
cutover. The SQLite path is a non-authoritative Preview implementation until the
later migration and cutover issues explicitly verify and activate it
([#138](https://github.com/spontain112/djsupport/issues/138),
[ADR-0005](../adr/0005-use-one-local-transactional-operational-store.md)).

## Explicit supersession

This note supersedes every standard-library-shaped implementation mechanism in
the earlier
[concurrency and durability research](2026-08-16-sqlite-concurrency-durability-contract.md),
including its connection example, transaction-control calls, cursor row-count
mechanism, backup call direction, exception hierarchy, runtime-version probe,
and illustrative aggregate `state_json` update. Preserve that note's behavioral
outcomes—WAL, bounded contention, optimistic concurrency, integrity, crash
atomicity, migration discipline, and scale—but implement them only through APSW
3.53.4.0 and the normalized schema below.

This note also supersedes the conditional language in the
[APSW integration research](2026-08-16-apsw-operational-store-integration-contract.md):
APSW 3.53.4.0 is now accepted, pinned, delivered, and qualified by the merged
#165–#167 work and
[package metadata](../../pyproject.toml). Python's standard `sqlite3` must not
open, inspect, migrate, back up, restore, test, or otherwise touch an Operational
Store. It is not a fallback or a second test oracle. APSW documents that it is
not DB-API compatible and that using different SQLite libraries against the same
database in one process can be unsafe
([APSW comparison](https://rogerbinns.github.io/apsw/pysqlite.html)).

## 1. Current repository gap

The merged Operational Store package currently owns runtime probing,
qualification, and delivery only. Runtime Assembly still constructs three file
Implementations: `MatchCache`, `FileTransferStorage`, and
`FilePublicationStorage`. `FileTransferStorage` mutates caller revisions and
rewrites one JSON document under a platform lock; `MatchCache` has no aggregate
revision; publication state has no general optimistic revision
([Runtime Assembly](../../djsupport/runtime.py),
[Transfer storage](../../djsupport/transfer.py),
[matching cache](../../djsupport/cache.py)).

The domain already carries the right occurrence primitive:
`SourceOccurrence(occurrence_id, position, facts)`. `SourceTrackFacts` includes
ordered artists and remixers, nullable nested facts, tri-state availability,
and explicitly opaque evidence. `TransferState` and `BatchState` already carry
integer revisions, but their JSON-shaped collections are not a normalized
transactional model
([source facts](../../djsupport/source_facts.py),
[Transfer model](../../djsupport/transfer.py)).

#138 must therefore add the storage Module and one non-authoritative end-to-end
Preview path; it must not merely wrap the existing three file Implementations or
put their whole documents into SQLite blobs. #139 then proves the same Module's
multi-connection, optimistic-write, integrity, and crash behavior.

## 2. One deep Module and one Interface

### Vocabulary and ownership

“Operational Store” is one Module. `OperationalStore` is its Interface. The
pure-Python in-memory store and APSW store are Implementations and Adapters.
Runtime qualification, the connection factory, schema registry, codecs,
integrity verifier, and lifecycle lease are private Seams inside the Module.
This gives the Module Depth: a small set of domain-named operations hides schema,
migrations, connection setup, transactions, locks, result codes, and recovery.
Transfer policy stays local to Transfer; persistence mechanics stay local to the
Operational Store.

### Normative Interface

The #138 Interface begins with two domain-named operations (names may change
during implementation, semantics may not):

```python
class OperationalStore(Protocol):
    def persist_transfer_preview(
        self, intent: PersistTransferPreview
    ) -> PersistTransferPreviewReceipt: ...

    def resume_transfer_preview(
        self, request: ResumeTransferPreview
    ) -> TransferPreviewSnapshot: ...
```

The associated immutable values are a closed, typed vocabulary:

- `PersistTransferPreview` carries one complete, validated Preview intent,
  expected aggregate revisions, an idempotency identity where the domain
  supplies one, and zero or more compact event facts. It describes domain intent,
  not tables, rows, or transaction steps.
- `PersistTransferPreviewReceipt` returns the durable store commit sequence and
  resulting aggregate revisions. It is created inside the private unit of work
  but returned only after the outer transaction has committed successfully.
- `ResumeTransferPreview` names one exact Transfer identity; it cannot contain
  arbitrary SQL, table names, paths, predicates, or callbacks.
- `TransferPreviewSnapshot` returns immutable domain facts plus the revision of
  each mutable aggregate read and the observed store commit sequence.

The persist operation may update a Transfer, its Batch, matching knowledge,
checkpoints, and compact events together. This is the Leverage the current
separate storage Interfaces cannot provide. A private typed unit-of-work plan may
compose those mutations inside the Module, but it is never exported as a generic
`commit(change)` command interpreter. Later issues extend the same Interface with
reviewed domain-named operations for Snapshot publication, Approval,
Qualification application, and Mirror maintenance.

The Interface deliberately has no `begin`, `execute`, `cursor`, `flush`,
`checkpoint_wal`, `migrate`, `path`, or `connection` member. No caller controls a
transaction. No persistence Adapter is passed separately to Transfer. Runtime
Assembly may expose a context-managed runtime session, but the selected store is
the one persistence Interface in that session.

### Error Interface

Both Implementations return the same stable, path-free errors:

| Error | Meaning | Caller outcome |
| --- | --- | --- |
| `StoreRuntimeUnavailable` | Exact runtime or artifact is not qualified | Stop before path access; no fallback |
| `StoreSchemaUnsupported` | Application ID, migration registry, schema fingerprint, or version is unknown/newer/drifted | Stop and direct repair/upgrade |
| `StoreIntegrityError` | SQLite, foreign-key, or domain integrity failed | Stop and direct restore/repair |
| `StoreLeaseBusy` | A shared operation or exclusive maintenance lease was not acquired in its bounded window | End this attempt; retry only as a new operation |
| `StoreBusy` | SQLite could not acquire its lock within 5,000 ms | End this attempt; retry only with a fresh connection and fresh facts |
| `StaleRevision` | An expected aggregate revision no longer matches | Reload before deciding whether to retry |
| `EntityMissing` | A required aggregate is absent | Do not reinterpret it as stale or create implicitly |
| `StoreInvariantError` | Typed input or persisted relational invariant is invalid | Fail closed; this is not contention |
| `StoreUnavailable` | Read-only, full disk, I/O, permission, open, or other storage failure | Fail closed; retain the private chained cause |

Messages and diagnostics include only stable reason codes and public runtime or
schema versions. They exclude paths, database names, SQL bindings, source facts,
account identifiers, playlist identifiers, credentials, and raw APSW error text.
The Adapter may chain the private APSW cause for local debugging.

### Binding containment and file layout

Only `djsupport/operational_store/apsw.py` may import or dynamically load APSW.
Extend the existing architecture test so every other production module remains
binding-neutral. A reasonable Locality-preserving layout is:

```text
djsupport/operational_store/
  __init__.py        binding-neutral exports only
  interface.py       OperationalStore and immutable request/result/error values
  model.py           closed snapshot and mutation vocabulary
  memory.py          pure-Python conforming Implementation
  schema.py          immutable migration registry and schema fingerprints
  lease.py           cross-platform shared/exclusive lifecycle lease
  apsw.py            sole APSW import, runtime probe, connection factory, Adapter
```

Do not create an ORM, a repository per table, or Adapter-specific abstractions
for callers. The table layout is private to the APSW Implementation.

### Private-path permission contract

After runtime qualification and before opening the store, verify that the
application-data directory and every existing database, WAL, SHM, lease, backup,
and staging member are regular, non-symlink objects owned by and accessible only
to the current OS account. New POSIX directories use mode `0700` and files use
mode `0600`; creation must not depend on a permissive process umask. On Windows,
use the platform ACL surface to require an equivalent current-user-only boundary
and reject broadly readable or writable inheritance. A platform on which that
boundary cannot be established fails closed with a path-free `StoreUnavailable`.

Permission and hostile-path tests run on native Linux, macOS, and Windows. They
cover permissive parent defaults, pre-existing symlinks/special files, foreign
ownership where the platform permits creating it, and an ACL/mode that grants
another principal access. Public diagnostics report only a stable reason code.

## 3. Two-Implementation conformance Seam

### Pure-Python in-memory Implementation

The in-memory Adapter is a strict behavioral peer, not a permissive fake and not
an APSW `:memory:` database. It must:

1. keep a normalized internal state with the same identities, positions,
   revision rules, constraints, and typed errors;
2. provide two independent handles over one shared backend for concurrency tests;
3. serialize each write operation with a private lock, validate every expected revision,
   apply mutations to a private copy, and publish the copy only after all
   validations succeed;
4. leave the prior state and every caller input unchanged on injected failure;
5. increment the store commit sequence exactly once per successful domain write
   operation, not once per row; and
6. return new immutable snapshots and receipts rather than shared mutable values.

The in-memory Adapter has no filesystem, WAL, migration, or APSW behavior. Those
are Adapter lifecycle tests, not Interface conformance. It still exposes the
current logical schema version in snapshots so semantic fixtures compare cleanly.

### Shared conformance suite

Run every fixture once against `MemoryOperationalStore` and once against a fresh
qualified `ApswOperationalStore`. Compare canonical domain snapshots and typed
outcomes, never private row layouts. The suite must cover:

- empty/missing entities and one complete Preview;
- exact zero-based Source Occurrence order;
- adjacent and non-adjacent duplicates with identical provider and Spotify facts;
- `facts=None`, nullable nested facts, tri-state booleans, empty repeated facts,
  Unicode, and canonical opaque evidence;
- matched proposals, failures, Batch/Transfer progress, checkpoints, and compact
  events;
- new revision `0` becoming durable revision `1`, then every successful update
  advancing exactly once;
- atomic multi-aggregate success and rollback on any stale member;
- two handles reading revision *n*, one winning, and the other receiving
  `StaleRevision` without hidden retry;
- fault injection before validation, between every mutation family, and before
  publication of a receipt; and
- immutable inputs and deterministic snapshots after success or failure.

Adapter-specific tests then add runtime-before-path, schema, WAL, busy,
multi-process, integrity, reopen, and crash cases.

## 4. Runtime-before-path gate and lifecycle lease

### Required startup order

The merged `SQLiteRuntimeQualification.run_qualified()` is the only entry to the
APSW-backed store. The order is normative:

1. Load the packaged runtime and delivery contracts and probe APSW's public
   runtime facts. Do not evaluate a default application-data path first.
2. Classify the exact binding, extension digest, embedded SQLite identity,
   Python ABI, OS, and architecture.
3. On any non-qualified result, raise `StoreRuntimeUnavailable` with a stable
   path-free reason and stop.
4. Inside the qualified callback only, resolve the private application-data
   directory, derive the candidate database/lease names, and acquire the lease.
5. Only then may code stat, create, open, configure, migrate, or check the
   database family.

The path resolver must be a thunk evaluated inside the qualified callback. A
precomputed `Path`, `RuntimePaths.defaults()` call that performs I/O, directory
creation, existence probe, log statement, or lease-file open before
qualification violates the gate. A spy test must make every path primitive fail
if invoked before the classifier returns qualified
([runtime qualification](../../djsupport/operational_store/qualification.py),
[#166](https://github.com/spontain112/djsupport/issues/166)).

### One lifecycle lease

Add one private, cross-platform `OperationalStoreLease` beside the database
family after qualification. It has two modes:

- a shared operation lease covers one complete CLI, web, or Agent Client command;
  multiple clients may hold it, including while bounded external work occurs;
- an exclusive maintenance lease covers first bootstrap, migrations, full
  integrity/repair, backup/restore, and later cutover operations; it starts only
  after existing shared operations drain.

The lease is not a database transaction. Every store operation still opens and
closes a short SQLite unit of work, including when the shared lease is held
across a Spotify call. SQLite revisions arbitrate same-aggregate writes;
the lease only prevents lifecycle replacement or migration underneath active
operations. Account publishing guards remain separate domain guards and do not
replace this store lease.

Acquisition is bounded and returns `StoreLeaseBusy`; it never waits forever.
Process death releases the OS lock. POSIX and Windows Implementations must share
one test contract, use a fixed lock byte/range, and never delete or replace a
lock file while contenders may exist. The lease path, as well as the database,
WAL, and SHM, is private user data and must be ignored, excluded from packages,
and absent from diagnostics. #138 introduces the Seam; later migration/cutover
issues reuse it rather than inventing another quiescence mechanism.

#138/#139 must not create or replace the future production generation selector.
The non-authoritative Preview database records a stable `generation_id` in its
metadata, but JSON remains selected production authority.

## 5. Normalized schema v1

### Global rules

All application tables are `STRICT`; use `WITHOUT ROWID` for composite-key tables
where it improves explicit identity. SQLite STRICT tables enforce declared types
and make integrity checks validate stored types
([SQLite STRICT tables](https://sqlite.org/stricttables.html)). Every identifier,
ordinal, status, and revision is `NOT NULL`; use `CHECK` constraints for
non-negative ordinals, revision bounds, boolean values, and closed status codes.
Foreign keys are explicit and default to `ON DELETE RESTRICT`. Deletion is a
typed domain mutation, never an incidental cascade from a parent row.

No authority-bearing aggregate is stored as `state_json`, pickled Python, a
generic key/value table, or a document blob. Repeated and ordered domain values
are child rows with explicit ordinals. A canonical JSON codec is allowed only
for fields the domain explicitly defines as opaque non-authoritative evidence
(`raw_evidence`, artwork, opaque price evidence, and bounded event facts). That
codec is versioned, UTF-8, key-sorted, compact, rejects NaN/infinity and
non-JSON values, and is exercised identically on Python 3.10–3.14.

### Required table families

| Table family | Required identity and facts | Required constraints |
| --- | --- | --- |
| `store_metadata` | Singleton row, generation ID, logical schema version, store commit sequence, created-at fact | Singleton key; non-negative sequence; generation immutable |
| `schema_migrations` | Version, stable name, SHA-256 of canonical migration bytes | Version primary key, name unique, contiguous immutable prefix |
| `source_selections` | Selection ID, source kind, source reference/digest, display facts, creation fact | Stable selection ID; no uniqueness rule that collapses occurrence content |
| `source_occurrences` | Selection ID, occurrence ID, zero-based position, nullable-facts marker | Primary key `(selection_id, occurrence_id)` and unique `(selection_id, position)`; contiguous positions verified by domain integrity |
| `source_occurrence_facts` | One-to-zero/one typed fact row for an occurrence: provider/item identity, title/URL, durations, dates, availability, commerce, preview, musical and release facts | Same occurrence key; nullable fields preserve absence; tri-state booleans are NULL/0/1 |
| `source_occurrence_entities` | Occurrence, role (`artist`, `remixer`, `genre`, `subgenre`, `release`, `label`), role ordinal, provider entity facts | Composite key including role/ordinal; ordered artists/remixers; singleton roles limited to ordinal 0 |
| `source_occurrence_evidence` | Occurrence, evidence kind, codec version, canonical opaque bytes/digest | Only explicitly opaque, non-authoritative facts; bounded size; no path-bearing evidence |
| `transfers` | Transfer ID, source/account/request scalar facts, status, timestamps, progress scalar facts, selection ID, revision | Revision at least 1 when durable; status/check constraints; selection FK |
| `transfer_proposals` | Transfer, occurrence, proposal ordinal, candidate/public review facts and score reasons | Occurrence FK; explicit proposal order; proposal remains non-authoritative |
| `transfer_failures` | Transfer, occurrence, failure kind and privacy-safe code | Occurrence FK; no raw exception text |
| `transfer_checkpoints` | Transfer, checkpoint kind, ordinal, typed progress facts and digest | Unique per transfer/kind/ordinal; no generic mutable checkpoint document |
| `batches` | Batch ID, scalar request/progress facts, status, revision | Revision at least 1; status/check constraints |
| `batch_transfers` | Batch ID, transfer ID, zero-based position and phase/outcome facts | Unique batch position and transfer membership; order explicit |
| `matching_entities` | Stable normalized lookup identity, current result facts, revision | Lookup identity unique only at the matching-entity level; revision at least 1 |
| `matching_observations` | Matching entity, observation identity/order, proposal/failure/availability facts | Append facts without overwriting an unrelated entity; no URI-wide uniqueness |
| `operational_events` | Store commit sequence, event ordinal, category/code, optional aggregate identity and bounded redacted facts | Primary key `(commit_sequence, event_ordinal)`; append-only in ordinary operation; no authority row cascades from event deletion |

The exact DDL is part of #138's review, but it must implement these identities and
constraints. If a current JSON field has no stable typed representation, #138
must narrow its Preview vocabulary or add a reviewed typed table; it must not
hide the field inside a generic aggregate blob.

### Source order and duplicates

`position` is zero based and, for a selection of length *n*, the set must be
exactly `0..n-1`. Reads always use an explicit `ORDER BY position`; insertion or
`RETURNING` order is never treated as domain order. SQLite documents that rows
from `RETURNING` have arbitrary order
([SQLite RETURNING](https://sqlite.org/lang_returning.html)).

Two occurrences with identical provider item ID, source entity ID, source URL,
title, artists, matching key, or Spotify proposal remain two rows with distinct
occurrence IDs and positions. None of those content columns is unique. Facts are
stored per occurrence rather than content-deduplicated in v1, avoiding accidental
identity collapse. Exact round-trip tests include duplicates at positions 0/1,
0/last, and three repeated occurrences separated by other tracks.

## 6. Immutable migration registry

The registry is a tuple of code-owned values:

```python
@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sha256: str
    statements: tuple[str, ...]
    schema_fingerprint: str
```

Canonical migration bytes are the UTF-8 encoding of every exact statement in
order, with LF line endings and one trailing LF per statement. The committed
digest and expected post-migration fingerprint are literals reviewed with the
DDL. Never calculate the expected digest from mutable database content at
runtime.

Bootstrap/migration runs only after runtime qualification and under the exclusive
maintenance lease. The Adapter must:

1. require an outermost transaction state, set
   `connection.transaction_mode = "IMMEDIATE"`, and enter one APSW connection
   context;
2. re-read `application_id`, `user_version`, `schema_migrations`, and the schema
   fingerprint after acquiring the writer transaction;
3. reject a foreign application ID, a newer version, a gap, duplicate, name or
   digest mismatch, changed historical migration, unexpected schema object, or
   `user_version`/registry disagreement;
4. execute each migration statement separately with bindings where applicable
   and fully consume its cursor; multiple statements in one APSW execute string
   are prohibited even though APSW supports them;
5. insert the migration registry row and update `user_version` in the same
   transaction after that migration's DDL/data steps;
6. verify the resulting schema fingerprint and contiguous registry before the
   transaction exits; and
7. return only after the APSW context has committed.

Schema v1 uses application ID `0x444A5350` (`1145721680`, ASCII `DJSP`). It is a
signed 32-bit value absent from SQLite's current assigned-ID list. Keep it
immutable and test it on every open. SQLite reserves the application header field
for exactly this file-identity purpose; `user_version` is application-owned
([SQLite application and user version](https://sqlite.org/pragma.html#pragma_application_id),
[SQLite assigned application IDs](https://sqlite.org/src/doc/trunk/magic.txt)).

APSW's connection context starts a transaction, commits on clean exit, rolls back
on exception, and uses savepoints for nested contexts. The factory must ensure
migration owns the outermost context and set its transaction mode explicitly
([APSW connection context](https://rogerbinns.github.io/apsw/connection.html#apsw.Connection.__enter__),
[APSW `transaction_mode`](https://rogerbinns.github.io/apsw/connection.html#apsw.Connection.transaction_mode)).

#138 must prove fresh bootstrap, idempotent reopen, every supported registry
prefix, concurrent bootstrap, statement-by-statement injected failure, digest
drift, version gap, newer schema, foreign application ID, and schema tampering.
A crash or exception exposes either the complete prior prefix or complete next
prefix. Migration of a non-empty production authority and its backup remain in
the later migration/backup issues; #138 tests only synthetic Preview databases.

## 7. APSW connection and transaction contract

### Open modes

Use one short-lived connection per unit of work. Never share a connection or
cursor simultaneously across threads, processes, or a fork. APSW permits
multiple connections across processes, while its cursors on one connection are
not isolated from one another; the stricter project rule produces one portable
execution model
([APSW connections](https://rogerbinns.github.io/apsw/connection.html),
[APSW cursors](https://rogerbinns.github.io/apsw/cursor.html)).

After qualification and exclusive lease:

- fresh bootstrap opens one uniquely named absent file with
  `SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_PRIVATECACHE |
  SQLITE_OPEN_EXRESCODE | SQLITE_OPEN_NOFOLLOW`;
- every ordinary/migration reopen omits `SQLITE_OPEN_CREATE`, does not use URI
  mode, and verifies `connection.readonly("main") is False`;
- no `ATTACH`, extension loading, shared cache, network filesystem, or user SQL
  is allowed.

SQLite WAL requires all processes to be on the same host and uses `-wal` and
`-shm` sidecars; it is not supported on a network filesystem
([SQLite WAL](https://sqlite.org/wal.html)). The application-data resolver must
reject known network locations or fail closed when locality cannot be established
for an authority-capable store.

### Per-connection invariants

On every ordinary open, before domain SQL, configure and read back:

| Invariant | Required value |
| --- | --- |
| `foreign_keys` | `ON` |
| `journal_mode` | `WAL` (set during bootstrap, verify on every open) |
| `synchronous` | `FULL` |
| `busy_timeout` | `5000` ms via `set_busy_timeout(5000)`, then read back |
| `wal_autocheckpoint` | `1000` pages |
| `trusted_schema` | `OFF` |
| `read_uncommitted` | `OFF` |
| `locking_mode` | `NORMAL` |
| `application_id` | `0x444A5350` (`1145721680`, ASCII `DJSP`) |
| `user_version` | exact latest migration version |

Also enable SQLite defensive mode and keep extension loading disabled through
APSW's connection configuration surface. Do not call the process-global APSW
recommended-hook bundle: its defaults and global hooks are not the reviewed DJ
Support connection contract. SQLite encourages disabling trusted schema on every
connection, and APSW's explicit PRAGMA method returns the effective value
([SQLite `trusted_schema`](https://sqlite.org/pragma.html#pragma_trusted_schema),
[APSW PRAGMA method](https://rogerbinns.github.io/apsw/connection.html#apsw.Connection.pragma),
[APSW best practice](https://rogerbinns.github.io/apsw/bestpractice.html)).

Any set/read mismatch closes the connection and raises a typed store error.
Never silently accept rollback-journal mode, a shorter durability setting, a
replaced busy handler, or a read-only fallback.

Fresh bootstrap is the only pre-schema exception to the final identity rows in
that table. Under the exclusive maintenance lease, the create path first proves
the newly created file has `application_id=0`, `user_version=0`, and no user
schema objects; it then configures the connection and installs schema v1,
application ID, migration registry, and `user_version` atomically. It closes the
bootstrap connection and reopens through the ordinary path, which must satisfy
the complete table before any Preview operation. A non-empty or non-zero
pre-bootstrap file is rejected rather than adopted.

### Read and write units

A read-oriented domain operation starts a short read transaction only when
multiple queries must share one snapshot, fully consumes every result, maps rows
to immutable domain values, and exits before returning. WAL gives each read
transaction a stable snapshot while allowing a writer to proceed
([SQLite isolation](https://sqlite.org/isolation.html)).

A write-oriented domain operation sets `transaction_mode = "IMMEDIATE"` and
enters one outer APSW connection context. It re-reads all expected revisions
after acquiring write intent, applies its complete private unit-of-work plan,
increments the store commit sequence, inserts its events, verifies mutation
counts, and exits. All remote reads,
matching computation, user interaction, and Spotify calls occur before or after
this context. `Connection.txn_state("main")` must report no transaction at every
external call Seam and before the connection closes
([APSW transaction state](https://rogerbinns.github.io/apsw/connection.html#apsw.Connection.txn_state)).

SQLite documents that escalating an old WAL read snapshot can fail with
`SQLITE_BUSY_SNAPSHOT`; starting a known read-then-write operation with
`BEGIN IMMEDIATE` prevents that history fork
([SQLite isolation](https://sqlite.org/isolation.html)). No hidden retry may
replay an operation intent against newer facts.

## 8. Revisions and atomic commits

Revisions are aggregate-scoped opaque concurrency tokens represented as
non-negative integers at the Interface:

- a new caller value has revision `0` and means “expected absent”;
- initial durable insertion returns revision `1`;
- each successful mutation of that aggregate increments it exactly once;
- an unchanged aggregate does not advance merely because another aggregate
  commits; and
- the store commit sequence advances exactly once for every successful
  domain write operation and never for a rejected or rolled-back operation.

Mutable v1 scopes are Transfer, Batch, and matching-knowledge entity. Child rows
take their concurrency scope from their owning aggregate. Later schema issues
add publication, Approval, Qualification, Mirror, and Effect Journal scopes; #138
must not pre-empt their domain decisions.

Use APSW iteration over a revision-qualified statement, not a DB-API row count:

```sql
UPDATE transfers
   SET status = ?, next_track_index = ?, revision = revision + 1
 WHERE transfer_id = ? AND revision = ?
 RETURNING revision;
```

Fully consume the result and require exactly one row. Zero rows triggers an
existence/revision check inside the same `BEGIN IMMEDIATE` transaction so
`EntityMissing` and `StaleRevision` remain distinct; more than one is an
invariant failure. Insert with expected revision `0`; a uniqueness conflict is
stale/existing, never an implicit overwrite. SQLite `RETURNING` reports values
from the modifying statement but the transaction is not durable until commit,
so the Adapter returns the receipt only after successful context exit
([SQLite RETURNING](https://sqlite.org/lang_returning.html),
[APSW execution model](https://rogerbinns.github.io/apsw/execution.html)).

For a multi-aggregate domain operation, every compare-and-swap must succeed or the
entire transaction rolls back, including child replacement, checkpoints,
events, and store sequence. Never mutate the caller's revision in place; return
new values in the immutable operation receipt.

## 9. WAL, busy, and result-code translation

WAL allows readers and one writer to proceed concurrently, but still permits
only one writer. A long read can delay checkpoint progress; therefore all
snapshots and cursors are bounded and fully consumed. Keep the default-sized
1,000-page automatic passive checkpoint and do not add a hidden checkpoint
scheduler or rollback-journal fallback in #138/#139
([SQLite WAL concurrency](https://sqlite.org/wal.html#concurrency),
[SQLite automatic checkpoint](https://sqlite.org/wal.html#automatic_checkpoint)).

Each connection installs exactly one 5,000 ms busy timeout. After it expires,
translate `apsw.BusyError` by extended result code:

- plain `SQLITE_BUSY` becomes `StoreBusy`;
- `SQLITE_BUSY_SNAPSHOT` becomes a stale-snapshot outcome requiring a fresh
  unit of work;
- a revision mismatch remains `StaleRevision`, never `StoreBusy`;
- `SQLITE_LOCKED` with private cache indicates Implementation misuse and becomes
  `StoreInvariantError`;
- constraint errors become the specific revision/invariant outcome after local
  classification;
- corrupt/not-a-database becomes `StoreIntegrityError`; and
- read-only, full, I/O, permission, cannot-open, and unknown storage errors become
  `StoreUnavailable` unless a more specific fail-closed type applies.

APSW exposes both primary and extended result codes on its exceptions and has a
specific busy-timeout method
([APSW errors](https://rogerbinns.github.io/apsw/exceptions.html),
[APSW busy timeout](https://rogerbinns.github.io/apsw/connection.html#apsw.Connection.set_busy_timeout),
[SQLite result codes](https://sqlite.org/rescode.html)). Translation tests use
the numeric APSW/SQLite constants, not error-message matching.

There is no Adapter-level retry loop. A CLI/web/Agent caller may offer a later
retry only by acquiring a new shared lease, opening a new connection, loading a
new snapshot, and rebuilding the domain decision. Tests shorten the timeout only
through an injected private connection policy and coordinate contenders with
process events, never timing sleeps.

## 10. Integrity and fail-closed startup

Integrity is layered:

| Boundary | Required checks |
| --- | --- |
| Every connection | Runtime proof, connection invariant read-back, application ID, exact registry/user version, expected schema fingerprint |
| First open in each process and every crash reopen | `PRAGMA quick_check`, `PRAGMA foreign_key_check`, plus domain integrity queries |
| Fresh bootstrap and after each migration | Full `PRAGMA integrity_check`, foreign-key check, registry/fingerprint, and domain invariants |
| Exclusive maintenance, backup/restore, and later cutover | Full integrity, foreign-key, normalized counts, revisions, order, and canonical domain digest |

`integrity_check` returns one `ok` row on success but does not find foreign-key
errors; `foreign_key_check` is separately mandatory. `quick_check` omits some
index/uniqueness work in exchange for linear-time checking
([SQLite integrity checks](https://sqlite.org/pragma.html#pragma_integrity_check),
[SQLite foreign keys](https://sqlite.org/foreignkeys.html)).

Domain integrity queries require, at minimum:

- contiguous occurrence and Batch positions;
- no orphan or cross-selection proposal/checkpoint rows;
- no durable mutable revision below 1;
- every event ordinal contiguous within its commit sequence;
- every event aggregate reference valid without making events authority;
- metadata commit sequence at least the largest event sequence;
- exactly one metadata row and one exact migration prefix; and
- canonical Interface re-materialization that passes domain constructors and
  status/identity invariants.

Any failure makes the Adapter unavailable. It does not create a replacement,
continue with partial tables, downgrade, delete sidecars, fall back to JSON, or
return partial snapshots. Since JSON is still production authority in #138/#139,
the existing product path remains unchanged; the failed SQLite Preview path is
reported unavailable rather than silently substituted.

## 11. Deterministic crash contract

Every committed domain write operation has exactly two valid post-crash outcomes: the
complete previous snapshot or the complete next snapshot. “Complete next”
includes every changed aggregate revision, child row, checkpoint, event, and the
one new store commit sequence. Any mix is a failure.

Use three complementary fault Seams:

1. ordinary Python exceptions at before-BEGIN, after-BEGIN, after each mutation
   family, before sequence/event retention, before context exit, and after context
   exit but before receipt mapping;
2. a child process that calls `os._exit()` at the same phases, leaving normal
   cleanup and rollback handlers unrun; and
3. a test-only derived APSW VFS that delegates to the platform VFS but injects
   typed failures from WAL/database `xWrite`, `xSync`, `xTruncate`, and `xDelete`
   operations around commit/checkpoint phases.

APSW exposes VFS/VFSFile inheritance specifically to augment file operations and
requires VFS routines to report errors by raising exceptions
([APSW VFS](https://rogerbinns.github.io/apsw/vfs.html)). Python documents
`os._exit()` as immediate process exit without cleanup handlers
([Python `os._exit`](https://docs.python.org/3.10/library/os.html#os._exit)).

Each fault case starts from a copied synthetic seed in its own temporary
application-data directory, uses a unique VFS name, terminates the writer, then
reopens through the public `OperationalStore.resume_transfer_preview()` Interface
in a new process using the normal VFS. The verifier runs runtime qualification,
connection read-back, full integrity, foreign-key and domain checks, then compares
a canonical semantic digest to the old and new expected snapshots. It retains
the synthetic database/WAL/SHM family only inside the ephemeral runner workspace
for that test and deletes it before job completion. It uploads no workflow
artifact and prints only privacy-redacted synthetic outcome facts.

Migration crash tests apply the same phases to every statement and registry
write. The observed schema/registry must be the complete prior or next migration
prefix. Busy and hard-exit tests use process events/pipes to prove exact phase;
they do not infer it from sleeps or log timing.

## 12. Scale and cross-platform verification matrix

The merged delivery catalog claims 25 exact native cells: five Python minors
(3.10–3.14) on Ubuntu 24.04 x86-64, Ubuntu 24.04 arm64, macOS 15 Intel, macOS 15
Apple silicon, and Windows Server 2025 x64
([artifact catalog](../../djsupport/contracts/apsw-runtime-artifacts.v1.json),
[#167](https://github.com/spontain112/djsupport/issues/167)). Store support must
not exceed the cells that run the required store evidence.

| Suite | Required cells | Required evidence |
| --- | --- | --- |
| Pure Interface conformance | Every ordinary Python 3.10–3.14 CI cell | Same snapshots, receipts, typed failures for memory and APSW Implementations |
| Qualified APSW foundation | All 25 catalog cells | Gate-before-path, bootstrap/reopen, PRAGMA read-back, schema registry/fingerprint, exact Preview round trip, CAS win/loss, WAL persistence, quick/FK checks |
| Native concurrency and hard exit | All 25 catalog cells | Two independent processes/connections, distinct writes, same-aggregate stale write, bounded busy, before/during/after-commit hard exit, old-or-new digest |
| VFS fault campaign | At least one exact Python patch on each of the five native OS/architecture shapes, plus Python 3.10 and 3.14 on Ubuntu x86-64 | Deterministic WAL/database write/sync/truncate/delete failures and verified reopen |
| #138 scale | Python 3.10 and 3.14 on Ubuntu x86-64, plus one macOS Apple-silicon and one Windows x64 cell | 10,000 Transfers, exactly 100,000 occurrences, deliberate adjacent/non-adjacent duplicates, matching/checkpoint/event facts, restart and semantic digest |
| Migration prefixes | All 25 for clean bootstrap/reopen; full fault matrix on the VFS campaign cells | Every prefix, idempotence, concurrent starter, drift/gap/newer/foreign/tampered failures |

The 100,000-occurrence fixture is arithmetic and synthetic: ten ordered
occurrences for each of 10,000 Transfers, deterministic IDs, positions, nullable
facts, and duplicate patterns. Assertions use aggregate counts, ordered identity
digests, revision sums, event/checkpoint categories, and sampled complete
snapshots rather than retaining all mapped domain objects at once. Record elapsed
time, peak memory, database/WAL size, and checkpoint progress as non-secret CI
metrics, but make correctness—not an unresearched timing threshold—the #138
acceptance gate.

No required row may skip, xfail, continue on error, emulate another architecture,
or silently select a different APSW artifact. A failed runtime classifier means
the persistence suite fails before path access. Release qualification must rerun
the focused foundation suite against the exact release-candidate artifact and
commit.

## 13. Rejected implementations

| Reject | Why | Required replacement |
| --- | --- | --- |
| One wrapper over the existing three JSON stores | Callers still coordinate authority and no cross-aggregate atomicity exists | One `OperationalStore` Interface and one private atomic unit of work per domain write operation |
| Whole `TransferState`/`BatchState`/cache JSON blobs | Hides identity, ordering, constraints, revisions, and migrations | Normalized aggregate and ordered child tables |
| Content-deduplicated source tracks | Collapses duplicate selected occurrences | Occurrence identity plus explicit position; content not unique |
| Standard-library SQLite connection in production or tests | Violates accepted sole binding and risks mixed SQLite libraries | APSW 3.53.4.0 only; pure-Python memory Adapter for independent conformance |
| Path resolution before qualification | Unsupported native code can touch private owner state | Lazy path thunk inside `run_qualified()` |
| APSW connection/cursor/error exposed to Transfer | Leaks mechanism and makes callers coordinate transactions | Binding-neutral domain intents, snapshots, receipts, and store errors |
| DB-API row counts or last-insert state | Not the selected mechanism and can obscure exact mutation identity | `RETURNING`, fully consumed and cardinality checked |
| Deferred read then write for authority mutation | Can attempt to fork an old WAL snapshot | Short `IMMEDIATE` write unit and in-transaction revision re-read |
| Hidden busy or stale retry | Replays a decision against new facts | Typed outcome, fresh connection, reload-before-retry |
| Database transaction across Spotify | Holds writer lock across uncertain network work | Commit local intent/checkpoint, close transaction, call externally, commit observation later |
| File-copy backup or deleting WAL/SHM | Can separate one database family at inconsistent points | Later APSW Online Backup workflow; preserve sidecars during active recovery |
| Production selector or dual write in #138/#139 | Exceeds the issue authority scope | Non-authoritative SQLite Preview only; later explicit migration/cutover |

## 14. Ready-to-paste issue amendments

### Amendment for #138

Append the following after the existing acceptance criteria:

```markdown
## Foundation implementation contract (2026-08-16)

The implementation follows
[`docs/research/2026-08-16-operational-store-foundation-implementation-contract.md`](https://github.com/spontain112/djsupport/blob/main/docs/research/2026-08-16-operational-store-foundation-implementation-contract.md).
It supersedes the standard-library-shaped mechanisms in the older concurrency
research. APSW 3.53.4.0 is the only SQLite binding; Python's standard `sqlite3`
must not open or test the Operational Store.

- [ ] Add one deep, binding-neutral `OperationalStore` interface whose #138
  surface has domain-named persist/resume Transfer Preview operations. Callers
  see immutable intents/snapshots/receipts and stable store errors, never a
  generic `commit(change)`, SQL, paths, transactions, APSW values, or separate
  persistence adapters. Keep mutation composition private so later issues extend
  this same port with reviewed domain operations rather than a second interface.
- [ ] Add a strict pure-Python in-memory adapter and one private APSW adapter;
  run the same interface conformance fixtures against both.
- [ ] Keep the sole direct APSW import in
  `djsupport/operational_store/apsw.py` and retain the architecture test that
  rejects binding leakage or any standard-library SQLite use.
- [ ] Require #166/#167 qualification before path resolution, stat, mkdir,
  lease, open, logging, or mutation; test the order with rejecting path spies.
- [ ] Add the shared-operation/exclusive-maintenance lifecycle lease after the
  runtime gate; lease acquisition is bounded and process death releases it.
- [ ] Implement normalized STRICT schema v1 and an immutable, digest-checked,
  contiguous migration registry with application ID `0x444A5350`, matching
  `user_version`, and post-migration schema fingerprints; reject drift, gaps,
  foreign/newer schemas, and partial prefixes.
- [ ] Encode each selected source occurrence as `(selection_id, occurrence_id,
  position)` with zero-based contiguous positions. Provider IDs, source entity
  IDs, URLs, matching keys, and Spotify URIs are not unique and must not collapse
  duplicate occurrences.
- [ ] Normalize Transfer, Batch, matching-knowledge, proposals, failures,
  checkpoints, and compact event facts; no authority-bearing aggregate
  `state_json`, pickle, generic key/value table, or ORM.
- [ ] Make Transfer, Batch, and matching-knowledge revisions conformant: caller
  revision 0 means expected absent, first durable revision is 1, each successful
  aggregate mutation advances once, and one successful domain write operation
  advances the store commit sequence once.
- [ ] Configure and read back WAL, `synchronous=FULL`, foreign keys,
  `busy_timeout=5000`, `wal_autocheckpoint=1000`, `trusted_schema=OFF`, normal
  locking, exact application ID, and exact schema version on each APSW open.
- [ ] Run fresh/idempotent/concurrent bootstrap plus every-prefix,
  statement-failure, digest-drift, gap, newer, foreign-ID, and tampered-schema
  migration tests.
- [ ] Run the 10,000-Transfer/100,000-occurrence synthetic fixture with deliberate
  adjacent and non-adjacent duplicates, restart, integrity checks, and a canonical
  semantic digest.
- [ ] Keep this SQLite Preview non-authoritative: do not create a production
  selector, dual-write, cut over, or fall back from SQLite to JSON.
- [ ] Document and ignore the database, WAL, SHM, and lease as private user data;
  exclude them from packages and repository fixtures.
- [ ] Verify owner-only application-data permissions after qualification and
  before open: POSIX directories `0700`, files `0600`, and equivalent
  current-user-only Windows ACLs. Reject symlinks, special files, foreign or
  broadly accessible objects, and permission checks that cannot be completed.
```

The existing “Completed prerequisites” list for #166/#167 remains accurate. Do
not remove the #136 human gate.

### Amendment for #139

Append the following after the existing acceptance criteria:

```markdown
## Concurrency and crash implementation contract (2026-08-16)

The implementation follows
[`docs/research/2026-08-16-operational-store-foundation-implementation-contract.md`](https://github.com/spontain112/djsupport/blob/main/docs/research/2026-08-16-operational-store-foundation-implementation-contract.md).

- [ ] Use one short-lived qualified APSW connection per unit of work; never share
  a connection/cursor concurrently across threads, processes, or a fork.
- [ ] Start every read-then-write domain operation with an outer APSW transaction whose
  `transaction_mode` is `IMMEDIATE`; re-read all expected revisions inside it and
  ensure `txn_state("main")` is none before every Spotify call.
- [ ] Implement compare-and-swap for Transfer, Batch, and matching-knowledge
  entities with revision-qualified `UPDATE ... RETURNING revision`; fully consume
  exactly one row, distinguish missing from stale, and roll back the complete
  domain operation if any member conflicts.
- [ ] Return new revisions only after commit; never mutate caller objects. A stale
  revision fails with a reload-before-retry outcome and is never silently retried.
- [ ] Install exactly one 5,000 ms APSW busy timeout per connection. Translate
  primary/extended APSW result codes to stable store errors; busy, stale revision,
  locked/misuse, integrity, and unavailable storage remain distinct.
- [ ] Prove two independent processes can update distinct work, one writer is
  bounded behind another, and two copies of the same revision yield one winner
  and one stale result without lost updates.
- [ ] On process startup run quick, foreign-key, schema, and domain integrity
  checks; after crash and under exclusive maintenance run full integrity plus
  canonical domain-digest verification. Any failure is fail-closed.
- [ ] Inject ordinary exceptions and `os._exit()` before, during, and after commit,
  and use a test-only derived APSW VFS to fail WAL/database write, sync, truncate,
  and delete phases. Reopen through the public interface and accept only the
  complete old or complete new snapshot, including revisions, events, and store
  commit sequence.
- [ ] Run the focused qualified APSW foundation/concurrency/hard-exit suite on all
  25 approved #167 cells: Python 3.10–3.14 on Ubuntu 24.04 x64/arm64, macOS 15
  Intel/Apple silicon, and Windows Server 2025 x64. Run the full VFS campaign on
  every native OS/architecture shape and both Linux Python edges.
- [ ] Preserve existing CLI, web, and Agent Client privacy-redacted behavior and
  keep JSON as production authority; #139 does not activate a selector, dual
  write, cutover, fallback, or release.
```

Keep `Blocked by #138` unchanged.

## 15. Implementation order

The lowest-risk dependency order is:

1. binding-neutral Interface values/errors and the pure-Python Adapter;
2. shared conformance fixtures, including exact duplicate/order and revision
   semantics;
3. immutable schema/migration registry and pure schema tests;
4. runtime-gated path thunk and lifecycle lease;
5. qualified APSW connection factory and error translation;
6. normalized APSW snapshot/commit mapping;
7. migration, integrity, multi-process busy/CAS, hard-exit, and VFS tests;
8. Runtime Assembly's one non-authoritative Preview route;
9. 100,000-occurrence scale and the 25-cell focused native matrix; and
10. privacy/package/docs/release-note checks.

Do not replace the existing production JSON Implementations in #138/#139. The
later migration, backup, cutover, and writer-retirement issues consume this
foundation only after their separate verification and review gates.

## Primary sources

### Project

- [ADR-0005](../adr/0005-use-one-local-transactional-operational-store.md)
- [#138](https://github.com/spontain112/djsupport/issues/138) and
  [#139](https://github.com/spontain112/djsupport/issues/139)
- [#165](https://github.com/spontain112/djsupport/issues/165),
  [#166](https://github.com/spontain112/djsupport/issues/166), and
  [#167](https://github.com/spontain112/djsupport/issues/167)
- [Operational Store runtime package](../../djsupport/operational_store/)
- [Runtime Assembly](../../djsupport/runtime.py),
  [Transfer model/storage](../../djsupport/transfer.py),
  [source facts](../../djsupport/source_facts.py), and
  [matching cache](../../djsupport/cache.py)
- [Package metadata](../../pyproject.toml) and
  [qualified artifact catalog](../../djsupport/contracts/apsw-runtime-artifacts.v1.json)

### APSW 3.53.4.0

- [About and release identity](https://rogerbinns.github.io/apsw/about.html)
- [Connections, contexts, PRAGMAs, transaction mode/state, and busy timeout](https://rogerbinns.github.io/apsw/connection.html)
- [Execution model](https://rogerbinns.github.io/apsw/execution.html)
- [Exceptions and extended result codes](https://rogerbinns.github.io/apsw/exceptions.html)
- [VFS](https://rogerbinns.github.io/apsw/vfs.html)
- [APSW and standard-library differences](https://rogerbinns.github.io/apsw/pysqlite.html)

### SQLite

- [WAL](https://sqlite.org/wal.html),
  [transactions](https://sqlite.org/lang_transaction.html), and
  [isolation](https://sqlite.org/isolation.html)
- [RETURNING](https://sqlite.org/lang_returning.html) and
  [result codes](https://sqlite.org/rescode.html)
- [STRICT tables](https://sqlite.org/stricttables.html),
  [foreign keys](https://sqlite.org/foreignkeys.html), and
  [PRAGMAs/integrity](https://sqlite.org/pragma.html)
- [Open flags](https://sqlite.org/c3ref/open.html),
  [security guidance](https://sqlite.org/security.html), and
  [crash/corruption guidance](https://sqlite.org/howtocorrupt.html)

### Python platform process testing

- [`os._exit`](https://docs.python.org/3.10/library/os.html#os._exit)
- [Multiprocessing start methods and contexts](https://docs.python.org/3.14/library/multiprocessing.html#contexts-and-start-methods)
