# APSW 3.53.4.0 Operational Store integration contract

**Date:** 2026-08-16

**Code baseline at research start:** `origin/main` at
`cdaff38a1e3c4b054fea75a0c7f706a8b5e78c9f`

**Status:** Conditional implementation research for
[#165](https://github.com/spontain112/djsupport/issues/165),
[#166](https://github.com/spontain112/djsupport/issues/166),
[#167](https://github.com/spontain112/djsupport/issues/167),
[#138](https://github.com/spontain112/djsupport/issues/138), and
[#139](https://github.com/spontain112/djsupport/issues/139). APSW is not an
approved DJ Support production dependency at this baseline. This contract becomes
actionable only if a human accepts #165 and the accepted decision updates the
literal standard-library wording identified by ADR-0005. It does not authorize a
production authority switch, live service call, release, or owner-data access.

**Authority:** The merged
[ADR-0005](../adr/0005-use-one-local-transactional-operational-store.md),
the linked repository issues and code, and primary documentation from APSW,
SQLite, Python, PyPA/PyPI, and GitHub Actions. Statements introduced with “DJ
Support must” or “the adapter must” are the project integration contract inferred
from those sources; they are not claims about APSW defaults.

## Outcome

If #165 approves APSW 3.53.4.0, it can implement ADR-0005 without changing the
architecture: one private APSW-backed adapter remains behind the existing deep
Operational Store interface, the in-memory adapter remains its behavioral
conformance peer, and Transfer remains the sole public policy authority. JSON is
still the only production authority before the later atomic, verified activation;
this work must not introduce dual writes, partial cutover, or silent JSON
fallback. The binding choice changes an internal mechanism, not the accepted
domain or authority model
([ADR-0005](../adr/0005-use-one-local-transactional-operational-store.md),
[#138](https://github.com/spontain112/djsupport/issues/138)).

The production contract is stricter than “install APSW 3.53.4.0.” DJ Support must
qualify the exact wheel and installed native extension, attest the APSW wrapper
and embedded SQLite runtime before any Operational Store path is created or
opened, configure and read back every connection invariant, contain APSW-specific
types and exceptions at the adapter boundary, and fail closed when any identity
is affected, withdrawn, revoked, malformed, future, unapproved, or unknown. The
five-state qualification model and pre-open ordering come from #166 and the
merged [runtime qualification
research](2026-08-16-sqlite-runtime-ci-qualification.md).

The official APSW 3.53.4.0 release currently supplies conventional GIL CPython
3.10–3.14 wheels for native x86-64 Linux, arm64 Linux, Intel macOS, Apple-silicon
macOS, x64 Windows, and arm64 Windows. That artifact availability is necessary
but does not itself declare DJ Support support. #165 must name the supported
OS/Python/architecture cells, and #167 must qualify the exact artifact used in
every claimed cell
([PyPI release files](https://pypi.org/pypi/apsw/3.53.4.0/json),
[#167](https://github.com/spontain112/djsupport/issues/167)).

## 1. Fixed architecture and decision boundary

### What is already accepted

ADR-0005 accepts one local transactional SQLite Operational Store behind one
deep, binding-neutral interface, with SQLite and in-memory adapters and no ORM.
It also requires exact-runtime qualification for concurrent WAL authority,
Online Backup API snapshots, short transactions that never span Spotify calls,
and explicit migration/cutover rather than fallback
([ADR-0005](../adr/0005-use-one-local-transactional-operational-store.md)).

The repository has not yet implemented the SQLite adapter. Runtime Assembly
still constructs the JSON authorities, and package metadata has no APSW
dependency. Consequently, the API mapping in this document translates the
merged standard-library-shaped research contract into APSW; it does not describe
an existing production `sqlite3` call site
([Runtime Assembly](../../djsupport/runtime.py),
[package metadata](../../pyproject.toml),
[#138](https://github.com/spontain112/djsupport/issues/138)).

### What #165 must decide before implementation

No code or metadata change may imply that the open decision is already accepted.
The human decision must name at least:

1. APSW `3.53.4.0` as the one Operational Store binding, or reject it;
2. every supported native OS/architecture/Python cell;
3. whether only official PyPI wheels are admissible, with source builds rejected
   unless separately qualified;
4. the artifact and runtime evidence required by #166/#167;
5. the fallback policy, which must not become an unqualified binding or JSON
   runtime fallback; and
6. the notices/credit route for APSW and its embedded SQLite.

Those are explicit acceptance boundaries in
[#165](https://github.com/spontain112/djsupport/issues/165). APSW describes itself
as a direct SQLite wrapper rather than a DB-API implementation, and warns that
using different SQLite libraries on the same database can be unsafe; the decision
therefore must be deliberate rather than a transparent import substitution
([APSW and pysqlite differences](https://rogerbinns.github.io/apsw/pysqlite.html),
[APSW tips](https://rogerbinns.github.io/apsw/tips.html)).

### Binding containment rule

After approval, exactly one private Operational Store binding package may import
`apsw`. Transfer, CLI, web, Agent Clients, domain objects, and the in-memory
adapter must depend only on the binding-neutral Operational Store port. APSW
connections, cursors, rows, result codes, and exceptions must not cross that
boundary. The application must never open an Operational Store with Python
`sqlite3`, and an architecture test must reject direct `apsw` imports elsewhere.
This is the smallest binding seam consistent with ADR-0005 and APSW's documented
non-DB-API surface
([ADR-0005](../adr/0005-use-one-local-transactional-operational-store.md),
[APSW DB-API comparison](https://rogerbinns.github.io/apsw/pysqlite.html)).

## 2. Two-layer binding and runtime attestation

Runtime facts cannot reconstruct the original wheel filename, archive digest, or
publisher provenance after installation. Conversely, a verified wheel download
does not prove that the process imported the expected installed extension. DJ
Support therefore needs two joined evidence layers: release/install evidence for
the archive, and runtime evidence for the loaded binding. PyPI publishes release
filenames and SHA-256 digests, its Integrity API exposes Trusted Publishing
provenance, and pip can produce a machine-readable installation report
([PyPI JSON API](https://pypi.org/pypi/apsw/3.53.4.0/json),
[PyPI attestations](https://docs.pypi.org/attestations/),
[pip installation report](https://pip.pypa.io/en/stable/reference/installation-report/)).

### Layer A — release and installation evidence

For each approved wheel, the versioned qualification manifest must record:

| Field | Exact contract |
| --- | --- |
| Evidence identity | Stable repository-owned ID, schema version, review status, activation date, and optional revocation/supersession identity. |
| Product cell | OS name/version family, native architecture, CPython implementation, exact Python patch used in release qualification, ABI tag, and platform tag. |
| APSW release | Distribution name `apsw`, version `3.53.4.0`, exact wheel filename, PyPI file URL, size, and SHA-256 from the official release JSON. |
| Publisher provenance | Trusted Publisher kind, repository `rogerbinns/apsw`, release workflow identity, source commit, and successful attestation verification for that exact wheel. |
| Installed artifact | Native extension SHA-256 and the installed distribution version; paths are consumed internally and never emitted. |
| Embedded SQLite | Version `3.53.4`, numeric version `3053004`, exact source ID, sorted compile options plus SHA-256, and `using_amalgamation=true`. |
| Loaded Python/platform | CPython major/minor, ABI/SOABI, GIL mode, OS, and native machine architecture matched to the selected wheel cell; the release job also records its exact Python patch and runner image. |
| Support status | `active`, `revoked`, or `superseded`; unknown and future entries are not active by default. |

The PyPI provenance observed for the release is produced from the official APSW
repository's `build-pypi.yml` workflow at source commit
`09b6a89e13e1c49f13bfb92fdb8725d1a0f03b5a`; #167 must verify the attestation
for every selected wheel rather than copying that fact from this dated research
([representative PyPI wheel provenance](https://pypi.org/integrity/apsw/3.53.4.0/apsw-3.53.4.0-cp314-cp314-manylinux_2_28_x86_64.whl/provenance),
[APSW 3.53.4.0 release](https://github.com/rogerbinns/apsw/releases/tag/3.53.4.0)).

### Layer B — loaded-runtime evidence

The probe that runs in the same interpreter and imports the same binding as the
Operational Store must require all of these exact facts:

```text
importlib.metadata.version("apsw") == "3.53.4.0"
apsw.apsw_version()                 == "3.53.4.0"
apsw.sqlite_lib_version()           == "3.53.4"
apsw.SQLITE_VERSION_NUMBER          == 3053004
apsw.sqlite3_sourceid()             ==
  "2026-07-24 19:02:57 "
  "bf7c7f30031888f4e796e429ab3978879485813aaca6f641c7b33e4e09459bcc"
apsw.using_amalgamation             is True
sha256(canonical compile-options bytes) == manifest value
sha256(loaded native extension bytes) == manifest value
```

APSW documents its wrapper version, SQLite runtime version, numeric version,
source ID, compile options, and amalgamation indicator as runtime APIs. SQLite
defines the source ID as the source check-in timestamp and hash; the official
3.53.4 release publishes the exact value above
([APSW module API](https://rogerbinns.github.io/apsw/apsw.html),
[SQLite library identity](https://sqlite.org/c3ref/libversion.html),
[SQLite 3.53.4](https://sqlite.org/releaselog/3_53_4.html),
[Python package metadata API](https://docs.python.org/3/library/importlib.metadata.html)).

`using_amalgamation=true` proves the imported APSW extension was built with an
SQLite amalgamation; it does not prove which downloaded wheel or publisher
produced the bytes. The extension digest joins runtime facts to Layer A, while
the wheel digest and PyPI attestation establish archive provenance. The
compile-option digest is part of identity because SQLite compile-time options can
change behavior, and APSW exposes the compiled set directly
([APSW module API](https://rogerbinns.github.io/apsw/apsw.html),
[SQLite compile options](https://sqlite.org/pragma.html#pragma_compile_options)).

The compile-option digest is SHA-256 over the UTF-8 bytes of the lexicographically
sorted option strings, each terminated by one LF byte. The probe must also match
the active CPython major/minor, ABI/SOABI, GIL mode, operating system, and native
machine architecture to the manifest cell. This canonicalization and cell match
are DJ Support requirements so two implementations cannot hash or select the
same facts differently; Python exposes the interpreter and extension-suffix
facts needed to implement them
([Python `sys.implementation`](https://docs.python.org/3/library/sys.html#sys.implementation),
[Python configuration variables](https://docs.python.org/3/library/sysconfig.html)).

### Five-state classifier and pre-path ordering

The pure classifier required by #166 returns exactly one state:
`qualified_upstream`, `qualified_downstream_attestation`,
`unqualified_affected`, `unqualified_withdrawn`, or `unqualified_unknown`.
APSW 3.53.4.0 with all exact manifest facts is the intended
`qualified_upstream` entry if #165 approves it. Any version-only match, missing
fact, malformed fact, mismatched extension, source build, revoked entry,
withdrawn SQLite 3.52.0, or unlisted future build is fail-closed evidence, not a
warning or fallback
([#166](https://github.com/spontain112/djsupport/issues/166),
[SQLite WAL advisory](https://sqlite.org/wal.html#the_wal_reset_bug),
[SQLite release news](https://sqlite.org/news.html)).

Startup ordering is normative:

1. Import APSW without resolving, creating, or opening an Operational Store path.
2. Collect the public wrapper/runtime facts and hash the loaded extension using
   its internal path without logging that path.
3. Classify the exact tuple against the reviewed manifest.
4. On any result other than qualified, return a stable path-free capability
   error and stop. No environment variable, user preference, downgrade, rollback
   journal mode, `sqlite3` import, or JSON authority fallback may override it.
5. Only after qualification may the private path resolver create directories or
   the connection factory open a file, configure WAL, migrate, back up, or write.

This ordering is the explicit fail-closed gate in #166. A temporary in-memory
connection is unnecessary for the APSW facts above; if a future probe needs SQL,
it may use only `:memory:` before qualification and must not touch an owner-data
path
([#166](https://github.com/spontain112/djsupport/issues/166),
[APSW module API](https://rogerbinns.github.io/apsw/apsw.html)).

Only stable reason codes and public version/build facts may reach diagnostics.
Native module paths, application-data paths, database names, SQL bindings, row
values, credentials, and user-derived identifiers remain private under the
repository's storage and privacy contract
([storage policy](../storage.md),
[repository privacy tests](../../tests/test_repository_privacy.py)).

## 3. Mapping the accepted `sqlite3`-shaped contract to APSW

APSW intentionally follows SQLite closely and is not DB-API compatible. The
adapter must translate explicitly rather than relying on accidental similarities
([APSW DB-API comparison](https://rogerbinns.github.io/apsw/pysqlite.html)).

| Accepted contract or standard-library idiom | APSW 3.53.4.0 implementation contract | Boundary rule |
| --- | --- | --- |
| `sqlite3.connect(path, timeout=5, isolation_level=None)` | Construct `apsw.Connection(path, ...)`, then call `set_busy_timeout(5000)`. APSW uses SQLite native autocommit and does not implement DB-API isolation levels. | Construction stays inside one qualified factory; never return the connection. |
| `connection.execute(sql, params)` | `Connection.execute()` may create an automatic cursor; `Cursor.execute()` is also available. | One prepared statement per adapter call and fully consume results before the next statement. |
| `fetchone()` / `fetchall()` | Consume the APSW cursor by iteration and convert tuples to domain values. | APSW row or cursor objects never escape. |
| `sqlite3.Row` / row factory | Use explicit column projection and a local mapper. | Domain mapping must not depend on mutable connection/cursor row tracers. |
| `detect_types`, adapters, and converters | Encode/decode identifiers, enums, timestamps, JSON payloads, and booleans with explicit versioned domain codecs over SQLite's supported null/integer/real/text/blob values. | No process-global adapter or implicit conversion becomes domain policy. |
| `executemany()` | APSW provides `Connection.executemany()`, but it adds no transaction boundary. Invoke it only inside the owning unit of work and fully consume any returned rows. | Batch convenience cannot create partial durability or escape lazy results. |
| `commit()` / `rollback()` | Use an explicit outer transaction context or explicit `BEGIN`/`COMMIT`/`ROLLBACK`; APSW has no DB-API implicit transaction management. | The unit of work owns the outer transaction. |
| `BEGIN IMMEDIATE` | Set the writer connection's `transaction_mode` to `IMMEDIATE` before entering the outer connection context, or execute the exact transaction statement in the unit-of-work wrapper. | Read units remain deferred; writes acquire intent before mutation. |
| Nested unit of work | APSW nested connection contexts use SQLite savepoints. | A nested release is local composition, not durable success. |
| `cursor.lastrowid` | Use SQL `INSERT ... RETURNING` and consume the returned value. | Do not expose connection-global generated-row state. |
| `cursor.rowcount` | Prefer `UPDATE ... WHERE revision = ? RETURNING ...`; zero returned rows is the optimistic conflict. Use `Connection.changes()` only where no returned value can express the invariant. | Require exactly the expected mutation count. |
| `PRAGMA ...` SQL | Prefer `Connection.pragma(name, value)` for supported pragma set/read operations. | Set and read back every invariant; a setter call alone is not evidence. |
| `check_same_thread=True` | APSW has different threading enforcement; use a new connection per executing thread/process/unit of work and prohibit simultaneous sharing. | Portability policy is stricter than the binding's serial cross-thread allowance. |
| `Connection.backup(target)` | Reverse the call site: `destination.backup("main", source, "main")`. | The destination owns the APSW backup object. |
| `sqlite3.Error` hierarchy | Translate APSW exceptions using `result` and `extendedresult`. | Preserve the chained private cause, expose only typed store errors and safe codes. |

APSW documents automatic cursors, lazy result consumption, multiple-statement
execution, and `IncompleteExecutionError` when statements or results remain.
Allowing multiple SQL statements in one string would also undermine migration
auditability. Every adapter operation and migration therefore uses one registered
statement at a time and consumes or closes its cursor before continuing
([APSW execution model](https://rogerbinns.github.io/apsw/execution.html),
[APSW cursor API](https://rogerbinns.github.io/apsw/cursor.html)).

APSW recommends SQLite's `RETURNING` clause instead of connection-global
last-insert-row state. DJ Support should also use `RETURNING` for optimistic
revision updates: one row is success, zero rows is a typed conflict, and more than
one row is an invariant failure
([APSW tips](https://rogerbinns.github.io/apsw/tips.html),
[SQLite `RETURNING`](https://sqlite.org/lang_returning.html),
[#139](https://github.com/spontain112/djsupport/issues/139)).

## 4. Connection factory and verified invariants

Every unit of work gets a short-lived connection from one qualified factory. The
factory must not cache a process-global connection, must not run before runtime
qualification, and must close partially configured connections on every error.
After opening the selected generation, it sets and reads back:

| Invariant | Set through APSW | Required read-back |
| --- | --- | --- |
| Busy timeout | `set_busy_timeout(5000)` | `pragma("busy_timeout") == 5000` |
| Foreign keys | `pragma("foreign_keys", True)` | numeric `1` |
| Trusted schema | `pragma("trusted_schema", False)` | numeric `0` |
| Synchronous policy | `pragma("synchronous", "full")` | numeric `2` |
| WAL autocheckpoint | `wal_autocheckpoint(1000)` | `pragma("wal_autocheckpoint") == 1000` |
| Journal mode | Bootstrap with `pragma("journal_mode", "wal")`; ordinary open verifies | lowercase text `wal` |
| Application/schema identity | Read the accepted application ID, user version, migration registry, and schema fingerprint | exact registered values |

SQLite documents that foreign-key enforcement is disabled by default per
connection, trusted schema should be disabled when schemas are not trusted,
`synchronous=FULL` is numeric value 2, and WAL activation succeeds only when the
returned journal mode is `wal`. SQLite also warns that unknown pragmas can be
ignored, which is why read-back is mandatory
([SQLite pragma reference](https://sqlite.org/pragma.html),
[trusted schema](https://sqlite.org/pragma.html#pragma_trusted_schema),
[WAL activation](https://sqlite.org/wal.html#activating_and_configuring_wal_mode)).

The factory uses explicit APSW open flags. Only exclusive bootstrap may include
`SQLITE_OPEN_CREATE`; an ordinary authority open uses read/write without create,
and a verification-only open uses read-only, so a missing or misdirected store
cannot silently become an empty database. URI interpretation or a non-default VFS
is forbidden unless a later reviewed contract names it. New-store bootstrap sets
and verifies WAL outside a transaction before creating the registered schema;
ordinary opens verify the persistent mode before returning. Foreign-key mode is
also set before any transaction because SQLite documents it as a no-op inside an
active transaction. Because SQLite may fall back from a requested read/write open
to read-only when operating-system permissions block writes, every authority
connection must also require `Connection.readonly("main") is False` before it
crosses the adapter boundary
([APSW connection constructor](https://rogerbinns.github.io/apsw/connection.html),
[SQLite open flags](https://sqlite.org/c3ref/open.html),
[SQLite foreign-key pragma](https://sqlite.org/pragma.html#pragma_foreign_keys)).

`set_busy_timeout()` installs SQLite's timeout busy handler. APSW documents that
setting a custom busy handler replaces the timeout handler and vice versa. The
adapter must install only the five-second timeout, never install a custom busy
handler before or after it on that connection, and verify the corresponding
pragma value
([APSW connection API](https://rogerbinns.github.io/apsw/connection.html),
[SQLite busy timeout](https://sqlite.org/c3ref/busy_timeout.html)).

Do not enable `apsw.bestpractice.recommended` wholesale. Its current convenience
set includes policy choices such as a 100-millisecond busy timeout and global
connection hooks that conflict with DJ Support's owned five-second connection
contract. If a recommendation is valuable, reproduce it explicitly in the
factory with a project test rather than accepting a mutable bundle
([APSW best practice](https://rogerbinns.github.io/apsw/bestpractice.html),
[APSW connection hooks](https://rogerbinns.github.io/apsw/apsw.html)).

## 5. Transactions, savepoints, and external effects

SQLite starts a transaction automatically for a statement only when no explicit
transaction is active; transactions may be DEFERRED, IMMEDIATE, or EXCLUSIVE.
`BEGIN IMMEDIATE` starts the write transaction immediately and can fail with
`SQLITE_BUSY`. In WAL mode, IMMEDIATE and EXCLUSIVE have the same locking effect
([SQLite transactions](https://sqlite.org/lang_transaction.html)).

APSW does not add DB-API transaction behavior. Its connection context manager
starts a transaction, commits on a clean exit, rolls back on an exception, and
uses savepoints for nested contexts; `transaction_mode` controls the outer begin
mode
([APSW connection context manager](https://rogerbinns.github.io/apsw/connection.html),
[APSW DB-API comparison](https://rogerbinns.github.io/apsw/pysqlite.html)).

The DJ Support unit-of-work contract is therefore:

1. A read unit opens a connection and uses the shortest possible deferred read
   transaction when snapshot consistency is required.
2. A write unit sets `transaction_mode="IMMEDIATE"`, enters exactly one outer
   transaction, performs only local database work, and exits it before returning.
3. The outer unit alone owns durable commit or rollback. Repository methods may
   use nested savepoints for local composition, but a successful `RELEASE` does
   not mean the work is durable until the outer transaction commits.
4. SQL cursors are consumed and closed within the transaction. A lazy cursor must
   never prolong a read transaction beyond the unit of work.
5. Spotify and Beatport calls, filesystem publication, and other external effects
   are forbidden inside the database transaction. The Effect Journal commits
   intent first; the bounded external call occurs with no database transaction;
   a later transaction records the observation.

SQLite documents that `RELEASE` of an inner savepoint can later be undone by an
outer rollback and that an outermost release is the durable transaction commit.
The no-external-call rule preserves ADR-0005's Effect Journal recovery model
([SQLite savepoints](https://sqlite.org/lang_savepoint.html),
[ADR-0005](../adr/0005-use-one-local-transactional-operational-store.md),
[#139](https://github.com/spontain112/djsupport/issues/139)).

Use `Connection.txn_state()` in assertions and defensive cleanup to distinguish
no transaction, read transaction, and write transaction. Do not infer state from
adapter booleans or implement a public `commit()` escape hatch
([APSW connection API](https://rogerbinns.github.io/apsw/connection.html),
[SQLite transaction state](https://sqlite.org/c3ref/txn_state.html)).

## 6. Busy, locked, and failure translation

APSW exceptions expose SQLite's primary `result` and `extendedresult` codes. A
single Python exception class can therefore require different recovery behavior;
the adapter must classify the extended code before translating it
([APSW exceptions](https://rogerbinns.github.io/apsw/exceptions.html),
[SQLite result codes](https://sqlite.org/rescode.html)).

The following table governs ordinary Operational Store statement/transaction
execution. Online Backup `step()` has the operation-specific retry rule stated
after the table.

| APSW/SQLite condition | Store-level classification | Required behavior |
| --- | --- | --- |
| `BusyError` with plain `SQLITE_BUSY`, `SQLITE_BUSY_RECOVERY`, or timeout | `StoreBusy` | Roll back/close the unit, then allow only a bounded fresh-unit retry under the caller's explicit policy. Never spin inside the transaction. |
| `BusyError` with `SQLITE_BUSY_SNAPSHOT` | `StaleReadSnapshot` | End the read transaction and reload state before any retry; retrying the same snapshot cannot become writable. |
| `LockedError` / `SQLITE_LOCKED` | `StoreInvariantFailure` | Treat as same-connection/shared-cache misuse, not ordinary cross-process contention. Close and fail. |
| Constraint result codes | Typed conflict or invariant error | Map only explicitly expected unique/foreign-key/check/revision cases; unknown constraint failures remain invariant errors. |
| `CorruptError`, `NotADBError`, integrity failure | `StoreIntegrityFailure` | Fail closed, preserve the private store, and offer only explicit verified recovery—not JSON fallback. |
| I/O, full-disk, read-only, cannot-open | Typed unavailable/storage error | Roll back where possible, never report success, and emit no path or row values. |
| Unknown APSW/SQLite exception | `StoreFailure` | Fail closed with a stable generic code and a privately chained cause. |

SQLite says `SQLITE_BUSY_SNAPSHOT` occurs when a read snapshot can no longer be
promoted because another connection changed the database, while `SQLITE_LOCKED`
generally denotes a conflict within the same connection or shared cache. Those
conditions are not interchangeable retries
([SQLite result codes](https://sqlite.org/rescode.html),
[SQLite transaction upgrade](https://sqlite.org/lang_transaction.html)).

The backup API is the deliberate exception: APSW documents that `Backup.step()`
may raise either `BusyError` or `LockedError` and that the same backup object may
be stepped again. Section 8's bounded monotonic deadline therefore retries that
step in place while keeping the backup lifecycle intact; it does not translate a
backup lock into the ordinary unit-of-work `StoreInvariantFailure`
([APSW backup API](https://rogerbinns.github.io/apsw/backup.html)).

The five-second SQLite timeout is the only low-level wait. Any higher-level retry
must use an injected monotonic clock and bounded sleeper, begin a new unit of
work, preserve optimistic-revision checks, and stop at an explicit deadline.
Tests must prove the upper bound; random unbounded backoff is not accepted by
[#139](https://github.com/spontain112/djsupport/issues/139).

SQLite may skip the busy handler when invoking it could lead to deadlock, so an
operation can still receive `BusyError` before the nominal timeout. The adapter
must always handle the exception path and must not treat five seconds as a
guaranteed sleep
([SQLite busy handler](https://sqlite.org/c3ref/busy_handler.html)).

## 7. WAL and checkpoint contract

WAL allows readers and one writer to overlap, but SQLite still permits only one
writer. It relies on same-host shared memory and is not a network-filesystem
protocol. A reader holds a stable end mark; a long reader can prevent checkpoint
completion and let the WAL grow
([SQLite WAL concurrency](https://sqlite.org/wal.html#concurrency),
[SQLite checkpointing](https://sqlite.org/wal.html#checkpointing)).

DJ Support must retain the explicit 1,000-page autocheckpoint. Routine
maintenance may call `Connection.wal_checkpoint("main",
apsw.SQLITE_CHECKPOINT_PASSIVE)` and record only redacted frame counts. APSW
returns the log-frame and checkpointed-frame counts; an incomplete passive
checkpoint under an active reader is normal contention, not corruption
([APSW connection API](https://rogerbinns.github.io/apsw/connection.html),
[SQLite checkpoint API](https://sqlite.org/c3ref/wal_checkpoint_v2.html)).

SQLite implements autocheckpointing through the connection's one WAL hook. A
later custom WAL hook disables that autocheckpoint, and reapplying
autocheckpointing replaces the hook. The adapter must therefore own that slot and
must not call `set_wal_hook()`; redacted checkpoint telemetry comes from the
explicit checkpoint return value instead
([SQLite WAL autocheckpoint](https://sqlite.org/c3ref/wal_autocheckpoint.html),
[APSW connection API](https://rogerbinns.github.io/apsw/connection.html)).

`RESTART` and `TRUNCATE` checkpoints require an explicit quiescent maintenance
route and the same bounded busy policy. They must not run opportunistically in
normal requests, and disabling autocheckpointing or serializing all clients is
not an acceptable substitute for runtime qualification. The SQLite WAL-reset
advisory recommends a fixed runtime rather than an application scheduling
workaround
([SQLite WAL checkpoint modes](https://sqlite.org/c3ref/wal_checkpoint_v2.html),
[SQLite WAL-reset advisory](https://sqlite.org/wal.html#the_wal_reset_bug)).

PASSIVE checkpointing never invokes the busy handler, and SQLite can return
`SQLITE_BUSY` immediately when another checkpoint is already running even for
other checkpoint modes. Checkpoint code must therefore accept immediate partial
progress or a typed busy result and apply only its own bounded maintenance
deadline; it must not assume the connection's five-second busy timeout ran
([SQLite checkpoint API](https://sqlite.org/c3ref/wal_checkpoint_v2.html)).

The main database, `-wal`, and `-shm` files are one live private state family.
Committed data may exist only in the WAL, so no component may copy, archive,
delete, or detach a live member. All repository/privacy/package rules in the
merged migration contract remain binding
([SQLite WAL file lifecycle](https://sqlite.org/wal.html#the_wal_file),
[migration and backup contract](2026-08-16-sqlite-migration-backup-cutover-contract.md)).

## 8. APSW Online Backup API contract

APSW reverses the standard-library-looking call direction: the destination
connection creates the backup from a distinct source connection. A complete
snapshot is:

```python
with destination.backup("main", source, "main") as backup:
    while not backup.done:
        backup.step(PAGES_PER_STEP)
```

`Backup.step()` copies a bounded number of pages, `done` reports completion, and
`finish()` must always be called. The context manager guarantees cleanup; if the
copy does not complete, the destination transaction is rolled back. APSW also
documents that the destination is write-locked for the backup lifetime and the
source and destination must be distinct
([APSW backup API](https://rogerbinns.github.io/apsw/backup.html),
[SQLite Online Backup API](https://sqlite.org/backup.html)).

The project wrapper must add the following policy:

1. Qualify the runtime before resolving either owner-data path.
2. Open the active source through the normal verified read factory and a fresh
   private destination through a backup-only factory.
3. Copy small page batches. On `BusyError` or `LockedError`, retry only under an
   injected monotonic deadline and bounded backoff; always call `finish()`.
4. After completion, normalize the destination to `journal_mode=delete`, require
   the returned mode, close every backup/connection handle, and reopen the closed
   standalone destination with `trusted_schema=OFF`.
5. Verify application ID, user version, migration registry, schema fingerprint,
   full `integrity_check`, empty `foreign_key_check`, authority revision, and the
   domain semantic digest before archiving or offering restore Preview.
6. Never filesystem-copy a live main/WAL/SHM family and never treat an incomplete
   destination as a backup.

These are the binding-specific mechanics for the already accepted backup and
restore protocol; they do not change its generation, verification, archive, or
cutover model
([migration and backup contract](2026-08-16-sqlite-migration-backup-cutover-contract.md),
[#145](https://github.com/spontain112/djsupport/issues/145),
[SQLite integrity check](https://sqlite.org/pragma.html#pragma_integrity_check)).

## 9. Connection, thread, and process ownership

APSW can serialize use of a connection across threads, but it detects concurrent
use and can raise `ThreadingViolationError`. APSW releases the GIL while SQLite
runs, so the GIL is not a connection-ownership mechanism. DJ Support's stricter
portable rule is one short-lived connection per executing thread/process/unit of
work, never simultaneous sharing and never a Runtime Assembly singleton
([APSW threading](https://rogerbinns.github.io/apsw/execution.html#multi-threading),
[APSW exceptions](https://rogerbinns.github.io/apsw/exceptions.html)).

No live connection, cursor, or backup object may cross `fork()`. A child opens its
own qualified connection after process start. SQLite explicitly warns that
carrying an open connection across fork can corrupt a database. On POSIX test
runs, `apsw.fork_checker()` should turn violations into
`ForkingViolationError`; it is test instrumentation, not a Windows or production
capability gate
([SQLite fork warning](https://sqlite.org/howtocorrupt.html#_carrying_an_open_database_connection_across_a_fork_),
[APSW fork checker](https://rogerbinns.github.io/apsw/apsw.html)).

Connections, cursors, and backup objects must be closed deterministically on
success and every exception. `with connection:` is a transaction context; it
does not replace an explicit `Connection.close()` in the factory's `finally`
path. The backup context calls `finish()`, and cursor lifetimes remain bounded by
the owning unit. No lifecycle may depend on garbage collection
([APSW connection API](https://rogerbinns.github.io/apsw/connection.html),
[APSW backup API](https://rogerbinns.github.io/apsw/backup.html)).

The qualified conventional CPython wheels keep the GIL. The separate `cp314t`
free-threaded wheels are not equivalent artifacts and are outside the initial
contract; APSW currently documents that importing APSW on free-threaded Python
re-enables the GIL unless an unsafe override is used. #165 would need a separate
explicit support and qualification decision before those wheels could enter the
manifest
([APSW installation](https://rogerbinns.github.io/apsw/install.html),
[PyPI release files](https://pypi.org/pypi/apsw/3.53.4.0/json)).

## 10. Packaging and native release matrix

APSW 3.53.4.0 declares Python `>=3.10`. The official PyPI release contains one
source distribution and 80 wheels. For each conventional GIL CPython minor from
3.10 through 3.14 it provides these relevant families
([PyPI release JSON](https://pypi.org/pypi/apsw/3.53.4.0/json),
[Python platform tags](https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/)):

| Family in the release | CPython 3.10–3.14 availability | Initial DJ Support consequence |
| --- | --- | --- |
| Linux glibc | `manylinux_2_28` x86-64, aarch64, and i686 wheels; ARMv7 wheels use additional compatible tags | x86-64 and any explicitly accepted arm64 cells have binary candidates. i686/ARMv7 are not implied support. |
| Linux musl | `musllinux_1_2` x86-64, aarch64, i686, and ARMv7 wheels | Alpine/musl is not implied support and requires separate native qualification. |
| macOS | Intel x86-64 and Apple-silicon arm64 wheels | Each architecture is a distinct artifact and product cell. |
| Windows | `win32`, `win_amd64`, and `win_arm64` wheels | x64 has a stable hosted-runner route; win32/arm64 are not implied support. |
| WebAssembly | selected wasm wheels | Not a native DJ Support target and must remain outside the manifest. |
| Free-threaded Python | `cp314t` wheels | Excluded pending a separate decision and concurrency qualification. |

The minimum support claim already described by #167 is native Ubuntu 24.04
x86-64, macOS 15, and Windows 2025 x64 across CPython 3.10–3.14 artifact
resolution, with the issue's specified native persistence edges. If #165 adds
Intel macOS, Linux arm64, Windows arm64, musl, or another architecture, #167 must
add a real native cell for every claimed combination; the presence of a wheel is
not a test result
([#167](https://github.com/spontain112/djsupport/issues/167),
[GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)).

GitHub currently provides versioned standard labels for Ubuntu 24.04 x64 and
arm64, macOS 15 arm64 and Intel, and Windows 2025 x64. Its Windows ARM label is a
Windows 11 public-preview runner, not Windows 2025. Therefore a Windows arm64
support claim requires an explicit runner/provisioning decision; it cannot be
silently covered by the x64 job
([GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)).

### Install and release rules

Only after #165 approval, package metadata may declare the exact dependency
`apsw==3.53.4.0`. Release jobs must resolve an official wheel with
`--only-binary=apsw`, verify its manifest SHA-256 and PyPI attestation, and reject
automatic source fallback. Secure-install mode should use pinned requirements
with `--require-hashes`; any source build needs a separate reviewed compiler,
source, options, artifact, and native-test qualification route
([pip `--only-binary`](https://pip.pypa.io/en/stable/cli/pip_install/#cmdoption--only-binary),
[pip secure installs](https://pip.pypa.io/en/stable/topics/secure-installs/),
[APSW installation](https://rogerbinns.github.io/apsw/install.html)).

DJ Support's own wheel must be built once, hashed once, and installed unchanged
in every release cell. Its archive remains pure Python and must not contain
`.so`, `.dylib`, `.dll`, or `.pyd` files; APSW remains the separately verified
dependency. #149's later release-candidate evidence must join the one DJ Support
wheel digest, exact APSW wheel digest/provenance, and loaded runtime attestation
for each claimed cell
([#149](https://github.com/spontain112/djsupport/issues/149),
[Python wheel format](https://packaging.python.org/en/latest/specifications/binary-distribution-format/)).

Every workflow must pin actions by full commit SHA, use least-privilege
permissions and no service credentials, request an exact Python patch for release
qualification, record the resolved interpreter and runner image, and fail rather
than skip or `continue-on-error`. A minor selector can move to a later patch, and
GitHub's hosted images are updated over time; floating labels are useful for
compatibility discovery but are not release artifact identity
([current CI](../../.github/workflows/ci.yml),
[setup-python version syntax](https://github.com/actions/setup-python#supported-version-syntax),
[GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)).

### Licensing and public credit

APSW's source is distributed under a permissive “any OSI approved license” grant
whose notice must remain with source distributions, and APSW asks for
acknowledgement. SQLite is dedicated to the public domain. The accepted #165/#167
route must extend DJ Support's canonical `THIRD_PARTY.md` open-source
credits/notices surface for both APSW and the embedded SQLite; this research file
must not create a competing credits artifact
([APSW copyright](https://rogerbinns.github.io/apsw/copyright.html),
[SQLite copyright](https://sqlite.org/copyright.html),
[current canonical third-party notices](https://github.com/spontain112/djsupport/blob/4b086c937be8190702513e9a34f681acafadccd4/THIRD_PARTY.md),
[#167](https://github.com/spontain112/djsupport/issues/167)).

## 11. Test seams

The deep adapter should make difficult evidence injectable without making
production policy optional:

| Seam | Production implementation | Test use |
| --- | --- | --- |
| Runtime-facts collector | Fixed APSW collector, called before path resolution | Supply complete, malformed, affected, withdrawn, revoked, future, and mismatched tuples to the pure classifier. |
| Qualification manifest | Versioned read-only repository data | Exercise all five states, schema validation, exact matching, and revocation without importing APSW. |
| Connection factory | Only qualified path to `apsw.Connection` | Use recording/failing connections for setup order; use temporary file-backed stores for real SQLite behavior. |
| Statement executor/mapper | Private APSW cursor consumption | Prove one-statement execution, full consumption, row translation, exception translation, and no APSW type escape. |
| Unit-of-work wrapper | Outer read/deferred or write/immediate transaction owner | Inject failure before/after statements and assert rollback, savepoint containment, and no external call in transaction. |
| Monotonic clock/sleeper | System monotonic clock and bounded sleep | Make busy and backup deadlines deterministic and prove the maximum wait. |
| Checkpoint wrapper | APSW passive checkpoint with redacted counts | Model held readers, partial progress, WAL growth, and quiescent maintenance. |
| Backup factory/verifier | Distinct source/destination connections and mandatory finish | Inject busy, locked, cancellation, incomplete copy, corruption, wrong schema, and verification failures. |
| Trace instrumentation | Test-only APSW execution/transaction tracing | Assert transaction boundaries and statement order; never log SQL bindings or row values. |

In-memory databases are suitable only for pure SQL and mapping tests. WAL,
independent-connection locking, checkpoint, crash, backup, reopen, and filesystem
privacy behavior require synthetic file-backed stores in private temporary
directories. SQLite's in-memory databases do not exercise the persistent WAL
family, while WAL concurrency depends on separate connections and shared memory
([SQLite in-memory databases](https://sqlite.org/inmemorydb.html),
[SQLite WAL concurrency](https://sqlite.org/wal.html#concurrency)).

Run APSW's installed self-tests (`python -m apsw.tests`) for every exact selected
wheel before DJ Support tests. That is upstream binding evidence, not a substitute
for domain conformance, failure injection, native concurrency, backup, or package
tests
([APSW testing](https://rogerbinns.github.io/apsw/install.html#testing)).

## 12. Fail-closed evidence by delivery issue

### #166 — runtime qualifier

The issue is complete only when tests prove:

- a versioned manifest schema and pure five-state classifier;
- exact acceptance of the reviewed APSW 3.53.4.0 tuple, not a numeric minimum;
- rejection of SQLite 3.52.0, known affected builds, missing/malformed facts,
  unknown future builds, unapproved source builds, revoked entries, wrong compile
  options, wrong extension bytes, and wrapper/distribution disagreement;
- qualification before any path creation/open, write, WAL activation, migration,
  or backup;
- no user/environment override and no fallback binding or authority;
- path-free error and diagnostic facts; and
- explicit Python 3.10 and 3.14 edge tests plus the ticket-specific release
  record.

This restates the executable acceptance boundary in
[#166](https://github.com/spontain112/djsupport/issues/166) using APSW's official
runtime facts
([APSW module API](https://rogerbinns.github.io/apsw/apsw.html)).

### #167 — dependency and native artifact qualification

The issue is complete only when tests and CI prove:

- exact dependency pin and binary-only resolution from official PyPI;
- wheel filename, archive SHA-256, PyPI provenance, source commit, installed
  extension SHA-256, wrapper version, SQLite version/source ID, compile options,
  and amalgamation status in every claimed cell;
- all CPython 3.10–3.14 artifact-resolution cells for each approved native
  OS/architecture, plus the required native persistence edge cells;
- one DJ Support wheel digest installed across the matrix, with no bundled native
  library and no unexpected private artifacts;
- no skip, source-build fallback, second Operational Store binding, secret, live
  call, or owner-data fixture; and
- canonical APSW/SQLite credits plus the ticket's release record.

These are the acceptance requirements of
[#167](https://github.com/spontain112/djsupport/issues/167), joined to official
PyPI artifact/provenance evidence
([PyPI release files](https://pypi.org/pypi/apsw/3.53.4.0/json),
[PyPI attestations](https://docs.pypi.org/attestations/)).

### #138 — non-authoritative adapter and conformance

The issue is complete only when:

- the in-memory and APSW adapters pass the same binding-neutral contract tests;
- ordered Source Occurrences and duplicate occurrences remain exact;
- revisions, failures, checkpoints, events, migration registry, schema identity,
  and deterministic 100,000-occurrence/10,000-Transfer scale fixtures pass;
- APSW-specific types, errors, transaction semantics, and lazy cursors remain
  private;
- architecture tests allow only the one APSW import boundary and prove the store
  is never opened through both APSW and `sqlite3`; and
- JSON remains sole production authority with no cutover or dual write.

Those are the binding-specific consequences of
[#138](https://github.com/spontain112/djsupport/issues/138), ADR-0005, and APSW's
documented execution model
([ADR-0005](../adr/0005-use-one-local-transactional-operational-store.md),
[APSW execution](https://rogerbinns.github.io/apsw/execution.html)).

### #139 — concurrency and durability

The issue is complete only when the exact qualified release artifacts, on the
required native macOS/Linux/Windows cells, prove:

- three or more independent connections, stable readers, one writer, bounded
  busy behavior, and no shared connection across concurrent execution;
- `BEGIN IMMEDIATE` writer units, optimistic revision conflict through
  `RETURNING`, nested savepoint rollback, and no external call in a transaction;
- exact setup/read-back, passive checkpoint progress under held readers, bounded
  quiescent restart/truncate maintenance, and no copied/deleted WAL sidecars;
- crash/fault injection before, during, and after commit with atomic recovery;
- mandatory application/schema/integrity/foreign-key checks and fail-closed
  corruption handling; and
- no skipped native cell and no success claim from stress tests without the
  exact binding/runtime evidence.

Passing stress runs alone cannot prove the WAL-reset fix; every cell must first
pass the exact runtime/artifact gate from #166/#167
([#139](https://github.com/spontain112/djsupport/issues/139),
[SQLite WAL-reset advisory](https://sqlite.org/wal.html#the_wal_reset_bug),
[concurrency contract](2026-08-16-sqlite-concurrency-durability-contract.md)).

The APSW backup tests in section 8 are required binding-integration evidence for
the later backup/restore ticket #145, not an expansion of #139's delivery scope
([#145](https://github.com/spontain112/djsupport/issues/145)).

## 13. Implementation order after a human approval

The dependency-safe sequence is:

1. Record the human #165 decision and update the literal binding language in the
   accepted issue/ADR route. If APSW is rejected, this document remains research.
2. Implement #166's manifest, collector, five-state classifier, path-free error,
   and pre-path gate without opening a production store.
3. Implement #167's exact dependency, binary-only supply-chain verification,
   native matrix, package checks, credits, and release record. Fail if any
   selected cell lacks an official wheel or native qualification route.
4. Implement #138's private APSW adapter and in-memory conformance peer as one
   non-authoritative Preview while JSON remains sole production authority.
5. Implement #139's native concurrency, durability, checkpoint, crash, and backup
   evidence against the exact qualified artifacts.
6. Leave production migration and activation to their later approved tickets;
   neither installing APSW nor passing #139 changes authority.

This ordering follows the current issue dependencies and ADR-0005's explicit
decision gate
([#165](https://github.com/spontain112/djsupport/issues/165),
[#166](https://github.com/spontain112/djsupport/issues/166),
[#167](https://github.com/spontain112/djsupport/issues/167),
[#138](https://github.com/spontain112/djsupport/issues/138),
[#139](https://github.com/spontain112/djsupport/issues/139),
[ADR-0005](../adr/0005-use-one-local-transactional-operational-store.md)).

## 14. Rejected shortcuts and open decisions

The implementation must reject these shortcuts:

- approving by `sqlite_version >= 3.51.3` or version string alone;
- hashing only the wheel or only the installed extension;
- probing Python `sqlite3` while APSW opens the store;
- automatically compiling APSW when a wheel is unavailable;
- treating wheel availability as a supported platform claim;
- loading both APSW and `sqlite3` against the Operational Store;
- using a shared connection because APSW can serialize some cross-thread calls;
- using `apsw.bestpractice.recommended` as unreviewed configuration policy;
- retrying `BUSY_SNAPSHOT` inside the stale transaction;
- letting nested savepoint success escape as durable success;
- disabling checkpoints, copying a live WAL family, or treating a stress pass as
  runtime qualification; and
- falling back to JSON, rollback journal, or a second binding after a gate fails.

Each rejection follows either the open decision/issue acceptance criteria or the
official binding/database behavior cited above. None is a new architecture
decision.

Two human choices remain deliberately unresolved here: the exact supported
OS/architecture set and whether any separately qualified source-build route is
worth owning. Windows arm64 is the clearest practical example: APSW publishes a
wheel, but GitHub's public hosted ARM runner is not Windows 2025. #165 must either
exclude that cell or accept a concrete native qualification route
([PyPI release files](https://pypi.org/pypi/apsw/3.53.4.0/json),
[GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners),
[#165](https://github.com/spontain112/djsupport/issues/165)).

## Primary-source index

- Repository: [ADR-0005](../adr/0005-use-one-local-transactional-operational-store.md),
  [runtime qualification](2026-08-16-sqlite-runtime-ci-qualification.md),
  [runtime delivery](2026-08-16-sqlite-runtime-qualification-and-delivery.md),
  [concurrency and durability](2026-08-16-sqlite-concurrency-durability-contract.md),
  [migration, backup, and cutover](2026-08-16-sqlite-migration-backup-cutover-contract.md),
  and issues [#165](https://github.com/spontain112/djsupport/issues/165),
  [#166](https://github.com/spontain112/djsupport/issues/166),
  [#167](https://github.com/spontain112/djsupport/issues/167),
  [#138](https://github.com/spontain112/djsupport/issues/138), and
  [#139](https://github.com/spontain112/djsupport/issues/139).
- APSW: [documentation](https://rogerbinns.github.io/apsw/),
  [module API](https://rogerbinns.github.io/apsw/apsw.html),
  [connections](https://rogerbinns.github.io/apsw/connection.html),
  [execution](https://rogerbinns.github.io/apsw/execution.html),
  [exceptions](https://rogerbinns.github.io/apsw/exceptions.html),
  [backup](https://rogerbinns.github.io/apsw/backup.html),
  [installation](https://rogerbinns.github.io/apsw/install.html), and
  [copyright](https://rogerbinns.github.io/apsw/copyright.html).
- SQLite: [3.53.4 release](https://sqlite.org/releaselog/3_53_4.html),
  [library identity](https://sqlite.org/c3ref/libversion.html),
  [WAL](https://sqlite.org/wal.html),
  [transactions](https://sqlite.org/lang_transaction.html),
  [savepoints](https://sqlite.org/lang_savepoint.html),
  [result codes](https://sqlite.org/rescode.html),
  [Online Backup API](https://sqlite.org/backup.html), and
  [pragmas](https://sqlite.org/pragma.html).
- Distribution and CI: [APSW 3.53.4.0 PyPI JSON](https://pypi.org/pypi/apsw/3.53.4.0/json),
  [PyPI attestations](https://docs.pypi.org/attestations/),
  [pip secure installs](https://pip.pypa.io/en/stable/topics/secure-installs/),
  [wheel tags](https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/),
  and [GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
