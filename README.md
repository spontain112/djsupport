# djsupport

Sync your Rekordbox playlists to Spotify. Parses a Rekordbox XML library export, fuzzy-matches tracks against the Spotify catalog, and creates or updates Spotify playlists automatically.

## Features

- **Rekordbox XML parsing** — reads playlists and tracks from your Rekordbox library export
- **Fuzzy matching** — multi-strategy search using artist, title, remixer, and duration fields with configurable confidence threshold
- **Duration-based matching** — disambiguates original, radio, and extended versions using track duration
- **Match caching** — persists matches to disk so subsequent syncs skip already-matched tracks; auto-retries failed matches after 7 days
- **Incremental updates** — only adds/removes changed tracks instead of replacing entire playlists
- **Dry-run mode** — preview matches without creating or modifying any Spotify playlists
- **Markdown reports** — save detailed match reports with per-playlist breakdowns
- **Playlist prefix** — prefix Spotify playlist names (e.g. `djsupport / Deep House`) to keep them organized
- **Combined playlist** — merge all tracks into a single playlist sorted by date added
- **Graceful rate limiting** — aborts with a clear message, saves cache, and exits non-zero instead of hanging; resume later to continue where you left off

## Prerequisites

- Python 3.10+
- A [Spotify Developer](https://developer.spotify.com/dashboard) application (for API credentials)
- A Rekordbox XML library export

## Installation

Clone the repo and install from the **project root** (the folder that contains `pyproject.toml`):

```bash
git clone <repo-url>
cd djsupport
pip install -e .
```

If you downloaded a zip from GitHub instead, the extracted folder is named
`djsupport-main` — install from there:

```bash
cd djsupport-main
pip install -e .
```

> **Note:** Use `pip`, not `pipx` — `pipx` does not support editable installs (`-e`).

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

### Sync playlists to Spotify

Sync all playlists:

```bash
djsupport sync
```

Sync a single playlist:

```bash
djsupport sync -p "Deep House"
```

Preview matches without modifying Spotify:

```bash
djsupport sync --dry-run
```

Combine all tracks into a single playlist sorted by date added:

```bash
djsupport sync --all --all-name "My DJ Tracks"
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

All sync options:

| Flag | Default | Description |
|------|---------|-------------|
| `-p, --playlist` | | Sync only this playlist by name |
| `--dry-run` | | Preview without modifying Spotify |
| `-t, --threshold` | 80 | Minimum match confidence (0–100) |
| `--all` | | Combine all tracks into one playlist |
| `--all-name` | Rekordbox All | Name for the combined playlist |
| `--report` | | Save Markdown report to this path |
| `--no-cache` | | Bypass match cache |
| `--retry` | | Force retry all failed matches |
| `--retry-days` | 7 | Auto-retry failures older than N days |
| `--incremental` | on | Diff-based playlist updates |
| `--prefix` | djsupport | Prefix for Spotify playlist names |
| `--no-prefix` | | Disable playlist name prefix |

## License

MIT
