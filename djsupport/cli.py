"""CLI entry point for djsupport."""

import sys
from datetime import datetime
from pathlib import Path

import click
from dotenv import load_dotenv

from djsupport.config import ConfigManager, validate_rekordbox_xml
from djsupport.matcher import match_track, match_track_cached
from djsupport.rekordbox import Track, parse_xml
from djsupport.report import (
    MatchedTrack,
    PlaylistReport,
    SyncReport,
    print_report,
    save_report,
)
from djsupport.spotify import (
    RateLimitError,
    create_or_update_playlist,
    format_playlist_name,
    get_client,
    get_user_playlists,
    incremental_update_playlist,
)


@click.group()
def cli():
    """DJ Support - Sync Rekordbox playlists to Spotify."""
    load_dotenv()


def _resolve_xml_path(explicit_xml_path: str | None) -> str:
    """Resolve Rekordbox XML path from explicit arg or saved local config."""
    if explicit_xml_path:
        return explicit_xml_path

    cfg = ConfigManager()
    cfg.load()
    saved_path = cfg.get_rekordbox_xml_path()
    if not saved_path:
        raise click.ClickException(
            "No Rekordbox XML path configured. "
            "Run `djsupport library set /path/to/library.xml` "
            "or pass an explicit XML path."
        )

    p = Path(saved_path).expanduser()
    if not p.exists() or not p.is_file():
        raise click.ClickException(
            "Configured Rekordbox XML path is missing or invalid:\n"
            f"  {p}\n"
            "Run `djsupport library set /path/to/library.xml` to update it."
        )
    return str(p)


def _match_and_sync_playlist(
    tracks: list[Track],
    playlist_name: str,
    playlist_path: str,
    *,
    sp,
    cache,
    state_mgr,
    existing_playlists: dict[str, str] | None,
    threshold: int,
    dry_run: bool,
    incremental: bool,
    prefix: str | None,
    retry_days: int = 7,
    retry: bool = False,
    source_type: str = "rekordbox",
) -> PlaylistReport:
    """Match tracks to Spotify and create/update a playlist.

    Returns a PlaylistReport. Raises RateLimitError if Spotify rate limit
    is exceeded — caller should save cache and handle the abort.
    """
    pl_report = PlaylistReport(name=playlist_name, path=playlist_path)
    matched_uris: list[str] = []

    with click.progressbar(
        tracks,
        label=f"Matching: {playlist_name}",
        show_eta=True,
        show_percent=True,
        show_pos=True,
        item_show_func=lambda t: t.display[:50] if t else "",
    ) as bar:
        for track in bar:
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
                ))
            else:
                pl_report.unmatched.append(track.display)

    # Deduplicate URIs (different source tracks can resolve to the same Spotify track)
    seen_uris: set[str] = set()
    unique_uris: list[str] = []
    for uri in matched_uris:
        if uri not in seen_uris:
            seen_uris.add(uri)
            unique_uris.append(uri)
    matched_uris = unique_uris

    if not dry_run and matched_uris:
        source_labels = {"rekordbox": "Rekordbox", "beatport": "Beatport", "label": "Beatport label"}
        source_label = source_labels.get(source_type, source_type)
        description = f"Synced from {source_label} by djsupport" if source_type == "rekordbox" else f"Imported from {source_label} by djsupport"

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
        if existing_playlists is not None:
            formatted = format_playlist_name(playlist_name, prefix)
            existing_playlists[formatted] = playlist_id
    elif dry_run:
        pl_report.action = "dry-run"

    return pl_report


@cli.group()
def library():
    """Manage local Rekordbox XML path configuration."""


@library.command("set")
@click.argument("xml_path", type=click.Path(exists=True, dir_okay=False))
def library_set(xml_path: str):
    """Validate and save the default Rekordbox XML path."""
    ok, error = validate_rekordbox_xml(xml_path)
    if not ok:
        raise click.ClickException(error or "Invalid Rekordbox XML file.")

    cfg = ConfigManager()
    cfg.load()
    cfg.set_rekordbox_xml_path(xml_path)
    cfg.save()

    click.echo(f"Saved Rekordbox XML path: {cfg.get_rekordbox_xml_path()}")


@library.command("show")
def library_show():
    """Show configured Rekordbox XML path and validation status."""
    cfg = ConfigManager()
    cfg.load()
    xml_path = cfg.get_rekordbox_xml_path()
    if not xml_path:
        click.echo("Rekordbox XML path is not configured.")
        click.echo("Set it with: djsupport library set /path/to/library.xml")
        return

    click.echo(f"Configured Rekordbox XML path: {xml_path}")
    ok, error = validate_rekordbox_xml(xml_path)
    if ok:
        click.echo("Status: OK (exists and parseable)")
    else:
        click.echo(f"Status: INVALID ({error})")


@cli.command()
@click.argument("xml_path", required=False, type=click.Path(exists=True, dir_okay=False))
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
@click.option("--prefix", default="djsupport", show_default=True, help="Prefix for Spotify playlist names.")
@click.option("--no-prefix", is_flag=True, help="Disable playlist name prefix.")
@click.option("--state-path", default=".djsupport_playlists.json", show_default=True, help="Path to playlist state file.")
def sync(
    xml_path: str | None,
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
    prefix: str,
    no_prefix: bool,
    state_path: str,
):
    """Sync Rekordbox playlists to Spotify.

    XML_PATH is the path to your Rekordbox XML library export (optional if configured via `library set`).
    """
    xml_path = _resolve_xml_path(xml_path)
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

    # Resolve prefix
    actual_prefix = None if no_prefix else prefix

    # Initialize playlist state manager
    from djsupport.state import PlaylistStateManager
    state_mgr = PlaylistStateManager(state_path)
    state_mgr.load()

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
        # Resolve track IDs to Track objects
        pl_tracks = [tracks[tid] for tid in pl.track_ids if tid in tracks]

        try:
            pl_report = _match_and_sync_playlist(
                pl_tracks,
                pl.name,
                pl.path,
                sp=sp,
                cache=cache,
                state_mgr=state_mgr,
                existing_playlists=existing,
                threshold=threshold,
                dry_run=dry_run,
                incremental=incremental,
                prefix=actual_prefix,
                retry_days=retry_days,
                retry=retry,
            )
        except RateLimitError as e:
            click.echo(f"\n{e}", err=True)
            if cache is not None:
                cache.save()
                click.echo(f"Cache saved to {cache_path} ({len(cache.entries)} entries).", err=True)
            print_report(report)
            if report_path:
                save_report(report, report_path)
            sys.exit(1)

        report.playlists.append(pl_report)

    # Save cache (even in dry-run — API lookups are still worth caching)
    if cache is not None:
        cache.save()

    # Save playlist state (skip in dry-run)
    if not dry_run:
        state_mgr.save()

    print_report(report)

    if report_path:
        save_report(report, report_path)
        click.echo(f"\nDetailed report saved to {report_path}")


@cli.command("list")
@click.argument("xml_path", required=False, type=click.Path(exists=True, dir_okay=False))
def list_playlists(xml_path: str | None):
    """List all playlists in a Rekordbox XML export."""
    xml_path = _resolve_xml_path(xml_path)
    _, playlists = parse_xml(xml_path)
    for pl in playlists:
        click.echo(f"  {pl.path} ({len(pl.track_ids)} tracks)")


DEFAULT_BEATPORT_CACHE_PATH = ".djsupport_beatport_cache.json"
DEFAULT_BEATPORT_STATE_PATH = ".djsupport_beatport_playlists.json"


@cli.command()
@click.argument("url")
@click.option("--dry-run", is_flag=True, help="Preview without modifying Spotify.")
@click.option("--threshold", "-t", default=80, show_default=True, help="Minimum match confidence (0-100).")
@click.option("--no-cache", is_flag=True, help="Bypass match cache.")
@click.option("--retry", is_flag=True, help="Force retry all previously failed matches.")
@click.option("--retry-days", default=7, show_default=True, help="Auto-retry failures older than N days.")
@click.option("--cache-path", default=DEFAULT_BEATPORT_CACHE_PATH, show_default=True, help="Path to Beatport match cache.")
@click.option("--state-path", default=DEFAULT_BEATPORT_STATE_PATH, show_default=True, help="Path to Beatport playlist state.")
@click.option("--report", "report_path", type=click.Path(), default=None, help="Save Markdown report.")
@click.option("--prefix", default="djsupport", show_default=True, help="Prefix for Spotify playlist name.")
@click.option("--no-prefix", is_flag=True, help="Disable playlist name prefix.")
@click.option("--incremental/--no-incremental", default=True, show_default=True, help="Use incremental playlist updates.")
def beatport(
    url: str,
    dry_run: bool,
    threshold: int,
    no_cache: bool,
    retry: bool,
    retry_days: int,
    cache_path: str,
    state_path: str,
    report_path: str | None,
    prefix: str,
    no_prefix: bool,
    incremental: bool,
) -> None:
    """Create a Spotify playlist from a Beatport DJ chart.

    URL is a Beatport chart page, e.g.:
    https://www.beatport.com/chart/garage-go-tos/815070
    """
    import requests

    from djsupport.beatport import BeatportParseError, InvalidBeatportURL, fetch_chart, validate_url

    try:
        url = validate_url(url)
    except InvalidBeatportURL as e:
        raise click.ClickException(str(e))

    click.echo("Fetching chart from Beatport...")
    try:
        chart_name, curator, tracks = fetch_chart(url)
    except BeatportParseError as e:
        raise click.ClickException(str(e))
    except requests.RequestException as e:
        if hasattr(e, "response") and e.response is not None and e.response.status_code == 404:
            raise click.ClickException("Chart not found — check the URL.")
        raise click.ClickException(f"Failed to fetch chart: {e}")

    if not tracks:
        click.echo(f"Chart '{chart_name}' has no tracks.")
        return

    click.echo(f"Chart: {chart_name} by {curator}. {len(tracks)} tracks.")

    # Initialize cache (separate from Rekordbox)
    cache = None
    if not no_cache:
        from djsupport.cache import MatchCache
        cache = MatchCache(cache_path)
        cache.load()
        if cache.entries:
            click.echo(f"Loaded {len(cache.entries)} cached Beatport matches from {cache_path}")

    # Resolve prefix
    actual_prefix = None if no_prefix else prefix

    # Initialize Beatport-specific playlist state
    from djsupport.state import PlaylistStateManager
    state_mgr = PlaylistStateManager(state_path)
    state_mgr.load()

    # Spotify client
    sp = get_client()
    existing = get_user_playlists(sp) if not dry_run else None

    # Match and sync via shared helper
    report = SyncReport(
        timestamp=datetime.now(),
        threshold=threshold,
        dry_run=dry_run,
        cache_enabled=cache is not None,
        source_label="Beatport",
    )

    try:
        pl_report = _match_and_sync_playlist(
            tracks,
            chart_name,
            url,
            sp=sp,
            cache=cache,
            state_mgr=state_mgr,
            existing_playlists=existing,
            threshold=threshold,
            dry_run=dry_run,
            incremental=incremental,
            prefix=actual_prefix,
            retry_days=retry_days,
            retry=retry,
            source_type="beatport",
        )
    except RateLimitError as e:
        click.echo(f"\n{e}", err=True)
        if cache is not None:
            cache.save()
            click.echo(f"Cache saved to {cache_path} ({len(cache.entries)} entries).", err=True)
        print_report(report)
        if report_path:
            save_report(report, report_path)
        sys.exit(1)

    report.playlists.append(pl_report)

    # Save cache
    if cache is not None:
        cache.save()

    # Save state
    if not dry_run:
        state_mgr.save()

    print_report(report)
    if report_path:
        save_report(report, report_path)
        click.echo(f"\nDetailed report saved to {report_path}")


DEFAULT_LABEL_CACHE_PATH = ".djsupport_label_cache.json"
DEFAULT_LABEL_STATE_PATH = ".djsupport_label_playlists.json"


@cli.command()
@click.argument("url_or_name")
@click.option("--dry-run", is_flag=True, help="Preview without modifying Spotify.")
@click.option("--threshold", "-t", default=80, show_default=True, help="Minimum match confidence (0-100).")
@click.option("--no-cache", is_flag=True, help="Bypass match cache.")
@click.option("--retry", is_flag=True, help="Force retry all previously failed matches.")
@click.option("--retry-days", default=7, show_default=True, help="Auto-retry failures older than N days.")
@click.option("--cache-path", default=DEFAULT_LABEL_CACHE_PATH, show_default=True, help="Path to label match cache.")
@click.option("--state-path", default=DEFAULT_LABEL_STATE_PATH, show_default=True, help="Path to label playlist state.")
@click.option("--report", "report_path", type=click.Path(), default=None, help="Save Markdown report.")
@click.option("--prefix", default="djsupport", show_default=True, help="Prefix for Spotify playlist name.")
@click.option("--no-prefix", is_flag=True, help="Disable playlist name prefix.")
@click.option("--incremental/--no-incremental", default=True, show_default=True, help="Use incremental playlist updates.")
def label(
    url_or_name: str,
    dry_run: bool,
    threshold: int,
    no_cache: bool,
    retry: bool,
    retry_days: int,
    cache_path: str,
    state_path: str,
    report_path: str | None,
    prefix: str,
    no_prefix: bool,
    incremental: bool,
) -> None:
    """Create a Spotify playlist from a Beatport record label.

    URL_OR_NAME is either a Beatport label URL or a label name to search for.

    \b
    Examples:
      djsupport label https://www.beatport.com/label/drumcode/1
      djsupport label "Drumcode"
    """
    import requests

    from djsupport.label import (
        InvalidLabelURL,
        LabelParseError,
        deduplicate_tracks,
        fetch_label_tracks,
        search_labels,
        validate_label_url,
        LARGE_LABEL_THRESHOLD,
    )

    # Detect URL vs name
    if "beatport.com/label/" in url_or_name:
        try:
            label_url = validate_label_url(url_or_name)
        except InvalidLabelURL as e:
            raise click.ClickException(str(e))
    else:
        # Search by name
        click.echo(f"Searching Beatport for label '{url_or_name}'...")
        try:
            results = search_labels(url_or_name)
        except LabelParseError as e:
            raise click.ClickException(str(e))
        except requests.RequestException as e:
            raise click.ClickException(f"Failed to search Beatport: {e}")

        if not results:
            click.echo(f"No labels found matching '{url_or_name}'.")
            return

        click.echo(f"\nFound {len(results)} label(s):\n")
        for i, r in enumerate(results, 1):
            latest = f' — latest: "{r.latest_release}"' if r.latest_release else ""
            date = f" ({r.latest_release_date})" if r.latest_release_date else ""
            click.echo(f"  {i}. {r.name}{latest}{date}")
            click.echo(f"     {r.url}")

        if len(results) == 1:
            label_url = results[0].url
            click.echo(f"\nUsing: {results[0].name}")
        else:
            selection = click.prompt("\nSelect label", type=int, default=1)
            if selection < 1 or selection > len(results):
                raise click.ClickException(f"Invalid selection: {selection}")
            label_url = results[selection - 1].url
            click.echo(f"\nUsing: {results[selection - 1].name}")

        # Re-validate URL constructed from search results
        try:
            label_url = validate_label_url(label_url)
        except InvalidLabelURL as e:
            raise click.ClickException(str(e))

    # Fetch tracks with pagination
    click.echo("Fetching tracks from Beatport label...")

    def on_total(total: int) -> bool | None:
        click.echo(f"Label has {total} tracks.")
        if total > LARGE_LABEL_THRESHOLD:
            if not click.confirm(
                f"This label has {total} tracks (>{LARGE_LABEL_THRESHOLD}). Continue?"
            ):
                return False
        return None

    def on_page(page: int, total_pages: int) -> None:
        click.echo(f"  Fetched page {page}/{total_pages}")

    def on_page_error(page: int, total_pages: int, error: Exception) -> None:
        click.echo(
            f"\nWarning: Failed to fetch page {page}/{total_pages}: {error}",
            err=True,
        )

    try:
        label_name, tracks = fetch_label_tracks(
            label_url, on_total=on_total, on_page=on_page,
            on_page_error=on_page_error,
        )
    except LabelParseError as e:
        raise click.ClickException(str(e))
    except requests.RequestException as e:
        if hasattr(e, "response") and e.response is not None and e.response.status_code == 404:
            raise click.ClickException("Label not found — check the URL.")
        raise click.ClickException(f"Failed to fetch label: {e}")

    if not tracks:
        click.echo(f"No tracks found for label '{label_name}'.")
        return

    # Deduplicate tracks across compilations
    tracks, dupes_removed = deduplicate_tracks(tracks)
    if dupes_removed:
        click.echo(f"Removed {dupes_removed} duplicate tracks. {len(tracks)} unique tracks remaining.")
    else:
        click.echo(f"{len(tracks)} tracks (newest first).")

    # Initialize cache
    cache = None
    if not no_cache:
        from djsupport.cache import MatchCache
        cache = MatchCache(cache_path)
        cache.load()
        if cache.entries:
            click.echo(f"Loaded {len(cache.entries)} cached label matches from {cache_path}")

    actual_prefix = None if no_prefix else prefix

    from djsupport.state import PlaylistStateManager
    state_mgr = PlaylistStateManager(state_path)
    state_mgr.load()

    sp = get_client()
    existing = get_user_playlists(sp) if not dry_run else None

    report = SyncReport(
        timestamp=datetime.now(),
        threshold=threshold,
        dry_run=dry_run,
        cache_enabled=cache is not None,
        source_label="Beatport",
    )

    try:
        pl_report = _match_and_sync_playlist(
            tracks,
            label_name,
            label_url,
            sp=sp,
            cache=cache,
            state_mgr=state_mgr,
            existing_playlists=existing,
            threshold=threshold,
            dry_run=dry_run,
            incremental=incremental,
            prefix=actual_prefix,
            retry_days=retry_days,
            retry=retry,
            source_type="label",
        )
    except RateLimitError as e:
        click.echo(f"\n{e}", err=True)
        if cache is not None:
            cache.save()
            click.echo(f"Cache saved to {cache_path} ({len(cache.entries)} entries).", err=True)
        print_report(report)
        if report_path:
            save_report(report, report_path)
        sys.exit(1)

    report.playlists.append(pl_report)

    if cache is not None:
        cache.save()

    if not dry_run:
        state_mgr.save()

    print_report(report)
    if report_path:
        save_report(report, report_path)
        click.echo(f"\nDetailed report saved to {report_path}")
