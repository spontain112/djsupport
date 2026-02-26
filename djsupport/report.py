"""Post-sync report generation for terminal and Markdown output."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MatchedTrack:
    source_name: str
    spotify_name: str
    spotify_artist: str
    score: float
    match_type: str = "exact"


@dataclass
class PlaylistReport:
    name: str
    path: str
    matched: list[MatchedTrack] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    action: str = "dry-run"  # "created", "updated", "unchanged", or "dry-run"
    cache_hits: int = 0
    api_lookups: int = 0
    retried: int = 0

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
    """Print a concise terminal summary of the sync report."""
    import click

    ts = report.timestamp.strftime("%Y-%m-%d %H:%M")
    mode = "dry-run" if report.dry_run else "live"

    click.echo()
    click.echo("\u2550" * 42)
    click.echo(f"  Sync Report  {ts}")
    click.echo(f"  Mode: {mode}  |  Threshold: {report.threshold}")
    click.echo("\u2550" * 42)

    for pl in report.playlists:
        click.echo()
        click.echo(f"Playlist: {pl.path}  ({pl.action})")
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
    mode = "dry-run" if report.dry_run else "live"
    lines: list[str] = []

    lines.append(f"# Sync Report — {ts}")
    lines.append("")
    lines.append(f"**Mode:** {mode}  |  **Threshold:** {report.threshold}")
    lines.append("")

    for pl in report.playlists:
        lines.append(f"## {pl.path}  ({pl.action})")
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
            lines.append(f"| {report.source_label} | Spotify Match | Score | Match Type |")
            lines.append("|-----------|---------------|-------|------------|")
            for m in pl.matched:
                lines.append(
                    f"| {m.source_name} | {m.spotify_artist} - {m.spotify_name}"
                    f" | {m.score:.1f} | {m.match_type} |"
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
            if m.score < 90 or m.match_type == "fallback_version":
                low_confidence.append((pl.path, m))

    if low_confidence:
        lines.append("## Low Confidence Matches (score < 90)")
        lines.append("")
        lines.append(f"| Playlist | {report.source_label} | Spotify Match | Score | Match Type |")
        lines.append("|----------|-----------|---------------|-------|------------|")
        for pl_path, m in low_confidence:
            lines.append(
                f"| {pl_path} | {m.source_name}"
                f" | {m.spotify_artist} - {m.spotify_name} | {m.score:.1f} | {m.match_type} |"
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
    lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines))
