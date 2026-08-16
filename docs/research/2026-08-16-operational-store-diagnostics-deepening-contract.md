# Operational Store diagnostics and Qualification deepening contract

**Date:** 2026-08-16

**Status:** implementation-readiness research; both delivery tickets remain
blocked by #147

**Baseline:** [`origin/main` at `3e6ae7f`](https://github.com/spontain112/djsupport/commit/3e6ae7f6157364eeedaa2667d2a1deabed9efcee)

**Source policy:** repository truth plus first-party SQLite and APSW 3.53.4.0
documentation only

**Contract precedence:** The ready-to-paste issue amendments are the proposed
normative execution delta; the preceding sections explain and source that delta.
Once an amendment is accepted into an issue, the issue body is authoritative.
Do not combine conflicting versions—reconcile the amendment first.

## Decision

[#130](https://github.com/spontain112/djsupport/issues/130) and
[#132](https://github.com/spontain112/djsupport/issues/132) can be made
implementation-ready now, but neither can start before
[#147](https://github.com/spontain112/djsupport/issues/147) is complete on an
accepted commit.

- #130 remains a conditional deletion test, not a mandatory extraction. The
  current evidence shows a coherent, substantial Qualification cluster inside
  `Transfer`, but the test must be rerun against the post-#147 interface. If a
  private module does not hide the complete invariant set without becoming a
  second policy interface, close #130 with evidence.
- #132 needs one correction to its execution lane. Reading diagnostics is
  query-only, but installing versioned SQL views and explicitly deleting event
  history are writes. Permit exactly one diagnostics-owned schema migration and
  one expected-epoch/count maintenance operation. Do not expose a generic SQL,
  event-write, or Operational Store mutation interface.
- “Spotify request cost” means locally retained **claimed request-attempt
  units** and requested-item units, with uncertainty kept explicit. A durable
  claim is committed immediately before one bounded adapter call; a crash can
  occur after that commit but before the network call, so the unit is a
  conservative upper bound and not proof that Spotify received a request. It
  does not mean money, Spotify billing, rate-limit quota units, or an estimate
  of provider cost.
- Analytics deletion has two truthful layers. The required result is atomic
  logical deletion of the previewed Operational Events without changing any
  authority or Effect Journal row. SQLite-level overwrite/checkpoint facts are
  reported separately and never imply erasure from backups, snapshots, retained
  generations, or physical media.

This packet does not change production authority, define a public Agent Client
contract, authorize telemetry, or authorize live/owner-data verification.

## Current-state evidence

### Dependency and implementation state

Both issue bodies still declare #147 as their blocker. ADR-0005 makes compact
Operational Events private and non-authoritative, allows explicit analytics
history deletion, and keeps Transfer as policy authority
([ADR-0005](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/docs/adr/0005-use-one-local-transactional-operational-store.md#L3-L30)).
The storage guide likewise says views are rebuildable projections and deletion
must not alter Transfers, Approval, Matching Knowledge, publication state, or
Effect Journal recovery facts
([storage contract](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/docs/storage.md#L198-L209)).

Current `origin/main` contains runtime qualification and artifact delivery under
`djsupport/operational_store/`, but no production Operational Event table,
diagnostics view, diagnostics document, or analytics-deletion implementation.
In particular,
[`djsupport/operational_store/qualification.py`](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/djsupport/operational_store/qualification.py)
already means **SQLite runtime qualification**. #130 must not reuse
`qualification.py` or create an import name that makes runtime qualification and
Transfer Qualification ambiguous.

Privacy scaffolding is ahead of the implementation: current ignore rules and
repository tests already cover `djsupport-operational-events*`,
`djsupport-analytics*`, `djsupport-diagnostics*`, and query exports
([`.gitignore`](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/.gitignore#L30-L51),
[`tests/test_repository_privacy.py`](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/tests/test_repository_privacy.py#L10-L86)).
Those are necessary delivery guards, not evidence that a diagnostics projection
is private by construction.

### Exact current deletion-test inventory for #130

At the pinned baseline:

| Evidence | Exact current fact | Why it matters after #147 |
| --- | --- | --- |
| Domain values | Eight Qualification-specific value types live in `transfer.py`: decision, status, request, durable draft state, item, view, apply outcome, and Approval outcome ([types](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/djsupport/transfer.py#L351-L543), [Approval outcome](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/djsupport/transfer.py#L858-L869)). | The public types must continue to be obtained from `djsupport.transfer`; an internal module must not become a second caller-facing seam. |
| Transfer lifecycle | `Transfer` presents nine Qualification operations: obtain, view, link, record, audition, discard, supersede, apply, and approve. | These nine existing operations remain the only public policy interface. Do not disguise their real lifecycle complexity behind an untyped `execute(command)` method. |
| Hidden implementation | The same class contains twelve Qualification-specific helpers: Transfer selection, three evidence digests, item construction, audition preflight, view construction, Approval serialization/deserialization/summary, application projection, and chunk application ([workflow span](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/djsupport/transfer.py#L2693-L4555)). | These helpers are the candidate implementation to concentrate, provided the post-#147 Effect Journal and store operations can stay internal. |
| Old persistence interface | `TransferStorage` has four Qualification-specific methods: load, save, atomically save successor, and list by playlist ([protocol](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/djsupport/transfer.py#L1143-L1169)). | Re-inventory the accepted Operational Store after #147. A deepening must consume it; it must not wrap it in a second public repository interface. |
| Behavioral tests | `tests/test_qualification.py` contains exactly 23 public-behavior tests spanning attention selection, decisions, application, Approval, duplicate occurrences, drift/conflict stops, restart, idempotency, linking, concurrency, migration, discard/supersession, redaction, and audition retirement ([test module](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/tests/test_qualification.py)). | These tests stay at the Transfer seam. They are not replaced by tests of a new internal class. |
| Thin clients | Agent rendering has eight Qualification operations and web has ten Qualification routes, all intended to render Transfer behavior ([Agent adapter](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/djsupport/agent.py#L639-L916), [web adapter](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/djsupport/web.py#L670-L969)). | No client may import the internal module or learn store ordering, revision, digest, or Effect Journal rules. |
| Leaked coordination | CLI currently performs one direct Qualification load and web performs two direct Qualification loads to recover context ([CLI](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/djsupport/cli.py#L794-L808), [web](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/djsupport/web.py#L580-L661)). | Recheck these after #147. #130 passes only if context recovery is Transfer-owned or a non-policy Runtime Assembly lookup; clients must not reconstruct lifecycle policy. |

Line count is not the depth test. The evidence is the set of invariants and
ordering knowledge that would have to reappear outside the candidate module if
it were deleted. A passing design must increase **Depth** by hiding that
complexity behind a smaller internal Interface, increase **Leverage** because
the same hidden rules serve multiple Transfer operations, and improve
**Locality** by keeping each invariant in one place. Moving names or lines
without those three effects fails the test.

## #130 contract: rerun the deletion test after #147

### Invariant families that must move together

The post-#147 inventory must account for all of these families before any
refactor begins:

1. Rekordbox-only eligibility, completed Mirror eligibility, bounded Transfer
   and Source Selection ownership, and unchanged browser-origin behavior.
2. Draft identity and lineage: Transfer, Batch when present, account, playlist,
   playlist head, Publication Manifest, selected Source Occurrences, supersedes,
   successor, and optimistic revision.
3. Selection, manifest, and audition-evidence digests; exact order and duplicate
   Source Occurrences; evidence-changed stop conditions.
4. Attention selection and the non-authoritative keep, Correction, deferred,
   exclusion, and rejection state machine. Pending/deferred work still blocks
   apply and Approval.
5. Explicit private-source authorization, bounded audition identity, unavailable
   media outcomes, and process-local handle invalidation without persistence;
   no path, filename, audio, fingerprint, account/playlist/track identifier, or
   private source fact may cross a privacy-redacted client interface.
6. Explicit Spotify-write authorization, stable playlist-head validation, one
   Effect Journal entry per bounded Spotify call, pause/resume/reconciliation,
   and idempotent completion without guessing.
7. Separate playlist-scoped Approval, stable manifest/head validation,
   collision/conflict handling, authority-only commit, and replay of an already
   completed outcome.

The current code repeats account, manifest, selection, playlist-head, status,
and review-required checks across obtain, link, record, apply, and approve. #147
will change their persistence mechanics, so the merged #147 commit—not this
baseline—decides whether those repetitions remain and whether deepening is
earned.

### Accepted module shape if the test passes

- Keep `Transfer` as the external seam and preserve its nine Qualification
  operations and public result types.
- Use one private Transfer-owned implementation module, recommended name
  `djsupport/_qualification_workflow.py`. Do not use
  `djsupport/operational_store/qualification.py`, which already owns SQLite
  runtime qualification.
- Only `Transfer` may construct/call the private module. CLI, web, Agent Client,
  Runtime Assembly, and Operational Store adapters must not import it.
- Inject the accepted Operational Store, Spotify and local-audition Interfaces,
  clock, retry/pause controls, and Effect Journal capability. Do not construct
  production Adapters inside the module.
- Keep matching/publication/Approval policy in this Transfer-owned
  implementation. The Operational Store retains facts and performs atomic units
  of work; it does not decide lifecycle transitions.
- Do not create a generic command bus or a second public “Qualification
  interface.” Collapsing nine typed operations into one untyped method is not
  depth; it merely moves the interface knowledge into command values and
  ordering rules.

### Exact deletion-test procedure

Run this only on the accepted #147 commit:

1. Record the fixed commit and inventory every Qualification production symbol,
   every non-test caller, every Operational Store operation it uses, and every
   existing Transfer-level behavior test. Include the command output in the
   issue/PR evidence.
2. Write the first failing Transfer tests for any invariant not already covered;
   parameterize only the internal recovery mechanics over in-memory and SQLite
   adapters.
3. Prepare the candidate private module without changing client-visible
   behavior. Preserve the complete Transfer, Agent, web, CLI, privacy, backup,
   migration, and package suites.
4. In a throwaway deletion diff, remove the candidate module. Fill this evidence
   table for each of the seven invariant families: `lost behavior`, `where the
   rule must be reimplemented`, `affected Transfer operation`, and `public test
   that proves it`. The module passes only when deletion forces substantial
   policy/recovery knowledge back into `Transfer` or duplicates it across
   callers/adapters.
5. Fail the deletion test if removing the module eliminates complexity, leaves
   only delegation glue, requires callers to learn the private module, or moves
   policy into the Operational Store. Close #130 with that evidence and no
   forced refactor.
6. If it passes, delete superseded shallow tests. Keep public behavior at the
   Transfer seam; retain narrower direct tests only for crash/recovery mechanics
   that cannot be observed more precisely through Transfer.

A release-note record is needed only if distributable behavior or packaging
changes. A behavior-preserving internal move alone does not earn a user-facing
release claim.

## #132 contract: allowed diagnostics and deletion seam

### Resolve the issue's read-only-lane contradiction

The existing issue asks for SQL views and deletion while saying the lane only
consumes a read-only query interface. Those requirements cannot all be true
without a narrow write seam. Permit exactly:

1. one versioned, diagnostics-owned Operational Store migration that installs
   or replaces named ordinary views; and
2. `delete_analytics_history(expected_epoch, expected_event_count)`, a typed
   maintenance operation implemented by the Operational Store.

All document rendering uses a read-only diagnostics query interface. There is
no generic `execute_sql`, view builder, event writer, table delete, predicate,
or user-supplied query. Transfer remains the only ordinary event producer and
the only policy authority.

SQLite ordinary views are read-only unless writable behavior is deliberately
added with `INSTEAD OF` triggers. Define every view with an explicit column-name
list and add no such triggers
([SQLite `CREATE VIEW`](https://sqlite.org/lang_createview.html)). The view
definitions live in the application migration registry, not in diagnostics
requests.

### Compact Operational Event allowlist

Implement one `STRICT` event table so SQLite enforces declared storage types and
integrity checks cover type violations
([SQLite STRICT tables](https://sqlite.org/stricttables.html)). The physical
schema may use the post-#147 table names, but its logical fields are frozen here:

| Field | Allowed meaning |
| --- | --- |
| `commit_sequence` | Non-negative Operational Store commit sequence inherited from the foundation schema. It is never emitted and is not reset or reused when analytics history is deleted. |
| `event_ordinal` | Non-negative event position within one commit sequence. Together with `commit_sequence`, it remains the frozen primary key `(commit_sequence, event_ordinal)`. |
| `analytics_epoch` | Non-authoritative integer generation copied from diagnostics metadata when the event is appended. |
| `recorded_at_utc` | Canonical internal UTC fact instant. It is never used to choose a latest state, emitted, or grouped in 0.7. |
| `category` | One of the six categories below; enforced by a constraint/registry. |
| `source_kind` | Exactly `rekordbox`, `beatport_chart`, `beatport_label`, or `not_applicable`; never null. No display label or source reference. |
| `phase` | `intake`, `matching`, `publication`, `qualification`, `qualification_apply`, `approval`, `mirror_maintenance`, or `recovery`. |
| `outcome` | A category-scoped code from the table below. Never provider/user text. |
| `reason_code` | A category-scoped stable code from the table below. Never a raw exception, report message, or source fact. |
| `attempt_units` | Non-negative integer. Exactly `1` on a `spotify_request` claim and `0` on its observation; zero for non-request events. A claim is committed immediately before the bounded adapter call, but a crash can intervene, so this is a conservative claimed-attempt unit rather than proof that a network request started. |
| `item_units` | Non-negative integer. For `spotify_request`, it is set only on the claim and is the number of query/item inputs presented to that bounded attempt, not unique recordings; observations use zero. It is exactly `1` for proposal/match subjects and `0` for Transfer/resume/effect subjects. Unknown request size is `0`, never null. |
| `subject_kind` | Closed private enum identifying the event subject family: `transfer`, `spotify_request`, `qualification_proposal`, `resume`, `effect`, or `match_fact`, matching the six categories one-to-one. It is never emitted. |
| `subject_id` | Required opaque, store-owned identity for one subject within its family. It may be a random token or keyed digest, but never a raw Transfer, Batch, Effect, account, source, playlist, track, provider, or filesystem identifier. It is copied into the event as a scalar, is never emitted, and is not a foreign key. |
| `subject_revision` | Non-negative integer that increases monotonically for each `(category, subject_kind, subject_id)`. A request claim and its observation have separate revisions; proposal/effect latest-state projections select the greatest revision. |

Enforce
`UNIQUE(category, subject_kind, subject_id, subject_revision)`. Recording is
insert-or-verify: retrying the same key succeeds only when every logical field
is identical; a mismatched duplicate is an integrity failure and rolls back the
associated local authority transaction. The event table has **no foreign keys
to authority or across subject families**. Authority deletion therefore cannot
rewrite an event, and ordinary history remains append-only until the explicit
whole-history deletion operation runs.

No event may contain an arbitrary JSON payload, free-form detail/message,
provider response, exception text, SQL, path, filename, source metadata,
Spotify URI, playlist/account identifier, fingerprint, credential, report, or
diagnostics document.

The category registry is:

| Category | Exact v1 outcomes | Exact v1 reason vocabulary |
| --- | --- | --- |
| `transfer_transition` | `completed`, `paused`, `partial_success`, `failed`, `abandoned`, `review_required` | `none`, `user_pause`, `store_busy`, `stale_revision`, `source_unavailable`, `account_changed`, `playlist_changed`, `manifest_changed`, `selection_changed`, `review_conflict`, `provider_failure`, `integrity_failure` |
| `spotify_request` | `claimed`, `observed_success`, `observed_failure`, `observed_rate_limited`, `uncertain` | `none`, `retryable_provider_failure`, `quota_or_rate_limit`, `non_retryable_provider_failure`, `response_unknown`, `observation_missing`, `reconciliation_required` |
| `proposal_transition` | `proposed`, `kept`, `corrected`, `rejected`, `deferred`, `excluded`, `approved`, `unresolved`, `collision`, `conflict` | `none`, `user_decision`, `explicit_correction`, `explicit_exclusion`, `explicit_rejection`, `playlist_review`, `approval_conflict`, `match_collision`, `no_acceptable_candidate` |
| `resume_transition` | `resumed`, `already_complete`, `paused`, `completed`, `review_required`, `failed` | `none`, `checkpoint`, `prepared_effect`, `in_flight_effect`, `observation_pending`, `reconciliation_required`, `stale_revision` |
| `effect_transition` | `prepared`, `in_flight`, `observed_complete`, `observed_not_applied`, `uncertain`, `reconciled_complete`, `reconciled_not_applied`, `review_required` | `none`, `not_attempted`, `call_claimed`, `remote_completion_proven`, `remote_not_applied_proven`, `remote_state_ambiguous`, `provider_failure` |
| `match_outcome` | `proposed`, `approved`, `rejected`, `corrected`, `unresolved`, `reused`, `collision`, `conflict` | `exact`, `shorter_version`, `fallback_version`, `approved_reuse`, `approved_local_audio_reuse`, `correction`, `no_acceptable_candidate`, `unavailable`, `match_collision`, `approval_conflict` |

Adding a source, phase, outcome, or reason is a reviewed registry/schema change.
An unknown value rolls back the associated local transaction, leaving every
authority row at its previous revision. The event may be committed in the same
local transaction as the domain change, but no domain operation may later read
an event to make an authority or recovery decision.

### Required read-only views

Install ordinary, explicitly named views with only aggregate columns:

1. `diagnostic_transfer_outcomes(source_kind, phase, outcome, reason_code,
   event_count)`;
2. `diagnostic_spotify_request_cost(source_kind, phase, request_state,
   reason_code, claimed_attempt_units, requested_item_units,
   uncertain_attempt_units)`;
3. `diagnostic_proposal_progression(source_kind, phase, outcome, reason_code,
   item_units, event_count)`;
4. `diagnostic_resume_outcomes(source_kind, phase, outcome, reason_code,
   event_count)`;
5. `diagnostic_effect_transitions(phase, outcome, reason_code, event_count)`;
6. `diagnostic_match_outcomes(source_kind, phase, outcome, reason_code,
   item_units, event_count)`; and
7. `diagnostic_incomplete_effects(phase, latest_outcome, reason_code,
   effect_count)`.

All seven derive only from Operational Events. Proposal progression selects the
greatest `subject_revision` per proposal before grouping, so one proposal is not
counted once per transition. The incomplete-effect view likewise selects the
greatest revision per effect and includes only `prepared`, `in_flight`,
`uncertain`, and `review_required`. It never reads the Effect Journal. After
analytics-history deletion this view truthfully becomes empty while Transfer
continues to recover from the untouched authoritative Effect Journal.

Every view groups inside SQL, exposes no private subject key, and has no
per-event row. For one `spotify_request` subject, revision zero is the durable
claim and a later revision is its conclusive observation or explicit uncertain
observation. The cost view joins each claim to its greatest revision and counts
the claim exactly once. A claim with no later observation—such as after a crash
between claim commit and adapter result—is projected as `request_state =
uncertain`, `reason_code = observation_missing`; an explicit uncertain
observation is also uncertain. Claimed-attempt and requested-item units are
therefore retained, conservative local evidence, never money, provider quota,
billing, exact network-start counts, or Spotify internal accounting.

### Consistent and private projection

- Query all seven views and analytics metadata in one explicit read transaction,
  exhaust/close every cursor, then render the document. SQLite guarantees that
  an active read transaction continues to see one historic snapshot while
  another connection writes
  ([SQLite transactions](https://sqlite.org/lang_transaction.html#read_transactions_versus_write_transactions)).
- Obtain the connection only through the accepted Operational Store query
  interface. If #132 opens a dedicated connection, open it with APSW
  `SQLITE_OPEN_READONLY` and require `Connection.readonly("main") is True`
  ([APSW read-only open](https://rogerbinns.github.io/apsw/example.html#opening-the-database),
  [`Connection.readonly`](https://rogerbinns.github.io/apsw/connection.html#apsw.Connection.readonly)).
  `PRAGMA query_only` alone is insufficient because SQLite documents that it can
  still checkpoint or commit
  ([SQLite `query_only`](https://sqlite.org/pragma.html#pragma_query_only)).
- Verify the connection returns to no transaction with APSW `txn_state()` after
  all rows are consumed
  ([APSW `txn_state`](https://rogerbinns.github.io/apsw/connection.html#apsw.Connection.txn_state)).
- Build the JSON from literal keys and typed aggregate values. Do not serialize
  arbitrary rows, expose a database connection, accept filters by private ID, or
  echo exception text.

The exact experimental document is:

```json
{
  "contract": "djsupport.local-diagnostics",
  "version": "0.7-experimental-1",
  "stability": "experimental",
  "analytics_epoch": 0,
  "event_count": 0,
  "transfer_outcomes": [],
  "spotify_request_cost": [],
  "proposal_progression": [],
  "resume_outcomes": [],
  "effect_transitions": [],
  "incomplete_effects": [],
  "match_outcomes": []
}
```

Rows contain only the view columns above and are explicitly ordered by their
category columns. The document excludes event/time IDs; Transfer, Batch, Draft,
Effect, account, source, playlist, and track identifiers; paths and source
metadata; Spotify URIs; fingerprints; credentials; SQL/schema/query plans; raw
exceptions; and per-event details. Stable redacted reason codes are permitted.
The document is private local user data, is ignored and package-rejected, and
is not accepted by `AgentTransferContract` or any stable Agent Client renderer.

### Explicit analytics-history deletion

Use a two-step, typed maintenance flow:

1. `preview_analytics_history_deletion()` reads one snapshot and returns only
   `analytics_epoch`, `event_count`, and category counts.
2. `delete_analytics_history(expected_epoch, expected_event_count)` begins one
   bounded `BEGIN IMMEDIATE` transaction, rechecks both values, and fails with a
   redacted `analytics_history_changed` outcome if either differs. It then
   deletes every Operational Event, obtains the directly deleted row count from
   APSW `Connection.changes()`, increments the analytics epoch, and commits
   ([APSW `changes`](https://rogerbinns.github.io/apsw/connection.html#apsw.Connection.changes),
   [SQLite `DELETE`](https://sqlite.org/lang_delete.html)).

The operation has no predicate, date range, category selector, cascade into
authority, or caller-supplied SQL. On success:

- all seven event-derived views are empty;
- Transfer, Batch, Qualification, Publication, Approval, Matching Knowledge,
  Mirror, Effect Journal, migration, backup, and authority-pointer rows and
  revisions have a canonical authority projection that is exactly unchanged;
- later ordinary recording uses the incremented epoch; and
- the result reports `deleted_events`, new `analytics_epoch`, and only redacted
  maintenance status.

Logical deletion is not automatically a forensic-erasure claim. SQLite says a
plain delete normally leaves content in reusable space, while enabling
`secure_delete` before deletion overwrites deleted content with zeros
([SQLite `secure_delete`](https://sqlite.org/pragma.html#pragma_secure_delete),
[SQLite `VACUUM`](https://sqlite.org/lang_vacuum.html)). Therefore the
maintenance connection must enable and verify `secure_delete=ON` before the
delete. After commit it may request one bounded `TRUNCATE` checkpoint through
the canonical Operational Store checkpoint coordinator. A successful TRUNCATE
checkpoint reduces the WAL to zero bytes; an active reader can block completion
([SQLite WAL checkpoints](https://sqlite.org/pragma.html#pragma_wal_checkpoint),
[WAL reader behavior](https://sqlite.org/wal.html#concurrency)).

Report these facts separately as `secure_delete_verified` and
`wal_cleanup: complete|pending`. If the checkpoint is busy, logical deletion
stays committed and the result truthfully reports pending WAL cleanup; it does
not delete sidecars, bypass the maintained checkpoint policy, or restore event
rows. Do not run `VACUUM` implicitly: SQLite documents that it rewrites the
database, may require up to twice the database size, and fails with an open
transaction. Existing backups, snapshots, rollback generations, and physical
storage may retain older bytes and require their own explicit retention action.

## The 1,000,000-event correctness proof

This is a correctness and privacy test, not a latency contest.

1. Generate exactly 10,000 invented Transfers with 100 events each in bounded
   production-shaped commits. Each Transfer contributes 1
   `transfer_transition`, 20 `spotify_request`, 20 `proposal_transition`, 5
   `resume_transition`, 4 `effect_transition`, and 50 `match_outcome` rows.
   The exact category totals are therefore 10,000; 200,000; 200,000; 50,000;
   40,000; and 500,000—exactly 1,000,000.
2. Cycle source, phase, outcome, and reason codes arithmetically over the closed
   registries. Of each Transfer's 20 `spotify_request` events, create eleven
   durable claims and nine later observations: seven successful, one failed,
   and one explicitly uncertain. Leave two claims without an observation to
   model a crash before conclusive recording. Claims use `attempt_units=1` and
   `item_units=(request_index mod 20)+1`; observations use zero for both. Across
   the fixture this gives 110,000 claimed-attempt units, 70,000 observed-success
   units, 10,000 observed-failure units, and 30,000 uncertain units (10,000
   explicit plus 20,000 missing observations). Compute every expected aggregate
   with an independent formula, not by calling the production projection code.
3. Put distinctive invented private markers only in the referenced synthetic
   authority rows. Assert no marker, identifier, forbidden key, path-shaped
   value, URI, fingerprint, credential-shaped value, SQL, or exception text
   appears in the document. Assert output row cardinality is bounded by the
   category vocabularies rather than event count.
4. Query all views twice in one read snapshot, close/reopen the store, query from
   a second read-only connection, reinstall the versioned views in a fresh
   synthetic store, and compare the same explicitly ordered typed tuples and
   canonical digest each time. Repeat the projection with SQLite
   `reverse_unordered_selects` first off and then on; both results must be
   identical because every consumer-visible query has an explicit complete
   ordering
   ([SQLite `reverse_unordered_selects`](https://sqlite.org/pragma.html#pragma_reverse_unordered_selects)).
5. Run full integrity and foreign-key checks. Take and restore the accepted
   Online Backup snapshot, then compare the same event count and diagnostic
   projection. Do not compare SQLite bytes, rowids, query plans, or WAL layout.
6. Preserve at least one incomplete Effect Journal row and its corresponding
   event revisions. Capture the canonical authority projection, preview
   deletion, delete with the exact epoch/count, and assert APSW reports
   1,000,000 directly deleted events. Prove the canonical authority projection
   is exactly unchanged while all seven event-derived views—including
   incomplete effects—become empty. Then exercise Transfer recovery for that
   Effect Journal entry to prove authority remains available without reading an
   event or diagnostic view.
7. Append one new event in the next epoch and prove recording/projection still
   works. Exercise stale epoch, stale count, busy, interrupted delete, commit
   fault, and blocked checkpoint outcomes without partial history deletion or
   authority change.
8. Record elapsed time, database/WAL size, and aggregate query plans only as
   non-gating diagnostic evidence. Do not assert wall-clock thresholds, compare
   machines, publish a benchmark, or weaken any exact-count/digest/privacy
   assertion to make the run faster.

Run the million-event proof in one dedicated fully offline synthetic CI job.
Run smaller view, read-only, deletion, redaction, and authority-independence
conformance on every supported native persistence cell. No generated database,
diagnostics JSON, query export, or timing evidence may be tracked or packaged.

## Ready-to-paste amendment for #130

```markdown
## Post-#147 execution amendment

This issue remains blocked until #147 is merged. Rerun the deletion test on the
exact accepted #147 commit; do not infer the result from the pre-cutover JSON
implementation.

Before editing, inventory every Qualification production symbol, non-test
caller, Operational Store operation, and Transfer-level behavior test. The
current pre-#147 baseline has nine public Transfer operations, twelve private
Qualification helpers, four old storage operations, and 23 tests in
`tests/test_qualification.py`; report the post-#147 equivalents exactly.

The deletion test covers seven invariant families as one cluster: Rekordbox-only
eligibility; bounded draft identity/lineage/revision; manifest/selection/head and
audition evidence; ordered duplicate Source Occurrences and the non-authoritative
decision state machine; private-source audition; explicit Spotify-write plus
Effect Journal recovery; and separate stable-head playlist Approval with
collision/conflict handling.

If earned, keep `Transfer` and its existing typed lifecycle as the sole public
policy interface and move the implementation behind one private Transfer-owned
module, recommended `djsupport/_qualification_workflow.py`. Do not reuse
`djsupport/operational_store/qualification.py`; that name already owns SQLite
runtime qualification. Only Transfer may call the private module. CLI, web,
Agent Clients, Runtime Assembly, and store adapters must not import it or learn
revision/digest/effect ordering.

Prove depth with a throwaway deletion diff: for each invariant family record the
lost behavior, where it would have to be reimplemented, the affected Transfer
operation, and the public test that proves it. Pass only if deleting the module
forces substantial policy/recovery knowledge back into Transfer or duplicates
it across callers/adapters. Fail if it removes complexity, leaves delegation
glue, creates a generic command bus, or moves policy into the Operational Store;
in that case close this issue with the evidence and no forced refactor.

Keep user behavior tested through Transfer. Direct internal tests may cover only
crash/recovery mechanics. Browser-origin review must remain unchanged. Add a
release-note record only if distributable behavior or packaging changes.
```

## Ready-to-paste amendment for #132

```markdown
## Post-#147 execution amendment

This issue remains blocked until #147 is merged. Its diagnostics reads stay
read-only, with exactly two narrow writes permitted: one versioned
diagnostics-owned migration installing named ordinary SQL views, and one
Operational Store maintenance operation
`delete_analytics_history(expected_epoch, expected_event_count)`. No generic SQL,
event-write, predicate-delete, or Transfer-persistence interface is exposed.

Freeze one STRICT compact Operational Event schema with primary key
`(commit_sequence, event_ordinal)` and six categories:
`transfer_transition`, `spotify_request`, `proposal_transition`,
`resume_transition`, `effect_transition`, and `match_outcome`. Fields are limited
to the internal commit sequence/event ordinal, epoch, and time values; registered
source kind, phase, outcome, and
reason codes; non-negative claimed-attempt/item units; and required private
`subject_kind`, opaque `subject_id`, and monotonic `subject_revision`. Enforce
`UNIQUE(category, subject_kind, subject_id, subject_revision)` with
insert-or-verify idempotency: an identical retry succeeds and a mismatched retry
rolls back the associated authority transaction. Events have no foreign keys to
authority or across subject families, and no subject identity crosses the query
interface. Arbitrary JSON, free-form messages, raw exceptions, SQL, paths,
source metadata, Spotify/account/playlist/track identifiers, fingerprints,
credentials, and reports are forbidden.

Expose aggregate ordinary views for Transfer outcomes and stop reasons, Spotify
claimed-attempt units by source/phase, proposal-to-Approved progression, resume
outcomes, historical Effect transitions, match outcomes by reason, and latest
incomplete Effect event states. Proposal and incomplete-effect views select the
greatest subject revision before grouping. Effect outcomes are exactly
`prepared`, `in_flight`, `observed_complete`, `observed_not_applied`,
`uncertain`, `reconciled_complete`, `reconciled_not_applied`, and
`review_required`; incomplete means `prepared`, `in_flight`, `uncertain`, or
`review_required`. Every view derives only from Operational Events. Views have
explicit column lists, no identity columns, and no INSTEAD OF triggers.

“Spotify request cost” means locally retained claimed-attempt and requested-item
units. Commit one `claimed` revision immediately before each bounded adapter
call, then a later observed-success, observed-failure, observed-rate-limited, or
explicit-uncertain revision. A claim without a later observation is uncertain:
a crash can happen before the network call, so claimed units are a conservative
upper bound, not proof a request started. They are not money, billing, provider
quota, or an estimate of Spotify's internal accounting.

Render all views from one read snapshot into
`djsupport.local-diagnostics` version `0.7-experimental-1`. Output only enum codes
and integer counts. It is private local data, not a stable Agent Client contract,
and excludes all event/time/private identities, metadata, SQL, and exceptions.

Deletion is Preview-first. Apply requires the exact previewed analytics epoch and
event count, revalidates both inside one bounded BEGIN IMMEDIATE transaction,
deletes all Operational Events, increments the epoch, and reports the directly
deleted count. Stale preview, busy, interruption, or commit failure is typed and
redacted. All seven event-derived views become empty, including incomplete
effects; the canonical authority projection, including the Effect Journal, is
exactly unchanged, and Transfer recovery remains available. Enable and verify SQLite
secure_delete before deletion and report bounded WAL TRUNCATE checkpoint success
or pending cleanup separately. Never claim that this deletes backups, snapshots,
retained generations, or physical-media traces, and never delete sidecars or run
VACUUM implicitly.

The scale proof creates exactly 1,000,000 deterministic synthetic events with
known category totals, independently checks claim/observation uncertainty,
compares aggregates across repeat query/reopen/second connection/fresh view
install/backup restore with `reverse_unordered_selects` both off and on, runs
integrity and foreign-key checks, proves private sentinels cannot enter JSON,
and then deletes exactly 1,000,000 events. All event views must empty while the
canonical authority projection stays exactly unchanged and Transfer recovery
still uses the retained Effect Journal. Timings and file sizes are recorded only
as non-gating diagnostics; there is no wall-clock benchmark assertion.

Keep all work fully offline and synthetic. Include the required release-note
record. Do not add telemetry, engagement/productivity/music-quality scores, raw
event export, live providers, owner data, tags, Releases, or package publication.
```

## Primary sources

Repository sources are pinned to the baseline commit above:

- [Issue #130](https://github.com/spontain112/djsupport/issues/130),
  [issue #132](https://github.com/spontain112/djsupport/issues/132), and
  [issue #147](https://github.com/spontain112/djsupport/issues/147)
- [ADR-0005](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/docs/adr/0005-use-one-local-transactional-operational-store.md)
- [Operational Store issue frontier](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/docs/research/2026-08-16-operational-store-issue-frontier.md)
- [SQLite concurrency and durability contract](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/docs/research/2026-08-16-sqlite-concurrency-durability-contract.md)
- [Transfer Qualification implementation](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/djsupport/transfer.py) and
  [Qualification behavior tests](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/tests/test_qualification.py)
- [Agent privacy decision](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/docs/adr/0002-make-transfer-agent-native.md)

External claims use only first-party documentation:

- SQLite: [`CREATE VIEW`](https://sqlite.org/lang_createview.html),
  [transactions](https://sqlite.org/lang_transaction.html),
  [`DELETE`](https://sqlite.org/lang_delete.html),
  [STRICT tables](https://sqlite.org/stricttables.html),
  [`secure_delete`](https://sqlite.org/pragma.html#pragma_secure_delete),
  [`query_only`](https://sqlite.org/pragma.html#pragma_query_only),
  [`reverse_unordered_selects`](https://sqlite.org/pragma.html#pragma_reverse_unordered_selects),
  [WAL checkpoint modes](https://sqlite.org/pragma.html#pragma_wal_checkpoint),
  [WAL concurrency](https://sqlite.org/wal.html), and
  [`VACUUM`](https://sqlite.org/lang_vacuum.html)
- APSW 3.53.4.0: [connection interface](https://rogerbinns.github.io/apsw/connection.html),
  [read-only open](https://rogerbinns.github.io/apsw/example.html#opening-the-database),
  [`Connection.readonly`](https://rogerbinns.github.io/apsw/connection.html#apsw.Connection.readonly),
  [`Connection.changes`](https://rogerbinns.github.io/apsw/connection.html#apsw.Connection.changes), and
  [`Connection.txn_state`](https://rogerbinns.github.io/apsw/connection.html#apsw.Connection.txn_state)
