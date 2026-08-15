# Operational Store issue frontier

**Date:** 2026-08-16

**Status:** implementation-readiness research; no authority switch or release action

**Baseline:** [`origin/main` at `6b04a70`](https://github.com/spontain112/djsupport/commit/6b04a70eb65681b97b104de8cc1eac6cef49713b)

## Decision summary

The next product implementation is [#138](https://github.com/spontain112/djsupport/issues/138), but it is not executable yet: its remaining blocker is the human-owned final-0.6 publication and return-to-development gate in [#136](https://github.com/spontain112/djsupport/issues/136). Its other blocker, [#137](https://github.com/spontain112/djsupport/issues/137), is closed on the baseline above. Public Releases still identify `v0.5.0` as Latest, while source metadata is `0.6.0`; #136 explicitly owns the final tag/Latest Release and the subsequent development-version commit ([Releases](https://github.com/spontain112/djsupport/releases), [`pyproject.toml`](../../pyproject.toml), [release policy](../releasing.md#9-promote-a-final-release-deliberately)). A `ready-for-agent` label therefore means the issue is specified, not that its declared blocker may be bypassed.

The storage program should be delivered through the bounded #138–#147 slices rather than by claiming the broad architecture umbrellas [#127](https://github.com/spontain112/djsupport/issues/127) or [#128](https://github.com/spontain112/djsupport/issues/128) as one change. That is an inference from the issue topology: #127 forbids a production switch, #128 defines the eventual sole authority, #138 starts with one non-authoritative Preview, and #146 performs the explicit cutover. The parent [#125](https://github.com/spontain112/djsupport/issues/125) fixes the invariants: one local SQLite store, one internal interface, no ORM without separate justification, no dual-write, an Effect Journal around external effects, rebuildable events rather than analytics authority, and private local operation only.

One architecture integration preflight remains visible: #125 names an ADR 0005 draft on the separate `djsupport/operational-store-architecture` branch, while current `origin/main` contains ADRs 0001–0003 only ([ADR directory](../adr/)). Do not independently recreate or reinterpret that concurrent architecture work. Before #138 writes a schema, confirm the accepted ADR has a stable integrated route; until then, the public issue decisions above are the authoritative contract available on main.

Release automation also needs deliberate sequencing. Two Runtime Assembly release records are already pending, but they are not storage records or an 0.7 candidate ([pending records](../../.release-notes)). Let the storage records accumulate behind normal review, and do not treat an automated version PR as the exact `0.7.0rc1` freeze: #149 and the one-use candidate override own that later gate ([#149](https://github.com/spontain112/djsupport/issues/149), [version workflow](../releasing.md#2-review-the-automated-version-pr)).

The highest-leverage implementation move is to preserve the public [`Transfer`](../../djsupport/transfer.py#L2093) seam and convert its existing behavior tests into Operational Store adapter-conformance tests. Today Transfer receives three persistence collaborators—matching knowledge, publication storage, and Transfer storage—and the storage guide explicitly says their JSON documents are independently authoritative and cannot form one transaction ([constructor](../../djsupport/transfer.py#L2093-L2117), [current storage relationships](../storage.md#storage-relationships), [current write semantics](../storage.md#write-and-concurrency-behavior)). The program is not a policy rewrite: the domain and lifecycle invariants already live above serialization and must remain unchanged ([domain model](../domain-model.md#core-invariants), [lifecycles](../lifecycles.md)).

## Current reusable foundation

- Exact Source Occurrence identity, order, and duplicate preservation already exist in the value model and high-level tests; these are the canonical facts the two new adapters must round-trip ([source facts](../../djsupport/source_facts.py#L181-L205), [duplicate Approval test](../../tests/test_qualification.py#L443-L490)).
- Transfer, Batch, and Qualification state already carry optimistic revisions, and file storage reloads under a lock before rejecting stale writes. Matching knowledge and publication state do not yet have the same per-entity contract ([state values](../../djsupport/transfer.py#L292-L430), [file-store concurrency](../../djsupport/transfer.py#L1171-L1347), [storage comparison](../storage.md#write-and-concurrency-behavior)).
- Publication recovery already has stable publication keys, retained playlist identity, chunk identities, and changed-head stop conditions. It is a useful behavioral baseline, but it is not an Effect Journal because intent is not committed before every external call ([publication path](../../djsupport/transfer.py#L5822-L5997), [checkpointed effects](../../djsupport/transfer.py#L6033-L6098), [durable lifecycle](../lifecycles.md#durable-transfer-and-batch-states)).
- Qualification and Mirror behavior is already heavily specified through Transfer. SQLite work should parameterize these tests over stores rather than move their authority rules into persistence ([Qualification tests](../../tests/test_qualification.py), [Mirror tests](../../tests/test_transfer.py#L882-L1568), [engineering convention](../../CONTRIBUTING.md#engineering-conventions)).
- Existing backup/migration code supplies reusable archive-path, hash, redaction, preview, and rollback patterns, but it operates on JSON members and is not a transactionally consistent SQLite snapshot implementation ([backup reader](../../djsupport/backup.py#L159-L221), [restore commit](../../djsupport/backup.py#L444-L477), [migration ownership](../storage.md#migration-ownership)).
- The current focused baseline is green: `python3 -m pytest tests/test_runtime.py tests/test_transfer.py tests/test_qualification.py tests/test_backup.py tests/test_migration.py tests/test_repository_privacy.py` completed with 227 passed and three pre-existing warnings. This is a regression baseline, not evidence that any SQLite criterion is complete.

## Acceptance frontier

Status meanings: **present** is authoritative current behavior that must be preserved; **partial** is reusable evidence but does not satisfy the issue; **missing** requires implementation; **gate** cannot be claimed yet.

### [#138 — Persist and resume one Transfer Preview through SQLite](https://github.com/spontain112/djsupport/issues/138)

| AC | Current evidence and gap | Status |
| --- | --- | --- |
| One Operational Store interface; callers do not coordinate separate adapters | Transfer currently receives three collaborators and Runtime Assembly constructs three file-backed paths/adapters ([Transfer constructor](../../djsupport/transfer.py#L2093-L2117), [Runtime Assembly](../../djsupport/runtime.py#L172-L205)). | **Missing** |
| In-memory and SQLite adapters pass the same conformance tests | `EphemeralMatchingKnowledge` and test-local `InMemoryStorage` cover narrower old protocols; there is no complete in-memory Operational Store or shared adapter suite ([test fake](../../tests/test_transfer.py#L137-L235), [current protocols](../../djsupport/transfer.py#L914-L938)). | **Missing** |
| Source Selection identity, occurrence order, and duplicates round-trip exactly | Exact occurrence values and duplicate-through-Approval coverage exist, but not through either proposed Operational Store adapter ([source occurrence](../../djsupport/source_facts.py#L181-L205), [duplicate test](../../tests/test_qualification.py#L443-L490)). | **Partial** |
| Preview retains proposals/failures, Batch and Transfer progress, resumable checkpoints, and compact Operational Events | Current JSON schemas retain all listed operational state except Operational Events; the storage inventory has no event category ([storage contents](../storage.md#file-contents-by-category), [Transfer state](../../djsupport/transfer.py#L696-L737)). | **Partial** |
| Explicit migration registry; Python `sqlite3`; no ORM | The package has no SQLite module, migration registry, or ORM dependency; current migration code is JSON-specific ([project dependencies](../../pyproject.toml), [legacy migration](../../djsupport/migration.py)). | **Missing** |
| Configuration and Spotipy credentials stay outside the database | This boundary is already canonical and must remain so ([storage boundary](../storage.md#configuration-and-credentials), [paths](../../djsupport/paths.py)). | **Present** |
| Scale: 100,000 Source Occurrences and 10,000 Transfers | No such scale fixture or verification exists in the current test inventory ([tests map](../../CONTRIBUTING.md#repository-map)). | **Missing** |
| Database, WAL, and SHM documented and ignored; repository/package privacy covers them | Current ignore and privacy tests cover reports, credentials, XML, playlist JSON, and regressions, but not database/sidecar/snapshot/staging patterns ([`.gitignore`](../../.gitignore), [privacy tests](../../tests/test_repository_privacy.py)). | **Missing** |
| Existing JSON remains production authority; no dual-write or cutover | Runtime Assembly still selects JSON adapters, so this guard currently holds. #138 must add an isolated Preview path without silently changing production selection ([Runtime Assembly](../../djsupport/runtime.py#L172-L217), [storage inventory](../storage.md#current-schema-owners)). | **Present guard** |
| Release-note record | The two pending records describe Runtime Assembly, not #138; the repository requires one record for a distributable implementation ([pending records](../../.release-notes), [release policy](../releasing.md#1-record-distributable-changes)). | **Missing** |

### [#139 — Reject stale concurrent Transfer writes safely](https://github.com/spontain112/djsupport/issues/139)

| AC | Current evidence and gap | Status |
| --- | --- | --- |
| Two independent connections safely update distinct work | File storage has process/thread locking, but no SQLite connection-conformance test exists ([file locking](../../djsupport/transfer.py#L1171-L1215)). | **Missing** |
| Stale Transfer, Batch, or matching-knowledge revision fails closed | Transfer/Batch/Qualification file entities reject stale revisions; matching knowledge and publication state explicitly lack that contract, and none is tested through SQLite ([file save](../../djsupport/transfer.py#L1278-L1347), [storage comparison](../storage.md#write-and-concurrency-behavior)). | **Partial** |
| WAL, short transactions, bounded busy handling, integrity checks | No SQLite implementation exists in the current production/storage map ([source map](../architecture.md#production-source-map), [project dependencies](../../pyproject.toml)). | **Missing** |
| Crash before/during/after commit yields the previous or complete next state | Existing file and restore tests provide failure-injection patterns, but not SQLite transaction crash points ([restore rollback test surface](../../tests/test_backup.py#L388-L638), [file-store save](../../djsupport/transfer.py#L1331-L1369)). | **Partial** |
| No database transaction spans an external service call | There is no database transaction to inspect yet; the future test must assert the synthetic Spotify adapter is invoked only with no store transaction active ([Spotify seam](../../djsupport/transfer.py#L885-L911)). | **Missing** |
| macOS, Linux, Windows; Python 3.10 and 3.14 edges on Linux | CI currently runs both Python edges only on Ubuntu; macOS and Windows persistence jobs are absent ([CI matrix](../../.github/workflows/ci.yml#L33-L55)). | **Partial** |
| CLI/web/Agent privacy-redacted behavior unchanged | The three clients now share Runtime Assembly and existing agent contracts are privacy-redacted; post-change regression is still required ([architecture](../architecture.md#module-architecture), [Agent decision](../adr/0002-make-transfer-agent-native.md)). | **Present baseline** |
| Release-note record | Required by the issue and repository policy; no #139 record exists ([pending records](../../.release-notes)). | **Missing** |

### [#140 — Publish one Snapshot through the Effect Journal](https://github.com/spontain112/djsupport/issues/140)

| AC | Current evidence and gap | Status |
| --- | --- | --- |
| Commit intent before Spotify; commit observed result afterward | Current playlist creation is followed by local retention; there is no pre-call Effect Journal intent record ([publication path](../../djsupport/transfer.py#L5822-L5869)). | **Missing** |
| No transaction across Spotify | Must be proved at the new store boundary; current code offers a synthetic Spotify seam but no database transaction ([Spotify protocol](../../djsupport/transfer.py#L885-L911)). | **Missing** |
| Manifest and ordered items retain exact proposed facts | The current manifest/value model and duplicate tests are reusable, but must move through the Operational Store ([manifest model](../../djsupport/transfer.py#L751-L827), [domain rule](../domain-model.md#relationship-summary)). | **Partial** |
| Resume distinguishes not attempted, observed complete, and uncertain effects | Current state distinguishes matching/retaining/completed and retains mutation snapshots, but has no explicit journal categories for uncertain effects ([lifecycle](../lifecycles.md#durable-transfer-and-batch-states), [Transfer state](../../djsupport/transfer.py#L696-L724)). | **Partial** |
| Stable identity prevents duplicate Snapshot creation when completion is provable | `publication_key`, recovery lookup, and retained playlist ID already supply the behavior to port ([checkpointed publication](../../djsupport/transfer.py#L6033-L6063), [recovery tests](../../tests/test_transfer.py#L2378-L2478)). | **Partial** |
| Crash immediately before/after call and before result retention is deterministic | Current tests cover important recovery points but not the complete three-state journal matrix ([publication lifecycle tests](../../tests/test_transfer.py#L2037-L2478)). | **Partial** |
| Preview creates no mutation-authorizing journal entry | Preview already forbids playlist and playlist-state mutation; the future store must make the same invariant observable in journal rows ([domain invariant](../domain-model.md#core-invariants)). | **Present baseline** |
| Exercise through Transfer with synthetic Spotify | High-level Transfer tests already use synthetic adapters and are the required seam ([engineering convention](../../CONTRIBUTING.md#engineering-conventions), [Snapshot tests](../../tests/test_transfer.py#L824-L881)). | **Present seam** |
| Release-note record | No #140 record exists ([pending records](../../.release-notes)). | **Missing** |

### [#141 — Approve one Provisional Playlist atomically](https://github.com/spontain112/djsupport/issues/141)

| AC | Current evidence and gap | Status |
| --- | --- | --- |
| Compare exact playlist head with account-scoped manifest | Current Approval reloads stores, scopes the manifest by account, and reads a stable head around ordered items ([Approval path](../../djsupport/transfer.py#L4563-L4758)). | **Present baseline** |
| Surviving/removed/Correction outcomes become the right authority | Existing Approval classifies these outcomes and checkpoints matching knowledge ([Approval classification](../../djsupport/transfer.py#L4797-L4967), [lifecycle](../lifecycles.md#approval-outcomes)). | **Present baseline** |
| Collisions and conflicts remain review-required | Current domain rules and tests forbid silent success ([domain invariants](../domain-model.md#core-invariants), [Approval tests](../../tests/test_transfer.py#L2784-L3372)). | **Present baseline** |
| Approval, publication, knowledge, Corrections, conflicts commit in one transaction | Current implementation checkpoints knowledge, optionally writes Mirror state, then appends Approval through independent adapters; the storage guide explicitly says separate files are not one transaction ([Approval writes](../../djsupport/transfer.py#L4898-L4980), [storage limitation](../storage.md#write-and-concurrency-behavior)). | **Missing** |
| Approval stays separate from publication and draft application | This is canonical and tested through Transfer ([authority ladder](../domain-model.md#authority-ladder), [Qualification lifecycle](../lifecycles.md#qualification-draft-states)). | **Present** |
| Repeat is idempotent; stale playlist or manifest revisions fail closed | Stable-head and changed-manifest checks exist for Qualification Approval; there is no single Operational Store revision/idempotency proof for every Approval fact ([Approval checks](../../djsupport/transfer.py#L4681-L4758), [Qualification idempotency tests](../../tests/test_agent_contract.py#L1122-L1265)). | **Partial** |
| Compact Operational Events retain categories without authority | There is no Operational Event category in the current storage model ([storage inventory](../storage.md#current-schema-owners)). | **Missing** |
| Transfer test proves rollback on injected failure | Existing tests exercise failures around Approval, but separate file writes cannot prove one local transaction rollback ([Approval tests](../../tests/test_transfer.py#L2784-L3372)). | **Missing** |
| Release-note record | No #141 record exists ([pending records](../../.release-notes)). | **Missing** |

### [#142 — Resume and apply one Qualification Draft](https://github.com/spontain112/djsupport/issues/142)

| AC | Current evidence and gap | Status |
| --- | --- | --- |
| Draft binds Transfer, manifest, account, playlist head, and selected occurrences | The current draft stores those identities/digests and item IDs; the port must prove exact round-trip through both new adapters ([draft state](../../djsupport/transfer.py#L381-L430), [domain relationship](../domain-model.md#relationship-summary)). | **Partial** |
| Keep, Correction, deferred, exclusion, rejection persist with revisions and no authority | Current decision recording and explicit deferred exclusion already enforce this, but only through JSON storage ([decision path](../../djsupport/transfer.py#L3604-L3715), [lifecycle table](../lifecycles.md#qualification)). | **Partial** |
| Discard/successor atomic; stale revisions fail closed | File storage already saves both successor sides under one lock and rejects stale revision; this is a direct adapter-conformance case ([successor save](../../djsupport/transfer.py#L1300-L1329), [stale test](../../tests/test_qualification.py#L1175-L1249)). | **Partial** |
| Digests and account-scoped Local Audio associations round-trip without paths, filenames, or audition handles | Current draft fields and storage docs enforce the privacy boundary; SQLite schema/adapter proof is missing ([draft state](../../djsupport/transfer.py#L381-L430), [storage boundary](../storage.md#transfer-state), [local-audio convention](../../CONTRIBUTING.md#engineering-conventions)). | **Partial** |
| Application uses Effect Journal and remains separate from Approval | Separation exists; Effect Journal does not ([Qualification lifecycle](../lifecycles.md#qualification-draft-states), [current chunk checkpoints](../../djsupport/transfer.py#L4501-L4561)). | **Partial** |
| Browser-origin selections remain reviewed in Spotify | Current behavior explicitly refuses a Qualification Draft for the browser-origin Snapshot path ([test](../../tests/test_qualification.py#L669-L703)). | **Present** |
| Scale: 1,000 Qualification Drafts | No scale fixture/test exists in the current Qualification suite ([tests](../../tests/test_qualification.py)). | **Missing** |
| Interruption and recovery through Transfer | Existing high-level tests cover paused/resumed draft application; adapter/journal coverage remains missing ([recovery tests](../../tests/test_qualification.py#L746-L945)). | **Partial** |
| Release-note record | No #142 record exists ([pending records](../../.release-notes)). | **Missing** |

### [#143 — Maintain one Mirror through the Operational Store](https://github.com/spontain112/djsupport/issues/143)

| AC | Current evidence and gap | Status |
| --- | --- | --- |
| Mirror identity scopes account, source type/reference, and playlist | Current `MirrorRelationship` carries account, source label/reference, and playlist identity ([model](../../djsupport/transfer.py#L829-L840), [domain relationship](../domain-model.md#relationship-summary)). | **Present baseline** |
| Initial/replacement state retains ordered items, manifest, revision, journal state | Ordered managed items and manifests exist; Mirror has no optimistic revision and there is no Effect Journal ([manifest/Mirror models](../../djsupport/transfer.py#L751-L840)). | **Partial** |
| Resume reconciles replacement, description, relink, and removal without guessing | Current publication chunks have recovery checkpoints, while relink/removal paths do not have the accepted journal model ([checkpointed effects](../../djsupport/transfer.py#L6033-L6098), [Mirror lifecycle tests](../../tests/test_transfer.py#L882-L1568)). | **Partial** |
| Drift permits only restore or Approved Match revocation | Canonical behavior and high-level tests already enforce the explicit choices ([Mirror lifecycle](../lifecycles.md#mirror-drift-and-orphaning), [drift tests](../../tests/test_transfer.py#L1213-L1426)). | **Present** |
| Orphan remains untouched until keep/relink/delete | Canonical behavior and tests already enforce it ([lifecycle](../lifecycles.md#mirror-drift-and-orphaning), [orphan tests](../../tests/test_transfer.py#L883-L1212)). | **Present** |
| No destructive action inferred from absence or conversation | Repository and Agent Client policy already forbid this ([AGENTS boundaries](../../AGENTS.md#boundaries), [Agent decision](../adr/0002-make-transfer-agent-native.md)). | **Present** |
| Complete lifecycle through Transfer with synthetic adapters | The current test group is a strong baseline; it must be parameterized through the new store and journal ([Mirror tests](../../tests/test_transfer.py#L882-L1568)). | **Partial** |
| Release-note record | No #143 record exists ([pending records](../../.release-notes)). | **Missing** |

### [#144 — Preview and exactly verify JSON-to-SQLite migration](https://github.com/spontain112/djsupport/issues/144)

| AC | Current evidence and gap | Status |
| --- | --- | --- |
| Read-only importer accepts every supported JSON schema version | The supported version inventory exists, but no current-authority JSON-to-SQLite importer exists ([schema inventory](../storage.md#supported-backup-and-restore-schemas), [backup constants](../../djsupport/backup.py#L21-L32)). | **Missing** |
| Import every named authority/operational category into a temporary database | Current state is distributed across the three JSON documents and migration markers; Operational Events and Effect Journal do not exist yet ([current schemas](../storage.md#current-schema-owners)). | **Missing** |
| Verify exact identities, occurrence order/duplicates, relationships, authority, revisions, evidence, incomplete effects | The domain supplies the identity rules, but there is no whole-store verifier ([identity layers](../domain-model.md#identity-layers)). | **Missing** |
| Malformed, unsupported, ambiguous, or unverifiable input fails closed with no switch | Existing schema readers and legacy migration provide reusable fail-closed patterns, not the required verifier ([migration ownership](../storage.md#migration-ownership), [migration tests](../../tests/test_migration.py)). | **Partial** |
| Preview excludes secrets, paths, metadata, identifiers, fingerprints, SQL, raw exceptions | Current migration/Agent outputs use aggregate privacy-safe facts; a new verification document and denylist test are required ([Agent privacy contract](../adr/0002-make-transfer-agent-native.md#L26-L31), [legacy migration tests](../../tests/test_migration.py#L32-L112)). | **Partial** |
| Crash before/during/after import leaves original JSON untouched | Current legacy migration leaves sources unchanged and tests commit failure, which is a reusable fixture pattern ([legacy migration](../../djsupport/migration.py#L60-L118), [failure tests](../../tests/test_migration.py#L351-L474)). | **Partial** |
| Configuration and Spotipy credentials are not imported/copied | Configuration and credentials are canonically separate; note that current generic backups include `config.json`, so this importer needs a narrower explicit member set ([configuration boundary](../storage.md#configuration-and-credentials), [backup members](../../djsupport/backup.py#L21-L32)). | **Present boundary / missing proof** |
| Tests use only synthetic data | Repository policy already requires invented fixtures and forbids owner data ([contribution policy](../../CONTRIBUTING.md#protect-local-dj-data), [ADR-0001](../adr/0001-keep-user-data-out-of-the-repository.md)). | **Present guard** |
| Release-note record | No #144 record exists ([pending records](../../.release-notes)). | **Missing** |

### [#145 — Back up and restore the SQLite Operational Store](https://github.com/spontain112/djsupport/issues/145)

| AC | Current evidence and gap | Status |
| --- | --- | --- |
| Transactionally consistent snapshot; no unsafe WAL/SHM copy | Current backup copies individual JSON bytes; no SQLite snapshot exists ([backup creation](../../djsupport/backup.py#L78-L125)). | **Missing** |
| Manifest records store schema/hash and excludes credentials | Current archive manifest records per-member schema/hash and screens credential fields; it is a reusable contract, not a database manifest ([backup manifest](../../djsupport/backup.py#L98-L124)). | **Partial** |
| Restore validates paths, members, hashes, DB integrity/schema before redacted Preview | Path/member/hash/schema validation exists for ZIP/JSON; database integrity and store schema validation do not ([archive reader](../../djsupport/backup.py#L190-L221)). | **Partial** |
| Apply is atomic or leaves previous complete store | Current multi-file restore has staged rollback; a database replacement/activation proof is missing ([restore commit](../../djsupport/backup.py#L444-L477)). | **Partial** |
| 0.7 rollback window without silently deleting legacy JSON | Current migration guidance preserves legacy sources, but the 0.7 window and SQLite rollback behavior do not exist ([migration ownership](../storage.md#migration-ownership), [upgrade guide](../upgrading.md)). | **Partial** |
| Snapshots/backups/staging/extracted copies documented and ignored | Current documentation and ignore rules do not enumerate the database family ([storage privacy](../storage.md), [`.gitignore`](../../.gitignore)). | **Missing** |
| Repository/package checks reject all such artifacts | Current checks do not include database, WAL/SHM, snapshot, or staging names ([privacy tests](../../tests/test_repository_privacy.py), [package inspection](../../.github/workflows/ci.yml#L57-L162)). | **Missing** |
| Cross-platform tests use synthetic application data | Existing backup tests are synthetic, but CI runs them only on Ubuntu ([backup tests](../../tests/test_backup.py), [CI matrix](../../.github/workflows/ci.yml#L33-L55)). | **Partial** |
| Release-note record | No #145 record exists ([pending records](../../.release-notes)). | **Missing** |

### [#146 — Apply the verified SQLite production cutover](https://github.com/spontain112/djsupport/issues/146)

| AC | Current evidence and gap | Status |
| --- | --- | --- |
| Create and verify a complete current-state backup first | Current migrations use backup-first patterns; no complete SQLite/JSON transition backup contract exists ([Foundation migration](../../djsupport/migration.py#L427-L471)). | **Partial** |
| Stage import, pass #144 exact verification, install complete DB before authority change | This depends on [#144](https://github.com/spontain112/djsupport/issues/144); current migration stages JSON writes rather than a verified database ([migration commit](../../djsupport/migration.py#L386-L417)). | **Missing** |
| Runtime Assembly selects store for every client only after activation | All clients now share Runtime Assembly, which is the right switch seam, but it is hard-coded to file adapters ([Runtime Assembly](../../djsupport/runtime.py#L142-L217), [architecture](../architecture.md#module-architecture)). | **Partial** |
| Failure before activation leaves JSON authority; success leaves SQLite authority | No activation state machine exists; Runtime Assembly selects file paths/adapters directly ([Runtime Assembly](../../djsupport/runtime.py#L172-L217)). | **Missing** |
| No dual-write, partial client cutover, or silent fallback | Shared Runtime Assembly can prevent partial client selection, but no accepted activation/fail-closed implementation exists ([Runtime Assembly](../../djsupport/runtime.py#L172-L205)). | **Partial** |
| Original JSON stays untouched for rollback window | Existing migration policy preserves sources; 0.7 cutover/retention is missing ([migration ownership](../storage.md#migration-ownership)). | **Partial** |
| Configuration and Spotipy credentials remain outside DB | Canonical boundary already exists ([storage configuration](../storage.md#configuration-and-credentials)). | **Present** |
| Crash injection at every apply/activation phase proves deterministic authority | Existing migration fault tests do not cover a SQLite activation state machine ([migration tests](../../tests/test_migration.py#L351-L474)). | **Missing** |
| Live services, owner data, tags, publication remain separately gated | Repository instructions already impose this boundary ([AGENTS boundaries](../../AGENTS.md#boundaries), [release checklist](../releasing.md)). | **Present guard** |
| Release-note record | No #146 record exists ([pending records](../../.release-notes)). | **Missing** |

### [#147 — Retire JSON production writers](https://github.com/spontain112/djsupport/issues/147)

| AC | Current evidence and gap | Status |
| --- | --- | --- |
| No production JSON adapter/fallback for authority state | Current production is explicitly JSON-backed, the opposite of the target ([storage owners](../storage.md#current-schema-owners), [Runtime Assembly](../../djsupport/runtime.py#L172-L205)). | **Missing** |
| Transfer and Runtime Assembly expose only Operational Store interface | Transfer and Runtime Assembly expose separate old adapters today ([Transfer constructor](../../djsupport/transfer.py#L2093-L2117), [Runtime graph](../../djsupport/runtime.py#L89-L95)). | **Missing** |
| Legacy JSON readable only through migration/rollback | Runtime still reads/writes JSON; explicit read-only legacy routing is missing ([Runtime Assembly](../../djsupport/runtime.py#L172-L217), [storage owners](../storage.md#current-schema-owners)). | **Missing** |
| Remove obsolete locks, temp paths, duplicate schema constants, old-interface tests | These are still active in `FileTransferStorage`, `FilePublicationStorage`, and cache code ([file adapters](../../djsupport/transfer.py#L941-L1369), [cache](../../djsupport/cache.py)). | **Missing** |
| Interface conformance replaces old adapter-specific tests without weaker behavior | No Operational Store conformance suite exists; current high-level behavior tests must remain ([testing convention](../../CONTRIBUTING.md#engineering-conventions)). | **Missing** |
| Privacy/package checks reject all database and legacy artifact categories | Current checks lack most enumerated patterns ([privacy tests](../../tests/test_repository_privacy.py), [package job](../../.github/workflows/ci.yml#L57-L162)). | **Missing** |
| Architecture/storage docs identify SQLite as sole authority and every ignored category | Current docs intentionally identify three JSON documents as authority ([architecture source map](../architecture.md#production-source-map), [storage owners](../storage.md#current-schema-owners)). | **Missing** |
| Complete offline and packaging suites pass | The commands/gates exist and are green as a baseline, but only the final #147 commit can satisfy this criterion ([contributing](../../CONTRIBUTING.md#development-setup), [release validation](../releasing.md#4-run-the-complete-release-validation)). | **Future gate** |
| Release-note record | No #147 record exists ([pending records](../../.release-notes)). | **Missing** |

### [#148 — Publish 0.7 migration/recovery guidance in djsupport-docs](https://github.com/spontain112/djsupport/issues/148)

| AC | Current evidence and gap | Status |
| --- | --- | --- |
| Implementation is in `djsupport-docs` and linked to the ticket | Product-repo edits cannot satisfy this; [#148](https://github.com/spontain112/djsupport/issues/148) is blocked by [#147](https://github.com/spontain112/djsupport/issues/147). | **Gate** |
| Cover preflight, backup, Preview, apply, interrupted recovery, restore, rollback | Current product docs explain the JSON-era workflows and can source stable concepts; final commands must wait for #147 behavior ([current backup guide](../backup-and-restore.md), [current upgrade guide](../upgrading.md)). | **Partial source / gate** |
| Commands/outcomes match final behavior without duplicating internal architecture | The product repo owns internal architecture and executable CLI truth; docs-site content must link rather than fork it ([documentation ownership](../../AGENTS.md#what-goes-where), [CLI truth](../../CONTRIBUTING.md#development-setup)). | **Present boundary / gate** |
| Private-data section covers every database/legacy/generated category | Current storage docs do not yet contain the final SQLite inventory; #147 must establish it first ([storage privacy](../storage.md)). | **Gate** |
| Explain gitignore is a guardrail and private data never enters Git | This wording already exists in the engineering guide and can be reused after behavior freezes ([privacy guidance](../../CONTRIBUTING.md#protect-local-dj-data)). | **Present source** |
| Config and Spotipy credentials outside store | Stable source exists now ([storage configuration](../storage.md#configuration-and-credentials)). | **Present source** |
| No owner data, paths, credentials, screenshots | Repository policy already forbids these; docs-site verification remains future work ([ADR-0001](../adr/0001-keep-user-data-out-of-the-repository.md), [AGENTS boundaries](../../AGENTS.md#boundaries)). | **Present guard / gate** |
| Documentation build/link checks pass | Must run in `djsupport-docs`; the product repository explicitly assigns stable public guidance there ([documentation ownership](../../AGENTS.md#what-goes-where)). | **Gate** |

### [#149 — Prepare and freeze exact 0.7.0rc1](https://github.com/spontain112/djsupport/issues/149)

| AC | Current evidence and gap | Status |
| --- | --- | --- |
| Complete records and generated changelog identify candidate | Release-record automation exists; the 0.7 records and exact override/candidate do not ([release records](../../.release-notes/README.md), [release workflow](../releasing.md#2-review-the-automated-version-pr)). | **Partial infrastructure** |
| Full offline/compile/privacy/migration/backup/restore/crash/diagnostics/cross-platform/package/archive/clean-install gates on exact commit | Current CI covers offline/compile on Linux 3.10/3.14 plus package/archive/clean install. SQLite migration, restore, crash, diagnostics, and macOS/Windows gates are missing ([CI](../../.github/workflows/ci.yml)). | **Partial** |
| Source/wheel contain no private data and include required public policy/notices | Archive inspection exists and `LICENSE` is tracked; the exact candidate still needs content and privacy proof ([package job](../../.github/workflows/ci.yml#L57-L162), [`LICENSE`](../../LICENSE)). | **Future gate** |
| Disposable installs verify Preview, cutover, resume, restore, rollback, diagnostics with synthetic data | Current clean-install job verifies import and `djsupport --help` only ([clean install](../../.github/workflows/ci.yml#L149-L162)). | **Missing** |
| Record exact candidate commit/evidence for pre-release publication | #134 provides the public evidence pattern for 0.6; no 0.7 candidate exists ([#134](https://github.com/spontain112/djsupport/issues/134)). | **Missing** |
| No tag, Release, package publication, live service, or owner-data operation | This is already the repository boundary and must stay separately gated ([AGENTS boundaries](../../AGENTS.md#boundaries), [release policy](../releasing.md#6-publish-an-exact-release-candidate)). | **Present guard** |
| Main stays explicit development unless a reviewed candidate version commit is required | Current main is stable `0.6.0`, and #136 owns returning it to development before storage work proceeds ([`pyproject.toml`](../../pyproject.toml), [#136](https://github.com/spontain112/djsupport/issues/136)). | **Current blocker / future gate** |

### [#132 — Rebuildable private local diagnostics](https://github.com/spontain112/djsupport/issues/132)

#132 is specified but blocked by #147. The future surface may consume only the accepted read-only event-query interface; it must not change Transfer persistence.

| AC | Current evidence and gap | Status |
| --- | --- | --- |
| Views answer Transfer outcomes/pause/failure, Spotify request cost, proposed-to-Approved progression, resume/incomplete effects, and match reasons | No current code defines Operational Events or SQL views; current Transfer reports are not rebuildable analytics projections ([current storage inventory](../storage.md#current-schema-owners), [report model](../../djsupport/report.py)). | **Missing** |
| Joined private identities never leak through diagnostics | Agent Client output has a reusable privacy-redaction discipline, but no diagnostics interface exists ([Agent privacy decision](../adr/0002-make-transfer-agent-native.md#L26-L31), [agent tests](../../tests/test_agent_contract.py)). | **Partial test model** |
| Exclude paths, source metadata, playlist/track/account IDs, fingerprints, credentials, SQL, and raw exceptions | Existing repository and Agent privacy tests cover subsets of this denylist; the diagnostics-document contract is missing ([privacy tests](../../tests/test_repository_privacy.py), [Agent decision](../adr/0002-make-transfer-agent-native.md)). | **Partial test model** |
| Inspect categories/counts and explicitly delete analytics without deleting authority | The current storage model has no analytics-history store, projection rebuild, or independent deletion operation ([storage inventory](../storage.md#current-schema-owners)). | **Missing** |
| JSON is experimental in 0.7 and not a stable Agent contract | No diagnostics JSON exists; the separation from the Agent contract is an explicit future guard ([Agent architecture](../adr/0002-make-transfer-agent-native.md)). | **Missing** |
| 1,000,000 compact events and deterministic rebuild | No event scale fixture or rebuild test exists in the current test map ([tests map](../../CONTRIBUTING.md#repository-map)). | **Missing** |
| No engagement score, productivity ranking, musical-quality judgment, or telemetry | These are issue guardrails, not implemented behavior; current repository CI also forbids credentialed/live service capability ([CI policy test](../../tests/test_release_channels.py#L61-L149)). | **Present guard** |
| Release-note record | No #132 record exists ([pending records](../../.release-notes)). | **Missing** |

## Dependency order and parallel-safe lanes

```text
human gate #136 ──┐
closed #137 ──────┴─> #138 -> #139 -> #140 -> #141
                                            |
                                            +-> #142 --+
                                            +-> #143 --+  (sequence, not parallel)
                                                       |
                                                       +-> #144 --+
                                                       +-> #145 --+  (sequence, not parallel)
                                                                  |
                                                                  -> #146 -> #147
                                                                              |
                                               +------------------------------+-------------------+
                                               |                              |                   |
                                             #130                           #132                #148
                                               +------------------------------+-------------------+
                                                                              |
                                                          closed #131 --------+-> #149
```

Although #142/#143 and #144/#145 are sibling dependencies, each issue declares the **Operational authority** lane and forbids concurrent work that changes Transfer persistence or the Operational Store interface. Implement one at a time, with either sibling order acceptable, then integrate. #146 is an explicit integration gate and starts only when Runtime Assembly and Operational Store lanes are idle at accepted commits. After #147, [#130](https://github.com/spontain112/djsupport/issues/130), #132, and #148 can run in parallel because they occupy Operational-authority review, read-only diagnostics, and separate public-documentation lanes respectively; [#131](https://github.com/spontain112/djsupport/issues/131) is already closed. #149 waits for all four named dependencies.

## TDD seams that should be reused

| Ticket(s) | First failing test seam | Reusable current evidence |
| --- | --- | --- |
| #138 | One parameterized Operational Store conformance suite, instantiated with in-memory and temp-file SQLite adapters; drive a Preview through `Transfer`, close/reopen, and compare exact aggregate state including duplicate occurrences and events. | [`Transfer` tests](../../tests/test_transfer.py), [source occurrence model](../../djsupport/source_facts.py) |
| #139 | Two independent SQLite connections: distinct-entity writes both survive; same-entity stale expected revision returns the stable reload-before-retry failure; injected commit faults leave old/next complete state; synthetic Spotify asserts no open local transaction at callback. | [file stale-write logic](../../djsupport/transfer.py#L1300-L1347), [runtime cross-client refresh](../../tests/test_runtime.py#L103-L135) |
| #140 | Table-drive `before_call`, `after_call`, and `before_result_retention` crashes through Transfer and a recording Spotify fake; reopen the store and assert journal classification plus at-most-one provable playlist identity. | [publication recovery tests](../../tests/test_transfer.py#L2378-L2478), [checkpointed publication](../../djsupport/transfer.py#L6033-L6098) |
| #141 | Inject a local commit failure after every staged Approval category and assert no authority-bearing row changes; then repeat the same completed Approval and stale manifest/head variants. | [Approval tests](../../tests/test_transfer.py#L2784-L3372), [Qualification Approval tests](../../tests/test_agent_contract.py#L1122-L1265) |
| #142 | Parameterize current Qualification lifecycle/recovery tests over stores; add 1,000 synthetic drafts and direct absence checks for paths, filenames, fingerprints, and audition handles. | [`test_qualification.py`](../../tests/test_qualification.py), [draft state](../../djsupport/transfer.py#L381-L430) |
| #143 | Parameterize the complete Mirror/Drift/orphan suite; inject interruption at create/replace/description/relink/remove journal boundaries and assert no inferred destructive choice. | [Mirror tests](../../tests/test_transfer.py#L882-L1568), [Mirror lifecycle](../lifecycles.md#mirror-drift-and-orphaning) |
| #144 | Build a synthetic fixture matrix for every version in `SUPPORTED_SCHEMAS`; hash source bytes before/after Preview and injected faults; compare a normalized whole-store identity projection and a redacted report. | [supported schemas](../../djsupport/backup.py#L21-L32), [migration tests](../../tests/test_migration.py) |
| #145 | Keep an active WAL-backed writer while taking a backup, validate a reopened snapshot, tamper each archive layer, inject replacement failure, and run platform-path cases with invented data only. | [backup tests](../../tests/test_backup.py), [archive reader](../../djsupport/backup.py#L190-L221) |
| #146 | Table-drive every staging/verification/install/activation crash point; reconstruct Runtime Assembly after each and assert exactly one authority, no dual writes, and no fallback. | [Runtime Assembly tests](../../tests/test_runtime.py), [current assembly seam](../../djsupport/runtime.py#L142-L217) |
| #147 | Deletion tests first: production import graph contains no JSON writer; old locks/temp paths/schema constants disappear; interface conformance plus public Transfer tests remain green; privacy/package filename corpus is exhaustive. | [architecture source map](../architecture.md#production-source-map), [privacy tests](../../tests/test_repository_privacy.py) |
| #132 | Populate deterministic synthetic events, rebuild every SQL view twice, compare results, test deletion independent of authority rows, and run the denylist over the experimental JSON at 1,000,000 events. | [Agent redaction contract](../adr/0002-make-transfer-agent-native.md#L26-L31) |
| #148 | In `djsupport-docs`, use only commands frozen by #147; build and link-check the site and scan the diff for private paths/data. Product-repo tests cannot substitute for that repository's gates. | [documentation ownership](../../AGENTS.md#what-goes-where), [#148](https://github.com/spontain112/djsupport/issues/148) |
| #149 | Install the exact wheel in disposable environments and execute synthetic Preview, cutover, resume, restore, rollback, and diagnostics; never rebuild a later SHA to stand in for the candidate. | [release checklist](../releasing.md), [current package job](../../.github/workflows/ci.yml#L57-L162) |

## Work that can be front-loaded safely

These preparations do not claim a blocked execution lane and contain no production authority switch:

1. **Synthetic fixture specification.** Define invented accounts, selections, duplicate occurrences, proposals, conflicts, drafts, Mirrors, incomplete effects, and events from the canonical domain identities. Do not serialize owner-derived examples ([domain identities](../domain-model.md#identity-layers), [fixture policy](../../CONTRIBUTING.md#protect-local-dj-data)).
2. **Legacy-version matrix.** Enumerate every supported JSON reader version from executable constants and identify the smallest synthetic fixture for each. This can be reviewed before #144, but the importer itself belongs to its Operational-authority lane ([backup constants](../../djsupport/backup.py#L21-L32)).
3. **Crash/fault matrix.** Write the named phase table for transaction commit, each Effect Journal boundary, migration staging/verification/activation, snapshot/restore, and diagnostics rebuild. Fault hooks may land only with their owning ticket; the research matrix itself is parallel-safe.
4. **Privacy filename corpus.** Prepare expected ignore/rejection cases for the database, `-wal`, `-shm`, snapshots, backups, restore staging/extraction, diagnostics, query exports, legacy JSON, reports, and temporary copies. Adding production patterns belongs in #138/#145/#147 as specified; no real artifact is needed ([current privacy tests](../../tests/test_repository_privacy.py)).
5. **Cross-platform CI design.** Specify the minimum macOS/Windows persistence jobs and Linux 3.10/3.14 edges without enabling credentials or live services. Current CI is read-only and offline, which must be preserved ([CI policy](../../tests/test_release_channels.py#L61-L149)).
6. **Diagnostics contract draft.** Define allowed aggregate categories, stable reason codes, explicit experimental versioning, deletion semantics, and the denylist before #132. Do not add telemetry, scores, or a second authority surface ([#132](https://github.com/spontain112/djsupport/issues/132)).
7. **Public-doc outline only.** The djsupport-docs lane may outline headings and link ownership, but final commands/outcomes and implementation claims wait for #147. Do not duplicate the internal schema or use private screenshots ([#148](https://github.com/spontain112/djsupport/issues/148)).
8. **Primary-source SQLite research packet.** Before #138 implementation, record the exact Python `sqlite3` contracts chosen for transaction boundaries, busy timeout, WAL, integrity checks, backup, supported Python versions, and platform behavior. That decision belongs in the product ADR/source tree, not in client adapters; it must not weaken #125's accepted constraints ([#125](https://github.com/spontain112/djsupport/issues/125), [architecture ownership](../../AGENTS.md#what-goes-where)).

## Verification command ladder

Run focused tests continuously, then the complete gates once per finished ticket. Proposed module names below become commands only after their owning ticket adds them.

```bash
# Existing regression baselines
python3 -m pytest tests/test_runtime.py tests/test_transfer.py tests/test_qualification.py
python3 -m pytest tests/test_migration.py tests/test_backup.py
python3 -m pytest tests/test_repository_privacy.py tests/test_release_records.py

# Proposed focused Operational Store surfaces
python3 -m pytest tests/test_operational_store.py
python3 -m pytest tests/test_operational_store_concurrency.py
python3 -m pytest tests/test_effect_journal.py
python3 -m pytest tests/test_operational_store_migration.py
python3 -m pytest tests/test_operational_store_backup.py
python3 -m pytest tests/test_operational_diagnostics.py

# End-of-ticket product gates
python3 -m pytest
python3 -m compileall -q djsupport tests
python3 scripts/release_records.py check origin/main HEAD
python3 -m build
```

For #139, passing locally is insufficient: GitHub CI must show macOS, Windows, Linux/Python 3.10, and Linux/Python 3.14 persistence coverage on the exact commit. For #145/#149, list and inspect both built archives and install the exact wheel in a disposable environment using the canonical commands in the [release checklist](../releasing.md#4-run-the-complete-release-validation). For #148, use the djsupport-docs repository's own build and link-check commands after inspecting its current tooling; do not invent or duplicate them here.

## Non-negotiable boundaries

- Use invented synthetic state only. Databases, WAL/SHM sidecars, snapshots, backups, diagnostics, exports, reports, JSON authority files, paths, playlist identifiers, matching knowledge, and evidence are private user data and never repository/package content ([ADR-0001](../adr/0001-keep-user-data-out-of-the-repository.md), [storage privacy](../storage.md)).
- No live Spotify or Beatport call, owner Rekordbox/audio read, playlist mutation, tag, GitHub Release, package publication, remote change, or user-derived export is authorized by these issues or this research ([AGENTS boundaries](../../AGENTS.md#boundaries), [#125](https://github.com/spontain112/djsupport/issues/125)).
- Preview is non-authoritative and never authorizes Spotify mutation; Qualification remains non-authoritative until separate playlist-scoped Approval ([domain invariants](../domain-model.md#core-invariants), [authority ladder](../domain-model.md#authority-ladder)).
- Never hold a database transaction across an external effect. Intent and observation are separate durable journal transitions; uncertain effects require reconciliation or review rather than guessed replay ([#128](https://github.com/spontain112/djsupport/issues/128), [#140](https://github.com/spontain112/djsupport/issues/140)).
- Do not dual-write and do not retain a production JSON fallback after cutover. Before #146 activation, JSON remains authoritative; after verified activation and #147 contraction, legacy JSON is read only through explicit migration/rollback ([#138](https://github.com/spontain112/djsupport/issues/138), [#146](https://github.com/spontain112/djsupport/issues/146), [#147](https://github.com/spontain112/djsupport/issues/147)).
- Keep configuration and Spotipy-managed credentials outside the Operational Store and every backup/migration payload ([storage configuration](../storage.md#configuration-and-credentials), [#144](https://github.com/spontain112/djsupport/issues/144)).
- Transfer remains the only public policy authority. Operational Store, Runtime Assembly, diagnostics, docs, and clients stay internal/adaptive surfaces and do not create matching, Approval, publication, or destructive intent ([architecture](../architecture.md), [Agent decision](../adr/0002-make-transfer-agent-native.md)).
