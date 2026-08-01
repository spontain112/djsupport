# djsupport

Transfer curated Rekordbox and Beatport selections to Spotify through reviewable Mirrors and Snapshots.

## Features

- **Rekordbox XML parsing** — reads playlists and tracks from your Rekordbox library export
- **Fuzzy matching** — multi-strategy search using artist, title, remixer, and duration fields with configurable confidence threshold
- **Duration-based matching** — disambiguates original, radio, and extended versions using track duration
- **Matching knowledge** — reuses Approved Matches and retained proposals across Transfers
- **Incremental updates** — only adds/removes changed tracks instead of replacing entire playlists
- **Preview** — complete matching and reporting without Spotify playlist or
  publication-manifest mutation; local matching knowledge and durable Transfer
  checkpoints may be retained (`--dry-run` remains the compatible flag)
- **Markdown reports** — save detailed match reports with per-playlist breakdowns
- **Playlist prefix** — prefix Spotify playlist names (e.g. `djsupport / Deep House`) to keep them organized
- **Explicit Batches** — select one or more Rekordbox playlists, or opt into the whole library with cost preflight
- **Graceful rate limiting** — aborts with a clear message, saves cache, and exits non-zero instead of hanging; resume later to continue where you left off
- **Local-data backup and restore** — creates versioned archives without OAuth credentials and validates, previews, and conflict-checks restores before changing data

## Prerequisites

- Python 3.10+
- A [Spotify Developer](https://developer.spotify.com/dashboard) application (for API credentials)
- A Rekordbox XML library export

## Installation

Install the command-line application from a release artifact:

```bash
python -m pip install djsupport
```

Install the optional local web UI as well:

```bash
python -m pip install "djsupport[web]"
```

For a source checkout used for development:

```bash
git clone <repo-url>
cd djsupport          # project root (contains pyproject.toml)
python -m pip install -e ".[dev,web]"
```

> **Troubleshooting:** Make sure you run `pip install` from the project root
> where `pyproject.toml` is located — not from the `djsupport/` subdirectory
> inside it. If you downloaded a zip from GitHub, the root folder is typically
> named `djsupport-main`. Also note that `pipx` does not support editable
> installs (`-e`); use `pip` instead.

### Upgrading from 0.3.0

Install 0.4.0, keep the old working directory intact, and use the explicit
preview-first migration described under [Upgrade from 0.3.0](#upgrade-from-030).
Version 0.4.0 does not discover or rewrite legacy files automatically.

## Setup

### 1. Spotify credentials

Copy the example env file and fill in your credentials:

```bash
cp .env.example .env
```

You can obtain these values from the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) after creating an application. Make sure `http://localhost:8888/callback` is added as a Redirect URI in your app settings.

### 2. Rekordbox XML export

In Rekordbox, go to **File > Export Collection in xml format** and save the file somewhere accessible.

### 3. Save your Rekordbox XML path (recommended)

Save the XML path once so future commands can omit it:

```bash
djsupport library set /path/to/library.xml
```

Check the saved path/status:

```bash
djsupport library show
```

## Usage

### Back up and restore local data

Create one timestamped archive in the private application-data directory:

```bash
djsupport backup
```

Validate and preview an archive without changing current data, then apply it:

```bash
djsupport restore /path/to/djsupport-backup-20260801T123456.zip
djsupport restore /path/to/djsupport-backup-20260801T123456.zip --apply
```

If Approval or playlist-state truth conflicts, restore stops without mutation
and prints the conflict identifier. Resolve it explicitly with
`--resolve 'CONFLICT_ID=current'` or `--resolve 'CONFLICT_ID=archive'`.

### Upgrade from 0.3.0

Migration is explicit and preview-first. Select the single working directory
that contains your old 0.3.0 files, review the aggregate-only report, and then
apply the same migration:

```bash
djsupport migrate-0-3 /path/to/old-working-directory
djsupport migrate-0-3 /path/to/old-working-directory --apply
```

Apply first creates and verifies a current-format backup. Legacy cache entries
remain non-authoritative retained proposals; current matching knowledge wins
conflicts. Rekordbox relationships require an explicit future relink because
0.3.0 did not retain safe Spotify account ownership. Beatport relationships are
kept only as unmanaged historical Snapshots. No Spotify request is made, and
the legacy directory is never changed or deleted. Repeating apply is safe.

See [upgrade guidance](docs/upgrading.md) and
[backup and restore details](docs/backup-and-restore.md).

Backups include only recognized versioned djsupport data and local Markdown/CSV
reports that do not contain common credential fields. OAuth tokens, `.env`
files, unrelated files, and report symlinks are excluded. Restore rejects
unexpected paths, unsupported schemas, integrity failures, and unresolved
Approval or playlist-state conflicts before replacing current data.

### List playlists

Preview what playlists are available in your Rekordbox export:

```bash
djsupport list
```

Output:

```
  House/Deep House (42 tracks)
  Techno/Peak Time (18 tracks)
  Festival 2025/Main Stage (35 tracks)
```

### Transfer Rekordbox playlists to Spotify

Transfer one playlist as a Mirror:

```bash
djsupport sync --playlist "Deep House"
```

Transfer several explicitly selected playlists as a Batch:

```bash
djsupport sync -p "Deep House" -p "Peak Time"
```

Opt into a whole-library Batch:

```bash
djsupport sync --whole-library
```

Preview a selection without modifying Spotify playlists or publication
manifests:

```bash
djsupport sync -p "Deep House" --dry-run
```

### Tuning match quality

Adjust the minimum match confidence (0–100, default 80):

```bash
djsupport sync -t 70
```

### Matching knowledge and retry

Bypass retained matching knowledge and re-search every track (the flag name is
preserved for compatibility):

```bash
djsupport sync --no-cache
```

Force retry all previously failed matches:

```bash
djsupport sync --retry
```

`--retry-days` remains accepted for command compatibility, but unmatched tracks
are retried only when `--retry` is explicit:

```bash
djsupport sync --retry-days 3
```

### Reports

Save a detailed Markdown report:

```bash
djsupport sync --report report.md
```

Beatport publication reports also create an editable CSV beside the Markdown
file. Review the Provisional Playlist in Spotify, remove incorrect proposals,
then approve that one playlist:

```bash
djsupport beatport <chart-url> --report review.md
djsupport approve <spotify-playlist-id> --review-csv review.csv
```

Approval records surviving proposals as approved, removed proposals as rejected,
and a deleted Provisional Playlist as abandoned while retaining its history.
Edit a row's Spotify URL to provide a Correction. Corrections repair the playlist
without duplicates and become approved matching knowledge stored only in your
local application data.

For matcher contributors, the optional live accuracy workflow consumes those
local Corrections directly; no personal mapping fixture is kept in Git. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the privacy-safe workflow and synthetic
fixture requirements.

### Beatport Snapshots and Mirrors

Create a one-time chart or label Snapshot (the default):

```bash
djsupport beatport <chart-url> --dry-run
djsupport beatport <chart-url>
djsupport label <label-url-or-name> --dry-run
djsupport label <label-url-or-name>
```

Use `--mirror` only when you want later Transfers to maintain one recurring
playlist. Interrupted Beatport Transfers print an ID that can be supplied to
`--resume`; use `--abandon` to end a retained Transfer explicitly.

```bash
djsupport beatport <chart-url> --mirror
djsupport beatport <chart-url> --resume <transfer-id>
djsupport beatport <chart-url> --abandon <transfer-id>
```

Chart playlist names include `Curator - Chart Name` when the supported Beatport
payload provides a curator; otherwise they use the chart name. Label Snapshots
use the label name.

### Review lifecycle

Preview performs source intake, matching, and reporting without modifying
Spotify playlists or publication manifests. It may retain local matching
knowledge and durable Transfer checkpoints so work can be inspected or resumed.
A non-Preview Beatport Transfer publishes a Provisional Playlist. Review it in
Spotify, remove wrong proposals, optionally edit the generated CSV with
Corrections, and then run `approve`. Approved Matches become reusable local
matching knowledge. A deleted Provisional Playlist is recorded as Abandoned,
and Match Collisions remain review-required until each mapping is corrected or
rejected.

### Privacy and local state

Credentials, source-library paths, matching knowledge, Corrections, Transfer
checkpoints, publication manifests, playlist identifiers, and reports are local
user data. They are not package assets and must not be committed or attached to
issues without explicit export, consent, and privacy review. On macOS and Linux,
default durable Transfer data is stored under the platform data directory
(`~/Library/Application Support/djsupport` on macOS and
`$XDG_DATA_HOME/djsupport` or `~/.local/share/djsupport` on Linux). The saved
Rekordbox XML path remains in the local configuration file created by
`djsupport library set`.

See [the 0.4.0 release notes](docs/release-notes-0.4.0.md) for the complete
upgrade summary and known limitations.

### Playlist naming

Spotify playlists are prefixed with `djsupport /` by default. Change or disable the prefix:

```bash
djsupport sync --prefix "dj"
djsupport sync --no-prefix
```

### Advanced options

You can pass an explicit XML path at any time to override the saved path:

```bash
djsupport sync /path/to/library.xml
```

Rekordbox Transfer options (the `sync` command name and `--dry-run` flag remain compatible):

| Flag | Default | Description |
|------|---------|-------------|
| `-p, --playlist` | | Select by exact name/path; repeat for a Batch |
| `--whole-library` | | Explicitly select every playlist |
| `--dry-run` | | Preview without modifying Spotify or publication manifests; local knowledge/checkpoints may be retained |
| `-t, --threshold` | 80 | Minimum match confidence (0–100) |
| `--report` | | Save Markdown report to this path |
| `--no-cache` | | Bypass retained matching knowledge (compatible flag) |
| `--retry` | | Force retry all failed matches |
| `--retry-days` | 7 | Compatibility-only; unmatched tracks require `--retry` |
| `--prefix` | djsupport | Prefix for Spotify playlist names |
| `--no-prefix` | | Disable playlist name prefix |

## License

MIT
