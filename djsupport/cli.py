"""CLI entry point for djsupport."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import click

from dotenv import load_dotenv

from djsupport.config import ConfigManager, validate_rekordbox_xml
from djsupport.rekordbox import parse_xml
from djsupport.report import (
    print_report,
    save_report,
    save_review_csv,
)
from djsupport.spotify import RateLimitError, get_client
from djsupport.transfer import (
    AccountPublishingGuards,
    default_matching_knowledge_path,
    default_publication_manifest_path,
)


DEFAULT_MATCHING_KNOWLEDGE_PATH = str(default_matching_knowledge_path())
DEFAULT_PUBLICATION_MANIFEST_PATH = str(default_publication_manifest_path())


@click.group()
def cli():
    """DJ Support - Transfer DJ selections to Spotify."""
    load_dotenv()


@cli.command("capabilities")
@click.option("--json", "as_json", is_flag=True, help="Emit the agent contract.")
def capabilities(as_json: bool) -> None:
    """Inspect optional capabilities without reading a library or Spotify."""
    from djsupport.agent import capability_document
    from djsupport.local_audio import ChromaprintLocalAudio

    document = capability_document(ChromaprintLocalAudio().capability())
    if as_json:
        click.echo(json.dumps(document, sort_keys=True))
        return
    local_audio = document["capabilities"]["local_audio_identity"]
    if local_audio["available"]:
        click.echo(
            "Local audio identity available "
            f"({local_audio['algorithm']} {local_audio['algorithm_version']})."
        )
    else:
        click.echo("Local audio identity unavailable; install fpcalc to enable it.")


def _resolve_xml_path(explicit_xml_path: str | None) -> str:
    """Resolve Rekordbox XML path from explicit arg or saved local config."""
    if explicit_xml_path:
        explicit = Path(explicit_xml_path).expanduser()
        if not explicit.exists() or not explicit.is_file():
            raise click.ClickException("Rekordbox XML path is missing or invalid.")
        return str(explicit)

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


@cli.command("backup")
@click.option(
    "--destination", type=click.Path(file_okay=False), default=None,
    help="Directory for the timestamped archive (defaults to local app data/backups).",
)
def backup_local_data(destination: str | None) -> None:
    """Create one versioned archive of local djsupport data."""
    from djsupport.backup import LocalDataBackup, default_app_data_path

    app_data = default_app_data_path()
    archive = LocalDataBackup(app_data).create(
        Path(destination) if destination else app_data / "backups"
    )
    click.echo(f"Backup created: {archive}")


@cli.command("restore")
@click.argument("archive", type=click.Path(exists=True, dir_okay=False))
@click.option("--apply", is_flag=True, help="Apply the validated restore preview.")
@click.option(
    "--resolve", "resolution_values", multiple=True, metavar="CONFLICT=CHOICE",
    help="Resolve a listed conflict with current or archive.",
)
def restore_local_data(
    archive: str, apply: bool, resolution_values: tuple[str, ...],
) -> None:
    """Validate and preview a backup; use --apply to restore it."""
    from djsupport.backup import LocalDataBackup, default_app_data_path

    service = LocalDataBackup(default_app_data_path())
    preview = service.preview(archive)
    if not preview.valid:
        raise click.ClickException("; ".join(preview.errors))
    click.echo("Archive contents:")
    for path in preview.contents:
        click.echo(f"  {path}")
    click.echo("Proposed changes:")
    for change in preview.changes:
        click.echo(f"  {change}")
    for conflict in preview.conflicts:
        click.echo(
            f"Conflict {conflict.conflict_id} ({conflict.kind}); "
            "choose current or archive"
        )
    if not apply:
        click.echo("Preview only; current data was not changed.")
        return
    try:
        resolutions = dict(value.split("=", 1) for value in resolution_values)
    except ValueError as exc:
        raise click.UsageError(
            "Each --resolve value must be CONFLICT=CHOICE."
        ) from exc
    result = service.restore(archive, resolutions=resolutions)
    if not result.restored:
        if result.errors:
            raise click.ClickException("; ".join(result.errors))
        raise click.ClickException(
            "Unresolved conflicts; current data was not changed."
        )
    click.echo("Restore completed.")


@cli.command("migrate-0-3")
@click.argument(
    "legacy_directory", type=click.Path(),
)
@click.option("--apply", is_flag=True, help="Apply the validated migration preview.")
def migrate_0_3(legacy_directory: str, apply: bool) -> None:
    """Preview migration of one explicitly selected 0.3.0 data directory."""
    from djsupport.backup import default_app_data_path
    from djsupport.migration import LegacyMigration

    report = LegacyMigration(default_app_data_path()).preview(legacy_directory)
    if not report.valid:
        raise click.ClickException("; ".join(report.errors))
    click.echo(f"Detected files: {report.detected_files}")
    click.echo(f"Cache records: {report.cache_records}")
    click.echo(f"Proposed cache imports: {report.proposed_cache_imports}")
    click.echo(f"Conflicts: {report.conflicts}")
    click.echo(f"Skipped: {report.skipped}")
    click.echo(f"Relink required: {report.relink_required}")
    click.echo(f"Historical Snapshots: {report.historical_snapshots}")
    if not apply:
        click.echo("Preview only; current and legacy data were not changed.")
        return
    result = LegacyMigration(default_app_data_path()).apply(legacy_directory)
    if not result.applied:
        raise click.ClickException("; ".join(result.errors))
    click.echo("Migration completed; legacy files were left unchanged.")


@cli.command("migrate-0-5")
@click.option("--legacy-account-id", required=True)
@click.option("--account-id", required=True)
def migrate_0_5(legacy_account_id: str, account_id: str) -> None:
    """Back up and migrate retained state to stable Spotify account identity."""
    from djsupport.backup import default_app_data_path
    from djsupport.migration import FoundationMigration

    try:
        result = FoundationMigration(default_app_data_path()).apply(
            legacy_account_id, account_id,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if result.applied:
        click.echo(
            "Foundation migration completed after verified backup. "
            f"Updated records: {result.changed_records}"
        )
    else:
        click.echo("Foundation migration already applied; no changes made.")


@cli.command()
@click.argument("xml_path", required=False, type=click.Path())
@click.option(
    "--playlist", "-p", multiple=True,
    help="Select a playlist by exact name or path; repeat for a Batch.",
)
@click.option(
    "--whole-library", is_flag=True,
    help="Explicitly select every Rekordbox playlist as one Batch.",
)
@click.option("--dry-run", is_flag=True, help="Preview matches without creating playlists.")
@click.option("--threshold", "-t", default=80, show_default=True, help="Minimum match confidence (0-100).")
@click.option("--report", "report_path", type=click.Path(), default=None, help="Save detailed Markdown report to this path.")
@click.option("--no-cache", is_flag=True, help="Bypass retained matching knowledge (compatible flag).")
@click.option("--retry", is_flag=True, help="Force retry all previously failed matches.")
@click.option("--retry-days", default=7, show_default=True, help="Accepted for compatibility; unmatched tracks retry only with --retry.")
@click.option("--cache-path", default=DEFAULT_MATCHING_KNOWLEDGE_PATH, show_default=True, help="Path to matching knowledge (compatible flag).")
@click.option("--prefix", default="djsupport", show_default=True, help="Prefix for Spotify playlist names.")
@click.option("--no-prefix", is_flag=True, help="Disable playlist name prefix.")
@click.option("--state-path", default=DEFAULT_PUBLICATION_MANIFEST_PATH, show_default=True, help="Path to durable publication manifests (compatible flag).")
@click.option(
    "--local-audio-identity", is_flag=True,
    help="Opt into local audio identity for the selected Rekordbox Batch.",
)
@click.option(
    "--json", "agent_json", is_flag=True,
    help="Emit the versioned non-interactive agent contract.",
)
@click.option(
    "--authorize-private-source", is_flag=True,
    help="Explicitly authorize reading the selected XML and local audio.",
)
@click.option(
    "--authorize-spotify-write", is_flag=True,
    help="Explicitly authorize Spotify mutation for this Batch.",
)
@click.option(
    "--confirm-expensive", is_flag=True,
    help="Explicitly confirm whole-library or expensive work.",
)
def sync(
    xml_path: str | None,
    playlist: tuple[str, ...],
    whole_library: bool,
    dry_run: bool,
    threshold: int,
    report_path: str | None,
    no_cache: bool,
    retry: bool,
    retry_days: int,
    cache_path: str,
    prefix: str,
    no_prefix: bool,
    state_path: str,
    local_audio_identity: bool,
    agent_json: bool,
    authorize_private_source: bool,
    authorize_spotify_write: bool,
    confirm_expensive: bool,
):
    """Transfer explicitly selected Rekordbox playlists to Spotify.

    XML_PATH is the path to your Rekordbox XML library export (optional if configured via `library set`).
    """
    if not playlist and not whole_library:
        raise click.UsageError(
            "Select at least one playlist with --playlist or opt into "
            "--whole-library."
        )
    if playlist and whole_library:
        raise click.UsageError(
            "Use explicit --playlist selections or --whole-library, not both."
        )

    from djsupport.cache import MatchCache
    from djsupport.transfer import (
        BatchPlanRequest,
        EphemeralMatchingKnowledge,
        FilePublicationStorage,
        FileTransferStorage,
        MatchCacheKnowledge,
        RekordboxPlaylistSource,
        SpotifyMatcher,
        Transfer,
        TransferAuthorization,
    )
    from djsupport.local_audio import ChromaprintLocalAudio

    request = BatchPlanRequest(
        playlist_references=playlist,
        whole_library=whole_library,
        threshold=threshold,
        preview=dry_run,
        retry=retry,
        retry_days=retry_days,
        playlist_prefix=None if no_prefix else prefix,
        confirm_expensive=confirm_expensive,
        local_audio_identity=local_audio_identity,
    )
    authorization = TransferAuthorization(
        private_source=authorize_private_source,
        spotify_write=authorize_spotify_write,
    )
    if agent_json:
        from djsupport.agent import authorization_required_document

        required = Transfer.authorization_requirement(
            request, authorization, phase="plan",
        )
        if required:
            click.echo(json.dumps(
                authorization_required_document("plan", required), sort_keys=True,
            ))
            raise click.exceptions.Exit(2)
    if local_audio_identity and no_cache:
        if agent_json:
            from djsupport.agent import error_document

            click.echo(json.dumps(
                error_document("plan", "durable_knowledge_required"), sort_keys=True,
            ))
            raise click.exceptions.Exit(2)
        raise click.UsageError(
            "Local audio identity requires durable matching knowledge; "
            "remove --no-cache"
        )
    try:
        xml_path = _resolve_xml_path(xml_path)
    except (click.ClickException, OSError, ValueError) as exc:
        if not agent_json:
            raise
        from djsupport.agent import error_document

        click.echo(json.dumps(
            error_document("plan", "private_source_unavailable"), sort_keys=True,
        ))
        raise click.exceptions.Exit(2) from exc

    cache = None if no_cache else MatchCache(cache_path)
    try:
        if cache is not None:
            cache.load()
    except (OSError, ValueError) as exc:
        if not agent_json:
            raise click.ClickException(str(exc)) from exc
        from djsupport.agent import error_document

        click.echo(json.dumps(
            error_document("plan", "matching_knowledge_unavailable"), sort_keys=True,
        ))
        raise click.exceptions.Exit(2) from exc
    execute_authorized = Transfer.authorization_requirement(
        request, authorization, phase="execute",
    ) is None
    transfer = Transfer(
        source=RekordboxPlaylistSource(
            xml_path, include_locations=local_audio_identity,
        ),
        spotify=(
            SpotifyMatcher(get_client())
            if execute_authorized else object()
        ),
        publishing_guards=AccountPublishingGuards(),
        matching_knowledge=(
            EphemeralMatchingKnowledge() if cache is None
            else MatchCacheKnowledge(cache)
        ),
        publication_storage=(
            None if dry_run else FilePublicationStorage(state_path)
        ),
        transfer_storage=FileTransferStorage(
            str(Path(state_path).with_suffix(".transfers.json"))
        ),
        local_audio=(ChromaprintLocalAudio() if local_audio_identity else None),
    )
    if agent_json:
        from djsupport.agent import AgentTransferContract

        contract = AgentTransferContract(transfer)
        try:
            outcome = (
                contract.execute_batch(request, authorization)
                if execute_authorized
                else contract.plan_batch(request, authorization)
            )
        except Exception:
            from djsupport.agent import error_document

            outcome = error_document(
                "execute" if execute_authorized else "plan",
                "transfer_failed",
            )
        click.echo(json.dumps(outcome, sort_keys=True))
        if outcome["status"] in {
            "authorization_required", "confirmation_required", "error",
        } or outcome.get("required_authorizations"):
            raise click.exceptions.Exit(2)
        return
    plan = transfer.plan_batch(request)
    click.echo(
        f"Transfer plan: {plan.total_tracks} tracks; "
        f"{plan.approved_match_hits} Approved Match hits; "
        f"{plan.cache_hits} retained proposal hits; "
        f"{plan.expected_uncached_lookups} expected Spotify lookups."
    )
    if plan.local_audio_identity:
        click.echo(
            "Local audio: "
            f"{plan.local_audio_eligible} eligible; "
            f"{plan.local_audio_indexed} indexed; "
            f"{plan.local_audio_pending} calculations; "
            f"{plan.local_audio_unavailable} unavailable."
        )
    if plan.confirmation_required:
        if not click.confirm("This Batch may be expensive. Continue?"):
            raise click.Abort()
        plan = transfer.plan_batch(
            BatchPlanRequest(**{**request.__dict__, "confirm_expensive": True})
        )
    try:
        report = transfer.execute_batch(plan)
    except RateLimitError as exc:
        raise click.ClickException(str(exc)) from exc

    print_report(report)

    if report_path:
        save_report(report, report_path)
        review_path = str(Path(report_path).with_suffix(".csv"))
        save_review_csv(report, review_path)
        click.echo(f"\nDetailed report saved to {report_path}")
        click.echo(f"Editable review CSV saved to {review_path}")


@cli.command("list")
@click.argument("xml_path", required=False, type=click.Path(exists=True, dir_okay=False))
def list_playlists(xml_path: str | None):
    """List all playlists in a Rekordbox XML export."""
    xml_path = _resolve_xml_path(xml_path)
    _, playlists = parse_xml(xml_path)
    for pl in playlists:
        click.echo(f"  {pl.path} ({len(pl.track_ids)} tracks)")


DEFAULT_BEATPORT_CACHE_PATH = DEFAULT_MATCHING_KNOWLEDGE_PATH
DEFAULT_BEATPORT_STATE_PATH = DEFAULT_PUBLICATION_MANIFEST_PATH


@cli.command()
@click.argument("playlist_id")
@click.option(
    "--state-path", default=DEFAULT_BEATPORT_STATE_PATH, show_default=True,
    help="Path to durable Provisional Playlist manifests.",
)
@click.option(
    "--cache-path", default=DEFAULT_BEATPORT_CACHE_PATH, show_default=True,
    help="Path to durable matching knowledge.",
)
@click.option(
    "--review-csv", type=click.Path(exists=True, dir_okay=False),
    help="Edited review CSV containing explicit Corrections.",
)
def approve(
    playlist_id: str, state_path: str, cache_path: str, review_csv: str | None,
) -> None:
    """Approve one Provisional Playlist after reviewing it in Spotify."""
    from djsupport.cache import MatchCache
    from djsupport.transfer import (
        BeatportChartSource,
        FilePublicationStorage,
        MatchCacheKnowledge,
        SpotifyMatcher,
        Transfer,
    )

    cache = MatchCache(cache_path)
    cache.load()
    transfer = Transfer(
        source=BeatportChartSource(),
        spotify=SpotifyMatcher(get_client()),
        publishing_guards=AccountPublishingGuards(),
        matching_knowledge=MatchCacheKnowledge(cache),
        publication_storage=FilePublicationStorage(state_path),
    )
    try:
        if review_csv is None:
            review = transfer.approve(playlist_id)
        else:
            review = transfer.approve(playlist_id, corrections=review_csv)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if review.status.value == "abandoned":
        click.echo(
            f"Provisional Playlist {playlist_id} is Abandoned; publication history retained."
        )
        return
    click.echo(
        f"Provisional Playlist {playlist_id}: "
        f"{len(review.approved)} approved, {len(review.rejected)} rejected, "
        f"{len(review.collisions)} collisions, "
        f"{len(review.corrections)} Corrections."
    )


@cli.command()
@click.argument("url")
@click.option("--dry-run", is_flag=True, help="Preview without modifying Spotify.")
@click.option("--threshold", "-t", default=80, show_default=True, help="Minimum match confidence (0-100).")
@click.option("--no-cache", is_flag=True, help="Bypass match cache.")
@click.option("--retry", is_flag=True, help="Force retry all previously failed matches.")
@click.option("--retry-days", default=7, show_default=True, help="Accepted for compatibility; unmatched tracks retry only with --retry.")
@click.option("--cache-path", default=DEFAULT_BEATPORT_CACHE_PATH, show_default=True, help="Path to Beatport match cache.")
@click.option(
    "--state-path", default=DEFAULT_BEATPORT_STATE_PATH, show_default=True,
    help="Path to durable Beatport publication manifests.",
)
@click.option("--report", "report_path", type=click.Path(), default=None, help="Save Markdown report.")
@click.option("--prefix", default="djsupport", show_default=True, help="Prefix for Spotify playlist name.")
@click.option("--no-prefix", is_flag=True, help="Disable playlist name prefix.")
@click.option("--incremental/--no-incremental", default=True, show_default=True, help="Use incremental playlist updates.")
@click.option("--mirror", is_flag=True, help="Maintain one recurring Beatport Mirror instead of distinct Snapshots.")
@click.option("--resume", "resume_id", default=None, help="Resume a durable Transfer ID.")
@click.option("--abandon", "abandon_id", default=None, help="Explicitly abandon a durable Transfer ID.")
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
    mirror: bool,
    resume_id: str | None,
    abandon_id: str | None,
) -> None:
    """Create a Spotify playlist from a Beatport DJ chart.

    URL is a Beatport chart page, e.g.:
    https://www.beatport.com/chart/garage-go-tos/815070
    """
    import requests

    from djsupport.beatport import (
        BeatportParseError,
        InvalidBeatportURL,
    )

    from djsupport.cache import MatchCache
    from djsupport.transfer import (
        BeatportChartSource,
        EphemeralMatchingKnowledge,
        FilePublicationStorage,
        FileTransferStorage,
        MatchCacheKnowledge,
        SpotifyMatcher,
        Transfer,
        TransferMode,
        TransferRequest,
    )

    cache = None if no_cache else MatchCache(cache_path)
    if cache is not None:
        cache.load()
    if resume_id and abandon_id:
        raise click.UsageError("Use either --resume or --abandon, not both.")
    transfer_storage = FileTransferStorage(
        str(Path(state_path).with_suffix(".transfers.json"))
    )
    transfer = Transfer(
        source=BeatportChartSource(),
        spotify=SpotifyMatcher(get_client()),
        publishing_guards=AccountPublishingGuards(),
        matching_knowledge=(
            EphemeralMatchingKnowledge()
            if cache is None else MatchCacheKnowledge(cache)
        ),
        publication_storage=(
            None if dry_run else FilePublicationStorage(state_path)
        ),
        transfer_storage=transfer_storage,
    )
    if abandon_id:
        transfer.abandon(abandon_id)
        click.echo(f"Transfer {abandon_id} abandoned.")
        return
    if resume_id and transfer_storage.load_transfer(resume_id) is None:
        raise click.ClickException(f"Unknown Transfer: {resume_id}")
    transfer_id = resume_id or uuid4().hex
    click.echo(f"Transfer ID: {transfer_id}")
    try:
        report = transfer.execute(TransferRequest(
            source=url,
            mode=TransferMode.MIRROR if mirror else TransferMode.SNAPSHOT,
            preview=dry_run,
            threshold=threshold,
            retry=retry,
            retry_days=retry_days,
            playlist_prefix=None if no_prefix else prefix,
            transfer_id=transfer_id,
            retain_matching_knowledge=not no_cache,
        ))
    except InvalidBeatportURL as e:
        raise click.ClickException(str(e))
    except BeatportParseError as e:
        raise click.ClickException(str(e))
    except requests.RequestException as e:
        if (
            hasattr(e, "response")
            and e.response is not None
            and e.response.status_code == 404
        ):
            raise click.ClickException("Chart not found — check the URL.")
        raise click.ClickException(f"Failed to fetch chart: {e}")
    except RateLimitError as e:
        raise click.ClickException(str(e))

    print_report(report)
    if report_path:
        save_report(report, report_path)
        review_path = str(Path(report_path).with_suffix(".csv"))
        save_review_csv(report, review_path)
        click.echo(f"\nDetailed report saved to {report_path}")
        click.echo(f"Editable review CSV saved to {review_path}")


# Charts and labels share user-local authoritative knowledge and publication
# manifests; callers can still override either path explicitly.
DEFAULT_LABEL_CACHE_PATH = DEFAULT_BEATPORT_CACHE_PATH
DEFAULT_LABEL_STATE_PATH = DEFAULT_BEATPORT_STATE_PATH


@cli.command()
@click.argument("url_or_name")
@click.option("--dry-run", is_flag=True, help="Preview without modifying Spotify.")
@click.option("--threshold", "-t", default=80, show_default=True, help="Minimum match confidence (0-100).")
@click.option("--no-cache", is_flag=True, help="Bypass match cache.")
@click.option("--retry", is_flag=True, help="Force retry all previously failed matches.")
@click.option("--retry-days", default=7, show_default=True, help="Accepted for compatibility; unmatched tracks retry only with --retry.")
@click.option("--cache-path", default=DEFAULT_LABEL_CACHE_PATH, show_default=True, help="Path to label match cache.")
@click.option("--state-path", default=DEFAULT_LABEL_STATE_PATH, show_default=True, help="Path to label playlist state.")
@click.option("--report", "report_path", type=click.Path(), default=None, help="Save Markdown report.")
@click.option("--prefix", default="djsupport", show_default=True, help="Prefix for Spotify playlist name.")
@click.option("--no-prefix", is_flag=True, help="Disable playlist name prefix.")
@click.option("--incremental/--no-incremental", default=True, show_default=True, help="Use incremental playlist updates.")
@click.option("--mirror", is_flag=True, help="Maintain one recurring Beatport Mirror instead of distinct Snapshots.")
@click.option("--resume", "resume_id", default=None, help="Resume a durable Transfer ID.")
@click.option("--abandon", "abandon_id", default=None, help="Explicitly abandon a durable Transfer ID.")
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
    mirror: bool,
    resume_id: str | None,
    abandon_id: str | None,
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

    def fetcher(url: str):
        click.echo("Fetching tracks from Beatport label...")
        return fetch_label_tracks(
            url, on_total=on_total, on_page=on_page, on_page_error=on_page_error,
        )

    def on_deduplicated(duplicates_removed: int, unique_count: int) -> None:
        if duplicates_removed:
            click.echo(
                f"Removed {duplicates_removed} duplicate tracks. "
                f"{unique_count} unique tracks remaining."
            )
        else:
            click.echo(f"{unique_count} tracks (newest first).")

    from djsupport.cache import MatchCache
    from djsupport.transfer import (
        BeatportLabelSource,
        EphemeralMatchingKnowledge,
        FilePublicationStorage,
        FileTransferStorage,
        MatchCacheKnowledge,
        SpotifyMatcher,
        Transfer,
        TransferMode,
        TransferRequest,
    )

    cache = None if no_cache else MatchCache(cache_path)
    if cache is not None:
        cache.load()
    if resume_id and abandon_id:
        raise click.UsageError("Use either --resume or --abandon, not both.")
    transfer_storage = FileTransferStorage(
        str(Path(state_path).with_suffix(".transfers.json"))
    )
    transfer = Transfer(
        source=BeatportLabelSource(
            fetcher=fetcher, on_deduplicated=on_deduplicated,
        ),
        spotify=SpotifyMatcher(get_client()),
        publishing_guards=AccountPublishingGuards(),
        matching_knowledge=(
            EphemeralMatchingKnowledge()
            if cache is None else MatchCacheKnowledge(cache)
        ),
        publication_storage=None if dry_run else FilePublicationStorage(state_path),
        transfer_storage=transfer_storage,
    )
    if abandon_id:
        transfer.abandon(abandon_id)
        click.echo(f"Transfer {abandon_id} abandoned.")
        return
    if resume_id and transfer_storage.load_transfer(resume_id) is None:
        raise click.ClickException(f"Unknown Transfer: {resume_id}")
    transfer_id = resume_id or uuid4().hex
    click.echo(f"Transfer ID: {transfer_id}")
    try:
        report = transfer.execute(TransferRequest(
            source=label_url,
            mode=TransferMode.MIRROR if mirror else TransferMode.SNAPSHOT,
            preview=dry_run,
            threshold=threshold,
            retry=retry,
            retry_days=retry_days,
            playlist_prefix=None if no_prefix else prefix,
            transfer_id=transfer_id,
            retain_matching_knowledge=not no_cache,
        ))
    except (InvalidLabelURL, LabelParseError) as e:
        raise click.ClickException(str(e))
    except requests.RequestException as e:
        if (
            hasattr(e, "response")
            and e.response is not None
            and e.response.status_code == 404
        ):
            raise click.ClickException("Label not found — check the URL.")
        raise click.ClickException(f"Failed to fetch label: {e}")
    except RateLimitError as e:
        raise click.ClickException(str(e))

    print_report(report)
    if report_path:
        save_report(report, report_path)
        review_path = str(Path(report_path).with_suffix(".csv"))
        save_review_csv(report, review_path)
        click.echo(f"\nDetailed report saved to {report_path}")
        click.echo(f"Editable review CSV saved to {review_path}")


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind to.")
@click.option("--port", default=8000, show_default=True, help="Port to bind to.")
def web(host: str, port: int):
    """Start the djsupport web UI."""
    try:
        import uvicorn
    except ImportError:
        click.echo(
            "Web UI requires extra dependencies. Install with:\n"
            "  pip install djsupport[web]"
        )
        raise SystemExit(1)

    click.echo(f"Starting djsupport web UI at http://{host}:{port}")
    uvicorn.run("djsupport.web:app", host=host, port=port)
