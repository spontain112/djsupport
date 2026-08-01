"""Thin FastAPI adapter for durable djsupport Transfers."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from spotipy.oauth2 import SpotifyOAuth

from djsupport.report import SyncReport
from djsupport.spotify import SCOPES
from djsupport.transfer import (
    AccountPublishingGuards,
    BeatportChartSource,
    BeatportLabelSource,
    EphemeralMatchingKnowledge,
    FilePublicationStorage,
    FileTransferStorage,
    MatchCacheKnowledge,
    SpotifyMatcher,
    Transfer,
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


def _thread_runner(target: Callable, args: tuple) -> None:
    threading.Thread(target=target, args=args, daemon=True).start()


def create_app(
    *,
    transfer_factory: Callable[[str, SyncRequest], Transfer] | None = None,
    auth_manager: Callable[[], SpotifyOAuth] | None = None,
    background_runner: Callable[[Callable, tuple], None] | None = None,
) -> FastAPI:
    """Create the web adapter with replaceable external-boundary wiring."""
    web_app = FastAPI(title="djsupport", lifespan=lifespan)
    web_app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    make_transfer = transfer_factory or _default_transfer_factory
    run_background = background_runner or _thread_runner

    def oauth_manager():
        return auth_manager() if auth_manager is not None else _auth_manager()

    def require_authenticated() -> None:
        mgr = oauth_manager()
        token = mgr.get_cached_token()
        if not token or mgr.is_token_expired(token):
            raise HTTPException(status_code=401, detail="Not authenticated with Spotify")

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
            request or SyncRequest(url=progress.source),
        ), progress

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
        )
        transfer.prepare(transfer_request)
        run_background(_run_transfer, (transfer, transfer_request))
        return {
            "transfer_id": transfer_id,
            "url_type": url_type,
        }

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
            run_background(
                _run_transfer,
                (transfer, TransferRequest(
                    source=progress.source, transfer_id=transfer_id,
                )),
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

    return web_app


def _run_transfer(transfer: Transfer, request: TransferRequest) -> None:
    try:
        transfer.execute(request)
    except Exception:
        logger.exception("Transfer failed")


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
    }


app = create_app()
