"""Thin FastAPI adapter for durable djsupport Transfers."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import threading
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request as FastAPIRequest
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from spotipy.oauth2 import SpotifyOAuth
from spotipy.exceptions import SpotifyOauthError

from djsupport.report import SyncReport
from djsupport.agent import FirstTransferAction
from djsupport.readiness import (
    FirstTransferReadiness,
    inspect_first_transfer_readiness,
)
from djsupport.spotify import SCOPES
from djsupport.local_audition import (
    AuditionHandleUnavailable,
    AuditionRangeNotSatisfiable,
    LocalSourceAudition,
)
from djsupport.transfer import (
    AccountPublishingGuards,
    BatchPlanRequest,
    BeatportChartSource,
    BeatportLabelSource,
    EphemeralMatchingKnowledge,
    FilePublicationStorage,
    FileTransferStorage,
    MatchCacheKnowledge,
    QualificationDecision,
    QualificationRequest,
    QualificationView,
    RekordboxPlaylistSource,
    SpotifyPlaylistChanged,
    SpotifyPlaylistReviewRequired,
    SpotifyMatcher,
    Transfer,
    TransferAuthorization,
    TransferMode,
    TransferRequest,
    default_matching_knowledge_path,
    default_publication_manifest_path,
)

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    from dotenv import load_dotenv
    load_dotenv()
    yield


class SyncRequest(BaseModel):
    url: str
    threshold: int = 80
    dry_run: bool = False
    prefix: str | None = "djsupport"
    retry: bool = False
    retry_days: int = 7
    no_cache: bool = False


class RekordboxBatchRequest(BaseModel):
    """Private, explicitly bounded Rekordbox request for the local web API."""

    xml_path: str
    playlists: list[str] = Field(default_factory=list)
    whole_library: bool = False
    threshold: int = 80
    preview: bool = False
    retry: bool = False
    retry_days: int = 7
    prefix: str | None = "djsupport"
    no_cache: bool = False
    local_audio_identity: bool = False
    local_audio_audition: bool = False
    confirm_expensive: bool = False
    authorize_private_source: bool = False
    authorize_spotify_write: bool = False


class FirstRekordboxTransferRequest(BaseModel):
    """Explicit facts for one harness-neutral first Transfer step."""

    xml_path: str | None = None
    playlist_reference: str | None = None
    local_audio_identity: bool | None = None
    action: FirstTransferAction | None = None
    transfer_id: str | None = None
    draft_id: str | None = None
    authorize_private_source: bool = False
    authorize_spotify_write: bool = False


class QualificationDraftRequest(BaseModel):
    """One explicit Rekordbox playlist selected for local qualification."""

    xml_path: str
    transfer_id: str
    playlist_reference: str | None = None
    include_all: bool = False
    no_cache: bool = False
    local_audio_identity: bool = False
    local_audio_audition: bool = False
    authorize_private_source: bool = False

    def transfer_request(self) -> RekordboxBatchRequest:
        return RekordboxBatchRequest(
            xml_path=self.xml_path,
            playlists=(
                [self.playlist_reference] if self.playlist_reference else []
            ),
            no_cache=self.no_cache,
            local_audio_identity=self.local_audio_identity,
            local_audio_audition=self.local_audio_audition,
            authorize_private_source=self.authorize_private_source,
        )


class QualificationDecisionRequest(BaseModel):
    item_id: str
    decision: QualificationDecision
    spotify_reference: str | None = None
    reason: str | None = None
    exclude: bool = False
    authorize_private_source: bool = False


class QualificationAuthorizationRequest(BaseModel):
    authorize_private_source: bool = False
    authorize_spotify_write: bool = False


class QualificationLinkRequest(BaseModel):
    publishing_transfer_id: str
    authorize_private_source: bool = False


QUALIFICATION_PRIVACY_HEADERS = {
    "Cache-Control": "private, no-store",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
        "img-src 'self' data:; media-src 'self'; "
        "frame-src https://open.spotify.com"
    ),
    "Cross-Origin-Resource-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


def _auth_manager() -> SpotifyOAuth:
    return SpotifyOAuth(scope=SCOPES, open_browser=False)


def _detect_url_type(url: str) -> str:
    """Return ``chart`` or ``label`` for a supported Beatport URL."""
    parsed = urlparse(url)
    if parsed.hostname not in ("beatport.com", "www.beatport.com"):
        raise ValueError(_url_error())
    if "/chart/" in parsed.path:
        return "chart"
    if "/label/" in parsed.path:
        return "label"
    raise ValueError(_url_error())


def _url_error() -> str:
    return (
        "URL must be a Beatport chart or label URL "
        "(e.g. https://www.beatport.com/chart/name/123 "
        "or https://www.beatport.com/label/name/1)"
    )


def _default_transfer_factory(url_type: str, request: SyncRequest) -> Transfer:
    from djsupport.cache import MatchCache
    from djsupport.spotify import get_client

    cache = None if request.no_cache else MatchCache(default_matching_knowledge_path())
    if cache is not None:
        cache.load()
    publication_path = default_publication_manifest_path()
    return Transfer(
        source=(BeatportChartSource() if url_type == "chart" else BeatportLabelSource()),
        spotify=SpotifyMatcher(get_client()),
        publishing_guards=AccountPublishingGuards(),
        matching_knowledge=(
            EphemeralMatchingKnowledge() if cache is None else MatchCacheKnowledge(cache)
        ),
        publication_storage=(
            None if request.dry_run else FilePublicationStorage(publication_path)
        ),
        transfer_storage=FileTransferStorage(
            publication_path.with_suffix(".transfers.json")
        ),
    )


def _default_rekordbox_transfer_factory(
    request: RekordboxBatchRequest, execute_authorized: bool,
    *, local_audition: LocalSourceAudition | None = None,
) -> Transfer:
    from djsupport.cache import MatchCache
    from djsupport.local_audio import ChromaprintLocalAudio
    from djsupport.spotify import get_client

    cache = None if request.no_cache else MatchCache(
        default_matching_knowledge_path(),
    )
    if cache is not None:
        cache.load()
    publication_path = default_publication_manifest_path()
    return Transfer(
        source=RekordboxPlaylistSource(
            request.xml_path,
            include_locations=(
                request.local_audio_identity or request.local_audio_audition
            ),
        ),
        spotify=(
            SpotifyMatcher(get_client()) if execute_authorized else object()
        ),
        publishing_guards=AccountPublishingGuards(),
        matching_knowledge=(
            EphemeralMatchingKnowledge()
            if cache is None else MatchCacheKnowledge(cache)
        ),
        publication_storage=(
            None if request.preview else FilePublicationStorage(publication_path)
        ),
        transfer_storage=FileTransferStorage(
            publication_path.with_suffix(".transfers.json")
        ),
        local_audio=(
            ChromaprintLocalAudio() if request.local_audio_identity else None
        ),
        local_audition=(
            local_audition if request.local_audio_audition else None
        ),
    )


def _thread_runner(target: Callable, args: tuple) -> None:
    threading.Thread(target=target, args=args, daemon=True).start()


def create_app(
    *,
    transfer_factory: Callable[[str, SyncRequest], Transfer] | None = None,
    rekordbox_transfer_factory: Callable[
        [RekordboxBatchRequest, bool], Transfer
    ] | None = None,
    auth_manager: Callable[[], SpotifyOAuth] | None = None,
    background_runner: Callable[[Callable, tuple], None] | None = None,
    local_audition: LocalSourceAudition | None = None,
    first_transfer_readiness: Callable[
        [str | None, bool], FirstTransferReadiness
    ] | None = None,
) -> FastAPI:
    """Create the web adapter with replaceable external-boundary wiring."""
    web_app = FastAPI(title="djsupport", lifespan=lifespan)
    web_app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    make_transfer = transfer_factory or _default_transfer_factory
    audition = local_audition or LocalSourceAudition()
    uses_default_rekordbox_wiring = rekordbox_transfer_factory is None
    if rekordbox_transfer_factory is None:
        def make_rekordbox_transfer(request, execute_authorized):
            return _default_rekordbox_transfer_factory(
                request, execute_authorized, local_audition=audition,
            )
    else:
        make_rekordbox_transfer = rekordbox_transfer_factory
    run_background = background_runner or _thread_runner
    qualification_contexts: dict[str, QualificationDraftRequest] = {}
    if first_transfer_readiness is None:
        def inspect_readiness(xml_path, authorize_private_source):
            return inspect_first_transfer_readiness(
                xml_path,
                authorize_private_source=authorize_private_source,
            )
    else:
        inspect_readiness = first_transfer_readiness

    @web_app.middleware("http")
    async def qualification_privacy(request: FastAPIRequest, call_next):
        qualification_route = (
            request.url.path.startswith("/rekordbox/qualification/")
            or request.url.path.startswith("/qualification/")
        )
        if qualification_route:
            try:
                require_qualification_loopback(request)
            except HTTPException as exc:
                response = JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": exc.detail},
                )
            else:
                response = await call_next(request)
            privacy_headers = dict(QUALIFICATION_PRIVACY_HEADERS)
            if request.url.path.startswith(
                "/rekordbox/qualification/media/"
            ):
                privacy_headers["Content-Security-Policy"] = (
                    "default-src 'none'; media-src 'self'"
                )
            for name, value in privacy_headers.items():
                response.headers[name] = value
        else:
            response = await call_next(request)
        return response

    def oauth_manager():
        return auth_manager() if auth_manager is not None else _auth_manager()

    def require_authenticated() -> None:
        mgr = oauth_manager()
        token = mgr.get_cached_token()
        if not token or mgr.is_token_expired(token):
            raise HTTPException(status_code=401, detail="Not authenticated with Spotify")

    def require_qualification_loopback(request: FastAPIRequest) -> None:
        peer = request.client.host if request.client else ""

        def is_loopback(value: str, *, allow_test: bool = False) -> bool:
            if value == "localhost" or (allow_test and value == "testserver"):
                return True
            try:
                return ipaddress.ip_address(value).is_loopback
            except ValueError:
                return False

        peer_is_test = peer == "testclient"
        if not (peer_is_test or is_loopback(peer)):
            raise HTTPException(
                status_code=403,
                detail="Qualification Workspace is available only on loopback",
            )
        host_header = request.headers.get("host", "")
        try:
            request_host = urlparse(f"//{host_header}").hostname or ""
        except ValueError:
            request_host = ""
        if not is_loopback(request_host, allow_test=peer_is_test):
            raise HTTPException(
                status_code=403,
                detail="Qualification Workspace requires a loopback Host",
            )
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin:
                try:
                    origin_host = urlparse(origin).hostname or ""
                except ValueError:
                    origin_host = ""
                if not is_loopback(origin_host, allow_test=peer_is_test):
                    raise HTTPException(
                        status_code=403,
                        detail=(
                            "Qualification Workspace requires a loopback Origin"
                        ),
                    )

    def transfer_for(transfer_id: str, request: SyncRequest | None = None):
        probe_request = request or SyncRequest(
            url="https://www.beatport.com/chart/durable/1"
        )
        probe = make_transfer("chart", probe_request)
        try:
            progress = probe.progress(transfer_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Transfer not found") from exc
        url_type = _detect_url_type(progress.source)
        return make_transfer(
            url_type,
            request or SyncRequest(
                url=progress.source,
                no_cache=not progress.retain_matching_knowledge,
            ),
        ), progress

    @web_app.get("/capabilities")
    def capabilities():
        from djsupport.agent import capability_document
        from djsupport.local_audio import ChromaprintLocalAudio

        return capability_document(
            ChromaprintLocalAudio().capability(), audition.capability(),
        )

    @web_app.get("/auth/status")
    def auth_status():
        mgr = oauth_manager()
        token = mgr.get_cached_token()
        if token and not mgr.is_token_expired(token):
            return {"authenticated": True}
        if token and mgr.is_token_expired(token):
            try:
                if mgr.refresh_access_token(token["refresh_token"]):
                    return {"authenticated": True}
            except Exception:
                pass
        return {"authenticated": False}

    @web_app.get("/auth/login")
    def auth_login():
        return RedirectResponse(oauth_manager().get_authorize_url())

    @web_app.get("/auth/callback")
    def auth_callback(code: str | None = None, error: str | None = None):
        if error:
            return HTMLResponse(
                f"<h1>Auth error</h1><p>{escape(error)}</p>", status_code=400,
            )
        if not code:
            return HTMLResponse("<h1>Missing code</h1>", status_code=400)
        oauth_manager().get_access_token(code)
        return RedirectResponse("/")

    @web_app.post("/sync")
    def start_sync(request: SyncRequest):
        try:
            url_type = _detect_url_type(request.url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        require_authenticated()
        transfer_id = uuid4().hex
        transfer = make_transfer(url_type, request)
        transfer_request = TransferRequest(
            source=request.url,
            mode=TransferMode.SNAPSHOT,
            preview=request.dry_run,
            threshold=request.threshold,
            retry=request.retry,
            retry_days=request.retry_days,
            playlist_prefix=request.prefix,
            transfer_id=transfer_id,
            retain_matching_knowledge=not request.no_cache,
        )
        transfer.prepare(transfer_request)
        run_background(_run_transfer, (transfer, transfer_request))
        return {
            "transfer_id": transfer_id,
            "url_type": url_type,
        }

    def rekordbox_request(
        request: RekordboxBatchRequest,
    ) -> tuple[BatchPlanRequest, TransferAuthorization]:
        return BatchPlanRequest(
            playlist_references=tuple(request.playlists),
            whole_library=request.whole_library,
            threshold=request.threshold,
            preview=request.preview,
            retry=request.retry,
            retry_days=request.retry_days,
            playlist_prefix=request.prefix,
            local_audio_identity=request.local_audio_identity,
            local_audio_audition=request.local_audio_audition,
            confirm_expensive=request.confirm_expensive,
        ), TransferAuthorization(
            private_source=request.authorize_private_source,
            spotify_write=request.authorize_spotify_write,
        )

    def rekordbox_contract(
        request: RekordboxBatchRequest, *, execute: bool,
    ) -> dict | JSONResponse:
        from djsupport.agent import (
            AgentTransferContract,
            authorization_required_document,
            error_document,
        )

        plan_request, authorization = rekordbox_request(request)
        required = Transfer.authorization_requirement(
            plan_request, authorization, phase="plan",
        )
        if required:
            return authorization_required_document(
                "execute" if execute else "plan", required,
            )
        if request.local_audio_identity and request.no_cache:
            return error_document("plan", "durable_knowledge_required")
        execute_authorized = (
            Transfer.authorization_requirement(
                plan_request, authorization, phase="execute",
            ) is None
        )
        if execute and execute_authorized:
            try:
                require_authenticated()
            except HTTPException as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content=error_document(
                        "execute", "spotify_authentication_required",
                    ),
                )
        try:
            contract = AgentTransferContract(make_rekordbox_transfer(
                request, execute and execute_authorized,
            ))
            if execute:
                return contract.execute_batch(plan_request, authorization)
            return contract.plan_batch(plan_request, authorization)
        except Exception:
            return error_document(
                "execute" if execute and execute_authorized else "plan",
                "transfer_failed",
            )

    @web_app.post("/rekordbox/batches/plan")
    def plan_rekordbox_batch(request: RekordboxBatchRequest):
        return rekordbox_contract(request, execute=False)

    @web_app.post("/rekordbox/batches/execute")
    def execute_rekordbox_batch(request: RekordboxBatchRequest):
        return rekordbox_contract(request, execute=True)

    @web_app.post("/rekordbox/first-transfer")
    def first_rekordbox_transfer(request: FirstRekordboxTransferRequest):
        """Render exactly one public guide step without adding policy."""
        from djsupport.agent import (
            AgentTransferContract,
            FirstTransferGuideRequest,
            error_document,
        )
        from djsupport.local_audio import ChromaprintLocalAudio

        readiness = inspect_readiness(
            request.xml_path, request.authorize_private_source,
        )

        adapter_request = RekordboxBatchRequest(
            xml_path=readiness.xml_path or "",
            playlists=(
                [request.playlist_reference]
                if request.playlist_reference is not None else []
            ),
            preview=not bool(request.action and request.action.publishes),
            local_audio_identity=bool(request.local_audio_identity),
            authorize_private_source=request.authorize_private_source,
            authorize_spotify_write=request.authorize_spotify_write,
        )
        activate = bool(
            readiness.spotify_configured
            and readiness.spotify_authenticated
            and readiness.rekordbox_configured
            and readiness.rekordbox_available
            and request.playlist_reference is not None
            and request.local_audio_identity is not None
            and request.authorize_private_source
        )
        spotify_access = bool(
            activate and readiness.spotify_authenticated
            and request.action is not None
            and request.action.needs_spotify_access
        )
        try:
            if uses_default_rekordbox_wiring and not activate:
                transfer = Transfer(
                    source=object(),
                    spotify=object(),
                    matching_knowledge=EphemeralMatchingKnowledge(),
                    publishing_guards=AccountPublishingGuards(),
                    local_audio=ChromaprintLocalAudio(),
                )
            else:
                transfer = make_rekordbox_transfer(
                    adapter_request, spotify_access,
                )
            contract = AgentTransferContract(transfer)
            return contract.first_rekordbox_transfer(
                FirstTransferGuideRequest(
                    spotify_configured=readiness.spotify_configured,
                    spotify_authenticated=readiness.spotify_authenticated,
                    rekordbox_configured=readiness.rekordbox_configured,
                    rekordbox_available=readiness.rekordbox_available,
                    playlist_reference=request.playlist_reference,
                    local_audio_identity=request.local_audio_identity,
                    action=request.action,
                    transfer_id=request.transfer_id,
                    draft_id=request.draft_id,
                ),
                TransferAuthorization(
                    private_source=request.authorize_private_source,
                    spotify_write=request.authorize_spotify_write,
                ),
            )
        except SpotifyOauthError:
            return error_document(
                "first_rekordbox_transfer",
                "spotify_authentication_required",
            )
        except Exception:
            return error_document(
                "first_rekordbox_transfer", "transfer_failed",
            )

    def recover_qualification_context(
        draft_id: str,
    ) -> QualificationDraftRequest | None:
        if not uses_default_rekordbox_wiring:
            return None
        from djsupport.config import ConfigManager

        publication_path = default_publication_manifest_path()
        storage = FileTransferStorage(
            publication_path.with_suffix(".transfers.json")
        )
        draft = storage.load_qualification(draft_id)
        if draft is None:
            return None
        state = storage.load_transfer(draft.transfer_id)
        if state is None:
            return None
        config = ConfigManager()
        config.load()
        xml_path = config.get_rekordbox_xml_path()
        if not xml_path or not Path(xml_path).is_file():
            return None
        return QualificationDraftRequest(
            xml_path=xml_path,
            transfer_id=draft.batch_id or draft.transfer_id,
            playlist_reference=draft.source_reference,
            no_cache=not state.request.get("retain_matching_knowledge", True),
            local_audio_identity=state.request.get(
                "local_audio_identity", False,
            ),
            local_audio_audition=state.request.get(
                "local_audio_audition", False,
            ),
            authorize_private_source=True,
        )

    def durable_qualification_context(
        request: QualificationDraftRequest,
    ) -> QualificationDraftRequest:
        """Derive adapter wiring from durable Transfer intent, not web input."""
        if not uses_default_rekordbox_wiring:
            return request
        publication_path = default_publication_manifest_path()
        storage = FileTransferStorage(
            publication_path.with_suffix(".transfers.json")
        )
        batch = storage.load_batch(request.transfer_id)
        transfer_id = request.transfer_id
        if batch is not None:
            selected = [
                item for item in batch.playlists
                if item.reference == request.playlist_reference
            ]
            if len(selected) != 1:
                return request
            transfer_id = selected[0].transfer_id
        state = storage.load_transfer(transfer_id)
        if state is None:
            return request
        return request.copy(update={
            "no_cache": not state.request.get(
                "retain_matching_knowledge", True,
            ),
            "local_audio_identity": state.request.get(
                "local_audio_identity", False,
            ),
            "local_audio_audition": state.request.get(
                "local_audio_audition", False,
            ),
        })

    def qualification_transfer(draft_id: str) -> Transfer:
        context = None
        if uses_default_rekordbox_wiring:
            context = recover_qualification_context(draft_id)
            if context is not None:
                qualification_contexts[draft_id] = context
        else:
            context = qualification_contexts.get(draft_id)
        if context is None:
            if uses_default_rekordbox_wiring:
                publication_path = default_publication_manifest_path()
                storage = FileTransferStorage(
                    publication_path.with_suffix(".transfers.json")
                )
                if storage.load_qualification(draft_id) is not None:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Qualification source evidence is unavailable; "
                            "review required"
                        ),
                    )
            raise HTTPException(
                status_code=404, detail="Qualification Draft is unavailable",
            )
        return make_rekordbox_transfer(context.transfer_request(), True)

    @web_app.post("/rekordbox/qualification/drafts")
    def create_qualification_draft(
        request: FastAPIRequest, payload: QualificationDraftRequest,
    ):
        require_qualification_loopback(request)
        if not payload.authorize_private_source:
            raise HTTPException(
                status_code=403, detail="Private source authorization required",
            )
        require_authenticated()
        context = durable_qualification_context(payload)
        transfer = make_rekordbox_transfer(context.transfer_request(), True)
        try:
            view = transfer.obtain_qualification(
                QualificationRequest(
                    transfer_id=payload.transfer_id,
                    playlist_reference=payload.playlist_reference,
                    include_all=payload.include_all,
                ),
                TransferAuthorization(private_source=True),
            )
        except SpotifyPlaylistReviewRequired as exc:
            raise HTTPException(
                status_code=409, detail="Qualification review required",
            ) from exc
        except (PermissionError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail="Qualification Draft is unavailable",
            ) from exc
        qualification_contexts[view.draft_id] = context
        return _qualification_to_dict(view)

    @web_app.get("/rekordbox/qualification/drafts/{draft_id}")
    def get_qualification_draft(
        draft_id: str,
        request: FastAPIRequest,
        authorize_private_source: bool = False,
    ):
        require_qualification_loopback(request)
        if not authorize_private_source:
            raise HTTPException(
                status_code=403, detail="Private source authorization required",
            )
        require_authenticated()
        try:
            return _qualification_to_dict(
                qualification_transfer(draft_id).qualification(
                    draft_id, TransferAuthorization(private_source=True),
                )
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=404, detail="Qualification Draft is unavailable",
            ) from exc

    @web_app.post("/rekordbox/qualification/drafts/{draft_id}/decisions")
    def decide_qualification_item(
        draft_id: str,
        request: FastAPIRequest,
        payload: QualificationDecisionRequest,
    ):
        require_qualification_loopback(request)
        if not payload.authorize_private_source:
            raise HTTPException(
                status_code=403, detail="Private source authorization required",
            )
        require_authenticated()
        try:
            view = qualification_transfer(draft_id).record_qualification(
                draft_id,
                payload.item_id,
                payload.decision,
                TransferAuthorization(private_source=True),
                spotify_reference=payload.spotify_reference,
                reason=payload.reason,
                exclude=payload.exclude,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="Qualification decision is invalid",
            ) from exc
        return _qualification_to_dict(view)

    @web_app.post(
        "/rekordbox/qualification/drafts/{draft_id}/include-all"
    )
    def include_all_qualification_items(
        draft_id: str,
        request: FastAPIRequest,
        payload: QualificationAuthorizationRequest,
    ):
        require_qualification_loopback(request)
        if not payload.authorize_private_source:
            raise HTTPException(
                status_code=403, detail="Private source authorization required",
            )
        require_authenticated()
        transfer = qualification_transfer(draft_id)
        context = qualification_contexts[draft_id]
        try:
            view = transfer.obtain_qualification(
                QualificationRequest(
                    transfer_id=context.transfer_id,
                    playlist_reference=context.playlist_reference,
                    include_all=True,
                ),
                TransferAuthorization(private_source=True),
            )
        except SpotifyPlaylistReviewRequired as exc:
            raise HTTPException(
                status_code=409, detail="Qualification review required",
            ) from exc
        except (PermissionError, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail="Qualification Draft cannot include all proposals",
            ) from exc
        qualification_contexts[view.draft_id] = context
        return _qualification_to_dict(view)

    @web_app.post(
        "/rekordbox/qualification/drafts/{draft_id}/audition/{item_id}"
    )
    def audition_qualification_item(
        draft_id: str,
        item_id: str,
        request: FastAPIRequest,
        payload: QualificationAuthorizationRequest,
    ):
        require_qualification_loopback(request)
        if not payload.authorize_private_source:
            raise HTTPException(
                status_code=403, detail="Private source authorization required",
            )
        require_authenticated()
        try:
            result = qualification_transfer(draft_id).audition_qualification(
                draft_id,
                item_id,
                TransferAuthorization(private_source=True),
            )
        except (SpotifyPlaylistChanged, SpotifyPlaylistReviewRequired) as exc:
            raise HTTPException(
                status_code=409, detail="Qualification review required",
            ) from exc
        except (PermissionError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail="Local audition is unavailable",
            ) from exc
        response = {
            "status": result.status,
            "media_type": result.media_type,
            "content_length": result.content_length,
            "expires_in": result.expires_in,
        }
        if result.status == "available" and result.handle:
            response["media_url"] = (
                f"/rekordbox/qualification/media/{result.handle}"
            )
        elif result.reason:
            response["reason"] = result.reason
        return response

    @web_app.post("/rekordbox/qualification/drafts/{draft_id}/apply")
    def apply_qualification_draft(
        draft_id: str,
        request: FastAPIRequest,
        payload: QualificationAuthorizationRequest,
    ):
        require_qualification_loopback(request)
        if not payload.authorize_private_source:
            raise HTTPException(
                status_code=403, detail="Private source authorization required",
            )
        if not payload.authorize_spotify_write:
            raise HTTPException(
                status_code=403, detail="Spotify write authorization required",
            )
        require_authenticated()
        try:
            outcome = qualification_transfer(draft_id).apply_qualification(
                draft_id,
                TransferAuthorization(private_source=True, spotify_write=True),
            )
        except (SpotifyPlaylistChanged, SpotifyPlaylistReviewRequired) as exc:
            raise HTTPException(
                status_code=409, detail="Qualification review required",
            ) from exc
        except (PermissionError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail="Qualification Draft cannot be applied",
            ) from exc
        return {
            "draft_id": outcome.draft_id,
            "status": outcome.status.value,
            "applied_items": outcome.applied_items,
            "authority": "none",
            "next_actions": list(outcome.next_actions),
        }

    @web_app.post("/rekordbox/qualification/drafts/{draft_id}/link")
    def link_qualification_draft(
        draft_id: str,
        request: FastAPIRequest,
        payload: QualificationLinkRequest,
    ):
        require_qualification_loopback(request)
        if not payload.authorize_private_source:
            raise HTTPException(
                status_code=403, detail="Private source authorization required",
            )
        require_authenticated()
        try:
            view = qualification_transfer(draft_id).link_qualification(
                draft_id,
                payload.publishing_transfer_id,
                TransferAuthorization(private_source=True),
            )
        except (SpotifyPlaylistChanged, SpotifyPlaylistReviewRequired) as exc:
            raise HTTPException(
                status_code=409, detail="Qualification review required",
            ) from exc
        except (PermissionError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail="Qualification Draft cannot be linked",
            ) from exc
        return _qualification_to_dict(view)

    @web_app.post("/rekordbox/qualification/drafts/{draft_id}/discard")
    def discard_qualification_draft(
        draft_id: str,
        request: FastAPIRequest,
        payload: QualificationAuthorizationRequest,
    ):
        require_qualification_loopback(request)
        if not payload.authorize_private_source:
            raise HTTPException(
                status_code=403, detail="Private source authorization required",
            )
        require_authenticated()
        try:
            view = qualification_transfer(draft_id).discard_qualification(
                draft_id, TransferAuthorization(private_source=True),
            )
        except (PermissionError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail="Qualification Draft cannot be discarded",
            ) from exc
        return _qualification_to_dict(view)

    @web_app.post("/rekordbox/qualification/drafts/{draft_id}/supersede")
    def supersede_qualification_draft(
        draft_id: str,
        request: FastAPIRequest,
        payload: QualificationAuthorizationRequest,
    ):
        require_qualification_loopback(request)
        if not payload.authorize_private_source:
            raise HTTPException(
                status_code=403, detail="Private source authorization required",
            )
        require_authenticated()
        try:
            view = qualification_transfer(draft_id).supersede_qualification(
                draft_id, TransferAuthorization(private_source=True),
            )
        except SpotifyPlaylistReviewRequired as exc:
            raise HTTPException(
                status_code=409, detail="Qualification review required",
            ) from exc
        except (PermissionError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail="Qualification Draft cannot be superseded",
            ) from exc
        qualification_contexts[view.draft_id] = qualification_contexts[draft_id]
        return _qualification_to_dict(view)

    @web_app.post("/rekordbox/qualification/drafts/{draft_id}/approve")
    def approve_qualification_draft(
        draft_id: str,
        request: FastAPIRequest,
        payload: QualificationAuthorizationRequest,
    ):
        require_qualification_loopback(request)
        if not payload.authorize_private_source:
            raise HTTPException(
                status_code=403, detail="Private source authorization required",
            )
        require_authenticated()
        try:
            outcome = qualification_transfer(draft_id).approve_qualification(
                draft_id,
                TransferAuthorization(private_source=True),
            )
        except (SpotifyPlaylistChanged, SpotifyPlaylistReviewRequired) as exc:
            raise HTTPException(
                status_code=409, detail="Qualification review required",
            ) from exc
        except (PermissionError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail="Qualification Draft cannot be approved",
            ) from exc
        return {
            "draft_id": draft_id,
            "status": outcome.status.value.replace(" ", "_"),
            "authority": (
                "playlist_approval"
                if outcome.status.value == "approved" else "none"
            ),
            "counts": {
                "approved": len(outcome.approved),
                "rejected": len(outcome.rejected),
                "collisions": len(outcome.collisions),
                "corrections": len(outcome.corrections),
            },
            "next_actions": (
                ["review"] if outcome.status.value == "needs review" else []
            ),
        }

    @web_app.get("/rekordbox/qualification/media/{handle}")
    def qualification_media(handle: str, request: FastAPIRequest):
        require_qualification_loopback(request)
        privacy_headers = QUALIFICATION_PRIVACY_HEADERS
        try:
            stream = audition.stream(handle, request.headers.get("range"))
        except AuditionHandleUnavailable as exc:
            raise HTTPException(
                status_code=404, detail="Local audition is unavailable",
                headers=privacy_headers,
            ) from exc
        except AuditionRangeNotSatisfiable as exc:
            raise HTTPException(
                status_code=416,
                detail="Audition byte range is not satisfiable",
                headers={
                    **privacy_headers,
                    "Content-Range": f"bytes */{exc.total_size}",
                },
            ) from exc
        headers = {
            **privacy_headers,
            "Accept-Ranges": "bytes",
            "Content-Length": str(stream.content_length),
        }
        if stream.content_range is not None:
            headers["Content-Range"] = stream.content_range
        return StreamingResponse(
            stream.body,
            status_code=stream.status_code,
            media_type=stream.media_type,
            headers=headers,
        )

    @web_app.get("/sync/{transfer_id}/progress")
    async def sync_progress(transfer_id: str):
        async def event_stream():
            while True:
                transfer, progress = transfer_for(transfer_id)
                data = {
                    "phase": (
                        "complete" if progress.status == "completed"
                        else "error" if progress.error
                        else progress.status
                    ),
                    "current": progress.current,
                    "total": progress.total,
                    "detail": progress.error or f"{progress.current}/{progress.total}",
                }
                yield f"data: {json.dumps(data)}\n\n"
                if progress.status in {"completed", "paused", "abandoned"}:
                    break
                await asyncio.sleep(0.25)
        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @web_app.post("/sync/{transfer_id}/resume")
    def resume_sync(transfer_id: str):
        require_authenticated()
        transfer, progress = transfer_for(transfer_id)
        if progress.status not in {"completed", "abandoned"}:
            resume_request = TransferRequest(
                source=progress.source,
                transfer_id=transfer_id,
                retain_matching_knowledge=progress.retain_matching_knowledge,
            )
            transfer.prepare(resume_request)
            run_background(
                _run_transfer,
                (transfer, resume_request),
            )
        return {"transfer_id": transfer_id, "status": progress.status}

    @web_app.get("/sync/{transfer_id}/result")
    def sync_result(transfer_id: str):
        transfer, progress = transfer_for(transfer_id)
        if progress.error:
            return {"error": progress.error, "transfer_id": transfer_id}
        if progress.status != "completed":
            raise HTTPException(status_code=202, detail="Transfer still in progress")
        report = transfer.execute(TransferRequest(
            source=progress.source, transfer_id=transfer_id,
        ))
        return _report_to_dict(report)

    @web_app.get("/")
    def index():
        return HTMLResponse((STATIC_DIR / "index.html").read_text())

    @web_app.get("/qualification/{draft_id}")
    def qualification_workspace(draft_id: str, request: FastAPIRequest):
        require_qualification_loopback(request)
        del draft_id
        return HTMLResponse((STATIC_DIR / "index.html").read_text())

    return web_app


def _run_transfer(transfer: Transfer, request: TransferRequest) -> None:
    try:
        transfer.execute(request)
    except Exception:
        logger.exception("Transfer failed")


def _qualification_to_dict(view: QualificationView) -> dict[str, Any]:
    """Render only review facts; filesystem references stay behind Transfer."""
    items = []
    for item in view.items:
        spotify_id = None
        prefix = "spotify:track:"
        if item.spotify_uri.startswith(prefix):
            candidate = item.spotify_uri[len(prefix):]
            if len(candidate) == 22 and candidate.isalnum():
                spotify_id = candidate
        items.append({
            "item_id": item.item_id,
            "source": {
                "artist": item.source_artist,
                "title": item.source_title,
                "release": item.source_release,
                "label": item.source_label,
                "version": item.source_version,
                "duration": item.source_duration,
            },
            "spotify": {
                "uri": item.spotify_uri,
                "name": item.spotify_name,
                "artist": item.spotify_artist,
                "release": item.spotify_release,
                "duration": item.spotify_duration,
                "embed_url": (
                    f"https://open.spotify.com/embed/track/{spotify_id}"
                    if spotify_id else None
                ),
                "open_url": (
                    f"https://open.spotify.com/track/{spotify_id}"
                    if spotify_id else None
                ),
            },
            "proposal": {
                "score": item.score,
                "match_type": item.match_type,
                "score_reasons": list(item.score_reasons),
                "authority_status": item.authority_status,
                "attention_reasons": list(item.attention_reasons),
                "availability_status": item.availability_status,
                "availability_reason": item.availability_reason,
                "availability_checked_at": item.availability_checked_at,
                "availability_source": item.availability_source,
            },
            "permitted_actions": [
                action.value for action in item.permitted_actions
            ],
            "audition_status": item.audition_status,
            "audition_reason": item.audition_reason,
            "decision": item.decision.value if item.decision else None,
            "correction_uri": item.correction_uri,
            "deferred_reason": item.deferred_reason,
            "excluded": item.excluded,
        })
    return {
        "draft_id": view.draft_id,
        "transfer_id": view.transfer_id,
        "status": view.status.value,
        "authority": "none",
        "next_actions": list(view.next_actions),
        "include_all": view.include_all,
        "counts": {
            "items": len(view.items),
            "pending": view.pending,
            "deferred": view.deferred,
        },
        "current_item_id": (
            view.current_item.item_id if view.current_item is not None else None
        ),
        "items": items,
    }


def _report_to_dict(report: SyncReport) -> dict[str, Any]:
    playlists = []
    for playlist in report.playlists:
        playlists.append({
            "name": playlist.name,
            "path": playlist.path,
            "action": playlist.action,
            "outcome": playlist.outcome,
            "spotify_playlist_id": playlist.spotify_playlist_id,
            "spotify_url": (
                f"https://open.spotify.com/playlist/{playlist.spotify_playlist_id}"
                if playlist.spotify_playlist_id else None
            ),
            "matched": [
                {
                    "source_name": match.source_name,
                    "spotify_name": match.spotify_name,
                    "spotify_artist": match.spotify_artist,
                    "score": match.score,
                    "match_type": match.match_type,
                }
                for match in playlist.matched
            ],
            "unmatched": playlist.unmatched,
            "total": playlist.total,
            "match_rate": playlist.match_rate,
            "cache_hits": playlist.cache_hits,
            "api_lookups": playlist.api_lookups,
            "retried": playlist.retried,
            "local_audio_eligible": playlist.local_audio_eligible,
            "local_audio_observed": playlist.local_audio_observed,
            "local_audio_unavailable": playlist.local_audio_unavailable,
            "local_audio_reused": playlist.local_audio_reused,
        })
    return {
        "timestamp": report.timestamp.isoformat(),
        "threshold": report.threshold,
        "dry_run": report.dry_run,
        "source_label": report.source_label,
        "transfer_id": report.transfer_id,
        "status": report.status,
        "playlists": playlists,
        "total_matched": report.total_matched,
        "total_unmatched": report.total_unmatched,
        "overall_match_rate": report.overall_match_rate,
        "local_audio_eligible": sum(
            playlist.local_audio_eligible for playlist in report.playlists
        ),
        "local_audio_observed": sum(
            playlist.local_audio_observed for playlist in report.playlists
        ),
        "local_audio_unavailable": sum(
            playlist.local_audio_unavailable for playlist in report.playlists
        ),
        "local_audio_reused": sum(
            playlist.local_audio_reused for playlist in report.playlists
        ),
    }


app = create_app()
