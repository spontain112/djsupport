"""Private production assembly for Transfer clients.

Clients provide source and phase facts. This module owns the corresponding
production adapters without taking matching, authorization, persistence, or
publication policy away from :class:`djsupport.transfer.Transfer`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from djsupport.cache import MatchCache
from djsupport.local_audio import ChromaprintLocalAudio
from djsupport.local_audition import LocalSourceAudition
from djsupport.spotify import get_client
from djsupport.transfer import (
    AccountPublishingGuards,
    EphemeralMatchingKnowledge,
    FilePublicationStorage,
    FileTransferStorage,
    MatchCacheKnowledge,
    SourceAdapter,
    SpotifyAdapter,
    SpotifyMatcher,
    Transfer,
    TransferMode,
    default_matching_knowledge_path,
    default_publication_manifest_path,
)


class RuntimeDependencyUnavailable(RuntimeError):
    """A phase tried to cross a production seam it did not enable."""


class MatchingKnowledgeUnavailable(ValueError):
    """Durable matching knowledge could not be assembled safely."""


class SpotifyAccess(str, Enum):
    """Whether this already-authorized phase may construct Spotify access."""

    DISABLED = "disabled"
    REQUIRED = "required"


@dataclass(frozen=True)
class RuntimePaths:
    """One coherent set of private application-data paths."""

    matching_knowledge: Path
    publication_state: Path

    @classmethod
    def defaults(cls) -> RuntimePaths:
        return cls(
            matching_knowledge=default_matching_knowledge_path(),
            publication_state=default_publication_manifest_path(),
        )

    @classmethod
    def selected(
        cls,
        matching_knowledge: str | Path,
        publication_state: str | Path,
    ) -> RuntimePaths:
        return cls(Path(matching_knowledge), Path(publication_state))

    @property
    def transfer_state(self) -> Path:
        return self.publication_state.with_suffix(".transfers.json")


@dataclass(frozen=True)
class RuntimeSettings:
    """Policy-neutral facts selecting adapters for one active Transfer."""

    paths: RuntimePaths
    spotify_access: SpotifyAccess = SpotifyAccess.DISABLED
    retain_matching_knowledge: bool = True
    retain_publications: bool = True
    local_audio_identity: bool = False
    local_audio_audition: bool = False


@dataclass(frozen=True)
class RuntimeGraph:
    """The assembled Transfer and its shared durable-state adapter."""

    transfer: Transfer
    transfer_storage: FileTransferStorage


class _UnavailableSource:
    source_label = "unavailable"
    default_mode = TransferMode.SNAPSHOT

    def consume(self, reference: str):
        del reference
        raise RuntimeDependencyUnavailable(
            "Private source access is unavailable in this runtime phase"
        )

    def consume_batch(self, references, whole_library):
        del references, whole_library
        raise RuntimeDependencyUnavailable(
            "Private source access is unavailable in this runtime phase"
        )


class _UnavailableSpotify:
    def _unavailable(self, *args, **kwargs):
        del args, kwargs
        raise RuntimeDependencyUnavailable(
            "Spotify access is unavailable in this runtime phase"
        )

    account_id = _unavailable
    add_items = _unavailable
    create_playlist = _unavailable
    delete_playlist = _unavailable
    delete_provisional_snapshot = _unavailable
    find_recovery_playlist = _unavailable
    match = _unavailable
    ordered_playlist_items = _unavailable
    playlist_head = _unavailable
    provisional_playlist_track_uris = _unavailable
    publish_provisional_snapshot = _unavailable
    replace_items = _unavailable
    replace_provisional_playlist_tracks = _unavailable
    set_playlist_description = _unavailable
    spotify_track = _unavailable


def _production_spotify() -> SpotifyAdapter:
    return SpotifyMatcher(get_client())


class RuntimeAssembly:
    """Assemble the production graph behind one private client seam."""

    def __init__(
        self,
        spotify_factory: Callable[[], SpotifyAdapter] = _production_spotify,
    ) -> None:
        self._spotify_factory = spotify_factory
        self._transfer_storages: dict[Path, FileTransferStorage] = {}

    def capability_transfer(self) -> Transfer:
        """Build a graph that inspects local capabilities and nothing private."""
        return Transfer(
            source=_UnavailableSource(),
            spotify=_UnavailableSpotify(),
            matching_knowledge=EphemeralMatchingKnowledge(),
            publishing_guards=AccountPublishingGuards(),
            local_audio=ChromaprintLocalAudio(),
            local_audition=LocalSourceAudition(),
        )

    def assemble(
        self,
        source: SourceAdapter,
        settings: RuntimeSettings,
    ) -> RuntimeGraph:
        """Build one active Transfer from explicit, policy-owned phase facts."""
        matching_knowledge = self._matching_knowledge(settings)
        transfer_storage = self.transfer_storage(settings.paths)
        spotify = (
            self._spotify_factory()
            if settings.spotify_access == SpotifyAccess.REQUIRED
            else _UnavailableSpotify()
        )
        transfer = Transfer(
            source=source,
            spotify=spotify,
            matching_knowledge=matching_knowledge,
            publishing_guards=AccountPublishingGuards(),
            publication_storage=(
                FilePublicationStorage(settings.paths.publication_state)
                if settings.retain_publications else None
            ),
            transfer_storage=transfer_storage,
            local_audio=(
                ChromaprintLocalAudio()
                if settings.local_audio_identity else None
            ),
            local_audition=(
                LocalSourceAudition()
                if settings.local_audio_audition else None
            ),
        )
        return RuntimeGraph(transfer, transfer_storage)

    def transfer_storage(self, paths: RuntimePaths) -> FileTransferStorage:
        """Return the shared Transfer-state adapter for one path family."""
        path = paths.transfer_state
        if path not in self._transfer_storages:
            self._transfer_storages[path] = FileTransferStorage(path)
        return self._transfer_storages[path]

    @staticmethod
    def _matching_knowledge(settings: RuntimeSettings):
        if not settings.retain_matching_knowledge:
            return EphemeralMatchingKnowledge()
        cache = MatchCache(settings.paths.matching_knowledge)
        try:
            cache.load()
        except (OSError, ValueError) as exc:
            raise MatchingKnowledgeUnavailable(str(exc)) from exc
        return MatchCacheKnowledge(cache)
