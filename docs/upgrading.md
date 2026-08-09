# Upgrading DJ Support

Create a local-data backup before an upgrade that changes retained schemas:

```bash
djsupport backup
```

## Move legacy Rekordbox configuration

DJ Support now stores the saved Rekordbox XML reference in private platform
application data as `config.json`. From the directory containing an older
`.djsupport_config.json`, preview the exact migration candidate:

```bash
djsupport library migrate-config
```

Apply only after reviewing the status:

```bash
djsupport library migrate-config --apply
```

The command checks only the current directory, never prints the saved XML path,
and leaves the legacy file unchanged. If both files exist and differ, migration
stops; use `djsupport library set` to choose the intended XML explicitly.
`config.json` is included in later `djsupport backup` archives, and a differing
configuration during restore requires an explicit `current` or `archive`
choice.

## To 0.5.0

Spotify authorization now includes `playlist-read-private` so DJ Support can
inspect private Provisional Playlists during Approval. Sign in again when
prompted. Denying that permission leaves private-playlist inspection
unavailable; DJ Support does not broaden permissions automatically.

Publication schema versions 1–4 and Transfer schema version 1 remain readable.
The next durable write upgrades them to publication schema 5 and Transfer
schema 2 while retaining account ownership, resumable work, ordered chunk
evidence, Mirrors, and Approval history.

If retained state uses a previous Spotify profile identity, run the explicit,
backup-first ownership migration with both account identities:

```bash
djsupport migrate-0-5 --legacy-account-id <old> --account-id <stable>
```

The migration stops on conflicting ownership, reports aggregate counts only,
and is safe to repeat. See the [0.5.0 release notes](release-notes-0.5.0.md) for
the Spotify boundary changes and known limitations.

## To the local-audio identity release

The first write after installing the local-audio identity release upgrades
matching knowledge to schema 2 and Transfer state to schema 3. Matching schema
1 and Transfer schemas 1–2 remain readable. Create a local-data backup first if
you want a recovery point. The upgrade retains Approved Matches, Corrections,
publication history, and current resumable work; a legacy Batch without a
content-bound plan identity must be restarted so changed private source content
cannot resume stale work. New fingerprint evidence remains in private
application data and is never added to Git or generated reports. Unsupported
matching-knowledge schemas are rejected without rewriting the private file.

## To the Qualification Workspace release

The next durable writes upgrade Transfer state to schema 4, matching knowledge
to schema 3, and publication manifests to schema 6. Earlier supported schemas
remain readable. Transfer schema 4 adds a `qualifications` collection; matching
schema 3 and publication schema 6 retain rich Spotify release, duration, and
truthful availability context for later Approved Match reuse. Qualification
Drafts are additive private state: they do not become matching knowledge or
Approval during upgrade. Backup/restore merges distinct drafts and requires an
explicit current/archive choice when the same draft differs, so neither state
wins silently. Audition handles, audio bytes, paths, filenames, and fingerprints
are not stored in a draft.

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
