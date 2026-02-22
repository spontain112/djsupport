"""Persistent playlist ID mapping for Rekordbox → Spotify sync."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

STATE_VERSION = 1
DEFAULT_STATE_PATH = ".djsupport_playlists.json"


@dataclass
class PlaylistState:
    spotify_id: str
    spotify_name: str
    rekordbox_path: str
    last_synced: str
    prefix_used: str | None


class PlaylistStateManager:
    def __init__(self, path: str = DEFAULT_STATE_PATH):
        self.path = Path(path)
        self.entries: dict[str, PlaylistState] = {}

    def load(self) -> None:
        """Load state from disk. No-op if file doesn't exist."""
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        if data.get("version") != STATE_VERSION:
            return
        for key, entry in data.get("entries", {}).items():
            self.entries[key] = PlaylistState(**entry)

    def save(self) -> None:
        """Write state to disk."""
        data = {
            "version": STATE_VERSION,
            "entries": {k: asdict(v) for k, v in self.entries.items()},
        }
        self.path.write_text(json.dumps(data, indent=2))

    def get(self, name: str) -> PlaylistState | None:
        """Look up state by Rekordbox playlist name."""
        return self.entries.get(name)

    def set(self, name: str, state: PlaylistState) -> None:
        """Store state for a Rekordbox playlist name."""
        self.entries[name] = state

    def is_empty(self) -> bool:
        return len(self.entries) == 0
