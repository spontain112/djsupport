"""CLI entry point for djsupport."""

import sys
from datetime import datetime

import click
from dotenv import load_dotenv

from djsupport.matcher import match_track
from djsupport.rekordbox import parse_xml
from djsupport.report import (
    MatchedTrack,
    PlaylistReport,
    SyncReport,
    print_report,
    save_report,
)
from djsupport.spotify import create_or_update_playlist, get_client, get_user_playlists


@click.group()
def cli():
    """DJ Support - Sync Rekordbox playlists to Spotify."""
    load_dotenv()


@cli.command()
@click.argument("xml_path", type=click.Path(exists=True))
@click.option("--playlist", "-p", help="Sync only this playlist (by name).")
@click.option("--dry-run", is_flag=True, help="Preview matches without creating playlists.")
@click.option("--threshold", "-t", default=80, show_default=True, help="Minimum match confidence (0-100).")
@click.option("--report", "report_path", type=click.Path(), default=None, help="Save detailed Markdown report to this path.")
def sync(xml_path: str, playlist: str | None, dry_run: bool, threshold: int, report_path: str | None):
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
    )

    for pl in playlists:
        pl_report = PlaylistReport(name=pl.name, path=pl.path)
        matched_uris: list[str] = []

        with click.progressbar(pl.track_ids, label=f"Matching: {pl.name}") as bar:
            for tid in bar:
                track = tracks.get(tid)
                if track is None:
                    continue

                result = match_track(sp, track, threshold=threshold)
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
            playlist_id, action = create_or_update_playlist(sp, pl.name, matched_uris, existing)
            pl_report.action = action
            # Update cache so subsequent playlists see this one
            if existing is not None:
                existing[pl.name] = playlist_id
        elif dry_run:
            pl_report.action = "dry-run"

        report.playlists.append(pl_report)

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
