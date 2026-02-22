# djsupport

Sync your Rekordbox playlists to Spotify. Parses a Rekordbox XML library export, fuzzy-matches tracks against the Spotify catalog, and creates or updates Spotify playlists automatically.

## Features

- **Rekordbox XML parsing** — reads playlists and tracks from your Rekordbox library export
- **Fuzzy matching** — multi-strategy search using artist, title, and remixer fields with configurable confidence threshold
- **Dry-run mode** — preview matches without creating or modifying any Spotify playlists
- **Threshold control** — tune the minimum match confidence (0–100, default 80)
- **Playlist filtering** — sync a single playlist by name or all playlists at once
- **Combined playlist** — merge all tracks into a single playlist sorted by date added

## Prerequisites

- Python 3.10+
- A [Spotify Developer](https://developer.spotify.com/dashboard) application (for API credentials)
- A Rekordbox XML library export

## Installation

```bash
git clone <repo-url>
cd djsupport
pip install -e .
```

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
djsupport sync path/to/library.xml -p "Deep House"
```

Preview matches without modifying Spotify (dry run):

```bash
djsupport sync path/to/library.xml --dry-run
```

Adjust the match confidence threshold (default 80):

```bash
djsupport sync path/to/library.xml -t 70
```

Combine all tracks into a single playlist (sorted by date added):

```bash
djsupport sync path/to/library.xml --all
```

Use a custom name for the combined playlist:

```bash
djsupport sync path/to/library.xml --all --all-name "My DJ Tracks"
```

You can still pass an explicit XML path at any time to override the saved path for a single run.

## License

MIT
