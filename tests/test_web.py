"""Tests for the FastAPI web backend."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from djsupport.report import PlaylistReport, SyncReport
from djsupport.rekordbox import Track
from djsupport.transfer import (
    AccountPublishingGuards,
    BatchPlan,
    FilePublicationStorage,
    FileTransferStorage,
    PlaylistPreflight,
    SourceSelection,
    Transfer,
    TransferProgress,
)
from djsupport.web import _report_to_dict, app, create_app


client = TestClient(app)


def test_web_outcome_exposes_aggregate_local_audio_counts():
    playlist = PlaylistReport(name="Synthetic", path="private", action="preview")
    playlist.local_audio_eligible = 3
    playlist.local_audio_observed = 2
    playlist.local_audio_unavailable = 1
    playlist.local_audio_reused = 1
    report = SyncReport(
        timestamp=datetime(2026, 8, 3), threshold=80, dry_run=True,
        playlists=[playlist],
    )

    rendered = _report_to_dict(report)

    assert rendered["local_audio_eligible"] == 3
    assert rendered["local_audio_observed"] == 2
    assert rendered["local_audio_unavailable"] == 1
    assert rendered["local_audio_reused"] == 1


def _agent_web_transfer(plan, report=None):
    transfer = MagicMock()
    transfer.authorization_requirement.side_effect = (
        lambda request, authorization, phase: Transfer.authorization_requirement(
            request, authorization, phase=phase,
        )
    )
    transfer.plan_batch.return_value = plan
    if report is not None:
        transfer.execute_batch.return_value = report
    return transfer


def test_rekordbox_web_plan_exposes_explicit_local_audio_opt_in_without_spotify():
    plan = BatchPlan((PlaylistPreflight(
        name="Private Selection",
        reference="Private/Selection",
        total_tracks=2,
        approved_match_hits=0,
        cache_hits=0,
        expected_uncached_lookups=2,
        local_audio_eligible=2,
        local_audio_pending=2,
        selection_token="private-content-token",
    ),), local_audio_identity=True)
    factory_calls = []

    def factory(request, execute_authorized):
        factory_calls.append((request, execute_authorized))
        return _agent_web_transfer(plan)

    web = create_app(
        rekordbox_transfer_factory=factory,
        auth_manager=lambda: (_ for _ in ()).throw(
            AssertionError("Spotify must stay untouched during planning")
        ),
    )
    response = TestClient(web).post("/rekordbox/batches/plan", json={
        "xml_path": "/private/synthetic-library.xml",
        "playlists": ["Private/Selection"],
        "local_audio_identity": True,
        "authorize_private_source": True,
    })

    assert response.status_code == 200
    body = response.json()
    assert body["phase"] == "plan"
    assert body["counts"]["local_audio_eligible"] == 2
    assert body["counts"]["local_audio_pending"] == 2
    assert factory_calls[0][0].local_audio_identity is True
    assert factory_calls[0][1] is False
    assert "synthetic-library" not in response.text


def test_rekordbox_web_execute_returns_aggregate_local_audio_outcome():
    plan = BatchPlan((PlaylistPreflight(
        name="Private Selection",
        reference="Private/Selection",
        total_tracks=1,
        approved_match_hits=0,
        cache_hits=0,
        expected_uncached_lookups=1,
        local_audio_eligible=1,
        local_audio_pending=1,
        selection_token="private-content-token",
    ),), local_audio_identity=True)
    playlist = PlaylistReport(
        name="Private Selection", path="Private/Selection", action="preview",
    )
    playlist.local_audio_eligible = 1
    playlist.local_audio_observed = 1
    playlist.local_audio_reused = 1
    report = SyncReport(
        timestamp=datetime(2026, 8, 3), threshold=80, dry_run=True,
        playlists=[playlist], transfer_id=plan.batch_id, status="completed",
    )
    transfer = _agent_web_transfer(plan, report)
    mgr = MagicMock()
    mgr.get_cached_token.return_value = {"access_token": "tok"}
    mgr.is_token_expired.return_value = False
    web = create_app(
        rekordbox_transfer_factory=lambda request, authorized: transfer,
        auth_manager=lambda: mgr,
    )

    response = TestClient(web).post("/rekordbox/batches/execute", json={
        "xml_path": "/private/synthetic-library.xml",
        "playlists": ["Private/Selection"],
        "preview": True,
        "local_audio_identity": True,
        "authorize_private_source": True,
    })

    assert response.status_code == 200
    assert response.json()["phase"] == "outcome"
    assert response.json()["counts"]["local_audio_observed"] == 1
    assert response.json()["counts"]["local_audio_reused"] == 1
    assert "synthetic-library" not in response.text


def test_rekordbox_web_execute_preserves_execute_phase_authorization_contract():
    web = create_app(
        rekordbox_transfer_factory=lambda request, authorized: (
            _ for _ in ()
        ).throw(AssertionError("private source must stay untouched")),
    )

    response = TestClient(web).post("/rekordbox/batches/execute", json={
        "xml_path": "/private/synthetic-library.xml",
        "playlists": ["Private/Selection"],
    })

    assert response.json() == {
        "contract_version": 1,
        "phase": "execute",
        "status": "authorization_required",
        "required_authorizations": ["private_source"],
        "next_actions": ["authorize_private_source"],
    }


def test_rekordbox_web_execute_plans_before_requesting_spotify_write():
    plan = BatchPlan((PlaylistPreflight(
        name="Private Selection",
        reference="Private/Selection",
        total_tracks=1,
        approved_match_hits=0,
        cache_hits=0,
        expected_uncached_lookups=1,
        selection_token="private-content-token",
    ),))
    transfer = _agent_web_transfer(plan)
    web = create_app(
        rekordbox_transfer_factory=lambda request, authorized: transfer,
    )

    response = TestClient(web).post("/rekordbox/batches/execute", json={
        "xml_path": "/private/synthetic-library.xml",
        "playlists": ["Private/Selection"],
        "authorize_private_source": True,
    })

    assert response.json()["phase"] == "execute"
    assert response.json()["status"] == "authorization_required"
    assert response.json()["required_authorizations"] == ["spotify_write"]
    assert response.json()["batch_id"] == plan.batch_id


def test_rekordbox_web_execute_renders_spotify_login_as_versioned_error():
    plan = BatchPlan((PlaylistPreflight(
        name="Private Selection",
        reference="Private/Selection",
        total_tracks=1,
        approved_match_hits=0,
        cache_hits=0,
        expected_uncached_lookups=1,
        selection_token="private-content-token",
    ),), preview=True)
    transfer = _agent_web_transfer(plan)
    mgr = MagicMock()
    mgr.get_cached_token.return_value = None
    web = create_app(
        rekordbox_transfer_factory=lambda request, authorized: transfer,
        auth_manager=lambda: mgr,
    )

    response = TestClient(web).post("/rekordbox/batches/execute", json={
        "xml_path": "/private/synthetic-library.xml",
        "playlists": ["Private/Selection"],
        "preview": True,
        "authorize_private_source": True,
    })

    assert response.status_code == 401
    assert response.json() == {
        "contract_version": 1,
        "phase": "execute",
        "status": "error",
        "error": {"code": "spotify_authentication_required"},
        "next_actions": ["authenticate_spotify"],
    }


def test_capabilities_are_available_without_spotify_or_private_source(monkeypatch):
    monkeypatch.setattr("djsupport.local_audio.shutil.which", lambda name: None)

    response = TestClient(create_app()).get("/capabilities")

    assert response.status_code == 200
    assert response.json()["contract_version"] == 1
    assert response.json()["phase"] == "capability"
    assert response.json()["capabilities"]["local_audio_identity"] == {
        "available": False,
        "algorithm": "chromaprint",
        "algorithm_version": None,
        "reason": "binary_unavailable",
    }


class TestAuthEndpoints:
    @patch("djsupport.web._auth_manager")
    def test_auth_status_authenticated(self, mock_mgr_fn):
        mgr = MagicMock()
        mgr.get_cached_token.return_value = {"access_token": "tok", "refresh_token": "ref"}
        mgr.is_token_expired.return_value = False
        mock_mgr_fn.return_value = mgr
        res = client.get("/auth/status")
        assert res.status_code == 200
        assert res.json()["authenticated"] is True

    @patch("djsupport.web._auth_manager")
    def test_auth_status_not_authenticated(self, mock_mgr_fn):
        mgr = MagicMock()
        mgr.get_cached_token.return_value = None
        mock_mgr_fn.return_value = mgr
        res = client.get("/auth/status")
        assert res.status_code == 200
        assert res.json()["authenticated"] is False

    @patch("djsupport.web._auth_manager")
    def test_auth_login_redirects(self, mock_mgr_fn):
        mgr = MagicMock()
        mgr.get_authorize_url.return_value = "https://accounts.spotify.com/authorize?..."
        mock_mgr_fn.return_value = mgr
        res = client.get("/auth/login", follow_redirects=False)
        assert res.status_code == 307
        assert "spotify.com" in res.headers["location"]

    @patch("djsupport.web._auth_manager")
    def test_auth_callback_success(self, mock_mgr_fn):
        mgr = MagicMock()
        mock_mgr_fn.return_value = mgr
        res = client.get("/auth/callback?code=abc123", follow_redirects=False)
        assert res.status_code == 307
        assert res.headers["location"] == "/"
        mgr.get_access_token.assert_called_once_with("abc123")

    @patch("djsupport.web._auth_manager")
    def test_auth_callback_error(self, mock_mgr_fn):
        res = client.get("/auth/callback?error=access_denied")
        assert res.status_code == 400


class TestSyncEndpoints:
    def test_sync_invalid_url(self):
        res = client.post("/sync", json={"url": "https://example.com"})
        assert res.status_code == 400
        assert "Beatport" in res.json()["detail"]

    @patch("djsupport.web._auth_manager")
    def test_sync_not_authenticated(self, mock_mgr_fn):
        mgr = MagicMock()
        mgr.get_cached_token.return_value = None
        mock_mgr_fn.return_value = mgr
        res = client.post("/sync", json={"url": "https://www.beatport.com/chart/test/123"})
        assert res.status_code == 401

    def test_chart_flow_reloads_durable_outcome_after_app_restart(self, tmp_path):
        class FixtureSource:
            source_label = "Beatport"

            def consume(self, reference):
                data = json.loads(
                    (Path(__file__).parent / "fixtures/beatport_chart.json").read_text()
                )
                return SourceSelection(data["name"], reference, [
                    Track(
                        track_id=item["track_id"], artist=item["artist"],
                        name=item["name"], album="", remixer="", label="",
                        genre="", date_added="",
                    )
                    for item in data["tracks"]
                ])

        class FixtureSpotify:
            def __init__(self):
                self.playlists = {}

            def account_id(self):
                return "spotify-user-1"

            def match(self, track, threshold):
                return {
                    "uri": f"spotify:track:{track.track_id}", "name": track.name,
                    "artist": track.artist, "score": 96.0, "match_type": "exact",
                }

            def publish_provisional_snapshot(
                self, name, track_uris, description, publication_key,
            ):
                self.playlists["snapshot-1"] = list(track_uris)
                return "snapshot-1"

        class Knowledge:
            persistent = False

            def lookup(self, track, threshold): return None
            def should_retry(self, track, threshold, retry_days, force): return True
            def retain(self, track, threshold, result): pass
            def checkpoint(self): pass

        spotify = FixtureSpotify()
        state_path = tmp_path / "transfers.json"
        factory_requests = []

        def factory(_kind, factory_request):
            factory_requests.append(factory_request)
            return Transfer(
                source=FixtureSource(), spotify=spotify,
                matching_knowledge=Knowledge(),
                publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
                publication_storage=FilePublicationStorage(
                    tmp_path / "publications.json"
                ),
                transfer_storage=FileTransferStorage(state_path),
            )

        mgr = MagicMock()
        mgr.get_cached_token.return_value = {"access_token": "tok"}
        mgr.is_token_expired.return_value = False
        pending_background_work = []
        first_app = create_app(
            transfer_factory=factory,
            auth_manager=lambda: mgr,
            background_runner=lambda target, args: pending_background_work.append(
                (target, args)
            ),
        )
        res = TestClient(first_app).post(
            "/sync", json={
                "url": "https://www.beatport.com/chart/test/123",
                "no_cache": True,
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert "transfer_id" in data
        assert data["url_type"] == "chart"
        assert len(pending_background_work) == 1

        prepared = TestClient(first_app).get(
            f"/sync/{data['transfer_id']}/result",
        )
        assert prepared.status_code == 202

        restarted_app = create_app(
            transfer_factory=factory,
            auth_manager=lambda: mgr,
            background_runner=lambda target, args: target(*args),
        )
        resumed = TestClient(restarted_app).post(
            f"/sync/{data['transfer_id']}/resume",
        )
        assert resumed.status_code == 200
        result = TestClient(restarted_app).get(
            f"/sync/{data['transfer_id']}/result",
        )
        assert result.status_code == 200
        assert result.json()["playlists"][0]["spotify_playlist_id"] == "snapshot-1"
        assert result.json()["status"] == "completed"
        assert result.json()["total_matched"] == 2
        assert spotify.playlists["snapshot-1"] == [
            "spotify:track:bp-1", "spotify:track:bp-2",
        ]
        assert factory_requests[-1].no_cache is True

    def test_label_flow_enters_the_same_transfer_interface(self):
        transfer = MagicMock()
        transfer.execute.return_value = SyncReport(
            timestamp=datetime(2026, 8, 1), threshold=80, dry_run=False,
            playlists=[], source_label="Beatport label", transfer_id="label-transfer",
        )
        mgr = MagicMock()
        mgr.get_cached_token.return_value = {"access_token": "tok"}
        mgr.is_token_expired.return_value = False
        label_app = create_app(
            transfer_factory=lambda kind, request: transfer,
            auth_manager=lambda: mgr,
            background_runner=lambda target, args: target(*args),
        )
        res = TestClient(label_app).post(
            "/sync", json={"url": "https://www.beatport.com/label/test/1"},
        )
        assert res.status_code == 200
        assert res.json()["url_type"] == "label"
        request = transfer.execute.call_args.args[0]
        assert request.source == "https://www.beatport.com/label/test/1"
        assert request.mode.value == "snapshot"
        assert request.local_audio_identity is False

    def test_failed_outcome_reloads_after_restart(self, tmp_path):
        class FailingSource:
            source_label = "Beatport"

            def consume(self, reference):
                raise ValueError("fixture chart is invalid")

        spotify = MagicMock()
        spotify.account_id.return_value = "spotify-user-1"

        class Knowledge:
            persistent = False
            def lookup(self, track, threshold): return None
            def should_retry(self, track, threshold, retry_days, force): return True
            def retain(self, track, threshold, result): pass
            def checkpoint(self): pass

        def factory(_kind, _request):
            return Transfer(
                source=FailingSource(), spotify=spotify,
                matching_knowledge=Knowledge(),
                publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
                publication_storage=FilePublicationStorage(
                    tmp_path / "publications.json"
                ),
                transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
            )

        mgr = MagicMock()
        mgr.get_cached_token.return_value = {"access_token": "tok"}
        mgr.is_token_expired.return_value = False
        failed_app = create_app(
            transfer_factory=factory, auth_manager=lambda: mgr,
            background_runner=lambda target, args: target(*args),
        )
        started = TestClient(failed_app).post(
            "/sync", json={"url": "https://www.beatport.com/chart/test/123"},
        )
        transfer_id = started.json()["transfer_id"]

        restarted = create_app(
            transfer_factory=factory, auth_manager=lambda: mgr,
            background_runner=lambda target, args: target(*args),
        )
        result = TestClient(restarted).get(f"/sync/{transfer_id}/result")

        assert result.status_code == 200
        assert result.json() == {
            "error": "fixture chart is invalid", "transfer_id": transfer_id,
        }


class TestURLDetection:
    def test_chart_url(self):
        from djsupport.web import _detect_url_type
        assert _detect_url_type("https://www.beatport.com/chart/test/123") == "chart"

    def test_label_url(self):
        from djsupport.web import _detect_url_type
        assert _detect_url_type("https://www.beatport.com/label/test/1") == "label"

    def test_invalid_url(self):
        from djsupport.web import _detect_url_type
        with pytest.raises(ValueError):
            _detect_url_type("https://example.com")


class TestIndexPage:
    def test_serves_html(self):
        res = client.get("/")
        assert res.status_code == 200
        assert "djsupport" in res.text
        assert "djsupport.activeTransfer" in res.text
        assert "text/html" in res.headers["content-type"]
