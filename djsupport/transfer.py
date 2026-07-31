"""Deep, framework-agnostic Transfer workflow.

The public seam is :class:`Transfer.execute`: adapters describe what to
transfer and receive a structured report, while this module owns matching,
persistence ordering, and Preview's read-only publication policy.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from djsupport.cache import MatchCache
from djsupport.matcher import match_track
from djsupport.rekordbox import Track
from djsupport.report import MatchedTrack, PlaylistReport, SyncReport


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


@dataclass(frozen=True)
class SourceSelection:
    """One named selection returned by a source adapter."""

    name: str
    reference: str
    tracks: list[Track]


class SourceAdapter(Protocol):
    source_label: str

    def consume(self, reference: str) -> SourceSelection: ...


class SpotifyAdapter(Protocol):
    def match(self, track: Track, threshold: int) -> dict | None: ...


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
    """Production Spotify matching adapter."""

    def __init__(self, client) -> None:
        self._client = client

    def match(self, track: Track, threshold: int) -> dict | None:
        return match_track(self._client, track, threshold=threshold)


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
    ) -> None:
        self._source = source
        self._spotify = spotify
        self._knowledge = matching_knowledge

    def execute(self, request: TransferRequest) -> SyncReport:
        """Execute one Transfer and return its structured outcome.

        This tracer-bullet implementation intentionally supports Preview only.
        Publication will be added behind this same seam by later Transfer work.
        """
        if not request.preview:
            raise ValueError("Publishing Transfers are not supported by this interface yet")

        selection = self._source.consume(request.source)
        playlist = PlaylistReport(
            name=selection.name,
            path=selection.reference,
            action="preview",
        )
        report = SyncReport(
            timestamp=datetime.now(),
            threshold=request.threshold,
            dry_run=True,
            playlists=[playlist],
            cache_enabled=getattr(self._knowledge, "persistent", True),
            source_label=self._source.source_label,
        )

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
                    playlist.matched.append(MatchedTrack(
                        source_name=track.display,
                        spotify_name=result["name"],
                        spotify_artist=result["artist"],
                        score=result["score"],
                        match_type=result.get("match_type", "exact"),
                    ))
        finally:
            # Matching discoveries survive an interrupted Preview. Playlist
            # management storage is deliberately absent from this workflow.
            self._knowledge.checkpoint()

        return report
