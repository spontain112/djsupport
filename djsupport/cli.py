"""CLI entry point for djsupport."""

import sys
from datetime import datetime

import click
from dotenv import load_dotenv

from djsupport.matcher import match_track, match_track_cached
from djsupport.rekordbox import parse_xml
from djsupport.report import (
    MatchedTrack,
    PlaylistReport,
    SyncReport,
    print_report,
    save_report,
)
from djsupport.spotify import (
    create_or_update_playlist,
    get_client,
    get_user_playlists,
    incremental_update_playlist,
)


@click.group()
def cli():
    """DJ Support - Sync Rekordbox playlists to Spotify."""
    load_dotenv()


@cli.command()
@click.argument("xml_path", type=click.Path(exists=True))
@click.option("--playlist", "-p", help="Sync only this playlist (by name).")
@click.option("--dry-run", is_flag=True, help="Preview matches without creating playlists.")
@click.option("--threshold", "-t", default=80, show_default=True, help="Minimum match confidence (0-100).")
@click.option("--all", "combine_all", is_flag=True, help="Combine all tracks into a single playlist instead of per-folder.")
@click.option("--all-name", default="Rekordbox All", show_default=True, help="Name for the combined playlist (used with --all).")
@click.option("--report", "report_path", type=click.Path(), default=None, help="Save detailed Markdown report to this path.")
@click.option("--no-cache", is_flag=True, help="Bypass cache; search Spotify for every track.")
@click.option("--retry", is_flag=True, help="Force retry all previously failed matches.")
@click.option("--retry-days", default=7, show_default=True, help="Auto-retry failures older than N days.")
@click.option("--cache-path", default=".djsupport_cache.json", show_default=True, help="Path to cache file.")
@click.option("--incremental/--no-incremental", default=True, show_default=True, help="Use incremental playlist updates.")
def sync(
    xml_path: str,
    playlist: str | None,
    dry_run: bool,
    threshold: int,
    combine_all: bool,
    all_name: str,
    report_path: str | None,
    no_cache: bool,
    retry: bool,
    retry_days: int,
    cache_path: str,
    incremental: bool,
):
    """Sync Rekordbox playlists to Spotify.

    XML_PATH is the path to your Rekordbox XML library export.
    """
    click.echo(f"Parsing {xml_path}...")
    tracks, playlists = parse_xml(xml_path)
    click.echo(f"Found {len(tracks)} tracks and {len(playlists)} playlists.")

    # Filter to a specific playlist if requested
    if playlist:
        playlists = [p for p in playlists if p.name == playlist]
        if not playlists:
            click.echo(f"Playlist '{playlist}' not found.", err=True)
            sys.exit(1)

    # Combine all tracks into a single playlist, sorted by date added
    if combine_all:
        seen: set[str] = set()
        all_track_ids: list[str] = []
        for pl in playlists:
            for tid in pl.track_ids:
                if tid not in seen:
                    seen.add(tid)
                    all_track_ids.append(tid)
        all_track_ids.sort(key=lambda tid: tracks[tid].date_added if tid in tracks else "")
        from djsupport.rekordbox import Playlist as RBPlaylist
        playlists = [RBPlaylist(name=all_name, path=all_name, track_ids=all_track_ids)]
        click.echo(f"Combined {len(all_track_ids)} unique tracks into '{all_name}' (sorted by date added).")

    # Initialize cache
    cache = None
    if not no_cache:
        from djsupport.cache import MatchCache
        cache = MatchCache(cache_path)
        cache.load()
        cached_count = len(cache.entries)
        if cached_count:
            click.echo(f"Loaded {cached_count} cached matches from {cache_path}")

    if not dry_run:
        sp = get_client()
        existing = get_user_playlists(sp)
    else:
        sp = get_client()
        existing = None

    report = SyncReport(
        timestamp=datetime.now(),
        threshold=threshold,
        dry_run=dry_run,
        cache_enabled=cache is not None,
    )

    for pl in playlists:
        pl_report = PlaylistReport(name=pl.name, path=pl.path)
        matched_uris: list[str] = []

        with click.progressbar(pl.track_ids, label=f"Matching: {pl.name}") as bar:
            for tid in bar:
                track = tracks.get(tid)
                if track is None:
                    continue

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
                        rekordbox_name=track.display,
                        spotify_name=result["name"],
                        spotify_artist=result["artist"],
                        score=result["score"],
                    ))
                else:
                    pl_report.unmatched.append(track.display)

        if not dry_run and matched_uris:
            if incremental:
                playlist_id, action, _diff = incremental_update_playlist(
                    sp, pl.name, matched_uris, existing,
                )
            else:
                playlist_id, action = create_or_update_playlist(
                    sp, pl.name, matched_uris, existing,
                )
            pl_report.action = action
            if existing is not None:
                existing[pl.name] = playlist_id
        elif dry_run:
            pl_report.action = "dry-run"

        report.playlists.append(pl_report)

    # Save cache (even in dry-run — API lookups are still worth caching)
    if cache is not None:
        cache.save()

    print_report(report)

    if report_path:
        save_report(report, report_path)
        click.echo(f"\nDetailed report saved to {report_path}")


@cli.command("list")
@click.argument("xml_path", type=click.Path(exists=True))
def list_playlists(xml_path: str):
    """List all playlists in a Rekordbox XML export."""
    _, playlists = parse_xml(xml_path)
    for pl in playlists:
        click.echo(f"  {pl.path} ({len(pl.track_ids)} tracks)")
