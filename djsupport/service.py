"""Framework-agnostic sync orchestration for Beatport charts and labels.

This module extracts the core sync logic from cli.py so that both the CLI
and the web frontend can share it.  All progress feedback is delivered via
an optional callback instead of Click's progress bar.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import spotipy

from djsupport.cache import MatchCache
from djsupport.matcher import match_track, match_track_cached
from djsupport.rekordbox import Track
from djsupport.report import MatchedTrack, PlaylistReport, SyncReport
from djsupport.spotify import (
    RateLimitError,
    create_or_update_playlist,
    format_playlist_name,
    get_user_playlists,
    incremental_update_playlist,
)
from djsupport.state import PlaylistStateManager


@dataclass
class ProgressEvent:
    """A single progress update emitted during sync."""

    phase: str  # "fetching", "matching", "syncing", "complete", "error"
    current: int = 0
    total: int = 0
    detail: str = ""


ProgressCallback = Callable[[ProgressEvent], None]


def match_and_sync_playlist(
    tracks: list[Track],
    playlist_name: str,
    playlist_path: str,
    *,
    sp: spotipy.Spotify,
    cache: MatchCache | None,
    state_mgr: PlaylistStateManager | None,
    existing_playlists: dict[str, str] | None,
    threshold: int,
    dry_run: bool,
    incremental: bool,
    prefix: str | None,
    retry_days: int = 7,
    retry: bool = False,
    source_type: str = "rekordbox",
    on_progress: ProgressCallback | None = None,
) -> PlaylistReport:
    """Match tracks to Spotify and create/update a playlist.

    This is the framework-agnostic version of cli._match_and_sync_playlist.
    Progress is reported via *on_progress* instead of click.progressbar.

    Raises RateLimitError if Spotify rate limit is exceeded — caller should
    save cache and handle the abort.
    """
    pl_report = PlaylistReport(name=playlist_name, path=playlist_path)
    matched_uris: list[str] = []

    total = len(tracks)
    for i, track in enumerate(tracks):
        if on_progress:
            on_progress(ProgressEvent(
                phase="matching",
                current=i + 1,
                total=total,
                detail=track.display[:80],
            ))

        if cache is not None:
            result, source = match_track_cached(
                sp, track, cache, threshold=threshold,
                retry_days=retry_days, force_retry=retry,
            )
            if source == "cache":
                pl_report.cache_hits += 1
            elif source == "retry":
                pl_report.retried += 1
            else:
                pl_report.api_lookups += 1
        else:
            result = match_track(sp, track, threshold=threshold)
            pl_report.api_lookups += 1

        if result:
            matched_uris.append(result["uri"])
            pl_report.matched.append(MatchedTrack(
                source_name=track.display,
                spotify_name=result["name"],
                spotify_artist=result["artist"],
                score=result["score"],
                match_type=result.get("match_type", "exact"),
                score_reasons=tuple(result.get("score_reasons", ())),
            ))
        else:
            pl_report.unmatched.append(track.display)

    # Deduplicate URIs
    seen_uris: set[str] = set()
    unique_uris: list[str] = []
    for uri in matched_uris:
        if uri not in seen_uris:
            seen_uris.add(uri)
            unique_uris.append(uri)
    matched_uris = unique_uris

    if not dry_run and matched_uris:
        if on_progress:
            on_progress(ProgressEvent(phase="syncing", detail="Creating/updating playlist..."))

        source_labels = {
            "rekordbox": "Rekordbox",
            "beatport": "Beatport",
            "label": "Beatport label",
        }
        source_label = source_labels.get(source_type, source_type)
        description = (
            f"Synced from {source_label} by djsupport"
            if source_type == "rekordbox"
            else f"Imported from {source_label} by djsupport"
        )

        if incremental:
            playlist_id, action, _diff = incremental_update_playlist(
                sp, playlist_name, matched_uris, existing_playlists,
                prefix=prefix, state_manager=state_mgr,
                source_path=playlist_path, source_type=source_type,
                description=description,
            )
        else:
            playlist_id, action = create_or_update_playlist(
                sp, playlist_name, matched_uris, existing_playlists,
                prefix=prefix, state_manager=state_mgr,
                source_path=playlist_path, source_type=source_type,
                description=description,
            )
        pl_report.action = action
        pl_report.spotify_playlist_id = playlist_id
        if existing_playlists is not None:
            formatted = format_playlist_name(playlist_name, prefix)
            existing_playlists[formatted] = playlist_id
    elif dry_run:
        pl_report.action = "dry-run"

    return pl_report


def sync_beatport_chart(
    url: str,
    *,
    sp: spotipy.Spotify,
    cache: MatchCache | None,
    state_mgr: PlaylistStateManager,
    threshold: int = 80,
    prefix: str | None = "djsupport",
    dry_run: bool = False,
    incremental: bool = True,
    retry: bool = False,
    retry_days: int = 7,
    on_progress: ProgressCallback | None = None,
) -> SyncReport:
    """Fetch a Beatport chart and sync it to Spotify.

    Returns a SyncReport.  Raises RateLimitError on excessive rate limiting.
    """
    from djsupport.beatport import compose_chart_playlist_name, fetch_chart, validate_url

    if on_progress:
        on_progress(ProgressEvent(phase="fetching", detail="Validating URL..."))
    url = validate_url(url)

    if on_progress:
        on_progress(ProgressEvent(phase="fetching", detail="Fetching chart from Beatport..."))
    chart_name, curator, tracks = fetch_chart(url)
    playlist_name = compose_chart_playlist_name(chart_name, curator)

    if not tracks:
        report = SyncReport(
            timestamp=datetime.now(), threshold=threshold,
            dry_run=dry_run, cache_enabled=cache is not None,
            source_label="Beatport",
        )
        report.playlists.append(PlaylistReport(name=playlist_name, path=url))
        return report

    existing = get_user_playlists(sp) if not dry_run else None

    report = SyncReport(
        timestamp=datetime.now(), threshold=threshold,
        dry_run=dry_run, cache_enabled=cache is not None,
        source_label="Beatport",
    )

    pl_report = match_and_sync_playlist(
        tracks, playlist_name, url,
        sp=sp, cache=cache, state_mgr=state_mgr,
        existing_playlists=existing, threshold=threshold,
        dry_run=dry_run, incremental=incremental,
        prefix=prefix, retry_days=retry_days, retry=retry,
        source_type="beatport", on_progress=on_progress,
    )
    report.playlists.append(pl_report)

    if on_progress:
        on_progress(ProgressEvent(phase="complete", detail="Sync complete"))

    return report


def sync_beatport_label(
    url: str,
    *,
    sp: spotipy.Spotify,
    cache: MatchCache | None,
    state_mgr: PlaylistStateManager,
    threshold: int = 80,
    prefix: str | None = "djsupport",
    dry_run: bool = False,
    incremental: bool = True,
    retry: bool = False,
    retry_days: int = 7,
    on_progress: ProgressCallback | None = None,
) -> SyncReport:
    """Fetch a Beatport label's tracks and sync to Spotify.

    Returns a SyncReport.  Raises RateLimitError on excessive rate limiting.
    """
    from djsupport.label import (
        deduplicate_tracks,
        fetch_label_tracks,
        validate_label_url,
    )

    if on_progress:
        on_progress(ProgressEvent(phase="fetching", detail="Validating URL..."))
    url = validate_label_url(url)

    if on_progress:
        on_progress(ProgressEvent(phase="fetching", detail="Fetching label tracks from Beatport..."))

    def _on_page(page: int, total_pages: int) -> None:
        if on_progress:
            on_progress(ProgressEvent(
                phase="fetching",
                current=page,
                total=total_pages,
                detail=f"Fetching page {page}/{total_pages}",
            ))

    label_name, tracks = fetch_label_tracks(
        url, on_page=_on_page,
    )

    if not tracks:
        report = SyncReport(
            timestamp=datetime.now(), threshold=threshold,
            dry_run=dry_run, cache_enabled=cache is not None,
            source_label="Beatport",
        )
        report.playlists.append(PlaylistReport(name=label_name, path=url))
        return report

    tracks, _dupes_removed = deduplicate_tracks(tracks)

    existing = get_user_playlists(sp) if not dry_run else None

    report = SyncReport(
        timestamp=datetime.now(), threshold=threshold,
        dry_run=dry_run, cache_enabled=cache is not None,
        source_label="Beatport",
    )

    pl_report = match_and_sync_playlist(
        tracks, label_name, url,
        sp=sp, cache=cache, state_mgr=state_mgr,
        existing_playlists=existing, threshold=threshold,
        dry_run=dry_run, incremental=incremental,
        prefix=prefix, retry_days=retry_days, retry=retry,
        source_type="label", on_progress=on_progress,
    )
    report.playlists.append(pl_report)

    if on_progress:
        on_progress(ProgressEvent(phase="complete", detail="Sync complete"))

    return report
