"""Deep, framework-agnostic Transfer workflow.

The public seam is :class:`Transfer.execute`: adapters describe what to
transfer and receive a structured report, while this module owns matching,
persistence ordering, Preview policy, and Provisional Snapshot publication.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from djsupport.cache import MatchCache
from djsupport.matcher import match_track
from djsupport.rekordbox import Track
from djsupport.report import MatchedTrack, PlaylistReport, SyncReport


PUBLICATION_MANIFEST_VERSION = 1


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
    def match(self, track: Track, threshold: int) -> dict | None: ...

    def publish_provisional_snapshot(
        self, name: str, track_uris: list[str], description: str,
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
        next_manifests = [*self.manifests, stored]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(json.dumps({
            "version": PUBLICATION_MANIFEST_VERSION,
            "manifests": next_manifests,
        }, indent=2))
        os.replace(temporary, self.path)
        self.manifests = next_manifests


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

    def match(self, track: Track, threshold: int) -> dict | None:
        return match_track(self._client, track, threshold=threshold)

    def publish_provisional_snapshot(
        self, name: str, track_uris: list[str], description: str,
    ) -> str:
        user_id = self._client.current_user()["id"]
        playlist = self._client.user_playlist_create(
            user_id, name, public=False, description=description,
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
        return self._cache.is_retry_eligible(
            track.artist, track.name, retry_days=retry_days, force=force,
        )

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
        publication_storage: PublicationStorage | None = None,
    ) -> None:
        self._source = source
        self._spotify = spotify
        self._knowledge = matching_knowledge
        self._publication_storage = publication_storage

    def execute(self, request: TransferRequest) -> SyncReport:
        """Execute one Transfer and return its structured outcome.

        Beatport publication creates a distinct Provisional Snapshot after the
        complete selection has matched safely.
        """
        if not request.preview and self._publication_storage is None:
            raise ValueError("Publishing Transfers require publication storage")

        selection = self._source.consume(request.source)
        created_at = datetime.now()
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
        )
        publication_items: list[PublicationItem] = []

        try:
            for track in selection.tracks:
                result = self._knowledge.lookup(track, request.threshold)
                if result is not None:
                    playlist.cache_hits += 1
                elif self._knowledge.should_retry(
                    track, request.threshold, request.retry_days, request.retry,
                ):
                    result = self._spotify.match(track, request.threshold)
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

            if not request.preview and not selection.tracks:
                playlist.action = "not published: empty source"
            elif not request.preview and playlist.unmatched:
                playlist.action = "not published: incomplete matching"
            elif not request.preview:
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
                playlist_id = self._spotify.publish_provisional_snapshot(
                    snapshot_name,
                    [item.spotify_uri for item in publication_items],
                    description,
                )
                manifest = PublicationManifest(
                    spotify_playlist_id=playlist_id,
                    spotify_playlist_name=snapshot_name,
                    source_label=self._source.source_label,
                    source_reference=selection.reference,
                    created_at=created_at,
                    items=tuple(publication_items),
                )
                assert self._publication_storage is not None
                try:
                    self._publication_storage.retain_publication(manifest)
                except Exception:
                    self._spotify.delete_provisional_snapshot(playlist_id)
                    raise
                playlist.name = snapshot_name
                playlist.spotify_playlist_id = playlist_id
                playlist.publication_manifest = manifest
                playlist.action = "provisional snapshot created"
        finally:
            # Matching discoveries survive interrupted matching or publication.
            self._knowledge.checkpoint()

        return report
