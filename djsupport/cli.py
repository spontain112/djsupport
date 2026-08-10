"""CLI entry point for djsupport."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import click
from spotipy.exceptions import SpotifyOauthError

from dotenv import load_dotenv

from djsupport.agent import FirstTransferAction
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
    from djsupport.local_audition import LocalSourceAudition

    document = capability_document(
        ChromaprintLocalAudio().capability(), LocalSourceAudition().capability(),
    )
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
    click.echo("Local audition available for explicitly authorized Rekordbox audio.")


def _first_transfer_readiness(
    explicit_xml_path: str | None,
) -> tuple[bool, bool, bool, bool, str | None]:
    """Inspect only local setup state; never call Spotify or parse the XML."""
    from djsupport.readiness import inspect_first_transfer_readiness

    readiness = inspect_first_transfer_readiness(explicit_xml_path)
    return (
        readiness.spotify_configured,
        readiness.spotify_authenticated,
        readiness.rekordbox_configured,
        readiness.rekordbox_available,
        readiness.xml_path,
    )


def _first_transfer_contract(
    *,
    xml_path: str | None,
    activate: bool,
    spotify_access: bool,
    local_audio_identity: bool | None,
    cache_path: str,
    state_path: str,
):
    """Build the public contract only as deeply as the current phase needs."""
    from djsupport.agent import AgentTransferContract
    from djsupport.cache import MatchCache
    from djsupport.local_audio import ChromaprintLocalAudio
    from djsupport.transfer import (
        EphemeralMatchingKnowledge,
        FilePublicationStorage,
        FileTransferStorage,
        MatchCacheKnowledge,
        RekordboxPlaylistSource,
        SpotifyMatcher,
        Transfer,
    )

    local_audio = ChromaprintLocalAudio()
    if not activate:
        return AgentTransferContract(Transfer(
            source=object(),
            spotify=object(),
            matching_knowledge=EphemeralMatchingKnowledge(),
            publishing_guards=AccountPublishingGuards(),
            local_audio=local_audio,
        ))

    if xml_path is None:
        raise ValueError("Rekordbox XML is unavailable")
    cache = MatchCache(cache_path)
    cache.load()
    publication_path = Path(state_path)
    return AgentTransferContract(Transfer(
        source=RekordboxPlaylistSource(
            xml_path, include_locations=bool(local_audio_identity),
        ),
        spotify=(SpotifyMatcher(get_client()) if spotify_access else object()),
        matching_knowledge=MatchCacheKnowledge(cache),
        publishing_guards=AccountPublishingGuards(),
        publication_storage=FilePublicationStorage(publication_path),
        transfer_storage=FileTransferStorage(
            publication_path.with_suffix(".transfers.json")
        ),
        local_audio=(local_audio if local_audio_identity else None),
    ))


@cli.command("first-transfer")
@click.option("--xml-path", type=click.Path(), default=None)
@click.option("--playlist", "playlist_reference", default=None)
@click.option(
    "--local-audio-identity/--no-local-audio-identity", default=None,
)
@click.option(
    "--action",
    type=click.Choice([action.value for action in FirstTransferAction]),
    default=None,
)
@click.option("--transfer-id", default=None)
@click.option("--draft-id", default=None)
@click.option("--authorize-private-source", is_flag=True)
@click.option("--authorize-spotify-write", is_flag=True)
@click.option("--cache-path", default=DEFAULT_MATCHING_KNOWLEDGE_PATH)
@click.option("--state-path", default=DEFAULT_PUBLICATION_MANIFEST_PATH)
@click.option("--json", "as_json", is_flag=True)
def first_transfer(
    xml_path: str | None,
    playlist_reference: str | None,
    local_audio_identity: bool | None,
    action: str | None,
    transfer_id: str | None,
    draft_id: str | None,
    authorize_private_source: bool,
    authorize_spotify_write: bool,
    cache_path: str,
    state_path: str,
    as_json: bool,
) -> None:
    """Return the next safe step for one first Rekordbox Transfer."""
    from djsupport.agent import FirstTransferGuideRequest
    from djsupport.transfer import TransferAuthorization

    readiness = _first_transfer_readiness(xml_path)
    (
        spotify_configured,
        spotify_authenticated,
        rekordbox_configured,
        rekordbox_available,
        selected_xml_path,
    ) = readiness
    if authorize_private_source:
        from djsupport.readiness import inspect_first_transfer_readiness

        authorized_readiness = inspect_first_transfer_readiness(
            selected_xml_path, authorize_private_source=True,
        )
        rekordbox_available = authorized_readiness.rekordbox_available
    activate = bool(
        spotify_configured
        and spotify_authenticated
        and rekordbox_configured
        and rekordbox_available
        and playlist_reference is not None
        and local_audio_identity is not None
        and authorize_private_source
    )
    action_kind = FirstTransferAction(action) if action is not None else None
    spotify_access = bool(
        action_kind is not None and action_kind.needs_spotify_access
    )
    try:
        contract = _first_transfer_contract(
            xml_path=selected_xml_path,
            activate=activate,
            spotify_access=spotify_access,
            local_audio_identity=local_audio_identity,
            cache_path=cache_path,
            state_path=state_path,
        )
        document = contract.first_rekordbox_transfer(
            FirstTransferGuideRequest(
                spotify_configured=spotify_configured,
                spotify_authenticated=spotify_authenticated,
                rekordbox_configured=rekordbox_configured,
                rekordbox_available=rekordbox_available,
                playlist_reference=playlist_reference,
                local_audio_identity=local_audio_identity,
                action=action_kind,
                transfer_id=transfer_id,
                draft_id=draft_id,
            ),
            TransferAuthorization(
                private_source=authorize_private_source,
                spotify_write=authorize_spotify_write,
            ),
        )
    except SpotifyOauthError:
        from djsupport.agent import error_document

        document = error_document(
            "first_rekordbox_transfer", "spotify_authentication_required",
        )
    except (OSError, PermissionError, ValueError):
        from djsupport.agent import error_document

        document = error_document(
            "first_rekordbox_transfer", "transfer_failed",
        )
    if as_json:
        click.echo(json.dumps(document, sort_keys=True))
        return
    click.echo(f"Next: {document.get('next_action') or 'complete'}")


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


@library.command("migrate-config")
@click.option(
    "--apply", is_flag=True,
    help="Copy valid legacy configuration into private application data.",
)
def library_migrate_config(apply: bool) -> None:
    """Preview or apply migration of the current-directory legacy config."""
    result = ConfigManager().migrate_legacy(apply=apply)
    if result.status == "not_found":
        click.echo("No legacy Rekordbox configuration found in this directory.")
    elif result.status == "invalid":
        raise click.ClickException(
            "Legacy Rekordbox configuration is invalid and was not migrated."
        )
    elif result.status == "conflict":
        raise click.ClickException(
            "Current and legacy Rekordbox configurations differ. "
            "Choose explicitly with `djsupport library set`."
        )
    elif result.status == "already_current":
        click.echo("Private Rekordbox configuration already matches the legacy file.")
    elif result.status == "migrated":
        click.echo(
            "Rekordbox configuration migrated to private application data. "
            "The legacy file was left unchanged."
        )
    else:
        click.echo(
            "Legacy Rekordbox configuration is ready to migrate. "
            "Run `djsupport library migrate-config --apply` to copy it."
        )


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
    "--local-audio-audition", is_flag=True,
    help="Opt into private local audition for the selected Rekordbox Batch.",
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
    local_audio_audition: bool,
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
    from djsupport.local_audition import LocalSourceAudition

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
        local_audio_audition=local_audio_audition,
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
    elif local_audio_audition and not authorization.private_source:
        raise click.UsageError(
            "Local audition requires --authorize-private-source."
        )
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
            xml_path,
            include_locations=(local_audio_identity or local_audio_audition),
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
        local_audition=(LocalSourceAudition() if local_audio_audition else None),
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
            "review_required",
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


@cli.command("qualification")
@click.argument("transfer_id", required=False)
@click.argument("xml_path_argument", required=False, type=click.Path())
@click.option("--xml-path", default=None, type=click.Path(), help="Explicit Rekordbox XML path for a draft-scoped operation.")
@click.option("--draft-id", default=None, help="Opaque Qualification Draft to resume.")
@click.option("--playlist", default=None, help="Exact selected Rekordbox playlist reference when obtaining a draft.")
@click.option("--include-all", is_flag=True, help="Include authoritative proposals for spot-checking.")
@click.option("--item-id", default=None, help="Opaque queue item to revise.")
@click.option(
    "--decision",
    type=click.Choice([
        "keep_proposal", "correction", "deferred", "reject_proposal",
    ]),
    default=None,
    help="Stage one non-authoritative draft outcome.",
)
@click.option("--spotify-reference", default=None, help="Explicit Spotify URL/URI for a Correction.")
@click.option("--reason", default=None, help="Optional private reason for a deferred item.")
@click.option("--exclude", is_flag=True, help="Explicitly exclude one deferred item from apply.")
@click.option("--apply", "apply_draft", is_flag=True, help="Apply a complete draft to its Provisional Playlist.")
@click.option("--approve", "approve_draft", is_flag=True, help="Separately Approve an applied draft's stable playlist.")
@click.option("--discard", "discard_draft", is_flag=True, help="Explicitly retire an unapplied draft without authority.")
@click.option("--supersede", "supersede_draft", is_flag=True, help="Start fresh from an explicitly discarded draft.")
@click.option("--link-transfer", default=None, help="Link a Preview draft to a distinct publishing Batch or Transfer.")
@click.option("--no-cache", is_flag=True, help="Bypass retained matching knowledge.")
@click.option("--cache-path", default=DEFAULT_MATCHING_KNOWLEDGE_PATH, show_default=True)
@click.option("--state-path", default=DEFAULT_PUBLICATION_MANIFEST_PATH, show_default=True)
@click.option("--authorize-private-source", is_flag=True, help="Authorize this bounded Rekordbox selection.")
@click.option("--authorize-spotify-write", is_flag=True, help="Authorize explicit draft application.")
@click.option("--review-origin", default="http://127.0.0.1:8000", show_default=True)
@click.option("--json", "agent_json", is_flag=True, help="Emit the privacy-redacted agent contract.")
def qualification_command(
    transfer_id: str | None,
    xml_path_argument: str | None,
    xml_path: str | None,
    draft_id: str | None,
    playlist: str | None,
    include_all: bool,
    item_id: str | None,
    decision: str | None,
    spotify_reference: str | None,
    reason: str | None,
    exclude: bool,
    apply_draft: bool,
    approve_draft: bool,
    discard_draft: bool,
    supersede_draft: bool,
    link_transfer: str | None,
    no_cache: bool,
    cache_path: str,
    state_path: str,
    authorize_private_source: bool,
    authorize_spotify_write: bool,
    review_origin: str,
    agent_json: bool,
) -> None:
    """Obtain or perform one explicit operation on a Qualification Draft."""
    from djsupport.agent import (
        AgentTransferContract,
        authorization_required_document,
        error_document,
    )
    from djsupport.cache import MatchCache
    from djsupport.local_audition import LocalSourceAudition
    from djsupport.transfer import (
        EphemeralMatchingKnowledge,
        FilePublicationStorage,
        FileTransferStorage,
        MatchCacheKnowledge,
        QualificationDecision,
        QualificationRequest,
        RekordboxPlaylistSource,
        SpotifyMatcher,
        Transfer,
        TransferAuthorization,
    )

    if not authorize_private_source:
        if agent_json:
            click.echo(json.dumps(
                authorization_required_document(
                    "qualification", "private_source",
                ),
                sort_keys=True,
            ))
            raise click.exceptions.Exit(2)
        raise click.UsageError(
            "Qualification requires --authorize-private-source."
        )
    if xml_path is not None and xml_path_argument is not None:
        raise click.UsageError("Use the XML positional argument or --xml-path, not both.")
    selected_xml_path = xml_path or xml_path_argument
    if (item_id is None) != (decision is None):
        raise click.UsageError("Use --item-id and --decision together.")
    operation_count = sum((
        bool(item_id), apply_draft, approve_draft, discard_draft,
        supersede_draft, link_transfer is not None,
    ))
    if operation_count > 1:
        raise click.UsageError(
            "Choose exactly one draft operation per invocation; Apply and "
            "Approval are always separate."
        )
    if draft_id is None:
        if operation_count:
            raise click.UsageError("Draft operations require --draft-id.")
        if transfer_id is None or playlist is None:
            raise click.UsageError(
                "Obtaining a draft requires TRANSFER_ID and --playlist."
            )
    elif transfer_id is not None or playlist is not None or include_all:
        raise click.UsageError(
            "Use --draft-id by itself for resumable draft-scoped operations."
        )
    try:
        selected_xml_path = _resolve_xml_path(selected_xml_path)
    except (click.ClickException, OSError, ValueError) as exc:
        if not agent_json:
            raise
        click.echo(json.dumps(
            error_document("qualification", "private_source_unavailable"),
            sort_keys=True,
        ))
        raise click.exceptions.Exit(2) from exc
    authorization = TransferAuthorization(
        private_source=True,
        spotify_write=authorize_spotify_write,
    )
    try:
        transfer_storage = FileTransferStorage(
            str(Path(state_path).with_suffix(".transfers.json"))
        )
        if draft_id is not None:
            stored_draft = transfer_storage.load_qualification(draft_id)
            stored_state = (
                transfer_storage.load_transfer(stored_draft.transfer_id)
                if stored_draft is not None else None
            )
            if stored_draft is None or stored_state is None:
                raise ValueError("Qualification Draft is unavailable")
            local_audio_audition = bool(
                stored_state.request.get("local_audio_audition", False)
            )
            no_cache = not bool(
                stored_state.request.get("retain_matching_knowledge", True)
            )
        else:
            assert transfer_id is not None and playlist is not None
            stored_batch = transfer_storage.load_batch(transfer_id)
            stored_transfer_id = transfer_id
            if stored_batch is not None:
                selected = [
                    item for item in stored_batch.playlists
                    if item.reference == playlist
                ]
                if len(selected) != 1:
                    raise ValueError("Qualification playlist is unavailable")
                stored_transfer_id = selected[0].transfer_id
            stored_state = transfer_storage.load_transfer(stored_transfer_id)
            if stored_state is None:
                raise ValueError("Qualification Transfer is unavailable")
            local_audio_audition = bool(
                stored_state.request.get("local_audio_audition", False)
            )
            no_cache = not bool(
                stored_state.request.get("retain_matching_knowledge", True)
            )
        cache = None if no_cache else MatchCache(cache_path)
        if cache is not None:
            cache.load()
        transfer = Transfer(
            source=RekordboxPlaylistSource(
                selected_xml_path, include_locations=local_audio_audition,
            ),
            spotify=SpotifyMatcher(get_client()),
            publishing_guards=AccountPublishingGuards(),
            matching_knowledge=(
                EphemeralMatchingKnowledge()
                if cache is None else MatchCacheKnowledge(cache)
            ),
            publication_storage=FilePublicationStorage(state_path),
            transfer_storage=transfer_storage,
            local_audition=(
                LocalSourceAudition() if local_audio_audition else None
            ),
        )
        contract = AgentTransferContract(transfer)
        if draft_id is None:
            assert transfer_id is not None and playlist is not None
            document = contract.qualification_draft(
                QualificationRequest(
                    transfer_id=transfer_id,
                    playlist_reference=playlist,
                    include_all=include_all,
                ),
                authorization,
                review_origin=review_origin,
            )
        elif item_id and decision:
            document = contract.record_qualification(
                draft_id,
                item_id,
                QualificationDecision(decision),
                authorization,
                spotify_reference=spotify_reference,
                reason=reason,
                exclude=exclude,
                review_origin=review_origin,
            )
        elif apply_draft:
            document = contract.apply_qualification(draft_id, authorization)
        elif approve_draft:
            document = contract.approve_qualification(draft_id, authorization)
        elif discard_draft:
            document = contract.discard_qualification(draft_id, authorization)
        elif supersede_draft:
            document = contract.supersede_qualification(
                draft_id, authorization, review_origin=review_origin,
            )
        elif link_transfer is not None:
            document = contract.link_qualification(
                draft_id, link_transfer, authorization,
                review_origin=review_origin,
            )
        else:
            document = contract.qualification_progress(
                draft_id, authorization, review_origin=review_origin,
            )
    except (OSError, PermissionError, ValueError) as exc:
        if agent_json:
            click.echo(json.dumps(
                error_document("qualification", "qualification_unavailable"),
                sort_keys=True,
            ))
            raise click.exceptions.Exit(2) from exc
        raise click.ClickException("Qualification operation is unavailable.") from exc
    if agent_json:
        click.echo(json.dumps(document, sort_keys=True))
        if document["status"] in {
            "authorization_required", "error", "review_required",
        }:
            raise click.exceptions.Exit(2)
        return
    if document["status"] in {"authorization_required", "error"}:
        raise click.ClickException("Qualification operation is unavailable.")
    if document["status"] == "review_required":
        handle = document.get("draft_id", "the selected draft")
        raise click.ClickException(
            f"Qualification review required for {handle}; use --discard "
            "before an explicit --supersede."
        )
    if document["phase"] == "qualification_approval":
        click.echo(
            f"Qualification Approval: {document['status']}; "
            f"{document['counts']['approved']} approved, "
            f"{document['counts']['rejected']} rejected."
        )
        return
    view = transfer.qualification(document["draft_id"], authorization)
    click.echo(
        f"Qualification Draft {view.draft_id}: {view.status.value}; "
        f"{len(view.items)} items, {view.pending} pending, "
        f"{view.deferred} deferred."
    )
    current = view.current_item
    if current is not None:
        click.echo(
            f"Current: {current.source_artist} — {current.source_title}; "
            f"proposal {current.spotify_artist} — {current.spotify_name}; "
            f"{current.match_type}; score {current.score:.0f}."
        )
    click.echo(f"Review locally: {review_origin.rstrip('/')}/qualification/{view.draft_id}")
    click.echo("Draft outcomes carry no authority; Approval remains separate.")


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
        FileTransferStorage,
        MatchCacheKnowledge,
        SpotifyPlaylistChanged,
        SpotifyPlaylistReviewRequired,
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
        transfer_storage=FileTransferStorage(
            str(Path(state_path).with_suffix(".transfers.json"))
        ),
    )
    try:
        if review_csv is None:
            review = transfer.approve(playlist_id)
        else:
            review = transfer.approve(playlist_id, corrections=review_csv)
    except (SpotifyPlaylistChanged, SpotifyPlaylistReviewRequired) as exc:
        raise click.ClickException(
            "Playlist review is required before Approval."
        ) from exc
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
@click.argument("url", required=False)
@click.option(
    "--export-file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Use an explicitly selected beatport.export/v2 JSON file.",
)
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
    url: str | None,
    export_file: Path | None,
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
    """Create a Spotify playlist from a Beatport selection.

    URL may be a Beatport chart page, e.g.:
    https://www.beatport.com/chart/garage-go-tos/815070

    Use --export-file for a local occurrence-safe Beatport CLI V2 export.
    """
    import requests

    from djsupport.beatport import (
        BeatportParseError,
        InvalidBeatportURL,
    )
    from djsupport.beatport_export import BeatportExportError

    from djsupport.cache import MatchCache
    from djsupport.transfer import (
        BeatportChartSource,
        BeatportExportSource,
        EphemeralMatchingKnowledge,
        FilePublicationStorage,
        FileTransferStorage,
        MatchCacheKnowledge,
        SpotifyMatcher,
        Transfer,
        TransferMode,
        TransferRequest,
    )

    if url and export_file is not None:
        raise click.UsageError("Use either URL or --export-file, not both.")
    if not url and export_file is None and not abandon_id:
        raise click.UsageError("Provide a Beatport URL or --export-file.")
    try:
        source = (
            BeatportExportSource(export_file)
            if export_file is not None else BeatportChartSource()
        )
    except BeatportExportError as exc:
        raise click.ClickException(str(exc)) from exc
    source_reference = (
        source.selection_reference
        if isinstance(source, BeatportExportSource) else (url or "")
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
        source=source,
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
            source=source_reference,
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
    except BeatportExportError as e:
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
