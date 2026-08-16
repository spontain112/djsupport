# Operational Store ADR integration audit

**Date:** 2026-08-16

**Status:** read-only architecture/specification audit; no architecture-lane edit,
commit, push, authority switch, live-service call, or owner-data access

**Compared state:**

- `origin/main` at `4be422b5565ac5491084771afa04784b2289318b`;
- the uncommitted `djsupport/operational-store-architecture` worktree at
  `8959036569d26976ea2754c0c2f1aa0b588383ec`;
- accepted program issue
  [#125](https://github.com/spontain112/djsupport/issues/125), delivery issues
  [#138](https://github.com/spontain112/djsupport/issues/138)–
  [#147](https://github.com/spontain112/djsupport/issues/147),
  and diagnostics issue [#132](https://github.com/spontain112/djsupport/issues/132);
- the three research contracts merged by PR #163: the
  [issue frontier](2026-08-16-operational-store-issue-frontier.md),
  [concurrency and durability contract](2026-08-16-sqlite-concurrency-durability-contract.md),
  and [migration, backup, and cutover contract](2026-08-16-sqlite-migration-backup-cutover-contract.md);
- current SQLite and Python primary documentation.

The architecture worktree was inspected only. Its exact dirty scope was five
files: `.gitignore`, `docs/architecture.md`, `docs/storage.md`,
`tests/test_repository_privacy.py`, and the untracked
`docs/adr/0005-use-one-local-transactional-operational-store.md`. This audit writes
only this findings file in a separate worktree.

## Outcome

ADR-0005 remains the right canonical decision and should keep its concise ADR
shape. It aligns with the accepted program on the fundamental choice: one local
SQLite Operational Store behind one internal interface, in-memory conformance
adapter, Transfer as sole policy authority, credentials and configuration kept
outside the store, Preview-first/backup-first migration, an Effect Journal around
external calls, private local Operational Events, no application-level encryption
in the first release, and retained rollback state.

The current five-file draft is **not ready to integrate unchanged**. It contains
four architecture-level ambiguities, one stale delivery sequence, and privacy
rules that do not match the canonical filenames now published on `main`. It also
lacks the release record required by the current range checker. These are bounded
review corrections; they do not justify taking implementation ownership away from
the separate architecture session.

The smallest sound route is an owner-led replay of the five-file draft onto
current `origin/main`, correction of the blocking items below, and one explicit
scope addition for a release record. ADR-0005 should link to the merged research
for mechanics rather than duplicate hundreds of lines of connection, schema,
backup, archive, filesystem, and crash-injection detail.

## Baseline and overlap

The architecture branch has no commits beyond its merge base and is 18 mainline
commits behind `origin/main`. The only overlapping tracked file changed upstream
is `docs/architecture.md`: `main` now documents the merged Runtime Assembly seam.
That upstream change is additive and does not reject ADR-0005, but it makes the
draft's proposed sequence stale. Runtime Assembly and the web assembly work have
already landed, while the draft still lists assembly as future work.

PR #163 deliberately left ADR-0005 to this owning lane. Its issue-frontier note
says schema work must wait for a stable ADR integration route and must not recreate
the concurrent draft. Therefore this audit does not propose moving the ADR into
the research branch. It proposes only a review contract the owner can apply.

The accepted issue numbering explicitly calls the decision ADR-0005. The absence
of ADR-0004 on current `main` is not a reason to renumber this file during
integration; renumbering would break the accepted issue and merged research
references without improving the decision.

## Finding 1: the WAL production claim needs a maintained runtime-qualification gate

The draft says the first production implementation uses WAL, but it does not say
that concurrent production authority must fail closed when the linked SQLite
runtime is not qualified. That omission is material. The runtime in this audit is
Python 3.12.1 linked to SQLite 3.43.1. SQLite's official WAL advisory says the rare
WAL-reset corruption race is likely present through 3.51.2 and requires multiple
connections, the exact operating mode introduced by #139. SQLite identifies
3.51.3 and specific backports as fixes and recommends upgrading
([official WAL-reset advisory](https://sqlite.org/wal.html#the_wal_reset_bug),
[#139](https://github.com/spontain112/djsupport/issues/139)).

There is also a correction to the merged concurrency research. Its phrases
"3.51.3 or later" and "3.51.3+" are too broad. SQLite withdrew 3.52.0 because its
floating-point conversion changes could leave expression indexes stale across
versions; SQLite then re-released the line as 3.53.0 with index repair/detection
support. A monotonic `version >= (3, 51, 3)` predicate would incorrectly admit the
withdrawn 3.52.0 runtime
([SQLite release news](https://sqlite.org/news.html),
[3.51.3 release](https://sqlite.org/releaselog/3_51_3.html),
[3.53.0 release](https://sqlite.org/releaselog/3_53_0.html)).

The stable ADR decision should therefore be concise and non-numeric: concurrent
WAL authority is enabled only for a linked SQLite build proven by the maintained
runtime-qualification contract; an unqualified or withdrawn build fails closed.
The implementation contract must use an explicit allow/deny table (and, for a
downstream backport, recorded distributor/source-build evidence), not a single
lower-bound comparison. At minimum it must reject the observed 3.43.1 runtime,
all unpatched lines identified by the WAL advisory, and withdrawn 3.52.0. Exact
currently accepted versions and source IDs belong in the corrected concurrency
research and executable tests, not permanently copied into the ADR.

#138 may still build a non-authoritative adapter on an older runtime because its
acceptance criteria retain JSON production authority. #139 must not claim safe
concurrent production behavior until its native macOS/Linux/Windows matrix proves
the runtime gate on the exact release commit.

## Finding 2: the architecture delivery sequence is stale and contradicts the issue graph

The new `docs/architecture.md` section proposes this sequence: migration/cutover,
then Effect Journal, then Runtime Assembly, then deletion tests, then diagnostics.
That sequence no longer matches either repository state or the accepted tickets:

- Runtime Assembly and web construction are already merged on `main`.
- #138 first adds one non-authoritative Preview path and expressly forbids cutover.
- #139 qualifies concurrency before #140–#143 move external effects and local
  authority transactions into the store.
- #144 and #145 add migration Preview and backup/restore only after those domain
  slices.
- #146 performs the only production activation, and #147 then removes JSON writers
  and fallback wiring.
- #130 and #132 follow #147; #131's rendering deletion test is already closed.

This is not merely outdated project-management prose: putting cutover before the
Effect Journal would violate #140 and #146's recovery model. The minimum correction
is to remove the five-step list from the stable architecture document and link to
the [merged dependency map](2026-08-16-operational-store-issue-frontier.md#dependency-order-and-parallel-safe-lanes).
If a short sequence remains, it must use the current #138 → #147 boundaries and
must describe Runtime Assembly as an existing seam, not future work.

## Finding 3: reject every runtime dual-authority path, not only a "long-term" adapter

The ADR rejects "Runtime dual-write and long-term JSON production adapters." The
word "long-term" leaves an unintended opening for a temporary JSON fallback or a
partially migrated client. Accepted #125 and #128 reject a JSON production runtime
adapter; #146 additionally rejects dual-write, partial-client cutover, and silent
fallback; #147 keeps legacy readers only in explicit migration/rollback tooling.

The canonical wording should be categorical:

- before #146's activation point, all production clients use JSON authority;
- after the activation point, all production clients resolve the selected SQLite
  generation;
- there is no runtime dual-write, partial-client cutover, or silent JSON fallback;
  and
- retained JSON is inert, read-only input to explicit migration/rollback workflows,
  never a second runtime authority.

The existing additions to `docs/architecture.md` and `docs/storage.md` correctly
say that JSON remains executable until migration ships. Preserve that temporal
boundary while removing "long-term" from the rejection.

## Finding 4: atomic authority means a stable selector, not a frozen active database

The draft promises an atomic authority switch but does not define what changes
atomically. The merged cutover contract corrected this before PR #163 merged: one
small authority pointer selects a complete database generation by stable identity.
The pointer is not a second state store and must not contain a database-byte hash
or authority revision that changes during ordinary writes.

The durable architectural invariant is:

- an inactive candidate is closed, validated, inert, and may be byte-hashed;
- activation atomically replaces only the selector after all clients quiesce;
- the selected generation then becomes the mutable sole authority; and
- an already-open connection to an old generation is forbidden, so Runtime
  Assembly must drain/reopen CLI, web, and Agent Client graphs around activation.

This design is a project inference from #145/#146 plus SQLite/Python filesystem
behavior. WAL files are part of the live database state, and Python only promises
`os.replace()` atomicity for a successful same-filesystem replacement; replacing
an open database is also platform-sensitive
([SQLite WAL file lifecycle](https://sqlite.org/wal.html#the_wal_file),
[Python `os.replace`](https://docs.python.org/3/library/os.html#os.replace),
[cutover contract](2026-08-16-sqlite-migration-backup-cutover-contract.md#145146--atomic-activation)).

ADR-0005 needs at most one sentence expressing selector-versus-active-state
semantics plus a link to the cutover contract. File layout, pointer JSON fields,
fsync ordering, maintenance leases, Preview tokens, and crash points should stay
in research and executable implementation tests.

## Finding 5: SQLite backup means the Online Backup API, never a live file-family copy

The draft uses "backup-first" and later says safe schema migrations may run after
an automatic backup, but does not distinguish a verified logical SQLite snapshot
from copying a live `.sqlite3` file. In WAL mode, a commit may exist only in the
`-wal` file, and SQLite warns that separating or copying mismatched database/WAL
state can lose transactions or corrupt the database. SQLite's Online Backup API,
exposed as Python `Connection.backup()`, is the accepted snapshot seam
([SQLite backup API](https://sqlite.org/backup.html),
[Python backup API](https://docs.python.org/3.10/library/sqlite3.html#sqlite3.Connection.backup),
[#145](https://github.com/spontain112/djsupport/issues/145)).

The concise storage decision should say that an active Operational Store is backed
up through `Connection.backup()` into a fresh private destination, then closed and
verified; production never archives or filesystem-copies a live main/WAL/SHM
family. The detailed deadline, normalization, archive-member, integrity,
foreign-key, schema, hash, and restore protocol remains in the merged backup and
cutover research.

The JSON migration's pre-cutover backup and a post-cutover SQLite snapshot are
different operations. The ADR may call both "backup-first," but `docs/storage.md`
should make that distinction explicit so no implementation reuses the current JSON
byte-copy code as a SQLite snapshot mechanism.

## Finding 6: analytics are deletable non-authority; "append-only" is too absolute

The draft correctly makes analytics rebuildable and non-authoritative, but its ADR
calls Operational Events "append-only" and limits the authority disclaimer to
"matching or playlist authority." #132 requires users to delete analytics history
without deleting authority-bearing state and forbids any analytics authority, not
only matching/playlist authority.

The stable distinction should be:

- Operational Events are append-only under ordinary recording and never consumed
  as an authority-bearing input;
- SQL views and diagnostics are rebuildable read-only projections;
- an explicit analytics-history deletion may remove events/projections without
  deleting or changing Transfers, Approval, Matching Knowledge, publication state,
  Effect Journal recovery facts, or other authority-bearing rows; and
- even a privacy-redacted diagnostics export remains private local user data.

Exact event categories, view SQL, JSON schema, one-million-event scale fixtures,
and deletion mechanics belong to #132 after #147. ADR-0005 should state only the
authority/deletion boundary and link to #132.

## Finding 7: the proposed ignore rules miss the filenames selected by merged research

The draft adds useful DJ Support-specific patterns and representative tests, but
its names predate PR #163. The merged research uses `operational-store.sqlite3`,
`operational-store.authority.json`, and `operational-stores/<generation>.sqlite3`.
None is ignored by the five-file draft. A read-only `git check-ignore --no-index`
probe against that draft produced:

| Representative private artifact | Draft result |
| --- | --- |
| `operational-store.sqlite3` | exposed |
| `operational-store.sqlite3-wal` | exposed |
| `operational-store.sqlite3-shm` | exposed |
| `operational-store.sqlite3-journal` | exposed |
| `operational-store.authority.json` | exposed |
| `operational-stores/<generation>.sqlite3` | exposed |
| `djsupport-snapshot-2026-08-16.sqlite3` | exposed |
| `djsupport-restore-staging/operational-store.sqlite3` | exposed |

The current canonical JSON authorities are also exposed if copied to a repository:
`matching-knowledge.json`, `publication-manifests.json`, and
`publication-manifests.transfers.json`. The backup reader's supported legacy set
also includes exposed `transfers.json`, `legacy-migration.json`, and
`foundation-migration.json`. Canonical `config.json` remains outside the future
database but is still a private source-path reference and is likewise exposed at a
repository root. Existing patterns protect older dot-prefixed names and
`playlist-state.json`, but that does not satisfy #125's configuration/legacy-state
boundary or #147's explicit package/repository gate. Canonical names are listed by
the current storage schema and backup reader
([storage inventory](../storage.md#current-schema-owners),
[`SUPPORTED_SCHEMAS`](../../djsupport/backup.py)).

The draft's prose also says synthetic fixtures can still be committed under
`tests/fixtures/`. That is too permissive for generated SQLite images: #138, #145,
and #147 require package inspection to reject database, sidecar, snapshot, backup,
staging, diagnostic, export, legacy-state, and report artifacts. Tests should
generate databases beneath temporary directories, not retain binary SQLite fixture
images. Invented source facts may remain reviewable fixtures when their explicit
format and privacy policy allow them.

Before integration, the owner should choose one exact canonical filename corpus
shared by `.gitignore` and `tests/test_repository_privacy.py`. It must include the
active pointer, active/staged/retained generation directory, main/WAL/SHM/rollback
journal family, logical snapshots, ZIP backups, migration/restore staging and
extraction, rollback copies, analytics/diagnostics/query exports, all supported
legacy JSON authorities, and reports. Avoid blanket `*.db`/`*.sqlite*` rules, but
do not preserve a loophole for committed generated database fixtures.

The present privacy test proves only ignore behavior for its hand-picked names.
It does not prove source archives or wheels are clean. The architecture PR may
truthfully land the corrected ignore corpus as a front-loaded guard, while #138,
#145, and #147 still own package-build rejection at the point executable artifact
names exist. `docs/storage.md` must not claim package coverage until generated
sdist/wheel inspection actually enforces it.

## Finding 8: current release policy expands the minimum PR scope to six files

Current `scripts/release_records.py` classifies `docs/architecture.md` and
`docs/storage.md` as distributable paths; only `docs/research/` is exempt. The
five-file dirty draft has no `.release-notes/*.md` record, so a normal committed
range would fail with "Distributable behavior changed without a release record"
([release checker](../../scripts/release_records.py),
[#125 program gate](https://github.com/spontain112/djsupport/issues/125)).

The minimum reviewable architecture PR therefore contains the corrected five
draft files **plus one owner-approved release record**. This is a deliberate
six-file scope, not an invitation to add schema, runtime, backup, or migration
implementation. If the owner instead drops both distributable documentation files,
the result would no longer integrate ADR-0005 as the canonical architecture route,
so that is not an equivalent solution.

## ADR depth boundary

ADR-0005 should remain short because its job is to preserve decisions that survive
implementation changes. It should contain:

1. one Operational Store/internal interface and Transfer's sole-policy-authority
   boundary;
2. the before/after authority model with categorical no-dual-write/no-fallback;
3. Effect Journal transaction/effect ordering;
4. compact, explicitly deletable, non-authoritative events/projections;
5. Preview-first, verified backup-first activation with stable-generation selector
   semantics;
6. Python `sqlite3`/WAL plus fail-closed maintained runtime qualification; and
7. private-data, credential/configuration, encryption, and rollback boundaries.

It should link to the two merged implementation contracts for transaction mode,
busy timeout, schema registry, foreign keys, trusted schema, revision SQL,
integrity checks, Online Backup API mechanics, archive validation, filesystem
flush/replace steps, pointer schema, crash matrices, scale fixtures, and platform
qualification. Repeating those details in the ADR would create two canonical
contracts and make future safety corrections—such as the 3.52.0 withdrawal—easy
to miss.

## Minimum exact integration route

1. Leave the separate `djsupport/operational-store-architecture` worktree under
   its current session's ownership. Do not stash, reset, rebase, stage, or commit
   it from a different session.
2. The owner records the exact five-file dirty state, then replays it in an
   owner-controlled clean worktree/branch based on the then-current `origin/main`.
   A fresh replay is safer than asking another session to manipulate the dirty,
   18-commit-old worktree.
3. Preserve current Runtime Assembly documentation from `main`; replace the stale
   delivery sequence with a link to the merged issue frontier.
4. Apply Findings 1–7 without adding implementation: maintained WAL qualification,
   categorical no-fallback language, selector/mutability semantics, Online Backup
   API boundary, deletable non-authority analytics, and one canonical private-file
   corpus.
5. Add exactly one `.release-notes/*.md` record approved for this architecture and
   privacy-guardrail change. Final scope is six files.
6. Correct the merged concurrency research's `3.51.3+` predicate in its own
   research-owned change, explicitly denying withdrawn 3.52.0. ADR integration may
   proceed with generic fail-closed qualification wording, but #139 remains blocked
   until the corrected executable predicate and CI evidence land.
7. Run the focused privacy/documentation/release-policy tests, the complete offline
   suite, compilation, release range check, and package build/inspection. Review
   the final cached diff and file list before any commit or push.
8. Open one architecture PR against current `main`; do not combine it with #138
   schema or adapter code. Once merged, ADR-0005 has the stable route required by
   #138. The separate #136 release/publication gate still blocks #138 schema writes.

## Blocking versus non-blocking findings

### Blocking for the ADR integration PR

- Remove or correct the stale `docs/architecture.md` delivery sequence.
- Replace "long-term JSON production adapters" with categorical no-dual-write,
  no-partial-cutover, and no-silent-fallback wording.
- State the maintained fail-closed WAL runtime-qualification invariant and do not
  encode a naive `>= 3.51.3` rule; withdrawn 3.52.0 must be denied.
- Preserve the stable-selector/mutable-active-generation distinction or link it
  unambiguously from the concise ADR/storage decision.
- State that SQLite backup uses `Connection.backup()` and never raw-copies a live
  main/WAL/SHM family.
- Reconcile ordinary append-only events with #132's explicit analytics-history
  deletion and broaden "never authority" beyond matching/playlist authority.
- Align `.gitignore`, its test corpus, and storage prose with canonical operational,
  generation, staging, backup, diagnostics, and legacy JSON names.
- Add the required release record and integrate from current `origin/main` without
  disturbing the existing dirty owner worktree.

### Blocking for #139 or later production authority, but not for the ADR-only PR

- Correct the merged concurrency research and executable runtime predicate so it
  uses maintained release/source evidence and explicitly rejects 3.52.0.
- Prove accepted SQLite builds on native macOS, Linux, and Windows jobs, including
  Python 3.10/3.14 Linux edges, on the exact candidate commit.
- Implement and test the authority pointer, quiescence, logical backup, restore,
  and crash protocols in their owning #145/#146 slices.
- Add generated sdist/wheel rejection when executable private-artifact names land;
  `.gitignore` alone is not package proof.

### Non-blocking and already aligned

- Keep the filename and references as ADR-0005.
- Keep one SQLite Operational Store plus in-memory conformance adapter.
- Keep Transfer as sole policy authority and clients as adapters.
- Keep configuration and Spotipy-managed credentials outside the database and
  backup/migration payloads.
- Keep Effect Journal intent before and observation after the bounded Spotify call,
  with no database transaction across it.
- Keep JSON production authority until #146 and original JSON retained through the
  explicit rollback window.
- Keep private local-only operation, OS account/disk protection for the first
  release, fail-closed integrity behavior, and no telemetry.
- ADR integration may precede #136 because it changes decisions/guardrails only;
  #136 still blocks schema implementation and any production transition.

## Exact owning-session review checklist

- [ ] Confirm the source worktree still has exactly the original five dirty files
  and no concurrent edits before preserving/replaying it.
- [ ] Base the integration branch on the then-current `origin/main`; retain the
  merged Runtime Assembly text in `docs/architecture.md`.
- [ ] Keep ADR-0005 concise and link both merged implementation research contracts.
- [ ] Delete the stale five-step delivery list or replace it with the exact
  #138 → #147 dependency route.
- [ ] Say explicitly: JSON before activation, SQLite after activation, never
  dual-write, partial-client cutover, or silent fallback.
- [ ] Say explicitly: the pointer selects only stable generation identity; an
  inactive candidate is inert and a selected active generation remains mutable.
- [ ] Say explicitly: active SQLite backups use `Connection.backup()` into a fresh
  verified destination, never a filesystem copy of live database/WAL/SHM files.
- [ ] Require maintained fail-closed runtime qualification; test that 3.43.1 and
  withdrawn 3.52.0 are denied and do not use one monotonic version comparison.
- [ ] Clarify that ordinary Operational Events are non-authoritative and that an
  explicit analytics-history deletion cannot alter authority-bearing state.
- [ ] Run `git check-ignore --no-index` over the complete canonical private-artifact
  corpus, including pointer, generation directory, sidecars, snapshots, backups,
  migration/restore staging, diagnostics/exports, current legacy JSON, and reports.
- [ ] Ensure no generated SQLite database fixture is tracked or packaged; generate
  synthetic databases only in temporary test storage.
- [ ] Add one valid `.release-notes/*.md` record; final intended PR scope is exactly
  the five corrected draft files plus that record.
- [ ] Run
  `python3 -m pytest tests/test_repository_privacy.py tests/test_documentation.py tests/test_release_records.py`.
- [ ] Run `python3 -m pytest` and `python3 -m compileall -q djsupport tests`.
- [ ] After committing, run `python3 scripts/release_records.py check origin/main HEAD`.
- [ ] Build sdist/wheel and inspect their member names; do not claim package privacy
  from `.gitignore` tests alone.
- [ ] Review `git diff --cached --name-only` and `git diff --cached` before commit;
  do not use `git add -A`.
- [ ] Do not add Operational Store schema/runtime code, cut over authority, access
  owner data, call live services, or publish tags/releases/packages in this PR.
- [ ] Merge ADR-0005 before #138 schema writes, while preserving #136 as the separate
  release/publication and return-to-development gate.
