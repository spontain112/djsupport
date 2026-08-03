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
    FilePublicationStorage,
    FileTransferStorage,
    SourceSelection,
    Transfer,
    TransferProgress,
)
from djsupport.web import app, create_app


client = TestClient(app)


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
