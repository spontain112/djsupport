# SQLite runtime qualification and delivery

**Date:** 2026-08-16

**Status:** Findings for an implementation decision

**Scope:** DJ Support's local Operational Store on Python 3.10-3.14, macOS, Linux, and Windows

**Evidence rule:** Primary sources only; public product and synthetic engineering evidence only

## Executive finding

DJ Support cannot guarantee a WAL-reset-safe Operational Store by requiring a Python version, testing only `sqlite3.sqlite_version`, relying on an operating-system update, or scheduling checkpoints itself. The supported Python installers and CI routes do not identify one SQLite runtime, and the official SQLite remedy for the WAL-reset corruption bug is to upgrade the SQLite library.

The production-grade route is:

1. Put a fail-closed SQLite runtime qualifier in front of every Operational Store open.
2. Ship one audited SQLite runtime as an application dependency across the supported matrix instead of inheriting whatever SQLite happens to be behind the standard-library module.
3. Record the selected binding artifact, SQLite version, SQLite source ID, build provenance, supported wheel tags, and withdrawn-release denylist in a reviewed qualification manifest.
4. Keep JSON authoritative until that runtime is installed and qualified; never silently change the database to rollback-journal mode.
5. Run the issue #139 concurrency and crash suite against the actual release artifacts on every claimed Python/OS combination.

The strongest current candidate is **APSW 3.53.4.0**, whose official wheels bundle SQLite 3.53.4 and cover Python 3.10-3.14 on the three target operating systems. It should sit behind DJ Support's internal Operational Store port so its non-DB-API interface does not escape into Transfer or adapters. Selecting it requires an explicit amendment to the accepted wording in issue #125 and the literal standard-library wording in issue #138; it must not arrive as an incidental dependency swap.

If that amendment is not accepted, the honest alternative is to keep the Python standard-library binding, qualify each concrete interpreter build, and fail closed on the common installers that remain affected or lack verified vendor-backport evidence. That alternative cannot currently promise the Operational Store on every advertised Python 3.10-3.14/macOS/Linux/Windows combination.

## Repository decision context

This analysis preserves the accepted direction while making its newly discovered runtime prerequisite explicit:

- [Issue #125](https://github.com/spontain112/djsupport/issues/125) accepted one local SQLite Operational Store, Python `sqlite3`, WAL, short transactions, bounded waits, and optimistic revisions.
- [Issue #138](https://github.com/spontain112/djsupport/issues/138) is a non-authoritative Preview and keeps production Runtime Assembly on JSON.
- [Issue #139](https://github.com/spontain112/djsupport/issues/139) introduces the independent-connection, concurrent-authority workloads that meet the upstream bug's trigger conditions and therefore needs the hard runtime gate.
- The merged [issue-frontier research](2026-08-16-operational-store-issue-frontier.md), [concurrency and durability contract](2026-08-16-sqlite-concurrency-durability-contract.md), and [migration, backup, and cutover contract](2026-08-16-sqlite-migration-backup-cutover-contract.md) establish the surrounding dependency order and fail-closed posture.

## The upstream safety boundary

SQLite's official [WAL-reset advisory](https://sqlite.org/wal.html#the_wal_reset_bug) says:

- the bug is likely present from SQLite 3.7.0 through 3.51.2;
- the fixed upstream release is 3.51.3, with official backports at 3.44.6 and 3.50.7;
- it requires WAL, at least two connections in separate threads or processes, and an overlapping write and checkpoint;
- the corrupting sequence is a completed checkpoint, a second checkpoint starting, another connection committing and resetting the WAL, and a later checkpoint skipping committed content; and
- despite the low observed probability, the consequence is corruption and application developers should upgrade.

The release number is not a monotonic allow rule. SQLite [withdrew 3.52.0](https://sqlite.org/releaselog/3_52_0.html), and the project's [news explanation](https://sqlite.org/news.html) says it could fail to interoperate with earlier releases for some expression indexes. SQLite 3.53.0 reintroduced the work with corrections. Therefore:

- `SQLite >= 3.51.3` is **not** an acceptable predicate because it admits withdrawn 3.52.0.
- 3.52.0 must be denied even though it contains the WAL-reset fix.
- An explicit withdrawn-release denylist is part of qualification, and an unknown future release does not become production-qualified merely because its number is larger.

The version merged by PR #163 used “3.51.3 or later” as a shorthand. This
research stream corrects that contract to require a positively qualified build
and explicitly deny withdrawn 3.52.0 rather than comparing one version floor.

### Initial upstream release policy

| Runtime claim | Initial result | Required evidence |
| --- | --- | --- |
| SQLite 3.44.6 | Eligible backport | Exact runtime identity plus the official 3.44.6 backport lineage linked by the advisory |
| SQLite 3.50.7 | Eligible backport | Exact runtime identity plus the official 3.50.7 backport lineage linked by the advisory |
| SQLite 3.51.3 | Eligible | Exact source ID from the [3.51.3 release](https://sqlite.org/releaselog/3_51_3.html) |
| SQLite 3.52.0 | Denied | Officially withdrawn |
| SQLite 3.53.0-3.53.4 | Eligible after artifact qualification | Exact source ID, artifact provenance, wheel matrix, and no withdrawn status; [3.53.4](https://sqlite.org/releaselog/3_53_4.html) is the current researched release |
| An older vendor version with a backport | Unknown by default | Exact vendor package/build plus a vendor source/advisory proving the WAL-reset patch |
| Any unlisted build | Denied by default | A reviewed manifest update |

“Eligible” is deliberately not “accepted from the version string.” It means a release can be added to DJ Support's qualification manifest after its concrete artifact is checked.

## Identity is more than a version string

At runtime, record at least:

- Python implementation and version;
- Python SQLite wrapper and wrapper version;
- `SELECT sqlite_version()`;
- `SELECT sqlite_source_id()`;
- `PRAGMA compile_options`;
- binding package name and installed distribution version;
- operating system, architecture, and wheel or vendor-package identity; and
- the qualification-manifest entry that admitted the build.

Qualification has two evidence layers. The release/install job records the original wheel filename, digest, and provenance. The running process checks what it can actually observe: binding distribution/version, SQLite version/source ID, compile options, OS, and architecture. An ordinary Python installation does not necessarily preserve the original wheel archive, so runtime code must not pretend it has re-verified that archive's attestation. A managed installer may retain an installation report; otherwise the exact dependency and source identity correlate the runtime to the artifact set admitted by release CI.

SQLite documents [SQLITE_SOURCE_ID](https://sqlite.org/c3ref/c_source_id.html) as the source check-in identity and exposes the corresponding [runtime library APIs](https://sqlite.org/c3ref/libversion.html). The official SQLite 3.51.3 source ID is:

`2026-03-13 10:38:09 737ae4a34738ffa0c3ff7f9bb18df914dd1cad163f28fd6b6e114a344fe6d618`

The researched current SQLite 3.53.4 source ID is:

`2026-07-24 19:02:57 bf7c7f30031888f4e796e429ab3978879485813aaca6f641c7b33e4e09459bcc`

Source ID improves evidence but is not a cryptographic attestation that an arbitrary downstream binary contains a particular backport. A vendor may retain an older upstream version, apply patches, and produce a different source ID; a locally rebuilt or edited source can also differ. A downstream build is accepted only when a reviewed entry maps the exact version, source ID, vendor package revision, platform, and architecture to:

1. an official vendor advisory or source-package change;
2. the exact patch/check-in that fixes the WAL-reset bug;
3. the artifact repository and integrity/provenance evidence; and
4. a passing DJ Support release-artifact test.

Unknown identity fails closed. Diagnostics may print these public build facts, but never the database path or user state.

## Why the standard library is not one runtime

Python's `sqlite3` module is an interface to the SQLite library used to build that interpreter. The [Python documentation](https://docs.python.org/3/library/sqlite3.html#sqlite3.sqlite_version) exposes the runtime SQLite version separately from the module version, while the [Unix build requirements](https://docs.python.org/3/using/configure.html#build-requirements) describe SQLite as a build dependency. Consequently, “Python 3.14” does not identify the SQLite build.

### Official installer evidence

The last or current binary-installing releases in each supported Python series embed the following SQLite versions in their tagged CPython build recipes:

| Python series | Official binary release inspected | Bundled SQLite in tagged macOS/Windows recipes | WAL-reset status by upstream advisory |
| --- | --- | --- | --- |
| 3.10 | [3.10.11](https://www.python.org/downloads/release/python-31011/) | 3.40.1 | Affected |
| 3.11 | [3.11.9](https://www.python.org/downloads/release/python-3119/) | 3.45.1 | Affected |
| 3.12 | [3.12.10](https://www.python.org/downloads/release/python-31210/) | 3.49.1 | Affected |
| 3.13 | [3.13.15](https://www.python.org/downloads/release/python-31315/) | 3.50.4 | Affected |
| 3.14 | [3.14.7](https://www.python.org/downloads/release/python-3147/) | 3.50.4 | Affected |

The evidence is in CPython's tagged Windows `PCbuild/python.props` and macOS `Mac/BuildScript/build-installer.py`:

- [CPython 3.10.11 Windows recipe](https://github.com/python/cpython/blob/v3.10.11/PCbuild/python.props) and [macOS recipe](https://github.com/python/cpython/blob/v3.10.11/Mac/BuildScript/build-installer.py)
- [CPython 3.11.9 Windows recipe](https://github.com/python/cpython/blob/v3.11.9/PCbuild/python.props) and [macOS recipe](https://github.com/python/cpython/blob/v3.11.9/Mac/BuildScript/build-installer.py)
- [CPython 3.12.10 Windows recipe](https://github.com/python/cpython/blob/v3.12.10/PCbuild/python.props) and [macOS recipe](https://github.com/python/cpython/blob/v3.12.10/Mac/BuildScript/build-installer.py)
- [CPython 3.13.15 Windows recipe](https://github.com/python/cpython/blob/v3.13.15/PCbuild/readme.txt) and [macOS recipe](https://github.com/python/cpython/blob/v3.13.15/Mac/BuildScript/build-installer.py)
- [CPython 3.14.7 Windows recipe](https://github.com/python/cpython/blob/v3.14.7/PCbuild/readme.txt) and [macOS recipe](https://github.com/python/cpython/blob/v3.14.7/Mac/BuildScript/build-installer.py)

The tagged macOS installer recipes compile and archive `libsqlite3.a`. The tagged Windows build downloads SQLite source and builds its own SQLite DLL before building `_sqlite3`. Those artifacts do not dynamically inherit a later SQLite fix merely because macOS or Windows updates its system library.

A de-identified probe of a current DJ Support development interpreter corroborates the official build model: a python.org-style Python 3.12 interpreter reports SQLite 3.43.1 and source ID `2023-09-11 12:01:27 2d3a40c05c49e1a49264912b1a05bc2143ac0e7c3df588276ce80a4cbc9bd1b0`, and its extension does not dynamically link a system SQLite library. This observation is supporting evidence only; the decision rests on the official CPython recipes.

### CI is also build-specific

The official [actions/setup-python advanced usage](https://github.com/actions/setup-python/blob/main/docs/advanced-usage.md) explains that hosted-toolcache entries or the `actions/python-versions` builds supply Python. The official [Ubuntu builder](https://github.com/actions/python-versions/blob/main/builders/ubuntu-python-builder.psm1) installs the distribution's `libsqlite3-dev`, while the macOS builder can use python.org installers and Windows uses official executables. A GitHub Actions matrix over Python labels therefore does not qualify SQLite unless the job interrogates the runtime it actually imported.

The present DJ Support CI matrix covers Ubuntu with Python 3.10 and 3.14. Production qualification needs all supported minor versions on macOS, Linux, and Windows, using the release installation path rather than a convenient development interpreter.

## Downstream vendor backports

Version suffixes prove that vendors patch old upstream releases, not that a particular security fix is present. For example, Ubuntu's official [USN-8480-1](https://ubuntu.com/security/notices/USN-8480-1) lists patched SQLite packages with Ubuntu revision suffixes while retaining old upstream version numbers. Ubuntu publishes the [source-package changelog](https://launchpad.net/ubuntu/+source/sqlite3/+changelog), and Debian publishes its [SQLite source-package security tracker](https://security-tracker.debian.org/tracker/source-package/sqlite3).

No official Ubuntu or Debian source found in this pass specifically proves that the installed older packages carry the 2026 WAL-reset patch. They remain unqualified until such an advisory/changelog and exact binary identity are available. A generic “security updated” status or an old version with a distro suffix is insufficient.

Even a verified operating-system backport only helps interpreters dynamically linked to that package. It cannot repair the separately bundled SQLite used by the official macOS and Windows Python builds described above. The capability probe must interrogate the imported binding, never the platform's `sqlite3` command-line tool.

## Delivery options and hard tradeoffs

### Option A: standard-library capability gate

**Shape:** Keep `sqlite3`; admit only a manifest-qualified concrete interpreter build.

**Benefits**

- No new runtime dependency or binding API.
- Preserves issue #125 and #138 wording.
- Linux distribution Python can become eligible when a vendor publishes verifiable backport evidence.

**Costs**

- Common supported python.org macOS/Windows installers are affected according to their tagged build inputs.
- Support becomes an interpreter-build matrix, not a Python-version matrix.
- A user can upgrade DJ Support without changing the vulnerable SQLite embedded in Python.
- An OS update cannot repair a statically or separately bundled interpreter.
- Source-built Python and environment managers add more build identities.

**Verdict:** Suitable as a fail-closed compatibility path, not as the default production delivery mechanism for a cross-platform guarantee.

### Option B: APSW with bundled SQLite

**Shape:** Depend on an exact qualified APSW release and keep it behind the Operational Store port.

APSW's official [comparison with pysqlite](https://rogerbinns.github.io/apsw/pysqlite.html) says its PyPI builds include SQLite statically and independently of the system SQLite. The current [APSW 3.53.4.0 project release](https://pypi.org/project/apsw/3.53.4.0/) requires Python 3.10 or newer and publishes CPython wheels for the relevant Windows, macOS, manylinux, and musllinux combinations, including Python 3.14. Its release artifacts publish PyPI provenance attestations. APSW's [copyright page](https://rogerbinns.github.io/apsw/copyright.html) describes permissive terms and required notices.

**Benefits**

- One SQLite source line across user machines rather than inheritance from each interpreter.
- Current wheels contain SQLite 3.53.4, whose official release source ID is known and whose line contains the WAL-reset fix.
- Current artifacts cover the requested Python 3.10-3.14 and desktop OS matrix.
- DJ Support's own wheel may remain pure Python because the native code is delivered by a dependency.
- Published provenance can be recorded during qualification.

**Costs**

- APSW intentionally is not Python DB-API `sqlite3`; the adapter implementation and tests must account for its transaction behavior and exception surface.
- This changes an accepted architecture detail and needs an explicit ADR/issue amendment.
- APSW and standard-library `sqlite3` may load two SQLite libraries in one process. APSW's documentation warns against opening the same database through both. DJ Support must make the chosen Operational Store engine exclusive.
- Native wheel availability remains a release concern; unsupported platform tags can trigger a source build unless install policy prevents or qualifies it.
- A third-party native dependency adds maintainer, release, provenance, and vulnerability-monitoring risk.

**Verdict:** Best current production route, provided the decision is explicit, the artifact is pinned/qualified, and all Operational Store opens go through one adapter.

### Option C: pysqlite3 or pysqlite3-binary

**Shape:** Use the separately packaged CPython `sqlite3` module, potentially as a closer DB-API replacement.

The official [pysqlite3 project page](https://pypi.org/project/pysqlite3/) describes a separately packaged standard-library module and a statically linked build option. However, the researched pysqlite3 0.6.0 release predates the March 2026 fix. The official [pysqlite3-binary project page](https://pypi.org/project/pysqlite3-binary/) currently shows an older release and a much narrower Linux wheel set.

**Benefits**

- API is closer to the accepted standard-library implementation.
- A correctly rebuilt release could bundle a qualified SQLite.

**Costs**

- Current release date and package label do not prove a fixed SQLite; the actual runtime and source ID still need inspection.
- The current binary distribution does not cover the required macOS/Linux/Windows matrix.
- Provenance and release freshness are weaker than the current APSW candidate.

**Verdict:** Not currently qualified. Re-evaluate only when a post-advisory release publishes complete wheels and concrete runtime/provenance evidence.

### Option D: DJ Support-owned native extension

**Shape:** Vendor an official SQLite amalgamation plus a Python binding or maintain a controlled pysqlite fork.

The PyPA [binary-extension packaging guide](https://packaging.python.org/en/latest/guides/packaging-binary-extensions/) explains that binary distributions multiply across Python versions, operating systems, and architectures; the stable ABI can reduce the Python dimension only when the extension can use it. PyPA's [packaging flow](https://packaging.python.org/en/latest/flow/) also explains that installers fall back to a source distribution when no compatible wheel exists. PyPA recommends tools such as `cibuildwheel` in its [tool recommendations](https://packaging.python.org/en/latest/guides/tool-recommendations/).

**Benefits**

- Maximum control over SQLite version, compile options, patch intake, and release timing.
- The outward adapter could preserve the standard-library-style subset.

**Costs**

- DJ Support becomes responsible for native build hardening, all wheel tags, repair/delocation, signing/provenance, source builds, crash debugging, and urgent SQLite rebuilds.
- The matrix is at least five CPython minors times three operating systems times each claimed architecture unless an ABI strategy genuinely reduces it.
- Missing wheels cause compiler/toolchain UX during installation.
- Vendoring CPython-derived binding code adds PSF license obligations in addition to the SQLite and binding notices.

**Verdict:** A fallback only if no maintained binding can meet the contract. It is disproportionate to the product at this stage.

## Why checkpoint scheduling is not a production workaround

The upstream race requires a second checkpoint to overlap the commit that resets the WAL. In a fully controlled closed system, disabling auto-checkpoint and allowing checkpoints only while an exclusive Runtime Assembly maintenance lease is held could theoretically remove that overlap **if every connection and every checkpoint obeyed the same lease**.

That is not a supportable guarantee here:

- SQLite's [automatic-checkpoint documentation](https://sqlite.org/wal.html#automatic_checkpoint) says a checkpoint occurs by default at the page threshold **or when the last connection closes**.
- The standard-library binding does not provide an application policy seam for every close-time checkpoint path.
- Independent CLI, web, and future agent processes can open or close connections outside one process-local coordinator; a stale or bypassed lease restores the overlap.
- SQLite warns that disabling automatic checkpoints can let the WAL grow excessively, consuming disk and degrading reads.
- Crash, forced termination, or another SQLite client can bypass the intended maintenance ceremony.
- The SQLite advisory recommends upgrading; it does not publish checkpoint scheduling as a supported remediation.

Therefore checkpoint serialization may narrow the timing window but does not qualify an affected runtime. The runtime gate must still reject it. An acceptance test should specifically prove that `wal_autocheckpoint=0` and a maintenance-lease flag cannot override a failed runtime qualification.

## Why rollback journal is not a silent fallback

The WAL-reset bug is WAL-specific, so rollback journal avoids this particular race. But issue #125 explicitly accepted WAL to support short concurrent reads and writes. SQLite's [WAL documentation](https://sqlite.org/wal.html) identifies the concurrency difference: in WAL, readers and a writer can proceed together, while rollback journaling follows the traditional lock/journal model.

Changing to `journal_mode=DELETE` would silently replace an accepted concurrency contract and produce different behavior under #139's multi-process workloads. It is an architectural alternative, not a runtime mitigation.

On an unqualified runtime DJ Support should:

- leave JSON as authority before cutover;
- refuse to open a concurrent WAL Operational Store;
- show an actionable, path-free upgrade message; and
- never silently return a usable store in rollback mode.

Issue #138's explicitly non-authoritative Preview can still exercise an in-memory implementation and pure schema/migration logic. A temporary, single-connection standard-library SQLite test adapter may be used only if it is unmistakably non-production and cannot be selected by Runtime Assembly. It must not be represented as qualification for #139.

## Installation and upgrade contract

### Installation

For the recommended APSW route:

1. Pin the audited binding release in package metadata for the release train.
2. Publish the exact supported Python/OS/architecture tags.
3. In CI and release qualification, install from the built DJ Support wheel into clean environments and require binary artifacts for the native binding.
4. Verify the downloaded artifact's index provenance and recorded digest.
5. Import the binding and compare version, source ID, compile options, binding version, and artifact identity with the reviewed manifest.
6. Fail before creating or migrating user state if no qualified artifact resolves.

Normal Python dependency metadata cannot force every installer never to build an sdist. A source installation is therefore an advanced, separately qualified route: it must produce the same approved source identity and pass the same tests. It is not silently covered by the wheel claim. PyPA's [secure installation guidance](https://pip.pypa.io/en/stable/topics/secure-installs/) describes hash-checking mode for repeatable artifact selection.

The user-facing failure should say which public runtime facts are unsupported and how to install a supported build. It must not expose application-data paths, database contents, or credentials.

### Upgrade

- Upgrading DJ Support alone must not be reported as repairing an interpreter-embedded SQLite.
- A binding update is a reviewed qualification change with a manifest diff, upstream release review, wheel/provenance review, and full matrix run.
- Perform the runtime check before schema migration, backup, or authority cutover.
- Preserve the last qualified binding until the replacement passes. Do not loosen the manifest just to admit a newer version.
- A cleanly closed synthetic WAL database created with the prior qualified release must reopen, pass integrity/foreign-key checks, and preserve its state digest after the upgrade.
- A database left with synthetic WAL state after process termination must recover correctly under the replacement before a release is admitted.

## Supply chain, security, and licensing

### Minimum controls

- Pin a specific binding release for each DJ Support release train.
- Record hashes and PyPI provenance for every admitted wheel; do not rely on a project name and version alone.
- Generate an SBOM or equivalent dependency inventory that names both the Python binding and embedded SQLite.
- Monitor the official [SQLite news](https://sqlite.org/news.html), release notes, and selected binding release feed.
- Treat a withdrawn upstream release as an immediate denylist/update event even when it fixes the target advisory.
- Exercise the runtime identity assertion in shipped code and in release CI.
- Keep the native dependency behind one deep adapter and forbid other modules from opening the Operational Store.
- Add the selected binding and its notices to open-source credits.

SQLite states that its source is in the [public domain](https://sqlite.org/copyright.html). APSW publishes its own [permissive copyright terms](https://rogerbinns.github.io/apsw/copyright.html), including notice and non-misrepresentation conditions. A DJ Support-owned fork of CPython binding code must also preserve the [PSF license](https://github.com/python/cpython/blob/main/LICENSE). Exact notice files should be taken from the actual selected artifacts at implementation time.

### Candidate-specific risk

APSW currently gives the best artifact coverage and freshness, but using it transfers trust to its build/release process. Its PyPI provenance is valuable evidence, not a substitute for DJ Support's runtime assertion or release tests. The binding update cadence, maintainer concentration, native compiler inputs, and wheel tags belong in the review checklist. DJ Support should never open the same Operational Store through both APSW and `sqlite3`.

## Recommended issue and implementation split

### R1 — Correct and adopt the qualification decision

**Can land now, before #138 and #139.**

- Correct the merged “3.51.3 or later” shorthand to deny withdrawn 3.52.0 and require a qualified build.
- Amend ADR/issue #125 and #138 if APSW is selected: “qualified SQLite Python binding, no ORM” replaces the literal standard-library requirement.
- Record the decision, fallback policy, open-source notices, and one-binding-only rule.
- Keep JSON authoritative.

### R2 — Runtime identity and fail-closed qualifier

**Can land before #138; blocks any Runtime Assembly selection of SQLite.**

- Add the reviewed qualification-manifest format.
- Implement a pure classifier over binding identity, SQLite version, source ID, artifact/vendor provenance, platform, architecture, and withdrawn denylist.
- Add path-free diagnostics and the negative rules for checkpoint scheduling and rollback fallback.
- Make unknown builds unavailable rather than “warn and continue.”

This issue can be developed test-first without opening a real user database.

### R3 — Select and deliver the native runtime

**Should land before the SQLite adapter portion of #138 to avoid churn; must land before #139.**

- Select APSW 3.53.4.0 or reject it through the explicit ADR gate.
- Add the dependency, adapter boundary, credits/notices, release qualification manifest, and clean-wheel matrix.
- Prove binary installation and runtime identity on Python 3.10-3.14, macOS/Linux/Windows, for every architecture DJ Support claims.
- Keep DJ Support's own domain and Transfer modules independent of the binding API.

### #138 — Non-authoritative Preview

The in-memory port, schema model, migration registry, serialization, privacy boundaries, and deterministic tests can proceed before R3. Runtime Assembly must remain on JSON. If the SQLite adapter proceeds before binding selection, constrain it to the shared Operational Store port and do not let standard-library-specific transaction behavior become the interface.

### #139 — Concurrent authority

#139 remains blocked until R1-R3 are merged and the selected release artifacts pass the full matrix. Its concurrency, stale-revision, WAL, process-crash, recovery, and cutover tests are the proof that the installed runtime meets the accepted contract.

## Exact acceptance tests

### Qualification classifier

1. Reject an upstream 3.44.5 fixture.
2. Accept only the manifest fixture for official backport 3.44.6 with its reviewed source lineage and artifact identity.
3. Reject representative 3.45.1 and 3.49.1 fixtures.
4. Reject an upstream 3.50.6 fixture.
5. Accept only the manifest fixture for official backport 3.50.7 with its reviewed source lineage and artifact identity.
6. Reject official 3.51.2.
7. Accept official 3.51.3 only with source ID `2026-03-13 10:38:09 737ae4a34738ffa0c3ff7f9bb18df914dd1cad163f28fd6b6e114a344fe6d618`.
8. Reject 3.52.0 unconditionally as withdrawn, even though its numeric version is greater than 3.51.3.
9. Accept the selected 3.53.4 artifact only with source ID `2026-07-24 19:02:57 bf7c7f30031888f4e796e429ab3978879485813aaca6f641c7b33e4e09459bcc`, selected binding version, artifact digest/provenance, platform, and architecture.
10. Reject the same approved version paired with an unknown source ID.
11. Reject the same source ID paired with an unapproved binding artifact or vendor package revision.
12. Reject a synthetic old-version “vendor backport” until its manifest entry includes an official vendor source/advisory and exact patch lineage; accept only the exact approved tuple.
13. Reject any unlisted newer release until a reviewed manifest update admits it.
14. Confirm `wal_autocheckpoint=0`, a maintenance-lease flag, or any checkpoint policy cannot change a rejected result.
15. Confirm an unqualified runtime cannot be converted silently to rollback journal and returned as an Operational Store.

### Runtime probe and privacy

16. Probe the imported binding, not the system CLI, for SQLite version, source ID, compile options, wrapper, and distribution identity.
17. Emit only public runtime facts and a stable reason code; assert diagnostics contain no home directory, database path, playlist name, credentials, or row values.
18. Run the probe before file creation, schema migration, backup, or cutover.
19. Confirm every production Operational Store open passes through the gate; direct binding imports outside the adapter fail the architecture check.
20. Confirm the same database cannot be opened through both APSW and standard-library `sqlite3` in DJ Support.

### Packaging and installation

21. Build the DJ Support wheel, install it in a clean environment, and resolve the selected native binding as a binary wheel for each CPython 3.10, 3.11, 3.12, 3.13, and 3.14 job on Linux, macOS, and Windows.
22. Cover each architecture publicly claimed by DJ Support; do not infer an architecture from another wheel tag.
23. Fail a binary-only installation on an intentionally unsupported tag before first run, with an actionable message and no state mutation.
24. Verify the installed wheel digest and published provenance against the qualification manifest.
25. Import the installed binding and assert its runtime source ID and compile options, rather than trusting wheel filenames or dependency metadata.
26. Inspect the built DJ Support wheel and source archive for credentials, user-derived data, absolute local paths, and unexpected native binaries.
27. Assert package metadata names the selected dependency and that distributed credits/notices cover the binding and SQLite.

### Upgrade and recovery

28. Create a synthetic WAL store with the previous qualified release, close cleanly, upgrade in place, reopen, and assert `integrity_check`, `foreign_key_check`, schema version, and a canonical state digest.
29. Terminate a writer after a committed synthetic transaction leaves WAL state, upgrade the binding, recover, and assert the committed state and integrity checks.
30. Attempt an upgrade under an unqualified runtime and prove it stops before migration or authority changes.
31. Upgrade from a qualified build to a numerically newer but unlisted/withdrawn fixture and prove the gate rejects it.
32. Prove backup/restore and rollback preserve the qualified-runtime requirement and never reopen through a different binding implicitly.

### #139 release matrix

33. Run independent-process readers and writers against WAL on the installed release artifact, not just a source checkout.
34. Exercise bounded busy waits, optimistic revision conflicts, checkpoint pressure, last-connection close, process termination, restart, and recovery.
35. Assert committed-state digests, `integrity_check`, and `foreign_key_check` after every stress/crash scenario.
36. Run those tests for every Python/OS combination claimed by the installer; a skipped native-runtime test fails release qualification.
37. Keep JSON authoritative until the same artifact matrix passes cutover, rollback, and post-cutover restart tests.

## What can land before #138/#139

The safe pre-runtime slice is substantial:

- this research and the 3.52.0 correction;
- the ADR/issue wording decision;
- the qualification manifest schema and pure classifier;
- the public, path-free runtime probe;
- unit fixtures for safe, affected, withdrawn, unknown, and vendor-backport identities;
- CI inventory that reports the imported runtime on every matrix job;
- binding selection and artifact/provenance evaluation;
- in-memory Operational Store models, migration planning, serialization, and privacy tests; and
- packaging/credits scaffolding that does not yet select SQLite in Runtime Assembly.

What must **not** land as a production claim before R1-R3:

- SQLite as Runtime Assembly authority;
- #139's concurrent WAL authority;
- a version-floor-only capability gate;
- a checkpoint-lease “mitigation” on an affected runtime;
- a silent rollback-journal fallback; or
- documentation promising all Python 3.10-3.14/macOS/Linux/Windows installs work without a qualified native artifact.

The dependency order is therefore:

`R1 decision/correction -> R2 qualifier -> R3 delivered runtime -> #138 adapter/preview completion -> #139 concurrent authority and cutover`.

## Sources

### SQLite

- [Write-Ahead Logging, including the 2026 WAL-reset advisory](https://sqlite.org/wal.html)
- [SQLite 3.51.3 release](https://sqlite.org/releaselog/3_51_3.html)
- [SQLite 3.52.0 withdrawn release](https://sqlite.org/releaselog/3_52_0.html)
- [SQLite 3.53.4 release](https://sqlite.org/releaselog/3_53_4.html)
- [SQLite news](https://sqlite.org/news.html)
- [Compile-time source identity](https://sqlite.org/c3ref/c_source_id.html)
- [Runtime library identity APIs](https://sqlite.org/c3ref/libversion.html)
- [SQLite copyright](https://sqlite.org/copyright.html)

### Python and CI

- [Python sqlite3 runtime version documentation](https://docs.python.org/3/library/sqlite3.html#sqlite3.sqlite_version)
- [CPython Unix build requirements](https://docs.python.org/3/using/configure.html#build-requirements)
- [CPython tagged Windows and macOS build recipes](https://github.com/python/cpython)
- [Python 3.10.11](https://www.python.org/downloads/release/python-31011/), [3.11.9](https://www.python.org/downloads/release/python-3119/), [3.12.10](https://www.python.org/downloads/release/python-31210/), [3.13.15](https://www.python.org/downloads/release/python-31315/), and [3.14.7](https://www.python.org/downloads/release/python-3147/) releases
- [actions/setup-python advanced usage](https://github.com/actions/setup-python/blob/main/docs/advanced-usage.md)
- [actions/python-versions Ubuntu builder](https://github.com/actions/python-versions/blob/main/builders/ubuntu-python-builder.psm1)
- [CPython license](https://github.com/python/cpython/blob/main/LICENSE)

### Packaging and candidate bindings

- [PyPA binary-extension packaging guide](https://packaging.python.org/en/latest/guides/packaging-binary-extensions/)
- [PyPA packaging flow](https://packaging.python.org/en/latest/flow/)
- [PyPA tool recommendations](https://packaging.python.org/en/latest/guides/tool-recommendations/)
- [pip secure installs](https://pip.pypa.io/en/stable/topics/secure-installs/)
- [APSW versus pysqlite](https://rogerbinns.github.io/apsw/pysqlite.html)
- [APSW 3.53.4.0 artifacts and provenance](https://pypi.org/project/apsw/3.53.4.0/)
- [APSW copyright](https://rogerbinns.github.io/apsw/copyright.html)
- [pysqlite3](https://pypi.org/project/pysqlite3/)
- [pysqlite3-binary](https://pypi.org/project/pysqlite3-binary/)

### Operating-system vendors

- [Ubuntu USN-8480-1](https://ubuntu.com/security/notices/USN-8480-1)
- [Ubuntu sqlite3 source-package changelog](https://launchpad.net/ubuntu/+source/sqlite3/+changelog)
- [Debian SQLite security tracker](https://security-tracker.debian.org/tracker/source-package/sqlite3)
