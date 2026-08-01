# DJ Support 0.4.0 release notes

DJ Support 0.4.0 makes Transfers durable and reviewable. Rekordbox selections
publish as Mirrors, Beatport charts and labels publish as Snapshots by default,
and retained proposals become authoritative matching knowledge only after
playlist-scoped Approval.

## Highlights

- Explicit Rekordbox Batches with lookup-cost preflight and independent playlist
  outcomes.
- Resumable Beatport Transfers, optional recurring Mirrors, and retained
  Abandonment history.
- Provisional Playlist review with editable Correction CSVs, Approved and
  Rejected Matches, and collision-safe Approval.
- Versioned local-data backup, validation, conflict preview, and atomic restore.
- Beatport label discovery plus an optional local web UI installed with
  `djsupport[web]`.
- Private, shared matching knowledge across source types; repository tests and
  fixtures remain synthetic.

## Upgrade from 0.3.0

Install 0.4.0, keep the old 0.3.0 working directory intact, and preview its four
known local-data files explicitly:

```bash
djsupport migrate-0-3 /path/to/old-working-directory
djsupport migrate-0-3 /path/to/old-working-directory --apply
```

Apply creates and verifies a current-format backup before writing atomically.
Current application-data truth wins collisions. Legacy cache entries remain
non-authoritative proposals; Rekordbox relationships require a future explicit
relink, while Beatport relationships are retained only as unmanaged historical
Snapshots. Migration is idempotent, makes no Spotify calls, and never changes
or deletes the legacy directory.

Publication manifests from schema versions 1–3 are accepted by the current
reader; schema v4 is the current format. Backup/restore accepts every supported
version and refuses unknown schemas, damaged archives, unexpected files, and
unresolved conflicts.

No migration reads a Rekordbox library, contacts Spotify or Beatport, or moves
data into the repository. Validation for this release used synthetic temporary
application data only.

## Privacy and recovery

OAuth credentials and tokens are not part of local-data backups. Recognized
versioned state and local Markdown/CSV reports are included only when they pass
the backup filters; unrelated files and report symlinks are excluded.

Provisional Playlist descriptions currently contain an opaque Transfer marker
and machine timestamp. They contain no OAuth credential or source-library path,
but they are internal recovery metadata shown in Spotify. Removing them safely
requires a replacement for crash recovery and duplicate-publication prevention,
so issue #61 remains a documented, non-blocking recovery/UX limitation.

## Known limitations

- Beatport may change its undocumented page-data shapes. Supported shapes retain
  the curator and use `Curator - Chart Name`; an unhandled shape can fall back
  to the chart name (#60).
- A materially shorter Spotify substitute may still be labelled exact even
  though its confidence receives a duration penalty (#56).
- A duplicated parenthetical subtitle can depress the correct candidate below
  the default threshold (#57).
- Spotify candidate breadth/fallback behavior, noisy source cleanup, and
  ISRC-first matching remain research items (#31, #32, #39, #42).

These matcher limitations do not bypass the threshold or Approval workflow.
Preview the Transfer, review Provisional Playlists, and use an explicit
Correction for a missing or wrong proposal.

## Compatibility note

The command names `sync` and flag `--dry-run` remain supported. Likewise,
`--no-cache` and `--retry-days` remain accepted for compatibility even though
the product language is matching knowledge and failed matches are retried only
when `--retry` is explicit.
