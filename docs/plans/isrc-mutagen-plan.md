# ISRC via Mutagen — Test Plan

## Goal

Test reading ISRC codes directly from audio files on disk, then using
them as a high-confidence pre-flight Spotify search strategy — before
falling back to fuzzy artist/title matching.

---

## Background

Rekordbox XML exports a `Location` attribute on every `<TRACK>` element
containing the absolute path to the audio file on disk, e.g.:

```xml
<TRACK TrackID="1"
       Name="Vultora (Original Mix)"
       Artist="Solomun"
       Location="file://localhost/Users/you/Music/Solomun - Vultora.mp3"
       ... />
```

The current parser (`rekordbox.py`) does not read `Location`.  If we
add it, we can open the file with **mutagen** and read the ISRC embedded
in the audio tags.

---

## Where ISRC Lives in Audio Files

| Format | Tag standard    | Key / frame |
|--------|-----------------|-------------|
| MP3    | ID3v2           | `TSRC`      |
| FLAC   | Vorbis Comments | `isrc`      |
| AIFF   | ID3v2           | `TSRC`      |
| MP4/AAC| iTunes atoms    | not standard, rarely present |

Beatport and Traxsource both embed ISRC in purchased downloads.
Promos and white labels typically do not have it.

---

## Dependencies

```bash
pip install mutagen
```

Mutagen has no dependencies outside the Python standard library.

---

## Step 1 — Parse `Location` from the XML

In `rekordbox.py`, add `location` to the `Track` dataclass and read it
in `parse_xml`:

```python
@dataclass
class Track:
    track_id: str
    name: str
    artist: str
    album: str
    remixer: str
    label: str
    genre: str
    date_added: str
    location: str = ""          # <-- add this
```

Inside the `for track_el in collection.findall("TRACK"):` loop:

```python
raw_loc = track_el.get("Location", "")
# Rekordbox uses file URIs: "file://localhost/path/to/file.mp3"
# Strip the scheme so pathlib can open it.
if raw_loc.startswith("file://localhost"):
    raw_loc = raw_loc[len("file://localhost"):]
tracks[tid] = Track(
    ...
    location=raw_loc,
)
```

---

## Step 2 — Read ISRC from the Audio File

A small utility function (could live in a new `djsupport/isrc.py`):

```python
from pathlib import Path

def read_isrc(file_path: str) -> str | None:
    """Return ISRC from audio file tags, or None if not found/readable."""
    if not file_path:
        return None

    p = Path(file_path)
    if not p.exists():
        return None

    try:
        suffix = p.suffix.lower()

        if suffix in (".mp3", ".aiff", ".aif"):
            from mutagen.id3 import ID3, ID3NoHeaderError
            try:
                tags = ID3(p)
            except ID3NoHeaderError:
                return None
            tsrc = tags.get("TSRC")
            return str(tsrc) if tsrc else None

        elif suffix == ".flac":
            from mutagen.flac import FLAC
            tags = FLAC(p)
            values = tags.get("isrc")
            return values[0] if values else None

    except Exception:
        return None

    return None
```

---

## Step 3 — ISRC as Strategy 0 in `match_track`

In `matcher.py`, before all existing strategies:

```python
from djsupport.isrc import read_isrc

def match_track(sp, track: Track, threshold: int = 80) -> dict | None:
    all_results: list[dict] = []

    # Strategy 0: exact ISRC lookup (highest confidence, no fuzzy needed)
    isrc = read_isrc(track.location)
    if isrc:
        isrc_results = search_track(sp, "", "", isrc=isrc)
        if isrc_results:
            best = isrc_results[0]
            return {**best, "score": 100.0, "match_type": "exact"}

    # Strategy 1 onwards: existing fuzzy strategies ...
```

And in `spotify.py`, extend `search_track` to accept an ISRC:

```python
def search_track(
    sp, artist: str, title: str,
    album: str | None = None,
    isrc: str | None = None,
) -> list[dict]:
    if isrc:
        query = f"isrc:{isrc}"
    else:
        query = f"artist:{artist} track:{title}"
        if album:
            query += f" album:{album}"

    results = sp.search(q=query, type="track", limit=5)
    ...
```

---

## Step 4 — Manual Test Script

Save as `scripts/test_isrc.py` (not part of the installed package).
Point it at your XML and a folder of audio files to see hit rate:

```python
#!/usr/bin/env python3
"""Quick manual test: how many tracks have ISRC in their audio tags?

Usage:
    python scripts/test_isrc.py /path/to/library.xml
"""
import sys
from djsupport.rekordbox import parse_xml
from djsupport.isrc import read_isrc   # once the module exists

xml_path = sys.argv[1]
tracks, _ = parse_xml(xml_path)

found = missing = no_location = 0
for t in tracks.values():
    if not t.location:
        no_location += 1
        continue
    isrc = read_isrc(t.location)
    if isrc:
        print(f"  FOUND  {t.artist} - {t.name}  →  {isrc}")
        found += 1
    else:
        print(f"  MISS   {t.artist} - {t.name}  (no ISRC tag)")
        missing += 1

total = found + missing + no_location
print(f"\nTotal: {total}  |  ISRC found: {found}  |  Missing: {missing}  |  No location: {no_location}")
print(f"Hit rate: {found / total * 100:.1f}%" if total else "No tracks.")
```

---

## What to Look For When Testing

- **Hit rate** — what % of your library has ISRC tags (expect higher
  for Beatport/Traxsource purchases, lower for promos/rips).
- **Correctness** — do the ISRCs returned by Spotify actually match the
  track you expected?  Cross-check a few manually.
- **File URI encoding** — Rekordbox escapes spaces as `%20` in
  `Location`.  If paths fail to resolve, add a `urllib.parse.unquote`
  call when stripping the scheme.
- **Missing files** — if the library has been moved since the XML was
  exported, `location` paths will be stale.  The function returns
  `None` gracefully in that case and falls through to fuzzy matching.

---

## Fixture XML

The test fixture at `tests/fixtures/library.xml` does not include
`Location` attributes (the files don't exist on disk).  Once
`location` is added to the `Track` dataclass it will default to `""`,
so existing tests and the fixture remain valid without modification.
