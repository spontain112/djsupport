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
    match_type: str | None = None
    approval_status: str | None = None
    source_duration: int = 0
    score_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.score_reasons = tuple(self.score_reasons)


class MatchCache:
    def __init__(self, path: str = DEFAULT_CACHE_PATH):
        self.path = Path(path)
        self.entries: dict[str, CacheEntry] = {}
        self.local_regressions: list[dict] = []
        self.approval_conflicts: list[dict] = []
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
        self.local_regressions = data.get("local_regressions", [])
        self.approval_conflicts = data.get("approval_conflicts", [])

    def save(self) -> None:
        """Write cache to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": CACHE_VERSION,
            "entries": {k: asdict(v) for k, v in self.entries.items()},
            "local_regressions": self.local_regressions,
            "approval_conflicts": self.approval_conflicts,
        }
        self.path.write_text(json.dumps(data, indent=2))
        self._dirty_count = 0

    def cache_key(self, artist: str, title: str, source_duration: int = 0) -> str:
        identity = f"{_normalize(artist)}||{_normalize(title)}"
        return f"{identity}||{source_duration}s" if source_duration > 0 else identity

    def lookup(
        self, artist: str, title: str, threshold: int, source_duration: int = 0,
    ) -> CacheEntry | None:
        """Return cached entry if valid for this threshold, else None."""
        key = self.cache_key(artist, title, source_duration)
        entry = self.entries.get(key)
        if entry is None and source_duration > 0:
            entry = self.entries.get(self.cache_key(artist, title))
        if source_duration == 0:
            identity_prefix = f"{self.cache_key(artist, title)}||"
            approved = [
                candidate for candidate_key, candidate in self.entries.items()
                if candidate_key.startswith(identity_prefix)
                and candidate.approval_status == "approved"
            ]
            approved_uris = {candidate.spotify_uri for candidate in approved}
            if len(approved_uris) == 1:
                entry = approved[0]
        if entry is None:
            return None
        if entry.approval_status == "rejected":
            return None
        if entry.approval_status == "approved":
            if (
                entry.source_duration > 0
                and source_duration > 0
                and abs(entry.source_duration - source_duration) > 30
            ):
                return None
            return entry
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
                match_type=result.get("match_type"),
                score_reasons=tuple(result.get("score_reasons", ())),
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
                match_type=None,
                matched=False,
                timestamp=datetime.now().isoformat(),
                threshold=threshold,
            )
        self._dirty_count += 1
        if self._dirty_count >= CHECKPOINT_INTERVAL:
            self.save()

    def record_approval(
        self, artist: str, title: str, status: str, result: dict,
        source_duration: int = 0,
    ) -> dict | None:
        """Mark retained matching knowledge as explicitly approved or rejected."""
        key = self.cache_key(artist, title, source_duration)
        if source_duration > 0:
            self.entries.pop(self.cache_key(artist, title), None)
        entry = self.entries.get(key)
        if (
            status == "approved"
            and entry is not None
            and entry.approval_status == "approved"
            and entry.spotify_uri != result["uri"]
        ):
            conflict = {
                "source_artist": artist,
                "source_title": title,
                "source_duration": source_duration,
                "approved_spotify_uri": entry.spotify_uri,
                "proposed_spotify_uri": result["uri"],
            }
            if conflict not in self.approval_conflicts:
                self.approval_conflicts.append(conflict)
                self._dirty_count += 1
            return conflict
        if entry is None or status == "approved":
            entry = CacheEntry(
                spotify_uri=result["uri"],
                spotify_name=result["name"],
                spotify_artist=result["artist"],
                score=result["score"],
                matched=True,
                timestamp=datetime.now().isoformat(),
                threshold=0,
                match_type=result.get("match_type"),
                score_reasons=tuple(result.get("score_reasons", ())),
                source_duration=source_duration,
            )
            self.entries[key] = entry
        entry.approval_status = status
        self._dirty_count += 1
        return None

    def record_correction(self, correction: dict) -> None:
        """Retain user-derived matcher truth only in local application data."""
        identity = correction["source_track_id"]
        self.local_regressions = [
            item for item in self.local_regressions
            if item.get("source_track_id") != identity
        ]
        self.local_regressions.append(correction)
        self._dirty_count += 1

    def revoke_approval(
        self, artist: str, title: str, source_duration: int = 0,
    ) -> None:
        """Remove authoritative knowledge after an explicit user decision."""
        self.entries.pop(self.cache_key(artist, title, source_duration), None)
        if source_duration > 0:
            self.entries.pop(self.cache_key(artist, title), None)
        self._dirty_count += 1

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
