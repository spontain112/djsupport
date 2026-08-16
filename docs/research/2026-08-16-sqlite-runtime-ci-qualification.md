# SQLite runtime and CI qualification for concurrent WAL authority

**Date:** 2026-08-16

**Code baseline:** `main` at `4be422b5565ac5491084771afa04784b2289318b`

**Status:** Read-only qualification research for
[#125](https://github.com/spontain112/djsupport/issues/125),
[#139](https://github.com/spontain112/djsupport/issues/139), and
[#149](https://github.com/spontain112/djsupport/issues/149). No production
authority switch, owner-data access, live service call, release, commit, or push
was performed.

**Authority:** Repository requirements and primary sources from SQLite, Python,
CPython, GitHub Actions, and operating-system vendors. “DJ Support should” and
“the workflow must” statements below are implementation inferences from those
sources.

## Executive decision

Issue #139 cannot safely enable concurrent WAL authority on the stock GitHub
Actions Python runtimes observed on 2026-08-16. SQLite says the WAL-reset race is
likely present from 3.7.0 through 3.51.2, is fixed in 3.51.3 and later, and has
backports for 3.44.6 and 3.50.7. The race requires multiple connections plus an
overlap between checkpointing and a commit that resets the WAL; SQLite could not
reproduce it organically and used special internal test logic. Its recommendation
is to upgrade, not to certify an application-level workaround.
([SQLite WAL-reset advisory](https://sqlite.org/wal.html#the_wal_reset_bug))

The current repository CI runs only `ubuntu-latest` with floating Python `3.10`
and `3.14` selectors ([workflow](../../.github/workflows/ci.yml)). The current
GitHub Ubuntu 24.04 image advertises SQLite 3.45.1, while Canonical's current Noble
package is 3.45.1-1ubuntu2.7 and its changelog does not carry the WAL-reset fix.
The current official CPython 3.14.7 Windows and macOS build recipes bundle SQLite
3.50.4. Those versions are within the advisory's affected range.
([Ubuntu 24.04 runner manifest](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md),
[Ubuntu Noble package](https://packages.ubuntu.com/noble/libsqlite3-0),
[Canonical package changelog](https://changelogs.ubuntu.com/changelogs/pool/main/s/sqlite3/sqlite3_3.45.1-1ubuntu2.7/changelog),
[CPython 3.14.7 Windows build](https://github.com/python/cpython/blob/v3.14.7/PCbuild/readme.txt),
[CPython 3.14.7 macOS build](https://github.com/python/cpython/blob/v3.14.7/Mac/BuildScript/build-installer.py))

Therefore the safe implementation order is:

1. Implement a runtime capability probe and an exact, reviewed evidence policy.
2. Keep concurrent WAL production authority unavailable when the runtime is
   affected, withdrawn, unknown, or only numerically “new enough.”
3. Add native cross-platform persistence tests, but do not mistake a passing
   stress test for proof that SQLite contains the upstream fix.
4. Qualify the exact selected-binding artifact and its SQLite runtime in every
   required release cell before #139 or #149 can pass.

This document audits the currently accepted standard-library `sqlite3` route.
The companion
[runtime delivery research](2026-08-16-sqlite-runtime-qualification-and-delivery.md)
finds that a qualified bundled binding is the strongest cross-platform delivery
route and recommends APSW 3.53.4.0 behind an explicit decision gate. If that
amendment is accepted, every production qualification rule below applies to the
selected APSW artifact and its embedded SQLite runtime; standard-library
`sqlite3` observations remain compatibility evidence only. The product must
probe the binding that actually opens the Operational Store, never a different
SQLite wrapper loaded in the same process.

There must be no user setting, environment variable, or undocumented switch that
overrides the gate. A vendor backport can be admitted without a user toggle only
through a reviewed evidence entry tied to exact runtime fingerprints and primary
vendor patch evidence.

## 1. What the repository currently proves

| Requirement | Current evidence | Qualification consequence |
| --- | --- | --- |
| Python support | `pyproject.toml` declares Python 3.10+, and CI runs the full suite on floating `3.10` and `3.14`. | Keep both Linux edges, but pin exact patch releases for release qualification. |
| Operating systems | CI has only `ubuntu-latest`; no native macOS or Windows persistence job exists. | #139's macOS/Linux/Windows requirement is not met. |
| SQLite behavior | No production SQLite adapter or runtime gate exists yet. | Existing green CI cannot qualify concurrent WAL authority. |
| Offline/least privilege | CI has read-only contents permission, pinned checkout/setup-python actions, no service credentials, and the complete offline suite. | New jobs must preserve those constraints. |
| Evidence retention | Repository policy test explicitly forbids `upload-artifact`. | Initially emit a redacted JSON record to the log and job summary. Adding uploaded artifacts requires a separate reviewed workflow-policy change. |
| Release candidate | Package validation builds once on Ubuntu/Python 3.14, but does not run a cross-platform persistence suite against that exact wheel. | #149 must install the same wheel digest in all qualification cells. |

These conclusions follow from the current
[CI workflow](../../.github/workflows/ci.yml),
[release-channel policy test](../../tests/test_release_channels.py),
[runtime test surface](../../tests/test_runtime.py), and the merged
[concurrency/durability contract](2026-08-16-sqlite-concurrency-durability-contract.md).

## 2. Why the selected binding's runtime is the evidence boundary

For the currently accepted standard-library route, Python documents
`sqlite3.sqlite_version` and `sqlite3.sqlite_version_info` as the version of the
SQLite library loaded by that wrapper. It is distinct from the Python wrapper's
own version. SQLite exposes `sqlite_source_id()` as the check-in timestamp and
source-tree hash of the running library. These are the facts the application will
execute, so the probe must obtain them through the exact binding that opens the
Operational Store. If another binding is selected, its wrapper identity and
native artifact replace `_sqlite3` in the evidence tuple; probing the standard
library would not qualify that store.
([Python 3.10 runtime API](https://docs.python.org/3.10/library/sqlite3.html#sqlite3.sqlite_version),
[SQLite runtime/source ID API](https://sqlite.org/c3ref/libversion.html),
[SQLite `sqlite_source_id()`](https://sqlite.org/lang_corefunc.html#sqlite_source_id))

An operating-system package version is supporting provenance, not a substitute
for this probe:

- GitHub's Ubuntu Python builder installs the distribution SQLite development
  library and builds CPython against it. The resulting interpreter normally loads
  the runner's shared SQLite library, so the exact runner image and installed
  library build can change independently of the requested Python minor version.
  ([Actions Ubuntu builder](https://github.com/actions/python-versions/blob/main/builders/ubuntu-python-builder.psm1))
- For modern macOS and Windows, `actions/python-versions` wraps the official
  python.org installers. CPython's platform build sources identify the bundled
  SQLite, and that library need not equal the operating system's `sqlite3`
  command or package.
  ([Actions macOS builder](https://github.com/actions/python-versions/blob/main/builders/macos-python-builder.psm1),
  [Actions Windows builder](https://github.com/actions/python-versions/blob/main/builders/win-python-builder.psm1))
- A representative interpreter probe returned SQLite `3.43.1` and source ID
  `2023-09-11 12:01:27 2d3a40c05c49e1a49264912b1a05bc2143ac0e7c3df588276ce80a4cbc9bd1b0`.
  On that macOS interpreter the extension had no dynamic SQLite dependency. The
  OS package version would therefore have been the wrong evidence; the result is
  correctly classified as `unqualified_affected`.

`actions/setup-python` first resolves its tool cache and otherwise downloads an
`actions/python-versions` release. A minor selector such as `3.14` is a moving
SemVer request, not a release-candidate identity. Runner images also change under
stable labels, and GitHub says `-latest` labels can migrate to newer operating
systems. Every qualification run must record the resolved patch version and exact
runner image; release gates must request an exact Python patch release and a
versioned OS label.
([setup-python version resolution](https://github.com/actions/setup-python#supported-version-syntax),
[actions/python-versions manifest](https://raw.githubusercontent.com/actions/python-versions/main/versions-manifest.json),
[GitHub-hosted runner images](https://github.com/actions/runner-images),
[GitHub-hosted runner documentation](https://docs.github.com/en/actions/concepts/runners/github-hosted-runners))

### Current stock-runtime finding

This table is a dated observation, not a permanent allowlist. Every workflow run
must probe again.

| Required surface | Distribution chain | Evidence available on 2026-08-16 | Result for concurrent WAL |
| --- | --- | --- | --- |
| Ubuntu 24.04, Python 3.10 | Actions-built CPython; dynamically linked distribution SQLite | Runner/package evidence points to SQLite 3.45.1; Canonical changelog has no WAL-reset backport. | `unqualified_affected` |
| Ubuntu 24.04, Python 3.14 | Same Ubuntu linkage, different interpreter | Same linked-library risk; an exact cell probe remains mandatory. | `unqualified_affected` unless the probe matches a reviewed downstream attestation |
| Native macOS 15, Python 3.14.7 | `actions/python-versions` wraps the python.org installer; CPython build recipe bundles SQLite 3.50.4 | SQLite is bundled with the interpreter, not inferred from macOS. | `unqualified_affected` |
| Windows 2025, Python 3.14.7 x64 | `actions/python-versions` wraps the python.org installer; CPython build recipe bundles SQLite 3.50.4 | SQLite is bundled with the interpreter, not inferred from Windows. | `unqualified_affected` |

CPython `main` has moved to a later SQLite release, but unreleased branch state
does not qualify any released Python artifact. Likewise, building a patched
interpreter only inside CI proves that curated artifact, not the Python that a
normal end user already has installed.

## 3. Runtime qualification policy

### 3.1 Classification, not a numeric minimum

A predicate such as `sqlite_version >= 3.51.3` is unsafe for three reasons:

1. It rejects upstream's supported 3.44.6 and 3.50.7 backports.
2. It can accept a vendor version string whose source does not contain the fix.
3. It accepts SQLite 3.52.0, which SQLite withdrew because of expression-index
   interoperability. A withdrawn build is not a production-qualified runtime
   merely because it contains the WAL patch.
   ([SQLite news](https://sqlite.org/news.html))

The runtime policy should return one of five explicit states:

| State | Meaning | Product behavior |
| --- | --- | --- |
| `qualified_upstream` | Exact version and source ID match a reviewed, non-withdrawn upstream release containing the fix. | Concurrent WAL may proceed, subject to the rest of #139's tests. |
| `qualified_downstream_attestation` | Exact runtime/build fingerprints match a reviewed vendor backport entry. | Concurrent WAL may proceed with the evidence ID recorded. |
| `unqualified_affected` | Runtime is in a known affected release/build family. | Fail before creating, opening for write, or converting the production store to WAL. |
| `unqualified_withdrawn` | Exact release is withdrawn or explicitly denied, including 3.52.0. | Fail closed even if the WAL fix is present. |
| `unqualified_unknown` | Missing, malformed, future, locally modified, or unmatched evidence. | Fail closed and name the missing evidence, never offer an override. |

The initial reviewed upstream evidence can include these exact public source IDs:

| Release | SQLite source ID | Basis |
| --- | --- | --- |
| 3.51.3 | `2026-03-13 10:38:09 737ae4a34738ffa0c3ff7f9bb18df914dd1cad163f28fd6b6e114a344fe6d618` | Release explicitly fixes the WAL-reset bug. |
| 3.53.0 | `2026-04-09 11:41:38 4525003a53a7fc63ca75c59b22c79608659ca12f0131f52c18637f829977f20b` | First non-withdrawn 3.53 release; release notes explicitly include the fix. |
| 3.53.4 | `2026-07-24 19:02:57 bf7c7f30031888f4e796e429ab3978879485813aaca6f641c7b33e4e09459bcc` | Current official release fingerprint at this research date. |

([SQLite 3.51.3 release](https://sqlite.org/releaselog/3_51_3.html),
[SQLite 3.53.0 release](https://sqlite.org/releaselog/3_53_0.html),
[SQLite 3.53.4 release](https://sqlite.org/releaselog/3_53_4.html))

That table is deliberately exact and conservative. It is not a rule that all
other versions fail forever: each later upstream release is added after its
official release/source ID and withdrawal status are reviewed. The advisory-linked
3.44.6 and 3.50.7 backports may likewise be admitted only with the exact source ID
returned by the candidate runtime. The advisory's backport labels alone must not
silently authorize a distributor-modified binary.

### 3.2 Downstream backport evidence schema

A downstream build can keep an older numeric version, and a vendor patch may not
make the source ID alone sufficient. Admission therefore requires one
maintainer-reviewed, repository-owned public evidence entry with all applicable
selectors:

```json
{
  "schema_version": 1,
  "evidence_id": "sqlite-wal-reset/<vendor>/<product>/<build>",
  "status": "active",
  "distributor": "public vendor name",
  "product": "public runtime/package name",
  "channel": "stable",
  "os": {"name": "...", "release": "...", "architecture": "..."},
  "python": {
    "implementation": "CPython",
    "version": "exact patch version",
    "build": "public build identity"
  },
  "sqlite": {
    "version": "runtime-reported version",
    "source_id": "runtime-reported full source ID",
    "compile_options_sha256": "sha256 of sorted compile options"
  },
  "binary": {
    "binding_extension_sha256": "sha256, no filesystem path",
    "linked_sqlite_sha256": "sha256 when dynamically linked",
    "vendor_package": "exact package and build version when applicable"
  },
  "fix": {
    "upstream_checkin": "official SQLite fix/backport check-in URL",
    "vendor_advisory": "official vendor advisory/changelog URL",
    "vendor_patch_digest": "sha256 of the reviewed public patch"
  },
  "qualification": {
    "repository_commit": "full DJ Support SHA",
    "workflow_run": "public Actions run URL",
    "qualified_at_utc": "RFC 3339 timestamp",
    "reviewed_by": "public maintainer identity"
  },
  "supersedes": null,
  "revoked_at_utc": null
}
```

Rules for applying an attestation:

- Match every populated selector exactly. No prefix, version range, wildcard,
  “same package family,” or user assertion is accepted.
- On dynamically linked systems, match the loaded SQLite library build as well as
  the selected Python binding extension. Hashing only the wrapper is insufficient
  when the shared library can be upgraded independently.
- Require a primary vendor advisory, changelog, or public source patch that maps
  the vendor change to SQLite's fix. A passing black-box race test is not patch
  provenance.
- Treat missing or conflicting fields as `unqualified_unknown`.
- Revocation is fail-closed and ships through the normal reviewed code/release
  path. It does not require or permit an end-user toggle.

This lets a real downstream backport work without forcing all users onto one
SQLite number, while preserving an auditable reason for every accepted binary.

## 4. Capability probe contract

The same probe should run in product startup, unit tests, every persistence CI
cell, and release qualification. It must execute before the production adapter
creates a database, enables WAL, runs a migration, or accepts a write.

### Required inputs

Collect from the running interpreter and selected Operational Store binding:

- Probe schema and policy version.
- Python implementation, exact `sys.version_info`, public build/compiler identity,
  and architecture. Do not record `sys.executable` or module paths.
- OS name, release, architecture, requested runner label, and exact runner image
  version.
- Binding package/distribution name and exact wrapper version.
- The binding's reported SQLite version plus `SELECT sqlite_source_id()` from a
  fresh in-memory connection created by that same binding.
- Sorted `PRAGMA compile_options`; hash the full sorted set and retain the
  non-sensitive options required by the connection contract.
- SHA-256 of the selected native binding extension bytes, but not its path.
- When dynamically linked, SHA-256 and exact public package/build identity of the
  loaded SQLite library, again without a filesystem path.
- Exact policy result, evidence ID if matched, and a stable public reason code.

For the standard-library compatibility route, also collect
`sqlite3.sqlite_version`, `sqlite3.sqlite_version_info`, and
`sqlite3.threadsafety`. For a bundled binding, collect its documented equivalent
identity APIs and the exact installed wheel/distribution identity. Never combine
the wrapper identity from one binding with the SQLite runtime from another.

Python 3.10 hard-codes its DB-API `threadsafety` value, while newer Python derives
it from SQLite's threading mode. The probe should therefore retain the
`THREADSAFE` compile option as cross-version evidence rather than treating
`sqlite3.threadsafety` alone as equivalent across 3.10 and 3.14.
([Python 3.10 `threadsafety`](https://docs.python.org/3.10/library/sqlite3.html#sqlite3.threadsafety),
[Python 3.14 `threadsafety`](https://docs.python.org/3.14/library/sqlite3.html#sqlite3.threadsafety))

### Required outputs and behavior

The probe returns a typed result, never a bare Boolean. A successful result names
the exact evidence entry. A failure contains only safe remediation such as
“install a supported DJ Support/Python build whose linked SQLite runtime is
qualified”; it must not print local database paths, Python installation paths, or
environment dumps.

The production gate then obeys these invariants:

```text
probe -> qualified_*        -> adapter may open/enable WAL -> normal #139 checks
probe -> unqualified_*      -> raise before store mutation -> no override/fallback
probe cannot collect proof  -> unqualified_unknown         -> no override/fallback
```

Policy unit tests should feed invented probe records for each classification,
including exact matches, one-field mismatches, modified source IDs, missing linked
library hashes, future releases, official backports, revoked attestations, and the
explicit 3.52.0 deny. No test needs a real user database or local path.

## 5. No-autocheckpoint plus quiesced checkpoints is not qualification

It is theoretically possible to narrow the advisory's race by disabling automatic
checkpoints on every connection and running manual checkpoints only while all
writers are globally quiesced. That is not a supported substitute for a patched
runtime:

- SQLite says the race needs a second checkpoint to start while another
  connection commits and resets the WAL. It still recommends upgrading.
  ([advisory details](https://sqlite.org/wal.html#the_wal_reset_bug))
- `wal_autocheckpoint` configures a connection; every code path and process must
  obey the same policy. SQLite also checkpoints when the last connection closes.
  ([automatic checkpoints](https://sqlite.org/wal.html#automatic_checkpoint),
  [WAL lifecycle](https://sqlite.org/wal.html#avoiding_excessively_large_wal_files))
- Preventing close-time checkpointing requires the C-level
  `SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE` control. Python exposes database-config
  controls only from 3.12, so Python 3.10 cannot implement one common stdlib-only
  control surface for the supported range.
  ([Python 3.14 `setconfig`](https://docs.python.org/3.14/library/sqlite3.html#sqlite3.Connection.setconfig),
  [SQLite database configuration](https://sqlite.org/c3ref/c_dbconfig_defensive.html))
- A test that fails to reproduce a rare race cannot prove that all present and
  future connection-close/checkpoint paths are globally quiesced. SQLite itself
  needed special test instrumentation.

CI could only support that mitigation claim with a single enforceable connection
factory, control over every process, proof that every connection has
autocheckpoint disabled, a complete close-checkpoint control on every supported
Python, a global checkpoint coordinator whose exclusion is mechanically tested,
and deterministic upstream-equivalent fault instrumentation. Those preconditions
are not available through the Python 3.10 standard library, and upstream does not
bless the workaround. Reject it as a qualification route; at most use explicit
checkpoint scheduling as defense in depth on an already qualified runtime.

## 6. CI topology and fail-versus-skip policy

Use two visibly different job classes.

### 6.1 Stock-runtime compatibility observation

Keep the ordinary full-suite Linux matrix on Python 3.10 and 3.14. Add the probe
and test that known affected/unknown stock runtimes are rejected before WAL
mutation. Such a cell can pass by proving fail-closed behavior, but its job name
and JSON result must say `compatibility-observation`; it is never evidence that
#139 may activate.

### 6.2 Required qualified-persistence matrix

Once an exact safe runtime artifact exists for every row, require this matrix on
#139 and on the exact #149 release-candidate commit:

| Cell | Runner | Python selector | Required proof |
| --- | --- | --- | --- |
| Linux lower edge | `ubuntu-24.04` x64 | exact supported 3.10 patch | Qualified linked SQLite plus complete persistence suite |
| Linux upper edge | `ubuntu-24.04` x64 | exact supported 3.14 patch | Qualified linked SQLite plus complete persistence suite |
| Native macOS | `macos-15` arm64 | exact supported 3.14 patch | Qualified selected-binding SQLite plus complete persistence suite |
| Native Windows | `windows-2025` x64 | exact supported 3.14 patch | Qualified selected-binding SQLite plus complete persistence suite |

This meets #139's explicit Linux version edges and native three-OS surface without
claiming support for an architecture that was never tested. If DJ Support promises
Intel macOS too, add a separate native Intel cell; do not let emulation stand in
for it. Versioned labels reduce, but do not eliminate, runner drift, so the exact
image remains part of the evidence.

All rows use the same repository SHA and, for #149, install the same wheel SHA-256.
Actions stay pinned to full commit SHAs; permissions remain `contents: read`; no
Spotify/Beatport credentials or calls are introduced.

### Fail-versus-skip rules

- Policy/classification unit tests run everywhere and **fail** on a missing field,
  unexpected classification, or denylist regression. They never skip.
- A required persistence cell **fails** if the probe is not `qualified_*`. It may
  not use `pytest.skip`, `continue-on-error`, dynamic matrix exclusion, or an
  expected-failure marker.
- A stock observation cell may pass only after asserting the exact fail-closed
  state. It cannot satisfy the required qualification job or be counted as a
  release-platform pass.
- A runner outage or unavailable exact interpreter leaves the required check
  incomplete/failed. It is not converted to a skip.
- Experimental architectures may run in a clearly non-required job, but their
  result is never substituted for a required row.
- Any scope change needed to make a row available stops #149 for a reviewed
  decision; it does not weaken the gate.

This distinction allows useful CI on today's unsafe stock interpreters while
making it impossible for an expected rejection to masquerade as production
qualification.

## 7. Concurrency and crash tests

Runtime provenance and application conformance are independent evidence. The
probe proves which SQLite is running; tests prove DJ Support uses it correctly.

### Required on every pull request in each qualified cell

- Open fresh connections in independent child processes using platform-native
  process creation. Never share a connection across a fork, thread, or process.
- Verify the connection factory's WAL, `synchronous=FULL`, foreign-key, busy-timeout,
  and transaction settings on every connection.
- Coordinate two writers with events/pipes, not timing sleeps, and prove distinct
  entity writes both persist through close/reopen.
- Race two revision-qualified writes to the same entity and prove exactly one wins
  while the stale revision fails closed.
- Hold the writer lock deliberately and prove bounded busy handling returns the
  domain result within the documented limit.
- Keep a reader snapshot open while a writer commits and a checkpoint is
  requested; prove snapshot stability, later visibility, and integrity after
  reopen.
- Put a synthetic external-call callback between two database units of work and
  assert no transaction remains open while that callback runs.
- Run `PRAGMA quick_check`, `PRAGMA integrity_check`, and
  `PRAGMA foreign_key_check` after concurrency and after every crash/reopen case.
- Crash a child before `BEGIN`, after writes but before `COMMIT`, and immediately
  after `COMMIT` returns. On reopen, require the exact prior or next domain state,
  never a mixture. Python documents `os._exit()` as immediate process exit and
  `multiprocessing` provides cross-platform process contexts.
  ([Python `os._exit`](https://docs.python.org/3.10/library/os.html#os._exit),
  [Python multiprocessing contexts](https://docs.python.org/3.14/library/multiprocessing.html#contexts-and-start-methods))

### Extended scheduled/manual qualification

- Repeat the independent-process writer/checkpointer scenario enough times to
  expose application locking mistakes, with bounded total duration.
- Exercise long-reader/checkpoint pressure, every supported migration boundary,
  and each deterministic application fault seam.
- Run the entire matrix manually for #149 against an exact commit and wheel
  digest. A schedule is useful drift detection, but only the exact candidate run
  is release evidence.

### What these tests cannot prove

A successful stress run does not prove absence of the WAL-reset bug. SQLite says
the race was not organically reproducible and its deterministic trigger used
special internal logic. `sqlite3_test_control()` is test-only, may be omitted at
compile time, and can change without notice, so hosted Python binaries cannot be
assumed to expose an upstream-equivalent trigger.
([SQLite testing interface](https://sqlite.org/c3ref/test_control.html),
[SQLite testing](https://sqlite.org/testing.html))

Likewise, Python's progress handler runs after a configured number of virtual
machine instructions; the documentation does not promise a callback at a specific
point inside the C `COMMIT` path. It cannot be labeled “crash during commit” until
a test first demonstrates the intended injection point. If #139 requires an exact
kill inside C commit rather than the three observable transaction boundaries, the
ticket needs a reviewed test-only VFS/fault harness. The acceptance criterion must
not be silently skipped.
([Python progress handler](https://docs.python.org/3.10/library/sqlite3.html#sqlite3.Connection.set_progress_handler))

Hosted-runner process kills prove application-visible process-crash atomicity on
that runner filesystem. They do not prove physical power-loss behavior, storage
firmware honesty, or every filesystem's `fsync` implementation.

## 8. Auditable CI evidence

Each cell should emit one path-free `sqlite-runtime-qualification.json` payload to
the log and `$GITHUB_STEP_SUMMARY`. It contains only synthetic/public build data:

- schema and policy versions;
- repository full SHA, workflow name, run ID/attempt, job, UTC time;
- requested runner label, OS/release/architecture, exact runner image version, and
  included-software manifest URL;
- full action commit SHAs;
- requested and resolved Python versions, implementation/build identity, and the
  exact `actions/python-versions` release/asset when used;
- all capability-probe fields and the resulting state/evidence ID;
- test selection, pass/fail/error counts, durations, and final result;
- exact wheel SHA-256 for #149 candidate runs.

Do not include environment dumps, usernames, hostnames, home/temp paths, database
names, database/WAL/SHM bytes, snapshots, reports, playlist identifiers, or any
owner-derived fixture. Tests use invented state only.

The present repository test rejects `upload-artifact`; therefore an implementation
that merely adds `actions/upload-artifact` would violate the existing least-
privilege contract. The first safe route is durable public job logs/summaries plus
the exact run URLs recorded in #149. If downloadable JSON retention is later
required, change the workflow policy in a separate reviewed scope: pin the upload
action by full SHA, allow only the one generated JSON file, set bounded retention,
inspect its contents, and keep all database/crash files excluded.

## 9. Evidence limits and unstable inputs

| Evidence | What it proves | What it does not prove |
| --- | --- | --- |
| Binding-reported SQLite version | Numeric version reported by the selected Operational Store binding | Patch presence, withdrawal status, or vendor backport identity |
| `sqlite_source_id()` | Upstream check-in identity for an unmodified build; edited amalgamations may change only part of the ID | That a distro backport changed its version/source ID, or that an arbitrary binary is trusted |
| OS package/advisory | Vendor-supported package build and documented patch provenance | The Python process loaded that package on macOS/Windows or in a custom interpreter |
| Binding-extension hash | Exact selected Python extension artifact | Exact shared `libsqlite3` on dynamically linked systems |
| Linked-library hash | Exact binary loaded for one dynamic build | Semantic safety without reviewed patch provenance |
| CPython build source | What the official tagged build recipe intended to bundle | The exact bytes loaded by a particular runner; probe them |
| Runner manifest | Snapshot of advertised image contents | Future contents of the same label |
| Exact Python selector | Requested/resolved interpreter patch line | SQLite safety; the bundled/system library still needs probing |
| Concurrency/crash tests | DJ Support behavior under tested schedules and process failures | Absence of a rare upstream race or real hardware power-loss semantics |
| `sqlite3_test_control` | Upstream internal fault injection when present in a controlled SQLite build | A stable production API or capability of hosted Python binaries |

The absence of a public Canonical WAL-reset advisory/backport for the current
Noble package is an evidence gap, not proof that no private or future patch exists.
The correct state remains `unqualified_unknown` or `unqualified_affected` until
official evidence and the actual runtime fingerprint agree.

## 10. Ticket acceptance criteria

### #139 — qualify before production authority

- [ ] A single runtime-probe implementation interrogates the binding that opens
  the Operational Store, produces all required safe metadata on Python 3.10 and
  3.14, and classifies exact upstream, downstream, affected, withdrawn, revoked,
  malformed, and unknown cases.
- [ ] The policy uses exact reviewed version/source/build evidence, explicitly
  rejects SQLite 3.52.0, and does not implement a bare numeric-minimum gate.
- [ ] Production SQLite/WAL creation, migration, and write authority fail before
  mutation on every `unqualified_*` result, with no CLI/config/environment toggle.
- [ ] A downstream backport is accepted only through the reviewed schema above and
  exact selector/fingerprint matching.
- [ ] Required CI has native Ubuntu 24.04/Python 3.10, Ubuntu 24.04/Python 3.14,
  macOS 15, and Windows 2025 cells, using exact Python patch versions and probing
  the selected binding/runtime artifact in each.
- [ ] Every required cell is `qualified_*`; a stock-runtime expected rejection is
  separately named and cannot satisfy this check.
- [ ] The independent-process concurrency, stale-revision, bounded-busy,
  checkpoint-pressure, no-external-call-in-transaction, crash/reopen, integrity,
  and foreign-key tests pass with invented state on all four cells.
- [ ] Any claim of a crash *inside* C commit is backed by a demonstrated injection
  point or reviewed test-only VFS/fault harness; otherwise the claim is narrowed
  to observable transaction boundaries.
- [ ] CI remains read-only/offline and emits a path-free evidence record. No
  database, WAL/SHM, snapshot, or owner-derived evidence is uploaded.
- [ ] The no-autocheckpoint/quiesced-checkpoint design is not accepted as a
  substitute for a patched runtime.

### #149 — release-candidate evidence

- [ ] The exact release-candidate commit and one wheel SHA-256 are identical across
  every qualification cell.
- [ ] A manually dispatched run on that exact commit completes the whole required
  matrix with no skip, xfail, `continue-on-error`, or removed row.
- [ ] Every cell's JSON/log evidence includes its exact runner image, resolved
  Python, SQLite version/source ID/binary fingerprints, policy result/evidence ID,
  test result, and wheel digest.
- [ ] The #149 record links the exact run and explains any admitted downstream
  attestation. No release/tag/publication occurs as part of qualification.
- [ ] A runner/runtime drift, failed cell, missing attestation, withdrawn build, or
  unavailable exact interpreter stops the candidate instead of weakening scope.

## 11. Concrete commands and workflow assertions

The eventual implementation should make these commands green from a clean
checkout, using the repository's final marker/file names:

```bash
python -m pytest tests/test_sqlite_runtime_qualification.py
python -m pytest tests/test_operational_store.py tests/test_operational_store_concurrency.py
python -m pytest tests/test_operational_store_crash.py
python -m pytest
python -m compileall -q djsupport tests
```

Each matrix cell should also run a path-free probe before persistence tests. The
exact module name is an implementation choice, but the assertion shape is not:

```bash
python -m djsupport.sqlite_runtime_probe --format json --require-qualified
python -m pytest -m "sqlite_persistence and not live_service"
```

Repository behavior tests should parse the workflow and assert:

- versioned native runner labels are exactly `ubuntu-24.04`, `macos-15`, and
  `windows-2025`, not `*-latest`;
- required Linux rows cover exact Python 3.10.x and 3.14.x, while macOS/Windows
  use the reviewed exact patch selector;
- checkout/setup actions remain full-SHA pinned and checkout credentials do not
  persist;
- workflow/job permissions remain `contents: read` and no service secrets exist;
- every required cell runs the probe with `--require-qualified`, the same complete
  persistence test command, and evidence emission;
- no `continue-on-error`, skip-based success, dynamic row removal, live Spotify or
  Beatport call, tag, release, package publication, or user-data upload exists;
- `upload-artifact` remains forbidden unless a separate policy change introduces
  one pinned, allowlisted, JSON-only evidence upload;
- the release workflow passes the same wheel SHA-256 to every cell and records the
  exact candidate SHA/run URL.

Until all #139 criteria are green on exact qualified runtimes, the correct CI
outcome is: ordinary compatibility tests may pass, the fail-closed runtime test
must pass, and the production concurrent-WAL qualification gate remains blocked.

## Primary sources

- SQLite: [WAL and WAL-reset advisory](https://sqlite.org/wal.html),
  [3.51.3 release](https://sqlite.org/releaselog/3_51_3.html),
  [3.53.0 release](https://sqlite.org/releaselog/3_53_0.html),
  [3.53.4 release](https://sqlite.org/releaselog/3_53_4.html),
  [news/withdrawals](https://sqlite.org/news.html),
  [runtime identity](https://sqlite.org/c3ref/libversion.html),
  [testing interface](https://sqlite.org/c3ref/test_control.html), and
  [testing overview](https://sqlite.org/testing.html).
- Python/CPython: [Python 3.10 `sqlite3`](https://docs.python.org/3.10/library/sqlite3.html),
  [Python 3.14 `sqlite3`](https://docs.python.org/3.14/library/sqlite3.html),
  [CPython 3.14.7 Windows build](https://github.com/python/cpython/blob/v3.14.7/PCbuild/readme.txt), and
  [CPython 3.14.7 macOS build](https://github.com/python/cpython/blob/v3.14.7/Mac/BuildScript/build-installer.py).
- GitHub Actions: [setup-python](https://github.com/actions/setup-python),
  [python-versions](https://github.com/actions/python-versions),
  [runner images](https://github.com/actions/runner-images), and
  [GitHub-hosted runner documentation](https://docs.github.com/en/actions/concepts/runners/github-hosted-runners).
- Ubuntu/Canonical: [Noble `libsqlite3-0`](https://packages.ubuntu.com/noble/libsqlite3-0),
  [package changelog](https://changelogs.ubuntu.com/changelogs/pool/main/s/sqlite3/sqlite3_3.45.1-1ubuntu2.7/changelog), and
  [Ubuntu security notices](https://ubuntu.com/security/notices).
