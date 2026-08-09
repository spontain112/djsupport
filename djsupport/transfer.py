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
import threading
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
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
from djsupport.local_audition import LocalAuditionResult
from djsupport.matcher import match_track_with_alternatives
from djsupport.paths import default_app_data_path
from djsupport.rekordbox import Track
from djsupport.report import (
    AlternativeCandidate,
    MatchCollision,
    MatchedTrack,
    PlaylistDrift,
    PlaylistReport,
    ReviewTrack,
    SyncReport,
    SourceRemoval,
    UnmatchedAlternatives,
    UnavailableApprovedMatch,
)
from djsupport.spotify import (
    MAX_RATE_LIMIT_WAIT,
    QuotaExceededError,
    RateLimitError,
    SpotifyCapabilityError,
    _parse_retry_after,
)


PUBLICATION_MANIFEST_VERSION = 6
TRANSFER_STATE_VERSION = 5
EXPENSIVE_BATCH_LOOKUP_THRESHOLD = 100
SPOTIFY_TRACK_URI = re.compile(r"^spotify:track:([A-Za-z0-9]{22})$")
SPOTIFY_TRACK_URL = re.compile(
    r"^https://open\.spotify\.com/track/([A-Za-z0-9]{22})(?:\?.*)?$"
)
ResultT = TypeVar("ResultT")


def default_matching_knowledge_path() -> Path:
    """Return a private, user-local path outside the repository."""
    return default_app_data_path() / "matching-knowledge.json"


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
    retain_matching_knowledge: bool = True
    local_audio_identity: bool = False
    local_audio_audition: bool = False


@dataclass(frozen=True)
class LocalAudioObservation:
    """One private local observation; values never enter reports or manifests."""

    status: str
    fingerprint: str | None = None
    algorithm: str = "chromaprint"
    algorithm_version: str = ""
    duration: int = 0
    reason: str | None = None

    @classmethod
    def available(
        cls, *, fingerprint: str, algorithm: str,
        algorithm_version: str, duration: int,
    ) -> LocalAudioObservation:
        return cls(
            status="available", fingerprint=fingerprint, algorithm=algorithm,
            algorithm_version=algorithm_version, duration=duration,
        )

    @classmethod
    def unavailable(cls, reason: str) -> LocalAudioObservation:
        return cls(status="unavailable", reason=reason)


@dataclass(frozen=True)
class BatchPlanRequest:
    """An explicit, bounded Rekordbox Batch selection."""

    playlist_references: tuple[str, ...] = ()
    whole_library: bool = False
    threshold: int = 80
    confirm_expensive: bool = False
    preview: bool = False
    retry: bool = False
    retry_days: int = 7
    playlist_prefix: str | None = "djsupport"
    local_audio_identity: bool = False
    local_audio_audition: bool = False


@dataclass(frozen=True)
class TransferAuthorization:
    """Explicit authority supplied by a client for one Transfer operation."""

    private_source: bool = False
    spotify_write: bool = False


@dataclass(frozen=True)
class PlaylistPreflight:
    name: str
    reference: str
    total_tracks: int
    approved_match_hits: int
    cache_hits: int
    expected_uncached_lookups: int
    local_audio_eligible: int = 0
    local_audio_indexed: int = 0
    local_audio_pending: int = 0
    local_audio_unavailable: int = 0
    selection_token: str = ""


@dataclass(frozen=True)
class BatchPlan:
    playlists: tuple[PlaylistPreflight, ...]
    confirmation_required: bool = False
    threshold: int = 80
    preview: bool = False
    retry: bool = False
    retry_days: int = 7
    playlist_prefix: str | None = "djsupport"
    local_audio_identity: bool = False
    local_audio_audition: bool = False

    @property
    def ready(self) -> bool:
        return not self.confirmation_required

    @property
    def total_tracks(self) -> int:
        return sum(playlist.total_tracks for playlist in self.playlists)

    @property
    def approved_match_hits(self) -> int:
        return sum(playlist.approved_match_hits for playlist in self.playlists)

    @property
    def cache_hits(self) -> int:
        return sum(playlist.cache_hits for playlist in self.playlists)

    @property
    def expected_uncached_lookups(self) -> int:
        return sum(
            playlist.expected_uncached_lookups for playlist in self.playlists
        )

    @property
    def local_audio_eligible(self) -> int:
        return sum(item.local_audio_eligible for item in self.playlists)

    @property
    def local_audio_indexed(self) -> int:
        return sum(item.local_audio_indexed for item in self.playlists)

    @property
    def local_audio_pending(self) -> int:
        return sum(item.local_audio_pending for item in self.playlists)

    @property
    def local_audio_unavailable(self) -> int:
        return sum(item.local_audio_unavailable for item in self.playlists)

    @property
    def batch_id(self) -> str:
        """Return a privacy-safe identity for the exact bounded plan."""
        material = {
            "selections": [
                (item.reference, item.selection_token) for item in self.playlists
            ],
            "threshold": self.threshold,
            "preview": self.preview,
            "retry": self.retry,
            "retry_days": self.retry_days,
            "playlist_prefix": self.playlist_prefix,
            "local_audio_identity": self.local_audio_identity,
            "local_audio_audition": self.local_audio_audition,
        }
        canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

class TransferStatus(str, Enum):
    MATCHING = "matching"
    PAUSED = "paused"
    RETAINING_PUBLICATION = "retaining publication"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


@dataclass(frozen=True)
class TransferProgress:
    """Durable, adapter-facing progress for one Transfer."""

    transfer_id: str
    source: str
    status: TransferStatus
    current: int
    total: int
    error: str | None = None
    retain_matching_knowledge: bool = True
    local_audio_identity: bool = False
    local_audio_audition: bool = False


class BatchPhase(str, Enum):
    PENDING = "pending"
    PAUSED = "paused"
    FAILED = "failed"
    COMPLETED = "completed"


class PlaylistOutcome(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class BatchStatus(str, Enum):
    MATCHING = "matching"
    PAUSED = "paused"
    COMPLETED = "completed"
    PARTIAL_SUCCESS = "partial success"
    FAILED = "failed"


@dataclass
class BatchPlaylistState:
    name: str
    reference: str
    transfer_id: str
    selection_token: str = ""
    phase: BatchPhase = BatchPhase.PENDING
    outcome: PlaylistOutcome = PlaylistOutcome.PENDING
    error: str | None = None

    @classmethod
    def from_dict(cls, value: dict) -> BatchPlaylistState:
        return cls(**{
            **value,
            "phase": BatchPhase(value.get("phase", BatchPhase.PENDING.value)),
            "outcome": PlaylistOutcome(
                value.get("outcome", PlaylistOutcome.PENDING.value)
            ),
        })


@dataclass
class BatchState:
    account_id: str | None
    created_at: str
    threshold: int
    status: BatchStatus
    playlists: list[BatchPlaylistState]
    preview: bool = False
    retry: bool = False
    retry_days: int = 7
    playlist_prefix: str | None = "djsupport"
    local_audio_identity: bool = False
    local_audio_audition: bool = False
    plan_id: str = ""
    revision: int = 0

    @classmethod
    def from_dict(cls, value: dict) -> BatchState:
        return cls(**{
            **value,
            "status": BatchStatus(value["status"]),
            "playlists": [
                BatchPlaylistState.from_dict(playlist)
                for playlist in value["playlists"]
            ],
        })


@dataclass(frozen=True)
class BatchProgress:
    transfer_id: str
    status: BatchStatus
    playlists: int
    completed: int
    failed: int
    pending: int


class QualificationDecision(str, Enum):
    """One non-authoritative human outcome in a Qualification Draft."""

    KEEP_PROPOSAL = "keep_proposal"
    CORRECTION = "correction"
    DEFERRED = "deferred"
    REJECT_PROPOSAL = "reject_proposal"


class QualificationStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    APPLYING = "applying"
    PAUSED = "paused"
    APPLIED = "applied"
    APPROVING = "approving"
    APPROVED = "approved"
    REVIEW_REQUIRED = "review_required"
    DISCARDED = "discarded"


@dataclass(frozen=True)
class QualificationRequest:
    """Select one completed Rekordbox playlist Transfer for qualification."""

    transfer_id: str
    playlist_reference: str | None = None
    include_all: bool = False


@dataclass
class QualificationDraftState:
    """Private, durable, non-authoritative Qualification working state."""

    draft_id: str
    transfer_id: str
    batch_id: str | None
    source_reference: str
    account_id: str
    playlist_id: str | None
    playlist_head: str | None
    manifest_digest: str
    selection_digest: str
    include_all: bool
    item_ids: list[str]
    decisions: dict[str, dict]
    status: QualificationStatus
    created_at: str
    updated_at: str
    mutation_snapshots: list[str] = field(default_factory=list)
    completed_chunks: list[str] = field(default_factory=list)
    applied_manifest: dict | None = None
    applied_uris: list[str] = field(default_factory=list)
    approval_outcome: dict | None = None
    audition_statuses: dict[str, dict] = field(default_factory=dict)
    audition_selection_digest: str | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    review_reason: str | None = None
    revision: int = 0

    @classmethod
    def from_dict(cls, value: dict) -> QualificationDraftState:
        return cls(**{
            "mutation_snapshots": [],
            "completed_chunks": [],
            "applied_manifest": None,
            "applied_uris": [],
            "approval_outcome": None,
            "audition_statuses": {},
            "audition_selection_digest": None,
            "supersedes": None,
            "superseded_by": None,
            "review_reason": None,
            "revision": 0,
            **value,
            "status": QualificationStatus(
                value.get("status", QualificationStatus.DRAFT.value)
            ),
        })


@dataclass(frozen=True)
class QualificationItem:
    """Privacy-bounded comparison facts for one selected source occurrence."""

    item_id: str
    source_index: int
    source_track_id: str
    source_artist: str
    source_title: str
    source_release: str = ""
    source_label: str = ""
    source_version: str = ""
    source_duration: int = 0
    spotify_uri: str = ""
    spotify_name: str = ""
    spotify_artist: str = ""
    spotify_release: str = ""
    spotify_duration: int = 0
    score: float = 0.0
    match_type: str = "unmatched"
    score_reasons: tuple[str, ...] = ()
    authority_status: str = "proposal"
    attention_reasons: tuple[str, ...] = ()
    audition_status: str = "not_requested"
    audition_reason: str | None = None
    decision: QualificationDecision | None = None
    correction_uri: str | None = None
    deferred_reason: str | None = None
    excluded: bool = False
    availability_status: str = "unknown"
    availability_reason: str | None = "not_checked"
    availability_checked_at: str | None = None
    availability_source: str | None = None
    permitted_actions: tuple[QualificationDecision, ...] = ()


@dataclass(frozen=True)
class QualificationView:
    draft_id: str
    transfer_id: str
    source_reference: str
    spotify_playlist_id: str | None
    status: QualificationStatus
    items: tuple[QualificationItem, ...]
    include_all: bool = False

    @property
    def pending(self) -> int:
        return sum(item.decision is None for item in self.items)

    @property
    def deferred(self) -> int:
        return sum(
            item.decision == QualificationDecision.DEFERRED and not item.excluded
            for item in self.items
        )

    @property
    def complete(self) -> bool:
        return self.pending == 0 and self.deferred == 0

    @property
    def next_actions(self) -> tuple[str, ...]:
        """Return policy-owned lifecycle actions for thin clients."""
        if self.status == QualificationStatus.APPROVED:
            return ()
        if self.status == QualificationStatus.APPROVING:
            return ("review",)
        if self.status == QualificationStatus.APPLIED:
            return ("approve",)
        if self.status == QualificationStatus.DISCARDED:
            return ("supersede",)
        if self.status in {
            QualificationStatus.APPLYING,
            QualificationStatus.PAUSED,
        }:
            return ("resume",)
        if self.status == QualificationStatus.REVIEW_REQUIRED:
            return ("review", "discard")
        if self.complete and self.spotify_playlist_id is None:
            return ("publish_and_link", "discard")
        if self.complete:
            return ("apply", "discard")
        return ("review", "discard")

    @property
    def current_item(self) -> QualificationItem | None:
        if self.status in {
            QualificationStatus.APPLYING,
            QualificationStatus.PAUSED,
            QualificationStatus.APPLIED,
            QualificationStatus.APPROVING,
            QualificationStatus.APPROVED,
            QualificationStatus.DISCARDED,
        }:
            return None
        return next((
            item for item in self.items
            if item.decision is None
            or (
                item.decision == QualificationDecision.DEFERRED
                and not item.excluded
            )
        ), self.items[0] if self.items else None)


@dataclass(frozen=True)
class QualificationApplyOutcome:
    draft_id: str
    spotify_playlist_id: str
    status: QualificationStatus
    applied_items: int
    next_actions: tuple[str, ...]


class ApprovalStatus(str, Enum):
    APPROVED = "approved"
    ABANDONED = "abandoned"
    NEEDS_REVIEW = "needs review"


class SpotifyItemKind(str, Enum):
    """Explicit classification of one ordered Spotify playlist occurrence."""

    TRACK = "track"
    NULL = "null"
    LOCAL = "local"
    EPISODE = "episode"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class SpotifyPlaylistHead:
    snapshot_id: str


@dataclass(frozen=True)
class SpotifyPlaylistItem:
    position: int
    kind: SpotifyItemKind
    uri: str | None
    is_local: bool = False
    is_playable: bool | None = None
    restrictions: dict | None = None
    linked_from_uri: str | None = None


@dataclass(frozen=True)
class SpotifyPlaylistPage:
    items: tuple[SpotifyPlaylistItem, ...]


@dataclass(frozen=True)
class SpotifyMutationResult:
    snapshot_id: str


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
                    if "QUOTA_EXCEEDED" in str(exc).upper():
                        raise QuotaExceededError(
                            "Spotify quota exhausted; Transfer checkpointed "
                            "and paused"
                        ) from exc
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


class SpotifyPlaylistChanged(RuntimeError):
    """Spotify's playlist head no longer matches retained Transfer evidence."""


class SpotifyPlaylistReviewRequired(RuntimeError):
    """Approval encountered playlist facts requiring an explicit user decision."""

    def __init__(self, message: str, *, draft_id: str | None = None) -> None:
        super().__init__(message)
        self.draft_id = draft_id


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
    mutation_snapshots: list[str] = field(default_factory=list)
    completed_chunks: list[str] = field(default_factory=list)
    api_lookups: int = 0
    local_audio_eligible: int = 0
    local_audio_observed: int = 0
    local_audio_unavailable: int = 0
    local_audio_reused: int = 0
    local_evidence_ids: dict[str, str] = field(default_factory=dict)
    audition_selection_digest: str | None = None
    revision: int = 0

    @classmethod
    def from_dict(cls, value: dict) -> TransferState:
        return cls(**{
            "alternatives": [], "mutation_snapshots": [],
            "completed_chunks": [], "api_lookups": 0,
            "local_audio_eligible": 0, "local_audio_observed": 0,
            "local_audio_unavailable": 0, "local_audio_reused": 0,
            "local_evidence_ids": {}, "audition_selection_digest": None,
            "revision": 0,
            **value,
            "status": TransferStatus(value["status"]),
        })


@dataclass(frozen=True)
class SourceSelection:
    """One named selection returned by a source adapter."""

    name: str
    reference: str
    tracks: list[Track]
    chart_title: str | None = None
    curator: str | None = None


@dataclass(frozen=True)
class PublicationItem:
    """One exact source-to-Spotify proposal published for review."""

    source_track_id: str
    source_name: str
    source_artist: str
    source_title: str
    occurrence_id: str = ""
    source_index: int = 0
    source_release: str = ""
    source_label: str = ""
    source_version: str = ""
    spotify_uri: str = ""
    spotify_name: str = ""
    spotify_artist: str = ""
    spotify_release: str = ""
    spotify_duration: int = 0
    score: float = 0.0
    match_type: str = "unmatched"
    score_reasons: tuple[str, ...] = ()
    source_duration: int = 0
    authoritative: bool = False
    local_evidence_id: str | None = None
    availability_status: str = "unknown"
    availability_reason: str | None = "not_checked"
    availability_checked_at: str | None = None
    availability_source: str | None = None
    qualification_outcome: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "score_reasons", tuple(self.score_reasons))


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
    chart_title: str | None = None
    curator: str | None = None


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

    def set_playlist_description(
        self, playlist_id: str, description: str,
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

    def retain_relinked_publication(
        self, previous: MirrorRelationship, replacement: MirrorRelationship,
        manifest: PublicationManifest,
    ) -> None: ...

    def remove_mirror(self, relationship: MirrorRelationship) -> None: ...


class FilePublicationStorage:
    """Versioned, durable publication manifests for later review."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.manifests: list[dict] = []
        self.approvals: list[dict] = []
        self.mirrors: list[dict] = []
        self._loaded_once = False
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            if self._loaded_once:
                raise ValueError(
                    "Publication state is unavailable; restore it before use"
                )
            self._loaded_once = True
            return
        try:
            data = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(
                "Publication state is malformed; restore it before use"
            ) from exc
        if not isinstance(data, dict) or data.get("version") not in (
            1, 2, 3, 4, 5, PUBLICATION_MANIFEST_VERSION,
        ):
            raise ValueError(
                "Publication state schema is unsupported; upgrade djsupport "
                "before using this file"
            )
        manifests = data.get("manifests", [])
        approvals = data.get("approvals", data.get("reviews", []))
        mirrors = data.get("mirrors", [])
        if not all(isinstance(value, list) for value in (
            manifests, approvals, mirrors,
        )):
            raise ValueError(
                "Publication state is malformed; restore it before use"
            )
        self.manifests = manifests
        self.approvals = approvals
        self.mirrors = mirrors
        self._loaded_once = True

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

    def retain_relinked_publication(
        self, previous: MirrorRelationship, replacement: MirrorRelationship,
        manifest: PublicationManifest,
    ) -> None:
        stored_manifest = asdict(manifest)
        stored_manifest["created_at"] = manifest.created_at.isoformat()
        next_manifests = [
            item for item in self.manifests
            if not (
                item.get("account_id") == manifest.account_id
                and item.get("spotify_playlist_id") == manifest.spotify_playlist_id
            )
        ]
        next_manifests.append(stored_manifest)
        stored_relationship = asdict(replacement)
        stored_relationship["approved_at"] = replacement.approved_at.isoformat()
        stored_relationship["orphaned_at"] = None
        previous_mirrors = self.mirrors
        self.mirrors = [
            item for item in self.mirrors
            if not (
                item.get("account_id") == previous.account_id
                and item.get("spotify_playlist_id") == previous.spotify_playlist_id
            )
        ]
        self.mirrors.append(stored_relationship)
        try:
            self._save(next_manifests, self.approvals)
        except Exception:
            self.mirrors = previous_mirrors
            raise

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

    def load_batch(self, transfer_id: str) -> BatchState | None: ...

    def save_batch(self, transfer_id: str, state: BatchState) -> None: ...

    def load_qualification(
        self, draft_id: str,
    ) -> QualificationDraftState | None: ...

    def save_qualification(
        self, draft_id: str, state: QualificationDraftState,
    ) -> None: ...

    def save_qualification_successor(
        self,
        discarded: QualificationDraftState,
        successor: QualificationDraftState,
    ) -> None: ...

    def qualifications_for_playlist(
        self, account_id: str, playlist_id: str,
    ) -> list[QualificationDraftState]: ...


class FileTransferStorage:
    """Atomically persisted, versioned state for resumable Transfers."""

    _thread_locks: dict[str, threading.RLock] = {}
    _thread_locks_guard = threading.Lock()

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.transfers: dict[str, TransferState] = {}
        self.batches: dict[str, BatchState] = {}
        self.qualifications: dict[str, QualificationDraftState] = {}
        lock_key = str(self.path.resolve())
        with self._thread_locks_guard:
            self._thread_lock = self._thread_locks.setdefault(
                lock_key, threading.RLock(),
            )
        self._load()

    @contextmanager
    def _exclusive(self):
        lock_path = self.path.with_suffix(f"{self.path.suffix}.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._thread_lock, lock_path.open("a+") as lock_file:
            if os.name == "nt":
                lock_file.seek(0)
                if not lock_file.read(1):
                    lock_file.write("0")
                    lock_file.flush()
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def refresh(self) -> None:
        """Reload complete authoritative state under its file lock."""
        with self._exclusive():
            self._reload_unlocked()

    def _reload_unlocked(self) -> None:
        if not self.path.exists():
            self.transfers = {}
            self.batches = {}
            self.qualifications = {}
            return
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(
                "Transfer state is malformed; repair or restore it before use"
            ) from exc
        if not isinstance(data, dict) or data.get("version") not in (
            1, 2, 3, 4, TRANSFER_STATE_VERSION,
        ):
            raise ValueError(
                "Transfer state schema is unsupported; upgrade djsupport "
                "before using this file"
            )
        sections = {
            "transfers": data.get("transfers", {}),
            "batches": data.get("batches", {}),
            "qualifications": data.get("qualifications", {}),
        }
        if not all(isinstance(value, dict) for value in sections.values()):
            raise ValueError(
                "Transfer state is malformed; repair or restore it before use"
            )
        try:
            transfers = {
                transfer_id: TransferState.from_dict(state)
                for transfer_id, state in sections["transfers"].items()
            }
            batches = {
                transfer_id: BatchState.from_dict(state)
                for transfer_id, state in sections["batches"].items()
            }
            qualifications = {
                draft_id: QualificationDraftState.from_dict(state)
                for draft_id, state in sections["qualifications"].items()
            }
            if any(
                draft_id != draft.draft_id
                for draft_id, draft in qualifications.items()
            ):
                raise ValueError(
                    "Qualification map key does not match embedded draft identity"
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "Transfer state is malformed; repair or restore it before use"
            ) from exc
        self.transfers = transfers
        self.batches = batches
        self.qualifications = qualifications

    def load_transfer(self, transfer_id: str) -> TransferState | None:
        return self.transfers.get(transfer_id)

    def save_transfer(self, transfer_id: str, state: TransferState) -> None:
        self._save_entity("transfers", transfer_id, state)

    def load_batch(self, transfer_id: str) -> BatchState | None:
        return self.batches.get(transfer_id)

    def save_batch(self, transfer_id: str, state: BatchState) -> None:
        self._save_entity("batches", transfer_id, state)

    def load_qualification(
        self, draft_id: str,
    ) -> QualificationDraftState | None:
        return self.qualifications.get(draft_id)

    def save_qualification(
        self, draft_id: str, state: QualificationDraftState,
    ) -> None:
        self._save_entity("qualifications", draft_id, state)

    def save_qualification_successor(
        self,
        discarded: QualificationDraftState,
        successor: QualificationDraftState,
    ) -> None:
        """Persist both sides of an explicit supersession atomically."""
        with self._exclusive():
            self._reload_unlocked()
            latest = self.qualifications.get(discarded.draft_id)
            if latest is None or latest.revision != discarded.revision:
                raise ValueError(
                    "Transfer state changed concurrently; reload before retry"
                )
            if successor.draft_id in self.qualifications:
                raise ValueError("Qualification successor already exists")
            old_revision = discarded.revision
            new_revision = successor.revision
            discarded.revision += 1
            successor.revision += 1
            self.qualifications = {
                **self.qualifications,
                discarded.draft_id: discarded,
                successor.draft_id: successor,
            }
            try:
                self._save()
            except Exception:
                discarded.revision = old_revision
                successor.revision = new_revision
                raise

    def _save_entity(self, section: str, key: str, state) -> None:
        with self._exclusive():
            self._reload_unlocked()
            collection = getattr(self, section)
            latest = collection.get(key)
            if latest is not None and latest.revision != state.revision:
                raise ValueError(
                    "Transfer state changed concurrently; reload before retry"
                )
            previous_revision = state.revision
            state.revision = previous_revision + 1
            setattr(self, section, {**collection, key: state})
            try:
                self._save()
            except Exception:
                state.revision = previous_revision
                raise

    def qualifications_for_playlist(
        self, account_id: str, playlist_id: str,
    ) -> list[QualificationDraftState]:
        return [
            draft for draft in self.qualifications.values()
            if draft.account_id == account_id and draft.playlist_id == playlist_id
        ]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(json.dumps({
            "version": TRANSFER_STATE_VERSION,
            "transfers": {
                key: asdict(transfer) for key, transfer in self.transfers.items()
            },
            "batches": {
                key: asdict(batch) for key, batch in self.batches.items()
            },
            "qualifications": {
                key: asdict(draft)
                for key, draft in self.qualifications.items()
            },
        }, indent=2))
        os.replace(temporary, self.path)


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

    def retain_local_audio(
        self, track: Track, observation: LocalAudioObservation,
    ) -> str: ...

    def lookup_local_audio(
        self, observation: LocalAudioObservation, account_id: str,
    ) -> dict | None: ...

    def approve_local_audio(
        self, item: PublicationItem, account_id: str,
    ) -> ApprovalConflict | None: ...

    def revoke_local_audio(
        self, item: PublicationItem, account_id: str,
    ) -> None: ...

    def has_local_audio_observation(
        self, track: Track, algorithm: str, algorithm_version: str,
    ) -> bool: ...

    def local_audio_observation(
        self, evidence_id: str,
    ) -> LocalAudioObservation | None: ...

    def approval_conflict(self, item: PublicationItem) -> bool: ...

    def local_audio_approval_conflict(
        self, item: PublicationItem, account_id: str,
    ) -> ApprovalConflict | None: ...


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
            chart_title=chart_name,
            curator=curator if curator != "Unknown" else None,
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

    def __init__(
        self, xml_path: str | Path, *, include_locations: bool = False,
    ) -> None:
        self._xml_path = Path(xml_path)
        self._include_locations = include_locations

    def consume(self, reference: str) -> SourceSelection:
        from djsupport.rekordbox import parse_xml

        tracks, playlists = parse_xml(
            self._xml_path, include_locations=self._include_locations,
        )
        return self._select(tracks, playlists, reference)

    @staticmethod
    def _select(tracks, playlists, reference: str) -> SourceSelection:
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

    def consume_batch(
        self, references: tuple[str, ...], whole_library: bool,
    ) -> tuple[SourceSelection, ...]:
        if references and whole_library:
            raise ValueError(
                "Select playlists explicitly or opt into the whole library, not both"
            )
        if not references and not whole_library:
            raise ValueError("A Batch must select at least one playlist explicitly")
        if len(set(references)) != len(references):
            raise ValueError("A Batch cannot contain a duplicate playlist reference")
        from djsupport.rekordbox import parse_xml

        tracks, playlists = parse_xml(
            self._xml_path, include_locations=self._include_locations,
        )
        selected_references = (
            tuple(playlist.path for playlist in playlists)
            if whole_library else references
        )
        selections = tuple(
            self._select(tracks, playlists, reference)
            for reference in selected_references
        )
        canonical_references = [selection.reference for selection in selections]
        if len(set(canonical_references)) != len(canonical_references):
            raise ValueError("A Batch cannot contain a duplicate playlist reference")
        return selections


class SpotifyMatcher:
    """Production Spotify matching and Transfer publication adapter."""

    def __init__(self, client) -> None:
        self._client = client

    def account_id(self) -> str:
        profile = self._client.current_user()
        return profile.get("account_id") or profile["id"]

    def create_playlist(self, name: str, description: str) -> str:
        playlist = self._client._post("me/playlists", payload={
            "name": name,
            "public": False,
            "description": description,
        })
        return playlist["id"]

    def find_recovery_playlist(self, publication_key: str) -> str | None:
        return self._find_publication(f"djsupport-transfer:{publication_key}")

    def playlist_head(self, playlist_id: str) -> SpotifyPlaylistHead:
        try:
            playlist = self._client.playlist(playlist_id, fields="snapshot_id")
        except spotipy.SpotifyException as exc:
            if exc.http_status == 403:
                raise SpotifyCapabilityError("playlist-read-private") from exc
            raise
        return SpotifyPlaylistHead(snapshot_id=playlist["snapshot_id"])

    def ordered_playlist_items(self, playlist_id: str) -> SpotifyPlaylistPage:
        try:
            page = self._client.playlist_items(playlist_id)
        except spotipy.SpotifyException as exc:
            if exc.http_status == 403:
                raise SpotifyCapabilityError("playlist-read-private") from exc
            raise
        items: list[SpotifyPlaylistItem] = []
        position = 0
        while page:
            for wrapper in page.get("items", []):
                value = wrapper.get("track") or wrapper.get("item")
                if value is None:
                    kind = SpotifyItemKind.NULL
                elif value.get("is_local"):
                    kind = SpotifyItemKind.LOCAL
                elif value.get("type") == "track":
                    kind = SpotifyItemKind.TRACK
                elif value.get("type") == "episode":
                    kind = SpotifyItemKind.EPISODE
                else:
                    kind = SpotifyItemKind.UNSUPPORTED
                items.append(SpotifyPlaylistItem(
                    position=position,
                    kind=kind,
                    uri=value.get("uri") if value else None,
                    is_local=bool(value and value.get("is_local")),
                    is_playable=value.get("is_playable") if value else None,
                    restrictions=value.get("restrictions") if value else None,
                    linked_from_uri=(
                        (value.get("linked_from") or {}).get("uri")
                        if value else None
                    ),
                ))
                position += 1
            if not page.get("next"):
                break
            try:
                page = self._client.next(page)
            except spotipy.SpotifyException as exc:
                if exc.http_status == 403:
                    raise SpotifyCapabilityError(
                        "playlist-read-private"
                    ) from exc
                raise
        return SpotifyPlaylistPage(tuple(items))

    def replace_items(
        self, playlist_id: str, uris: list[str],
    ) -> SpotifyMutationResult:
        result = self._client.playlist_replace_items(playlist_id, uris)
        return SpotifyMutationResult(result["snapshot_id"])

    def add_items(
        self, playlist_id: str, uris: list[str],
    ) -> SpotifyMutationResult:
        result = self._client.playlist_add_items(playlist_id, uris)
        return SpotifyMutationResult(result["snapshot_id"])

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
            playlist_id = self.create_playlist(name, description)
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

    def set_playlist_description(
        self, playlist_id: str, description: str,
    ) -> None:
        self._client.playlist_change_details(
            playlist_id, description=description,
        )

    def spotify_track(self, uri: str) -> dict:
        track = self._client.track(uri)
        return {
            "uri": track["uri"],
            "name": track["name"],
            "artist": ", ".join(artist["name"] for artist in track["artists"]),
            "album": (track.get("album") or {}).get("name", ""),
            "duration_ms": int(track.get("duration_ms", 0)),
            "is_playable": track.get("is_playable"),
            "restrictions": track.get("restrictions"),
            "linked_from": track.get("linked_from"),
            "is_local": track.get("is_local", False),
        }


class MatchCacheKnowledge:
    """Expose the existing durable match cache as Transfer storage."""

    persistent = True

    def __init__(self, cache: MatchCache) -> None:
        self._cache = cache

    def refresh(self) -> None:
        """Reload durable authority before a guarded policy decision."""
        self._cache.reload_strict()

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
            "album": entry.spotify_release,
            "duration_ms": entry.spotify_duration * 1000,
            "score": entry.score,
            "match_type": entry.match_type or "exact",
            "score_reasons": list(entry.score_reasons),
            "authoritative": entry.approval_status == "approved",
            "availability_status": entry.availability_status,
            "availability_reason": entry.availability_reason,
            "availability_checked_at": entry.availability_checked_at,
            "availability_source": entry.availability_source,
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
                "score_reasons": list(item.score_reasons),
                "spotify_release": item.spotify_release,
                "spotify_duration": item.spotify_duration,
                "availability_status": item.availability_status,
                "availability_reason": item.availability_reason,
                "availability_checked_at": item.availability_checked_at,
                "availability_source": item.availability_source,
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
                "score_reasons": list(item.score_reasons),
                "spotify_release": item.spotify_release,
                "spotify_duration": item.spotify_duration,
                "availability_status": item.availability_status,
                "availability_reason": item.availability_reason,
                "availability_checked_at": item.availability_checked_at,
                "availability_source": item.availability_source,
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
            "source_duration": item.source_duration,
            "spotify_uri": item.spotify_uri,
            "spotify_name": item.spotify_name,
            "spotify_artist": item.spotify_artist,
        })
        return None

    def revoke(self, item: PublicationItem) -> None:
        self._cache.revoke_approval(
            item.source_artist, item.source_title, item.source_duration,
        )

    def revoke_local_audio(
        self, item: PublicationItem, account_id: str,
    ) -> None:
        self._cache.revoke_fingerprints(
            source_artist=item.source_artist,
            source_title=item.source_title,
            source_duration=item.source_duration,
            evidence_id=item.local_evidence_id,
            account_id=account_id,
        )

    def retain_local_audio(
        self, track: Track, observation: LocalAudioObservation,
    ) -> str:
        assert observation.fingerprint is not None
        return self._cache.retain_fingerprint_observation(
            algorithm=observation.algorithm,
            algorithm_version=observation.algorithm_version,
            fingerprint=observation.fingerprint,
            audio_duration=observation.duration,
            source_track_id=track.track_id,
        )

    def lookup_local_audio(
        self, observation: LocalAudioObservation, account_id: str,
    ) -> dict | None:
        if observation.status != "available" or observation.fingerprint is None:
            return None
        return self._cache.lookup_fingerprint(
            algorithm=observation.algorithm,
            algorithm_version=observation.algorithm_version,
            fingerprint=observation.fingerprint,
            account_id=account_id,
        )

    def approve_local_audio(
        self, item: PublicationItem, account_id: str,
    ) -> ApprovalConflict | None:
        if item.local_evidence_id is None:
            return None
        conflict = self._cache.approve_fingerprint(
            evidence_id=item.local_evidence_id,
            account_id=account_id,
            source_artist=item.source_artist,
            source_title=item.source_title,
            source_duration=item.source_duration,
            result={
                "uri": item.spotify_uri,
                "name": item.spotify_name,
                "artist": item.spotify_artist,
                "score": item.score,
                "match_type": item.match_type,
                "score_reasons": list(item.score_reasons),
                "spotify_release": item.spotify_release,
                "spotify_duration": item.spotify_duration,
                "availability_status": item.availability_status,
                "availability_reason": item.availability_reason,
                "availability_checked_at": item.availability_checked_at,
                "availability_source": item.availability_source,
            },
        )
        return ApprovalConflict(**conflict) if conflict else None

    def local_audio_approval_conflict(
        self, item: PublicationItem, account_id: str,
    ) -> ApprovalConflict | None:
        if item.local_evidence_id is None:
            return None
        conflict = self._cache.fingerprint_approval_conflict(
            evidence_id=item.local_evidence_id,
            account_id=account_id,
            spotify_uri=item.spotify_uri,
            source_artist=item.source_artist,
            source_title=item.source_title,
            source_duration=item.source_duration,
        )
        return ApprovalConflict(**conflict) if conflict else None

    def has_local_audio_observation(
        self, track: Track, algorithm: str, algorithm_version: str,
    ) -> bool:
        return any(
            item.get("source_track_id") == track.track_id
            and item.get("algorithm") == algorithm
            and item.get("algorithm_version") == algorithm_version
            for item in self._cache.fingerprint_observations.values()
        )

    def local_audio_observation(
        self, evidence_id: str,
    ) -> LocalAudioObservation | None:
        item = self._cache.fingerprint_observation(evidence_id)
        if item is None:
            return None
        return LocalAudioObservation.available(
            fingerprint=item["fingerprint"],
            algorithm=item["algorithm"],
            algorithm_version=item["algorithm_version"],
            duration=item["audio_duration"],
        )

    def approval_conflict(self, item: PublicationItem) -> bool:
        retained = self._cache.lookup(
            item.source_artist,
            item.source_title,
            100,
            item.source_duration,
        )
        conflicts_with_approved = bool(
            retained is not None
            and retained.approval_status == ApprovalStatus.APPROVED.value
            and retained.spotify_uri
            and retained.spotify_uri != item.spotify_uri
        )
        return conflicts_with_approved or any(
            conflict.get("source_artist") == item.source_artist
            and conflict.get("source_title") == item.source_title
            and int(conflict.get("source_duration", 0)) == item.source_duration
            and conflict.get("proposed_spotify_uri") == item.spotify_uri
            for conflict in self._cache.approval_conflicts
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

    def retain_local_audio(
        self, track: Track, observation: LocalAudioObservation,
    ) -> str:
        raise ValueError("Local audio identity requires durable matching knowledge")

    def lookup_local_audio(
        self, observation: LocalAudioObservation, account_id: str,
    ) -> dict | None:
        return None

    def approve_local_audio(
        self, item: PublicationItem, account_id: str,
    ) -> ApprovalConflict | None:
        return None

    def revoke_local_audio(
        self, item: PublicationItem, account_id: str,
    ) -> None:
        pass

    def has_local_audio_observation(
        self, track: Track, algorithm: str, algorithm_version: str,
    ) -> bool:
        return False

    def local_audio_observation(
        self, evidence_id: str,
    ) -> LocalAudioObservation | None:
        return None

    def approval_conflict(self, item: PublicationItem) -> bool:
        return False

    def local_audio_approval_conflict(
        self, item: PublicationItem, account_id: str,
    ) -> ApprovalConflict | None:
        return None


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
        local_audio=None,
        local_audition=None,
    ) -> None:
        self._source = source
        self._spotify = spotify
        self._knowledge = matching_knowledge
        self._publishing_guards = publishing_guards
        self._publication_storage = publication_storage
        self._transfer_storage = transfer_storage
        self._retry_policy = retry_policy or RetryPolicy()
        self._local_audio = local_audio
        self._local_audition = local_audition
        self._pause_requested = False

    @staticmethod
    def private_source_authorization_requirement(
        authorization: TransferAuthorization | None,
    ) -> str | None:
        """Own the policy for access to private source material."""
        return (
            None
            if authorization is not None and authorization.private_source
            else "private_source"
        )

    @staticmethod
    def authorization_requirement(
        request: BatchPlanRequest,
        authorization: TransferAuthorization,
        *,
        phase: str,
    ) -> str | None:
        """Return the next missing authority; adapters only render the result."""
        if phase == "plan":
            return Transfer.private_source_authorization_requirement(authorization)
        required = Transfer.required_authorizations(
            request, authorization, phase=phase,
        )
        return required[0] if required else None

    @staticmethod
    def required_authorizations(
        request: BatchPlanRequest,
        authorization: TransferAuthorization,
        *,
        phase: str,
    ) -> tuple[str, ...]:
        """Return all missing authorities for a bounded Transfer phase."""
        private_required = Transfer.private_source_authorization_requirement(
            authorization,
        )
        if private_required:
            return (private_required,)
        if (
            phase in {"plan", "execute"}
            and not request.preview
            and not authorization.spotify_write
        ):
            return ("spotify_write",)
        return ()

    def pause(self) -> None:
        """Request a pause after the current track reaches a safe checkpoint."""
        self._pause_requested = True

    def local_audio_capability(self):
        """Inspect optional local identity support without consuming a source."""
        if self._local_audio is None:
            from djsupport.local_audio import LocalAudioCapability

            return LocalAudioCapability(
                available=False, reason="not_configured",
            )
        return self._local_audio.capability()

    def local_audition_capability(self):
        """Inspect audition support without opening source media."""
        if self._local_audition is None:
            from djsupport.local_audition import LocalAuditionCapability

            return LocalAuditionCapability(
                available=False, reason="not_configured",
            )
        return self._local_audition.capability()

    def prepare(self, request: TransferRequest) -> str:
        """Durably reserve a Transfer ID before potentially slow source intake."""
        if self._transfer_storage is None:
            raise ValueError("Preparation requires durable Transfer storage")
        if request.mode is None:
            request = replace(
                request,
                mode=getattr(self._source, "default_mode", TransferMode.SNAPSHOT),
            )
        transfer_id = request.transfer_id or uuid4().hex
        state = self._transfer_storage.load_transfer(transfer_id)
        if state is not None:
            if state.source != request.source:
                raise ValueError("A resumed Transfer must use its original source")
            if state.account_id != self._spotify.account_id():
                raise ValueError("A Transfer cannot resume under another Spotify account")
            if state.status == TransferStatus.PAUSED:
                state.status = TransferStatus.MATCHING
                state.outcome = None
                self._save_transfer(transfer_id, state)
            return transfer_id
        state = TransferState(
            status=TransferStatus.MATCHING,
            source=request.source,
            account_id=self._spotify.account_id(),
            request=self._stored_request(request),
            selection={},
            created_at=datetime.now().isoformat(),
            next_track_index=0,
            matched=[], unmatched=[], publication_items=[], alternatives=[],
        )
        self._save_transfer(transfer_id, state)
        return transfer_id

    def progress(self, transfer_id: str) -> TransferProgress:
        """Reload observable progress without consuming or resuming the source."""
        if self._transfer_storage is None:
            raise ValueError("Progress requires durable Transfer storage")
        state = self._transfer_storage.load_transfer(transfer_id)
        if state is None:
            raise ValueError(f"Unknown Transfer: {transfer_id}")
        if state.account_id != self._spotify.account_id():
            raise ValueError("A Transfer cannot be viewed under another Spotify account")
        return TransferProgress(
            transfer_id=transfer_id,
            source=state.source,
            status=state.status,
            current=state.next_track_index,
            total=len(state.selection.get("tracks", ())),
            error=state.outcome if state.status == TransferStatus.PAUSED else None,
            retain_matching_knowledge=state.request.get(
                "retain_matching_knowledge", True,
            ),
            local_audio_identity=state.request.get("local_audio_identity", False),
            local_audio_audition=state.request.get("local_audio_audition", False),
        )

    def batch_progress(self, transfer_id: str) -> BatchProgress:
        """Reload aggregate Batch progress without consuming its source."""
        if self._transfer_storage is None:
            raise ValueError("Progress requires durable Transfer storage")
        batch = self._transfer_storage.load_batch(transfer_id)
        if batch is None:
            raise ValueError(f"Unknown Batch: {transfer_id}")
        if (
            batch.account_id is not None
            and batch.account_id != self._spotify.account_id()
        ):
            raise ValueError("A Batch cannot be viewed under another Spotify account")
        return BatchProgress(
            transfer_id=transfer_id,
            status=batch.status,
            playlists=len(batch.playlists),
            completed=sum(
                item.outcome == PlaylistOutcome.COMPLETED
                for item in batch.playlists
            ),
            failed=sum(
                item.outcome == PlaylistOutcome.FAILED
                for item in batch.playlists
            ),
            pending=sum(
                item.outcome in (PlaylistOutcome.PENDING, PlaylistOutcome.SKIPPED)
                for item in batch.playlists
            ),
        )

    @staticmethod
    def _stored_request(request: TransferRequest) -> dict:
        assert request.mode is not None
        return {
            "source": request.source,
            "mode": request.mode.value,
            "preview": request.preview,
            "threshold": request.threshold,
            "retry": request.retry,
            "retry_days": request.retry_days,
            "playlist_prefix": request.playlist_prefix,
            "drift_resolution": (
                request.drift_resolution.value if request.drift_resolution else None
            ),
            "mirror_disposition": (
                request.mirror_disposition.value
                if request.mirror_disposition else None
            ),
            "mirror_playlist_id": request.mirror_playlist_id,
            "retain_matching_knowledge": request.retain_matching_knowledge,
            "local_audio_identity": request.local_audio_identity,
            "local_audio_audition": request.local_audio_audition,
        }

    @staticmethod
    def _stored_track(track: Track, *, include_location: bool) -> dict:
        """Serialize a track without touching its private location by default."""
        stored = {
            "track_id": track.track_id,
            "name": track.name,
            "artist": track.artist,
            "album": track.album,
            "remixer": track.remixer,
            "label": track.label,
            "genre": track.genre,
            "date_added": track.date_added,
            "duration": track.duration,
            "version": track.version,
        }
        if include_location:
            stored["location"] = track.location
        return stored

    @classmethod
    def _selection_token(
        cls, selection: SourceSelection, *, include_locations: bool,
    ) -> str:
        material = [
            cls._stored_track(track, include_location=include_locations)
            for track in selection.tracks
        ]
        return hashlib.sha256(json.dumps(
            material, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()

    def plan_batch(self, request: BatchPlanRequest) -> BatchPlan:
        """Plan an explicitly selected Rekordbox Batch without side effects."""
        if request.local_audio_identity and not getattr(
            self._knowledge, "persistent", True,
        ):
            raise ValueError(
                "Local audio identity requires durable matching knowledge; "
                "remove --no-cache"
            )
        selections = self._source.consume_batch(
            request.playlist_references, request.whole_library,
        )
        local_capability = (
            self.local_audio_capability() if request.local_audio_identity else None
        )
        playlists = []
        for selection in selections:
            selection_token = self._selection_token(
                selection,
                include_locations=(
                    request.local_audio_identity
                    or request.local_audio_audition
                ),
            )
            approved_match_hits = 0
            cache_hits = 0
            expected_uncached_lookups = 0
            local_audio_eligible = 0
            local_audio_indexed = 0
            local_audio_pending = 0
            local_audio_unavailable = 0
            for track in selection.tracks:
                known = self._knowledge.lookup(track, request.threshold)
                if known is not None and known.get("authoritative"):
                    approved_match_hits += 1
                elif known is not None or not self._knowledge.should_retry(
                    track, request.threshold, 7, False,
                ):
                    cache_hits += 1
                else:
                    expected_uncached_lookups += 1
                if request.local_audio_identity:
                    status = "not_configured"
                    if local_capability is not None and local_capability.available:
                        status = self._local_audio.preflight(track)
                    if status == "eligible":
                        local_audio_eligible += 1
                        indexed = self._knowledge.has_local_audio_observation(
                            track,
                            local_capability.algorithm,
                            local_capability.algorithm_version or "unknown",
                        )
                        if indexed:
                            local_audio_indexed += 1
                        else:
                            local_audio_pending += 1
                    else:
                        local_audio_unavailable += 1
            playlists.append(PlaylistPreflight(
                name=selection.name,
                reference=selection.reference,
                total_tracks=len(selection.tracks),
                approved_match_hits=approved_match_hits,
                cache_hits=cache_hits,
                expected_uncached_lookups=expected_uncached_lookups,
                local_audio_eligible=local_audio_eligible,
                local_audio_indexed=local_audio_indexed,
                local_audio_pending=local_audio_pending,
                local_audio_unavailable=local_audio_unavailable,
                selection_token=selection_token,
            ))
        expected_lookups = sum(
            playlist.expected_uncached_lookups for playlist in playlists
        )
        return BatchPlan(
            tuple(playlists),
            confirmation_required=(
                (
                    request.whole_library
                    or expected_lookups >= EXPENSIVE_BATCH_LOOKUP_THRESHOLD
                )
                and not request.confirm_expensive
            ),
            threshold=request.threshold,
            preview=request.preview,
            retry=request.retry,
            retry_days=request.retry_days,
            playlist_prefix=request.playlist_prefix,
            local_audio_identity=request.local_audio_identity,
            local_audio_audition=request.local_audio_audition,
        )

    def execute_batch(
        self, plan: BatchPlan, *, transfer_id: str | None = None,
    ) -> SyncReport:
        """Execute and durably checkpoint each planned Rekordbox playlist."""
        if not plan.preview and self._publication_storage is None:
            raise ValueError("Publishing Transfers require publication storage")
        if not plan.ready:
            raise ValueError("An expensive Batch must be confirmed before execution")
        if self._transfer_storage is None:
            raise ValueError("Batch execution requires durable Transfer storage")
        batch_id = transfer_id or uuid4().hex
        batch = self._load_or_create_batch(batch_id, plan)
        try:
            account_id = self._spotify.account_id()
        except Exception as exc:
            if not self._is_shared_failure(exc):
                raise
            batch.status = BatchStatus.PAUSED
            self._transfer_storage.save_batch(batch_id, batch)
            authentication_actions = {
                PlaylistOutcome.COMPLETED: (
                    "completed before shared authentication failure"
                ),
                PlaylistOutcome.FAILED: "failed before shared authentication failure",
                PlaylistOutcome.SKIPPED: "skipped after shared failure",
                PlaylistOutcome.PENDING: "pending: shared authentication failure",
            }
            playlists = [
                self._batch_playlist_report(
                    item, authentication_actions[item.outcome], item.outcome,
                )
                for item in batch.playlists
            ]
            report_status = (
                BatchStatus.PARTIAL_SUCCESS
                if any(
                    item.outcome == PlaylistOutcome.COMPLETED
                    for item in batch.playlists
                )
                else BatchStatus.PAUSED
            )
            return self._batch_report(
                batch_id, batch, playlists, report_status,
            )
        if batch.account_id is None:
            batch.account_id = account_id
            self._transfer_storage.save_batch(batch_id, batch)
        elif batch.account_id != account_id:
            raise ValueError("A Batch cannot resume under another Spotify account")
        with self._publishing_guards.acquire(account_id):
            return self._execute_batch(batch_id, batch)

    def _load_or_create_batch(
        self, batch_id: str, plan: BatchPlan,
    ) -> BatchState:
        assert self._transfer_storage is not None
        batch = self._transfer_storage.load_batch(batch_id)
        if batch is None:
            batch = BatchState(
                account_id=None,
                created_at=datetime.now().isoformat(),
                threshold=plan.threshold,
                status=BatchStatus.MATCHING,
                preview=plan.preview,
                retry=plan.retry,
                retry_days=plan.retry_days,
                playlist_prefix=plan.playlist_prefix,
                local_audio_identity=plan.local_audio_identity,
                local_audio_audition=plan.local_audio_audition,
                plan_id=plan.batch_id,
                playlists=[
                    BatchPlaylistState(
                        planned.name, planned.reference, f"{batch_id}:{index}",
                        selection_token=planned.selection_token,
                    )
                    for index, planned in enumerate(plan.playlists)
                ],
            )
            self._transfer_storage.save_batch(batch_id, batch)
        elif batch.plan_id and batch.plan_id != plan.batch_id:
            raise ValueError("A resumed Batch must use its original plan")
        elif [item.reference for item in batch.playlists] != [
            item.reference for item in plan.playlists
        ]:
            raise ValueError("A resumed Batch must use its original plan")
        elif not batch.plan_id:
            raise ValueError(
                "A legacy Batch without a bounded plan identity must be restarted"
            )
        return batch

    def _execute_batch(self, batch_id: str, batch: BatchState) -> SyncReport:
        assert self._transfer_storage is not None
        playlists: list[PlaylistReport] = []
        for index, item in enumerate(batch.playlists):
            try:
                report = self._execute(TransferRequest(
                    source=item.reference,
                    mode=TransferMode.MIRROR,
                    preview=batch.preview,
                    threshold=batch.threshold,
                    retry=batch.retry,
                    retry_days=batch.retry_days,
                    playlist_prefix=batch.playlist_prefix,
                    transfer_id=item.transfer_id,
                    local_audio_identity=batch.local_audio_identity,
                    local_audio_audition=batch.local_audio_audition,
                ), expected_selection_token=item.selection_token)
            except Exception as exc:
                if not self._is_shared_failure(exc) and not self._is_playlist_failure(exc):
                    raise
                shared_failure = self._is_shared_failure(exc)
                item.phase = BatchPhase.PAUSED if shared_failure else BatchPhase.FAILED
                item.outcome = (
                    PlaylistOutcome.PENDING
                    if shared_failure else PlaylistOutcome.FAILED
                )
                item.error = str(exc)
                playlists.append(self._batch_playlist_report(
                    item, str(exc), item.outcome,
                ))
                if shared_failure:
                    for pending in batch.playlists[index + 1:]:
                        pending.phase = BatchPhase.PENDING
                        pending.outcome = PlaylistOutcome.SKIPPED
                        playlists.append(self._batch_playlist_report(
                            pending, "skipped after shared failure",
                            PlaylistOutcome.SKIPPED,
                        ))
                    batch.status = BatchStatus.PAUSED
                    self._transfer_storage.save_batch(batch_id, batch)
                    break
            else:
                if report.status == "paused":
                    item.phase = BatchPhase.PAUSED
                    item.outcome = PlaylistOutcome.PENDING
                    report.playlists[0].outcome = PlaylistOutcome.PENDING.value
                    playlists.extend(report.playlists)
                    for pending in batch.playlists[index + 1:]:
                        pending.phase = BatchPhase.PENDING
                        pending.outcome = PlaylistOutcome.PENDING
                        playlists.append(self._batch_playlist_report(
                            pending, "pending", PlaylistOutcome.PENDING,
                        ))
                    batch.status = BatchStatus.PAUSED
                    self._transfer_storage.save_batch(batch_id, batch)
                    break
                item.phase = BatchPhase.COMPLETED
                item.outcome = PlaylistOutcome.COMPLETED
                item.error = None
                report.playlists[0].outcome = item.outcome.value
                playlists.extend(report.playlists)
                self._transfer_storage.save_batch(batch_id, batch)
        completed = sum(
            playlist.outcome == PlaylistOutcome.COMPLETED for playlist in playlists
        )
        failed = sum(
            playlist.outcome == PlaylistOutcome.FAILED for playlist in playlists
        )
        pending = sum(
            playlist.outcome == PlaylistOutcome.PENDING for playlist in playlists
        )
        skipped = sum(
            playlist.outcome == PlaylistOutcome.SKIPPED for playlist in playlists
        )
        status = (
            BatchStatus.PAUSED if pending and not completed
            else BatchStatus.PARTIAL_SUCCESS if completed and (failed or pending or skipped)
            else BatchStatus.FAILED if failed or skipped
            else BatchStatus.COMPLETED
        )
        batch.status = (
            BatchStatus.PAUSED
            if any(item.phase == BatchPhase.PAUSED for item in batch.playlists)
            else status
        )
        self._transfer_storage.save_batch(batch_id, batch)
        return self._batch_report(batch_id, batch, playlists, status)

    def _batch_report(
        self, batch_id: str, batch: BatchState,
        playlists: list[PlaylistReport], status: BatchStatus,
    ) -> SyncReport:
        return SyncReport(
            timestamp=datetime.fromisoformat(batch.created_at),
            threshold=batch.threshold, dry_run=batch.preview,
            playlists=playlists,
            cache_enabled=getattr(self._knowledge, "persistent", True),
            source_label=self._source.source_label,
            transfer_id=batch_id,
            status=status.value,
        )

    def _batch_playlist_report(
        self, item: BatchPlaylistState, action: str,
        outcome: PlaylistOutcome,
    ) -> PlaylistReport:
        report = PlaylistReport(
            name=item.name, path=item.reference, action=action,
            outcome=outcome.value,
        )
        state = (
            self._transfer_storage.load_transfer(item.transfer_id)
            if self._transfer_storage is not None else None
        )
        if state is None:
            return report
        report.matched = [MatchedTrack(**matched) for matched in state.matched]
        report.unmatched = list(state.unmatched)
        report.api_lookups = state.api_lookups
        report.local_audio_eligible = state.local_audio_eligible
        report.local_audio_observed = state.local_audio_observed
        report.local_audio_unavailable = state.local_audio_unavailable
        report.local_audio_reused = state.local_audio_reused
        report.alternatives = [
            UnmatchedAlternatives(
                source_track_id=alternative["source_track_id"],
                source_name=alternative["source_name"],
                candidates=tuple(
                    AlternativeCandidate(**candidate)
                    for candidate in alternative["candidates"]
                ),
            )
            for alternative in state.alternatives
        ]
        report.spotify_playlist_id = state.spotify_playlist_id
        return report

    @staticmethod
    def _is_shared_failure(exc: Exception) -> bool:
        if isinstance(exc, (RateLimitError, requests.Timeout, requests.ConnectionError)):
            return True
        return isinstance(exc, spotipy.SpotifyException) and (
            exc.http_status in (401, 403, 429)
            or exc.http_status is None
            or exc.http_status >= 500
        )

    @staticmethod
    def _is_playlist_failure(exc: Exception) -> bool:
        return isinstance(exc, (ValueError, SourceNotFound)) or (
            isinstance(exc, spotipy.SpotifyException)
            and exc.http_status is not None
            and 400 <= exc.http_status < 500
        )

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
        if self._local_audition is not None and hasattr(
            self._local_audition, "invalidate_transfer"
        ):
            self._local_audition.invalidate_transfer(transfer_id)

    def obtain_qualification(
        self,
        request: QualificationRequest,
        authorization: TransferAuthorization,
    ) -> QualificationView:
        """Obtain or resume one non-authoritative Rekordbox draft."""
        required = self.private_source_authorization_requirement(authorization)
        if required:
            raise PermissionError(required)
        if self._source.source_label != "Rekordbox":
            raise ValueError(
                "Qualification is available only for Rekordbox Mirrors"
            )
        if self._transfer_storage is None or not all(
            hasattr(self._transfer_storage, method)
            for method in ("load_qualification", "save_qualification")
        ):
            raise ValueError("Qualification requires durable Transfer storage")
        if hasattr(self._transfer_storage, "refresh"):
            self._transfer_storage.refresh()
        child_id, batch_id, state = self._qualification_transfer(request)
        if state.status != TransferStatus.COMPLETED:
            raise ValueError("Qualification requires a completed Transfer")
        if state.request.get("mode") != TransferMode.MIRROR.value:
            raise ValueError(
                "Qualification is available only for Rekordbox Mirrors"
            )
        initial_source_reference = state.selection.get("reference")
        if not initial_source_reference:
            raise ValueError("Qualification source selection is unavailable")
        draft_id = hashlib.sha256(
            f"qualification\0{child_id}\0{initial_source_reference}".encode()
        ).hexdigest()
        draft = self._transfer_storage.load_qualification(draft_id)
        seen_drafts: set[str] = set()
        while draft is not None and draft.superseded_by is not None:
            if draft.draft_id in seen_drafts:
                raise SpotifyPlaylistReviewRequired(
                    "Qualification Draft lineage is invalid; review required",
                    draft_id=draft.draft_id,
                )
            seen_drafts.add(draft.draft_id)
            successor = self._transfer_storage.load_qualification(
                draft.superseded_by
            )
            if successor is None:
                raise SpotifyPlaylistReviewRequired(
                    "Qualification Draft successor is unavailable; review required",
                    draft_id=draft.draft_id,
                )
            draft = successor
            draft_id = successor.draft_id
        if draft is not None and draft.transfer_id != child_id:
            linked_state = self._transfer_storage.load_transfer(
                draft.transfer_id
            )
            if linked_state is not None:
                child_id = draft.transfer_id
                batch_id = draft.batch_id
                state = linked_state
        source_reference = state.selection.get("reference")
        if not source_reference:
            raise ValueError("Qualification source selection is unavailable")
        selection_digest = self._qualification_selection_digest(state.selection)
        manifest_digest = self._qualification_manifest_digest(state)
        account_id = self._spotify.account_id()
        if state.account_id != account_id:
            raise ValueError(
                "A Qualification Draft cannot resume under another Spotify account"
            )
        playlist_head = None
        if state.spotify_playlist_id and hasattr(self._spotify, "playlist_head"):
            playlist_head = self._retry_policy.run(
                lambda: self._spotify.playlist_head(
                    state.spotify_playlist_id  # type: ignore[arg-type]
                ).snapshot_id
            )
        if (
            draft is None
            and state.spotify_playlist_id is not None
            and hasattr(
                self._transfer_storage, "qualifications_for_playlist"
            )
        ):
            linked = [
                candidate
                for candidate in self._transfer_storage.qualifications_for_playlist(
                    account_id, state.spotify_playlist_id,
                )
                if candidate.transfer_id == child_id
                and candidate.source_reference == source_reference
                and candidate.superseded_by is None
            ]
            if len(linked) > 1:
                raise SpotifyPlaylistReviewRequired(
                    "Multiple Qualification Drafts claim this bounded Transfer; "
                    "review required"
                )
            if linked:
                draft = linked[0]
                draft_id = draft.draft_id
        items = self._qualification_items(state, None)
        requested_ids = [
            item.item_id for item in items
            if request.include_all or item.attention_reasons
        ]
        now = datetime.now().isoformat()
        if draft is None:
            draft = QualificationDraftState(
                draft_id=draft_id,
                transfer_id=child_id,
                batch_id=batch_id,
                source_reference=source_reference,
                account_id=account_id,
                playlist_id=state.spotify_playlist_id,
                playlist_head=playlist_head,
                manifest_digest=manifest_digest,
                selection_digest=selection_digest,
                include_all=request.include_all,
                item_ids=requested_ids,
                decisions={},
                status=QualificationStatus.DRAFT,
                created_at=now,
                updated_at=now,
                audition_selection_digest=state.audition_selection_digest,
            )
        else:
            if draft.account_id != account_id:
                raise ValueError(
                    "A Qualification Draft cannot resume under another Spotify account"
                )
            recoverable_manifest = (
                draft.status in {
                    QualificationStatus.APPLYING,
                    QualificationStatus.PAUSED,
                }
                and draft.applied_manifest is not None
                and manifest_digest == self._publication_digest(
                    self._publication_from_stored(draft.applied_manifest)
                )
            )
            if (
                draft.transfer_id != child_id
                or draft.source_reference != source_reference
                or draft.selection_digest != selection_digest
                or (
                    draft.manifest_digest != manifest_digest
                    and not recoverable_manifest
                )
                or draft.playlist_id != state.spotify_playlist_id
            ):
                draft.status = QualificationStatus.REVIEW_REQUIRED
                draft.review_reason = "evidence_changed"
                draft.updated_at = now
                self._transfer_storage.save_qualification(draft_id, draft)
                raise SpotifyPlaylistReviewRequired(
                    "Qualification evidence changed; create a new bounded review",
                    draft_id=draft_id,
                )
            if (
                draft.playlist_head is not None
                and playlist_head is not None
                and draft.playlist_head != playlist_head
                and draft.status not in {
                    QualificationStatus.APPLYING,
                    QualificationStatus.PAUSED,
                    QualificationStatus.APPLIED,
                    QualificationStatus.APPROVING,
                    QualificationStatus.APPROVED,
                    QualificationStatus.DISCARDED,
                }
            ):
                draft.status = QualificationStatus.REVIEW_REQUIRED
                draft.review_reason = "evidence_changed"
                draft.updated_at = now
                self._transfer_storage.save_qualification(draft_id, draft)
                raise SpotifyPlaylistReviewRequired(
                    "Spotify playlist changed; Qualification review required",
                    draft_id=draft_id,
                )
            draft.include_all = draft.include_all or request.include_all
            selected_ids = [
                item.item_id for item in items
                if draft.include_all or item.attention_reasons
            ]
            draft.item_ids = list(dict.fromkeys([
                *draft.item_ids, *selected_ids,
            ]))
            draft.updated_at = now
            if draft.status in {
                QualificationStatus.APPLYING,
                QualificationStatus.PAUSED,
                QualificationStatus.APPLIED,
                QualificationStatus.APPROVING,
                QualificationStatus.APPROVED,
                QualificationStatus.DISCARDED,
            }:
                return self._qualification_view(draft, state)
        try:
            self._preflight_qualification_audition(draft, state)
        except SpotifyPlaylistReviewRequired as exc:
            exc.draft_id = draft_id
            raise
        view = self._qualification_view(draft, state)
        draft.status = (
            QualificationStatus.READY if view.complete
            else QualificationStatus.DRAFT
        )
        draft.updated_at = now
        self._transfer_storage.save_qualification(draft_id, draft)
        return self._qualification_view(draft, state)

    def qualification(
        self,
        draft_id: str,
        authorization: TransferAuthorization | None = None,
    ) -> QualificationView:
        """Render one durable draft without inferring any outcome."""
        required = self.private_source_authorization_requirement(authorization)
        if required:
            raise PermissionError(required)
        if self._transfer_storage is None or not hasattr(
            self._transfer_storage, "load_qualification"
        ):
            raise ValueError("Qualification requires durable Transfer storage")
        if hasattr(self._transfer_storage, "refresh"):
            self._transfer_storage.refresh()
        draft = self._transfer_storage.load_qualification(draft_id)
        if draft is None:
            raise ValueError(f"Unknown Qualification Draft: {draft_id}")
        if draft.account_id != self._spotify.account_id():
            raise ValueError(
                "A Qualification Draft cannot be viewed under another Spotify account"
            )
        state = self._transfer_storage.load_transfer(draft.transfer_id)
        if state is None:
            raise ValueError("Qualification Transfer evidence is unavailable")
        return self._qualification_view(draft, state)

    def link_qualification(
        self,
        draft_id: str,
        publishing_transfer_id: str,
        authorization: TransferAuthorization,
    ) -> QualificationView:
        """Link one Preview draft to a distinct, equivalent Provisional Mirror."""
        required = self.private_source_authorization_requirement(authorization)
        if required:
            raise PermissionError(required)
        if self._transfer_storage is None or self._publication_storage is None:
            raise ValueError(
                "Qualification linking requires durable Transfer and publication state"
            )
        account_id = self._spotify.account_id()
        with self._publishing_guards.acquire(account_id):
            if hasattr(self._transfer_storage, "refresh"):
                self._transfer_storage.refresh()
            if hasattr(self._publication_storage, "load"):
                self._publication_storage.load()
            draft = self._transfer_storage.load_qualification(draft_id)
            if draft is None:
                raise ValueError(f"Unknown Qualification Draft: {draft_id}")
            if draft.account_id != account_id:
                raise ValueError(
                    "A Qualification Draft cannot be linked under another account"
                )
            if draft.playlist_id is not None:
                raise ValueError(
                    "A Qualification Draft is already linked to a Provisional Playlist"
                )
            if draft.status in {
                QualificationStatus.APPLYING,
                QualificationStatus.PAUSED,
                QualificationStatus.APPLIED,
                QualificationStatus.APPROVING,
                QualificationStatus.APPROVED,
                QualificationStatus.DISCARDED,
            }:
                raise ValueError(
                    "This Qualification Draft cannot be linked in its current state"
                )
            preview_state = self._transfer_storage.load_transfer(
                draft.transfer_id
            )
            if preview_state is None or not preview_state.request.get(
                "preview", False,
            ):
                raise ValueError(
                    "Only a Preview Qualification Draft requires explicit linking"
                )
            if (
                self._qualification_manifest_digest(preview_state)
                != draft.manifest_digest
            ):
                draft.status = QualificationStatus.REVIEW_REQUIRED
                draft.review_reason = "evidence_changed"
                draft.updated_at = datetime.now().isoformat()
                self._transfer_storage.save_qualification(draft_id, draft)
                raise SpotifyPlaylistReviewRequired(
                    "Preview Qualification evidence changed; review required",
                    draft_id=draft_id,
                )
            target_id, target_batch_id, target_state = (
                self._qualification_transfer(QualificationRequest(
                    transfer_id=publishing_transfer_id,
                    playlist_reference=draft.source_reference,
                    include_all=draft.include_all,
                ))
            )
            if target_id == draft.transfer_id:
                raise ValueError(
                    "Preview and publishing Transfers must remain distinct"
                )
            if (
                target_state.status != TransferStatus.COMPLETED
                or target_state.request.get("preview", False)
                or target_state.request.get("mode") != TransferMode.MIRROR.value
                or target_state.spotify_playlist_id is None
            ):
                raise ValueError(
                    "Qualification linking requires a completed Provisional Mirror"
                )
            if target_state.account_id != account_id:
                raise ValueError(
                    "A Qualification Draft cannot be linked under another account"
                )
            target_selection_digest = self._qualification_selection_digest(
                target_state.selection
            )
            if target_selection_digest != draft.selection_digest:
                raise SpotifyPlaylistReviewRequired(
                    "Publishing Transfer source evidence differs from the Preview",
                    draft_id=draft_id,
                )
            if (
                bool(preview_state.request.get("local_audio_audition", False))
                != bool(target_state.request.get("local_audio_audition", False))
                or draft.audition_selection_digest
                != target_state.audition_selection_digest
            ):
                raise SpotifyPlaylistReviewRequired(
                    "Publishing Transfer audition intent or evidence differs",
                    draft_id=draft_id,
                )
            try:
                current_selection = self._source.consume(
                    draft.source_reference
                )
            except Exception as exc:
                draft.status = QualificationStatus.REVIEW_REQUIRED
                draft.review_reason = "evidence_changed"
                draft.updated_at = datetime.now().isoformat()
                self._transfer_storage.save_qualification(draft_id, draft)
                raise SpotifyPlaylistReviewRequired(
                    "Rekordbox source evidence is unavailable; review required",
                    draft_id=draft_id,
                ) from exc
            current_public = {
                "reference": current_selection.reference,
                "tracks": [
                    self._stored_track(track, include_location=False)
                    for track in current_selection.tracks
                ],
            }
            if (
                self._qualification_selection_digest(current_public)
                != draft.selection_digest
                or (
                    draft.audition_selection_digest is not None
                    and self._qualification_audition_digest(current_selection)
                    != draft.audition_selection_digest
                )
            ):
                raise SpotifyPlaylistReviewRequired(
                    "Rekordbox source selection changed; review required",
                    draft_id=draft_id,
                )
            target_manifest = self._publication_storage.publication_for_playlist(
                account_id, target_state.spotify_playlist_id,
            )
            if target_manifest is None or self._publication_digest(
                target_manifest
            ) != self._qualification_manifest_digest(target_state):
                raise SpotifyPlaylistReviewRequired(
                    "Provisional publication evidence changed; review required",
                    draft_id=draft_id,
                )
            other_drafts = [
                candidate
                for candidate in self._transfer_storage.qualifications_for_playlist(
                    account_id, target_state.spotify_playlist_id,
                )
                if candidate.draft_id != draft_id
                and candidate.status not in {
                    QualificationStatus.APPLIED,
                    QualificationStatus.APPROVING,
                    QualificationStatus.APPROVED,
                    QualificationStatus.DISCARDED,
                }
            ]
            if other_drafts:
                raise SpotifyPlaylistReviewRequired(
                    "The Provisional Playlist already has a Qualification Draft",
                    draft_id=draft_id,
                )

            preview_items = {
                (item.source_index, item.source_track_id): item
                for item in self._qualification_items(preview_state, None)
            }
            target_items = {
                (item.source_index, item.source_track_id): item
                for item in self._qualification_items(target_state, None)
            }
            preview_by_id = {
                item.item_id: item for item in preview_items.values()
            }
            mapped_ids: dict[str, str] = {}
            for old_item_id in draft.item_ids:
                old_item = preview_by_id.get(old_item_id)
                if old_item is None:
                    raise SpotifyPlaylistReviewRequired(
                        "Preview Qualification evidence is incomplete",
                        draft_id=draft_id,
                    )
                target_item = target_items.get((
                    old_item.source_index, old_item.source_track_id,
                ))
                if target_item is None:
                    raise SpotifyPlaylistReviewRequired(
                        "Publishing Transfer source evidence differs from the Preview",
                        draft_id=draft_id,
                    )
                if old_item_id in draft.decisions and (
                    old_item.spotify_uri,
                    old_item.spotify_name,
                    old_item.spotify_artist,
                    old_item.spotify_release,
                    old_item.spotify_duration,
                    old_item.score,
                    old_item.match_type,
                    old_item.score_reasons,
                    old_item.authority_status,
                    old_item.attention_reasons,
                    old_item.availability_status,
                    old_item.availability_reason,
                    old_item.availability_checked_at,
                    old_item.availability_source,
                ) != (
                    target_item.spotify_uri,
                    target_item.spotify_name,
                    target_item.spotify_artist,
                    target_item.spotify_release,
                    target_item.spotify_duration,
                    target_item.score,
                    target_item.match_type,
                    target_item.score_reasons,
                    target_item.authority_status,
                    target_item.attention_reasons,
                    target_item.availability_status,
                    target_item.availability_reason,
                    target_item.availability_checked_at,
                    target_item.availability_source,
                ):
                    raise SpotifyPlaylistReviewRequired(
                        "A reviewed Spotify proposal changed before linking",
                        draft_id=draft_id,
                    )
                mapped_ids[old_item_id] = target_item.item_id

            selected_target_ids = [
                item.item_id for item in target_items.values()
                if draft.include_all or item.attention_reasons
            ]
            old_transfer_id = draft.transfer_id
            draft.transfer_id = target_id
            draft.batch_id = target_batch_id
            draft.playlist_id = target_state.spotify_playlist_id
            draft.playlist_head = self._retry_policy.run(
                lambda: self._spotify.playlist_head(
                    target_state.spotify_playlist_id  # type: ignore[arg-type]
                )
            ).snapshot_id
            draft.manifest_digest = self._publication_digest(target_manifest)
            draft.selection_digest = target_selection_digest
            draft.item_ids = list(dict.fromkeys([
                *(mapped_ids[item_id] for item_id in draft.item_ids),
                *selected_target_ids,
            ]))
            draft.decisions = {
                mapped_ids[item_id]: decision
                for item_id, decision in draft.decisions.items()
            }
            draft.audition_statuses = {}
            if self._local_audition is not None and hasattr(
                self._local_audition, "invalidate_transfer"
            ):
                self._local_audition.invalidate_transfer(old_transfer_id)
            self._preflight_qualification_audition(draft, target_state)
            linked_view = self._qualification_view(draft, target_state)
            draft.status = (
                QualificationStatus.READY
                if linked_view.complete else QualificationStatus.DRAFT
            )
            draft.updated_at = datetime.now().isoformat()
            self._transfer_storage.save_qualification(draft_id, draft)
            return self._qualification_view(draft, target_state)

    def _qualification_transfer(
        self, request: QualificationRequest,
    ) -> tuple[str, str | None, TransferState]:
        assert self._transfer_storage is not None
        batch = self._transfer_storage.load_batch(request.transfer_id)
        batch_id = request.transfer_id if batch is not None else None
        if batch is not None:
            candidates = [
                item for item in batch.playlists
                if request.playlist_reference is not None
                and item.reference == request.playlist_reference
            ]
            if not candidates:
                raise ValueError(
                    "Select one playlist from the completed Rekordbox Batch"
                )
            if len(candidates) != 1:
                raise ValueError("Qualification playlist selection is ambiguous")
            child_id = candidates[0].transfer_id
        else:
            child_id = request.transfer_id
        state = self._transfer_storage.load_transfer(child_id)
        if state is None:
            raise ValueError(f"Unknown Transfer: {request.transfer_id}")
        if (
            request.playlist_reference is not None
            and state.selection.get("reference") != request.playlist_reference
        ):
            raise ValueError("Qualification playlist is outside the selected Batch")
        return child_id, batch_id, state

    @classmethod
    def _qualification_selection_digest(cls, selection: dict) -> str:
        track_defaults = {
            "track_id": "",
            "name": "",
            "artist": "",
            "album": "",
            "remixer": "",
            "label": "",
            "genre": "",
            "date_added": "",
            "duration": 0,
            "version": "",
        }
        private_safe = {
            "reference": selection.get("reference"),
            "tracks": [
                {
                    key: track.get(key, default)
                    for key, default in track_defaults.items()
                }
                for track in selection.get("tracks", ())
            ],
        }
        return hashlib.sha256(json.dumps(
            private_safe, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()

    @classmethod
    def _qualification_audition_digest(cls, selection: SourceSelection) -> str:
        """Bind audition to exact selected locations without retaining them."""
        return cls._selection_token(selection, include_locations=True)

    @classmethod
    def _qualification_manifest_digest(cls, state: TransferState) -> str:
        if state.publication_manifest is not None:
            evidence = cls._stored_publication(
                cls._publication_from_stored(state.publication_manifest)
            )
        else:
            evidence = {
                "preview_items": [
                    asdict(PublicationItem(**item))
                    for item in state.publication_items
                ],
                "playlist_id": state.spotify_playlist_id,
            }
        return hashlib.sha256(json.dumps(
            evidence, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()

    @staticmethod
    def _availability_facts(result: dict, *, source: str) -> dict:
        """Normalize truthful availability without treating omission as proof."""
        retained_status = result.get("availability_status")
        if retained_status in {"available", "unavailable", "unknown"}:
            return {
                "availability_status": retained_status,
                "availability_reason": result.get("availability_reason"),
                "availability_checked_at": result.get(
                    "availability_checked_at"
                ),
                "availability_source": result.get(
                    "availability_source", source,
                ),
            }
        playable = result.get("is_playable")
        if playable is True:
            status, reason = "available", None
        elif playable is False:
            status, reason = "unavailable", "spotify_unavailable"
        else:
            status, reason = "unknown", "not_checked"
        return {
            "availability_status": status,
            "availability_reason": reason,
            "availability_checked_at": (
                datetime.now().isoformat()
                if isinstance(playable, bool) else None
            ),
            "availability_source": source,
        }

    def _qualification_items(
        self,
        state: TransferState,
        draft: QualificationDraftState | None,
    ) -> list[QualificationItem]:
        publication_items = [
            PublicationItem(**item) for item in state.publication_items
        ]
        source_identities_by_uri: dict[
            str, set[tuple[str, str, int]]
        ] = {}
        for item in publication_items:
            if item.spotify_uri:
                source_identities_by_uri.setdefault(item.spotify_uri, set()).add((
                    item.source_artist.casefold(),
                    item.source_title.casefold(),
                    item.source_duration,
                ))
        collision_uris = {
            uri for uri, identities in source_identities_by_uri.items()
            if len(identities) > 1
        }
        alternative_ids = {
            item.get("source_track_id") for item in state.alternatives
        }
        rendered: list[QualificationItem] = []
        for ordinal, item in enumerate(publication_items):
            source_index = item.source_index if item.occurrence_id else ordinal
            item_id = item.occurrence_id or hashlib.sha256(
                f"{state.source}\0{source_index}\0{item.source_track_id}".encode()
            ).hexdigest()
            authority_status = "approved" if item.authoritative else "proposal"
            decision_data = (
                draft.decisions.get(item_id, {}) if draft is not None else {}
            )
            decision_value = decision_data.get("decision")
            decision = (
                QualificationDecision(decision_value)
                if decision_value is not None else None
            )
            rendered_item = item
            if decision == QualificationDecision.CORRECTION:
                rendered_item = replace(
                    item,
                    spotify_uri=str(decision_data["correction_uri"]),
                    spotify_name=str(decision_data["spotify_name"]),
                    spotify_artist=str(decision_data["spotify_artist"]),
                    spotify_release=str(
                        decision_data.get("spotify_release", "")
                    ),
                    spotify_duration=int(
                        decision_data.get("spotify_duration", 0)
                    ),
                    score=100.0,
                    match_type="correction",
                    score_reasons=("explicit Qualification Correction",),
                    authoritative=False,
                    availability_status=str(
                        decision_data.get("availability_status", "unknown")
                    ),
                    availability_reason=decision_data.get(
                        "availability_reason"
                    ),
                    availability_checked_at=decision_data.get(
                        "availability_checked_at"
                    ),
                    availability_source=decision_data.get(
                        "availability_source"
                    ),
                )
                authority_status = "proposal"
            reasons: list[str] = []
            if decision == QualificationDecision.CORRECTION:
                reasons.append("staged_correction")
            elif not rendered_item.authoritative:
                if rendered_item.spotify_uri:
                    reasons.append("new_proposal")
                else:
                    reasons.append("unresolved")
                if rendered_item.match_type in {
                    "shorter_version", "fallback_version",
                }:
                    reasons.append(rendered_item.match_type)
                if (
                    rendered_item.source_duration > 0
                    and rendered_item.spotify_duration > 0
                    and abs(
                        rendered_item.source_duration
                        - rendered_item.spotify_duration
                    ) > 30
                ):
                    reasons.append("duration_conflict")
                if any(
                    "version" in reason.casefold()
                    and any(marker in reason.casefold() for marker in (
                        "conflict", "differ", "fallback", "shorter", "mismatch",
                    ))
                    for reason in rendered_item.score_reasons
                ):
                    reasons.append("version_conflict")
                if rendered_item.source_track_id in alternative_ids:
                    reasons.append("alternatives")
                if rendered_item.spotify_uri in collision_uris:
                    reasons.append("match_collision")
            conflict_checker = getattr(
                self._knowledge, "approval_conflict", None
            )
            if (
                not rendered_item.authoritative
                and conflict_checker is not None
                and conflict_checker(rendered_item)
            ):
                reasons.append("approval_conflict")
            if decision == QualificationDecision.DEFERRED and not decision_data.get(
                "excluded", False
            ):
                reasons.append("deferred")
            if rendered_item.availability_status == "unavailable":
                reasons.append(
                    rendered_item.availability_reason or "spotify_unavailable"
                )
            permitted_actions = (
                ()
                if draft is not None and draft.status in {
                    QualificationStatus.APPLYING,
                    QualificationStatus.PAUSED,
                    QualificationStatus.APPLIED,
                    QualificationStatus.APPROVING,
                    QualificationStatus.APPROVED,
                    QualificationStatus.DISCARDED,
                }
                or (
                    draft is not None
                    and draft.status == QualificationStatus.REVIEW_REQUIRED
                    and draft.review_reason != "resolvable_conflict"
                )
                else (
                    (
                        QualificationDecision.KEEP_PROPOSAL,
                        QualificationDecision.CORRECTION,
                        QualificationDecision.DEFERRED,
                        QualificationDecision.REJECT_PROPOSAL,
                    )
                    if (
                        item.spotify_uri
                        and item.availability_status != "unavailable"
                    ) else (
                        QualificationDecision.CORRECTION,
                        QualificationDecision.DEFERRED,
                        *(
                            (QualificationDecision.REJECT_PROPOSAL,)
                            if item.spotify_uri else ()
                        ),
                    )
                )
            )
            audition_fact = (
                draft.audition_statuses.get(item_id, {})
                if draft is not None else {}
            )
            audition_status = (
                str(audition_fact.get("status"))
                if audition_fact.get("status")
                else "available_on_request"
                if state.request.get("local_audio_audition")
                and self._local_audition is not None
                else "not_configured"
                if state.request.get("local_audio_audition")
                else "not_requested"
            )
            rendered.append(QualificationItem(
                item_id=item_id,
                source_index=source_index,
                source_track_id=item.source_track_id,
                source_artist=item.source_artist,
                source_title=item.source_title,
                source_release=item.source_release,
                source_label=item.source_label,
                source_version=item.source_version,
                source_duration=item.source_duration,
                spotify_uri=rendered_item.spotify_uri,
                spotify_name=rendered_item.spotify_name,
                spotify_artist=rendered_item.spotify_artist,
                spotify_release=rendered_item.spotify_release,
                spotify_duration=rendered_item.spotify_duration,
                score=rendered_item.score,
                match_type=rendered_item.match_type,
                score_reasons=rendered_item.score_reasons,
                authority_status=authority_status,
                attention_reasons=tuple(dict.fromkeys(reasons)),
                audition_status=audition_status,
                audition_reason=audition_fact.get("reason"),
                decision=decision,
                correction_uri=decision_data.get("correction_uri"),
                deferred_reason=decision_data.get("reason"),
                excluded=bool(decision_data.get("excluded", False)),
                availability_status=rendered_item.availability_status,
                availability_reason=rendered_item.availability_reason,
                availability_checked_at=rendered_item.availability_checked_at,
                availability_source=rendered_item.availability_source,
                permitted_actions=permitted_actions,
            ))
        return rendered

    def _preflight_qualification_audition(
        self, draft: QualificationDraftState, state: TransferState,
    ) -> None:
        if not state.request.get("local_audio_audition", False):
            return
        selection = self._source.consume(draft.source_reference)
        comparison = {
            "reference": selection.reference,
            "tracks": [
                self._stored_track(track, include_location=False)
                for track in selection.tracks
            ],
        }
        if self._qualification_selection_digest(comparison) != draft.selection_digest:
            raise SpotifyPlaylistReviewRequired(
                "Rekordbox source selection changed; audition blocked"
            )
        expected_digest = state.audition_selection_digest
        if draft.audition_selection_digest is None and expected_digest is not None:
            draft.audition_selection_digest = expected_digest
        if expected_digest is None:
            for item_id in draft.item_ids:
                draft.audition_statuses[item_id] = {
                    "status": "unavailable",
                    "reason": "selection_binding_unavailable",
                }
            return
        if (
            draft.audition_selection_digest != expected_digest
            or self._qualification_audition_digest(selection) != expected_digest
        ):
            raise SpotifyPlaylistReviewRequired(
                "Rekordbox source selection changed; audition blocked"
            )
        if (
            self._local_audition is None
            or not hasattr(self._local_audition, "preflight")
        ):
            return
        items = {
            item.item_id: item
            for item in self._qualification_items(state, draft)
            if item.item_id in draft.item_ids
        }
        for item_id, item in items.items():
            if item.source_index >= len(selection.tracks):
                draft.audition_statuses[item_id] = {
                    "status": "unavailable", "reason": "unselected_source",
                }
                continue
            track = selection.tracks[item.source_index]
            if track.track_id != item.source_track_id:
                draft.audition_statuses[item_id] = {
                    "status": "unavailable", "reason": "unselected_source",
                }
                continue
            result = self._local_audition.preflight(track)
            draft.audition_statuses[item_id] = {
                "status": result.status,
                "reason": result.reason,
            }

    def _qualification_view(
        self, draft: QualificationDraftState, state: TransferState,
    ) -> QualificationView:
        item_by_id = {
            item.item_id: item
            for item in self._qualification_items(state, draft)
        }
        items = tuple(
            item_by_id[item_id]
            for item_id in draft.item_ids
            if item_id in item_by_id
        )
        return QualificationView(
            draft_id=draft.draft_id,
            transfer_id=draft.transfer_id,
            source_reference=draft.source_reference,
            spotify_playlist_id=draft.playlist_id,
            status=draft.status,
            items=items,
            include_all=draft.include_all,
        )

    def record_qualification(
        self,
        draft_id: str,
        item_id: str,
        decision: QualificationDecision,
        authorization: TransferAuthorization | None = None,
        *,
        spotify_reference: str | None = None,
        reason: str | None = None,
        exclude: bool = False,
    ) -> QualificationView:
        """Record or revise one draft outcome without creating authority."""
        required = self.private_source_authorization_requirement(authorization)
        if required:
            raise PermissionError(required)
        if self._transfer_storage is None or not hasattr(
            self._transfer_storage, "load_qualification"
        ):
            raise ValueError("Qualification requires durable Transfer storage")
        if hasattr(self._transfer_storage, "refresh"):
            self._transfer_storage.refresh()
        draft = self._transfer_storage.load_qualification(draft_id)
        if draft is None:
            raise ValueError(f"Unknown Qualification Draft: {draft_id}")
        if draft.status in {
            QualificationStatus.APPLYING,
            QualificationStatus.PAUSED,
            QualificationStatus.APPLIED,
            QualificationStatus.APPROVING,
            QualificationStatus.APPROVED,
            QualificationStatus.DISCARDED,
        } or (
            draft.status == QualificationStatus.REVIEW_REQUIRED
            and draft.review_reason != "resolvable_conflict"
        ):
            raise ValueError(
                "A Qualification Draft cannot be revised after application starts"
            )
        if draft.account_id != self._spotify.account_id():
            raise ValueError(
                "A Qualification Draft cannot be revised under another Spotify account"
            )
        state = self._transfer_storage.load_transfer(draft.transfer_id)
        if state is None:
            raise ValueError("Qualification Transfer evidence is unavailable")
        items = {
            item.item_id: item
            for item in self._qualification_items(state, draft)
        }
        if item_id not in draft.item_ids or item_id not in items:
            raise ValueError("Qualification item is outside the selected playlist")
        item = items[item_id]
        if decision not in item.permitted_actions:
            raise ValueError(
                "Qualification outcome is unavailable for this proposal"
            )
        if exclude and decision != QualificationDecision.DEFERRED:
            raise ValueError("Only a deferred item can be explicitly excluded")
        stored: dict[str, object] = {
            "decision": decision.value,
            "updated_at": datetime.now().isoformat(),
        }
        if decision == QualificationDecision.CORRECTION:
            if spotify_reference is None:
                raise ValueError("A staged Correction requires a Spotify track URL or URI")
            spotify_uri = self._spotify_uri(spotify_reference, 1)
            if spotify_uri == item.spotify_uri:
                raise ValueError(
                    "A staged Correction must select a different Spotify track"
                )
            spotify_track = self._retry_policy.run(
                lambda: self._spotify.spotify_track(spotify_uri)
            )
            if spotify_track.get("uri") != spotify_uri:
                raise ValueError("The staged Correction did not resolve to its Spotify track")
            if (
                spotify_track.get("is_playable") is False
                or spotify_track.get("is_local") is True
                or bool(spotify_track.get("restrictions"))
                or spotify_track.get("linked_from") is not None
                or spotify_track.get("linked_from_uri") is not None
            ):
                raise ValueError(
                    "The staged Correction is not an available Spotify track"
                )
            stored.update({
                "correction_uri": spotify_uri,
                "spotify_name": spotify_track["name"],
                "spotify_artist": spotify_track["artist"],
                "spotify_release": spotify_track.get("album", ""),
                "spotify_duration": int(
                    spotify_track.get("duration_ms", 0)
                ) // 1000,
                **self._availability_facts(
                    spotify_track, source="spotify_track_lookup",
                ),
            })
        elif decision == QualificationDecision.DEFERRED:
            stored.update({
                "reason": reason.strip() if reason and reason.strip() else None,
                "excluded": exclude,
            })
        draft.decisions[item_id] = stored
        draft.updated_at = datetime.now().isoformat()
        view = self._qualification_view(draft, state)
        draft.status = (
            QualificationStatus.READY if view.complete
            else QualificationStatus.DRAFT
        )
        draft.review_reason = None
        self._transfer_storage.save_qualification(draft_id, draft)
        return self._qualification_view(draft, state)

    def audition_qualification(
        self,
        draft_id: str,
        item_id: str,
        authorization: TransferAuthorization,
    ) -> LocalAuditionResult:
        """Open only one exact selected source occurrence after authorization."""
        required = self.private_source_authorization_requirement(authorization)
        if required:
            raise PermissionError(required)
        if self._local_audition is None:
            return LocalAuditionResult.unavailable("not_configured")
        if self._transfer_storage is None or not hasattr(
            self._transfer_storage, "load_qualification"
        ):
            raise ValueError("Qualification requires durable Transfer storage")
        if hasattr(self._transfer_storage, "refresh"):
            self._transfer_storage.refresh()
        draft = self._transfer_storage.load_qualification(draft_id)
        if draft is None:
            raise ValueError(f"Unknown Qualification Draft: {draft_id}")
        if draft.status == QualificationStatus.DISCARDED:
            raise ValueError(
                "A discarded Qualification Draft cannot audition source media"
            )
        if draft.account_id != self._spotify.account_id():
            raise ValueError(
                "A Qualification Draft cannot be auditioned under another Spotify account"
            )
        state = self._transfer_storage.load_transfer(draft.transfer_id)
        if state is None:
            raise ValueError("Qualification Transfer evidence is unavailable")
        if not state.request.get("local_audio_audition", False):
            return LocalAuditionResult.unavailable("not_requested")
        view_items = {
            item.item_id: item
            for item in self._qualification_items(state, draft)
            if item.item_id in draft.item_ids
        }
        if item_id not in view_items:
            raise ValueError(
                "Audition item is outside the selected Qualification playlist"
            )
        item = view_items[item_id]
        selection = self._source.consume(draft.source_reference)
        comparison = {
            "reference": selection.reference,
            "tracks": [
                self._stored_track(track, include_location=False)
                for track in selection.tracks
            ],
        }
        if self._qualification_selection_digest(comparison) != draft.selection_digest:
            raise SpotifyPlaylistReviewRequired(
                "Rekordbox source selection changed; audition blocked"
            )
        expected_digest = state.audition_selection_digest
        if expected_digest is None:
            return LocalAuditionResult.unavailable(
                "selection_binding_unavailable"
            )
        if (
            draft.audition_selection_digest != expected_digest
            or self._qualification_audition_digest(selection) != expected_digest
        ):
            raise SpotifyPlaylistReviewRequired(
                "Rekordbox source selection changed; audition blocked"
            )
        if item.source_index >= len(selection.tracks):
            raise ValueError("Audition item is outside the selected source")
        selected_track = selection.tracks[item.source_index]
        if selected_track.track_id != item.source_track_id:
            raise ValueError("Audition item is outside the selected source")
        result = self._local_audition.open(
            draft.transfer_id, item_id, selected_track,
        )
        draft.audition_statuses[item_id] = {
            "status": result.status,
            "reason": result.reason,
        }
        self._transfer_storage.save_qualification(draft_id, draft)
        return result

    def discard_qualification(
        self,
        draft_id: str,
        authorization: TransferAuthorization,
    ) -> QualificationView:
        """Explicitly retire an unapplied draft without creating authority."""
        required = self.private_source_authorization_requirement(authorization)
        if required:
            raise PermissionError(required)
        if self._transfer_storage is None:
            raise ValueError("Qualification requires durable Transfer storage")
        if hasattr(self._transfer_storage, "refresh"):
            self._transfer_storage.refresh()
        draft = self._transfer_storage.load_qualification(draft_id)
        if draft is None:
            raise ValueError(f"Unknown Qualification Draft: {draft_id}")
        if draft.account_id != self._spotify.account_id():
            raise ValueError(
                "A Qualification Draft cannot be discarded under another account"
            )
        if draft.status in {
            QualificationStatus.APPLYING,
            QualificationStatus.PAUSED,
            QualificationStatus.APPLIED,
            QualificationStatus.APPROVING,
            QualificationStatus.APPROVED,
        }:
            raise ValueError(
                "A Qualification Draft cannot be discarded after application starts"
            )
        state = self._transfer_storage.load_transfer(draft.transfer_id)
        if state is None:
            raise ValueError("Qualification Transfer evidence is unavailable")
        draft.status = QualificationStatus.DISCARDED
        draft.updated_at = datetime.now().isoformat()
        self._transfer_storage.save_qualification(draft_id, draft)
        if self._local_audition is not None and hasattr(
            self._local_audition, "invalidate_transfer"
        ):
            self._local_audition.invalidate_transfer(draft.transfer_id)
        return self._qualification_view(draft, state)

    def supersede_qualification(
        self,
        draft_id: str,
        authorization: TransferAuthorization,
    ) -> QualificationView:
        """Explicitly start fresh from one discarded draft's current evidence."""
        required = self.private_source_authorization_requirement(authorization)
        if required:
            raise PermissionError(required)
        if self._transfer_storage is None:
            raise ValueError("Qualification requires durable Transfer storage")
        if hasattr(self._transfer_storage, "refresh"):
            self._transfer_storage.refresh()
        old = self._transfer_storage.load_qualification(draft_id)
        if old is None:
            raise ValueError(f"Unknown Qualification Draft: {draft_id}")
        if old.status != QualificationStatus.DISCARDED:
            raise ValueError(
                "Only an explicitly discarded Qualification Draft can be superseded"
            )
        if old.superseded_by is not None:
            existing = self._transfer_storage.load_qualification(
                old.superseded_by
            )
            if existing is None:
                raise SpotifyPlaylistReviewRequired(
                    "Qualification supersession is incomplete; review required",
                    draft_id=draft_id,
                )
            state = self._transfer_storage.load_transfer(existing.transfer_id)
            if state is None:
                raise ValueError("Qualification Transfer evidence is unavailable")
            return self._qualification_view(existing, state)
        account_id = self._spotify.account_id()
        if old.account_id != account_id:
            raise ValueError(
                "A Qualification Draft cannot be superseded under another account"
            )
        state = self._transfer_storage.load_transfer(old.transfer_id)
        if state is None or state.status != TransferStatus.COMPLETED:
            raise ValueError("Qualification Transfer evidence is unavailable")
        current_selection = self._source.consume(old.source_reference)
        current_public = {
            "reference": current_selection.reference,
            "tracks": [
                self._stored_track(track, include_location=False)
                for track in current_selection.tracks
            ],
        }
        selection_digest = self._qualification_selection_digest(current_public)
        if selection_digest != self._qualification_selection_digest(state.selection):
            raise SpotifyPlaylistReviewRequired(
                "Rekordbox source selection changed; execute a new bounded Transfer",
                draft_id=draft_id,
            )
        audition_digest = state.audition_selection_digest
        if (
            audition_digest is not None
            and self._qualification_audition_digest(current_selection)
            != audition_digest
        ):
            raise SpotifyPlaylistReviewRequired(
                "Rekordbox audition selection changed; execute a new bounded Transfer",
                draft_id=draft_id,
            )
        manifest_digest = self._qualification_manifest_digest(state)
        if old.playlist_id is not None:
            if self._publication_storage is None:
                raise ValueError(
                    "Qualification requires durable publication state"
                )
            if hasattr(self._publication_storage, "load"):
                self._publication_storage.load()
            manifest = self._publication_storage.publication_for_playlist(
                account_id, old.playlist_id,
            )
            if (
                manifest is None
                or self._publication_digest(manifest) != manifest_digest
            ):
                raise SpotifyPlaylistReviewRequired(
                    "Publication evidence changed; execute a new bounded Transfer",
                    draft_id=draft_id,
                )
        playlist_head = None
        if old.playlist_id is not None and hasattr(self._spotify, "playlist_head"):
            playlist_head = self._retry_policy.run(
                lambda: self._spotify.playlist_head(old.playlist_id)
            ).snapshot_id
        items = self._qualification_items(state, None)
        item_ids = [
            item.item_id for item in items
            if old.include_all or item.attention_reasons
        ]
        now = datetime.now().isoformat()
        new_id = hashlib.sha256(
            f"qualification\0{old.transfer_id}\0{old.source_reference}\0{uuid4().hex}".encode()
        ).hexdigest()
        fresh = QualificationDraftState(
            draft_id=new_id,
            transfer_id=old.transfer_id,
            batch_id=old.batch_id,
            source_reference=old.source_reference,
            account_id=account_id,
            playlist_id=old.playlist_id,
            playlist_head=playlist_head,
            manifest_digest=manifest_digest,
            selection_digest=selection_digest,
            include_all=old.include_all,
            item_ids=item_ids,
            decisions={},
            status=QualificationStatus.DRAFT,
            created_at=now,
            updated_at=now,
            audition_selection_digest=audition_digest,
            supersedes=old.draft_id,
        )
        self._preflight_qualification_audition(fresh, state)
        view = self._qualification_view(fresh, state)
        fresh.status = (
            QualificationStatus.READY if view.complete
            else QualificationStatus.DRAFT
        )
        old.superseded_by = new_id
        old.updated_at = now
        if not hasattr(
            self._transfer_storage, "save_qualification_successor"
        ):
            raise ValueError(
                "Qualification supersession requires transactional storage"
            )
        self._transfer_storage.save_qualification_successor(old, fresh)
        return self._qualification_view(fresh, state)

    def approve_qualification(
        self,
        draft_id: str,
        authorization: TransferAuthorization,
    ) -> ApprovalOutcome:
        """Approve an applied draft as a distinct playlist-scoped operation."""
        required = self.private_source_authorization_requirement(authorization)
        if required:
            raise PermissionError(required)
        if self._transfer_storage is None:
            raise ValueError("Qualification requires durable Transfer storage")
        draft = self._transfer_storage.load_qualification(draft_id)
        if draft is None:
            raise ValueError(f"Unknown Qualification Draft: {draft_id}")
        if draft.approval_outcome is not None:
            return self._approval_from_stored(draft.approval_outcome)
        if draft.status == QualificationStatus.APPROVING:
            raise SpotifyPlaylistReviewRequired(
                "Qualification Approval was interrupted; review retained "
                "authority before any retry",
                draft_id=draft_id,
            )
        if draft.status != QualificationStatus.APPLIED:
            raise SpotifyPlaylistReviewRequired(
                "Qualification Draft must be applied before Approval",
                draft_id=draft_id,
            )
        draft.status = QualificationStatus.APPROVING
        draft.updated_at = datetime.now().isoformat()
        self._transfer_storage.save_qualification(draft_id, draft)
        outcome = self._approve(
            None, qualification_draft_id=draft_id,
        )
        draft = self._transfer_storage.load_qualification(draft_id)
        if draft is None:
            raise ValueError(f"Unknown Qualification Draft: {draft_id}")
        draft.status = (
            QualificationStatus.APPROVED
            if outcome.status == ApprovalStatus.APPROVED
            else QualificationStatus.REVIEW_REQUIRED
        )
        draft.review_reason = (
            None
            if outcome.status == ApprovalStatus.APPROVED
            else "approval_needs_review"
        )
        draft.approval_outcome = self._stored_approval(outcome)
        draft.updated_at = datetime.now().isoformat()
        self._transfer_storage.save_qualification(draft_id, draft)
        return outcome

    def apply_qualification(
        self,
        draft_id: str,
        authorization: TransferAuthorization,
    ) -> QualificationApplyOutcome:
        """Apply a complete draft to its Provisional Playlist, never Approval."""
        required = self.private_source_authorization_requirement(authorization)
        if required:
            raise PermissionError(required)
        if not authorization.spotify_write:
            raise PermissionError("spotify_write")
        if self._transfer_storage is None or not hasattr(
            self._transfer_storage, "load_qualification"
        ):
            raise ValueError("Qualification requires durable Transfer storage")
        if self._publication_storage is None:
            raise ValueError("Qualification application requires publication storage")
        account_id = self._spotify.account_id()
        with self._publishing_guards.acquire(account_id):
            if hasattr(self._transfer_storage, "refresh"):
                self._transfer_storage.refresh()
            draft = self._transfer_storage.load_qualification(draft_id)
            if draft is None:
                raise ValueError(f"Unknown Qualification Draft: {draft_id}")
            if draft.account_id != account_id:
                raise ValueError(
                    "A Qualification Draft cannot be applied under another "
                    "Spotify account"
                )
            if draft.status == QualificationStatus.DISCARDED:
                raise ValueError("A discarded Qualification Draft cannot be applied")
            if draft.status == QualificationStatus.APPROVING:
                raise SpotifyPlaylistReviewRequired(
                    "Qualification Approval was interrupted; review required",
                    draft_id=draft_id,
                )
            if draft.status in {
                QualificationStatus.APPLIED,
                QualificationStatus.APPROVED,
            }:
                assert draft.playlist_id is not None
                next_actions = (
                    ("approve",)
                    if draft.status == QualificationStatus.APPLIED else ()
                )
                return QualificationApplyOutcome(
                    draft_id, draft.playlist_id, draft.status,
                    len((draft.applied_manifest or {}).get("managed_items", ())),
                    next_actions,
                )
            if draft.playlist_id is None:
                raise SpotifyPlaylistReviewRequired(
                    "Preview Qualification Draft must be linked to a distinct "
                    "Provisional Mirror before apply",
                    draft_id=draft_id,
                )
            if hasattr(self._publication_storage, "load"):
                self._publication_storage.load()
            if hasattr(self._knowledge, "refresh"):
                self._knowledge.refresh()
            state = self._transfer_storage.load_transfer(draft.transfer_id)
            if state is None:
                raise ValueError("Qualification Transfer evidence is unavailable")
            view = self._qualification_view(draft, state)
            if not view.complete:
                raise ValueError(
                    "Qualification Draft has pending or deferred items"
                )
            unresolved_approval_conflicts = []
            for item in view.items:
                if "approval_conflict" not in item.attention_reasons:
                    continue
                decision = draft.decisions.get(item.item_id, {})
                choice = decision.get("decision")
                resolved = choice in {
                    QualificationDecision.CORRECTION.value,
                    QualificationDecision.REJECT_PROPOSAL.value,
                } or (
                    choice == QualificationDecision.DEFERRED.value
                    and bool(decision.get("excluded"))
                )
                if not resolved:
                    unresolved_approval_conflicts.append(item.item_id)
            if unresolved_approval_conflicts:
                draft.status = QualificationStatus.REVIEW_REQUIRED
                draft.review_reason = "resolvable_conflict"
                self._transfer_storage.save_qualification(draft_id, draft)
                raise SpotifyPlaylistReviewRequired(
                    "Qualification conflict remains unresolved",
                    draft_id=draft_id,
                )

            try:
                current_selection = self._source.consume(
                    draft.source_reference
                )
            except Exception as exc:
                draft.status = QualificationStatus.REVIEW_REQUIRED
                draft.review_reason = "evidence_changed"
                draft.updated_at = datetime.now().isoformat()
                self._transfer_storage.save_qualification(draft_id, draft)
                raise SpotifyPlaylistReviewRequired(
                    "Rekordbox source evidence is unavailable; review required",
                    draft_id=draft_id,
                ) from exc
            selection = {
                "reference": current_selection.reference,
                "tracks": [
                    self._stored_track(track, include_location=False)
                    for track in current_selection.tracks
                ],
            }
            if (
                self._qualification_selection_digest(selection)
                != draft.selection_digest
                or (
                    draft.audition_selection_digest is not None
                    and (
                        state.audition_selection_digest
                        != draft.audition_selection_digest
                        or self._qualification_audition_digest(current_selection)
                        != draft.audition_selection_digest
                    )
                )
            ):
                draft.status = QualificationStatus.REVIEW_REQUIRED
                draft.review_reason = "evidence_changed"
                self._transfer_storage.save_qualification(draft_id, draft)
                raise SpotifyPlaylistReviewRequired(
                    "Rekordbox source selection changed; review required",
                    draft_id=draft_id,
                )

            intended_manifest = (
                self._publication_from_stored(draft.applied_manifest)
                if draft.applied_manifest is not None else None
            )
            current_manifest = (
                self._publication_storage.publication_for_playlist(
                    account_id, draft.playlist_id,
                )
                if draft.playlist_id is not None else None
            )
            expected_head = (
                draft.mutation_snapshots[-1]
                if draft.mutation_snapshots else draft.playlist_head
            )
            if (
                expected_head is not None
                and hasattr(self._spotify, "playlist_head")
            ):
                current_head = self._retry_policy.run(
                    lambda: self._spotify.playlist_head(draft.playlist_id)
                )
                if current_head.snapshot_id != expected_head:
                    draft.status = QualificationStatus.REVIEW_REQUIRED
                    draft.review_reason = "evidence_changed"
                    self._transfer_storage.save_qualification(draft_id, draft)
                    raise SpotifyPlaylistChanged(
                        "Spotify playlist changed before Qualification apply"
                    )
            if current_manifest is not None:
                current_digest = self._publication_digest(current_manifest)
                if current_digest != draft.manifest_digest:
                    if (
                        intended_manifest is not None
                        and draft.status in {
                            QualificationStatus.APPLYING,
                            QualificationStatus.PAUSED,
                        }
                        and current_digest
                        == self._publication_digest(intended_manifest)
                    ):
                        state.publication_manifest = self._stored_publication(
                            intended_manifest
                        )
                        state.status = TransferStatus.COMPLETED
                        self._save_transfer(draft.transfer_id, state)
                        draft.manifest_digest = current_digest
                        draft.status = QualificationStatus.APPLIED
                        if draft.mutation_snapshots:
                            draft.playlist_head = draft.mutation_snapshots[-1]
                        self._transfer_storage.save_qualification(draft_id, draft)
                        return QualificationApplyOutcome(
                            draft_id, draft.playlist_id,
                            QualificationStatus.APPLIED,
                            len(intended_manifest.managed_items), ("approve",),
                        )
                    draft.status = QualificationStatus.REVIEW_REQUIRED
                    draft.review_reason = "evidence_changed"
                    self._transfer_storage.save_qualification(draft_id, draft)
                    raise SpotifyPlaylistReviewRequired(
                        "Publication manifest changed; review required",
                        draft_id=draft_id,
                    )
            else:
                draft.status = QualificationStatus.REVIEW_REQUIRED
                draft.review_reason = "evidence_changed"
                self._transfer_storage.save_qualification(draft_id, draft)
                raise SpotifyPlaylistReviewRequired(
                    "The linked Provisional Playlist manifest is unavailable",
                    draft_id=draft_id,
                )
            if intended_manifest is not None and draft.applied_uris:
                updated_manifest = intended_manifest
                desired_uris = list(draft.applied_uris)
            else:
                updated_manifest, desired_uris = self._qualification_application(
                    draft, state, current_manifest,
                )
            conflict_checker = getattr(
                self._knowledge, "approval_conflict", None,
            )
            if (
                conflict_checker is not None
                and any(
                    item.match_type == "correction" and conflict_checker(item)
                    for item in updated_manifest.managed_items
                )
            ):
                draft.status = QualificationStatus.REVIEW_REQUIRED
                draft.review_reason = "resolvable_conflict"
                self._transfer_storage.save_qualification(draft_id, draft)
                raise SpotifyPlaylistReviewRequired(
                    "Qualification Correction conflicts with an Approved Match",
                    draft_id=draft_id,
                )
            identities_by_uri: dict[str, set[tuple[str, str, int]]] = {}
            for item in updated_manifest.managed_items:
                identities_by_uri.setdefault(item.spotify_uri, set()).add((
                    item.source_artist.casefold(),
                    item.source_title.casefold(),
                    item.source_duration,
                ))
            if any(
                len(identities) > 1
                for identities in identities_by_uri.values()
            ):
                draft.status = QualificationStatus.REVIEW_REQUIRED
                draft.review_reason = "resolvable_conflict"
                self._transfer_storage.save_qualification(draft_id, draft)
                raise SpotifyPlaylistReviewRequired(
                    "Qualification conflict remains unresolved",
                    draft_id=draft_id,
                )
            if not draft.applied_uris:
                preservation_manifest = current_manifest
                if draft.completed_chunks and intended_manifest is not None:
                    preservation_manifest = intended_manifest
                desired_uris = self._preserve_unmanaged_playlist_items(
                    draft.playlist_id, preservation_manifest, desired_uris,
                )
            draft.applied_manifest = self._stored_publication(updated_manifest)
            draft.applied_uris = list(desired_uris)
            draft.status = QualificationStatus.APPLYING
            draft.updated_at = datetime.now().isoformat()
            self._transfer_storage.save_qualification(draft_id, draft)

            paused = self._apply_qualification_chunks(draft, desired_uris)
            if paused:
                return QualificationApplyOutcome(
                    draft_id, draft.playlist_id, QualificationStatus.PAUSED,
                    len(updated_manifest.managed_items), ("resume",),
                )
            self._publication_storage.retain_publication(updated_manifest)
            state.publication_manifest = self._stored_publication(updated_manifest)
            state.spotify_playlist_id = draft.playlist_id
            state.spotify_playlist_name = updated_manifest.spotify_playlist_name
            state.status = TransferStatus.COMPLETED
            self._save_transfer(draft.transfer_id, state)
            draft.manifest_digest = self._publication_digest(updated_manifest)
            draft.status = QualificationStatus.APPLIED
            if draft.mutation_snapshots:
                draft.playlist_head = draft.mutation_snapshots[-1]
            draft.updated_at = datetime.now().isoformat()
            self._transfer_storage.save_qualification(draft_id, draft)
            return QualificationApplyOutcome(
                draft_id, draft.playlist_id, QualificationStatus.APPLIED,
                len(updated_manifest.managed_items), ("approve",),
            )

    @staticmethod
    def _stored_publication(manifest: PublicationManifest) -> dict:
        stored = asdict(manifest)
        stored["created_at"] = manifest.created_at.isoformat()
        return stored

    @staticmethod
    def _publication_from_stored(stored: dict) -> PublicationManifest:
        return PublicationManifest(**{
            **stored,
            "mode": TransferMode(
                stored.get("mode", TransferMode.SNAPSHOT.value)
            ),
            "created_at": datetime.fromisoformat(stored["created_at"]),
            "items": tuple(
                PublicationItem(**item) for item in stored.get("items", ())
            ),
            "managed_items": tuple(
                PublicationItem(**item)
                for item in stored.get("managed_items", stored.get("items", ()))
            ),
        })

    @staticmethod
    def _stored_approval(outcome: ApprovalOutcome) -> dict:
        stored = asdict(outcome)
        stored["reviewed_at"] = outcome.reviewed_at.isoformat()
        stored["status"] = outcome.status.value
        return stored

    @staticmethod
    def _approval_from_stored(stored: dict) -> ApprovalOutcome:
        return ApprovalOutcome(**{
            **stored,
            "reviewed_at": datetime.fromisoformat(stored["reviewed_at"]),
            "status": ApprovalStatus(stored["status"]),
            "approved": tuple(
                PublicationItem(**item) for item in stored.get("approved", ())
            ),
            "rejected": tuple(
                PublicationItem(**item) for item in stored.get("rejected", ())
            ),
            "collisions": tuple(
                PublicationItem(**item)
                for item in stored.get("collisions", ())
            ),
            "corrections": tuple(
                PublicationItem(**item)
                for item in stored.get("corrections", ())
            ),
            "conflicts": tuple(
                ApprovalConflict(**item) for item in stored.get("conflicts", ())
            ),
        })

    @classmethod
    def _publication_digest(cls, manifest: PublicationManifest) -> str:
        return hashlib.sha256(json.dumps(
            cls._stored_publication(manifest),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()).hexdigest()

    def _qualification_application(
        self,
        draft: QualificationDraftState,
        state: TransferState,
        manifest: PublicationManifest,
    ) -> tuple[PublicationManifest, list[str]]:
        all_items = [PublicationItem(**item) for item in state.publication_items]
        decision_by_id = draft.decisions
        desired_items: list[PublicationItem] = []
        review_items: list[PublicationItem] = []
        original_review_ids = {
            item.occurrence_id or item.source_track_id for item in manifest.items
        }
        for ordinal, item in enumerate(all_items):
            item_id = item.occurrence_id or hashlib.sha256(
                f"{state.source}\0{ordinal}\0{item.source_track_id}".encode()
            ).hexdigest()
            decision = decision_by_id.get(item_id)
            resolved = item
            excluded = False
            rejected = False
            if decision is not None:
                choice = QualificationDecision(decision["decision"])
                if choice == QualificationDecision.CORRECTION:
                    resolved = replace(
                        item,
                        spotify_uri=str(decision["correction_uri"]),
                        spotify_name=str(decision["spotify_name"]),
                        spotify_artist=str(decision["spotify_artist"]),
                        spotify_release=str(decision.get("spotify_release", "")),
                        spotify_duration=int(
                            decision.get("spotify_duration", 0)
                        ),
                        score=100.0,
                        match_type="correction",
                        score_reasons=("explicit Qualification Correction",),
                        authoritative=False,
                        availability_status=str(
                            decision.get("availability_status", "unknown")
                        ),
                        availability_reason=decision.get(
                            "availability_reason"
                        ),
                        availability_checked_at=decision.get(
                            "availability_checked_at"
                        ),
                        availability_source=decision.get(
                            "availability_source"
                        ),
                        qualification_outcome=choice.value,
                    )
                elif choice == QualificationDecision.REJECT_PROPOSAL:
                    rejected = True
                    resolved = replace(
                        item, qualification_outcome=choice.value,
                    )
                elif choice == QualificationDecision.DEFERRED:
                    excluded = bool(decision.get("excluded"))
                    resolved = replace(
                        item, qualification_outcome=choice.value,
                    )
                else:
                    resolved = replace(
                        item, qualification_outcome=choice.value,
                    )
            if resolved.spotify_uri and not rejected and not excluded:
                desired_items.append(resolved)
            was_review_item = (
                item.occurrence_id or item.source_track_id
            ) in original_review_ids
            if excluded:
                continue
            if (
                was_review_item
                or decision is not None
                or resolved.match_type == "correction"
            ):
                review_items.append(resolved)
        updated = replace(
            manifest,
            items=tuple(review_items),
            managed_items=tuple(desired_items),
        )
        return updated, [item.spotify_uri for item in desired_items]

    def _preserve_unmanaged_playlist_items(
        self,
        playlist_id: str,
        manifest: PublicationManifest,
        desired_uris: list[str],
    ) -> list[str]:
        if hasattr(self._spotify, "ordered_playlist_items"):
            ordered = self._retry_policy.run(
                lambda: self._spotify.ordered_playlist_items(playlist_id)
            )
            if any(
                item.kind != SpotifyItemKind.TRACK
                or item.is_playable is False
                or item.restrictions is not None
                or item.linked_from_uri is not None
                for item in ordered.items
            ):
                raise SpotifyPlaylistReviewRequired(
                    "Spotify playlist contains unavailable, unsupported, "
                    "restricted, or relinked items; review required"
                )
            current_uris = [item.uri for item in ordered.items if item.uri]
        else:
            current_uris = self._retry_policy.run(
                lambda: self._spotify.provisional_playlist_track_uris(playlist_id)
            ) or []
        managed = Counter(
            item.spotify_uri for item in (manifest.managed_items or manifest.items)
            if item.spotify_uri
        )
        manual_by_boundary: dict[int, list[str]] = {}
        managed_seen = 0
        for uri in current_uris:
            if managed[uri] > 0:
                managed[uri] -= 1
                managed_seen += 1
                continue
            boundary = min(managed_seen, len(desired_uris))
            manual_by_boundary.setdefault(boundary, []).append(uri)
        repaired: list[str] = []
        for boundary in range(len(desired_uris) + 1):
            repaired.extend(manual_by_boundary.get(boundary, ()))
            if boundary < len(desired_uris):
                repaired.append(desired_uris[boundary])
        return repaired

    def _apply_qualification_chunks(
        self, draft: QualificationDraftState, uris: list[str],
    ) -> bool:
        assert self._transfer_storage is not None
        assert draft.playlist_id is not None
        chunks = [uris[:100]] + [
            uris[offset:offset + 100] for offset in range(100, len(uris), 100)
        ]
        for index, chunk in enumerate(chunks):
            chunk_id = hashlib.sha256(json.dumps(
                [index, chunk], separators=(",", ":"),
            ).encode()).hexdigest()
            if chunk_id in draft.completed_chunks:
                continue
            expected_head = (
                draft.mutation_snapshots[-1]
                if draft.mutation_snapshots else draft.playlist_head
            )
            if expected_head is not None and hasattr(self._spotify, "playlist_head"):
                current = self._retry_policy.run(
                    lambda: self._spotify.playlist_head(draft.playlist_id)
                )
                if current.snapshot_id != expected_head:
                    raise SpotifyPlaylistChanged(
                        "Spotify playlist changed during Qualification apply"
                    )
            if all(hasattr(self._spotify, method) for method in (
                "replace_items", "add_items",
            )):
                result = self._retry_policy.run(
                    lambda: (
                        self._spotify.replace_items(draft.playlist_id, chunk)
                        if index == 0 else self._spotify.add_items(
                            draft.playlist_id, chunk,
                        )
                    )
                )
                snapshot_id = result.snapshot_id
            else:
                if index > 0:
                    raise ValueError(
                        "Qualification application requires checkpointed playlist writes"
                    )
                self._retry_policy.run(
                    lambda: self._spotify.replace_provisional_playlist_tracks(
                        draft.playlist_id, chunk,
                    )
                )
                snapshot_id = (
                    self._spotify.playlist_head(draft.playlist_id).snapshot_id
                    if hasattr(self._spotify, "playlist_head") else ""
                )
            draft.mutation_snapshots.append(snapshot_id)
            draft.completed_chunks.append(chunk_id)
            self._transfer_storage.save_qualification(draft.draft_id, draft)
            if self._pause_requested:
                self._pause_requested = False
                draft.status = QualificationStatus.PAUSED
                self._transfer_storage.save_qualification(draft.draft_id, draft)
                return True
        return False

    def approve(
        self, playlist_id: str, *, corrections: str | Path | None = None,
    ) -> ApprovalOutcome:
        """Review exactly one retained Provisional Playlist against Spotify."""
        return self._approve(playlist_id, corrections=corrections)

    def _approve(
        self,
        playlist_id: str | None,
        *,
        corrections: str | Path | None = None,
        qualification_draft_id: str | None = None,
    ) -> ApprovalOutcome:
        """Perform Approval under one account guard and evidence snapshot."""
        if self._publication_storage is None:
            raise ValueError("Approval requires publication storage")
        account_id = self._spotify.account_id()
        with self._publishing_guards.acquire(account_id):
            if hasattr(self._publication_storage, "load"):
                self._publication_storage.load()
            if hasattr(self._knowledge, "refresh"):
                self._knowledge.refresh()
            if self._transfer_storage is not None and hasattr(
                self._transfer_storage, "refresh"
            ):
                self._transfer_storage.refresh()
            qualification_draft = None
            if qualification_draft_id is not None:
                if self._transfer_storage is None:
                    raise ValueError(
                        "Qualification Approval requires durable Transfer storage"
                    )
                qualification_draft = (
                    self._transfer_storage.load_qualification(
                        qualification_draft_id
                    )
                )
                if (
                    qualification_draft is None
                    or qualification_draft.status
                    not in {
                        QualificationStatus.APPLIED,
                        QualificationStatus.APPROVING,
                    }
                ):
                    raise SpotifyPlaylistReviewRequired(
                        "Qualification Draft must be applied before Approval"
                    )
                if qualification_draft.account_id != account_id:
                    raise ValueError(
                        "A Qualification Draft cannot be approved under "
                        "another account"
                    )
                if qualification_draft.playlist_id is None:
                    raise ValueError(
                        "Applied Qualification playlist is unavailable"
                    )
                playlist_id = qualification_draft.playlist_id
            if playlist_id is None:
                raise ValueError("Approval requires a Provisional Playlist")
            manifest = self._publication_storage.publication_for_playlist(
                account_id, playlist_id,
            )
            if manifest is None:
                raise ValueError(
                    "No Provisional Playlist belongs to this Spotify account"
                )
            if self._transfer_storage is not None and hasattr(
                self._transfer_storage, "qualifications_for_playlist"
            ):
                playlist_drafts = (
                    self._transfer_storage.qualifications_for_playlist(
                        account_id, playlist_id,
                    )
                )
                applied_drafts = [
                    draft for draft in playlist_drafts
                    if draft.status in {
                        QualificationStatus.APPLIED,
                        QualificationStatus.APPROVING,
                    }
                ]
                unapplied = []
                for draft in playlist_drafts:
                    if draft.status in {
                        QualificationStatus.APPLIED,
                        QualificationStatus.APPROVING,
                    }:
                        continue
                    if (
                        draft.status == QualificationStatus.DISCARDED
                        and any(
                            applied.updated_at >= draft.updated_at
                            for applied in applied_drafts
                        )
                    ):
                        continue
                    unapplied.append(draft)
                if unapplied:
                    raise SpotifyPlaylistReviewRequired(
                        "Qualification Draft must be completed and applied "
                        "before Approval"
                    )
                if applied_drafts:
                    applicable = max(
                        applied_drafts,
                        key=lambda draft: (draft.updated_at, draft.created_at),
                    )
                    if qualification_draft is None:
                        raise SpotifyPlaylistReviewRequired(
                            "Qualification Approval requires its applied Draft "
                            "and explicit private-source authorization"
                        )
                    if applicable.draft_id != qualification_draft.draft_id:
                        raise SpotifyPlaylistReviewRequired(
                            "A newer applied Qualification Draft must be "
                            "approved"
                        )
                    applied_manifest = (
                        self._publication_from_stored(
                            applicable.applied_manifest
                        )
                        if applicable.applied_manifest is not None else None
                    )
                    current_digest = self._publication_digest(manifest)
                    if (
                        applied_manifest is None
                        or applicable.manifest_digest != current_digest
                        or self._publication_digest(applied_manifest)
                        != current_digest
                    ):
                        raise SpotifyPlaylistReviewRequired(
                            "Publication manifest changed after Qualification; "
                            "review required"
                        )
                    try:
                        current_selection = self._source.consume(
                            applicable.source_reference
                        )
                    except Exception as exc:
                        raise SpotifyPlaylistReviewRequired(
                            "Rekordbox source evidence is unavailable after "
                            "Qualification; review required",
                            draft_id=applicable.draft_id,
                        ) from exc
                    public_selection = {
                        "reference": current_selection.reference,
                        "tracks": [
                            self._stored_track(track, include_location=False)
                            for track in current_selection.tracks
                        ],
                    }
                    if (
                        self._qualification_selection_digest(public_selection)
                        != applicable.selection_digest
                        or (
                            applicable.audition_selection_digest is not None
                            and self._qualification_audition_digest(
                                current_selection
                            ) != applicable.audition_selection_digest
                        )
                    ):
                        raise SpotifyPlaylistReviewRequired(
                            "Rekordbox source selection changed after "
                            "Qualification; review required",
                            draft_id=applicable.draft_id,
                        )
            corrected_items = self._read_corrections(corrections, manifest)
            if all(hasattr(self._spotify, method) for method in (
                "playlist_head", "ordered_playlist_items",
            )):
                try:
                    before = self._retry_policy.run(
                        lambda: self._spotify.playlist_head(playlist_id)
                    )
                    ordered = self._retry_policy.run(
                        lambda: self._spotify.ordered_playlist_items(playlist_id)
                    )
                    after = self._retry_policy.run(
                        lambda: self._spotify.playlist_head(playlist_id)
                    )
                    if (
                        qualification_draft is not None
                        and qualification_draft.playlist_head is not None
                        and before.snapshot_id
                        != qualification_draft.playlist_head
                    ):
                        raise SpotifyPlaylistChanged(
                            "Spotify playlist changed after Qualification; "
                            "re-review required"
                        )
                    if before.snapshot_id != after.snapshot_id:
                        raise SpotifyPlaylistChanged(
                            "Spotify playlist changed during Approval; "
                            "re-review required"
                        )
                    review_required = [
                        item for item in ordered.items
                        if item.kind != SpotifyItemKind.TRACK
                        or item.is_playable is False
                        or item.restrictions is not None
                        or item.linked_from_uri is not None
                    ]
                    if review_required:
                        positions = ", ".join(
                            str(item.position) for item in review_required
                        )
                        raise SpotifyPlaylistReviewRequired(
                            "Spotify playlist contains unavailable, local, "
                            "episode, unsupported, restricted, or relinked "
                            f"items at positions {positions}; explicit review required"
                        )
                    current_uris = [
                        item.uri for item in ordered.items
                        if item.kind == SpotifyItemKind.TRACK and item.uri
                    ]
                except spotipy.SpotifyException as exc:
                    if exc.http_status != 404:
                        raise
                    current_uris = None
            else:
                current_uris = self._retry_policy.run(
                    lambda: self._spotify.provisional_playlist_track_uris(
                        playlist_id
                    )
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
                present_counts = Counter(current_uris)
                expected_managed_counts = Counter(
                    item.spotify_uri
                    for item in (manifest.managed_items or manifest.items)
                    if item.spotify_uri
                )
                approved: list[PublicationItem] = []
                rejected: list[PublicationItem] = []
                reviewed_items = tuple(
                    corrected_items.get(item.source_track_id, item)
                    for item in manifest.items
                )
                original_identities: dict[
                    str, set[tuple[str, str, int]]
                ] = {}
                for item in manifest.items:
                    if item.spotify_uri:
                        original_identities.setdefault(item.spotify_uri, set()).add((
                            item.source_artist.casefold(),
                            item.source_title.casefold(),
                            item.source_duration,
                        ))
                original_collision_uris = {
                    uri for uri, identities in original_identities.items()
                    if len(identities) > 1
                }
                unresolved_collision_ids = {
                    item.occurrence_id or item.source_track_id
                    for item in manifest.items
                    if item.spotify_uri in original_collision_uris
                    and item.source_track_id not in corrected_items
                    and item.qualification_outcome is None
                }
                proposed_identities: dict[
                    str, set[tuple[str, str, int]]
                ] = {}
                collision_candidates = tuple(
                    item for item in reviewed_items
                    if item.qualification_outcome
                    != QualificationDecision.REJECT_PROPOSAL.value
                )
                for item in collision_candidates:
                    if item.spotify_uri:
                        proposed_identities.setdefault(item.spotify_uri, set()).add((
                            item.source_artist.casefold(),
                            item.source_title.casefold(),
                            item.source_duration,
                        ))
                collision_uris = {
                    uri for uri, identities in proposed_identities.items()
                    if len(identities) > 1
                }
                collisions: list[PublicationItem] = []
                for item in reviewed_items:
                    if not item.spotify_uri:
                        continue
                    if item.qualification_outcome == (
                        QualificationDecision.REJECT_PROPOSAL.value
                    ):
                        if (
                            present_counts[item.spotify_uri]
                            > expected_managed_counts[item.spotify_uri]
                        ):
                            collisions.append(item)
                            continue
                        rejected.append(item)
                        continue
                    if (
                        (item.occurrence_id or item.source_track_id)
                        in unresolved_collision_ids
                        or item.spotify_uri in collision_uris
                    ):
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
                        or item.match_type == "correction"
                    ),
                )
                conflicts: list[ApprovalConflict] = []
                for item in outcome.approved:
                    local_conflict_checker = getattr(
                        self._knowledge,
                        "local_audio_approval_conflict",
                        None,
                    )
                    local_preflight_conflict = (
                        local_conflict_checker(item, account_id)
                        if local_conflict_checker is not None else None
                    )
                    if local_preflight_conflict is not None:
                        recorded_conflict = self._knowledge.approve_local_audio(
                            item, account_id,
                        )
                        conflicts.append(
                            recorded_conflict or local_preflight_conflict
                        )
                        continue
                    if (
                        item.source_track_id in corrected_items
                        or item.match_type == "correction"
                    ):
                        conflict = self._knowledge.correct(item)
                    else:
                        conflict = self._knowledge.approve(item)
                    if conflict is not None:
                        conflicts.append(conflict)
                    if (
                        conflict is None
                        and item.match_type == "correction"
                        and item.local_evidence_id is None
                    ):
                        revoke_local_audio = getattr(
                            self._knowledge, "revoke_local_audio", None,
                        )
                        if revoke_local_audio is not None:
                            revoke_local_audio(item, account_id)
                    if conflict is None and item.local_evidence_id is not None:
                        local_conflict = self._knowledge.approve_local_audio(
                            item, account_id,
                        )
                        if local_conflict is not None:
                            conflicts.append(local_conflict)
                for item in outcome.rejected:
                    self._knowledge.reject(item)
                    revoke_local_audio = getattr(
                        self._knowledge, "revoke_local_audio", None,
                    )
                    if revoke_local_audio is not None:
                        revoke_local_audio(item, account_id)
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
                if (
                    outcome.status == ApprovalStatus.APPROVED
                    and hasattr(self._spotify, "set_playlist_description")
                ):
                    self._retry_policy.run(
                        lambda: self._spotify.set_playlist_description(
                            playlist_id, self._approved_description(manifest),
                        )
                    )
            self._publication_storage.retain_approval(outcome)
            if (
                outcome.status == ApprovalStatus.ABANDONED
                and qualification_draft is not None
            ):
                qualification_draft.status = QualificationStatus.REVIEW_REQUIRED
                qualification_draft.review_reason = "playlist_abandoned"
                qualification_draft.updated_at = datetime.now().isoformat()
                assert self._transfer_storage is not None
                self._transfer_storage.save_qualification(
                    qualification_draft.draft_id, qualification_draft,
                )
                if self._local_audition is not None and hasattr(
                    self._local_audition, "invalidate_transfer"
                ):
                    self._local_audition.invalidate_transfer(
                        qualification_draft.transfer_id
                    )
            return outcome

    @staticmethod
    def _approved_description(manifest: PublicationManifest) -> str:
        relationship = (
            "managed Mirror relationship" if manifest.mode == TransferMode.MIRROR
            else "approved Snapshot provenance"
        )
        chart = manifest.chart_title or manifest.source_label
        curator = f" by {manifest.curator}" if manifest.curator else ""
        return (
            f"{chart}{curator}; {relationship}. Source: "
            f"{manifest.source_reference}"
        )

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
                if not spotify_reference:
                    continue
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
                if (
                    spotify_track.get("is_playable") is False
                    or spotify_track.get("is_local") is True
                    or bool(spotify_track.get("restrictions"))
                    or spotify_track.get("linked_from") is not None
                    or spotify_track.get("linked_from_uri") is not None
                ):
                    raise ValueError(
                        f"Correction row {row_number} is not an available Spotify track"
                    )
                corrected[source_track_id] = replace(
                    original,
                    spotify_uri=spotify_uri,
                    spotify_name=spotify_track["name"],
                    spotify_artist=spotify_track["artist"],
                    spotify_release=spotify_track.get("album", ""),
                    spotify_duration=int(
                        spotify_track.get("duration_ms", 0)
                    ) // 1000,
                    score=100.0,
                    match_type="correction",
                    score_reasons=("explicit playlist Correction",),
                    authoritative=False,
                    **self._availability_facts(
                        spotify_track, source="spotify_track_lookup",
                    ),
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

        manual_by_managed_boundary: dict[int, list[str]] = {}
        managed_seen = 0
        for uri in current_uris:
            if uri in managed_uris:
                managed_seen += 1
                continue
            boundary = min(managed_seen, len(desired))
            manual_by_managed_boundary.setdefault(boundary, []).append(uri)
        repaired: list[str] = []
        for boundary in range(len(desired) + 1):
            repaired.extend(manual_by_managed_boundary.get(boundary, ()))
            if boundary < len(desired):
                repaired.append(desired[boundary])
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

    def _execute(
        self,
        request: TransferRequest,
        *,
        expected_selection_token: str | None = None,
    ) -> SyncReport:
        """Execute one Transfer and return its structured outcome.

        Beatport publication creates a distinct Provisional Snapshot after the
        complete selection has matched safely.
        """
        if not request.preview and self._publication_storage is None:
            raise ValueError("Publishing Transfers require publication storage")
        if request.local_audio_identity and not getattr(
            self._knowledge, "persistent", True,
        ):
            raise ValueError(
                "Local audio identity requires durable matching knowledge; "
                "remove --no-cache"
            )

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
        if state is None or not state.selection:
            prepared_state = state
            if prepared_state is not None:
                if prepared_state.source != request.source:
                    raise ValueError("A resumed Transfer must use its original source")
                if prepared_state.account_id != self._spotify.account_id():
                    raise ValueError(
                        "A Transfer cannot resume under another Spotify account"
                    )
                request = TransferRequest(
                    **{
                        **prepared_state.request,
                        "mode": TransferMode(prepared_state.request["mode"]),
                        "drift_resolution": (
                            DriftResolution(prepared_state.request["drift_resolution"])
                            if prepared_state.request.get("drift_resolution") else None
                        ),
                        "mirror_disposition": (
                            MirrorDisposition(
                                prepared_state.request["mirror_disposition"]
                            )
                            if prepared_state.request.get("mirror_disposition") else None
                        ),
                    },
                    transfer_id=transfer_id,
                )
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
                if prepared_state is not None:
                    prepared_state.status = TransferStatus.PAUSED
                    prepared_state.outcome = "Source selection was not found"
                    self._save_transfer(transfer_id, prepared_state)
                raise
            except Exception as exc:
                if prepared_state is not None:
                    prepared_state.status = TransferStatus.PAUSED
                    prepared_state.outcome = str(exc)
                    self._save_transfer(transfer_id, prepared_state)
                raise
            if expected_selection_token:
                actual_selection_token = self._selection_token(
                    selection,
                    include_locations=(
                        request.local_audio_identity
                        or request.local_audio_audition
                    ),
                )
                if actual_selection_token != expected_selection_token:
                    raise SpotifyPlaylistReviewRequired(
                        "Rekordbox Batch selection changed before execution"
                    )
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
            created_at = (
                datetime.fromisoformat(prepared_state.created_at)
                if prepared_state is not None else datetime.now()
            )
            state = TransferState(
                status=TransferStatus.MATCHING,
                source=request.source,
                account_id=self._spotify.account_id(),
                request=self._stored_request(request),
                selection={
                    "name": selection.name,
                    "reference": selection.reference,
                    "tracks": [
                        self._stored_track(
                            track,
                            include_location=request.local_audio_identity,
                        )
                        for track in selection.tracks
                    ],
                    "chart_title": selection.chart_title,
                    "curator": selection.curator,
                },
                created_at=created_at.isoformat(),
                next_track_index=0,
                matched=[],
                unmatched=[],
                publication_items=[],
                alternatives=[],
                audition_selection_digest=(
                    self._selection_token(
                        selection, include_locations=True,
                    )
                    if request.local_audio_audition else None
                ),
                spotify_playlist_id=(
                    relinked_mirror.spotify_playlist_id if relinked_mirror else None
                ),
                spotify_playlist_name=(
                    relinked_mirror.spotify_playlist_name if relinked_mirror else None
                ),
                revision=(prepared_state.revision if prepared_state is not None else 0),
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
                chart_title=stored_selection.get("chart_title"),
                curator=stored_selection.get("curator"),
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
        playlist.api_lookups = state.api_lookups
        playlist.local_audio_eligible = state.local_audio_eligible
        playlist.local_audio_observed = state.local_audio_observed
        playlist.local_audio_unavailable = state.local_audio_unavailable
        playlist.local_audio_reused = state.local_audio_reused
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
        playlist.review_items = self._review_tracks(publication_items)
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
                occurrence_id = self._occurrence_id(transfer_id, index, track)
                result = self._knowledge.lookup(track, request.threshold)
                local_evidence_id = None
                if (
                    request.local_audio_identity
                    and self._local_audio is not None
                    and not (result is not None and result.get("authoritative"))
                ):
                    evidence_key = str(index)
                    local_evidence_id = state.local_evidence_ids.get(evidence_key)
                    observation = (
                        self._knowledge.local_audio_observation(local_evidence_id)
                        if local_evidence_id is not None else None
                    )
                    if observation is None:
                        observation = self._local_audio.observe(track)
                    if observation.status == "available":
                        playlist.local_audio_eligible += 1
                        playlist.local_audio_observed += 1
                        if local_evidence_id is None:
                            local_evidence_id = self._knowledge.retain_local_audio(
                                track, observation,
                            )
                            state.local_evidence_ids[evidence_key] = local_evidence_id
                            self._knowledge.checkpoint()
                            self._save_transfer(transfer_id, state)
                        local_result = self._knowledge.lookup_local_audio(
                            observation, self._spotify.account_id(),
                        )
                        if local_result is not None:
                            result = local_result
                            playlist.local_audio_reused += 1
                    else:
                        playlist.local_audio_unavailable += 1
                if result is not None:
                    playlist.cache_hits += 1
                    if result.get("authoritative"):
                        result = {
                            **result,
                            **self._approved_availability(result["uri"]),
                        }
                    if (
                        result.get("authoritative")
                        and result.get("availability_status") == "unavailable"
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
                            occurrence_id=occurrence_id,
                            source_index=index,
                            source_release=track.album,
                            source_label=track.label,
                            source_version=track.version,
                            spotify_uri=result["uri"],
                            spotify_name=result["name"],
                            spotify_artist=result["artist"],
                            spotify_release=result.get("album", ""),
                            spotify_duration=(
                                int(result.get("duration_ms", 0)) // 1000
                            ),
                            score=result["score"],
                            match_type=result.get("match_type", "exact"),
                            score_reasons=tuple(result.get("score_reasons", ())),
                            source_duration=track.duration,
                            authoritative=True,
                            local_evidence_id=local_evidence_id,
                            **self._availability_facts(
                                result, source="spotify_track_lookup",
                            ),
                        ))
                        result = None
                elif self._knowledge.should_retry(
                    track, request.threshold, request.retry_days, request.retry,
                ):
                    result = self._retry_policy.run(
                        lambda: self._spotify.match(track, request.threshold)
                    )
                    playlist.api_lookups += 1
                    if result is not None and "alternatives" not in result:
                        result = {
                            **result,
                            **self._availability_facts(
                                result, source="spotify_or_retained_result",
                            ),
                        }
                    self._knowledge.retain(
                        track, request.threshold,
                        None if result and "alternatives" in result else result,
                    )
                else:
                    result = None
                    playlist.cache_hits += 1

                if result is None or "alternatives" in result:
                    playlist.unmatched.append(track.display)
                    if self._is_new_reviewable_occurrence(
                        occurrence_id, publication_items,
                    ):
                        publication_items.append(PublicationItem(
                            source_track_id=track.track_id,
                            source_name=track.display,
                            source_artist=track.artist,
                            source_title=track.name,
                            occurrence_id=occurrence_id,
                            source_index=index,
                            source_release=track.album,
                            source_label=track.label,
                            source_version=track.version,
                            source_duration=track.duration,
                            local_evidence_id=local_evidence_id,
                        ))
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
                        score_reasons=tuple(result.get("score_reasons", ())),
                        source_track_id=track.track_id,
                        spotify_uri=result["uri"],
                    )
                    playlist.matched.append(matched_track)
                    if self._is_new_reviewable_occurrence(
                        occurrence_id, publication_items,
                    ):
                        publication_items.append(PublicationItem(
                            source_track_id=track.track_id,
                            source_name=track.display,
                            source_artist=track.artist,
                            source_title=track.name,
                            occurrence_id=occurrence_id,
                            source_index=index,
                            source_release=track.album,
                            source_label=track.label,
                            source_version=track.version,
                            spotify_uri=result["uri"],
                            spotify_name=matched_track.spotify_name,
                            spotify_artist=matched_track.spotify_artist,
                            spotify_release=result.get("album", ""),
                            spotify_duration=(
                                int(result.get("duration_ms", 0)) // 1000
                            ),
                            score=matched_track.score,
                            match_type=matched_track.match_type,
                            score_reasons=matched_track.score_reasons,
                            source_duration=track.duration,
                            authoritative=bool(result.get("authoritative")),
                            local_evidence_id=local_evidence_id,
                            **self._availability_facts(
                                result, source="spotify_or_retained_result",
                            ),
                        ))

                state.next_track_index = index + 1
                state.api_lookups = playlist.api_lookups
                state.local_audio_eligible = playlist.local_audio_eligible
                state.local_audio_observed = playlist.local_audio_observed
                state.local_audio_unavailable = playlist.local_audio_unavailable
                state.local_audio_reused = playlist.local_audio_reused
                state.matched = [asdict(item) for item in playlist.matched]
                state.unmatched = list(playlist.unmatched)
                state.alternatives = [asdict(item) for item in playlist.alternatives]
                state.publication_items = [
                    asdict(item) for item in publication_items
                ]
                playlist.review_items = self._review_tracks(publication_items)
                self._knowledge.checkpoint()
                if self._pause_requested:
                    state.status = TransferStatus.PAUSED
                    self._save_transfer(transfer_id, state)
                    self._pause_requested = False
                    playlist.action = "paused"
                    report.status = "paused"
                    return report
                self._save_transfer(transfer_id, state)

            source_ids_by_uri: dict[
                str, set[tuple[str, str, int]]
            ] = {}
            for item in publication_items:
                if not item.spotify_uri:
                    continue
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
                            if item.local_evidence_id is not None:
                                self._knowledge.revoke_local_audio(
                                    item, state.account_id,
                                )
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
                    description = self._provisional_description(
                        request.mode, selection,
                    )
                    publication_key = transfer_id
                    if request.mode == TransferMode.MIRROR:
                        publication_key = hashlib.sha256(
                            f"{state.account_id}\0{selection.reference}".encode()
                        ).hexdigest()
                    publish_uris = [
                        item.spotify_uri for item in publication_items
                        if item.spotify_uri
                        and item.spotify_uri not in collision_uris
                    ]
                    if all(hasattr(self._spotify, method) for method in (
                        "create_playlist", "find_recovery_playlist",
                        "replace_items", "add_items", "playlist_head",
                    )):
                        playlist_id = self._publish_checkpointed(
                            transfer_id, state, snapshot_name, description,
                            publication_key, publish_uris,
                        )
                    else:
                        playlist_id = self._retry_policy.run(
                            lambda: self._spotify.publish_provisional_snapshot(
                                snapshot_name, publish_uris, description,
                                publication_key,
                            )
                        )
                    state.spotify_playlist_id = playlist_id
                    state.spotify_playlist_name = snapshot_name
                    state.status = TransferStatus.RETAINING_PUBLICATION
                    self._save_transfer(transfer_id, state)
                    # The recovery key is permitted only until the returned ID
                    # has crossed the durable local checkpoint above.
                    if hasattr(self._spotify, "set_playlist_description"):
                        self._retry_policy.run(
                            lambda: self._spotify.set_playlist_description(
                                playlist_id, description,
                            )
                        )
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
                                if item.spotify_uri
                                and item.spotify_uri not in collision_uris
                            )),
                        )
                    )
                elif (
                    state.publication_manifest is None
                    and all(hasattr(self._spotify, method) for method in (
                        "create_playlist", "find_recovery_playlist",
                        "replace_items", "add_items", "playlist_head",
                    ))
                ):
                    description = self._provisional_description(
                        request.mode, selection,
                    )
                    publication_key = transfer_id
                    if request.mode == TransferMode.MIRROR:
                        publication_key = hashlib.sha256(
                            f"{state.account_id}\0{selection.reference}".encode()
                        ).hexdigest()
                    publish_uris = [
                        item.spotify_uri for item in publication_items
                        if item.spotify_uri
                        and item.spotify_uri not in collision_uris
                    ]
                    playlist_id = self._publish_checkpointed(
                        transfer_id, state, snapshot_name, description,
                        publication_key, publish_uris,
                    )
                assert snapshot_name is not None
                managed_items = tuple(
                    item for item in publication_items
                    if item.spotify_uri and item.spotify_uri not in collision_uris
                )
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
                    ),
                    mode=request.mode,
                    managed_items=managed_items,
                    chart_title=selection.chart_title,
                    curator=selection.curator,
                )
                stored_manifest = asdict(manifest)
                stored_manifest["created_at"] = manifest.created_at.isoformat()
                state.publication_manifest = stored_manifest
                self._save_transfer(transfer_id, state)
                assert self._publication_storage is not None
                try:
                    if request.mirror_disposition == MirrorDisposition.RELINK:
                        assert request.mirror_playlist_id is not None
                        previous = self._publication_storage.mirror_for_playlist(
                            state.account_id, request.mirror_playlist_id,
                        )
                        assert previous is not None
                        self._publication_storage.retain_relinked_publication(
                            previous,
                            replace(
                                previous,
                                source_label=self._source.source_label,
                                source_reference=selection.reference,
                                orphaned_at=None,
                            ),
                            manifest,
                        )
                    else:
                        self._publication_storage.retain_publication(manifest)
                except Exception:
                    if state.completed_chunks:
                        # Remote mutation evidence and playlist identity are
                        # authoritative recovery facts. Keep them intact so a
                        # resume retries only local manifest retention.
                        raise
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
        except (
            QuotaExceededError, RateLimitError, requests.Timeout,
            requests.ConnectionError,
        ) as exc:
            state.status = TransferStatus.PAUSED
            state.outcome = str(exc)
            self._save_transfer(transfer_id, state)
            raise exc
        except spotipy.SpotifyException as exc:
            if exc.http_status not in (401, 403, 429) and (
                exc.http_status is None or exc.http_status < 500
            ):
                raise
            state.status = TransferStatus.PAUSED
            state.outcome = str(exc)
            self._save_transfer(transfer_id, state)
            raise
        except KeyboardInterrupt:
            state.status = TransferStatus.PAUSED
            self._save_transfer(transfer_id, state)
            raise
        except Exception as exc:
            # A durable single Transfer remains resumable after adapter or
            # integration failures that are not classified above.
            state.status = TransferStatus.PAUSED
            state.outcome = str(exc)
            self._save_transfer(transfer_id, state)
            raise
        finally:
            # Matching discoveries survive interrupted matching or publication.
            self._knowledge.checkpoint()

        return report

    def _publish_checkpointed(
        self,
        transfer_id: str,
        state: TransferState,
        name: str,
        description: str,
        publication_key: str,
        uris: list[str],
    ) -> str:
        """Publish ordered chunks with durable mutation evidence.

        Spotify has no atomic multi-chunk replace. An edit may still land
        between the fresh head read and the next write; every observable head
        mismatch stops publication for explicit review.
        """
        playlist_id = state.spotify_playlist_id
        if playlist_id is None:
            playlist_id = self._retry_policy.run(
                lambda: self._spotify.find_recovery_playlist(publication_key)
            )
        if playlist_id is None:
            marker = f"djsupport-transfer:{publication_key}"
            playlist_id = self._retry_policy.run(
                lambda: self._spotify.create_playlist(
                    name, f"{description} {marker}",
                )
            )
        state.spotify_playlist_id = playlist_id
        state.spotify_playlist_name = name
        state.status = TransferStatus.RETAINING_PUBLICATION
        self._save_transfer(transfer_id, state)
        if hasattr(self._spotify, "set_playlist_description"):
            self._retry_policy.run(
                lambda: self._spotify.set_playlist_description(
                    playlist_id, description,
                )
            )

        chunks = [uris[:100]] + [
            uris[offset:offset + 100] for offset in range(100, len(uris), 100)
        ]
        for index, chunk in enumerate(chunks):
            chunk_id = hashlib.sha256(
                json.dumps([index, chunk], separators=(",", ":")).encode()
            ).hexdigest()
            if chunk_id in state.completed_chunks:
                continue
            if state.mutation_snapshots:
                current = self._retry_policy.run(
                    lambda: self._spotify.playlist_head(playlist_id)
                )
                if current.snapshot_id != state.mutation_snapshots[-1]:
                    raise SpotifyPlaylistChanged(
                        "Spotify playlist changed during publication; "
                        "publication paused for explicit review"
                    )
            result = self._retry_policy.run(
                lambda: (
                    self._spotify.replace_items(playlist_id, chunk)
                    if index == 0 else self._spotify.add_items(playlist_id, chunk)
                )
            )
            state.mutation_snapshots.append(result.snapshot_id)
            state.completed_chunks.append(chunk_id)
            self._save_transfer(transfer_id, state)
        return playlist_id

    def _provisional_description(
        self, mode: TransferMode, selection: SourceSelection,
    ) -> str:
        if self._source.source_label == "Beatport":
            curator = f" by {selection.curator}" if selection.curator else ""
            return (
                f"Provisional Beatport chart{curator}; awaiting review and "
                f"Approval as a {mode.value.title()}. Source: {selection.reference}"
            )
        return (
            f"Provisional {mode.value.title()} from {self._source.source_label}; "
            f"awaiting review and Approval. Source: {selection.reference}"
        )

    def _save_transfer(self, transfer_id: str, state: TransferState) -> None:
        if self._transfer_storage is not None:
            self._transfer_storage.save_transfer(transfer_id, state)

    @staticmethod
    def _review_tracks(items: list[PublicationItem]) -> list[ReviewTrack]:
        return [
            ReviewTrack(
                source_track_id=item.source_track_id,
                source_name=item.source_name,
                source_artist=item.source_artist,
                source_title=item.source_title,
                source_release=item.source_release,
                source_label=item.source_label,
                source_version=item.source_version,
                source_duration=item.source_duration,
                spotify_uri=item.spotify_uri,
                spotify_name=item.spotify_name,
                spotify_artist=item.spotify_artist,
                spotify_release=item.spotify_release,
                spotify_duration=item.spotify_duration,
                score=item.score,
                match_type=item.match_type,
                score_reasons=item.score_reasons,
                authority_status=(
                    "approved" if item.authoritative else "proposal"
                ),
            )
            for item in items
        ]

    @staticmethod
    def _occurrence_id(transfer_id: str, index: int, track: Track) -> str:
        material = f"{transfer_id}\0{index}\0{track.track_id}"
        return hashlib.sha256(material.encode()).hexdigest()

    @staticmethod
    def _is_new_reviewable_occurrence(
        occurrence_id: str, items: list[PublicationItem],
    ) -> bool:
        return bool(occurrence_id) and not any(
            item.occurrence_id == occurrence_id for item in items
        )

    def _approved_availability(self, spotify_uri: str) -> dict:
        try:
            track = self._retry_policy.run(
                lambda: self._spotify.spotify_track(spotify_uri)
            )
        except spotipy.SpotifyException as exc:
            if exc.http_status == 404:
                return {
                    "availability_status": "unavailable",
                    "availability_reason": "spotify_unavailable",
                    "availability_checked_at": datetime.now().isoformat(),
                    "availability_source": "spotify_track_lookup",
                }
            raise
        return self._availability_facts(
            track, source="spotify_track_lookup",
        )
