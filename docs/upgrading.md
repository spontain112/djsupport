# Upgrading DJ Support

## From 0.3.0

DJ Support does not migrate working-directory data automatically. Keep the old
directory intact and explicitly preview its four known 0.3.0 files:

```bash
djsupport migrate-0-3 /path/to/old-working-directory
```

The report contains counts only. It does not print track metadata, Spotify
identifiers, or absolute paths. Unknown files—including credentials and
reports—are ignored. Malformed or unsupported known files stop migration
without changing either location.

After reviewing the report, apply it explicitly:

```bash
djsupport migrate-0-3 /path/to/old-working-directory --apply
```

Apply creates and verifies a current-format backup before an atomic write.
Current application-data truth wins every collision. Old cache results remain
non-authoritative and never become Approved Matches. Old Rekordbox playlist
state is retained as relink-required because 0.3.0 did not safely retain account
ownership; no relationship is inferred from a name, path, or playlist content.
Old Beatport state becomes unmanaged historical Snapshot information. Migration
makes no Spotify calls and never changes or deletes the old files. Re-running
apply does not duplicate records.

If apply fails, correct the reported file or storage problem and run preview
again. A failed validation, backup, conversion, or commit leaves current data
unchanged.
