# DJ Support

DJ Support turns curated Rekordbox playlists and Beatport selections into
reviewable Spotify playlists. It keeps the DJ in control of matching,
publication, and later playlist changes.

## Supported workflows

| Source | Default result | Best for |
| --- | --- | --- |
| Rekordbox playlist | **Mirror** | Keeping a Spotify playlist aligned with an explicitly selected Rekordbox playlist |
| Beatport chart | **Snapshot** | Capturing a chart once; opt into a Mirror only when it should be maintained |
| Beatport label | **Snapshot** | Capturing a label selection once; opt into a Mirror only when it should be maintained |

Every Transfer can be Previewed before Spotify is changed. Published matches
are reviewable in Spotify, and explicit Approval turns accepted matches into
reusable local matching knowledge. DJ Support never infers Approval,
Corrections, or destructive playlist intent.

## Requirements

- Python 3.10 or newer
- A [Spotify Developer](https://developer.spotify.com/dashboard) application
- A Rekordbox XML export for Rekordbox Transfers
- Optional: `fpcalc` from Chromaprint for local audio identity

## Install

Install the command-line application:

```bash
python3 -m pip install djsupport
```

Include the optional local web application with:

```bash
python3 -m pip install "djsupport[web]"
```

For development from a source checkout, see
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Spotify setup

Copy the example environment file:

```bash
cp .env.example .env
```

Add your Spotify client ID and secret to `.env`. In the Spotify Developer
Dashboard, allow this exact redirect URI:

```text
http://127.0.0.1:8888/callback
```

Spotify does not accept `localhost` as an alias for this callback. The same
Spotify application may allowlist additional callbacks used by other DJ Support
clients.

## Your first Rekordbox Transfer

Export your collection from Rekordbox with **File → Export Collection in xml
format**, then save its location:

```bash
djsupport library set /path/to/library.xml
djsupport library show
```

List the available playlists:

```bash
djsupport list
```

Preview one playlist without modifying Spotify or playlist state:

```bash
djsupport sync --playlist "Deep House" --dry-run
```

Preview may retain local matching knowledge and a resumable Transfer checkpoint.
When the report looks right, run the same bounded selection without
`--dry-run`:

```bash
djsupport sync --playlist "Deep House"
```

Select several playlists by repeating the option:

```bash
djsupport sync -p "Deep House" -p "Peak Time"
```

Processing the complete library is deliberately explicit because it can be
expensive:

```bash
djsupport sync --whole-library
```

## Beatport charts and labels

Preview and publish a one-time chart Snapshot:

```bash
djsupport beatport <chart-url> --dry-run
djsupport beatport <chart-url>
```

Preview and publish a label Snapshot by URL or name:

```bash
djsupport label <label-url-or-name> --dry-run
djsupport label <label-url-or-name>
```

Use `--mirror` only when later Transfers should maintain the same Spotify
playlist:

```bash
djsupport beatport <chart-url> --mirror
djsupport label <label-url-or-name> --mirror
```

## Review, Approval, and Corrections

Save a detailed report when publishing:

```bash
djsupport beatport <chart-url> --report review.md
```

Beatport reports include an editable review CSV. Review the Provisional Playlist
in Spotify, remove wrong proposals, and replace an incorrect or missing match in
the CSV with the correct Spotify URL. Then approve that playlist:

```bash
djsupport approve <spotify-playlist-id> --review-csv review.csv
```

Surviving proposals and Corrections become Approved Matches. Removed proposals
become Rejected Matches. If the Provisional Playlist was deleted, DJ Support
records it as Abandoned without accepting its pending matches.

Approved Matches become the local source of truth for later matching. A manual
change to a managed Spotify Mirror is reported as Playlist Drift and requires an
explicit choice; DJ Support does not silently restore or accept the change.

## Retry and resume

Previously unsuccessful matches are retried only when requested:

```bash
djsupport sync -p "Deep House" --retry
djsupport beatport <chart-url> --retry
```

An interrupted Beatport Transfer prints its Transfer ID. Resume it or abandon
it explicitly:

```bash
djsupport beatport <chart-url> --resume <transfer-id>
djsupport beatport <chart-url> --abandon <transfer-id>
```

Run `djsupport --help` or `djsupport <command> --help` for the complete current
command and option reference.

## Optional local audio identity

DJ Support can use a local Chromaprint calculation to recover an existing
Approved Match when Rekordbox metadata has changed:

```bash
djsupport capabilities
djsupport sync -p "Deep House" --dry-run --local-audio-identity
```

This is opt-in and limited to the selected Batch. It does not scan directories,
upload audio or fingerprints, modify files, or identify unknown recordings.
Exact compatible evidence can only reuse a match that the same Spotify account
already approved. Missing or unreadable audio falls back to metadata matching.

## AI-agent use

Codex and other harnesses are first-class clients of the same Transfer policy.
Inspect capabilities without reading private source data:

```bash
djsupport capabilities --json
```

Plan one selected Batch with private-source authorization:

```bash
djsupport sync -p "Deep House" --dry-run --json \
  --authorize-private-source
```

Spotify publication requires separate authorization:

```bash
djsupport sync -p "Deep House" --json \
  --authorize-private-source --authorize-spotify-write
```

JSON mode is non-interactive and never treats conversation as authorization. A
changed source selection or effect scope produces a different Batch identity.
See [ADR-0002](docs/adr/0002-make-transfer-agent-native.md) for the complete
contract.

## Backup, upgrades, and local data

Create a versioned local-data backup with:

```bash
djsupport backup
```

Restore is preview-first:

```bash
djsupport restore /path/to/djsupport-backup.zip
djsupport restore /path/to/djsupport-backup.zip --apply
```

Read [backup and restore](docs/backup-and-restore.md) and the
[upgrade guide](docs/upgrading.md) before migrating retained data.

Credentials, source-library paths, matching knowledge, Corrections, Transfer
checkpoints, publication state, playlist identifiers, and generated reports are
private local data. They are not repository or package content. On macOS, the
default data directory is `~/Library/Application Support/djsupport`; on Linux it
is `$XDG_DATA_HOME/djsupport` or `~/.local/share/djsupport`.

## Documentation

- [Domain language](CONTEXT.md)
- [Upgrade guide](docs/upgrading.md)
- [Backup and restore](docs/backup-and-restore.md)
- [Release notes](docs/release-notes-0.5.0.md)
- [Changelog](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)

## License

MIT
