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

## Superseded or out of scope

- The old repository-hygiene plan is superseded by ADR-0001, which permits project documentation while keeping user-specific data local.
- The Chrome-extension plan is outside this repository's scope and should move to the dedicated extensions workspace if pursued.

## Data ownership

The unmatched-track report remains tracked temporarily so its generalized findings are not lost before issue #33 provides a safe local destination. Do not add new personal reports, Corrections, Approved Matches, playlist state, or user-derived regression data to Git.
