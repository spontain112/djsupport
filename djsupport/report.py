"""Transfer outcome reporting for terminal, Markdown, and Correction CSV."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from djsupport.source_facts import SourceOccurrence

if TYPE_CHECKING:
    from djsupport.transfer import PublicationManifest


@dataclass
class MatchedTrack:
    source_name: str
    spotify_name: str
    spotify_artist: str
    score: float
    match_type: str = "exact"
    score_reasons: tuple[str, ...] = ()
    source_track_id: str = ""
    spotify_uri: str = ""


@dataclass(frozen=True)
class ReviewTrack:
    source_track_id: str
    source_name: str
    source_occurrence: SourceOccurrence | dict | None = None
    source_artist: str = ""
    source_title: str = ""
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

    def __post_init__(self) -> None:
        if isinstance(self.source_occurrence, dict):
            object.__setattr__(
                self,
                "source_occurrence",
                SourceOccurrence.from_storage(self.source_occurrence),
            )

    @property
    def occurrence_id(self) -> str:
        return (
            self.source_occurrence.occurrence_id
            if isinstance(self.source_occurrence, SourceOccurrence) else ""
        )

    @property
    def source_position(self) -> int:
        return (
            self.source_occurrence.position
            if isinstance(self.source_occurrence, SourceOccurrence) else 0
        )

    @property
    def source_facts(self) -> dict:
        occurrence = self.source_occurrence
        if not isinstance(occurrence, SourceOccurrence) or occurrence.facts is None:
            return {}
        return occurrence.facts.to_review_facts()


@dataclass(frozen=True)
class AlternativeCandidate:
    rank: int
    spotify_uri: str
    spotify_name: str
    spotify_artist: str
    version: str
    duration_ms: int
    score: float
    score_reasons: tuple[str, ...]


@dataclass(frozen=True)
class UnmatchedAlternatives:
    source_track_id: str
    source_name: str
    candidates: tuple[AlternativeCandidate, ...]


@dataclass(frozen=True)
class UnavailableApprovedMatch:
    source_track_id: str
    source_name: str
    spotify_uri: str


@dataclass(frozen=True)
class MatchCollision:
    source_track_id: str
    source_name: str
    spotify_uri: str


@dataclass(frozen=True)
class SourceRemoval:
    source_track_id: str
    source_name: str
    spotify_uri: str


@dataclass(frozen=True)
class PlaylistDrift:
    source_track_id: str
    source_name: str
    spotify_uri: str


def _spotify_url(uri: str) -> str:
    if uri.startswith("spotify:track:"):
        return f"https://open.spotify.com/track/{uri.removeprefix('spotify:track:')}"
    return uri


@dataclass
class PlaylistReport:
    name: str
    path: str
    matched: list[MatchedTrack] = field(default_factory=list)
    review_items: list[ReviewTrack] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    alternatives: list[UnmatchedAlternatives] = field(default_factory=list)
    unavailable_approved: list[UnavailableApprovedMatch] = field(default_factory=list)
    match_collisions: list[MatchCollision] = field(default_factory=list)
    source_removals: list[SourceRemoval] = field(default_factory=list)
    playlist_drift: list[PlaylistDrift] = field(default_factory=list)
    drift_choices: tuple[str, ...] = ()
    mirror_dispositions: tuple[str, ...] = ()
    mirror_disposition: str | None = None
    action: str = "dry-run"  # "created", "updated", "unchanged", or "dry-run"
    outcome: str = "completed"
    spotify_playlist_id: str | None = None
    publication_manifest: PublicationManifest | None = None
    cache_hits: int = 0
    api_lookups: int = 0
    retried: int = 0
    local_audio_eligible: int = 0
    local_audio_observed: int = 0
    local_audio_unavailable: int = 0
    local_audio_reused: int = 0

    @property
    def total(self) -> int:
        return len(self.matched) + len(self.unmatched)

    @property
    def match_rate(self) -> float:
        return (len(self.matched) / self.total * 100) if self.total else 0.0


@dataclass
class SyncReport:
    timestamp: datetime
    threshold: int
    dry_run: bool
    playlists: list[PlaylistReport] = field(default_factory=list)
    cache_enabled: bool = False
    source_label: str = "Rekordbox"
    transfer_id: str | None = None
    status: str = "completed"

    @property
    def total_matched(self) -> int:
        return sum(len(p.matched) for p in self.playlists)

    @property
    def total_unmatched(self) -> int:
        return sum(len(p.unmatched) for p in self.playlists)

    @property
    def overall_match_rate(self) -> float:
        total = self.total_matched + self.total_unmatched
        return (self.total_matched / total * 100) if total else 0.0


def print_report(report: SyncReport) -> None:
    """Print a concise terminal summary of a Transfer outcome."""
    import click

    ts = report.timestamp.strftime("%Y-%m-%d %H:%M")
    mode = "Preview" if report.dry_run else "Transfer"

    click.echo()
    click.echo("\u2550" * 42)
    click.echo(f"  Transfer Report  {ts}")
    click.echo(f"  Mode: {mode}  |  Threshold: {report.threshold}")
    if report.transfer_id:
        click.echo(f"  Transfer: {report.transfer_id}  |  Status: {report.status}")
    click.echo("\u2550" * 42)

    for pl in report.playlists:
        click.echo()
        click.echo(
            f"Playlist: {pl.path}  ({pl.action})  |  Outcome: {pl.outcome}"
        )
        click.echo(f"  Matched:  {len(pl.matched)}/{pl.total} ({pl.match_rate:.1f}%)")

        if pl.matched:
            scores = [m.score for m in pl.matched]
            click.echo(
                f"  Scores:   avg {sum(scores)/len(scores):.1f}"
                f"  min {min(scores):.1f}"
                f"  max {max(scores):.1f}"
            )
            fallback_count = sum(1 for m in pl.matched if m.match_type == "fallback_version")
            if fallback_count:
                click.echo(f"  Version fallbacks: {fallback_count}")

        if pl.unmatched:
            click.echo(f"  Unmatched ({len(pl.unmatched)}):")
            for name in pl.unmatched:
                click.echo(f"    - {name}")

        if report.cache_enabled:
            click.echo(f"  Cache: {pl.cache_hits} hits | {pl.api_lookups} API | {pl.retried} retries")
        if (
            pl.local_audio_eligible or pl.local_audio_observed
            or pl.local_audio_unavailable or pl.local_audio_reused
        ):
            click.echo(
                f"  Local audio: {pl.local_audio_eligible} eligible"
                f" | {pl.local_audio_observed} observed"
                f" | {pl.local_audio_reused} Approved Match reuses"
                f" | {pl.local_audio_unavailable} unavailable"
            )

    click.echo()
    click.echo("\u2500" * 42)
    total_cache = sum(p.cache_hits for p in report.playlists)
    total_api = sum(p.api_lookups for p in report.playlists)
    total_retries = sum(p.retried for p in report.playlists)
    click.echo(
        f"  TOTALS: {len(report.playlists)} playlists"
        f" | {report.total_matched} matched"
        f" | {report.total_unmatched} unmatched"
    )
    click.echo(f"  Overall match rate: {report.overall_match_rate:.1f}%")
    if report.cache_enabled:
        click.echo(f"  Cache: {total_cache} hits | {total_api} API calls | {total_retries} retries")
    click.echo("\u2500" * 42)


def save_report(report: SyncReport, path: str) -> None:
    """Save a detailed Markdown report to a file."""
    ts = report.timestamp.strftime("%Y-%m-%d %H:%M")
    mode = "Preview" if report.dry_run else "Transfer"
    lines: list[str] = []

    lines.append(f"# Transfer Report — {ts}")
    lines.append("")
    lines.append(f"**Mode:** {mode}  |  **Threshold:** {report.threshold}")
    if report.transfer_id:
        lines.append(f"**Transfer:** {report.transfer_id}  |  **Status:** {report.status}")
    elif report.status != "completed":
        lines.append(f"**Status:** {report.status}")
    lines.append("")

    for pl in report.playlists:
        lines.append(f"## {pl.path}  ({pl.action})")
        lines.append("")
        lines.append(f"**Outcome:** {pl.outcome}")
        lines.append("")
        lines.append(f"**Matched:** {len(pl.matched)}/{pl.total} ({pl.match_rate:.1f}%)")

        if pl.matched:
            scores = [m.score for m in pl.matched]
            lines.append(
                f"**Scores:** avg {sum(scores)/len(scores):.1f}"
                f" | min {min(scores):.1f}"
                f" | max {max(scores):.1f}"
            )
            fallback_count = sum(1 for m in pl.matched if m.match_type == "fallback_version")
            if fallback_count:
                lines.append(f"**Version fallbacks:** {fallback_count}")

        lines.append("")

        if pl.matched:
            lines.append(
                f"| Source Reference | {report.source_label} | Spotify Proposal"
                " | Score | Match Type | Score Reasons |"
            )
            lines.append(
                "|------------------|-----------|------------------|-------|------------|---------------|"
            )
            for m in pl.matched:
                reasons = "; ".join(m.score_reasons)
                proposal = f"{m.spotify_artist} - {m.spotify_name}"
                if m.spotify_uri:
                    proposal = f"[{proposal}]({_spotify_url(m.spotify_uri)})"
                lines.append(
                    f"| {m.source_track_id} | {m.source_name} | {proposal}"
                    f" | {m.score:.1f} | {m.match_type} | {reasons} |"
                )
            lines.append("")

        for uncertain in pl.alternatives:
            lines.append(f"### Alternatives for {uncertain.source_name}")
            lines.append("")
            for candidate in uncertain.candidates:
                reasons = "; ".join(candidate.score_reasons)
                lines.append(
                    f"{candidate.rank}. [{candidate.spotify_artist} - "
                    f"{candidate.spotify_name}]({_spotify_url(candidate.spotify_uri)}) "
                    f"— {candidate.version}, {candidate.duration_ms / 1000:.0f}s, "
                    f"score {candidate.score:.1f} ({reasons})"
                )
            lines.append("")

        if pl.unavailable_approved:
            lines.append("### Unavailable Approved Matches")
            lines.append("")
            for unavailable in pl.unavailable_approved:
                lines.append(
                    f"- {unavailable.source_name}: retained authoritative mapping "
                    f"to `{unavailable.spotify_uri}`; no replacement attempted"
                )
            lines.append("")

        if pl.match_collisions:
            lines.append("### Match Collisions (review required)")
            lines.append("")
            for collision in pl.match_collisions:
                lines.append(
                    f"- {collision.source_track_id}: {collision.source_name} → "
                    f"`{collision.spotify_uri}`"
                )
            lines.append("")

        if pl.source_removals:
            lines.append("### Source Removals")
            lines.append("")
            for removal in pl.source_removals:
                lines.append(
                    f"- {removal.source_track_id}: {removal.source_name} → "
                    f"`{removal.spotify_uri}` removed from the Mirror"
                )
            lines.append("")

        if pl.playlist_drift:
            lines.append("### Playlist Drift (decision required)")
            lines.append("")
            for drift in pl.playlist_drift:
                lines.append(
                    f"- {drift.source_track_id}: {drift.source_name} → "
                    f"`{drift.spotify_uri}` is missing in Spotify"
                )
            lines.append(
                "Choose explicitly: " + " or ".join(pl.drift_choices)
            )
            lines.append("")

        if pl.mirror_dispositions:
            lines.append("### Orphaned Mirror (decision required)")
            lines.append("")
            lines.append(
                "Choose explicitly: " + ", ".join(pl.mirror_dispositions[:-1])
                + f", or {pl.mirror_dispositions[-1]}"
            )
            lines.append("")

        if pl.mirror_disposition:
            lines.append(
                f"**Orphaned Mirror disposition:** {pl.mirror_disposition}"
            )
            lines.append("")

        if pl.unmatched:
            lines.append(f"### Unmatched ({len(pl.unmatched)})")
            lines.append("")
            for name in pl.unmatched:
                lines.append(f"- {name}")
            lines.append("")

    # Low confidence section
    low_confidence = []
    for pl in report.playlists:
        for m in pl.matched:
            if m.score < 90 or m.match_type in {
                "fallback_version", "shorter_version",
            }:
                low_confidence.append((pl.path, m))

    if low_confidence:
        lines.append("## Low Confidence and Version Review Matches")
        lines.append("")
        lines.append(
            f"| Playlist | {report.source_label} | Spotify Match | Score"
            " | Match Type | Reasons |"
        )
        lines.append(
            "|----------|-----------|---------------|-------|------------|---------|"
        )
        for pl_path, m in low_confidence:
            reasons = "; ".join(m.score_reasons)
            lines.append(
                f"| {pl_path} | {m.source_name}"
                f" | {m.spotify_artist} - {m.spotify_name} | {m.score:.1f}"
                f" | {m.match_type} | {reasons} |"
            )
        lines.append("")

    # Totals
    lines.append("---")
    lines.append("")
    lines.append(
        f"**Totals:** {len(report.playlists)} playlists"
        f" | {report.total_matched} matched"
        f" | {report.total_unmatched} unmatched"
        f" | {report.overall_match_rate:.1f}% match rate"
    )
    if report.cache_enabled:
        total_cache = sum(p.cache_hits for p in report.playlists)
        total_api = sum(p.api_lookups for p in report.playlists)
        total_retries = sum(p.retried for p in report.playlists)
        lines.append(
            f"**Cache:** {total_cache} hits"
            f" | {total_api} API calls"
            f" | {total_retries} retries"
        )
    local_eligible = sum(p.local_audio_eligible for p in report.playlists)
    local_observed = sum(p.local_audio_observed for p in report.playlists)
    local_reused = sum(p.local_audio_reused for p in report.playlists)
    local_unavailable = sum(p.local_audio_unavailable for p in report.playlists)
    if local_eligible or local_observed or local_reused or local_unavailable:
        lines.append(
            f"**Local audio:** {local_eligible} eligible"
            f" | {local_observed} observed"
            f" | {local_reused} Approved Match reuses"
            f" | {local_unavailable} unavailable"
        )
    lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines))


def save_review_csv(report: SyncReport, path: str) -> None:
    """Write editable proposal rows keyed by stable source-track references."""
    with open(path, "w", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow([
            "source_track_id", "source_track", "spotify_url", "spotify_track",
            "score", "match_type", "score_reasons", "source_artist", "source_title",
            "source_release", "source_label", "source_version", "source_duration",
            "spotify_release", "spotify_duration", "authority_status",
        ])
        for playlist in report.playlists:
            review_items = (
                playlist.review_items
                or (
                    list(playlist.publication_manifest.items)
                    if playlist.publication_manifest is not None else []
                )
            )
            if review_items:
                for item in review_items:
                    writer.writerow([
                        item.source_track_id,
                        item.source_name,
                        _spotify_url(item.spotify_uri) if item.spotify_uri else "",
                        (
                            f"{item.spotify_artist} - {item.spotify_name}"
                            if item.spotify_uri else ""
                        ),
                        f"{item.score:.1f}" if item.spotify_uri else "",
                        item.match_type,
                        "; ".join(item.score_reasons),
                        item.source_artist,
                        item.source_title,
                        item.source_release,
                        item.source_label,
                        item.source_version,
                        item.source_duration,
                        item.spotify_release,
                        item.spotify_duration,
                        item.authority_status,
                    ])
                continue
            for match in playlist.matched:
                writer.writerow([
                    match.source_track_id,
                    match.source_name,
                    _spotify_url(match.spotify_uri),
                    f"{match.spotify_artist} - {match.spotify_name}",
                    f"{match.score:.1f}",
                    match.match_type,
                    "; ".join(match.score_reasons),
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ])
