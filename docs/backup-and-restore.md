# Backup and restore

`djsupport backup` creates a versioned archive in private application storage.
It includes matching knowledge, Transfer and publication state, migration
records, and privacy-screened reports. Credentials and unrelated files are not
included.

Matching-knowledge schema 3 includes private local-audio observations,
account-scoped Approved Match associations, and retained Spotify review facts.
Publication schema 6 retains the corresponding review and availability facts.
Transfer-state schema 4 includes the opt-in, completed evidence checkpoints,
and private Qualification Drafts.
Both are backed up and restored as private application data. Audition handles,
audio, paths, filenames, and fingerprints are never part of a Qualification
Draft. A differing copy of the same draft requires an explicit restore choice;
neither draft silently wins. Conflicting local-audio authority requires
an explicit restore choice identified by a privacy-safe hashed label; reports
and archive manifests do not print fingerprints or source paths.

Restore is preview-first:

```bash
djsupport restore /path/to/archive.zip
djsupport restore /path/to/archive.zip --apply
```

Archives are checked against their manifest, hashes, known filenames, and
supported schema versions before use. Restore merges compatible records,
requires an explicit choice for conflicting truth, stages all writes, and rolls
back if a commit fails.

The 0.3.0 migration command creates and verifies one of these archives before
writing. Backups do not replace the unchanged legacy directory; keep or remove
that directory later according to your own retention policy.
