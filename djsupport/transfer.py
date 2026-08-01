"""Deep, framework-agnostic Transfer workflow.

The public seam is :class:`Transfer.execute`: adapters describe what to
transfer and receive a structured report, while this module owns matching,
persistence ordering, Preview policy, and Provisional Snapshot publication.
"""

from __future__ import annotations

import json
import hashlib
import csv
import os
import re
import sys
import tempfile
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Protocol, TypeVar
from uuid import uuid4

import requests
import spotipy

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from djsupport.cache import MatchCache
from djsupport.matcher import match_track_with_alternatives
from djsupport.rekordbox import Track
from djsupport.report import (
    AlternativeCandidate,
    MatchCollision,
    MatchedTrack,
    PlaylistDrift,
    PlaylistReport,
    SyncReport,
    SourceRemoval,
    UnmatchedAlternatives,
    UnavailableApprovedMatch,
)
from djsupport.spotify import MAX_RATE_LIMIT_WAIT, RateLimitError, _parse_retry_after


PUBLICATION_MANIFEST_VERSION = 3
TRANSFER_STATE_VERSION = 1
SPOTIFY_TRACK_URI = re.compile(r"^spotify:track:([A-Za-z0-9]{22})$")
SPOTIFY_TRACK_URL = re.compile(
    r"^https://open\.spotify\.com/track/([A-Za-z0-9]{22})(?:\?.*)?$"
)
ResultT = TypeVar("ResultT")


def default_matching_knowledge_path() -> Path:
    """Return a private, user-local path outside the repository."""
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "djsupport" / "matching-knowledge.json"


class TransferMode(str, Enum):
    SNAPSHOT = "snapshot"
    MIRROR = "mirror"


class DriftResolution(str, Enum):
    RESTORE = "restore"
    REVOKE = "revoke"


class MirrorDisposition(str, Enum):
    KEEP = "keep"
    RELINK = "relink"
    DELETE = "delete"


@dataclass(frozen=True)
class TransferRequest:
    """Everything an adapter must provide to start one Transfer."""

    source: str
    mode: TransferMode | None = None
    preview: bool = False
    threshold: int = 80
    retry: bool = False
    retry_days: int = 7
    playlist_prefix: str | None = "djsupport"
    transfer_id: str | None = None
    drift_resolution: DriftResolution | None = None
    mirror_disposition: MirrorDisposition | None = None
    mirror_playlist_id: str | None = None

class TransferStatus(str, Enum):
    MATCHING = "matching"
    PAUSED = "paused"
    RETAINING_PUBLICATION = "retaining publication"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class ApprovalStatus(str, Enum):
    APPROVED = "approved"
    ABANDONED = "abandoned"
    NEEDS_REVIEW = "needs review"


@dataclass(frozen=True)
class RetryPolicy:
    """Bound retries for transient Spotify failures and short rate limits."""

    max_attempts: int = 3
    backoff_seconds: float = 1.0
    max_rate_limit_wait: int = MAX_RATE_LIMIT_WAIT
    sleep: Callable[[float], None] = time.sleep

    def run(self, operation: Callable[[], ResultT]) -> ResultT:
        for attempt in range(1, self.max_attempts + 1):
            try:
                return operation()
            except spotipy.SpotifyException as exc:
                retryable_error: Exception = exc
                status = exc.http_status
                if status == 429:
                    delay = _parse_retry_after(exc)
                    if delay > self.max_rate_limit_wait:
                        raise RateLimitError(delay) from exc
                elif status is not None and status >= 500:
                    delay = self.backoff_seconds * (2 ** (attempt - 1))
                else:
                    raise
            except (requests.Timeout, requests.ConnectionError) as exc:
                retryable_error = exc
                delay = self.backoff_seconds * (2 ** (attempt - 1))
            if attempt == self.max_attempts:
                raise retryable_error
            self.sleep(delay)
        raise AssertionError("unreachable")


class PublishingTransferConflict(RuntimeError):
    """Raised when another publishing Transfer owns an account guard."""


class SourceNotFound(ValueError):
    """Raised only when an exact requested source selection does not exist."""


class AccountPublishingGuards:
    """Serialize publishing Transfers across processes by Spotify account."""

    def __init__(self, lock_directory: str | Path | None = None) -> None:
        self.lock_directory = Path(
            lock_directory
            or Path(tempfile.gettempdir()) / "djsupport-publishing-locks"
        )

    @contextmanager
    def acquire(self, account_id: str):
        account_key = hashlib.sha256(account_id.encode()).hexdigest()
        self.lock_directory.mkdir(parents=True, exist_ok=True)
        lock_file = (self.lock_directory / f"{account_key}.lock").open("a+b")
        try:
            self._lock(lock_file)
        except OSError:
            lock_file.close()
            raise PublishingTransferConflict(
                f"A publishing Transfer is already active for {account_id}"
            ) from None
        try:
            yield
        finally:
            self._unlock(lock_file)
            lock_file.close()

    @staticmethod
    def _lock(lock_file) -> None:
        if os.name == "nt":
            lock_file.seek(0)
            if not lock_file.read(1):
                lock_file.write(b"0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock(lock_file) -> None:
        if os.name == "nt":
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


@dataclass
class TransferState:
    """Mutable, versioned checkpoint for one durable Transfer."""

    status: TransferStatus
    source: str
    account_id: str
    request: dict
    selection: dict
    created_at: str
    next_track_index: int
    matched: list[dict]
    unmatched: list[str]
    publication_items: list[dict]
    alternatives: list[dict]
    spotify_playlist_id: str | None = None
    spotify_playlist_name: str | None = None
    publication_manifest: dict | None = None
    outcome: str | None = None

    @classmethod
    def from_dict(cls, value: dict) -> TransferState:
        return cls(**{
            "alternatives": [], **value,
            "status": TransferStatus(value["status"]),
        })


@dataclass(frozen=True)
class SourceSelection:
    """One named selection returned by a source adapter."""

    name: str
    reference: str
    tracks: list[Track]


@dataclass(frozen=True)
class PublicationItem:
    """One exact source-to-Spotify proposal published for review."""

    source_track_id: str
    source_name: str
    source_artist: str
    source_title: str
    spotify_uri: str
    spotify_name: str
    spotify_artist: str
    score: float
    match_type: str
    source_duration: int = 0
    authoritative: bool = False


@dataclass(frozen=True)
class PublicationManifest:
    """The durable facts needed to review one Provisional Playlist."""

    account_id: str
    spotify_playlist_id: str
    spotify_playlist_name: str
    source_label: str
    source_reference: str
    created_at: datetime
    items: tuple[PublicationItem, ...]
    mode: TransferMode = TransferMode.SNAPSHOT
    managed_items: tuple[PublicationItem, ...] = ()


@dataclass(frozen=True)
class MirrorRelationship:
    """An Approved, account-owned relationship to one source playlist."""

    account_id: str
    source_label: str
    source_reference: str
    spotify_playlist_id: str
    spotify_playlist_name: str
    approved_at: datetime
    orphaned_at: datetime | None = None


@dataclass(frozen=True)
class ApprovalOutcome:
    """The durable outcome of approving one Provisional Playlist."""

    account_id: str
    spotify_playlist_id: str
    reviewed_at: datetime
    status: ApprovalStatus
    approved: tuple[PublicationItem, ...] = ()
    rejected: tuple[PublicationItem, ...] = ()
    collisions: tuple[PublicationItem, ...] = ()
    corrections: tuple[PublicationItem, ...] = ()
    conflicts: tuple[ApprovalConflict, ...] = ()


@dataclass(frozen=True)
class ApprovalConflict:
    source_artist: str
    source_title: str
    source_duration: int
    approved_spotify_uri: str
    proposed_spotify_uri: str


class SourceAdapter(Protocol):
    source_label: str

    def consume(self, reference: str) -> SourceSelection: ...


class SpotifyAdapter(Protocol):
    def account_id(self) -> str: ...

    def match(self, track: Track, threshold: int) -> dict | None: ...

    def publish_provisional_snapshot(
        self, name: str, track_uris: list[str], description: str,
        publication_key: str,
    ) -> str: ...

    def delete_provisional_snapshot(self, playlist_id: str) -> None: ...

    def delete_playlist(self, playlist_id: str) -> None: ...

    def provisional_playlist_track_uris(
        self, playlist_id: str,
    ) -> list[str] | None: ...

    def replace_provisional_playlist_tracks(
        self, playlist_id: str, track_uris: list[str],
    ) -> None: ...

    def spotify_track(self, uri: str) -> dict: ...


class PublicationStorage(Protocol):
    def retain_publication(self, manifest: PublicationManifest) -> None: ...

    def publication_for_playlist(
        self, account_id: str, playlist_id: str,
    ) -> PublicationManifest | None: ...

    def retain_approval(self, outcome: ApprovalOutcome) -> None: ...

    def retain_mirror(self, relationship: MirrorRelationship) -> None: ...

    def mirror_for_source(
        self, account_id: str, source_label: str, source_reference: str,
    ) -> MirrorRelationship | None: ...

    def mirror_for_playlist(
        self, account_id: str, playlist_id: str,
    ) -> MirrorRelationship | None: ...

    def replace_mirror(
        self, previous: MirrorRelationship, replacement: MirrorRelationship,
    ) -> None: ...

    def remove_mirror(self, relationship: MirrorRelationship) -> None: ...


class FilePublicationStorage:
    """Versioned, durable publication manifests for later review."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.manifests: list[dict] = []
        self.approvals: list[dict] = []
        self.mirrors: list[dict] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        if data.get("version") not in (1, 2, PUBLICATION_MANIFEST_VERSION):
            return
        self.manifests = data.get("manifests", [])
        self.approvals = data.get("approvals", data.get("reviews", []))
        self.mirrors = data.get("mirrors", [])

    def _save(self, manifests: list[dict], approvals: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(json.dumps({
            "version": PUBLICATION_MANIFEST_VERSION,
            "manifests": manifests,
            "approvals": approvals,
            "mirrors": self.mirrors,
        }, indent=2))
        os.replace(temporary, self.path)
        self.manifests = manifests
        self.approvals = approvals

    def retain_publication(self, manifest: PublicationManifest) -> None:
        stored = asdict(manifest)
        stored["created_at"] = manifest.created_at.isoformat()
        next_manifests = [
            item for item in self.manifests
            if not (
                item.get("account_id") == manifest.account_id
                and item.get("spotify_playlist_id") == manifest.spotify_playlist_id
            )
        ]
        next_manifests.append(stored)
        self._save(next_manifests, self.approvals)

    def manifests_for_account(self, account_id: str) -> list[dict]:
        """Return only playlist-management state owned by one account."""
        return [
            manifest for manifest in self.manifests
            if manifest.get("account_id") == account_id
        ]

    def publication_for_playlist(
        self, account_id: str, playlist_id: str,
    ) -> PublicationManifest | None:
        stored = next((
            manifest for manifest in self.manifests
            if manifest.get("account_id") == account_id
            and manifest.get("spotify_playlist_id") == playlist_id
        ), None)
        if stored is None:
            return None
        return PublicationManifest(
            **{
                **stored,
                "mode": TransferMode(
                    stored.get("mode", TransferMode.SNAPSHOT.value)
                ),
                "created_at": datetime.fromisoformat(stored["created_at"]),
                "items": tuple(PublicationItem(**item) for item in stored["items"]),
                "managed_items": tuple(
                    PublicationItem(**item)
                    for item in stored.get("managed_items", stored["items"])
                ),
            }
        )

    def retain_approval(self, outcome: ApprovalOutcome) -> None:
        stored = asdict(outcome)
        stored["reviewed_at"] = outcome.reviewed_at.isoformat()
        self._save(self.manifests, [*self.approvals, stored])

    def retain_mirror(self, relationship: MirrorRelationship) -> None:
        stored = asdict(relationship)
        stored["approved_at"] = relationship.approved_at.isoformat()
        stored["orphaned_at"] = (
            relationship.orphaned_at.isoformat()
            if relationship.orphaned_at else None
        )
        self.mirrors = [
            item for item in self.mirrors
            if not (
                item.get("account_id") == relationship.account_id
                and item.get("source_label") == relationship.source_label
                and item.get("source_reference") == relationship.source_reference
            )
        ]
        self.mirrors.append(stored)
        self._save(self.manifests, self.approvals)

    def mirrors_for_account(self, account_id: str) -> list[MirrorRelationship]:
        return [
            MirrorRelationship(**{
                **item,
                "approved_at": datetime.fromisoformat(item["approved_at"]),
                "orphaned_at": (
                    datetime.fromisoformat(item["orphaned_at"])
                    if item.get("orphaned_at") else None
                ),
            })
            for item in self.mirrors
            if item.get("account_id") == account_id
        ]

    def mirror_for_source(
        self, account_id: str, source_label: str, source_reference: str,
    ) -> MirrorRelationship | None:
        return next((
            mirror for mirror in self.mirrors_for_account(account_id)
            if mirror.source_label == source_label
            and mirror.source_reference == source_reference
        ), None)

    def mirror_for_playlist(
        self, account_id: str, playlist_id: str,
    ) -> MirrorRelationship | None:
        return next((
            mirror for mirror in self.mirrors_for_account(account_id)
            if mirror.spotify_playlist_id == playlist_id
        ), None)

    def replace_mirror(
        self, previous: MirrorRelationship, replacement: MirrorRelationship,
    ) -> None:
        self.mirrors = [
            item for item in self.mirrors
            if not (
                item.get("account_id") == previous.account_id
                and item.get("spotify_playlist_id") == previous.spotify_playlist_id
            )
        ]
        self.retain_mirror(replacement)

    def remove_mirror(self, relationship: MirrorRelationship) -> None:
        self.mirrors = [
            item for item in self.mirrors
            if not (
                item.get("account_id") == relationship.account_id
                and item.get("spotify_playlist_id")
                == relationship.spotify_playlist_id
            )
        ]
        self._save(self.manifests, self.approvals)


class TransferStorage(Protocol):
    def load_transfer(self, transfer_id: str) -> TransferState | None: ...

    def save_transfer(self, transfer_id: str, state: TransferState) -> None: ...


class FileTransferStorage:
    """Atomically persisted, versioned state for resumable Transfers."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.transfers: dict[str, TransferState] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        if data.get("version") == TRANSFER_STATE_VERSION:
            for transfer_id, state in data.get("transfers", {}).items():
                try:
                    self.transfers[transfer_id] = TransferState.from_dict(state)
                except (KeyError, TypeError, ValueError):
                    continue

    def load_transfer(self, transfer_id: str) -> TransferState | None:
        return self.transfers.get(transfer_id)

    def save_transfer(self, transfer_id: str, state: TransferState) -> None:
        next_transfers = {**self.transfers, transfer_id: state}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(json.dumps({
            "version": TRANSFER_STATE_VERSION,
            "transfers": {
                key: asdict(transfer) for key, transfer in next_transfers.items()
            },
        }, indent=2))
        os.replace(temporary, self.path)
        self.transfers = next_transfers


def default_publication_manifest_path() -> Path:
    return default_matching_knowledge_path().with_name("publication-manifests.json")


class MatchingKnowledge(Protocol):
    def lookup(self, track: Track, threshold: int) -> dict | None: ...

    def should_retry(
        self, track: Track, threshold: int, retry_days: int, force: bool,
    ) -> bool: ...

    def retain(self, track: Track, threshold: int, result: dict | None) -> None: ...

    def checkpoint(self) -> None: ...

    def approve(self, item: PublicationItem) -> ApprovalConflict | None: ...

    def reject(self, item: PublicationItem) -> None: ...

    def correct(self, item: PublicationItem) -> ApprovalConflict | None: ...

    def revoke(self, item: PublicationItem) -> None: ...


class BeatportChartSource:
    """Production source adapter for one Beatport chart."""

    source_label = "Beatport"
    default_mode = TransferMode.SNAPSHOT

    def consume(self, reference: str) -> SourceSelection:
        from djsupport.beatport import (
            compose_chart_playlist_name,
            fetch_chart,
            validate_url,
        )

        url = validate_url(reference)
        chart_name, curator, tracks = fetch_chart(url)
        return SourceSelection(
            name=compose_chart_playlist_name(chart_name, curator),
            reference=url,
            tracks=tracks,
        )


class BeatportLabelSource:
    """Production source adapter for one Beatport record-label selection."""

    source_label = "Beatport label"
    default_mode = TransferMode.SNAPSHOT

    def __init__(
        self,
        *,
        fetcher: Callable[[str], tuple[str, list[Track]]] | None = None,
        validator: Callable[[str], str] | None = None,
        on_deduplicated: Callable[[int, int], None] | None = None,
    ) -> None:
        self._fetcher = fetcher
        self._validator = validator
        self._on_deduplicated = on_deduplicated

    def consume(self, reference: str) -> SourceSelection:
        from djsupport.label import (
            deduplicate_tracks,
            fetch_label_tracks,
            validate_label_url,
        )

        url = (self._validator or validate_label_url)(reference)
        label_name, tracks = (self._fetcher or fetch_label_tracks)(url)
        unique_tracks, duplicates_removed = deduplicate_tracks(tracks)
        if self._on_deduplicated is not None:
            self._on_deduplicated(duplicates_removed, len(unique_tracks))
        return SourceSelection(label_name, url, unique_tracks)


class RekordboxPlaylistSource:
    """Fixture-friendly intake for one explicitly selected Rekordbox playlist."""

    source_label = "Rekordbox"
    default_mode = TransferMode.MIRROR

    def __init__(self, xml_path: str | Path) -> None:
        self._xml_path = Path(xml_path)

    def consume(self, reference: str) -> SourceSelection:
        from djsupport.rekordbox import parse_xml

        tracks, playlists = parse_xml(self._xml_path)
        selected = [
            playlist for playlist in playlists
            if playlist.path == reference or playlist.name == reference
        ]
        if not selected:
            raise SourceNotFound(f"Rekordbox playlist not found: {reference}")
        if len(selected) > 1:
            raise ValueError(
                f"Rekordbox playlist name is ambiguous; select its path: {reference}"
            )
        playlist = selected[0]
        missing_track_ids = [
            track_id for track_id in playlist.track_ids if track_id not in tracks
        ]
        if missing_track_ids:
            raise ValueError(
                "Rekordbox playlist has missing track references: "
                + ", ".join(missing_track_ids)
            )
        return SourceSelection(
            playlist.name,
            playlist.path,
            [tracks[track_id] for track_id in playlist.track_ids],
        )


class SpotifyMatcher:
    """Production Spotify matching and Transfer publication adapter."""

    def __init__(self, client) -> None:
        self._client = client

    def account_id(self) -> str:
        return self._client.current_user()["id"]

    def match(self, track: Track, threshold: int) -> dict | None:
        return match_track_with_alternatives(
            self._client, track, threshold=threshold,
        )

    def publish_provisional_snapshot(
        self, name: str, track_uris: list[str], description: str,
        publication_key: str,
    ) -> str:
        # This marker is the durable identity contract for recurring Mirrors.
        # It lives with the Spotify playlist, so a new process/client can find
        # the relationship without depending on process-local state.
        marker = f"djsupport-transfer:{publication_key}"
        description = f"{description} {marker}"
        playlist_id = self._find_publication(marker)
        if playlist_id is None:
            playlist = self._client.user_playlist_create(
                self.account_id(), name, public=False, description=description,
            )
            playlist_id = playlist["id"]
        try:
            if track_uris:
                self._client.playlist_replace_items(playlist_id, track_uris[:100])
                for offset in range(100, len(track_uris), 100):
                    self._client.playlist_add_items(
                        playlist_id, track_uris[offset:offset + 100],
                    )
            else:
                self._client.playlist_replace_items(playlist_id, [])
        except Exception:
            self.delete_provisional_snapshot(playlist_id)
            raise
        return playlist_id

    def _find_publication(self, marker: str) -> str | None:
        page = self._client.current_user_playlists(limit=50)
        while page:
            for playlist in page.get("items", []):
                if marker in (playlist.get("description") or ""):
                    return playlist["id"]
            if not page.get("next"):
                break
            page = self._client.next(page)
        return None

    def delete_provisional_snapshot(self, playlist_id: str) -> None:
        self._client.current_user_unfollow_playlist(playlist_id)

    def delete_playlist(self, playlist_id: str) -> None:
        self._client.current_user_unfollow_playlist(playlist_id)

    def provisional_playlist_track_uris(self, playlist_id: str) -> list[str] | None:
        try:
            page = self._client.playlist_items(playlist_id)
        except spotipy.SpotifyException as exc:
            if exc.http_status == 404:
                return None
            raise
        uris: list[str] = []
        while page:
            for item in page.get("items", []):
                track = item.get("track") or {}
                if track.get("uri"):
                    uris.append(track["uri"])
            if not page.get("next"):
                break
            page = self._client.next(page)
        return uris

    def replace_provisional_playlist_tracks(
        self, playlist_id: str, track_uris: list[str],
    ) -> None:
        self._client.playlist_replace_items(playlist_id, track_uris[:100])
        for offset in range(100, len(track_uris), 100):
            self._client.playlist_add_items(
                playlist_id, track_uris[offset:offset + 100],
            )

    def spotify_track(self, uri: str) -> dict:
        track = self._client.track(uri)
        return {
            "uri": track["uri"],
            "name": track["name"],
            "artist": ", ".join(artist["name"] for artist in track["artists"]),
        }


class MatchCacheKnowledge:
    """Expose the existing durable match cache as Transfer storage."""

    persistent = True

    def __init__(self, cache: MatchCache) -> None:
        self._cache = cache

    def lookup(self, track: Track, threshold: int) -> dict | None:
        entry = self._cache.lookup(
            track.artist, track.name, threshold, track.duration,
        )
        if entry is None or not entry.matched:
            return None
        return {
            "uri": entry.spotify_uri,
            "name": entry.spotify_name,
            "artist": entry.spotify_artist,
            "score": entry.score,
            "match_type": entry.match_type or "exact",
            "authoritative": entry.approval_status == "approved",
        }

    def should_retry(
        self, track: Track, threshold: int, retry_days: int, force: bool,
    ) -> bool:
        entry = self._cache.lookup(
            track.artist, track.name, threshold, track.duration,
        )
        if entry is None:
            return True
        if entry.matched:
            return False
        return force

    def retain(self, track: Track, threshold: int, result: dict | None) -> None:
        self._cache.store(track.artist, track.name, threshold, result)

    def checkpoint(self) -> None:
        self._cache.save()

    def approve(self, item: PublicationItem) -> ApprovalConflict | None:
        conflict = self._cache.record_approval(
            item.source_artist, item.source_title, ApprovalStatus.APPROVED.value,
            {
                "uri": item.spotify_uri,
                "name": item.spotify_name,
                "artist": item.spotify_artist,
                "score": item.score,
                "match_type": item.match_type,
            }, item.source_duration,
        )
        return ApprovalConflict(**conflict) if conflict else None

    def reject(self, item: PublicationItem) -> None:
        self._cache.record_approval(
            item.source_artist, item.source_title, "rejected",
            {
                "uri": item.spotify_uri,
                "name": item.spotify_name,
                "artist": item.spotify_artist,
                "score": item.score,
                "match_type": item.match_type,
            }, item.source_duration,
        )

    def correct(self, item: PublicationItem) -> ApprovalConflict | None:
        conflict = self.approve(item)
        if conflict is not None:
            return conflict
        self._cache.record_correction({
            "source_track_id": item.source_track_id,
            "source_artist": item.source_artist,
            "source_title": item.source_title,
            "spotify_uri": item.spotify_uri,
            "spotify_name": item.spotify_name,
            "spotify_artist": item.spotify_artist,
        })
        return None

    def revoke(self, item: PublicationItem) -> None:
        self._cache.revoke_approval(
            item.source_artist, item.source_title, item.source_duration,
        )


class EphemeralMatchingKnowledge:
    """Non-persistent matching knowledge used for explicit ``--no-cache``."""

    persistent = False

    def lookup(self, track: Track, threshold: int) -> dict | None:
        return None

    def should_retry(
        self, track: Track, threshold: int, retry_days: int, force: bool,
    ) -> bool:
        return True

    def retain(self, track: Track, threshold: int, result: dict | None) -> None:
        pass

    def checkpoint(self) -> None:
        pass

    def approve(self, item: PublicationItem) -> None:
        pass

    def reject(self, item: PublicationItem) -> None:
        pass

    def correct(self, item: PublicationItem) -> None:
        pass

    def revoke(self, item: PublicationItem) -> None:
        pass


class Transfer:
    """Coordinate a Transfer through source, Spotify, and storage seams."""

    def __init__(
        self,
        *,
        source: SourceAdapter,
        spotify: SpotifyAdapter,
        matching_knowledge: MatchingKnowledge,
        publishing_guards: AccountPublishingGuards,
        publication_storage: PublicationStorage | None = None,
        transfer_storage: TransferStorage | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._source = source
        self._spotify = spotify
        self._knowledge = matching_knowledge
        self._publishing_guards = publishing_guards
        self._publication_storage = publication_storage
        self._transfer_storage = transfer_storage
        self._retry_policy = retry_policy or RetryPolicy()
        self._pause_requested = False

    def pause(self) -> None:
        """Request a pause after the current track reaches a safe checkpoint."""
        self._pause_requested = True

    def abandon(self, transfer_id: str) -> None:
        """Explicitly make a persisted, non-completed Transfer terminal."""
        if self._transfer_storage is None:
            raise ValueError("Abandonment requires durable Transfer storage")
        state = self._transfer_storage.load_transfer(transfer_id)
        if state is None:
            raise ValueError(f"Unknown Transfer: {transfer_id}")
        if state.status == TransferStatus.COMPLETED:
            raise ValueError("A completed Transfer cannot be abandoned")
        if state.account_id != self._spotify.account_id():
            raise ValueError("A Transfer cannot be abandoned under another Spotify account")
        state.status = TransferStatus.ABANDONED
        self._transfer_storage.save_transfer(transfer_id, state)

    def approve(
        self, playlist_id: str, *, corrections: str | Path | None = None,
    ) -> ApprovalOutcome:
        """Review exactly one retained Provisional Playlist against Spotify."""
        if self._publication_storage is None:
            raise ValueError("Approval requires publication storage")
        account_id = self._spotify.account_id()
        manifest = self._publication_storage.publication_for_playlist(
            account_id, playlist_id,
        )
        if manifest is None:
            raise ValueError(
                f"No Provisional Playlist {playlist_id} belongs to this Spotify account"
            )
        with self._publishing_guards.acquire(account_id):
            corrected_items = self._read_corrections(corrections, manifest)
            current_uris = self._retry_policy.run(
                lambda: self._spotify.provisional_playlist_track_uris(playlist_id)
            )
            if current_uris is None:
                outcome = ApprovalOutcome(
                    account_id=account_id,
                    spotify_playlist_id=playlist_id,
                    reviewed_at=datetime.now(),
                    status=ApprovalStatus.ABANDONED,
                )
            else:
                if corrected_items:
                    current_uris = self._repair_corrections(
                        playlist_id, manifest, current_uris, corrected_items,
                    )
                remaining = Counter(current_uris)
                approved: list[PublicationItem] = []
                rejected: list[PublicationItem] = []
                reviewed_items = tuple(
                    corrected_items.get(item.source_track_id, item)
                    for item in manifest.items
                )
                proposed_counts = Counter(item.spotify_uri for item in reviewed_items)
                collision_uris = {
                    uri for uri, count in proposed_counts.items() if count > 1
                }
                collisions: list[PublicationItem] = []
                for item in reviewed_items:
                    if item.spotify_uri in collision_uris:
                        collisions.append(item)
                        continue
                    if remaining[item.spotify_uri] > 0:
                        approved.append(item)
                        remaining[item.spotify_uri] -= 1
                    else:
                        rejected.append(item)
                outcome = ApprovalOutcome(
                    account_id=account_id,
                    spotify_playlist_id=playlist_id,
                    reviewed_at=datetime.now(),
                    status=(
                        ApprovalStatus.NEEDS_REVIEW
                        if collisions else ApprovalStatus.APPROVED
                    ),
                    approved=tuple(approved),
                    rejected=tuple(rejected),
                    collisions=tuple(collisions),
                    corrections=tuple(
                        item for item in approved
                        if item.source_track_id in corrected_items
                    ),
                )
                conflicts: list[ApprovalConflict] = []
                for item in outcome.approved:
                    if item.source_track_id in corrected_items:
                        conflict = self._knowledge.correct(item)
                    else:
                        conflict = self._knowledge.approve(item)
                    if conflict is not None:
                        conflicts.append(conflict)
                for item in outcome.rejected:
                    self._knowledge.reject(item)
                if conflicts:
                    conflict_identities = {
                        (item.source_artist, item.source_title, item.source_duration)
                        for item in conflicts
                    }
                    outcome = replace(
                        outcome,
                        status=ApprovalStatus.NEEDS_REVIEW,
                        approved=tuple(item for item in outcome.approved if (
                            item.source_artist, item.source_title,
                            item.source_duration,
                        ) not in conflict_identities),
                        corrections=tuple(item for item in outcome.corrections if (
                            item.source_artist, item.source_title,
                            item.source_duration,
                        ) not in conflict_identities),
                        conflicts=tuple(conflicts),
                    )
                self._knowledge.checkpoint()
                if (
                    outcome.status == ApprovalStatus.APPROVED
                    and manifest.mode == TransferMode.MIRROR
                ):
                    self._publication_storage.retain_mirror(MirrorRelationship(
                        account_id=account_id,
                        source_label=manifest.source_label,
                        source_reference=manifest.source_reference,
                        spotify_playlist_id=manifest.spotify_playlist_id,
                        spotify_playlist_name=manifest.spotify_playlist_name,
                        approved_at=outcome.reviewed_at,
                    ))
            self._publication_storage.retain_approval(outcome)
            return outcome

    def _read_corrections(
        self, corrections: str | Path | None, manifest: PublicationManifest,
    ) -> dict[str, PublicationItem]:
        if corrections is None:
            return {}
        source_reference_counts = Counter(
            item.source_track_id for item in manifest.items
        )
        manifest_items = {item.source_track_id: item for item in manifest.items}
        corrected: dict[str, PublicationItem] = {}
        seen_source_references: set[str] = set()
        with Path(corrections).open(newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            required = {"source_track_id", "spotify_url"}
            if not required.issubset(reader.fieldnames or ()):
                raise ValueError(
                    "Correction CSV requires source_track_id and spotify_url columns"
                )
            for row_number, row in enumerate(reader, start=2):
                source_track_id = (row.get("source_track_id") or "").strip()
                spotify_reference = (row.get("spotify_url") or "").strip()
                if not spotify_reference:
                    continue
                if not source_track_id or source_track_id not in manifest_items:
                    raise ValueError(
                        f"Correction row {row_number} has an unknown source_track_id"
                    )
                if source_reference_counts[source_track_id] != 1:
                    raise ValueError(
                        f"Correction row {row_number} source_track_id "
                        f"{source_track_id} is not a unique stable source reference"
                    )
                if source_track_id in seen_source_references:
                    raise ValueError(
                        f"Correction row {row_number} repeats source_track_id "
                        f"{source_track_id}"
                    )
                seen_source_references.add(source_track_id)
                original = manifest_items[source_track_id]
                if spotify_reference == original.spotify_uri:
                    continue
                spotify_uri = self._spotify_uri(spotify_reference, row_number)
                if spotify_uri == original.spotify_uri:
                    continue
                spotify_track = self._retry_policy.run(
                    lambda uri=spotify_uri: self._spotify.spotify_track(uri)
                )
                if spotify_track.get("uri") != spotify_uri:
                    raise ValueError(
                        f"Correction row {row_number} did not resolve to its Spotify track"
                    )
                corrected[source_track_id] = replace(
                    original,
                    spotify_uri=spotify_uri,
                    spotify_name=spotify_track["name"],
                    spotify_artist=spotify_track["artist"],
                    score=100.0,
                    match_type="correction",
                )
        return corrected

    @staticmethod
    def _spotify_uri(reference: str, row_number: int) -> str:
        uri_match = SPOTIFY_TRACK_URI.fullmatch(reference)
        if uri_match:
            return reference
        url_match = SPOTIFY_TRACK_URL.fullmatch(reference)
        if url_match:
            return f"spotify:track:{url_match.group(1)}"
        raise ValueError(
            f"Correction row {row_number} has an invalid Spotify track URL or URI"
        )

    def _repair_corrections(
        self,
        playlist_id: str,
        manifest: PublicationManifest,
        current_uris: list[str],
        corrected_items: dict[str, PublicationItem],
    ) -> list[str]:
        original_uris = {item.spotify_uri for item in manifest.items}
        corrected_uris = {item.spotify_uri for item in corrected_items.values()}
        managed_uris = original_uris | corrected_uris
        present = Counter(current_uris)
        desired = []
        for item in manifest.items:
            correction = corrected_items.get(item.source_track_id)
            if correction is not None:
                if correction.spotify_uri not in desired:
                    desired.append(correction.spotify_uri)
            elif present[item.spotify_uri] and item.spotify_uri not in desired:
                desired.append(item.spotify_uri)

        first_managed = next(
            (index for index, uri in enumerate(current_uris) if uri in managed_uris),
            0,
        )
        manual = [uri for uri in current_uris if uri not in managed_uris]
        insertion = sum(
            1 for uri in current_uris[:first_managed] if uri not in managed_uris
        )
        repaired = [*manual[:insertion], *desired, *manual[insertion:]]
        if repaired != current_uris:
            self._retry_policy.run(
                lambda: self._spotify.replace_provisional_playlist_tracks(
                    playlist_id, repaired,
                )
            )
        return repaired

    def execute(self, request: TransferRequest) -> SyncReport:
        """Execute at most one publishing Transfer per Spotify account."""
        if request.preview:
            if request.mirror_disposition is not None:
                raise ValueError("Mirror dispositions are not available in Preview")
            return self._execute(request)
        if self._publication_storage is None:
            raise ValueError("Publishing Transfers require publication storage")
        account_id = self._spotify.account_id()
        with self._publishing_guards.acquire(account_id):
            return self._execute(request)

    def _execute(self, request: TransferRequest) -> SyncReport:
        """Execute one Transfer and return its structured outcome.

        Beatport publication creates a distinct Provisional Snapshot after the
        complete selection has matched safely.
        """
        if not request.preview and self._publication_storage is None:
            raise ValueError("Publishing Transfers require publication storage")

        if request.mode is None:
            # Older internal/test adapters predate source-owned mode policy.
            request = replace(
                request,
                mode=getattr(self._source, "default_mode", TransferMode.SNAPSHOT),
            )

        transfer_id = request.transfer_id or uuid4().hex
        state = (
            self._transfer_storage.load_transfer(transfer_id)
            if self._transfer_storage is not None else None
        )
        if state is None:
            try:
                selection = self._source.consume(request.source)
            except SourceNotFound:
                relationship = (
                    self._publication_storage.mirror_for_source(
                        self._spotify.account_id(), self._source.source_label,
                        request.source,
                    )
                    if self._publication_storage is not None else None
                )
                if request.mode == TransferMode.MIRROR and relationship is not None:
                    if not request.preview:
                        assert self._publication_storage is not None
                        relationship = replace(
                            relationship, orphaned_at=datetime.now(),
                        )
                        self._publication_storage.retain_mirror(relationship)
                    action = "disposition required"
                    status = "orphaned mirror"
                    if request.mirror_disposition == MirrorDisposition.KEEP:
                        assert self._publication_storage is not None
                        self._publication_storage.remove_mirror(relationship)
                        action = "mirror kept as ordinary playlist"
                        status = "completed"
                    elif request.mirror_disposition == MirrorDisposition.DELETE:
                        self._retry_policy.run(
                            lambda: self._spotify.delete_playlist(
                                relationship.spotify_playlist_id
                            )
                        )
                        assert self._publication_storage is not None
                        self._publication_storage.remove_mirror(relationship)
                        action = "mirror explicitly deleted"
                        status = "completed"
                    return SyncReport(
                        timestamp=datetime.now(), threshold=request.threshold,
                        dry_run=request.preview,
                        playlists=[PlaylistReport(
                            name=relationship.spotify_playlist_name,
                            path=relationship.source_reference,
                            action=action,
                            spotify_playlist_id=relationship.spotify_playlist_id,
                            mirror_dispositions=tuple(
                                choice.value for choice in MirrorDisposition
                            ),
                            mirror_disposition=(
                                request.mirror_disposition.value
                                if request.mirror_disposition else None
                            ),
                        )],
                        cache_enabled=getattr(self._knowledge, "persistent", True),
                        source_label=self._source.source_label,
                        transfer_id=transfer_id,
                        status=status,
                    )
                raise
            relinked_mirror = None
            if request.mirror_disposition == MirrorDisposition.RELINK:
                if request.mode != TransferMode.MIRROR or not request.mirror_playlist_id:
                    raise ValueError(
                        "Relinking requires Mirror mode and an explicit Spotify playlist ID"
                    )
                assert self._publication_storage is not None
                relinked_mirror = self._publication_storage.mirror_for_playlist(
                    self._spotify.account_id(), request.mirror_playlist_id,
                )
                if relinked_mirror is None:
                    raise ValueError(
                        "The Mirror to relink does not belong to this Spotify account"
                    )
            created_at = datetime.now()
            state = TransferState(
                status=TransferStatus.MATCHING,
                source=request.source,
                account_id=self._spotify.account_id(),
                request={
                    "source": request.source,
                    "mode": request.mode.value,
                    "preview": request.preview,
                    "threshold": request.threshold,
                    "retry": request.retry,
                    "retry_days": request.retry_days,
                    "playlist_prefix": request.playlist_prefix,
                    "drift_resolution": (
                        request.drift_resolution.value
                        if request.drift_resolution else None
                    ),
                    "mirror_disposition": (
                        request.mirror_disposition.value
                        if request.mirror_disposition else None
                    ),
                    "mirror_playlist_id": request.mirror_playlist_id,
                },
                selection={
                    "name": selection.name,
                    "reference": selection.reference,
                    "tracks": [asdict(track) for track in selection.tracks],
                },
                created_at=created_at.isoformat(),
                next_track_index=0,
                matched=[],
                unmatched=[],
                publication_items=[],
                alternatives=[],
                spotify_playlist_id=(
                    relinked_mirror.spotify_playlist_id if relinked_mirror else None
                ),
                spotify_playlist_name=(
                    relinked_mirror.spotify_playlist_name if relinked_mirror else None
                ),
            )
            self._save_transfer(transfer_id, state)
        else:
            if state.status == TransferStatus.ABANDONED:
                raise ValueError(f"Transfer {transfer_id} was abandoned")
            if state.source != request.source:
                raise ValueError("A resumed Transfer must use its original source")
            if state.account_id != self._spotify.account_id():
                raise ValueError("A Transfer cannot resume under another Spotify account")
            request = TransferRequest(
                **{
                    **state.request,
                    "mode": TransferMode(
                        state.request.get("mode", TransferMode.SNAPSHOT.value)
                    ),
                    "drift_resolution": (
                        DriftResolution(state.request["drift_resolution"])
                        if state.request.get("drift_resolution") else None
                    ),
                    "mirror_disposition": (
                        MirrorDisposition(state.request["mirror_disposition"])
                        if state.request.get("mirror_disposition") else None
                    ),
                },
                transfer_id=transfer_id,
            )
            stored_selection = state.selection
            selection = SourceSelection(
                stored_selection["name"], stored_selection["reference"],
                [Track(**track) for track in stored_selection["tracks"]],
            )
            created_at = datetime.fromisoformat(state.created_at)

        playlist = PlaylistReport(
            name=selection.name,
            path=selection.reference,
            action="preview" if request.preview else "pending publication",
        )
        report = SyncReport(
            timestamp=created_at,
            threshold=request.threshold,
            dry_run=request.preview,
            playlists=[playlist],
            cache_enabled=getattr(self._knowledge, "persistent", True),
            source_label=self._source.source_label,
            transfer_id=transfer_id,
            status=state.status.value,
        )
        playlist.matched = [MatchedTrack(**item) for item in state.matched]
        playlist.unmatched = list(state.unmatched)
        playlist.alternatives = [
            UnmatchedAlternatives(
                source_track_id=item["source_track_id"],
                source_name=item["source_name"],
                candidates=tuple(
                    AlternativeCandidate(**candidate)
                    for candidate in item["candidates"]
                ),
            )
            for item in state.alternatives
        ]
        publication_items = [
            PublicationItem(**item) for item in state.publication_items
        ]
        if state.status == TransferStatus.COMPLETED:
            report.status = "completed"
            if state.spotify_playlist_id:
                playlist.name = state.spotify_playlist_name or playlist.name
                playlist.spotify_playlist_id = state.spotify_playlist_id
                playlist.action = (
                    state.outcome
                    or (
                        "provisional mirror updated"
                        if request.mode == TransferMode.MIRROR
                        else "provisional snapshot created"
                    )
                )
                stored_manifest = state.publication_manifest
                if stored_manifest:
                    playlist.publication_manifest = PublicationManifest(
                        **{
                            **stored_manifest,
                            "mode": TransferMode(
                                stored_manifest.get(
                                    "mode", TransferMode.SNAPSHOT.value,
                                )
                            ),
                            "account_id": stored_manifest.get(
                                "account_id", state.account_id,
                            ),
                            "created_at": datetime.fromisoformat(
                                stored_manifest["created_at"]
                            ),
                            "items": tuple(
                                PublicationItem(**item)
                                for item in stored_manifest["items"]
                            ),
                            "managed_items": tuple(
                                PublicationItem(**item)
                                for item in stored_manifest.get(
                                    "managed_items", stored_manifest["items"],
                                )
                            ),
                        }
                    )
            elif not request.preview and not selection.tracks:
                playlist.action = "not published: empty source"
            return report

        try:
            for index in range(state.next_track_index, len(selection.tracks)):
                track = selection.tracks[index]
                result = self._knowledge.lookup(track, request.threshold)
                if result is not None:
                    playlist.cache_hits += 1
                    if result.get("authoritative") and not self._approved_available(
                        result["uri"]
                    ):
                        playlist.unavailable_approved.append(
                            UnavailableApprovedMatch(
                                source_track_id=track.track_id,
                                source_name=track.display,
                                spotify_uri=result["uri"],
                            )
                        )
                        publication_items.append(PublicationItem(
                            source_track_id=track.track_id,
                            source_name=track.display,
                            source_artist=track.artist,
                            source_title=track.name,
                            spotify_uri=result["uri"],
                            spotify_name=result["name"],
                            spotify_artist=result["artist"],
                            score=result["score"],
                            match_type=result.get("match_type", "exact"),
                            source_duration=track.duration,
                            authoritative=True,
                        ))
                        result = None
                elif self._knowledge.should_retry(
                    track, request.threshold, request.retry_days, request.retry,
                ):
                    result = self._retry_policy.run(
                        lambda: self._spotify.match(track, request.threshold)
                    )
                    playlist.api_lookups += 1
                    self._knowledge.retain(
                        track, request.threshold,
                        None if result and "alternatives" in result else result,
                    )
                else:
                    result = None
                    playlist.cache_hits += 1

                if result is None or "alternatives" in result:
                    playlist.unmatched.append(track.display)
                    candidates = tuple(
                        AlternativeCandidate(
                            rank=rank,
                            spotify_uri=candidate["uri"],
                            spotify_name=candidate["name"],
                            spotify_artist=candidate["artist"],
                            version=candidate.get("version", "default version"),
                            duration_ms=candidate.get("duration_ms", 0),
                            score=candidate["score"],
                            score_reasons=tuple(candidate.get("score_reasons", ())),
                        )
                        for rank, candidate in enumerate(
                            (result or {}).get("alternatives", ())[:3], start=1,
                        )
                    )
                    if candidates:
                        playlist.alternatives.append(UnmatchedAlternatives(
                            source_track_id=track.track_id,
                            source_name=track.display,
                            candidates=candidates,
                        ))
                else:
                    matched_track = MatchedTrack(
                        source_name=track.display,
                        spotify_name=result["name"],
                        spotify_artist=result["artist"],
                        score=result["score"],
                        match_type=result.get("match_type", "exact"),
                        source_track_id=track.track_id,
                        spotify_uri=result["uri"],
                    )
                    playlist.matched.append(matched_track)
                    publication_items.append(PublicationItem(
                        source_track_id=track.track_id,
                        source_name=track.display,
                        source_artist=track.artist,
                        source_title=track.name,
                        spotify_uri=result["uri"],
                        spotify_name=matched_track.spotify_name,
                        spotify_artist=matched_track.spotify_artist,
                        score=matched_track.score,
                        match_type=matched_track.match_type,
                        source_duration=track.duration,
                        authoritative=bool(result.get("authoritative")),
                    ))

                state.next_track_index = index + 1
                state.matched = [asdict(item) for item in playlist.matched]
                state.unmatched = list(playlist.unmatched)
                state.alternatives = [asdict(item) for item in playlist.alternatives]
                state.publication_items = [
                    asdict(item) for item in publication_items
                ]
                self._knowledge.checkpoint()
                if self._pause_requested:
                    state.status = TransferStatus.PAUSED
                    self._save_transfer(transfer_id, state)
                    self._pause_requested = False
                    playlist.action = "paused"
                    report.status = "paused"
                    return report
                self._save_transfer(transfer_id, state)

            source_ids_by_uri: dict[str, set[tuple[str, str, int]]] = {}
            for item in publication_items:
                source_ids_by_uri.setdefault(item.spotify_uri, set()).add(
                    (
                        item.source_artist.casefold(),
                        item.source_title.casefold(),
                        item.source_duration,
                    )
                )
            collision_uris = {
                uri for uri, source_ids in source_ids_by_uri.items()
                if len(source_ids) > 1
            }
            if collision_uris:
                colliding_items = [
                    item for item in publication_items
                    if item.spotify_uri in collision_uris
                ]
                playlist.match_collisions = [
                    MatchCollision(
                        item.source_track_id, item.source_name, item.spotify_uri,
                    )
                    for item in colliding_items
                ]
                colliding_ids = {
                    item.source_track_id for item in colliding_items
                }
                playlist.matched = [
                    item for item in playlist.matched
                    if item.source_track_id not in colliding_ids
                ]
                playlist.unmatched.extend(
                    item.source_name for item in colliding_items
                    if item.source_name not in playlist.unmatched
                )
                state.matched = [asdict(item) for item in playlist.matched]
                state.unmatched = list(playlist.unmatched)

            relink_original_uris: list[str] | None = None
            if request.mode == TransferMode.MIRROR:
                assert self._publication_storage is not None or request.preview
                relationship = (
                    self._publication_storage.mirror_for_playlist(
                        state.account_id, request.mirror_playlist_id,
                    )
                    if (
                        self._publication_storage is not None
                        and request.mirror_disposition == MirrorDisposition.RELINK
                        and request.mirror_playlist_id is not None
                    )
                    else self._publication_storage.mirror_for_source(
                        state.account_id, self._source.source_label,
                        selection.reference,
                    )
                    if self._publication_storage is not None else None
                )
                previous_manifest = (
                    self._publication_storage.publication_for_playlist(
                        state.account_id, relationship.spotify_playlist_id,
                    )
                    if relationship is not None else None
                )
                current_source_ids = {
                    track.track_id for track in selection.tracks
                }
                if previous_manifest is not None:
                    playlist.source_removals = [
                        SourceRemoval(
                            item.source_track_id, item.source_name,
                            item.spotify_uri,
                        )
                        for item in (
                            previous_manifest.managed_items
                            or previous_manifest.items
                        )
                        if item.source_track_id not in current_source_ids
                    ]
                if relationship is not None:
                    current_uris = self._retry_policy.run(
                        lambda: self._spotify.provisional_playlist_track_uris(
                            relationship.spotify_playlist_id
                        )
                    )
                    if request.mirror_disposition == MirrorDisposition.RELINK:
                        relink_original_uris = list(current_uris or ())
                    current_uri_set = set(current_uris or ())
                    playlist.playlist_drift = [
                        PlaylistDrift(
                            item.source_track_id, item.source_name,
                            item.spotify_uri,
                        )
                        for item in publication_items
                        if item.authoritative
                        and item.spotify_uri not in current_uri_set
                    ]
                    if (
                        playlist.playlist_drift
                        and request.drift_resolution is None
                    ):
                        playlist.action = "restore or revoke required"
                        playlist.drift_choices = tuple(
                            choice.value for choice in DriftResolution
                        )
                        report.status = "playlist drift"
                        return report
                    if (
                        playlist.playlist_drift
                        and request.drift_resolution == DriftResolution.REVOKE
                    ):
                        drifted_ids = {
                            item.source_track_id for item in playlist.playlist_drift
                        }
                        revoked_items = [
                            item for item in publication_items
                            if item.source_track_id in drifted_ids
                        ]
                        for item in revoked_items:
                            self._knowledge.revoke(item)
                        self._knowledge.checkpoint()
                        publication_items = [
                            item for item in publication_items
                            if item.source_track_id not in drifted_ids
                        ]
                        playlist.matched = [
                            item for item in playlist.matched
                            if item.source_track_id not in drifted_ids
                        ]
                        playlist.unmatched.extend(
                            item.source_name for item in revoked_items
                            if item.source_name not in playlist.unmatched
                        )
                        state.publication_items = [
                            asdict(item) for item in publication_items
                        ]
                        state.matched = [asdict(item) for item in playlist.matched]
                        state.unmatched = list(playlist.unmatched)
                        self._save_transfer(transfer_id, state)

            if not request.preview and not selection.tracks:
                playlist.action = "not published: empty source"
            elif not request.preview:
                playlist_id = state.spotify_playlist_id
                snapshot_name = state.spotify_playlist_name
                created_playlist = playlist_id is None
                if playlist_id is None:
                    if request.mode == TransferMode.MIRROR:
                        snapshot_name = selection.name
                    else:
                        discriminator = (
                            f"{created_at:%Y-%m-%d %H%M%S} {uuid4().hex[:8]}"
                        )
                        snapshot_name = f"{selection.name} — {discriminator}"
                    if request.playlist_prefix:
                        snapshot_name = f"{request.playlist_prefix} / {snapshot_name}"
                    description = (
                        f"Provisional {request.mode.value.title()} from "
                        f"{self._source.source_label}: "
                        f"{selection.reference}. Created {created_at.isoformat()}."
                    )
                    publication_key = transfer_id
                    if request.mode == TransferMode.MIRROR:
                        publication_key = hashlib.sha256(
                            f"{state.account_id}\0{selection.reference}".encode()
                        ).hexdigest()
                    playlist_id = self._retry_policy.run(
                        lambda: self._spotify.publish_provisional_snapshot(
                            snapshot_name,
                            list(dict.fromkeys(
                                item.spotify_uri for item in publication_items
                                if item.spotify_uri not in collision_uris
                            )),
                            description,
                            publication_key,
                        )
                    )
                    state.spotify_playlist_id = playlist_id
                    state.spotify_playlist_name = snapshot_name
                    state.status = TransferStatus.RETAINING_PUBLICATION
                    self._save_transfer(transfer_id, state)
                    if self._pause_requested:
                        self._pause_requested = False
                        state.status = TransferStatus.PAUSED
                        self._save_transfer(transfer_id, state)
                        playlist.name = snapshot_name
                        playlist.spotify_playlist_id = playlist_id
                        playlist.action = "paused"
                        report.status = "paused"
                        return report
                elif request.mirror_disposition == MirrorDisposition.RELINK:
                    self._retry_policy.run(
                        lambda: self._spotify.replace_provisional_playlist_tracks(
                            playlist_id,
                            list(dict.fromkeys(
                                item.spotify_uri for item in publication_items
                                if item.spotify_uri not in collision_uris
                            )),
                        )
                    )
                assert snapshot_name is not None
                managed_items_by_uri: dict[str, PublicationItem] = {}
                for item in publication_items:
                    if item.spotify_uri not in collision_uris:
                        managed_items_by_uri.setdefault(item.spotify_uri, item)
                manifest = PublicationManifest(
                    account_id=state.account_id,
                    spotify_playlist_id=playlist_id,
                    spotify_playlist_name=snapshot_name,
                    source_label=self._source.source_label,
                    source_reference=selection.reference,
                    created_at=created_at,
                    items=tuple(
                        item for item in publication_items
                        if not item.authoritative
                        and item.spotify_uri not in collision_uris
                    ),
                    mode=request.mode,
                    managed_items=tuple(managed_items_by_uri.values()),
                )
                stored_manifest = asdict(manifest)
                stored_manifest["created_at"] = manifest.created_at.isoformat()
                state.publication_manifest = stored_manifest
                self._save_transfer(transfer_id, state)
                assert self._publication_storage is not None
                try:
                    self._publication_storage.retain_publication(manifest)
                except Exception:
                    if created_playlist:
                        self._spotify.delete_provisional_snapshot(playlist_id)
                    elif relink_original_uris is not None:
                        self._spotify.replace_provisional_playlist_tracks(
                            playlist_id, relink_original_uris,
                        )
                    state.spotify_playlist_id = None
                    state.spotify_playlist_name = None
                    state.status = TransferStatus.MATCHING
                    self._save_transfer(transfer_id, state)
                    raise
                if request.mirror_disposition == MirrorDisposition.RELINK:
                    assert request.mirror_playlist_id is not None
                    previous = self._publication_storage.mirror_for_playlist(
                        state.account_id, request.mirror_playlist_id,
                    )
                    assert previous is not None
                    self._publication_storage.replace_mirror(
                        previous,
                        replace(
                            previous,
                            source_label=self._source.source_label,
                            source_reference=selection.reference,
                            orphaned_at=None,
                        ),
                    )
                playlist.name = snapshot_name
                playlist.spotify_playlist_id = playlist_id
                playlist.publication_manifest = manifest
                playlist.mirror_disposition = (
                    request.mirror_disposition.value
                    if request.mirror_disposition else None
                )
                playlist.action = (
                    "mirror relinked"
                    if request.mirror_disposition == MirrorDisposition.RELINK
                    else "provisional mirror updated"
                    if request.mode == TransferMode.MIRROR
                    else "provisional snapshot created"
                )
            state.outcome = playlist.action
            state.status = TransferStatus.COMPLETED
            self._save_transfer(transfer_id, state)
            report.status = "completed"
        except (RateLimitError, requests.Timeout, requests.ConnectionError) as exc:
            state.status = TransferStatus.PAUSED
            self._save_transfer(transfer_id, state)
            raise exc
        except spotipy.SpotifyException as exc:
            if exc.http_status not in (401, 403, 429) and (
                exc.http_status is None or exc.http_status < 500
            ):
                raise
            state.status = TransferStatus.PAUSED
            self._save_transfer(transfer_id, state)
            raise
        except KeyboardInterrupt:
            state.status = TransferStatus.PAUSED
            self._save_transfer(transfer_id, state)
            raise
        finally:
            # Matching discoveries survive interrupted matching or publication.
            self._knowledge.checkpoint()

        return report

    def _save_transfer(self, transfer_id: str, state: TransferState) -> None:
        if self._transfer_storage is not None:
            self._transfer_storage.save_transfer(transfer_id, state)

    def _approved_available(self, spotify_uri: str) -> bool:
        try:
            track = self._retry_policy.run(
                lambda: self._spotify.spotify_track(spotify_uri)
            )
        except spotipy.SpotifyException as exc:
            if exc.http_status == 404:
                return False
            raise
        return track.get("is_playable", True) is not False
