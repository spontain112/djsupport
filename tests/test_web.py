"""Tests for the FastAPI web backend."""

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from djsupport.report import PlaylistReport, SyncReport
from djsupport.readiness import FirstTransferReadiness
from djsupport.rekordbox import Track
from djsupport.local_audition import LocalSourceAudition
from djsupport.transfer import (
    AccountPublishingGuards,
    BatchPlan,
    BatchPlanRequest,
    EphemeralMatchingKnowledge,
    FilePublicationStorage,
    FileTransferStorage,
    PlaylistPreflight,
    QualificationDecision,
    QualificationItem,
    QualificationRequest,
    QualificationStatus,
    QualificationView,
    SourceSelection,
    Transfer,
    TransferAuthorization,
    TransferProgress,
    TransferMode,
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


def test_first_transfer_web_route_is_a_thin_agent_contract_rendering():
    transfer = MagicMock()
    transfer.local_audio_capability.return_value = MagicMock(
        available=False,
    )
    web = create_app(
        rekordbox_transfer_factory=lambda request, authorized: transfer,
        first_transfer_readiness=lambda path, authorized: FirstTransferReadiness(
            True, True, True, True, path,
        ),
    )

    response = TestClient(web).post("/rekordbox/first-transfer", json={
        "xml_path": "/private/library.xml",
        "playlist_reference": "Private/Selection",
    })

    assert response.status_code == 200
    assert response.json() == {
        "contract_version": 2,
        "phase": "first_rekordbox_transfer",
        "status": "decision_required",
        "next_action": "choose_local_audio_identity",
        "required_input": {"kind": "boolean", "default": False},
        "local_audio_identity": {
            "available": False,
            "scope": "selected_tracks_only",
            "uploads": "none",
            "file_changes": "none",
            "first_run_spotify_search_reduction": False,
            "future_reuse": "exact_approved_match_after_approval",
            "approval_authority": "none",
            "audition": "separate",
        },
    }
    assert "Private/Selection" not in response.text


def test_first_transfer_web_route_ignores_caller_asserted_readiness():
    transfer = MagicMock()
    web = create_app(
        rekordbox_transfer_factory=lambda request, authorized: transfer,
        first_transfer_readiness=lambda path, authorized: FirstTransferReadiness(
            False, False, False, False, None,
        ),
    )

    response = TestClient(web).post("/rekordbox/first-transfer", json={
        "spotify_configured": True,
        "spotify_authenticated": True,
        "rekordbox_configured": True,
        "rekordbox_available": True,
        "playlist_reference": "Private/Selection",
    })

    assert response.json()["next_action"] == "configure_spotify"
    transfer.assert_not_called()


def test_first_transfer_web_route_forwards_only_explicit_authority():
    transfer = MagicMock()
    transfer.authorization_requirement.side_effect = (
        lambda request, authorization, phase: Transfer.authorization_requirement(
            request, authorization, phase=phase,
        )
    )
    transfer.plan_batch.return_value = BatchPlan((PlaylistPreflight(
        name="Private Selection",
        reference="Private/Selection",
        total_tracks=2,
        approved_match_hits=1,
        cache_hits=0,
        expected_uncached_lookups=1,
        selection_token="opaque",
    ),), preview=True)
    calls = []

    def factory(request, authorized):
        calls.append((request, authorized))
        return transfer

    web = create_app(
        rekordbox_transfer_factory=factory,
        first_transfer_readiness=lambda path, authorized: FirstTransferReadiness(
            True, True, True, True, path,
        ),
    )
    response = TestClient(web).post("/rekordbox/first-transfer", json={
        "xml_path": "/private/library.xml",
        "playlist_reference": "Private/Selection",
        "local_audio_identity": False,
        "authorize_private_source": True,
    })

    assert response.status_code == 200
    assert response.json()["next_action"] == "preview"
    assert calls[0][0].whole_library is False
    assert calls[0][0].playlists == ["Private/Selection"]
    assert calls[0][0].authorize_private_source is True
    assert calls[0][0].authorize_spotify_write is False
    assert calls[0][1] is False
    assert "Private/Selection" not in response.text


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
        "contract_version": 2,
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
        "contract_version": 2,
        "phase": "execute",
        "status": "error",
        "error": {"code": "spotify_authentication_required"},
        "next_actions": ["authenticate_spotify"],
    }


def test_capabilities_are_available_without_spotify_or_private_source(monkeypatch):
    monkeypatch.setattr("djsupport.local_audio.shutil.which", lambda name: None)

    response = TestClient(create_app()).get("/capabilities")

    assert response.status_code == 200
    assert response.json()["contract_version"] == 2
    assert response.json()["phase"] == "capability"
    assert response.json()["capabilities"]["local_audio_identity"] == {
        "available": False,
        "algorithm": "chromaprint",
        "algorithm_version": None,
        "reason": "binary_unavailable",
        "default_enabled": False,
        "authority": "approved_match_reuse_only",
        "first_run_discovery": "none_until_explicit_approval",
        "execution_order": "after_retained_knowledge_before_spotify_search",
    }
    assert response.json()["capabilities"]["local_audio_audition"] == {
        "available": True,
        "default_enabled": False,
        "authority": "none",
        "requires_local_audio_identity": False,
        "requires_durable_matching_knowledge": False,
    }


def _qualification_view() -> QualificationView:
    return QualificationView(
        draft_id="draft-opaque-1",
        transfer_id="transfer-opaque-1",
        source_reference="Private/Selection",
        spotify_playlist_id="playlist-opaque-1",
        status=QualificationStatus.DRAFT,
        items=(QualificationItem(
            item_id="item-opaque-1",
            source_index=0,
            source_track_id="source-opaque-1",
            source_artist="Source Artist",
            source_title="Source Title",
            source_release="Source Release",
            source_label="Source Label",
            source_version="Extended Mix",
            source_duration=380,
            spotify_uri="spotify:track:0123456789012345678901",
            spotify_name="Spotify Title",
            spotify_artist="Spotify Artist",
            spotify_release="Spotify Release",
            spotify_duration=250,
            score=86.0,
            match_type="shorter_version",
            score_reasons=("title", "artist"),
            attention_reasons=("new_proposal", "duration_conflict"),
            audition_status="available",
            permitted_actions=(
                QualificationDecision.KEEP_PROPOSAL,
                QualificationDecision.CORRECTION,
                QualificationDecision.DEFERRED,
                QualificationDecision.REJECT_PROPOSAL,
            ),
        ),),
    )


def _authenticated_manager():
    manager = MagicMock()
    manager.get_cached_token.return_value = {"access_token": "synthetic"}
    manager.is_token_expired.return_value = False
    return manager


def test_rekordbox_qualification_routes_render_rich_path_free_review_facts():
    transfer = MagicMock()
    transfer.obtain_qualification.return_value = _qualification_view()
    transfer.qualification.return_value = _qualification_view()
    web = create_app(
        rekordbox_transfer_factory=lambda request, authorized: transfer,
        auth_manager=_authenticated_manager,
    )

    response = TestClient(web).post("/rekordbox/qualification/drafts", json={
        "xml_path": "/private/owner-library.xml",
        "transfer_id": "batch-opaque-1",
        "playlist_reference": "Private/Selection",
        "local_audio_audition": True,
        "authorize_private_source": True,
    })

    assert response.status_code == 200
    body = response.json()
    assert body["draft_id"] == "draft-opaque-1"
    assert body["authority"] == "none"
    assert body["counts"] == {"items": 1, "pending": 1, "deferred": 0}
    assert body["current_item_id"] == "item-opaque-1"
    assert body["items"][0] == {
        "item_id": "item-opaque-1",
        "source": {
            "artist": "Source Artist",
            "title": "Source Title",
            "release": "Source Release",
            "label": "Source Label",
            "version": "Extended Mix",
            "duration": 380,
        },
        "spotify": {
            "uri": "spotify:track:0123456789012345678901",
            "name": "Spotify Title",
            "artist": "Spotify Artist",
            "release": "Spotify Release",
            "duration": 250,
            "embed_url": "https://open.spotify.com/embed/track/0123456789012345678901",
            "open_url": "https://open.spotify.com/track/0123456789012345678901",
        },
        "proposal": {
            "score": 86.0,
            "match_type": "shorter_version",
            "score_reasons": ["title", "artist"],
            "authority_status": "proposal",
            "attention_reasons": ["new_proposal", "duration_conflict"],
            "availability_status": "unknown",
            "availability_reason": "not_checked",
            "availability_checked_at": None,
            "availability_source": None,
        },
        "permitted_actions": [
            "keep_proposal", "correction", "deferred", "reject_proposal",
        ],
        "audition_status": "available",
        "audition_reason": None,
        "decision": None,
        "correction_uri": None,
        "deferred_reason": None,
        "excluded": False,
    }
    assert "owner-library" not in response.text
    transfer.obtain_qualification.assert_called_once()


def test_qualification_decision_delegates_to_transfer_without_approval():
    transfer = MagicMock()
    transfer.obtain_qualification.return_value = _qualification_view()
    decided = _qualification_view()
    transfer.record_qualification.return_value = decided
    web = create_app(
        rekordbox_transfer_factory=lambda request, authorized: transfer,
        auth_manager=_authenticated_manager,
    )
    client = TestClient(web)
    created = client.post("/rekordbox/qualification/drafts", json={
        "xml_path": "/private/owner-library.xml",
        "transfer_id": "batch-opaque-1",
        "playlist_reference": "Private/Selection",
        "authorize_private_source": True,
    })

    response = client.post(
        f"/rekordbox/qualification/drafts/{created.json()['draft_id']}/decisions",
        json={
            "item_id": "item-opaque-1",
            "decision": "keep_proposal",
            "authorize_private_source": True,
        },
    )

    assert response.status_code == 200
    transfer.record_qualification.assert_called_once_with(
        "draft-opaque-1",
        "item-opaque-1",
        QualificationDecision.KEEP_PROPOSAL,
        TransferAuthorization(private_source=True),
        spotify_reference=None,
        reason=None,
        exclude=False,
    )
    assert not transfer.approve.called


def test_workspace_can_explicitly_include_all_proposals_through_transfer():
    transfer = MagicMock()
    initial = _qualification_view()
    included = replace(initial, include_all=True)
    transfer.obtain_qualification.side_effect = [initial, included]
    web = create_app(
        rekordbox_transfer_factory=lambda request, authorized: transfer,
        auth_manager=_authenticated_manager,
    )
    client = TestClient(web)
    created = client.post("/rekordbox/qualification/drafts", json={
        "xml_path": "/private/owner-library.xml",
        "transfer_id": "batch-opaque-1",
        "playlist_reference": "Private/Selection",
        "authorize_private_source": True,
    })

    response = client.post(
        f"/rekordbox/qualification/drafts/{created.json()['draft_id']}"
        "/include-all",
        json={"authorize_private_source": True},
    )

    assert response.status_code == 200
    assert response.json()["include_all"] is True
    request = transfer.obtain_qualification.call_args_list[-1].args[0]
    assert request.transfer_id == "batch-opaque-1"
    assert request.playlist_reference == "Private/Selection"
    assert request.include_all is True


def test_web_qualification_approval_is_explicit_without_spotify_write_flag():
    transfer = MagicMock()
    transfer.obtain_qualification.return_value = _qualification_view()
    transfer.approve_qualification.return_value = MagicMock(
        status=MagicMock(value="approved"),
        approved=(), rejected=(), collisions=(), corrections=(),
    )
    web = create_app(
        rekordbox_transfer_factory=lambda request, authorized: transfer,
        auth_manager=_authenticated_manager,
    )
    client = TestClient(web)
    created = client.post("/rekordbox/qualification/drafts", json={
        "xml_path": "/private/owner-library.xml",
        "transfer_id": "batch-opaque-1",
        "playlist_reference": "Private/Selection",
        "authorize_private_source": True,
    })

    response = client.post(
        f"/rekordbox/qualification/drafts/{created.json()['draft_id']}/approve",
        json={"authorize_private_source": True},
    )

    assert response.status_code == 200
    assert response.json()["authority"] == "playlist_approval"
    transfer.approve_qualification.assert_called_once_with(
        "draft-opaque-1", TransferAuthorization(private_source=True),
    )


def test_qualification_audition_requires_exact_authorization_and_returns_url():
    transfer = MagicMock()
    transfer.obtain_qualification.return_value = _qualification_view()
    transfer.audition_qualification.return_value = MagicMock(
        status="available", handle="opaque-media-handle", media_type="audio/mpeg",
        content_length=8, expires_in=600, reason=None,
    )
    web = create_app(
        rekordbox_transfer_factory=lambda request, authorized: transfer,
        auth_manager=_authenticated_manager,
    )
    client = TestClient(web)
    created = client.post("/rekordbox/qualification/drafts", json={
        "xml_path": "/private/owner-library.xml",
        "transfer_id": "batch-opaque-1",
        "playlist_reference": "Private/Selection",
        "local_audio_audition": True,
        "authorize_private_source": True,
    })
    url = (
        f"/rekordbox/qualification/drafts/{created.json()['draft_id']}"
        "/audition/item-opaque-1"
    )

    denied = client.post(url, json={"authorize_private_source": False})
    allowed = client.post(url, json={"authorize_private_source": True})

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json() == {
        "status": "available",
        "media_type": "audio/mpeg",
        "content_length": 8,
        "expires_in": 600,
        "media_url": "/rekordbox/qualification/media/opaque-media-handle",
    }
    assert "/private/" not in allowed.text
    transfer.audition_qualification.assert_called_once()


def test_local_media_route_supports_bounded_ranges_without_filename(tmp_path):
    media = tmp_path / "private-owner-name.mp3"
    media.write_bytes(b"0123456789")
    audition = LocalSourceAudition(max_range_bytes=4)
    opened = audition.open("transfer-1", "item-1", Track(
        track_id="1", name="Synthetic", artist="Artist", album="", remixer="",
        label="", genre="", date_added="", location=media.as_uri(),
    ))
    web = create_app(local_audition=audition)
    client = TestClient(web)
    url = f"/rekordbox/qualification/media/{opened.handle}"

    response = client.get(url, headers={"Range": "bytes=2-5"})
    excessive = client.get(url, headers={"Range": "bytes=0-8"})
    missing = client.get("/rekordbox/qualification/media/not-a-handle")

    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-security-policy"] == "default-src 'none'; media-src 'self'"
    assert "content-disposition" not in response.headers
    assert "private-owner-name" not in str(response.headers)
    assert excessive.status_code == 416
    assert excessive.headers["content-range"] == "bytes */10"
    assert missing.status_code == 404
    for denied in (excessive, missing):
        assert denied.headers["cache-control"] == "private, no-store"
        assert denied.headers["content-security-policy"] == (
            "default-src 'none'; media-src 'self'"
        )
        assert denied.headers["x-content-type-options"] == "nosniff"
        assert "private-owner-name" not in str(denied.headers)


def test_qualification_routes_reject_remote_peer_rebinding_host_and_origin():
    web = create_app()
    remote = TestClient(
        web,
        base_url="http://127.0.0.1",
        client=("203.0.113.20", 50000),
    )
    local = TestClient(web)

    assert remote.get("/qualification/opaque-draft").status_code == 403
    assert local.get(
        "/qualification/opaque-draft",
        headers={"Host": "attacker.example"},
    ).status_code == 403
    assert local.post(
        "/rekordbox/qualification/drafts",
        headers={"Origin": "https://attacker.example"},
        json={},
    ).status_code == 403


def test_durable_draft_with_missing_source_is_review_required_not_missing(
    tmp_path, monkeypatch,
):
    class SelectedSource:
        source_label = "Rekordbox"
        default_mode = TransferMode.MIRROR

        def consume(self, reference):
            return SourceSelection("Selected", reference, [Track(
                track_id="synthetic", name="Synthetic", artist="Artist",
                album="Release", remixer="", label="Label", genre="",
                date_added="", duration=180,
            )])

        def consume_batch(self, references, whole_library):
            return tuple(self.consume(reference) for reference in references)

    class PreviewSpotify:
        def account_id(self):
            return "spotify-account-one"

        def match(self, track, threshold):
            return {
                "uri": "spotify:track:0123456789012345678901",
                "name": "Synthetic", "artist": "Artist", "score": 96.0,
                "match_type": "exact",
            }

    publication_path = tmp_path / "publication-manifests.json"
    transfer = Transfer(
        source=SelectedSource(),
        spotify=PreviewSpotify(),
        matching_knowledge=EphemeralMatchingKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        transfer_storage=FileTransferStorage(
            publication_path.with_suffix(".transfers.json")
        ),
    )
    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Selected",), preview=True,
    ))
    report = transfer.execute_batch(plan, transfer_id=plan.batch_id)
    draft = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    )
    monkeypatch.setattr(
        "djsupport.web.default_publication_manifest_path",
        lambda: publication_path,
    )
    monkeypatch.setattr(
        "djsupport.config.ConfigManager.get_rekordbox_xml_path",
        lambda self: str(tmp_path / "missing-source.xml"),
    )
    web = create_app(auth_manager=_authenticated_manager)

    response = TestClient(web).get(
        f"/rekordbox/qualification/drafts/{draft.draft_id}",
        params={"authorize_private_source": "true"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Qualification source evidence is unavailable; review required"
    )
    assert "missing-source" not in response.text


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

    def test_qualification_workspace_is_public_responsive_and_one_action_at_a_time(self):
        res = client.get("/qualification/synthetic-draft")

        assert res.status_code == 200
        assert "classification: public" in res.text
        assert 'id="qualification-section"' in res.text
        assert 'class="qualification-grid"' in res.text
        assert 'id="local-player"' in res.text
        assert 'id="spotify-player"' in res.text
        assert "OPEN IN SPOTIFY" in res.text
        assert ">CORRECT<" in res.text
        assert "WRONG — FIND ANOTHER" in res.text
        assert "CANNOT VERIFY" in res.text
        assert "NOT MY SOURCE" in res.text
        assert "@media (max-width: 980px)" in res.text
        assert "grid-auto-flow: column" in res.text
        assert "authorization mode" not in res.text.casefold()
        assert "test scenario" not in res.text.casefold()
