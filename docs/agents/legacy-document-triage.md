# Legacy Document Triage

Audit performed on 2026-07-31 after GitHub Issues became the configured work tracker.

## Converted work

| Source | Disposition |
| --- | --- |
| Pending remixer co-credit plan | [Issue #30](https://github.com/spontain112/djsupport/issues/30), `ready-for-agent` |
| ISRC via Mutagen test plan | [Issue #31](https://github.com/spontain112/djsupport/issues/31), `needs-triage` |
| Generalized unmatched-track metadata patterns | [Issue #32](https://github.com/spontain112/djsupport/issues/32), `needs-triage` |
| Tracked user-derived report and matching evidence | [Issue #33](https://github.com/spontain112/djsupport/issues/33), `ready-for-agent`; blocked by #19 and blocks final cleanup #29 |

## Retained as history

- Completed feature plans remain implementation history and do not receive retroactive issues.
- Solution documents remain resolved incident knowledge.
- Completed `todos/` remain historical review records; they do not re-enter triage.
- Tests remain executable verification rather than tracker items. The default suite contains no skipped or expected-failure tests.

## Removed from the current tree

- The old repository-hygiene plan was superseded by ADR-0001 and removed; Git
  history remains the recovery source.
- The Chrome-extension plan was removed because extension work is outside this
  repository's scope. It was not relocated into another unit.
- The unreferenced data-model and matcher-playground HTML visualizers were
  removed. The shipped web UI remains `djsupport/static/index.html` with its
  runtime image assets. Its deliberately authored `NewUI.pen` design source was
  retained under `docs/design/` rather than mixed into the runtime package.

The evidence and complete classification are recorded in
[repository-artifact-audit.md](repository-artifact-audit.md).

## Data ownership

Issue #33 removed the personal unmatched-track listing after its generalized
metadata findings were retained in issue #32. Corrections, Approved Matches,
playlist state, reports, and user-derived regression knowledge remain in local
application storage; repository tests use synthetic or explicitly exported,
consented, and privacy-reviewed contributions only.
