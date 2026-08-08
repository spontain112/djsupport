"""Versioned, harness-neutral contract tests for AI agent clients."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from djsupport.agent import (
    AgentAuthorization,
    AgentTransferContract,
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
    QualificationRequest,
    SourceSelection,
    Transfer,
)


class UntouchedSource:
    source_label = "Rekordbox"

    def __init__(self) -> None:
        self.calls = 0

    def consume(self, reference):
        self.calls += 1
        raise AssertionError("capability inspection must not read the source")


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
        approved=(), rejected=(), collisions=(), corrections=(),
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
