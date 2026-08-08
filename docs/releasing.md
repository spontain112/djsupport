# Releasing DJ Support

This is the canonical maintainer checklist for moving DJ Support from
development through a release candidate to a final release. Replace every
`X.Y.Z` placeholder deliberately and record the exact commit used at each gate.

A release-preparation PR, passing CI, a tag, a GitHub Release, and
package-index publication are separate gated operations. None implies or
authorizes another. Preparing this checklist or completing issue #107 does not
authorize any tag, GitHub Release, or package publication.

## 1. Choose the version and exact commit

- [ ] Choose the intended candidate `X.Y.ZrcN` or final `X.Y.Z` version.
- [ ] Record the full commit SHA proposed for release; do not release an
      unrecorded moving branch head.
- [ ] Confirm the version follows PEP 440 and that its Git tag will be the same
      version prefixed with `v`.

## 2. Confirm `main` is ready

- [ ] Ensure every issue and PR required for the release is merged.
- [ ] Fetch `main`, confirm the recorded commit is reachable from it, and
      confirm the checkout has no uncommitted or untracked release content.
- [ ] Keep unrelated work out of the release scope. Create a stable maintenance
      branch only when an actual patch release needs one.

## 3. Prepare the release through a PR

- [ ] Open a dedicated release-preparation PR that changes the version in
      `pyproject.toml`, the single source of version truth.
- [ ] Move the relevant `[Unreleased]` changelog entries under the exact
      candidate or final version and date; do not rewrite earlier releases.
- [ ] Review and merge that PR normally. Merging it does not authorize tagging
      or publication.

## 4. Run the complete release validation

- [ ] From the exact proposed commit, install development and web extras and run
      the complete offline suite plus compilation:

  ```bash
  python3 -m pip install ".[dev,web]"
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
    "$artifact_dir/djsupport-X.Y.Z-py3-none-any.whl"
  "$install_dir/venv/bin/python" -c \
    'from importlib.metadata import version; assert version("djsupport") == "X.Y.Z"; import djsupport'
  "$install_dir/venv/bin/djsupport" --help
  ```

- [ ] Resolve every validation failure. A skipped or partially run command is not
      a passing release gate.

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
- [ ] With separate explicit authorization, create and push the annotated final
      tag, then publish the final GitHub Release as Latest.
- [ ] Verify the release page and every downloadable artifact resolve to the
      intended final version. Package-index publication, if any, remains a
      separate explicitly authorized operation and requires its own verification.

## 10. Return `main` to development

- [ ] Immediately open a follow-up PR moving `pyproject.toml` to the next
      `.dev0` version while keeping new work under `[Unreleased]`.
- [ ] Confirm stable users still resolve to the final Latest release and that
      `main` is again clearly identified as development software.
