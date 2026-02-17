"""CLI entry point for djsupport."""

import sys

import click
from dotenv import load_dotenv

from djsupport.matcher import match_track
from djsupport.rekordbox import parse_xml
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
def sync(xml_path: str, playlist: str | None, dry_run: bool, threshold: int):
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

    total_matched = 0
    total_unmatched = 0
    all_unmatched: list[str] = []

    for pl in playlists:
        click.echo(f"\n{'=' * 60}")
        click.echo(f"Playlist: {pl.path} ({len(pl.track_ids)} tracks)")
        click.echo("=" * 60)

        matched_uris: list[str] = []
        unmatched: list[str] = []

        with click.progressbar(pl.track_ids, label="Matching tracks") as bar:
            for tid in bar:
                track = tracks.get(tid)
                if track is None:
                    continue

                result = match_track(sp, track, threshold=threshold)
                if result:
                    matched_uris.append(result["uri"])
                else:
                    unmatched.append(track.display)

        total_matched += len(matched_uris)
        total_unmatched += len(unmatched)

        click.echo(f"  Matched: {len(matched_uris)}/{len(pl.track_ids)}")

        if unmatched:
            click.echo(f"  Unmatched ({len(unmatched)}):")
            for name in unmatched:
                click.echo(f"    - {name}")
            all_unmatched.extend(unmatched)

        if not dry_run and matched_uris:
            playlist_id = create_or_update_playlist(sp, pl.name, matched_uris, existing)
            click.echo(f"  -> Spotify playlist updated: {pl.name} (id: {playlist_id})")
            # Update cache so subsequent playlists see this one
            if existing is not None:
                existing[pl.name] = playlist_id
        elif dry_run:
            click.echo("  (dry run - no changes made)")

    click.echo(f"\n{'=' * 60}")
    click.echo(f"Total matched: {total_matched}")
    click.echo(f"Total unmatched: {total_unmatched}")

    if all_unmatched:
        click.echo(f"\nAll unmatched tracks ({len(all_unmatched)}):")
        for name in all_unmatched:
            click.echo(f"  - {name}")


@cli.command("list")
@click.argument("xml_path", type=click.Path(exists=True))
def list_playlists(xml_path: str):
    """List all playlists in a Rekordbox XML export."""
    _, playlists = parse_xml(xml_path)
    for pl in playlists:
        click.echo(f"  {pl.path} ({len(pl.track_ids)} tracks)")
