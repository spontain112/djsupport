"""Versioned, harness-neutral contract tests for AI agent clients."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from djsupport.cache import MatchCache
from djsupport.agent import (
    AgentAuthorization,
    AgentTransferContract,
    FirstTransferGuideRequest,
    error_document,
)
from djsupport.local_audio import LocalAudioCapability
from djsupport.local_audition import LocalAuditionCapability
from djsupport.rekordbox import Track
from djsupport.transfer import (
    AccountPublishingGuards,
    BatchPlanRequest,
    FilePublicationStorage,
    FileTransferStorage,
    LocalAudioObservation,
    MatchCacheKnowledge,
    QualificationDecision,
    QualificationDraftState,
    QualificationRequest,
    QualificationStatus,
    SourceSelection,
    SpotifyPlaylistReviewRequired,
    Transfer,
)


class UntouchedSource:
    source_label = "Rekordbox"

    def __init__(self) -> None:
        self.calls = 0

    def consume(self, reference):
        self.calls += 1
        raise AssertionError("capability inspection must not read the source")


@pytest.mark.parametrize(
    ("guide_request", "next_action", "required_input"),
    (
        (
            FirstTransferGuideRequest(),
            "configure_spotify",
            {
                "kind": "spotify_configuration",
                "redirect_uri": "http://127.0.0.1:8888/callback",
                "callback_policy": "add_without_replacing_existing",
            },
        ),
        (
            FirstTransferGuideRequest(spotify_configured=True),
            "authenticate_spotify",
            {"kind": "spotify_authentication"},
        ),
        (
            FirstTransferGuideRequest(
                spotify_configured=True,
                spotify_authenticated=True,
            ),
            "select_rekordbox_xml",
            {"kind": "rekordbox_xml", "selection": "exact_file"},
        ),
        (
            FirstTransferGuideRequest(
                spotify_configured=True,
                spotify_authenticated=True,
                rekordbox_configured=True,
                rekordbox_available=False,
            ),
            "repair_rekordbox_xml",
            {"kind": "rekordbox_xml", "selection": "exact_file"},
        ),
    ),
)
def test_first_transfer_readiness_returns_one_privacy_safe_next_action(
    guide_request, next_action, required_input,
):
    transfer = MagicMock()
    contract = AgentTransferContract(transfer)

    document = contract.first_rekordbox_transfer(
        guide_request, AgentAuthorization(),
    )

    assert document == {
        "contract_version": 2,
        "phase": "first_rekordbox_transfer",
        "status": "input_required",
        "next_action": next_action,
        "required_input": required_input,
    }
    transfer.assert_not_called()
    rendered = json.dumps(document)
    for private_value in (
        "client_secret", "access_token", "account_id", "playlist_name",
        "track_name", "source_path", "fingerprint",
    ):
        assert private_value not in rendered


def test_first_transfer_asks_for_one_bounded_playlist_after_setup():
    transfer = MagicMock()
    contract = AgentTransferContract(transfer)
    guide_request = FirstTransferGuideRequest(
        spotify_configured=True,
        spotify_authenticated=True,
        rekordbox_configured=True,
        rekordbox_available=True,
    )

    document = contract.first_rekordbox_transfer(
        guide_request, AgentAuthorization(),
    )

    assert document == {
        "contract_version": 2,
        "phase": "first_rekordbox_transfer",
        "status": "input_required",
        "next_action": "select_playlist",
        "required_input": {
            "kind": "rekordbox_playlist",
            "selection": "one_explicit_playlist",
            "whole_library": False,
        },
    }
    transfer.assert_not_called()


def test_first_transfer_explains_local_identity_before_an_explicit_choice():
    transfer = MagicMock()
    transfer.local_audio_capability.return_value = LocalAudioCapability(
        available=True,
        algorithm="chromaprint",
        algorithm_version="1.6.1",
    )
    contract = AgentTransferContract(transfer)
    guide_request = FirstTransferGuideRequest(
        spotify_configured=True,
        spotify_authenticated=True,
        rekordbox_configured=True,
        rekordbox_available=True,
        playlist_reference="Private/Selection",
    )

    document = contract.first_rekordbox_transfer(
        guide_request, AgentAuthorization(),
    )

    assert document == {
        "contract_version": 2,
        "phase": "first_rekordbox_transfer",
        "status": "decision_required",
        "next_action": "choose_local_audio_identity",
        "required_input": {
            "kind": "boolean",
            "default": False,
        },
        "local_audio_identity": {
            "available": True,
            "scope": "selected_tracks_only",
            "uploads": "none",
            "file_changes": "none",
            "first_run_spotify_search_reduction": False,
            "future_reuse": "exact_approved_match_after_approval",
            "approval_authority": "none",
            "audition": "separate",
        },
    }
    transfer.local_audio_capability.assert_called_once_with()


def test_first_transfer_cannot_enable_unavailable_local_identity():
    transfer = MagicMock()
    transfer.local_audio_capability.return_value = LocalAudioCapability(
        available=False,
        algorithm="chromaprint",
        algorithm_version=None,
        reason="binary_unavailable",
    )
    contract = AgentTransferContract(transfer)

    document = contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(
            spotify_configured=True,
            spotify_authenticated=True,
            rekordbox_configured=True,
            rekordbox_available=True,
            playlist_reference="Private/Selection",
            local_audio_identity=True,
        ),
        AgentAuthorization(private_source=True),
    )

    assert document == {
        "contract_version": 2,
        "phase": "first_rekordbox_transfer",
        "status": "decision_required",
        "next_action": "continue_without_local_audio_identity",
        "required_input": {"kind": "boolean", "value": False},
        "reason": {"code": "local_audio_identity_unavailable"},
    }
    transfer.plan_batch.assert_not_called()


def test_first_transfer_requires_private_source_authority_before_planning():
    transfer = MagicMock()
    contract = AgentTransferContract(transfer)
    guide_request = FirstTransferGuideRequest(
        spotify_configured=True,
        spotify_authenticated=True,
        rekordbox_configured=True,
        rekordbox_available=True,
        playlist_reference="Private/Selection",
        local_audio_identity=False,
    )

    document = contract.first_rekordbox_transfer(
        guide_request, AgentAuthorization(),
    )

    assert document == {
        "contract_version": 2,
        "phase": "first_rekordbox_transfer",
        "status": "authorization_required",
        "next_action": "authorize_private_source",
        "required_authorization": "private_source",
    }
    transfer.plan_batch.assert_not_called()


def test_machine_error_next_actions_are_specific_to_the_failure():
    assert error_document(
        "plan", "durable_knowledge_required",
    )["next_actions"] == ["enable_durable_knowledge"]
    assert error_document(
        "plan", "matching_knowledge_unavailable",
    )["next_actions"] == ["repair_matching_knowledge"]
    assert error_document(
        "execute", "transfer_failed",
    )["next_actions"] == ["inspect_transfer_status"]
    assert error_document(
        "execute", "spotify_authentication_required",
    )["next_actions"] == ["authenticate_spotify"]


def test_qualification_approval_is_explicit_without_spotify_write_authority():
    transfer = MagicMock()
    transfer.private_source_authorization_requirement.side_effect = (
        Transfer.private_source_authorization_requirement
    )
    transfer.approve_qualification.return_value = SimpleNamespace(
        status=SimpleNamespace(value="approved"),
        approved_count=0, rejected_count=0, collision_count=0,
        correction_count=0,
    )
    contract = AgentTransferContract(transfer)
    authorization = AgentAuthorization(private_source=True)

    document = contract.approve_qualification("opaque-draft", authorization)

    assert document["status"] == "approved"
    assert document["authority"] == "playlist_approval"
    transfer.approve_qualification.assert_called_once_with(
        "opaque-draft", authorization,
    )


class UntouchedSpotify:
    def __init__(self) -> None:
        self.calls = 0

    def account_id(self):
        self.calls += 1
        raise AssertionError("capability inspection must not contact Spotify")


class UntouchedKnowledge:
    persistent = True


class AvailableLocalAudio:
    def capability(self):
        return LocalAudioCapability(
            available=True,
            algorithm="chromaprint",
            algorithm_version="1.6.1",
        )


class FixedGuideLocalAudio(AvailableLocalAudio):
    def preflight(self, track):
        del track
        return "eligible"

    def observe(self, track):
        del track
        return LocalAudioObservation.available(
            fingerprint="synthetic-guide-fingerprint",
            algorithm="chromaprint",
            algorithm_version="1.6.1",
            duration=180,
        )


class AvailableAudition:
    def capability(self):
        return LocalAuditionCapability(available=True)


def test_capability_inspection_is_versioned_and_side_effect_free(tmp_path):
    source = UntouchedSource()
    spotify = UntouchedSpotify()
    contract = AgentTransferContract(Transfer(
        source=source,
        spotify=spotify,
        matching_knowledge=UntouchedKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        local_audio=AvailableLocalAudio(),
        local_audition=AvailableAudition(),
    ))

    result = contract.capabilities()

    assert result == {
        "contract_version": 2,
        "phase": "capability",
        "status": "ready",
        "capabilities": {
            "local_audio_identity": {
                "available": True,
                "algorithm": "chromaprint",
                "algorithm_version": "1.6.1",
                "default_enabled": False,
                "authority": "approved_match_reuse_only",
                "first_run_discovery": "none_until_explicit_approval",
                "execution_order": (
                    "after_retained_knowledge_before_spotify_search"
                ),
            },
            "local_audio_audition": {
                "available": True,
                "default_enabled": False,
                "authority": "none",
                "requires_local_audio_identity": False,
                "requires_durable_matching_knowledge": False,
            },
        },
        "next_actions": ["plan"],
    }
    assert source.calls == 0
    assert spotify.calls == 0


class BoundedSource(UntouchedSource):
    def __init__(self):
        super().__init__()
        self.title = "Invented Signal"

    def selection(self, reference):
        return SourceSelection("Private Playlist", reference, [Track(
            track_id="synthetic-1",
            name=self.title,
            artist="Invented Artist",
            album="",
            remixer="",
            label="",
            genre="",
            date_added="",
            duration=180,
            location="file:///synthetic/selected.wav",
        )])

    def consume(self, reference):
        self.calls += 1
        return self.selection(reference)

    def consume_batch(self, references, whole_library):
        self.calls += 1
        return (self.selection(references[0]),)


class EmptyKnowledge(UntouchedKnowledge):
    def __init__(self):
        self.retained = []

    def lookup(self, track, threshold):
        return None

    def should_retry(self, track, threshold, retry_days, force):
        return True

    def retain(self, track, threshold, result):
        self.retained.append(result)

    def checkpoint(self):
        pass


class FirstTransferKnowledge(EmptyKnowledge):
    def __init__(self):
        super().__init__()
        self.approved = []
        self.rejected = []
        self.corrected = []

    def approve(self, item):
        self.approved.append(item)

    def reject(self, item):
        self.rejected.append(item)

    def correct(self, item):
        self.corrected.append(item)

    def approval_conflict(self, item):
        del item
        return False

    def approve_local_audio(self, item, account_id):
        del item, account_id
        return None


def test_batch_plan_requires_explicit_private_source_authorization(tmp_path):
    source = BoundedSource()
    contract = AgentTransferContract(Transfer(
        source=source,
        spotify=UntouchedSpotify(),
        matching_knowledge=EmptyKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
    ))
    request = BatchPlanRequest(playlist_references=("Private/Selection",))

    blocked = contract.plan_batch(request, AgentAuthorization())

    assert blocked == {
        "contract_version": 2,
        "phase": "plan",
        "status": "authorization_required",
        "required_authorizations": ["private_source"],
        "next_actions": ["authorize_private_source"],
    }
    assert source.calls == 0


@pytest.mark.parametrize("origin", [
    "https://review.example.test",
    "http://127.0.0.1.example.test",
    "http://user@127.0.0.1:8000",
])
def test_qualification_review_url_rejects_non_loopback_origins(origin):
    transfer = MagicMock()
    transfer.private_source_authorization_requirement.return_value = None
    contract = AgentTransferContract(transfer)

    with pytest.raises(ValueError, match="loopback"):
        contract.qualification_draft(
            QualificationRequest(transfer_id="opaque-transfer"),
            AgentAuthorization(private_source=True),
            review_origin=origin,
        )

    transfer.obtain_qualification.assert_not_called()


def test_authorized_plan_is_stable_bounded_and_privacy_redacted(tmp_path):
    source = BoundedSource()
    contract = AgentTransferContract(Transfer(
        source=source,
        spotify=UntouchedSpotify(),
        matching_knowledge=EmptyKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
    ))
    request = BatchPlanRequest(playlist_references=("Private/Selection",))
    authorization = AgentAuthorization(private_source=True)

    first = contract.plan_batch(request, authorization)
    second = contract.plan_batch(request, authorization)

    assert first == second
    assert first["contract_version"] == 2
    assert first["phase"] == "plan"
    assert first["status"] == "ready"
    assert len(first["batch_id"]) == 64
    assert first["counts"] == {
        "playlists": 1,
        "tracks": 1,
        "approved_match_hits": 0,
        "retained_proposal_hits": 0,
        "expected_spotify_lookups": 1,
        "local_audio_eligible": 0,
        "local_audio_indexed": 0,
        "local_audio_pending": 0,
        "local_audio_unavailable": 0,
    }
    assert first["required_authorizations"] == ["spotify_write"]
    assert first["next_actions"] == ["authorize_spotify_write", "execute"]
    rendered = json.dumps(first)
    assert "Private" not in rendered
    assert "Invented" not in rendered
    assert first["local_audio"] == {
        "identity_requested": False,
        "audition_requested": False,
        "identity_default_enabled": False,
        "identity_first_run_discovery": "none_until_explicit_approval",
        "identity_execution_order": (
            "after_retained_knowledge_before_spotify_search"
        ),
        "audition_requires_identity": False,
    }


def test_expensive_confirmation_does_not_change_batch_identity(tmp_path):
    contract = AgentTransferContract(Transfer(
        source=BoundedSource(),
        spotify=UntouchedSpotify(),
        matching_knowledge=EmptyKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
    ))
    authorization = AgentAuthorization(private_source=True)

    before = contract.plan_batch(BatchPlanRequest(
        playlist_references=("Private/Selection",),
    ), authorization)
    confirmed = contract.plan_batch(BatchPlanRequest(
        playlist_references=("Private/Selection",),
        confirm_expensive=True,
    ), authorization)

    assert before["batch_id"] == confirmed["batch_id"]


def test_source_content_change_creates_a_new_bounded_batch_identity(tmp_path):
    source = BoundedSource()
    contract = AgentTransferContract(Transfer(
        source=source,
        spotify=UntouchedSpotify(),
        matching_knowledge=EmptyKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
    ))
    request = BatchPlanRequest(playlist_references=("Private/Selection",))
    authorization = AgentAuthorization(private_source=True)

    before = contract.plan_batch(request, authorization)
    source.title = "Changed Source Content"
    after = contract.plan_batch(request, authorization)

    assert before["batch_id"] != after["batch_id"]


def test_private_read_authorization_does_not_authorize_spotify_mutation(tmp_path):
    source = BoundedSource()
    spotify = UntouchedSpotify()
    contract = AgentTransferContract(Transfer(
        source=source,
        spotify=spotify,
        matching_knowledge=EmptyKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
    ))
    request = BatchPlanRequest(playlist_references=("Private/Selection",))

    blocked = contract.execute_batch(
        request, AgentAuthorization(private_source=True),
    )

    assert blocked["contract_version"] == 2
    assert blocked["phase"] == "execute"
    assert blocked["status"] == "authorization_required"
    assert blocked["required_authorizations"] == ["spotify_write"]
    assert blocked["next_actions"] == ["authorize_spotify_write"]
    assert spotify.calls == 0


class PreviewSpotify:
    def __init__(self):
        self.searches = 0

    def account_id(self):
        return "spotify-account-one"

    def match(self, track, threshold):
        self.searches += 1
        return {
            "uri": "spotify:track:synthetic",
            "name": "Invented Signal",
            "artist": "Invented Artist",
            "score": 96.0,
            "match_type": "exact",
        }


class FirstTransferSpotify(PreviewSpotify):
    def __init__(self):
        super().__init__()
        self.playlists = {}
        self.heads = {}
        self.playlist_writes = 0
        self.description_writes = 0

    def create_playlist(self, name, description):
        del name, description
        self.playlists["provisional-one"] = []
        self.heads["provisional-one"] = "head-0"
        return "provisional-one"

    def find_recovery_playlist(self, publication_key):
        del publication_key
        return None

    def replace_items(self, playlist_id, uris):
        self.playlist_writes += 1
        self.playlists[playlist_id] = list(uris)
        head = f"head-{self.playlist_writes}"
        self.heads[playlist_id] = head
        return SimpleNamespace(snapshot_id=head)

    def add_items(self, playlist_id, uris):
        return self.replace_items(
            playlist_id, [*self.playlists[playlist_id], *uris],
        )

    def playlist_head(self, playlist_id):
        return SimpleNamespace(snapshot_id=self.heads[playlist_id])

    def ordered_playlist_items(self, playlist_id):
        from djsupport.transfer import (
            SpotifyItemKind,
            SpotifyPlaylistItem,
            SpotifyPlaylistPage,
        )

        return SpotifyPlaylistPage(tuple(
            SpotifyPlaylistItem(index, SpotifyItemKind.TRACK, uri)
            for index, uri in enumerate(self.playlists[playlist_id])
        ))

    def set_playlist_description(self, playlist_id, description):
        del playlist_id, description
        self.description_writes += 1

    def provisional_playlist_track_uris(self, playlist_id):
        return list(self.playlists[playlist_id])

    def replace_provisional_playlist_tracks(self, playlist_id, uris):
        return self.replace_items(playlist_id, uris)

    def spotify_track(self, uri):
        return {
            "uri": uri,
            "name": "Invented Signal",
            "artist": "Invented Artist",
            "album": "Invented Release",
            "duration_ms": 180_000,
            "is_playable": True,
        }


def test_first_transfer_returns_transfer_owned_preview_plan():
    spotify = PreviewSpotify()
    contract = AgentTransferContract(Transfer(
        source=BoundedSource(),
        spotify=spotify,
        matching_knowledge=EmptyKnowledge(),
        publishing_guards=AccountPublishingGuards(),
    ))
    guide_request = FirstTransferGuideRequest(
        spotify_configured=True,
        spotify_authenticated=True,
        rekordbox_configured=True,
        rekordbox_available=True,
        playlist_reference="Private/Selection",
        local_audio_identity=False,
    )

    document = contract.first_rekordbox_transfer(
        guide_request, AgentAuthorization(private_source=True),
    )

    assert document["contract_version"] == 2
    assert document["phase"] == "first_rekordbox_transfer"
    assert document["status"] == "ready"
    assert document["next_action"] == "preview"
    assert document["required_input"] == {
        "kind": "action_confirmation", "action": "preview",
    }
    assert document["counts"] == {
        "playlists": 1,
        "tracks": 1,
        "approved_match_hits": 0,
        "retained_proposal_hits": 0,
        "expected_spotify_lookups": 1,
        "local_audio_eligible": 0,
        "local_audio_indexed": 0,
        "local_audio_pending": 0,
        "local_audio_unavailable": 0,
    }
    assert "next_actions" not in document
    assert spotify.searches == 0
    rendered = json.dumps(document)
    assert "Private" not in rendered
    assert "Invented" not in rendered


def test_first_transfer_preview_is_explicit_and_idempotent(tmp_path):
    spotify = PreviewSpotify()
    contract = AgentTransferContract(Transfer(
        source=BoundedSource(),
        spotify=spotify,
        matching_knowledge=EmptyKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
    ))
    guide_request = FirstTransferGuideRequest(
        spotify_configured=True,
        spotify_authenticated=True,
        rekordbox_configured=True,
        rekordbox_available=True,
        playlist_reference="Private/Selection",
        local_audio_identity=False,
        action="preview",
    )
    authorization = AgentAuthorization(private_source=True)

    first = contract.first_rekordbox_transfer(guide_request, authorization)
    repeated = contract.first_rekordbox_transfer(guide_request, authorization)

    assert first == repeated
    assert first["phase"] == "first_rekordbox_transfer"
    assert first["status"] == "completed"
    assert first["next_action"] == "qualify"
    assert first["required_input"] == {
        "kind": "action_confirmation", "action": "qualify",
    }
    assert first["transfer_id"] == first["batch_id"]
    assert "next_actions" not in first
    assert spotify.searches == 1


def test_first_transfer_paused_preview_exposes_resume_not_qualification():
    transfer = MagicMock()
    transfer.authorization_requirement.return_value = None
    transfer.plan_batch.return_value = SimpleNamespace(
        batch_id="opaque-batch",
        ready=True,
    )
    contract = AgentTransferContract(transfer)
    contract.execute_batch = MagicMock(return_value={
        "contract_version": 2,
        "phase": "outcome",
        "status": "paused",
        "transfer_id": "opaque-transfer",
        "next_actions": ["resume"],
    })

    document = contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(
            spotify_configured=True,
            spotify_authenticated=True,
            rekordbox_configured=True,
            rekordbox_available=True,
            playlist_reference="Private/Selection",
            local_audio_identity=False,
            action="preview",
        ),
        AgentAuthorization(private_source=True),
    )

    assert document["next_action"] == "resume"
    assert document["required_input"] == {
        "kind": "action_confirmation", "action": "resume",
    }


def test_first_transfer_resume_reuses_the_exact_transfer_identity():
    transfer = MagicMock()
    contract = AgentTransferContract(transfer)
    contract.execute_batch = MagicMock(return_value={
        "contract_version": 2,
        "phase": "outcome",
        "status": "completed",
        "transfer_id": "opaque-transfer",
        "next_actions": ["qualify"],
    })
    request = FirstTransferGuideRequest(
        spotify_configured=True,
        spotify_authenticated=True,
        rekordbox_configured=True,
        rekordbox_available=True,
        playlist_reference="Private/Selection",
        local_audio_identity=False,
        action="resume",
        transfer_id="opaque-transfer",
    )

    document = contract.first_rekordbox_transfer(
        request, AgentAuthorization(private_source=True),
    )

    _, authorization = contract.execute_batch.call_args.args
    assert authorization.private_source is True
    assert contract.execute_batch.call_args.kwargs == {
        "transfer_id": "opaque-transfer",
    }
    assert document["next_action"] == "qualify"


def test_first_transfer_abandonment_is_explicit_and_terminal():
    transfer = MagicMock()
    contract = AgentTransferContract(transfer)
    request = FirstTransferGuideRequest(
        spotify_configured=True,
        spotify_authenticated=True,
        rekordbox_configured=True,
        rekordbox_available=True,
        playlist_reference="Private/Selection",
        local_audio_identity=False,
        action="abandon",
        transfer_id="opaque-transfer",
    )

    document = contract.first_rekordbox_transfer(
        request, AgentAuthorization(private_source=True),
    )

    assert document == {
        "contract_version": 2,
        "phase": "first_rekordbox_transfer",
        "status": "abandoned",
        "transfer_id": "opaque-transfer",
        "next_action": None,
    }
    transfer.abandon.assert_called_once_with("opaque-transfer")


def test_first_transfer_restart_derives_the_next_action_from_durable_progress():
    transfer = MagicMock()
    contract = AgentTransferContract(transfer)
    contract.progress = MagicMock(return_value={
        "contract_version": 2,
        "phase": "progress",
        "status": "paused",
        "transfer_id": "opaque-transfer",
        "counts": {
            "playlists": 1, "completed": 0, "failed": 0, "pending": 1,
        },
        "next_actions": ["resume"],
    })

    document = contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(
            spotify_configured=True,
            spotify_authenticated=True,
            rekordbox_configured=True,
            rekordbox_available=True,
            playlist_reference="Private/Selection",
            local_audio_identity=False,
            transfer_id="opaque-transfer",
        ),
        AgentAuthorization(private_source=True),
    )

    assert document["phase"] == "first_rekordbox_transfer"
    assert document["next_action"] == "resume"
    assert document["required_input"] == {
        "kind": "action_confirmation", "action": "resume",
    }
    contract.progress.assert_called_once()


def test_first_transfer_rejects_unknown_actions_without_falling_back_to_plan():
    transfer = MagicMock()
    contract = AgentTransferContract(transfer)

    document = contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(
            spotify_configured=True,
            spotify_authenticated=True,
            rekordbox_configured=True,
            rekordbox_available=True,
            playlist_reference="Private/Selection",
            local_audio_identity=False,
            action="invent_authority",
        ),
        AgentAuthorization(private_source=True),
    )

    assert document == {
        "contract_version": 2,
        "phase": "first_rekordbox_transfer",
        "status": "error",
        "error": {"code": "unsupported_action"},
        "next_action": "review_request",
    }
    transfer.plan_batch.assert_not_called()


def test_first_transfer_hands_preview_to_local_qualification(tmp_path):
    spotify = PreviewSpotify()
    contract = AgentTransferContract(Transfer(
        source=BoundedSource(),
        spotify=spotify,
        matching_knowledge=EmptyKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
    ))
    base = dict(
        spotify_configured=True,
        spotify_authenticated=True,
        rekordbox_configured=True,
        rekordbox_available=True,
        playlist_reference="Private/Selection",
        local_audio_identity=False,
    )
    authorization = AgentAuthorization(private_source=True)
    preview = contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(**base, action="preview"), authorization,
    )

    document = contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(
            **base, action="qualify", transfer_id=preview["transfer_id"],
        ),
        authorization,
    )

    assert document["phase"] == "first_rekordbox_transfer"
    assert document["status"] == "draft"
    assert document["authority"] == "none"
    assert document["counts"] == {"items": 1, "pending": 1, "deferred": 0}
    assert document["next_action"] == "review"
    assert document["required_input"] == {
        "kind": "local_qualification_review",
        "review_url": document["review_url"],
    }
    assert document["review_url"].startswith(
        "http://127.0.0.1:8000/qualification/"
    )
    assert "next_actions" not in document
    rendered = json.dumps(document)
    assert "Private" not in rendered
    assert "Invented" not in rendered


def test_completed_preview_qualification_requires_separate_spotify_write(
    tmp_path,
):
    spotify = PreviewSpotify()
    contract = AgentTransferContract(Transfer(
        source=BoundedSource(),
        spotify=spotify,
        matching_knowledge=EmptyKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
    ))
    base = dict(
        spotify_configured=True,
        spotify_authenticated=True,
        rekordbox_configured=True,
        rekordbox_available=True,
        playlist_reference="Private/Selection",
        local_audio_identity=False,
    )
    private_source = AgentAuthorization(private_source=True)
    preview = contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(**base, action="preview"), private_source,
    )
    draft = contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(
            **base, action="qualify", transfer_id=preview["transfer_id"],
        ),
        private_source,
    )
    contract.record_qualification(
        draft["draft_id"], draft["current_item"]["item_id"],
        QualificationDecision.KEEP_PROPOSAL, private_source,
    )

    document = contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(**base, draft_id=draft["draft_id"]),
        private_source,
    )

    assert document == {
        "contract_version": 2,
        "phase": "first_rekordbox_transfer",
        "status": "authorization_required",
        "draft_id": draft["draft_id"],
        "authority": "none",
        "next_action": "authorize_spotify_write",
        "required_authorization": "spotify_write",
    }
    assert spotify.searches == 1


def test_first_transfer_publishes_and_links_without_applying_the_draft(
    tmp_path,
):
    spotify = FirstTransferSpotify()
    contract = AgentTransferContract(Transfer(
        source=BoundedSource(),
        spotify=spotify,
        matching_knowledge=EmptyKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=FilePublicationStorage(tmp_path / "publications.json"),
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
    ))
    base = dict(
        spotify_configured=True,
        spotify_authenticated=True,
        rekordbox_configured=True,
        rekordbox_available=True,
        playlist_reference="Private/Selection",
        local_audio_identity=False,
    )
    private_source = AgentAuthorization(private_source=True)
    preview = contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(**base, action="preview"), private_source,
    )
    draft = contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(
            **base, action="qualify", transfer_id=preview["transfer_id"],
        ),
        private_source,
    )
    contract.record_qualification(
        draft["draft_id"], draft["current_item"]["item_id"],
        QualificationDecision.KEEP_PROPOSAL, private_source,
    )
    publish = FirstTransferGuideRequest(
        **base, action="publish_and_link", draft_id=draft["draft_id"],
    )
    spotify_write = AgentAuthorization(
        private_source=True, spotify_write=True,
    )

    first = contract.first_rekordbox_transfer(publish, spotify_write)
    repeated = contract.first_rekordbox_transfer(publish, spotify_write)

    assert first == repeated
    assert first["status"] == "ready"
    assert first["authority"] == "none"
    assert first["next_action"] == "apply"
    assert first["required_input"] == {
        "kind": "action_confirmation", "action": "apply",
    }
    assert "next_actions" not in first
    assert spotify.playlist_writes == 1


def test_first_transfer_applies_draft_without_creating_approval(tmp_path):
    spotify = FirstTransferSpotify()
    contract = AgentTransferContract(Transfer(
        source=BoundedSource(),
        spotify=spotify,
        matching_knowledge=EmptyKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=FilePublicationStorage(tmp_path / "publications.json"),
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
    ))
    base = dict(
        spotify_configured=True,
        spotify_authenticated=True,
        rekordbox_configured=True,
        rekordbox_available=True,
        playlist_reference="Private/Selection",
        local_audio_identity=False,
    )
    private_source = AgentAuthorization(private_source=True)
    spotify_write = AgentAuthorization(
        private_source=True, spotify_write=True,
    )
    preview = contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(**base, action="preview"), private_source,
    )
    draft = contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(
            **base, action="qualify", transfer_id=preview["transfer_id"],
        ),
        private_source,
    )
    contract.record_qualification(
        draft["draft_id"], draft["current_item"]["item_id"],
        QualificationDecision.KEEP_PROPOSAL, private_source,
    )
    contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(
            **base, action="publish_and_link", draft_id=draft["draft_id"],
        ),
        spotify_write,
    )
    apply = FirstTransferGuideRequest(
        **base, action="apply", draft_id=draft["draft_id"],
    )

    first = contract.first_rekordbox_transfer(apply, spotify_write)
    repeated = contract.first_rekordbox_transfer(apply, spotify_write)

    assert first == repeated
    assert first == {
        "contract_version": 2,
        "phase": "first_rekordbox_transfer",
        "status": "applied",
        "draft_id": draft["draft_id"],
        "counts": {"applied_items": 1},
        "authority": "none",
        "next_action": "approve",
        "required_input": {
            "kind": "authority_confirmation", "authority": "playlist_approval",
        },
    }


def test_first_transfer_approval_is_a_final_explicit_authority_step(tmp_path):
    spotify = FirstTransferSpotify()
    knowledge = FirstTransferKnowledge()
    contract = AgentTransferContract(Transfer(
        source=BoundedSource(),
        spotify=spotify,
        matching_knowledge=knowledge,
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=FilePublicationStorage(tmp_path / "publications.json"),
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
    ))
    base = dict(
        spotify_configured=True,
        spotify_authenticated=True,
        rekordbox_configured=True,
        rekordbox_available=True,
        playlist_reference="Private/Selection",
        local_audio_identity=False,
    )
    private_source = AgentAuthorization(private_source=True)
    spotify_write = AgentAuthorization(
        private_source=True, spotify_write=True,
    )
    preview = contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(**base, action="preview"), private_source,
    )
    draft = contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(
            **base, action="qualify", transfer_id=preview["transfer_id"],
        ),
        private_source,
    )
    contract.record_qualification(
        draft["draft_id"], draft["current_item"]["item_id"],
        QualificationDecision.CORRECTION, private_source,
        spotify_reference="spotify:track:replacement00000000000",
    )
    contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(
            **base, action="publish_and_link", draft_id=draft["draft_id"],
        ),
        spotify_write,
    )
    contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(
            **base, action="apply", draft_id=draft["draft_id"],
        ),
        spotify_write,
    )
    approval = FirstTransferGuideRequest(
        **base, action="approve", draft_id=draft["draft_id"],
    )
    description_writes_before_approval = spotify.description_writes

    first = contract.first_rekordbox_transfer(approval, private_source)
    repeated = contract.first_rekordbox_transfer(approval, private_source)

    assert first == repeated
    assert first == {
        "contract_version": 2,
        "phase": "first_rekordbox_transfer",
        "status": "approved",
        "draft_id": draft["draft_id"],
        "counts": {
            "approved": 1,
            "rejected": 0,
            "collisions": 0,
            "corrections": 1,
        },
        "authority": "playlist_approval",
        "effects": {
            "spotify_writes_during_approval": 0,
            "spotify_playlist_items": 1,
        },
        "retained": {
            "approved_matches": 1,
            "corrections": 1,
            "rejected_matches": 0,
        },
        "next_action": None,
    }
    assert len(knowledge.corrected) == 1
    assert spotify.description_writes == description_writes_before_approval
    writes = spotify.playlist_writes

    terminal_publish = contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(
            **base, action="publish_and_link", draft_id=draft["draft_id"],
        ),
        spotify_write,
    )
    terminal_apply = contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(
            **base, action="apply", draft_id=draft["draft_id"],
        ),
        spotify_write,
    )

    assert terminal_publish["status"] == "approved"
    assert terminal_publish["next_action"] is None
    assert terminal_apply["status"] == "approved"
    assert terminal_apply["next_action"] is None
    assert spotify.playlist_writes == writes


def test_interrupted_approval_never_repeats_matching_authority(tmp_path):
    storage = FileTransferStorage(tmp_path / "transfers.json")
    storage.save_qualification("opaque-draft", QualificationDraftState(
        draft_id="opaque-draft",
        transfer_id="opaque-transfer",
        batch_id=None,
        source_reference="Private/Selection",
        account_id="spotify-account-one",
        playlist_id="provisional-one",
        playlist_head="head-1",
        manifest_digest="opaque-manifest",
        selection_digest="opaque-selection",
        include_all=True,
        item_ids=[],
        decisions={},
        status=QualificationStatus.APPROVING,
        created_at="2026-08-10T00:00:00",
        updated_at="2026-08-10T00:00:00",
    ))
    knowledge = FirstTransferKnowledge()
    transfer = Transfer(
        source=BoundedSource(),
        spotify=FirstTransferSpotify(),
        matching_knowledge=knowledge,
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=FilePublicationStorage(
            tmp_path / "publications.json",
        ),
        transfer_storage=storage,
    )

    with pytest.raises(SpotifyPlaylistReviewRequired, match="interrupted"):
        transfer.approve_qualification(
            "opaque-draft", AgentAuthorization(private_source=True),
        )

    assert knowledge.approved == []


def test_first_transfer_approved_fingerprint_reuses_after_metadata_change(
    tmp_path,
):
    spotify = FirstTransferSpotify()
    cache_path = tmp_path / "matching-knowledge.json"
    source = BoundedSource()
    local_audio = FixedGuideLocalAudio()
    publication_path = tmp_path / "publications.json"
    storage_path = tmp_path / "transfers.json"

    def guide_contract():
        cache = MatchCache(cache_path)
        cache.load()
        return AgentTransferContract(Transfer(
            source=source,
            spotify=spotify,
            matching_knowledge=MatchCacheKnowledge(cache),
            publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
            publication_storage=FilePublicationStorage(publication_path),
            transfer_storage=FileTransferStorage(storage_path),
            local_audio=local_audio,
        ))

    base = dict(
        spotify_configured=True,
        spotify_authenticated=True,
        rekordbox_configured=True,
        rekordbox_available=True,
        playlist_reference="Private/Selection",
        local_audio_identity=True,
    )
    private = AgentAuthorization(private_source=True)
    write = AgentAuthorization(private_source=True, spotify_write=True)
    contract = guide_contract()
    preview = contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(**base, action="preview"), private,
    )
    draft = contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(
            **base, action="qualify", transfer_id=preview["transfer_id"],
        ),
        private,
    )
    contract.record_qualification(
        draft["draft_id"], draft["current_item"]["item_id"],
        QualificationDecision.KEEP_PROPOSAL, private,
    )
    published = contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(
            **base, action="publish_and_link", draft_id=draft["draft_id"],
        ),
        write,
    )
    assert published["next_action"] == "apply", published
    applied = contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(
            **base, action="apply", draft_id=draft["draft_id"],
        ),
        write,
    )
    assert applied["status"] == "applied", applied
    approval = contract.first_rekordbox_transfer(
        FirstTransferGuideRequest(
            **base, action="approve", draft_id=draft["draft_id"],
        ),
        private,
    )
    assert approval["status"] == "approved", json.dumps(approval, sort_keys=True)

    source.title = "Metadata Changed Completely"
    later = guide_contract().first_rekordbox_transfer(
        FirstTransferGuideRequest(**base, action="preview"), private,
    )

    assert later["counts"]["local_audio_reused"] == 1
    assert later["counts"]["spotify_api_lookups"] == 0
    assert spotify.searches == 1


def test_authorized_preview_executes_non_interactively_and_is_idempotent(tmp_path):
    spotify = PreviewSpotify()
    contract = AgentTransferContract(Transfer(
        source=BoundedSource(),
        spotify=spotify,
        matching_knowledge=EmptyKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
    ))
    request = BatchPlanRequest(
        playlist_references=("Private/Selection",), preview=True,
    )
    authorization = AgentAuthorization(private_source=True)

    first = contract.execute_batch(request, authorization)
    repeated = contract.execute_batch(request, authorization)
    progress = contract.progress(first["transfer_id"], authorization)

    assert first == repeated
    assert first["contract_version"] == 2
    assert first["phase"] == "outcome"
    assert first["status"] == "completed"
    assert first["transfer_id"] == first["batch_id"]
    assert first["counts"] == {
        "playlists": 1,
        "matched": 1,
        "unmatched": 0,
        "spotify_api_lookups": 1,
        "local_audio_eligible": 0,
        "local_audio_observed": 0,
        "local_audio_unavailable": 0,
        "local_audio_reused": 0,
    }
    assert first["next_actions"] == ["qualify"]
    assert spotify.searches == 1
    assert progress == {
        "contract_version": 2,
        "phase": "progress",
        "status": "completed",
        "transfer_id": first["transfer_id"],
        "counts": {
            "playlists": 1,
            "completed": 1,
            "failed": 0,
            "pending": 0,
        },
        "next_actions": ["qualify"],
    }
    rendered = json.dumps(first)
    assert "Private" not in rendered
    assert "Invented" not in rendered


def test_resume_rejects_a_request_that_changes_the_original_effect_scope(tmp_path):
    storage = FileTransferStorage(tmp_path / "transfers.json")
    transfer = Transfer(
        source=BoundedSource(),
        spotify=PreviewSpotify(),
        matching_knowledge=EmptyKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=FilePublicationStorage(tmp_path / "publications.json"),
        transfer_storage=storage,
    )
    preview = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Private/Selection",), preview=True,
    ))
    completed = transfer.execute_batch(preview, transfer_id=preview.batch_id)
    publishing = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Private/Selection",), preview=False,
    ))

    with pytest.raises(ValueError, match="original plan"):
        transfer.execute_batch(publishing, transfer_id=completed.transfer_id)
