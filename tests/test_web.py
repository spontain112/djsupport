"""Tests for the FastAPI web backend."""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from djsupport.web import app, _current_job, _job_lock, SyncJob


@pytest.fixture(autouse=True)
def reset_job_state():
    """Reset the global job state before each test."""
    import djsupport.web as web_mod
    web_mod._current_job = None
    yield
    web_mod._current_job = None


client = TestClient(app)


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

    @patch("djsupport.web._run_sync")
    @patch("djsupport.web._auth_manager")
    def test_sync_starts_job(self, mock_mgr_fn, mock_run):
        mgr = MagicMock()
        mgr.get_cached_token.return_value = {"access_token": "tok"}
        mgr.is_token_expired.return_value = False
        mock_mgr_fn.return_value = mgr

        res = client.post("/sync", json={"url": "https://www.beatport.com/chart/test/123"})
        assert res.status_code == 200
        data = res.json()
        assert "job_id" in data
        assert data["url_type"] == "chart"

    @patch("djsupport.web._run_sync")
    @patch("djsupport.web._auth_manager")
    def test_sync_detects_label_url(self, mock_mgr_fn, mock_run):
        mgr = MagicMock()
        mgr.get_cached_token.return_value = {"access_token": "tok"}
        mgr.is_token_expired.return_value = False
        mock_mgr_fn.return_value = mgr

        res = client.post("/sync", json={"url": "https://www.beatport.com/label/test/1"})
        assert res.status_code == 200
        assert res.json()["url_type"] == "label"

    @patch("djsupport.web._run_sync")
    @patch("djsupport.web._auth_manager")
    def test_sync_409_on_concurrent(self, mock_mgr_fn, mock_run):
        mgr = MagicMock()
        mgr.get_cached_token.return_value = {"access_token": "tok"}
        mgr.is_token_expired.return_value = False
        mock_mgr_fn.return_value = mgr

        # Start first job
        res1 = client.post("/sync", json={"url": "https://www.beatport.com/chart/test/123"})
        assert res1.status_code == 200

        # Second job should be rejected
        res2 = client.post("/sync", json={"url": "https://www.beatport.com/chart/test/456"})
        assert res2.status_code == 409

    def test_result_404_unknown_job(self):
        res = client.get("/sync/nonexistent/result")
        assert res.status_code == 404

    def test_result_202_while_running(self):
        import djsupport.web as web_mod
        job = SyncJob("test123", "https://example.com")
        job.done = False
        web_mod._current_job = job

        res = client.get("/sync/test123/result")
        assert res.status_code == 202

    def test_result_returns_data_when_done(self):
        import djsupport.web as web_mod
        job = SyncJob("test456", "https://example.com")
        job.done = True
        job.result = {"playlists": [], "total_matched": 5}
        web_mod._current_job = job

        res = client.get("/sync/test456/result")
        assert res.status_code == 200
        assert res.json()["total_matched"] == 5

    def test_result_returns_error_when_failed(self):
        import djsupport.web as web_mod
        job = SyncJob("test789", "https://example.com")
        job.done = True
        job.error = "Rate limit exceeded"
        web_mod._current_job = job

        res = client.get("/sync/test789/result")
        assert res.status_code == 200
        assert res.json()["error"] == "Rate limit exceeded"


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
        assert "text/html" in res.headers["content-type"]
