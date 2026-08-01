"""Deep, framework-agnostic Transfer workflow.

The public seam is :class:`Transfer.execute`: adapters describe what to
transfer and receive a structured report, while this module owns matching,
persistence ordering, Preview policy, and Provisional Snapshot publication.
"""

from __future__ import annotations

import json
import hashlib
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
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
from djsupport.matcher import match_track
from djsupport.rekordbox import Track
from djsupport.report import MatchedTrack, PlaylistReport, SyncReport
from djsupport.spotify import MAX_RATE_LIMIT_WAIT, RateLimitError, _parse_retry_after


PUBLICATION_MANIFEST_VERSION = 1
TRANSFER_STATE_VERSION = 1
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


@dataclass(frozen=True)
class TransferRequest:
    """Everything an adapter must provide to start one Transfer."""

    source: str
    preview: bool = False
    threshold: int = 80
    retry: bool = False
    retry_days: int = 7
    playlist_prefix: str | None = "djsupport"
    transfer_id: str | None = None


class TransferStatus(str, Enum):
    MATCHING = "matching"
    PAUSED = "paused"
    RETAINING_PUBLICATION = "retaining publication"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


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
    spotify_playlist_id: str | None = None
    spotify_playlist_name: str | None = None
    publication_manifest: dict | None = None
    outcome: str | None = None

    @classmethod
    def from_dict(cls, value: dict) -> TransferState:
        return cls(**{**value, "status": TransferStatus(value["status"])})


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


class PublicationStorage(Protocol):
    def retain_publication(self, manifest: PublicationManifest) -> None: ...


class FilePublicationStorage:
    """Versioned, durable publication manifests for later review."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.manifests: list[dict] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        if data.get("version") != PUBLICATION_MANIFEST_VERSION:
            return
        self.manifests = data.get("manifests", [])

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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(json.dumps({
            "version": PUBLICATION_MANIFEST_VERSION,
            "manifests": next_manifests,
        }, indent=2))
        os.replace(temporary, self.path)
        self.manifests = next_manifests

    def manifests_for_account(self, account_id: str) -> list[dict]:
        """Return only playlist-management state owned by one account."""
        return [
            manifest for manifest in self.manifests
            if manifest.get("account_id") == account_id
        ]


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


class BeatportChartSource:
    """Production source adapter for one Beatport chart."""

    source_label = "Beatport"

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


class SpotifyMatcher:
    """Production Spotify matching and Snapshot publication adapter."""

    def __init__(self, client) -> None:
        self._client = client

    def account_id(self) -> str:
        return self._client.current_user()["id"]

    def match(self, track: Track, threshold: int) -> dict | None:
        return match_track(self._client, track, threshold=threshold)

    def publish_provisional_snapshot(
        self, name: str, track_uris: list[str], description: str,
        publication_key: str,
    ) -> str:
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


class MatchCacheKnowledge:
    """Expose the existing durable match cache as Transfer storage."""

    persistent = True

    def __init__(self, cache: MatchCache) -> None:
        self._cache = cache

    def lookup(self, track: Track, threshold: int) -> dict | None:
        entry = self._cache.lookup(track.artist, track.name, threshold)
        if entry is None or not entry.matched:
            return None
        return {
            "uri": entry.spotify_uri,
            "name": entry.spotify_name,
            "artist": entry.spotify_artist,
            "score": entry.score,
            "match_type": entry.match_type or "exact",
        }

    def should_retry(
        self, track: Track, threshold: int, retry_days: int, force: bool,
    ) -> bool:
        entry = self._cache.lookup(track.artist, track.name, threshold)
        if entry is None:
            return True
        if entry.matched:
            return False
        return force

    def retain(self, track: Track, threshold: int, result: dict | None) -> None:
        self._cache.store(track.artist, track.name, threshold, result)

    def checkpoint(self) -> None:
        self._cache.save()


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

    def execute(self, request: TransferRequest) -> SyncReport:
        """Execute at most one publishing Transfer per Spotify account."""
        if request.preview:
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

        transfer_id = request.transfer_id or uuid4().hex
        state = (
            self._transfer_storage.load_transfer(transfer_id)
            if self._transfer_storage is not None else None
        )
        if state is None:
            selection = self._source.consume(request.source)
            created_at = datetime.now()
            state = TransferState(
                status=TransferStatus.MATCHING,
                source=request.source,
                account_id=self._spotify.account_id(),
                request={
                    "source": request.source,
                    "preview": request.preview,
                    "threshold": request.threshold,
                    "retry": request.retry,
                    "retry_days": request.retry_days,
                    "playlist_prefix": request.playlist_prefix,
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
                **state.request, transfer_id=transfer_id,
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
        publication_items = [
            PublicationItem(**item) for item in state.publication_items
        ]
        if state.status == TransferStatus.COMPLETED:
            report.status = "completed"
            if state.spotify_playlist_id:
                playlist.name = state.spotify_playlist_name or playlist.name
                playlist.spotify_playlist_id = state.spotify_playlist_id
                playlist.action = "provisional snapshot created"
                stored_manifest = state.publication_manifest
                if stored_manifest:
                    playlist.publication_manifest = PublicationManifest(
                        **{
                            **stored_manifest,
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
                        }
                    )
            elif not request.preview and not selection.tracks:
                playlist.action = "not published: empty source"
            elif not request.preview and playlist.unmatched:
                playlist.action = "not published: incomplete matching"
            return report

        try:
            for index in range(state.next_track_index, len(selection.tracks)):
                track = selection.tracks[index]
                result = self._knowledge.lookup(track, request.threshold)
                if result is not None:
                    playlist.cache_hits += 1
                elif self._knowledge.should_retry(
                    track, request.threshold, request.retry_days, request.retry,
                ):
                    result = self._retry_policy.run(
                        lambda: self._spotify.match(track, request.threshold)
                    )
                    playlist.api_lookups += 1
                    self._knowledge.retain(track, request.threshold, result)
                else:
                    result = None
                    playlist.cache_hits += 1

                if result is None:
                    playlist.unmatched.append(track.display)
                else:
                    matched_track = MatchedTrack(
                        source_name=track.display,
                        spotify_name=result["name"],
                        spotify_artist=result["artist"],
                        score=result["score"],
                        match_type=result.get("match_type", "exact"),
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
                    ))

                state.next_track_index = index + 1
                state.matched = [asdict(item) for item in playlist.matched]
                state.unmatched = list(playlist.unmatched)
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

            if not request.preview and not selection.tracks:
                playlist.action = "not published: empty source"
            elif not request.preview and playlist.unmatched:
                playlist.action = "not published: incomplete matching"
            elif not request.preview:
                playlist_id = state.spotify_playlist_id
                snapshot_name = state.spotify_playlist_name
                if playlist_id is None:
                    discriminator = (
                        f"{created_at:%Y-%m-%d %H%M%S} {uuid4().hex[:8]}"
                    )
                    snapshot_name = f"{selection.name} — {discriminator}"
                    if request.playlist_prefix:
                        snapshot_name = f"{request.playlist_prefix} / {snapshot_name}"
                    description = (
                        f"Provisional Snapshot from {self._source.source_label}: "
                        f"{selection.reference}. Created {created_at.isoformat()}."
                    )
                    playlist_id = self._retry_policy.run(
                        lambda: self._spotify.publish_provisional_snapshot(
                            snapshot_name,
                            [item.spotify_uri for item in publication_items],
                            description,
                            transfer_id,
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
                assert snapshot_name is not None
                manifest = PublicationManifest(
                    account_id=state.account_id,
                    spotify_playlist_id=playlist_id,
                    spotify_playlist_name=snapshot_name,
                    source_label=self._source.source_label,
                    source_reference=selection.reference,
                    created_at=created_at,
                    items=tuple(publication_items),
                )
                stored_manifest = asdict(manifest)
                stored_manifest["created_at"] = manifest.created_at.isoformat()
                state.publication_manifest = stored_manifest
                self._save_transfer(transfer_id, state)
                assert self._publication_storage is not None
                try:
                    self._publication_storage.retain_publication(manifest)
                except Exception:
                    self._spotify.delete_provisional_snapshot(playlist_id)
                    state.spotify_playlist_id = None
                    state.spotify_playlist_name = None
                    state.status = TransferStatus.MATCHING
                    self._save_transfer(transfer_id, state)
                    raise
                playlist.name = snapshot_name
                playlist.spotify_playlist_id = playlist_id
                playlist.publication_manifest = manifest
                playlist.action = "provisional snapshot created"
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
