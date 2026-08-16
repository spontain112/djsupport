# Release-record classifier contract for public root artifacts

**Date:** 2026-08-16

**Research baseline:** `origin/main` at
`87a546ff45ef87047aac036b95d4e42ff607ebeb`

**Issue:** [#174 — Make the release-record classifier cover public root
artifacts](https://github.com/spontain112/djsupport/issues/174)

**Status:** implementation-ready repository-policy research. This note changes
no release tooling, tests, package contents, version, workflow, tag, release, or
publication state.

## Outcome

The release-record gate must use one explicit allowlist containing exactly these
ten public root artifacts:

```text
.env.example
CHANGELOG.md
CONTEXT.md
CONTRIBUTING.md
LICENSE
MANIFEST.in
README.md
SECURITY.md
THIRD_PARTY.md
pyproject.toml
```

That set is the exact contract in issue #174. It also follows the repository's
own ownership map: `CONTEXT.md` is canonical domain language,
`CONTRIBUTING.md` is the public engineering guide, and `pyproject.toml` owns
package metadata, dependencies, version, and package data
([repository card](../../AGENTS.md), [package metadata](../../pyproject.toml)).

The classifier is a **public-release policy**, not an sdist-membership detector.
A clean isolated `python3 -m build` at the research baseline proved both sides
of that distinction:

- `.env.example` and `CONTEXT.md` are not in the current sdist, but they are
  public configuration and domain contracts and therefore need release records;
- `tests/test_*.py` and `docs/releasing.md` are in the current sdist, but they are
  internal verification and maintainer-operation material and therefore remain
  exempt.

Setuptools confirms that an sdist includes configured package files, common
tests, `pyproject.toml`, README and license files, and `MANIFEST.in` by default,
while `MANIFEST.in` adds or removes files from the sdist. It also explains that
only data inside package directories reaches a wheel by default
([setuptools file-selection documentation](https://setuptools.pypa.io/en/latest/userguide/miscellaneous.html#controlling-files-in-the-distribution)).
PyPA likewise distinguishes a source distribution, which may contain tests and
documentation, from a wheel containing installed-runtime material
([PyPA packaging flow](https://packaging.python.org/en/latest/flow/#build-artifacts)).
Archive membership is consequently neither necessary nor sufficient for this
repository policy.

## Exact public-root policy

| Root artifact | Current artifact evidence | Why a change is distributable |
| --- | --- | --- |
| `.env.example` | Repository-only at this baseline | Names the supported public environment configuration contract ([template](../../.env.example)). |
| `CHANGELOG.md` | Included in the sdist by [`MANIFEST.in`](../../MANIFEST.in) | Is the generated public release history consumed by users and maintainers ([changelog](../../CHANGELOG.md)). |
| `CONTEXT.md` | Repository-only at this baseline | Owns canonical public domain language used by code and documentation ([context](../../CONTEXT.md), [repository card](../../AGENTS.md)). |
| `CONTRIBUTING.md` | Included in the sdist by [`MANIFEST.in`](../../MANIFEST.in) | Defines public setup, engineering, privacy, dependency-credit, and release guidance ([contribution guide](../../CONTRIBUTING.md)). |
| `LICENSE` | Included in the sdist and under the wheel's `.dist-info/licenses/` directory | Changes the legal terms distributed with the project. PyPA requires declared license files in distribution archives ([license](../../LICENSE), [PyPA project-metadata specification](https://packaging.python.org/en/latest/specifications/pyproject-toml/#license-files)). |
| `MANIFEST.in` | Included in the sdist by setuptools | Directly changes which additional source-tree files enter the sdist ([manifest](../../MANIFEST.in), [setuptools file-selection documentation](https://setuptools.pypa.io/en/latest/userguide/miscellaneous.html#controlling-files-in-the-distribution)). |
| `README.md` | Included in the sdist and embedded as wheel/sdist Description metadata | Is the public workflow entry point and the configured project description ([README](../../README.md), [PyPA `readme` metadata](https://packaging.python.org/en/latest/specifications/pyproject-toml/#readme)). |
| `SECURITY.md` | Included in the sdist by [`MANIFEST.in`](../../MANIFEST.in) | Defines supported versions, private reporting, scope, and coordinated disclosure ([security policy](../../SECURITY.md)). |
| `THIRD_PARTY.md` | Included in the sdist by [`MANIFEST.in`](../../MANIFEST.in) | Defines public attribution, dependency provenance, and the repository's notice-maintenance rule ([acknowledgements](../../THIRD_PARTY.md)). |
| `pyproject.toml` | Required in the sdist; controls generated metadata and wheel/package contents | Owns build backend, version, dependencies, entry point, and package data ([package metadata](../../pyproject.toml), [PyPA sdist specification](https://packaging.python.org/en/latest/specifications/source-distribution-format/)). |

The clean baseline sdist contained these root files: `CHANGELOG.md`,
`CONTRIBUTING.md`, `LICENSE`, `MANIFEST.in`, `README.md`, `SECURITY.md`,
`THIRD_PARTY.md`, and `pyproject.toml`, plus generated `PKG-INFO` and
`setup.cfg`. The wheel contained the `djsupport/` runtime tree, generated
metadata, and `LICENSE` under `.dist-info/licenses/`; the README text was present
in `METADATA` because `[project].readme` points to `README.md`. These observations
match the current manifest and package configuration and do not imply that
future backend behavior should define release policy
([manifest](../../MANIFEST.in), [package metadata](../../pyproject.toml)).

## Existing non-root rules remain unchanged

The public-root allowlist deepens rather than replaces the current classifier:

- every path under `djsupport/` remains distributable;
- public `docs/**` paths remain distributable;
- `docs/research/**` and the exact maintainer checklist
  `docs/releasing.md` remain exempt.

That preserves the current executable and public-documentation contract while
keeping dated evidence and release machinery from recursively requiring their
own release records
([current classifier](../../scripts/release_records.py),
[release policy](../releasing.md#1-record-distributable-changes)).

## Explicit internal exclusions

The implementation must not generalize the allowlist to “all tracked root
files,” “all Markdown,” or “all sdist members.” Those rules would incorrectly
classify internal material. These paths remain non-distributable unless a future
issue deliberately changes their role:

| Internal surface | Required classification | Reason |
| --- | --- | --- |
| `docs/research/**` | false | Dated evidence and decision support; already explicitly exempt. |
| `docs/releasing.md` | false | Maintainer operations; explicitly exempt even though currently in the sdist. |
| `tests/**` | false | Offline verification, not consumer behavior; setuptools currently includes common tests in the sdist by default. |
| `.github/workflows/**` | false | Repository automation, including CI and version-PR preparation. |
| `AGENTS.md`, `CLAUDE.md`, `.claude/**` | false | Agent-only repository instructions. This does not exclude public documentation merely because it lives under `docs/agents/`. |
| `scripts/**` | false | Internal release tooling. The #174 implementation itself must therefore need no release record. |
| `.release-notes/**` | false | Inputs consumed into the changelog; classifying the inputs would make the gate recursive. |
| `.gitignore` | false | Repository privacy/build guardrail rather than a consumer release surface. |

The explicit allowlist makes additions intentional: a new public root contract
does not silently become distributable by filename pattern; its introducing
change must update the allowlist and its named contract test.

## Generated changelog and version automation

Classifying `CHANGELOG.md` does not create a loop in the automated version PR.
The repository's preparation function:

1. loads pending `.release-notes/*.md` records;
2. selects the next version or one-use override;
3. writes that version to `pyproject.toml`;
4. consumes record summaries into `CHANGELOG.md`; and
5. removes the consumed records
   ([preparation code](../../scripts/release_records.py),
   [release-record format](../../.release-notes/README.md)).

The version workflow stages `pyproject.toml`, `CHANGELOG.md`, and
`.release-notes` together
([version workflow](../../.github/workflows/version-pr.yml)). During range
checking, a version-preparation PR has distributable changes but no newly added
record because the records were removed; the checker then compares the base and
head versions and accepts the range as “included in a version update.” That
existing version-change branch remains the correct escape hatch
([range checker](../../scripts/release_records.py)).

The resulting behavior is deliberate:

- a generated changelog change paired with the prepared version passes without
  another release record;
- a manual changelog-only change requires a release record;
- adding or editing an unconsumed release record alone does not recursively
  trigger the classifier; and
- changing the release script or its tests alone reports `No distributable
  changes.`

No change to version selection, preparation order, workflow permissions,
package contents, or release publication follows from #174.

## Implementation and test contract

The smallest stable implementation is a named immutable set such as
`PUBLIC_ROOT_ARTIFACTS`, used as an exact-membership branch inside
`_is_distributable()`. Preserve the existing `djsupport/` and public-`docs/`
branches unchanged. Do not derive the set dynamically from `MANIFEST.in`, an
sdist, the filesystem, or Git, because each would conflate packaging state with
the policy established above.

The focused test must name the policy (for example,
`test_public_root_artifacts_are_distributable`) and enumerate all ten paths. A
separate exclusion test should retain representative cases for
`docs/research/**`, `docs/releasing.md`, tests, workflows, and agent-only
instructions. The issue's required red-green evidence is:

1. the new public-root test fails against the baseline because only `README.md`
   and `pyproject.toml` currently return true;
2. the exact allowlist makes it pass without changing any unrelated rule;
3. `python3 -m pytest -q tests/test_release_records.py`, the full offline suite,
   and compilation pass; and
4. `python3 scripts/release_records.py check origin/main HEAD` reports
   `No distributable changes.` for the tooling-and-test-only implementation.

Because this research file is under `docs/research/`, it is itself covered by the
existing research exclusion and does not require a release record.

## Conformance of local implementation `00ae775`

The inspected local implementation commit
`00ae775a2ab836b23bcaa994550ef05647c584e6` conforms exactly to this contract:

- its `PUBLIC_ROOT_ARTIFACTS` set contains all and only the ten paths named by
  issue #174;
- it preserves `djsupport/**` and the existing public-`docs/**` rule with the
  two exact documentation exclusions;
- its focused test names and enumerates the public-root contract; and
- its agent-only exclusion test confirms root instruction files remain false.

**No contradiction was found** between issue #174, the primary packaging and
repository evidence, and the implemented public-root set. Test execution,
range-check output, publication boundaries, and other activity gates remain
runtime evidence; this source-level conformance statement does not substitute
for those checks.
