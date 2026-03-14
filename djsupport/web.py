"""FastAPI web backend for djsupport."""

from __future__ import annotations

import asyncio
import json
import queue
import uuid
from dataclasses import asdict
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from spotipy.oauth2 import SpotifyOAuth

from djsupport.service import ProgressEvent, sync_beatport_chart, sync_beatport_label
from djsupport.spotify import SCOPES, RateLimitError

load_dotenv()

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="djsupport")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# In-memory job store (single-user, single-job)
# ---------------------------------------------------------------------------

class SyncJob:
    def __init__(self, job_id: str, url: str):
        self.job_id = job_id
        self.url = url
        self.progress_queue: queue.Queue[ProgressEvent | None] = queue.Queue(maxsize=500)
        self.result: dict | None = None
        self.error: str | None = None
        self.done = False


_current_job: SyncJob | None = None
_job_lock = Lock()


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

def _auth_manager() -> SpotifyOAuth:
    return SpotifyOAuth(scope=SCOPES, open_browser=False)


@app.get("/auth/status")
def auth_status():
    """Check if a valid Spotify token exists."""
    mgr = _auth_manager()
    token = mgr.get_cached_token()
    if token and not mgr.is_token_expired(token):
        return {"authenticated": True}
    if token and mgr.is_token_expired(token):
        refreshed = mgr.refresh_access_token(token["refresh_token"])
        if refreshed:
            return {"authenticated": True}
    return {"authenticated": False}


@app.get("/auth/login")
def auth_login():
    """Redirect the user to Spotify's authorization page."""
    mgr = _auth_manager()
    auth_url = mgr.get_authorize_url()
    return RedirectResponse(auth_url)


@app.get("/auth/callback")
def auth_callback(code: str | None = None, error: str | None = None):
    """Handle the Spotify OAuth callback."""
    if error:
        return HTMLResponse(f"<h1>Auth error</h1><p>{error}</p>", status_code=400)
    if not code:
        return HTMLResponse("<h1>Missing code</h1>", status_code=400)

    mgr = _auth_manager()
    mgr.get_access_token(code)
    return RedirectResponse("/")


# ---------------------------------------------------------------------------
# Sync endpoints
# ---------------------------------------------------------------------------

class SyncRequest(BaseModel):
    url: str


def _detect_url_type(url: str) -> str:
    """Return 'chart', 'label', or raise ValueError."""
    if "beatport.com/chart/" in url:
        return "chart"
    if "beatport.com/label/" in url:
        return "label"
    raise ValueError(
        "URL must be a Beatport chart or label URL "
        "(e.g. https://www.beatport.com/chart/name/123 "
        "or https://www.beatport.com/label/name/1)"
    )


@app.post("/sync")
def start_sync(req: SyncRequest):
    """Start a sync job. Returns the job ID."""
    global _current_job

    # Validate URL type
    try:
        url_type = _detect_url_type(req.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Check auth
    mgr = _auth_manager()
    token = mgr.get_cached_token()
    if not token or mgr.is_token_expired(token):
        raise HTTPException(status_code=401, detail="Not authenticated with Spotify")

    with _job_lock:
        if _current_job is not None and not _current_job.done:
            raise HTTPException(status_code=409, detail="A sync is already running")

        job_id = uuid.uuid4().hex[:12]
        job = SyncJob(job_id, req.url)
        _current_job = job

    # Run sync in background thread
    asyncio.get_event_loop().run_in_executor(None, _run_sync, job, url_type)
    return {"job_id": job_id, "url_type": url_type}


def _run_sync(job: SyncJob, url_type: str) -> None:
    """Execute the sync in a background thread."""
    from djsupport.cache import MatchCache
    from djsupport.spotify import get_client
    from djsupport.state import PlaylistStateManager

    cache_path = (
        ".djsupport_beatport_cache.json" if url_type == "chart"
        else ".djsupport_label_cache.json"
    )
    state_path = (
        ".djsupport_beatport_playlists.json" if url_type == "chart"
        else ".djsupport_label_playlists.json"
    )

    cache = MatchCache(cache_path)
    cache.load()
    state_mgr = PlaylistStateManager(state_path)
    state_mgr.load()

    def _on_progress(event: ProgressEvent) -> None:
        try:
            job.progress_queue.put_nowait(event)
        except queue.Full:
            pass  # drop event if consumer is too slow

    try:
        sp = get_client()
        if url_type == "chart":
            report = sync_beatport_chart(
                job.url, sp=sp, cache=cache, state_mgr=state_mgr,
                on_progress=_on_progress,
            )
        else:
            report = sync_beatport_label(
                job.url, sp=sp, cache=cache, state_mgr=state_mgr,
                on_progress=_on_progress,
            )

        cache.save()
        state_mgr.save()

        job.result = _report_to_dict(report)
    except RateLimitError as e:
        cache.save()
        job.error = str(e)
        _on_progress(ProgressEvent(phase="error", detail=str(e)))
    except Exception as e:
        job.error = str(e)
        _on_progress(ProgressEvent(phase="error", detail=str(e)))
    finally:
        job.done = True
        job.progress_queue.put(None)  # sentinel


def _report_to_dict(report) -> dict:
    """Serialize a SyncReport to a JSON-safe dict."""
    playlists = []
    for pl in report.playlists:
        matched = [
            {
                "source_name": m.source_name,
                "spotify_name": m.spotify_name,
                "spotify_artist": m.spotify_artist,
                "score": m.score,
                "match_type": m.match_type,
            }
            for m in pl.matched
        ]
        playlists.append({
            "name": pl.name,
            "path": pl.path,
            "action": pl.action,
            "spotify_playlist_id": pl.spotify_playlist_id,
            "spotify_url": (
                f"https://open.spotify.com/playlist/{pl.spotify_playlist_id}"
                if pl.spotify_playlist_id else None
            ),
            "matched": matched,
            "unmatched": pl.unmatched,
            "total": pl.total,
            "match_rate": pl.match_rate,
            "cache_hits": pl.cache_hits,
            "api_lookups": pl.api_lookups,
            "retried": pl.retried,
        })

    return {
        "timestamp": report.timestamp.isoformat(),
        "threshold": report.threshold,
        "dry_run": report.dry_run,
        "source_label": report.source_label,
        "playlists": playlists,
        "total_matched": report.total_matched,
        "total_unmatched": report.total_unmatched,
        "overall_match_rate": report.overall_match_rate,
    }


@app.get("/sync/{job_id}/progress")
async def sync_progress(job_id: str):
    """Stream progress events via SSE."""
    if _current_job is None or _current_job.job_id != job_id:
        raise HTTPException(status_code=404, detail="Job not found")

    job = _current_job

    async def event_stream():
        while True:
            try:
                event = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: job.progress_queue.get(timeout=30)
                )
            except queue.Empty:
                # Send keepalive
                yield f": keepalive\n\n"
                continue

            if event is None:  # sentinel — sync done
                if job.error:
                    data = json.dumps({"phase": "error", "detail": job.error})
                else:
                    data = json.dumps({"phase": "complete", "detail": "Sync complete"})
                yield f"data: {data}\n\n"
                break

            data = json.dumps({
                "phase": event.phase,
                "current": event.current,
                "total": event.total,
                "detail": event.detail,
            })
            yield f"data: {data}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/sync/{job_id}/result")
def sync_result(job_id: str):
    """Get the final sync result."""
    if _current_job is None or _current_job.job_id != job_id:
        raise HTTPException(status_code=404, detail="Job not found")

    if not _current_job.done:
        raise HTTPException(status_code=202, detail="Sync still in progress")

    if _current_job.error:
        return {"error": _current_job.error}

    return _current_job.result


# ---------------------------------------------------------------------------
# Serve frontend
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    """Serve the frontend."""
    index_path = STATIC_DIR / "index.html"
    return HTMLResponse(index_path.read_text())
