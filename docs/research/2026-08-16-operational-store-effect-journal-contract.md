# Operational Store Effect Journal implementation contract

**Date:** 2026-08-16

**Current implementation baseline:** `origin/main` at
`3e6ae7f6157364eeedaa2667d2a1deabed9efcee`

**Scope:** implementation-readiness research for
[#140](https://github.com/spontain112/djsupport/issues/140),
[#141](https://github.com/spontain112/djsupport/issues/141),
[#142](https://github.com/spontain112/djsupport/issues/142), and
[#143](https://github.com/spontain112/djsupport/issues/143)

**Status:** contract research only. It does not switch production authority,
call a live provider, read owner data, publish a package, or authorize work past
the issues' dependency gates.

**Contract precedence:** The actionable issue amendments are the proposed
normative execution delta; the preceding sections explain and source that delta.
Once an amendment is accepted into an issue, the issue body is authoritative.
Do not combine conflicting versions—reconcile the amendment first.

## Decision

Issues #140–#143 should share one explicit effect protocol and extend the one
Operational Store Interface with domain-cohesive publication, Approval,
Qualification, and Mirror operations. A logical provider effect has a
stable identity and a durable desired state. Each actual provider call has three
local boundaries:

1. commit the desired state and a `prepared` effect;
2. commit an attempt claim, leaving the effect `in_flight`;
3. with **no database transaction open**, make exactly one bounded provider
   call, then commit the observed result and all local state made valid by that
   result.

`prepared` proves the call has not been claimed and is safe to claim.
`in_flight` means the call may have happened; after interruption it is
`uncertain` and must be reconciled. A durable observation is replayable without
calling the provider. This extra claim boundary is necessary because a single
`intent -> call -> observation` sequence cannot distinguish a crash before
dispatch from a lost response after dispatch.

SQLite can make each local transition atomic, but it cannot include Spotify in
the database commit. SQLite permits only one writer at a time, and
`BEGIN IMMEDIATE` acquires the write transaction before a read-then-write unit
does its validation. APSW's connection context manager commits on clean exit,
rolls back on exception, and uses its `transaction_mode` for the outer
transaction. Every writer unit should therefore use an outer
`transaction_mode="IMMEDIATE"` context and finish before the provider adapter is
entered
([SQLite transactions](https://sqlite.org/lang_transaction.html),
[APSW connection transactions](https://rogerbinns.github.io/apsw/connection.html)).

This contract deepens the accepted
[ADR-0005](../adr/0005-use-one-local-transactional-operational-store.md),
[APSW integration contract](2026-08-16-apsw-operational-store-integration-contract.md),
and
[concurrency contract](2026-08-16-sqlite-concurrency-durability-contract.md).
It does not replace their qualified-runtime, connection, backup, migration, or
cutover rules.

## What the current implementation proves—and what it does not

The current domain policy is already substantial:

- `Transfer` owns publication, Qualification, Approval, Drift, orphaning, and
  explicit Mirror disposition; clients remain renderers
  ([architecture](../architecture.md), [domain model](../domain-model.md)).
- Publication recovery uses a stable marker and chunk checkpoints; Approval
  double-reads the playlist head around ordered playlist items; Qualification
  retains manifest, selection, account, and playlist-head evidence; file-backed
  drafts already reject stale revisions and persist both sides of supersession
  together
  ([Transfer implementation](../../djsupport/transfer.py),
  [Transfer tests](../../tests/test_transfer.py),
  [Qualification tests](../../tests/test_qualification.py)).
- The merged runtime work pins APSW 3.53.4.0, qualifies exact native artifacts,
  and keeps APSW private to the Operational Store adapter
  ([ADR-0005](../adr/0005-use-one-local-transactional-operational-store.md),
  [runtime qualification tests](../../tests/test_sqlite_runtime_qualification.py),
  [delivery tests](../../tests/test_sqlite_runtime_delivery.py)).

Those behaviors are regression inputs, not proof that the four issues are
already implementable without choices. The current JSON model still has these
material gaps:

1. `PublicationManifest` requires a Spotify playlist ID and has no independent
   immutable publication identity or manifest revision. The store must be able
   to commit the manifest **before** playlist creation returns an ID.
2. `_publish_checkpointed` and Qualification chunking retain remote results
   after calls, but there is no pre-call Effect Journal claim that separates
   definitely unattempted work from uncertain work.
3. Approval writes matching knowledge, publication state, and Qualification
   state through separate files. A failure can split one logical Approval.
4. Correction repair can mutate a Spotify playlist from inside the current
   Approval path. That remote mutation must become a separately authorized,
   journaled application effect; local Approval itself remains authority-only.
5. `MirrorRelationship` has no optimistic revision or lifecycle state beyond an
   `orphaned_at` timestamp, and `remove_mirror` deletes the active relationship
   rather than retaining a terminal history fact.
6. Draft IDs are initially derived from Transfer and source reference while the
   remaining binding facts are validated as mutable fields. #142 needs one exact
   identity contract for account, Transfer, manifest, playlist head, and selected
   occurrences.

## Common transaction and Effect Journal protocol

### Connection and unit-of-work rules

Every Operational Store call in this document inherits the accepted connection
contract: runtime qualification occurs before path resolution, each unit opens a
fresh APSW connection, the five-second busy timeout and connection PRAGMAs are
set and read back, WAL and `synchronous=FULL` are required, and connections,
cursors, and result iterators stay inside the adapter. WAL lets readers proceed
with a writer, but still allows only one writer; all clients must be on the same
host
([SQLite WAL concurrency](https://sqlite.org/wal.html#concurrency),
[APSW busy timeout](https://rogerbinns.github.io/apsw/connection.html#apsw.Connection.set_busy_timeout)).

For each write unit:

```text
open qualified connection
set transaction_mode = IMMEDIATE
BEGIN IMMEDIATE
  reload every aggregate and expected revision
  validate closed-state and identity constraints
  perform all local writes for this transition
  append the compact Operational Event in the same transaction
COMMIT, or roll back the whole unit
assert txn_state(main) == NONE
close connection
```

APSW exposes `txn_state()` specifically to distinguish no transaction, read
transaction, and write transaction. Tests must assert `NONE` immediately before
every synthetic provider call and after every public store operation
([APSW transaction state](https://rogerbinns.github.io/apsw/connection.html#apsw.Connection.txn_state)).
Nested helpers may use savepoints, but an inner `RELEASE` is not durable if the
outer transaction later rolls back
([SQLite savepoints](https://sqlite.org/lang_savepoint.html)).

Use `UPDATE ... WHERE id = ? AND revision = ? RETURNING revision` for mutable
aggregates. Consume exactly one returned row; zero means a typed stale revision,
and more than one is an invariant failure. SQLite's `RETURNING` output appears
only after the statement's database modifications, but the enclosing transaction
still owns the commit
([SQLite `RETURNING`](https://sqlite.org/lang_returning.html),
[APSW connection API](https://rogerbinns.github.io/apsw/connection.html)).

### Durable effect states

```text
prepared --claim attempt--> in_flight --observed response--> observed_complete
                                    |                    \-> observed_not_applied
                                    |
                                    +--process loss / ambiguous response--> uncertain

uncertain --reconcile--> reconciled_complete
                       \-> reconciled_not_applied
                       \-> review_required

observed_not_applied / reconciled_not_applied --permitted retry--> prepared
```

- `prepared` contains the exact aggregate revision, operation kind, ordered
  effect ordinal, canonical request digest, and the durable desired facts needed
  to invoke or reconcile. It is inserted in the same transaction as those
  desired facts.
- Claiming an attempt is a separate revision-qualified local transaction.
  A crash during this commit leaves either `prepared` or `in_flight`.
- Once `in_flight` commits, no automatic resume may assume the call did not
  happen—even if the process died before the adapter was entered. This may
  conservatively require reconciliation for a call that never reached the
  provider, but it never guesses that an applied call was absent.
- `observed_not_applied` is allowed only for a response that conclusively says the
  requested mutation did not apply. A timeout, disconnect, process loss, or
  ambiguous provider error is `uncertain`.
- Reconciliation itself consists of provider reads outside a database
  transaction followed by one local transaction that binds the exact observation
  to the still-current effect and aggregate revisions.
- An uncertain effect may be retried only after reconciliation proves it was not
  applied, or when the provider operation has a separately documented
  idempotency guarantee. A stable DJ Support key is evidence for reconciliation,
  not proof of provider idempotency.
- A conclusive not-applied result returns the same logical effect to `prepared`
  only when the request and aggregate revisions are still exact and Transfer's
  bounded retry policy permits another attempt. The next claim creates a new
  attempt ordinal; it never overwrites attempt history.
- Each provider call is one effect. Playlist creation, description update,
  replacement, each append chunk, relink mutation, restore, and deletion do not
  share an opaque “publication happened” journal row.
- Effects in one operation have an ordinal and predecessor. Effect `n+1` cannot
  be claimed until effect `n` is durably complete.
- Preview creates neither an effect nor an attempt. A Preview checkpoint and its
  compact event remain explicitly non-authoritative.

### Live claimant boundary

Durable `in_flight` state alone does not prove whether another process is still
inside the bounded provider call. Before claiming `prepared`, a worker acquires a
non-blocking, process-scoped exclusive OS lock for that effect, using a fixed
private lock directory and a one-way safe filename derived from the effect ID.
It keeps the lock handle open across the claim transaction, provider call, and
observation/uncertain transaction, then releases it. Lock files use the
foundation's owner-only permission contract and are never deleted while another
process may contend for them.

A concurrent resume that cannot acquire the lock returns the stable
`effect_attempt_active` outcome and performs no provider read, write, or state
transition. If it acquires the lock and then observes `in_flight`, the previous
claimant is no longer live; it atomically marks the attempt `uncertain` before
reconciliation. Wall-clock expiry, process IDs, and heartbeats are not accepted
as proof that a provider call ended. Process death releases the OS lock while the
durable claim remains for conservative recovery.

### Minimum binding-neutral schema facts

The final table names belong to #138's schema registry. The following facts and
constraints are normative for #140–#143, regardless of names:

| Record | Required durable facts and constraints |
| --- | --- |
| Publication | Local `publication_id` independent of a remote playlist ID; Transfer, account, mode, source identity, lifecycle state, current manifest revision, and optimistic revision. One Snapshot publication per exact Transfer; a later Transfer of the same source remains a distinct Snapshot. |
| Publication Manifest | Immutable `manifest_id`, publication ID, manifest revision, canonical digest, source facts, and creation fact. It does not require a remote playlist ID; that nullable binding belongs to the Publication aggregate. `UNIQUE(publication_id, manifest_revision)`; later Mirror or Qualification applications create a new revision rather than overwriting history. |
| Publication Item | Manifest ID, explicit ordinal, exact Source Occurrence ID and proposal/unresolved facts. `UNIQUE(manifest_id, ordinal)` and explicit `ORDER BY ordinal`; track facts and Spotify URIs are deliberately **not** unique because duplicate occurrences are valid. Review items and managed items need two ordered relations or an equally lossless role/ordinal representation. |
| Logical effect | Stable effect ID, owning operation/aggregate, effect ordinal and predecessor, effect kind, expected aggregate revision, canonical request digest, lifecycle state, optimistic revision, and timestamps. `UNIQUE(operation_id, effect_ordinal)` and `UNIQUE(effect_id)`. |
| Effect attempt/observation | Effect ID, attempt ordinal, opaque claim token, claim/observation state, stable safe reason code, provider object identity/head when observed, and result digest. Raw provider responses and exceptions are not required; if retained privately they never enter diagnostics. `UNIQUE(effect_id, attempt_ordinal)`. |
| Approval | Stable approval request ID, account, publication/manifest revision and digest, exact reviewed playlist head plus ordered-item digest, correction-input digest, outcome, and terminal revision. An exact attempt replay returns the retained result without a second event or authority write. At most one terminal `approved` or `abandoned` Approval exists per publication revision; retained `needs_review` attempts may be followed only after an explicit supported repair produces new evidence. |
| Approval item | Approval ID, manifest item/occurrence identity, classification (`approved`, `rejected`, `collision`, `correction`, or `conflict`) and ordinal. Ambiguous items never acquire successful representation implicitly. |
| Qualification Draft | Exact draft identity tuple, status, account, Transfer, manifest revision/digest, playlist ID/head, selection and selected-occurrence digests, revision, predecessor/successor, intended applied manifest revision, and application operation ID. |
| Qualification decision | Draft ID, selected occurrence ID, decision kind, explicit exclusion flag where allowed, correction facts or private reason, and decision revision/fact time. One current decision per selected occurrence; history may be an event but is never matching authority. |
| Mirror | Stable Mirror ID, account, source type, Source Selection reference, remote playlist ID, lifecycle state, current Mirror revision, current manifest revision, and last conclusively observed playlist head. Active source and playlist bindings are unique within an account. |
| Mirror revision | Immutable Mirror ID/revision, source binding, manifest, ordered managed items, expected/observed remote head, maintenance operation ID, and outcome. `UNIQUE(mirror_id, revision)`. |
| Operational Event | Stable event ID, category, aggregate type and opaque local identity, outcome/reason category, counts, and fact time. No authority code reads it; rebuilding or deleting analytics history cannot change any row above. |

All text identities are `NOT NULL`; revisions and ordinals have non-negative
`CHECK` constraints; closed state vocabularies are checked. Parent ownership uses
foreign keys with `RESTRICT`/`NO ACTION`, not cascades that could turn deletion
into authority. SQLite foreign-key enforcement is disabled by default and must
be enabled and verified on every connection. Full integrity verification also
requires both `PRAGMA integrity_check` and `PRAGMA foreign_key_check`, because
the former does not check foreign keys
([SQLite foreign keys](https://sqlite.org/foreignkeys.html),
[SQLite integrity checks](https://sqlite.org/pragma.html#pragma_integrity_check)).

## #140 — publish one Snapshot through the Effect Journal

### Exact operation boundary

1. **Prepare outside a transaction.** Transfer finishes matching, constructs one
   immutable local publication/manifest identity, canonical ordered Publication
   Items, desired playlist name/description/items, and request digest. This pure
   work does not call Spotify.
2. **Transaction P — prepare publication.** `BEGIN IMMEDIATE`; reload the
   Transfer and expected revision; require the same account, mode, selection, and
   incomplete publication state; insert the publication, immutable manifest and
   ordered items; insert effect 0 (`playlist_create`) as `prepared`; move the
   Transfer to retaining-publication; append the compact prepared event; commit.
   The remote playlist ID is still null.
3. **Transaction C — claim effect.** Compare-and-swap `prepared -> in_flight`,
   create attempt 1, and commit.
4. **Provider boundary.** Assert the APSW connection has no transaction. Invoke
   exactly one synthetic/production Spotify adapter method. For create, pass the
   stable publication recovery marker already modeled by the current adapter.
5. **Transaction O — observe.** Reload effect, attempt, Transfer, and publication
   revisions. Atomically retain the exact observed playlist ID/head or conclusive
   failure, bind the Publication aggregate to the remote playlist, advance the Transfer and
   effect, and append the outcome event. A commit failure leaves `in_flight`, not
   a partial manifest.
6. **Continue one effect at a time.** Description, initial replacement, and each
   append chunk repeat C/provider/O with their own stable effect IDs. Only after
   all required effects are observed complete does one final local transaction
   mark the publication and Transfer complete.

An interrupted create is reconciled by the stable publication marker and exact
desired facts. Exactly one matching remote playlist can prove completion; more
than one is review-required. No match is not automatically proof of absence
after an ambiguous dispatch. The current recovery-marker search remains useful,
but #140 must not describe it as an at-most-once guarantee unless the adapter can
prove the remote result
([current publication and recovery tests](../../tests/test_transfer.py)).

The new ordering removes the current need to delete a newly created playlist
when local manifest retention fails. Such a compensating delete would itself be
an external effect, require separate authorization and journaling, and could
turn a recoverable local failure into an untracked destructive action.

### Required first tests

- Through `Transfer`, parameterize in-memory and APSW-backed store adapters over
  duplicate Source Occurrences and exact manifest order.
- Add named failpoints after Transaction P commit, during Transaction C commit,
  after C before adapter entry, after the adapter has applied the mutation, and
  at each statement/commit point in Transaction O. Reopen in a fresh process.
- Assert the durable classification is respectively unattempted (`prepared`),
  previous-or-uncertain, uncertain, uncertain, and uncertain-or-complete.
- Make reconciliation return zero, one, and two marker matches; only the single
  exact match advances automatically.
- Repeat the completed Transfer and assert no provider write, authority write,
  duplicate event, or second playlist.
- Exercise create, description, replace, and a two-chunk (>100 item) publication;
  crash every call boundary. A later chunk never causes an earlier chunk to
  repeat without proof.
- Run the same Preview and assert zero Effect Journal and effect-attempt rows.

## #141 — approve one Provisional Playlist atomically

### Remote evidence phase

Approval cannot lock Spotify and SQLite atomically. It must instead bind one
stable remote observation to one local transaction:

1. outside any database transaction, obtain the account identity;
2. read playlist head `H1`, then exact ordered items, then head `H2`;
3. require `H1 == H2`, reject unsupported/local/relinked/unavailable items, and
   compute the ordered-item digest;
4. resolve Correction track metadata outside a database transaction, without
   creating matching authority;
5. only then enter the local Approval transaction.

A remote change after `H2` is a later fact; the Approval row records the exact
head and ordered-item digest it approved. There is no honest claim of distributed
atomicity.

Current CSV Correction repair can replace playlist items during Approval. #141
must either route that mutation through a separately authorized Effect Journal
operation before the evidence phase or reject it with a next action. The final
Approval transaction itself performs zero Spotify writes, matching
[ADR-0002](../adr/0002-make-transfer-agent-native.md) and the existing Agent
Client Approval test
([Agent contract tests](../../tests/test_agent_contract.py)).

### One local authority transaction

Under `BEGIN IMMEDIATE`, the store must:

1. load the publication, immutable manifest revision, optional applied
   Qualification Draft, and every affected matching-knowledge identity;
2. compare account, publication state, manifest revision/digest, expected local
   revisions, reviewed `H2`, ordered-item digest, Correction digest, and any
   Qualification evidence;
3. insert or replay the stable Approval request ID;
4. classify every manifest occurrence as surviving, removed, corrected,
   colliding, or conflicting;
5. create Approved Matches, Rejected Matches, Corrections, Local Audio Identity
   associations, conflicts, Mirror establishment (for an approved Mirror), the
   Publication outcome, Qualification aggregate outcome, and compact event;
6. commit all changes once, or roll them all back.

Atomic storage failure and domain partial success are different. To preserve
current Transfer policy, a `needs_review` outcome may commit unambiguous
approved/rejected items and explicit conflict/collision facts together, while
ambiguous identities acquire no successful representation. The issue should say
this explicitly; if product intent is instead “any ambiguity rolls back all item
authority,” that is a policy change requiring a separate decision.

An exact repeated Approval request returns the retained outcome. It does not
re-read and reapply matching authority, increment revisions, or append another
event. A retained `needs_review` attempt may be followed after an explicit
supported repair with a new request identity and evidence. A different head,
manifest revision, Correction digest, or draft revision after terminal
`approved` or `abandoned` fails closed as an incompatible second Approval; it
does not become latest-write-wins.

### Required first tests

- Inject a failure after every local mutation category—Approval row,
  classifications, Approved Match, Rejected Match, Correction, Local Audio
  association, conflict, Mirror, Publication state, Qualification outcome, and
  event—and assert a canonical whole-store digest is unchanged.
- Run the existing surviving/removed/Correction/collision/conflict cases through
  both store adapters and compare exact domain outcomes, not SQL rows.
- Race two independent connections approving the same request. Exactly one
  commit occurs; the loser reloads and receives the identical terminal outcome.
- Race the same publication with different manifest/head/Correction evidence.
  One may commit; the incompatible request fails stale and creates no authority.
- Assert the provider adapter records zero writes during local Approval.
- Crash during COMMIT in a subprocess; reopen to the complete prior or complete
  next state, then run integrity and foreign-key checks.

## #142 — resume and apply one Qualification Draft

### Draft identity and local transitions

The durable draft identity must bind this exact tuple, either directly in the
stable ID digest or through an immutable identity row protected by a unique
constraint:

```text
schema version
Transfer ID
Spotify Account
Publication ID + manifest revision + digest
Spotify playlist ID + reviewed head
Source Selection digest
ordered selected Source Occurrence IDs + selection mode
```

The initial ID must not be only `Transfer + source reference`. A changed
manifest, account, playlist head, selected occurrence set, or selection digest is
new bounded evidence and cannot silently resume the old draft.

Every create, decision, revision, discard, or status transition is one short
optimistic transaction. Discard plus successor creation is one transaction that
marks the old draft terminal, inserts the new identity/items, and links both
sides. A unique successor constraint makes an exact repeated request return the
existing successor. No caller may coordinate two repository writes.

Keep, Correction, deferred, rejection, and exclusion remain non-authoritative.
The issue must define exclusion as either its own decision or the existing
explicit modifier of `deferred`; the database must not accept both meanings.
Corrections retain reviewed track facts but become matching authority only in the
later playlist-scoped Approval transaction.

Local Audio Identity handling needs the same precision. A draft may reference an
opaque evidence digest and an already existing account-scoped association, but it
must not create a new association. Fingerprints remain private, and source paths,
filenames, file URLs, and process-local audition handles never enter the store.

### Effect-journaled application

Application first computes the intended immutable next manifest and exact
ordered desired playlist representation. Transaction P binds that intended
manifest, current draft revision, current publication/manifest revision, current
playlist head, and one effect per provider call. The intended manifest is staged,
not active.

Each replacement/append call then follows claim/provider/observation. The effect
records the expected pre-call head and the observed post-call head. Resume accepts
the latest head only when it is the postcondition of this draft's immediately
preceding observed effect; any other head is review-required. Unmanaged playlist
items are preserved from one exact ordered observation included in the request
digest, not through set-based reconstruction that loses duplicates or order.

After every required effect is durably complete, one final transaction activates
the staged manifest revision, marks the draft `applied`, records the final head,
updates the Transfer projection, and emits the outcome event. Application still
creates no Approved Match, Correction authority, rejection authority, or Mirror
Approval. `approve_qualification` remains a later #141 transaction.

### Required first tests

- Parameterize the complete existing Qualification lifecycle suite over the
  in-memory and SQLite adapters, including duplicate occurrences, Preview-link,
  stale revision, changed evidence, discard/successor, and idempotent terminal
  replay.
- Race two decision writes at the same draft revision; one succeeds and one
  returns reload-before-retry with no merged guess.
- Fail every statement in discard/successor and prove neither half commits.
- For one- and multi-chunk apply, crash at every prepare/claim/provider/observe
  boundary. Reconcile exact pre-head, exact observed post-head, external edit,
  missing playlist, and ambiguous ordered state.
- Assert an interrupted application never activates the intended manifest early
  and never creates matching authority.
- Generate exactly 1,000 deterministic drafts spanning all lifecycle states,
  close/reopen, compare canonical ordered digests, run integrity and foreign-key
  checks, and prove the database contains none of the path/filename/handle denylist.

## #143 — create and maintain one Mirror

### Revision and lifecycle model

An Approved Mirror has one stable identity and immutable revisions. The active
binding is unique by `(account, source type, Source Selection reference)` and by
`(account, Spotify playlist)`. A revision links the exact ordered managed items,
manifest revision, expected/observed playlist head, and maintenance operation.
Source facts or remote facts never select a row by “latest timestamp.”

The minimum explicit lifecycle is:

```text
active -> maintenance_pending -> active
active -> drift_review_required -> active
active -> orphaned -> active (relink)
active -> orphaned -> released (keep as ordinary playlist)
active -> orphaned -> deletion_pending -> deleted
```

Terminal `released` and `deleted` records remain as history; “remove Mirror” must
not physically erase the only evidence of an explicit decision. A source-not-found
result may create `orphaned` in one local revision transaction. Source parse,
permission, validation, or transient I/O failures merely pause/fail the Transfer
and never infer orphaning.

### Operation-specific boundaries

| Explicit operation | Local preparation | Provider effects | Atomic local finalization |
| --- | --- | --- | --- |
| Ordinary source maintenance | Bind current Mirror/manifest revision, exact source selection, desired next manifest, and expected playlist head. | Replace, each append chunk, and description are separate effects. | Activate one new Mirror and manifest revision only after every effect is observed complete. |
| Drift restore | Bind the exact drift observation and explicit `restore` choice. | Journal replacement/chunks against the observed head. | New revision records restored head; matching authority is unchanged. |
| Drift revoke | Bind exact drift and explicit `revoke` choice. | None. | In one transaction revoke only the affected Approved Matches/Local Audio associations, create the next manifest/Mirror revision, and append the event. |
| Orphan keep | Bind current orphan revision and explicit `keep`. | None. | Mark `released`; retain playlist and Mirror history. |
| Orphan relink | Bind current orphan revision, explicitly selected new source, intended manifest, and current playlist head. | Journal replacement/chunks and description. | Activate the new source binding and next revision only after conclusive effects. |
| Orphan delete | Bind current orphan revision and explicit `delete` plus Spotify-write authorization. | One journaled playlist-delete effect. | Mark `deleted` only after observed/reconciled deletion; uncertainty stays pending/review-required. |

All desired managed items preserve Source Occurrence identity and order.
`dict.fromkeys`, URI sets, or track-ID sets cannot define the provider request,
because repeated occurrences are valid domain facts
([domain identity layers](../domain-model.md#identity-layers)).

One maintenance operation may contain several remote calls, so `maintenance_pending`
belongs to the operation while the previously completed Mirror revision remains
the last authoritative complete revision. Resume does not publish a partially
mutated remote playlist as a completed next Mirror revision. The new revision is
activated only after reconciliation proves every required effect.

### Required first tests

- Reuse the complete current Mirror/Drift/orphan suite through both store
  adapters, then assert immutable revision history and exact ordered duplicate
  occurrences.
- Crash create, replace, append, description, relink, restore, and delete at each
  effect boundary; reopen and reconcile without an inferred destructive choice.
- Race two maintenance requests at one Mirror revision. One can commit its plan;
  the other fails stale before a provider call.
- Inject source-not-found separately from malformed, permission, and transient
  source failures; only the exact not-found case becomes orphaned.
- Repeat keep, relink, delete, restore, and revoke. Exact repeats replay; changed
  intent or revision fails closed.
- Assert deletion uncertainty retains the Mirror, manifest, journal, and explicit
  choice; no cleanup code deletes the remote playlist or local history by inference.

## TDD seams and implementation order

The Operational Store should remain deep. `Transfer` asks for domain-named
operations on the same Interface established by #138; it does not receive an
APSW connection, SQL transaction, table repository, exported unit-of-work plan,
or generic `commit(change)` method. Private transaction composition stays inside
the Module.

| Seam | First red test | Production responsibility |
| --- | --- | --- |
| Store conformance factory | Run the same aggregate scenarios against in-memory and temporary APSW stores. | One binding-neutral interface and equivalent domain results. |
| Effect coordinator | Table-drive prepared, claim, observe, uncertain, reconcile, and terminal replay. | Stable effect/attempt identity and legal transitions; no provider policy. |
| Recording provider adapter | Assert `txn_state == NONE` at every read/write and coordinate barriers around dispatch/application/return. | Existing Spotipy adapter behind the same semantic effect calls. |
| Deterministic identity/codec | Golden digests for manifests, ordered items, draft identity, approval request, and effect requests. | Versioned canonical encoding; no wall clock, Python hash, rowid, or insertion-order identity. |
| Transaction failpoint | Raise after each repository mutation and during commit. | Test-only instrumentation below the deep interface; no production user toggle. |
| Reconciler | Zero/one/multiple remote candidates, exact/mismatched head, missing target, and unsupported item. | Pure classification plus bounded provider observations; never guessed replay. |
| Privacy projection | Deny raw identifiers/paths/SQL/exceptions while preserving category, count, lifecycle, and next action. | Existing CLI/web/Agent renderers consume domain outcomes, never journal rows. |

Implementation order follows the issue dependencies: #140 establishes the
effect protocol; #141 makes the first whole-authority local transaction; #142
reuses both for draft application; #143 reuses both for multi-revision Mirror
maintenance. #142 and #143 are separate Operational-authority lanes and must not
change the interface concurrently even though both depend on #141
([issue frontier](2026-08-16-operational-store-issue-frontier.md)).

## Cross-platform failure and durability matrix

The exact supported cells are the reviewed native artifact catalog introduced by
#167; at this baseline it contains 25 conventional-GIL CPython 3.10–3.14 cells
across Linux x64/arm64, macOS Intel/arm64, and Windows x64. A wheel's existence is
not persistence evidence
([artifact catalog](../../djsupport/contracts/apsw-runtime-artifacts.v1.json),
[APSW integration contract](2026-08-16-apsw-operational-store-integration-contract.md)).

1. Run the focused store/effect/Approval/Qualification/Mirror conformance tests on
   every admitted native cell. Fail rather than skip when the runtime qualifier
   or artifact admission rejects the cell.
2. Run the subprocess crash/commit suite natively on every OS/architecture
   family, plus Linux Python 3.10 and 3.14 edges. A child process opens its own
   connection; no connection crosses `fork`. Windows uses a spawned subprocess,
   not a POSIX-only signal assumption.
3. Coordinate contention and crash locations with pipes/events and durable test
   barriers, not sleeps. Hold `BEGIN IMMEDIATE` on one independent connection to
   prove bounded busy translation on another.
4. For local transaction crashes, accept only the complete prior or complete
   next canonical domain digest. For external effects, accept only the durable
   journal classifications specified above; “test did not see a duplicate” is
   not recovery proof.
5. After every process-kill case, reopen from a fresh process and require full
   `integrity_check`, empty `foreign_key_check`, supported migration registry,
   exact ordered domain digest, and no open transaction.
6. Inject typed APSW/SQLite busy, snapshot-stale, constraint, full-disk, I/O,
   read-only, corruption, and unknown failures at adapter boundaries. Translate
   by APSW `result` and `extendedresult`, retain the private chained cause, and
   expose only stable path-free store errors
   ([APSW exceptions](https://rogerbinns.github.io/apsw/exceptions.html)).
7. Scale tests use deterministic synthetic facts and correctness assertions, not
   wall-clock pass thresholds. Keep the million-event/large-store run in its
   owning schema/diagnostics lane; #142 still owns its exact 1,000-draft reopen
   proof.

WAL commits append a commit record, and `synchronous=FULL` syncs each WAL commit;
checkpointing is a later operation. Tests must not delete or detach `-wal` or
`-shm`, and must not treat a filesystem copy of the main database as a valid
snapshot
([SQLite WAL operation](https://sqlite.org/wal.html#how_wal_works),
[SQLite WAL file lifecycle](https://sqlite.org/wal.html#the_wal_file)).

## Privacy and publication constraints

- The Operational Store, WAL/SHM sidecars, snapshots, backups, restore staging,
  diagnostics, query exports, legacy JSON, reports, and every generated failure
  artifact are private user data. They never enter Git or package archives
  ([ADR-0001](../adr/0001-keep-user-data-out-of-the-repository.md),
  [private storage](../storage.md)).
- Account, source, playlist, track, manifest, Correction, fingerprint, and
  Effect Journal facts may be necessary inside the private store. Public and
  Agent-facing output exposes only approved aggregate counts, opaque bounded
  work IDs, lifecycle states, stable reason codes, and permitted next actions.
- Configuration and Spotipy-managed credentials remain outside the Operational
  Store. Effect requests and observations never retain tokens, request headers,
  raw HTTP bodies, raw exceptions, SQL text/bindings, or native/database paths.
- Qualification retains no source path, filename, `file://` URL, audio bytes,
  local audition handle, or unapproved fingerprint association. All repository
  fixtures are invented; no owner-derived database or regression evidence is
  admissible.
- Operational Events are rebuildable analytics input, not authority. Authority
  logic may not query them, and deleting analytics history cannot cascade into
  Transfers, publications, matching knowledge, drafts, effects, Approvals, or
  Mirrors.
- None of #140–#143 authorizes a live Spotify/Beatport call, owner Rekordbox/audio
  read, playlist mutation, tag, GitHub Release, package publication, advisory,
  or public security-fix merge. Synthetic provider adapters remain the default
  evidence surface.

## Actionable issue amendments

### Amend #140

1. Name `prepared`, `in_flight`, observed, uncertain, reconciled, and
   review-required states; add crash hooks after prepare, after claim, after
   provider application, and during observation commit.
2. Require a local publication identity and immutable manifest revision that
   exist before the remote playlist ID.
3. State whether the issue journals all Snapshot writes—create, description,
   replace, and append chunks. “Publish one Snapshot” should not leave the calls
   after creation on the old checkpoint model.
4. Define zero/one/multiple reconciliation outcomes and prohibit automatic replay
   of an uncertain create without proof.
5. Remove compensating remote deletion from local retention failure unless it is
   a separately authorized and journaled explicit effect.
6. Require the per-effect OS claimant lock across claim, provider call, and
   observation. A busy lock returns `effect_attempt_active`; a resume may mark
   `in_flight` uncertain only after acquiring the lock and re-reading the exact
   durable attempt.

### Amend #141

1. Define the stable Approval request identity and exact terminal replay result.
2. Require `head -> ordered items -> head` remote evidence and bind its ordered
   digest to the local transaction.
3. Move Correction playlist mutation out of authority-only Approval into a
   separately authorized, Effect Journal-backed application step.
4. Decide explicitly whether unambiguous items may commit in a `needs_review`
   outcome. The current policy supports that while ambiguous items remain
   non-authoritative.
5. Name every expected revision checked inside the transaction, including
   publication/manifest, applicable draft, and affected matching identities.

### Amend #142

1. Define the complete immutable draft identity tuple and selected-occurrence
   digest; do not leave identity as Transfer/source reference alone.
2. Decide whether exclusion is a first-class decision or only an explicit
   deferred-item modifier.
3. Require one journal effect per replacement/append call with expected and
   observed heads, plus staged-versus-active manifest semantics.
4. Clarify that Local Audio Identity references round-trip but drafts never create
   account-scoped authority; only Approval can do so.
5. Define the 1,000-draft proof as deterministic populate, close/reopen, canonical
   digest, integrity/foreign-key checks, and privacy denylist—not only row count.

### Amend #143

1. Define Mirror lifecycle states and require retained terminal history for keep
   and delete instead of physical relationship removal.
2. Define when a multi-effect maintenance operation increments the authoritative
   Mirror revision: only after all effects are conclusively complete.
3. Enumerate journaled create/replace/append/description/relink/restore/delete
   calls and their reconciliation evidence.
4. Separate local-only revocation/keep/orphan transitions from provider effects,
   and require compare-and-swap revisions for both.
5. Distinguish exact source-not-found from validation, permission, parse, and
   transient failures; only the former may produce orphaning.
6. Require ordered duplicate Source Occurrences throughout Mirror replacement;
   URI or track-ID deduplication is not an implementation shortcut.

With these amendments, the four labels can mean “ready for an implementation
agent after declared dependencies,” rather than “policy-complete but still
requiring transactional design choices during coding.”

## Primary sources

- DJ Support:
  [program #125](https://github.com/spontain112/djsupport/issues/125),
  [implementation parent #128](https://github.com/spontain112/djsupport/issues/128),
  [#138](https://github.com/spontain112/djsupport/issues/138),
  [#139](https://github.com/spontain112/djsupport/issues/139),
  [#140](https://github.com/spontain112/djsupport/issues/140),
  [#141](https://github.com/spontain112/djsupport/issues/141),
  [#142](https://github.com/spontain112/djsupport/issues/142), and
  [#143](https://github.com/spontain112/djsupport/issues/143).
- Repository truth:
  [ADR-0001](../adr/0001-keep-user-data-out-of-the-repository.md),
  [ADR-0002](../adr/0002-make-transfer-agent-native.md),
  [ADR-0005](../adr/0005-use-one-local-transactional-operational-store.md),
  [domain model](../domain-model.md), [lifecycles](../lifecycles.md),
  [storage](../storage.md),
  [Transfer](../../djsupport/transfer.py),
  [Transfer tests](../../tests/test_transfer.py), and
  [Qualification tests](../../tests/test_qualification.py).
- SQLite:
  [transactions](https://sqlite.org/lang_transaction.html),
  [isolation](https://sqlite.org/isolation.html),
  [WAL](https://sqlite.org/wal.html),
  [savepoints](https://sqlite.org/lang_savepoint.html),
  [`RETURNING`](https://sqlite.org/lang_returning.html),
  [foreign keys](https://sqlite.org/foreignkeys.html), and
  [integrity PRAGMAs](https://sqlite.org/pragma.html#pragma_integrity_check).
- APSW 3.53.4.0:
  [connection and transaction API](https://rogerbinns.github.io/apsw/connection.html),
  [execution model](https://rogerbinns.github.io/apsw/execution.html),
  [SQLite/DB-API differences](https://rogerbinns.github.io/apsw/pysqlite.html),
  and [exceptions](https://rogerbinns.github.io/apsw/exceptions.html).
