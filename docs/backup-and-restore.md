# Backup and restore

`djsupport backup` creates a versioned archive in private application storage.
It includes matching knowledge, Transfer and publication state, migration
records, and privacy-screened reports. Credentials and unrelated files are not
included.

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
