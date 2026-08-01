# djsupport

Transfer curated Rekordbox and Beatport selections to Spotify through reviewable Mirrors and Snapshots.

## Features

- **Rekordbox XML parsing** — reads playlists and tracks from your Rekordbox library export
- **Fuzzy matching** — multi-strategy search using artist, title, remixer, and duration fields with configurable confidence threshold
- **Duration-based matching** — disambiguates original, radio, and extended versions using track duration
- **Matching knowledge** — reuses Approved Matches and retained proposals across Transfers
- **Incremental updates** — only adds/removes changed tracks instead of replacing entire playlists
- **Preview** — complete matching and reporting without playlist or playlist-state mutation (`--dry-run` remains the compatible flag)
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

```bash
git clone <repo-url>
cd djsupport          # project root (contains pyproject.toml)
pip install -e .
```

> **Troubleshooting:** Make sure you run `pip install` from the project root
> where `pyproject.toml` is located — not from the `djsupport/` subdirectory
> inside it. If you downloaded a zip from GitHub, the root folder is typically
> named `djsupport-main`. Also note that `pipx` does not support editable
> installs (`-e`); use `pip` instead.

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

Preview a selection without modifying Spotify playlists or playlist state:

```bash
djsupport sync -p "Deep House" --dry-run
```

### Tuning match quality

Adjust the minimum match confidence (0–100, default 80):

```bash
djsupport sync -t 70
```

### Cache and retry

Bypass the cache and re-search every track:

```bash
djsupport sync --no-cache
```

Force retry all previously failed matches:

```bash
djsupport sync --retry
```

Change auto-retry window (default: retry failures older than 7 days):

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
| `--dry-run` | | Preview without modifying Spotify or playlist state |
| `-t, --threshold` | 80 | Minimum match confidence (0–100) |
| `--report` | | Save Markdown report to this path |
| `--no-cache` | | Bypass match cache |
| `--retry` | | Force retry all failed matches |
| `--retry-days` | 7 | Auto-retry failures older than N days |
| `--prefix` | djsupport | Prefix for Spotify playlist names |
| `--no-prefix` | | Disable playlist name prefix |

## License

MIT
