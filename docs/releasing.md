# Releasing DJ Support

This is the canonical maintainer checklist for moving DJ Support from
development through a release candidate to a final release. Ordinary changes
record release intent beside the change; automation maintains the
release-preparation PR. Replace every `X.Y.Z` placeholder deliberately and
record the exact commit used at each publication gate.

A release-preparation PR, passing CI, a tag, a GitHub Release, and
package-index publication are separate gated operations. None implies or
authorizes another. Preparing this checklist or completing issue #107 does not
authorize any tag, GitHub Release, or package publication.

## 1. Record distributable changes

- [ ] Every PR that changes `djsupport/`, package metadata, or user-facing
      documentation adds one `.release-notes/*.md` file.
- [ ] Set `bump` to `patch`, `minor`, or `major`; set `section` to a Keep a
      Changelog heading; describe the consumer-visible effect.
- [ ] Internal-only changes to tests, release machinery, research notes under
      `docs/research/`, or this checklist do not require a release record. If
      the same pull request changes distributable behavior or user guidance,
      that change still requires a release record.

## 2. Review the automated version PR

- [ ] After release records reach `main`, confirm the `release/version` PR
      contains the intended version, consumes the pending records, and moves
      their summaries into `CHANGELOG.md`.
- [ ] Confirm the version follows PEP 440. A `.dev0` development version is
      finalized at its base version; later stable versions follow the highest
      pending bump.
- [ ] For a candidate or final promotion, add the exact intended version to the
      one-use `.release-notes/next-version` override before the version PR is
      prepared (for example `0.6.0rc1` or `0.6.0`).
- [ ] Ensure every issue and PR required for the release is merged before
      merging the version PR.

## 3. Merge version metadata through the PR

- [ ] Require green CI on the version PR, including release-record validation.
- [ ] Review and merge the PR normally. The PR changes `pyproject.toml`, the
      single source of version truth, and the changelog together.
- [ ] Merging the version PR does not authorize tagging or publication.

## 4. Run the complete release validation

- [ ] From the exact proposed commit, install development and web extras and run
      the complete offline suite plus compilation:

  ```bash
  python3 -m pip install --only-binary=apsw ".[dev,web]"
  python3 -m pytest
  python3 -m compileall -q djsupport tests
  ```

- [ ] Run the repository privacy checks and the synthetic migration and backup
      validation. Never point these commands at real application data:

  ```bash
  python3 -m pytest tests/test_repository_privacy.py
  python3 -m pytest tests/test_migration.py tests/test_backup.py
  ```

- [ ] Build both distributions once in a fresh temporary artifact directory:

  ```bash
  artifact_dir="$(mktemp -d)"
  python3 -m build --outdir "$artifact_dir"
  ```

- [ ] Inspect every source and wheel archive member. Confirm the archives contain
      only intended package and repository content—never credentials, local
      paths, owner data, reports, XML, audio, identifiers, or regression
      evidence:

  ```bash
  python3 -m tarfile -l "$artifact_dir/djsupport-X.Y.Z.tar.gz"
  python3 -m zipfile -l "$artifact_dir/djsupport-X.Y.Z-py3-none-any.whl"
  ```

- [ ] Create a separate disposable environment, install the built wheel, verify
      its metadata reports exactly `X.Y.Z`, import the public package, and invoke
      the installed CLI:

  ```bash
  install_dir="$(mktemp -d)"
  python3 -m venv "$install_dir/venv"
  "$install_dir/venv/bin/python" -m pip install \
    --only-binary=apsw \
    "$artifact_dir/djsupport-X.Y.Z-py3-none-any.whl"
  "$install_dir/venv/bin/python" -c \
    'from importlib.metadata import version; assert version("djsupport") == "X.Y.Z"; import djsupport'
  "$install_dir/venv/bin/djsupport" --help
  ```

- [ ] Resolve every validation failure. A skipped or partially run command is not
      a passing release gate.

### Publication-free candidate qualification

Candidate qualification is validation-only. The read-only
`candidate-qualification.yml` workflow binds an exact product commit, exact
`djsupport-docs` commit, expected package version, changelog heading, pinned
build tools, all 25 qualified APSW native cells, reproducible DJ Support wheel
identity, installed synthetic checks, and documentation validation into one
path-free evidence document. Finalization consumes the completed public
workflow job and step observations; missing, failed, or duplicate observations
fail closed instead of being inferred as passing.

The harness does not add `.release-notes/next-version`, does not consume release
records, does not change `pyproject.toml`, and does not upload its source archive
or wheel. A green evidence document is not authority to create a tag, GitHub
Release, release asset, package upload, advisory publication, live-provider
call, or owner-data test. The exact final Operational Store scenarios are added
only after their owning behavior is merged; the checked-in harness proves the
same versioned interface now with invented, synthetic facts. Synthetic evidence
is always labelled non-release and cannot qualify a release candidate.

## 5. Require green CI on the release commit

- [ ] Confirm the exact release commit has green CI for Python 3.10 and 3.14,
      compilation, packaging, archive inspection, and clean installation.
- [ ] Confirm no later commit has replaced the reviewed release commit. Passing
      CI on another SHA does not satisfy this gate.

## 6. Publish an exact release candidate

- [ ] Obtain explicit authorization to create and push an annotated
      `vX.Y.ZrcN` tag pointing at the validated commit.
- [ ] Separately obtain authorization to create the GitHub Release for that tag.
- [ ] Mark the candidate as a GitHub pre-release, never Latest, and attach or
      link only the exact validated artifacts.
- [ ] If package-index publication is intended, treat it as another separately
      authorized operation; neither the tag nor GitHub pre-release authorizes it.

## 7. Test the exact candidate artifact

- [ ] Install the exact tagged artifact in a disposable environment rather than
      rebuilding from a later checkout.
- [ ] Back up local application data before any owner testing. Never test with
      the only copy of a Rekordbox library or audio collection.
- [ ] Treat any live Spotify or Beatport call and any owner-data access as a
      separately authorized, bounded validation—not as part of offline CI.

## 8. Fix defects through normal development

- [ ] Record candidate defects in issues and fix them through named branches,
      reviewed PRs, and `main`.
- [ ] Repeat the complete validation and issue a new candidate number. Never
      move or replace an existing candidate tag or artifact.

## 9. Promote a final release deliberately

- [ ] Prepare the final `X.Y.Z` version and changelog in another dedicated PR,
      then rerun the complete validation on its exact commit.
- [ ] Require green CI on the exact final commit. Candidate CI or CI on another
      SHA does not satisfy the final-release gate.
- [ ] Obtain explicit authorization to create and push the annotated final tag
      pointing at the validated final commit.
- [ ] Separately obtain authorization to publish the final GitHub Release as
      Latest.
- [ ] Verify the release page and every downloadable artifact resolve to the
      intended final version. Package-index publication, if any, remains a
      separate explicitly authorized operation and requires its own verification.

## 10. Continue development

- [ ] New distributable work starts with new release records under
      `.release-notes/`; automation opens or updates the next version PR.
- [ ] Confirm stable users still resolve to the final Latest release. The
      mutable `main` branch is not itself a publication channel.
