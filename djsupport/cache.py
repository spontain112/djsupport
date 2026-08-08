"""Persistent match cache with auto-checkpoint and retry logic."""

import json
from hashlib import sha256
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from djsupport.matcher import _normalize

CACHE_VERSION = 2
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
    spotify_release: str = ""
    spotify_duration: int = 0

    def __post_init__(self) -> None:
        self.score_reasons = tuple(self.score_reasons)


class MatchCache:
    def __init__(self, path: str = DEFAULT_CACHE_PATH):
        self.path = Path(path)
        self.entries: dict[str, CacheEntry] = {}
        self.local_regressions: list[dict] = []
        self.approval_conflicts: list[dict] = []
        self.fingerprint_observations: dict[str, dict] = {}
        self.fingerprint_associations: list[dict] = []
        self._dirty_count: int = 0

    def load(self) -> None:
        """Load cache from disk. No-op if file doesn't exist."""
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        if data.get("version") not in (1, CACHE_VERSION):
            raise ValueError(
                "Unsupported matching-knowledge schema; upgrade djsupport "
                "before using this file"
            )
        for key, entry in data.get("entries", {}).items():
            self.entries[key] = CacheEntry(**entry)
        self.local_regressions = data.get("local_regressions", [])
        self.approval_conflicts = data.get("approval_conflicts", [])
        self.fingerprint_observations = data.get("fingerprint_observations", {})
        self.fingerprint_associations = data.get("fingerprint_associations", [])

    def save(self) -> None:
        """Write cache to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": CACHE_VERSION,
            "entries": {k: asdict(v) for k, v in self.entries.items()},
            "local_regressions": self.local_regressions,
            "approval_conflicts": self.approval_conflicts,
            "fingerprint_observations": self.fingerprint_observations,
            "fingerprint_associations": self.fingerprint_associations,
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
                spotify_release=result.get("album", ""),
                spotify_duration=int(result.get("duration_ms", 0)) // 1000,
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
                spotify_release=result.get("spotify_release", result.get("album", "")),
                spotify_duration=int(
                    result.get(
                        "spotify_duration",
                        int(result.get("duration_ms", 0)) // 1000,
                    )
                ),
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

    def retain_fingerprint_observation(
        self, *, algorithm: str, algorithm_version: str, fingerprint: str,
        audio_duration: int, source_track_id: str,
    ) -> str:
        """Retain private provisional evidence and return a non-secret handle."""
        material = "\0".join((
            algorithm, algorithm_version, fingerprint, str(audio_duration),
            source_track_id,
        ))
        evidence_id = sha256(material.encode()).hexdigest()
        self.fingerprint_observations[evidence_id] = {
            "algorithm": algorithm,
            "algorithm_version": algorithm_version,
            "fingerprint": fingerprint,
            "audio_duration": audio_duration,
            "source_track_id": source_track_id,
            "observed_at": datetime.now().isoformat(),
        }
        self._dirty_count += 1
        return evidence_id

    def fingerprint_observation(self, evidence_id: str) -> dict | None:
        return self.fingerprint_observations.get(evidence_id)

    def lookup_fingerprint(
        self, *, algorithm: str, algorithm_version: str, fingerprint: str,
        account_id: str,
    ) -> dict | None:
        """Return one exact account-scoped Approved Match, never a guess."""
        matching = [
            item for item in self.fingerprint_associations
            if item["algorithm"] == algorithm
            and item["algorithm_version"] == algorithm_version
            and item["fingerprint"] == fingerprint
            and item["account_id"] == account_id
        ]
        if any(item.get("authority_status") == "conflict" for item in matching):
            return None
        candidates = [
            item for item in matching
            if item.get("authority_status") == "approved"
        ]
        uris = {item["spotify_uri"] for item in candidates}
        if len(uris) != 1:
            return None
        item = candidates[0]
        return {
            "uri": item["spotify_uri"],
            "name": item["spotify_name"],
            "artist": item["spotify_artist"],
            "score": item["score"],
            "match_type": "approved_local_audio",
            "score_reasons": [
                "Approved Match reused from local audio identity",
                *item.get("score_reasons", ()),
            ],
            "album": item.get("spotify_release", ""),
            "duration_ms": int(item.get("spotify_duration", 0)) * 1000,
            "authoritative": True,
        }

    def approve_fingerprint(
        self, *, evidence_id: str, account_id: str, source_artist: str,
        source_title: str, source_duration: int, result: dict,
    ) -> dict | None:
        observation = self.fingerprint_observations.get(evidence_id)
        if observation is None:
            return None
        same_identity = [
            item for item in self.fingerprint_associations
            if item["algorithm"] == observation["algorithm"]
            and item["algorithm_version"] == observation["algorithm_version"]
            and item["fingerprint"] == observation["fingerprint"]
            and item["account_id"] == account_id
            and item.get("authority_status") == "approved"
        ]
        approved_uris = {item["spotify_uri"] for item in same_identity}
        association = {
            **observation,
            "account_id": account_id,
            "source_artist": source_artist,
            "source_title": source_title,
            "source_duration": source_duration,
            "spotify_uri": result["uri"],
            "spotify_name": result["name"],
            "spotify_artist": result["artist"],
            "score": result["score"],
            "match_type": result.get("match_type", "exact"),
            "score_reasons": list(result.get("score_reasons", ())),
            "spotify_release": result.get("spotify_release", ""),
            "spotify_duration": int(result.get("spotify_duration", 0)),
            "authority_status": "approved",
            "approved_at": datetime.now().isoformat(),
        }
        if approved_uris and approved_uris != {result["uri"]}:
            conflict = {
                "source_artist": source_artist,
                "source_title": source_title,
                "source_duration": source_duration,
                "approved_spotify_uri": sorted(approved_uris)[0],
                "proposed_spotify_uri": result["uri"],
            }
            conflict_association = {
                **association, "authority_status": "conflict",
            }
            if not any(item == conflict_association for item in self.fingerprint_associations):
                self.fingerprint_associations.append(conflict_association)
            if conflict not in self.approval_conflicts:
                self.approval_conflicts.append(conflict)
            self._dirty_count += 1
            return conflict
        self.fingerprint_associations = [
            item for item in self.fingerprint_associations
            if not (
                item["algorithm"] == observation["algorithm"]
                and item["algorithm_version"] == observation["algorithm_version"]
                and item["fingerprint"] == observation["fingerprint"]
                and item["account_id"] == account_id
                and item.get("authority_status") == "conflict"
            )
        ]
        if not any(
            item["algorithm"] == association["algorithm"]
            and item["algorithm_version"] == association["algorithm_version"]
            and item["fingerprint"] == association["fingerprint"]
            and item["account_id"] == association["account_id"]
            and item["spotify_uri"] == association["spotify_uri"]
            for item in self.fingerprint_associations
        ):
            self.fingerprint_associations.append(association)
            self._dirty_count += 1
        return None

    def revoke_fingerprints(
        self, *, source_artist: str, source_title: str, source_duration: int,
        evidence_id: str | None = None, account_id: str,
    ) -> None:
        observation = (
            self.fingerprint_observations.get(evidence_id)
            if evidence_id is not None else None
        )
        self.fingerprint_associations = [
            item for item in self.fingerprint_associations
            if not (
                item.get("account_id") == account_id
                and (
                    (
                        item.get("source_artist") == source_artist
                        and item.get("source_title") == source_title
                        and item.get("source_duration") == source_duration
                    )
                    or (
                        observation is not None
                        and item.get("algorithm") == observation.get("algorithm")
                        and item.get("algorithm_version")
                        == observation.get("algorithm_version")
                        and item.get("fingerprint") == observation.get("fingerprint")
                    )
                )
            )
        ]
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
