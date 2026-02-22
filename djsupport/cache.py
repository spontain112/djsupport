"""Persistent match cache with auto-checkpoint and retry logic."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from djsupport.matcher import _normalize

CACHE_VERSION = 1
DEFAULT_CACHE_PATH = ".djsupport_cache.json"
DEFAULT_RETRY_DAYS = 7
CHECKPOINT_INTERVAL = 50


@dataclass
class CacheEntry:
    spotify_uri: str | None
    spotify_name: str | None
    spotify_artist: str | None
    score: float | None
    matched: bool
    timestamp: str
    threshold: int


class MatchCache:
    def __init__(self, path: str = DEFAULT_CACHE_PATH):
        self.path = Path(path)
        self.entries: dict[str, CacheEntry] = {}
        self._dirty_count: int = 0

    def load(self) -> None:
        """Load cache from disk. No-op if file doesn't exist."""
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        if data.get("version") != CACHE_VERSION:
            return
        for key, entry in data.get("entries", {}).items():
            self.entries[key] = CacheEntry(**entry)

    def save(self) -> None:
        """Write cache to disk."""
        data = {
            "version": CACHE_VERSION,
            "entries": {k: asdict(v) for k, v in self.entries.items()},
        }
        self.path.write_text(json.dumps(data, indent=2))
        self._dirty_count = 0

    def cache_key(self, artist: str, title: str) -> str:
        return f"{_normalize(artist)}||{_normalize(title)}"

    def lookup(self, artist: str, title: str, threshold: int) -> CacheEntry | None:
        """Return cached entry if valid for this threshold, else None."""
        key = self.cache_key(artist, title)
        entry = self.entries.get(key)
        if entry is None:
            return None
        if entry.matched and entry.score is not None and entry.score >= threshold:
            return entry
        if not entry.matched and entry.threshold <= threshold:
            return entry
        return None

    def store(self, artist: str, title: str, threshold: int,
              result: dict | None) -> None:
        """Store a match result (or failure) in cache. Auto-checkpoints."""
        key = self.cache_key(artist, title)
        if result is not None:
            self.entries[key] = CacheEntry(
                spotify_uri=result["uri"],
                spotify_name=result["name"],
                spotify_artist=result["artist"],
                score=result["score"],
                matched=True,
                timestamp=datetime.now().isoformat(),
                threshold=threshold,
            )
        else:
            self.entries[key] = CacheEntry(
                spotify_uri=None,
                spotify_name=None,
                spotify_artist=None,
                score=None,
                matched=False,
                timestamp=datetime.now().isoformat(),
                threshold=threshold,
            )
        self._dirty_count += 1
        if self._dirty_count >= CHECKPOINT_INTERVAL:
            self.save()

    def is_retry_eligible(self, artist: str, title: str,
                          retry_days: int = DEFAULT_RETRY_DAYS,
                          force: bool = False) -> bool:
        """Check if a failed entry should be retried."""
        key = self.cache_key(artist, title)
        entry = self.entries.get(key)
        if entry is None or entry.matched:
            return False
        if force:
            return True
        age = datetime.now() - datetime.fromisoformat(entry.timestamp)
        return age > timedelta(days=retry_days)
