"""Behavior tests for Rekordbox Qualification through the Transfer seam."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime

import pytest

from djsupport.agent import AgentAuthorization, AgentTransferContract
from djsupport.cache import MatchCache
from djsupport.local_audition import (
    AuditionHandleUnavailable,
    LocalSourceAudition,
)
from djsupport.rekordbox import Track
from djsupport.transfer import (
    AccountPublishingGuards,
    BatchPlanRequest,
    EphemeralMatchingKnowledge,
    FilePublicationStorage,
    FileTransferStorage,
    MatchCacheKnowledge,
    PublicationItem,
    PublicationManifest,
    QualificationDecision,
    QualificationRequest,
    QualificationStatus,
    SourceSelection,
    SourceNotFound,
    SpotifyMutationResult,
    SpotifyPlaylistHead,
    SpotifyPlaylistItem,
    SpotifyPlaylistPage,
    SpotifyItemKind,
    SpotifyPlaylistChanged,
    SpotifyPlaylistReviewRequired,
    Transfer,
    TransferAuthorization,
    TransferMode,
)


def _track(
    track_id: str,
    *,
    title: str,
    duration: int,
    album: str = "Invented Source Release",
    label: str = "Invented Source Label",
    version: str = "",
    location: str = "",
) -> Track:
    return Track(
        track_id=track_id,
        name=title,
        artist="Invented Source Artist",
        album=album,
        remixer="",
        label=label,
        genre="Synthetic",
        date_added="2026-08-08",
        duration=duration,
        location=location,
        version=version,
    )


class RekordboxSelection:
    source_label = "Rekordbox"
    default_mode = TransferMode.MIRROR

    def __init__(self, tracks: list[Track]) -> None:
        self.tracks = tracks
        self.consumed = 0

    def consume(self, reference: str) -> SourceSelection:
        self.consumed += 1
        return SourceSelection("Selected", reference, list(self.tracks))

    def consume_batch(self, references, whole_library):
        return tuple(self.consume(reference) for reference in references)


class ProposalSpotify:
    def __init__(self, proposals: dict[str, dict | None]) -> None:
        self.proposals = proposals
        self.searches: list[str] = []

    def account_id(self):
        return "spotify-account-one"

    def match(self, track, threshold):
        self.searches.append(track.track_id)
        return self.proposals[track.track_id]

    def spotify_track(self, uri):
        return {"uri": uri, "is_playable": True}


class PlaylistSpotify(ProposalSpotify):
    def __init__(self, proposals: dict[str, dict | None]) -> None:
        super().__init__(proposals)
        self.playlists: dict[str, list[str]] = {}
        self.heads: dict[str, str] = {}
        self.playlist_writes = 0

    def create_playlist(self, name, description):
        self.playlists["provisional-one"] = []
        self.heads["provisional-one"] = "head-0"
        return "provisional-one"

    def find_recovery_playlist(self, publication_key):
        return None

    def _mutated(self, playlist_id, uris):
        self.playlist_writes += 1
        self.playlists[playlist_id] = list(uris)
        head = f"head-{self.playlist_writes}"
        self.heads[playlist_id] = head
        return SpotifyMutationResult(head)

    def replace_items(self, playlist_id, uris):
        return self._mutated(playlist_id, uris)

    def add_items(self, playlist_id, uris):
        return self._mutated(playlist_id, [*self.playlists[playlist_id], *uris])

    def playlist_head(self, playlist_id):
        return SpotifyPlaylistHead(self.heads[playlist_id])

    def ordered_playlist_items(self, playlist_id):
        return SpotifyPlaylistPage(tuple(
            SpotifyPlaylistItem(index, SpotifyItemKind.TRACK, uri)
            for index, uri in enumerate(self.playlists[playlist_id])
        ))

    def set_playlist_description(self, playlist_id, description):
        pass

    def provisional_playlist_track_uris(self, playlist_id):
        return list(self.playlists[playlist_id])

    def replace_provisional_playlist_tracks(self, playlist_id, uris):
        self._mutated(playlist_id, uris)

    def spotify_track(self, uri):
        return {
            "uri": uri,
            "name": "Explicit Replacement",
            "artist": "Replacement Artist",
            "album": "Replacement Release",
            "duration_ms": 222_000,
            "is_playable": True,
        }


class RetainedKnowledge(EphemeralMatchingKnowledge):
    persistent = True

    def __init__(self, retained: dict[str, dict] | None = None) -> None:
        self.retained = retained or {}

    def lookup(self, track, threshold):
        return self.retained.get(track.track_id)


class AuthorityRecordingKnowledge(RetainedKnowledge):
    def __init__(self) -> None:
        super().__init__()
        self.proposal_writes = 0
        self.approved = []
        self.corrected = []
        self.rejected = []

    def should_retry(self, track, threshold, retry_days, force):
        return True

    def retain(self, track, threshold, result):
        self.proposal_writes += 1

    def approve(self, item):
        self.approved.append(item)

    def correct(self, item):
        self.corrected.append(item)

    def reject(self, item):
        self.rejected.append(item)

    def approve_local_audio(self, item, account_id):
        return None


def _proposal(
    suffix: str,
    *,
    match_type: str = "exact",
    score: float = 96.0,
    reasons: tuple[str, ...] = ("artist agrees", "duration agrees"),
    duration_ms: int = 181_000,
) -> dict:
    return {
        "uri": f"spotify:track:{suffix:0<22}",
        "name": f"Invented Spotify {suffix}",
        "artist": "Invented Spotify Artist",
        "album": "Invented Spotify Release",
        "duration_ms": duration_ms,
        "score": score,
        "match_type": match_type,
        "score_reasons": list(reasons),
    }


def test_rekordbox_attention_queue_preserves_review_facts_and_authority(
    tmp_path,
):
    tracks = [
        _track("new", title="New Proposal", duration=181, version="Original Mix"),
        _track("short", title="Shorter Proposal", duration=360),
        _track("approved", title="Approved by Local Audio", duration=240),
    ]
    source = RekordboxSelection(tracks)
    spotify = ProposalSpotify({
        "new": _proposal("new"),
        "short": _proposal(
            "short", match_type="shorter_version", score=91.0,
            reasons=("artist agrees", "Spotify proposal is meaningfully shorter"),
            duration_ms=210_000,
        ),
        "approved": None,
    })
    knowledge = RetainedKnowledge({
        "approved": {
            **_proposal("approved", match_type="approved_local_audio"),
            "authoritative": True,
        },
    })
    storage = FileTransferStorage(tmp_path / "transfers.json")
    transfer = Transfer(
        source=source,
        spotify=spotify,
        matching_knowledge=knowledge,
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        transfer_storage=storage,
    )
    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Selected",),
        preview=True,
        local_audio_audition=True,
    ))
    report = transfer.execute_batch(plan, transfer_id=plan.batch_id)

    attention = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    )

    assert [item.source_track_id for item in attention.items] == ["new", "short"]
    assert attention.items[0].attention_reasons == ("new_proposal",)
    assert "shorter_version" in attention.items[1].attention_reasons
    assert attention.items[0].source_release == "Invented Source Release"
    assert attention.items[0].source_label == "Invented Source Label"
    assert attention.items[0].source_version == "Original Mix"
    assert attention.items[0].spotify_release == "Invented Spotify Release"
    assert attention.items[0].spotify_duration == 181
    assert attention.items[0].score_reasons == (
        "artist agrees", "duration agrees",
    )
    assert attention.pending == 2
    assert spotify.searches == ["new", "short"]

    all_proposals = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Selected",
            include_all=True,
        ),
        TransferAuthorization(private_source=True),
    )

    assert [item.source_track_id for item in all_proposals.items] == [
        "new", "short", "approved",
    ]
    approved = all_proposals.items[-1]
    assert approved.match_type == "approved_local_audio"
    assert approved.authority_status == "approved"
    assert approved.attention_reasons == ()

    transfer.record_qualification(
        all_proposals.draft_id,
        approved.item_id,
        QualificationDecision.DEFERRED,
        TransferAuthorization(private_source=True),
        reason="Explicit spot check is still unresolved",
    )
    resumed = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    )

    assert resumed.include_all is True
    assert [item.source_track_id for item in resumed.items] == [
        "new", "short", "approved",
    ]
    assert resumed.deferred == 1


def test_completed_draft_applies_before_separate_playlist_approval(tmp_path):
    tracks = [
        _track("keep", title="Keep Proposal", duration=181),
        _track("correct", title="Correct Proposal", duration=182),
        _track("defer", title="Deferred Proposal", duration=183),
        _track("reject", title="Rejected Proposal", duration=184),
    ]
    spotify = PlaylistSpotify({
        track.track_id: _proposal(track.track_id, duration_ms=track.duration * 1000)
        for track in tracks
    })
    knowledge = AuthorityRecordingKnowledge()
    publications = FilePublicationStorage(tmp_path / "publications.json")
    transfer = Transfer(
        source=RekordboxSelection(tracks),
        spotify=spotify,
        matching_knowledge=knowledge,
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=publications,
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
    )
    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Selected",),
    ))
    report = transfer.execute_batch(plan, transfer_id=plan.batch_id)
    playlist_id = report.playlists[0].spotify_playlist_id
    view = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    )
    item_ids = {item.source_track_id: item.item_id for item in view.items}
    writes_after_publication = spotify.playlist_writes
    proposal_writes_after_matching = knowledge.proposal_writes

    transfer.record_qualification(
        view.draft_id, item_ids["keep"], QualificationDecision.KEEP_PROPOSAL,
        TransferAuthorization(private_source=True),
    )
    transfer.record_qualification(
        view.draft_id,
        item_ids["correct"],
        QualificationDecision.CORRECTION,
        TransferAuthorization(private_source=True),
        spotify_reference="spotify:track:replacement00000000000",
    )
    deferred = transfer.record_qualification(
        view.draft_id,
        item_ids["defer"],
        QualificationDecision.DEFERRED,
        TransferAuthorization(private_source=True),
        reason="Needs a different listening environment",
    )
    transfer.record_qualification(
        view.draft_id, item_ids["reject"], QualificationDecision.REJECT_PROPOSAL,
        TransferAuthorization(private_source=True),
    )

    assert deferred.deferred == 1
    assert spotify.playlist_writes == writes_after_publication
    assert knowledge.proposal_writes == proposal_writes_after_matching
    assert knowledge.approved == knowledge.corrected == knowledge.rejected == []
    with pytest.raises(
        SpotifyPlaylistReviewRequired, match="completed and applied"
    ):
        transfer.approve(playlist_id)
    with pytest.raises(ValueError, match="pending or deferred"):
        transfer.apply_qualification(
            view.draft_id,
            TransferAuthorization(private_source=True, spotify_write=True),
        )
    with pytest.raises(PermissionError, match="spotify_write"):
        transfer.apply_qualification(
            view.draft_id, TransferAuthorization(private_source=True),
        )
    assert spotify.playlist_writes == writes_after_publication

    ready = transfer.record_qualification(
        view.draft_id,
        item_ids["defer"],
        QualificationDecision.DEFERRED,
        TransferAuthorization(private_source=True),
        reason="Explicitly omitted from this bounded review",
        exclude=True,
    )
    assert ready.complete is True
    applied = transfer.apply_qualification(
        view.draft_id,
        TransferAuthorization(private_source=True, spotify_write=True),
    )

    assert applied.status.value == "applied"
    assert spotify.playlists[playlist_id] == [
        _proposal("keep")["uri"],
        "spotify:track:replacement00000000000",
    ]
    assert knowledge.approved == knowledge.corrected == knowledge.rejected == []

    resumed_applied = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    )

    assert resumed_applied.status.value == "applied"
    assert transfer.apply_qualification(
        view.draft_id,
        TransferAuthorization(private_source=True, spotify_write=True),
    ).status.value == "applied"

    approval = transfer.approve_qualification(
        view.draft_id,
        TransferAuthorization(private_source=True, spotify_write=True),
    )

    assert approval.status.value == "approved"
    assert [item.source_track_id for item in knowledge.approved] == ["keep"]
    assert [item.source_track_id for item in knowledge.corrected] == ["correct"]
    assert [item.source_track_id for item in knowledge.rejected] == ["reject"]


def test_duplicate_source_occurrences_remain_ordered_facts_through_approval(
    tmp_path,
):
    repeated = _track("repeat", title="Repeated Source", duration=181)
    spotify = PlaylistSpotify({"repeat": _proposal("repeat")})
    knowledge = AuthorityRecordingKnowledge()
    publications = FilePublicationStorage(tmp_path / "publications.json")
    transfer = Transfer(
        source=RekordboxSelection([repeated, repeated]),
        spotify=spotify,
        matching_knowledge=knowledge,
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=publications,
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
    )
    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Selected",),
    ))
    report = transfer.execute_batch(plan, transfer_id=plan.batch_id)
    view = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    )

    assert [item.source_index for item in view.items] == [0, 1]
    assert len({item.item_id for item in view.items}) == 2
    for item in view.items:
        transfer.record_qualification(
            view.draft_id, item.item_id, QualificationDecision.KEEP_PROPOSAL,
            TransferAuthorization(private_source=True),
        )
    transfer.apply_qualification(
        view.draft_id,
        TransferAuthorization(private_source=True, spotify_write=True),
    )
    outcome = transfer.approve_qualification(
        view.draft_id,
        TransferAuthorization(private_source=True, spotify_write=True),
    )

    assert outcome.status.value == "approved"
    assert outcome.collision_count == 0
    assert spotify.playlists[report.playlists[0].spotify_playlist_id] == [
        _proposal("repeat")["uri"], _proposal("repeat")["uri"],
    ]


def test_attention_queue_explains_fallback_unresolved_collision_and_conflict(
    tmp_path,
):
    tracks = [
        _track("fallback", title="Fallback", duration=360),
        _track(
            "version", title="Version Conflict", duration=240,
            version="Extended Mix",
        ),
        _track("unresolved", title="Unresolved", duration=200),
        _track("collision-a", title="Collision A", duration=201),
        _track("collision-b", title="Collision B", duration=202),
    ]
    shared = _proposal("shared")
    spotify = ProposalSpotify({
        "fallback": _proposal("fallback", match_type="fallback_version"),
        "version": _proposal(
            "version", reasons=(
                "artist agrees",
                "version conflict: Spotify proposal differs from source version",
            ),
        ),
        "unresolved": {"alternatives": [_proposal("alternative", score=77.0)]},
        "collision-a": shared,
        "collision-b": shared,
    })

    class ConflictKnowledge(RetainedKnowledge):
        def should_retry(self, track, threshold, retry_days, force):
            return True

        def approval_conflict(self, item):
            return item.source_track_id == "fallback"

    transfer = Transfer(
        source=RekordboxSelection(tracks),
        spotify=spotify,
        matching_knowledge=ConflictKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
    )
    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Selected",), preview=True,
    ))
    report = transfer.execute_batch(plan, transfer_id=plan.batch_id)
    view = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    )
    reasons = {
        item.source_track_id: item.attention_reasons for item in view.items
    }

    assert [item.source_track_id for item in view.items] == [
        "fallback", "version", "unresolved", "collision-a", "collision-b",
    ]
    assert "fallback_version" in reasons["fallback"]
    assert "approval_conflict" in reasons["fallback"]
    assert "version_conflict" in reasons["version"]
    assert reasons["unresolved"] == ("unresolved", "alternatives")
    assert "match_collision" in reasons["collision-a"]
    assert "match_collision" in reasons["collision-b"]


@pytest.mark.parametrize("conflict_kind", ["match_collision", "approval_conflict"])
def test_unresolved_conflicts_block_draft_application_before_mutation(
    tmp_path, conflict_kind,
):
    tracks = [
        _track("conflict-a", title="Conflict A", duration=181),
        _track("conflict-b", title="Conflict B", duration=182),
    ]
    proposals = {
        "conflict-a": _proposal("shared"),
        "conflict-b": (
            _proposal("shared")
            if conflict_kind == "match_collision" else _proposal("other")
        ),
    }

    class ConflictKnowledge(AuthorityRecordingKnowledge):
        def approval_conflict(self, item):
            return (
                conflict_kind == "approval_conflict"
                and item.source_track_id == "conflict-a"
            )

    spotify = PlaylistSpotify(proposals)
    transfer = Transfer(
        source=RekordboxSelection(tracks),
        spotify=spotify,
        matching_knowledge=ConflictKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=FilePublicationStorage(tmp_path / "publications.json"),
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
    )
    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Conflict",),
    ))
    report = transfer.execute_batch(plan, transfer_id=plan.batch_id)
    view = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Conflict",
        ),
        TransferAuthorization(private_source=True),
    )
    for item in view.items:
        transfer.record_qualification(
            view.draft_id, item.item_id, QualificationDecision.KEEP_PROPOSAL,
            TransferAuthorization(private_source=True),
        )
    writes_before = spotify.playlist_writes

    with pytest.raises(SpotifyPlaylistReviewRequired, match="conflict"):
        transfer.apply_qualification(
            view.draft_id,
            TransferAuthorization(private_source=True, spotify_write=True),
        )

    assert spotify.playlist_writes == writes_before


def test_staged_correction_rechecks_approved_match_conflict_before_mutation(
    tmp_path,
):
    replacement_uri = "spotify:track:replacement00000000000"

    class CorrectedConflictKnowledge(AuthorityRecordingKnowledge):
        def approval_conflict(self, item):
            return item.spotify_uri == replacement_uri

    track = _track("conflict", title="Correction Conflict", duration=181)
    spotify = PlaylistSpotify({"conflict": _proposal("conflict")})
    transfer = Transfer(
        source=RekordboxSelection([track]),
        spotify=spotify,
        matching_knowledge=CorrectedConflictKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=FilePublicationStorage(
            tmp_path / "publications.json"
        ),
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
    )
    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Conflict",),
    ))
    report = transfer.execute_batch(plan, transfer_id=plan.batch_id)
    view = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Conflict",
        ),
        TransferAuthorization(private_source=True),
    )
    transfer.record_qualification(
        view.draft_id,
        view.items[0].item_id,
        QualificationDecision.CORRECTION,
        TransferAuthorization(private_source=True),
        spotify_reference=replacement_uri,
    )
    writes_before = spotify.playlist_writes

    with pytest.raises(SpotifyPlaylistReviewRequired, match="conflict"):
        transfer.apply_qualification(
            view.draft_id,
            TransferAuthorization(private_source=True, spotify_write=True),
        )

    assert spotify.playlist_writes == writes_before


def test_browser_origin_snapshot_never_creates_a_qualification_draft(tmp_path):
    class BrowserSource:
        source_label = "Beatport"
        default_mode = TransferMode.SNAPSHOT

        def consume(self, reference):
            return SourceSelection(
                "Browser Selection", reference,
                [_track("browser", title="Browser Track", duration=180)],
            )

    storage = FileTransferStorage(tmp_path / "transfers.json")
    transfer = Transfer(
        source=BrowserSource(),
        spotify=ProposalSpotify({"browser": _proposal("browser")}),
        matching_knowledge=RetainedKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        transfer_storage=storage,
    )
    from djsupport.transfer import TransferRequest

    report = transfer.execute(TransferRequest(
        source="https://browser.example/selection",
        preview=True,
        transfer_id="browser-transfer",
    ))

    with pytest.raises(ValueError, match="only for Rekordbox Mirrors"):
        transfer.obtain_qualification(
            QualificationRequest(transfer_id=report.transfer_id),
            TransferAuthorization(private_source=True),
        )
    assert storage.qualifications == {}


def test_changed_playlist_head_blocks_draft_application_before_mutation(tmp_path):
    track = _track("head", title="Head Guard", duration=181)
    spotify = PlaylistSpotify({"head": _proposal("head")})
    publications = FilePublicationStorage(tmp_path / "publications.json")
    transfer = Transfer(
        source=RekordboxSelection([track]),
        spotify=spotify,
        matching_knowledge=AuthorityRecordingKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=publications,
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
    )
    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Selected",),
    ))
    report = transfer.execute_batch(plan, transfer_id=plan.batch_id)
    view = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    )
    transfer.record_qualification(
        view.draft_id, view.items[0].item_id,
        QualificationDecision.KEEP_PROPOSAL,
        TransferAuthorization(private_source=True),
    )
    playlist_id = report.playlists[0].spotify_playlist_id
    spotify._mutated(playlist_id, spotify.playlists[playlist_id])
    writes_after_external_change = spotify.playlist_writes

    with pytest.raises(SpotifyPlaylistChanged, match="changed before"):
        transfer.apply_qualification(
            view.draft_id,
            TransferAuthorization(private_source=True, spotify_write=True),
        )

    assert spotify.playlist_writes == writes_after_external_change


@pytest.mark.parametrize("external_edit", [False, True])
def test_draft_application_recovers_only_its_checkpointed_playlist_mutation(
    tmp_path, external_edit,
):
    class CrashOncePublicationStorage(FilePublicationStorage):
        crash_next = False

        def retain_publication(self, manifest):
            if self.crash_next:
                self.crash_next = False
                raise RuntimeError("synthetic retention crash")
            super().retain_publication(manifest)

    track = _track("crash", title="Crash Recovery", duration=181)
    spotify = PlaylistSpotify({"crash": _proposal("crash")})
    knowledge = AuthorityRecordingKnowledge()
    publication_path = tmp_path / "publications.json"
    transfer_path = tmp_path / "transfers.json"
    publications = CrashOncePublicationStorage(publication_path)
    transfer = Transfer(
        source=RekordboxSelection([track]),
        spotify=spotify,
        matching_knowledge=knowledge,
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=publications,
        transfer_storage=FileTransferStorage(transfer_path),
    )
    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Selected",),
    ))
    report = transfer.execute_batch(plan, transfer_id=plan.batch_id)
    draft = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    )
    transfer.record_qualification(
        draft.draft_id,
        draft.items[0].item_id,
        QualificationDecision.KEEP_PROPOSAL,
        TransferAuthorization(private_source=True),
    )
    writes_before = spotify.playlist_writes
    publications.crash_next = True

    with pytest.raises(RuntimeError, match="retention crash"):
        transfer.apply_qualification(
            draft.draft_id,
            TransferAuthorization(private_source=True, spotify_write=True),
        )

    assert spotify.playlist_writes == writes_before + 1
    if external_edit:
        spotify._mutated(
            report.playlists[0].spotify_playlist_id,
            [_proposal("external-edit")["uri"]],
        )
    writes_before_resume = spotify.playlist_writes
    restarted = Transfer(
        source=RekordboxSelection([track]),
        spotify=spotify,
        matching_knowledge=knowledge,
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=FilePublicationStorage(publication_path),
        transfer_storage=FileTransferStorage(transfer_path),
    )
    if external_edit:
        with pytest.raises(SpotifyPlaylistChanged):
            restarted.apply_qualification(
                draft.draft_id,
                TransferAuthorization(
                    private_source=True, spotify_write=True,
                ),
            )
    else:
        outcome = restarted.apply_qualification(
            draft.draft_id,
            TransferAuthorization(private_source=True, spotify_write=True),
        )
        assert outcome.status == QualificationStatus.APPLIED

    assert spotify.playlist_writes == writes_before_resume
    assert knowledge.approved == knowledge.corrected == knowledge.rejected == []


@pytest.mark.parametrize("changed_evidence", ["source", "manifest", "account"])
def test_changed_bound_evidence_blocks_application_without_mutation(
    tmp_path, changed_evidence,
):
    track = _track("bound", title="Bound Evidence", duration=181)
    source = RekordboxSelection([track])
    spotify = PlaylistSpotify({"bound": _proposal("bound")})
    publications = FilePublicationStorage(tmp_path / "publications.json")
    transfer = Transfer(
        source=source,
        spotify=spotify,
        matching_knowledge=AuthorityRecordingKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=publications,
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
    )
    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Selected",),
    ))
    report = transfer.execute_batch(plan, transfer_id=plan.batch_id)
    playlist_id = report.playlists[0].spotify_playlist_id
    view = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    )
    transfer.record_qualification(
        view.draft_id, view.items[0].item_id,
        QualificationDecision.KEEP_PROPOSAL,
        TransferAuthorization(private_source=True),
    )
    if changed_evidence == "source":
        source.tracks[0] = replace(track, duration=999)
    elif changed_evidence == "manifest":
        manifest = publications.publication_for_playlist(
            "spotify-account-one", playlist_id,
        )
        publications.retain_publication(replace(
            manifest, spotify_playlist_name="Changed Playlist Name",
        ))
    else:
        spotify.account_id = lambda: "spotify-account-two"
    writes_before = spotify.playlist_writes

    with pytest.raises((SpotifyPlaylistReviewRequired, ValueError)):
        transfer.apply_qualification(
            view.draft_id,
            TransferAuthorization(private_source=True, spotify_write=True),
        )

    assert spotify.playlist_writes == writes_before


def test_large_draft_application_resumes_from_checkpoints_and_is_idempotent(
    tmp_path,
):
    tracks = [
        _track(f"track-{index}", title=f"Track {index}", duration=180 + index)
        for index in range(101)
    ]
    spotify = PlaylistSpotify({
        track.track_id: _proposal(f"{index:022d}")
        for index, track in enumerate(tracks)
    })
    transfer = Transfer(
        source=RekordboxSelection(tracks),
        spotify=spotify,
        matching_knowledge=AuthorityRecordingKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=FilePublicationStorage(tmp_path / "publications.json"),
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
    )
    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Large",), confirm_expensive=True,
    ))
    report = transfer.execute_batch(plan, transfer_id=plan.batch_id)
    view = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Large",
        ),
        TransferAuthorization(private_source=True),
    )
    for item in view.items:
        transfer.record_qualification(
            view.draft_id, item.item_id, QualificationDecision.KEEP_PROPOSAL,
            TransferAuthorization(private_source=True),
        )
    writes_before_apply = spotify.playlist_writes
    transfer.pause()

    paused = transfer.apply_qualification(
        view.draft_id,
        TransferAuthorization(private_source=True, spotify_write=True),
    )
    resumed = transfer.apply_qualification(
        view.draft_id,
        TransferAuthorization(private_source=True, spotify_write=True),
    )
    writes_after_resume = spotify.playlist_writes
    repeated = transfer.apply_qualification(
        view.draft_id,
        TransferAuthorization(private_source=True, spotify_write=True),
    )

    assert paused.status.value == "paused"
    assert resumed.status.value == repeated.status.value == "applied"
    assert spotify.playlist_writes == writes_before_apply + 2
    assert spotify.playlist_writes == writes_after_resume
    assert len(spotify.playlists[report.playlists[0].spotify_playlist_id]) == 101


def test_agent_qualification_documents_are_first_class_and_privacy_redacted(
    tmp_path,
):
    track = _track("agent", title="Private Agent Review", duration=181)
    spotify = PlaylistSpotify({"agent": _proposal("agent")})
    transfer = Transfer(
        source=RekordboxSelection([track]),
        spotify=spotify,
        matching_knowledge=AuthorityRecordingKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=FilePublicationStorage(tmp_path / "publications.json"),
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
    )
    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Private/Agent",),
    ))
    report = transfer.execute_batch(plan, transfer_id=plan.batch_id)
    contract = AgentTransferContract(transfer)
    request = QualificationRequest(
        transfer_id=report.transfer_id,
        playlist_reference="Private/Agent",
    )

    blocked = contract.qualification_draft(request, AgentAuthorization())
    document = contract.qualification_draft(
        request, AgentAuthorization(private_source=True),
    )

    assert blocked["status"] == "authorization_required"
    assert document["contract_version"] == 2
    assert document["phase"] == "qualification"
    assert document["status"] == "draft"
    assert document["counts"] == {
        "items": 1, "pending": 1, "deferred": 0,
    }
    assert document["authority"] == "none"
    assert document["review_url"].startswith(
        "http://127.0.0.1:8000/qualification/"
    )
    assert document["next_actions"] == ["review", "discard"]
    rendered = str(document)
    assert "Private/Agent" not in rendered
    assert "Private Agent Review" not in rendered
    assert _proposal("agent")["uri"] not in rendered

    item_id = transfer.qualification(
        document["draft_id"], TransferAuthorization(private_source=True),
    ).items[0].item_id
    transfer.record_qualification(
        document["draft_id"], item_id, QualificationDecision.KEEP_PROPOSAL,
        TransferAuthorization(private_source=True),
    )
    ready = contract.qualification_progress(
        document["draft_id"], AgentAuthorization(private_source=True),
    )
    denied_apply = contract.apply_qualification(
        document["draft_id"], AgentAuthorization(private_source=True),
    )

    assert ready["status"] == "ready"
    assert ready["next_actions"] == ["apply", "discard"]
    assert denied_apply["status"] == "authorization_required"
    assert denied_apply["required_authorizations"] == ["spotify_write"]


def test_preview_draft_links_to_distinct_equivalent_provisional_mirror(
    tmp_path,
):
    track = _track("preview-link", title="Preview Link", duration=181)
    spotify = PlaylistSpotify({"preview-link": _proposal("preview-link")})
    knowledge = AuthorityRecordingKnowledge()
    publications = FilePublicationStorage(tmp_path / "publications.json")
    storage = FileTransferStorage(tmp_path / "transfers.json")
    transfer = Transfer(
        source=RekordboxSelection([track]),
        spotify=spotify,
        matching_knowledge=knowledge,
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=publications,
        transfer_storage=storage,
    )
    preview_plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Selected",), preview=True,
    ))
    preview = transfer.execute_batch(
        preview_plan, transfer_id=preview_plan.batch_id,
    )
    draft = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=preview.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    )
    decided = transfer.record_qualification(
        draft.draft_id,
        draft.items[0].item_id,
        QualificationDecision.KEEP_PROPOSAL,
        TransferAuthorization(private_source=True),
    )

    assert decided.spotify_playlist_id is None
    assert decided.next_actions == ("publish_and_link", "discard")
    with pytest.raises(SpotifyPlaylistReviewRequired, match="linked"):
        transfer.apply_qualification(
            draft.draft_id,
            TransferAuthorization(private_source=True, spotify_write=True),
        )

    publish_plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Selected",),
    ))
    published = transfer.execute_batch(
        publish_plan, transfer_id=publish_plan.batch_id,
    )
    writes_before_link = spotify.playlist_writes
    linked = transfer.link_qualification(
        draft.draft_id,
        published.transfer_id,
        TransferAuthorization(private_source=True),
    )

    assert linked.draft_id == draft.draft_id
    assert linked.transfer_id != draft.transfer_id
    assert linked.spotify_playlist_id == published.playlists[0].spotify_playlist_id
    assert linked.items[0].decision == QualificationDecision.KEEP_PROPOSAL
    assert linked.next_actions == ("apply", "discard")
    assert spotify.playlist_writes == writes_before_link
    assert knowledge.approved == knowledge.corrected == knowledge.rejected == []
    restarted = Transfer(
        source=RekordboxSelection([track]),
        spotify=spotify,
        matching_knowledge=knowledge,
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=FilePublicationStorage(
            tmp_path / "publications.json"
        ),
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
    )
    resumed = restarted.obtain_qualification(
        QualificationRequest(
            transfer_id=published.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    )
    assert resumed.draft_id == linked.draft_id
    assert resumed.items[0].decision == QualificationDecision.KEEP_PROPOSAL
    resumed_from_preview = restarted.obtain_qualification(
        QualificationRequest(
            transfer_id=preview.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    )
    assert resumed_from_preview.draft_id == linked.draft_id

    transfer.apply_qualification(
        linked.draft_id,
        TransferAuthorization(private_source=True, spotify_write=True),
    )
    approval = transfer.approve_qualification(
        linked.draft_id,
        TransferAuthorization(private_source=True, spotify_write=True),
    )

    assert approval.status.value == "approved"
    assert [item.source_track_id for item in knowledge.approved] == [
        "preview-link"
    ]


def test_preview_link_fails_closed_if_reviewed_preview_evidence_drifted(
    tmp_path,
):
    track = _track("preview-drift", title="Preview Drift", duration=181)
    spotify = PlaylistSpotify({"preview-drift": _proposal("preview-drift")})
    storage = FileTransferStorage(tmp_path / "transfers.json")
    transfer = Transfer(
        source=RekordboxSelection([track]),
        spotify=spotify,
        matching_knowledge=AuthorityRecordingKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=FilePublicationStorage(
            tmp_path / "publications.json"
        ),
        transfer_storage=storage,
    )
    preview_plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Selected",), preview=True,
    ))
    preview = transfer.execute_batch(
        preview_plan, transfer_id=preview_plan.batch_id,
    )
    draft = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=preview.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    )
    transfer.record_qualification(
        draft.draft_id,
        draft.items[0].item_id,
        QualificationDecision.KEEP_PROPOSAL,
        TransferAuthorization(private_source=True),
    )
    preview_child = storage.load_batch(preview.transfer_id).playlists[0].transfer_id
    preview_state = storage.load_transfer(preview_child)
    preview_state.publication_items[0]["spotify_name"] = "Drifted proposal"
    storage.save_transfer(preview_child, preview_state)
    publish_plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Selected",),
    ))
    published = transfer.execute_batch(
        publish_plan, transfer_id=publish_plan.batch_id,
    )
    writes_before = spotify.playlist_writes

    with pytest.raises(SpotifyPlaylistReviewRequired, match="Preview"):
        transfer.link_qualification(
            draft.draft_id,
            published.transfer_id,
            TransferAuthorization(private_source=True),
        )

    assert spotify.playlist_writes == writes_before


def test_qualification_storage_rejects_stale_concurrent_revision(tmp_path):
    track = _track("concurrent", title="Concurrent", duration=181)
    path = tmp_path / "transfers.json"
    transfer = Transfer(
        source=RekordboxSelection([track]),
        spotify=PlaylistSpotify({"concurrent": _proposal("concurrent")}),
        matching_knowledge=AuthorityRecordingKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=FilePublicationStorage(
            tmp_path / "publications.json"
        ),
        transfer_storage=FileTransferStorage(path),
    )
    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Selected",),
    ))
    report = transfer.execute_batch(plan, transfer_id=plan.batch_id)
    draft = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    )
    first = FileTransferStorage(path)
    second = FileTransferStorage(path)
    first_state = first.load_qualification(draft.draft_id)
    stale_state = second.load_qualification(draft.draft_id)
    first_state.include_all = True
    first.save_qualification(draft.draft_id, first_state)
    stale_state.include_all = False

    with pytest.raises(ValueError, match="changed concurrently"):
        second.save_qualification(draft.draft_id, stale_state)

    assert FileTransferStorage(path).load_qualification(
        draft.draft_id
    ).include_all is True


def test_qualification_storage_rejects_mismatched_embedded_draft_identity(
    tmp_path,
):
    track = _track("identity", title="Identity", duration=181)
    path = tmp_path / "transfers.json"
    transfer = Transfer(
        source=RekordboxSelection([track]),
        spotify=PlaylistSpotify({"identity": _proposal("identity")}),
        matching_knowledge=AuthorityRecordingKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=FilePublicationStorage(
            tmp_path / "publications.json"
        ),
        transfer_storage=FileTransferStorage(path),
    )
    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Selected",),
    ))
    report = transfer.execute_batch(plan, transfer_id=plan.batch_id)
    draft = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    )
    persisted = json.loads(path.read_text())
    stored = persisted["qualifications"].pop(draft.draft_id)
    persisted["qualifications"]["different-map-key"] = stored
    path.write_text(json.dumps(persisted))

    with pytest.raises(ValueError, match="Transfer state is malformed"):
        FileTransferStorage(path)


def test_schema_three_transfer_and_schema_five_manifest_apply_additively(
    tmp_path,
):
    legacy_item_keys = {
        "source_track_id", "source_name", "source_artist", "source_title",
        "spotify_uri", "spotify_name", "spotify_artist", "score",
        "match_type", "score_reasons", "source_duration", "authoritative",
        "local_evidence_id",
    }

    def legacy_item(item):
        return {key: value for key, value in item.items() if key in legacy_item_keys}

    track = _track("legacy", title="Legacy", duration=181)
    spotify = PlaylistSpotify({"legacy": _proposal("legacy")})
    transfer_path = tmp_path / "transfers.json"
    publication_path = tmp_path / "publications.json"
    transfer = Transfer(
        source=RekordboxSelection([track]),
        spotify=spotify,
        matching_knowledge=AuthorityRecordingKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=FilePublicationStorage(publication_path),
        transfer_storage=FileTransferStorage(transfer_path),
    )
    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Selected",),
    ))
    report = transfer.execute_batch(plan, transfer_id=plan.batch_id)

    legacy_transfers = json.loads(transfer_path.read_text())
    legacy_transfers["version"] = 3
    for batch in legacy_transfers["batches"].values():
        batch.pop("revision", None)
    for state in legacy_transfers["transfers"].values():
        state.pop("revision", None)
        state.pop("audition_selection_digest", None)
        for selected in state.get("selection", {}).get("tracks", []):
            selected.pop("version", None)
        state["publication_items"] = [
            legacy_item(item) for item in state["publication_items"]
        ]
        if state.get("publication_manifest"):
            state["publication_manifest"]["items"] = [
                legacy_item(item)
                for item in state["publication_manifest"]["items"]
            ]
            state["publication_manifest"]["managed_items"] = [
                legacy_item(item)
                for item in state["publication_manifest"]["managed_items"]
            ]
    transfer_path.write_text(json.dumps(legacy_transfers))
    legacy_publications = json.loads(publication_path.read_text())
    legacy_publications["version"] = 5
    for manifest in legacy_publications["manifests"]:
        manifest["items"] = [legacy_item(item) for item in manifest["items"]]
        manifest["managed_items"] = [
            legacy_item(item) for item in manifest["managed_items"]
        ]
    publication_path.write_text(json.dumps(legacy_publications))

    resumed = Transfer(
        source=RekordboxSelection([track]),
        spotify=spotify,
        matching_knowledge=AuthorityRecordingKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=FilePublicationStorage(publication_path),
        transfer_storage=FileTransferStorage(transfer_path),
    )
    draft = resumed.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    )
    resumed.record_qualification(
        draft.draft_id,
        draft.items[0].item_id,
        QualificationDecision.KEEP_PROPOSAL,
        TransferAuthorization(private_source=True),
    )
    outcome = resumed.apply_qualification(
        draft.draft_id,
        TransferAuthorization(private_source=True, spotify_write=True),
    )

    assert outcome.status == QualificationStatus.APPLIED
    assert json.loads(transfer_path.read_text())["version"] == 5
    assert json.loads(publication_path.read_text())["version"] == 6


def test_discard_blocks_approval_until_explicit_fresh_draft_is_applied(
    tmp_path,
):
    track = _track("discard", title="Discard", duration=181)
    spotify = PlaylistSpotify({"discard": _proposal("discard")})
    knowledge = AuthorityRecordingKnowledge()
    transfer = Transfer(
        source=RekordboxSelection([track]),
        spotify=spotify,
        matching_knowledge=knowledge,
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=FilePublicationStorage(
            tmp_path / "publications.json"
        ),
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
    )
    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Selected",),
    ))
    report = transfer.execute_batch(plan, transfer_id=plan.batch_id)
    playlist_id = report.playlists[0].spotify_playlist_id
    draft = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    )

    discarded = transfer.discard_qualification(
        draft.draft_id, TransferAuthorization(private_source=True),
    )

    assert discarded.status.value == "discarded"
    assert transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    ).status.value == "discarded"
    with pytest.raises(SpotifyPlaylistReviewRequired, match="completed and applied"):
        transfer.approve(playlist_id)
    assert knowledge.approved == knowledge.rejected == []

    fresh = transfer.supersede_qualification(
        draft.draft_id, TransferAuthorization(private_source=True),
    )
    assert fresh.draft_id != draft.draft_id
    assert fresh.pending == 1
    assert transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    ).draft_id == fresh.draft_id
    ready = transfer.record_qualification(
        fresh.draft_id,
        fresh.items[0].item_id,
        QualificationDecision.KEEP_PROPOSAL,
        TransferAuthorization(private_source=True),
    )
    transfer.apply_qualification(
        ready.draft_id,
        TransferAuthorization(private_source=True, spotify_write=True),
    )
    approved = transfer.approve_qualification(
        fresh.draft_id,
        TransferAuthorization(private_source=True, spotify_write=True),
    )

    assert approved.status.value == "approved"
    assert [item.source_track_id for item in knowledge.approved] == ["discard"]


def test_changed_manifest_after_apply_blocks_approval_without_authority_writes(
    tmp_path,
):
    track = _track("manifest", title="Manifest", duration=181)
    spotify = PlaylistSpotify({"manifest": _proposal("manifest")})
    knowledge = AuthorityRecordingKnowledge()
    publications = FilePublicationStorage(tmp_path / "publications.json")
    transfer = Transfer(
        source=RekordboxSelection([track]),
        spotify=spotify,
        matching_knowledge=knowledge,
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=publications,
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
    )
    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Selected",),
    ))
    report = transfer.execute_batch(plan, transfer_id=plan.batch_id)
    playlist_id = report.playlists[0].spotify_playlist_id
    draft = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    )
    transfer.record_qualification(
        draft.draft_id,
        draft.items[0].item_id,
        QualificationDecision.KEEP_PROPOSAL,
        TransferAuthorization(private_source=True),
    )
    transfer.apply_qualification(
        draft.draft_id,
        TransferAuthorization(private_source=True, spotify_write=True),
    )
    retained = publications.publication_for_playlist(
        "spotify-account-one", playlist_id,
    )
    assert retained is not None
    publications.retain_publication(replace(
        retained, spotify_playlist_name="Changed after Qualification",
    ))

    with pytest.raises(SpotifyPlaylistReviewRequired, match="changed after"):
        transfer.approve_qualification(
            draft.draft_id,
            TransferAuthorization(private_source=True, spotify_write=True),
        )

    assert knowledge.approved == knowledge.corrected == knowledge.rejected == []


@pytest.mark.parametrize("changed_evidence", ["source", "playlist_head"])
def test_changed_evidence_after_apply_blocks_qualification_approval(
    tmp_path, changed_evidence,
):
    track = _track("approve-stable", title="Approve Stable", duration=181)
    source = RekordboxSelection([track])
    spotify = PlaylistSpotify({"approve-stable": _proposal("approve-stable")})
    knowledge = AuthorityRecordingKnowledge()
    transfer = Transfer(
        source=source,
        spotify=spotify,
        matching_knowledge=knowledge,
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=FilePublicationStorage(
            tmp_path / "publications.json"
        ),
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
    )
    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Selected",),
    ))
    report = transfer.execute_batch(plan, transfer_id=plan.batch_id)
    draft = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    )
    transfer.record_qualification(
        draft.draft_id,
        draft.items[0].item_id,
        QualificationDecision.KEEP_PROPOSAL,
        TransferAuthorization(private_source=True),
    )
    transfer.apply_qualification(
        draft.draft_id,
        TransferAuthorization(private_source=True, spotify_write=True),
    )
    writes_before_approval = spotify.playlist_writes
    if changed_evidence == "source":
        source.tracks = [
            replace(track, name="Changed after application"),
        ]
        expected = SpotifyPlaylistReviewRequired
    else:
        spotify._mutated(
            report.playlists[0].spotify_playlist_id,
            [_proposal("manual-edit")["uri"]],
        )
        expected = SpotifyPlaylistChanged
        writes_before_approval = spotify.playlist_writes

    with pytest.raises(expected):
        transfer.approve_qualification(
            draft.draft_id,
            TransferAuthorization(private_source=True, spotify_write=True),
        )

    assert spotify.playlist_writes == writes_before_approval
    assert knowledge.approved == knowledge.corrected == knowledge.rejected == []


@pytest.mark.parametrize("phase", ["apply", "approval"])
def test_agent_reports_missing_source_as_review_required_without_effects(
    tmp_path, phase,
):
    track = _track("source-loss", title="Source Loss", duration=181)
    source = RekordboxSelection([track])
    spotify = PlaylistSpotify({"source-loss": _proposal("source-loss")})
    knowledge = AuthorityRecordingKnowledge()
    transfer = Transfer(
        source=source,
        spotify=spotify,
        matching_knowledge=knowledge,
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=FilePublicationStorage(
            tmp_path / "publications.json"
        ),
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
    )
    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Selected",),
    ))
    report = transfer.execute_batch(plan, transfer_id=plan.batch_id)
    draft = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    )
    transfer.record_qualification(
        draft.draft_id,
        draft.items[0].item_id,
        QualificationDecision.KEEP_PROPOSAL,
        TransferAuthorization(private_source=True),
    )
    if phase == "approval":
        transfer.apply_qualification(
            draft.draft_id,
            TransferAuthorization(private_source=True, spotify_write=True),
        )
    writes_before = spotify.playlist_writes

    def missing(reference):
        raise SourceNotFound("synthetic selected source disappeared")

    source.consume = missing
    contract = AgentTransferContract(transfer)
    if phase == "apply":
        document = contract.apply_qualification(
            draft.draft_id,
            AgentAuthorization(private_source=True, spotify_write=True),
        )
    else:
        document = contract.approve_qualification(
            draft.draft_id,
            AgentAuthorization(private_source=True),
        )

    assert document["status"] == "review_required"
    assert document["draft_id"] == draft.draft_id
    assert spotify.playlist_writes == writes_before
    assert knowledge.approved == knowledge.corrected == knowledge.rejected == []


def test_staged_correction_renders_replacement_facts_and_rejects_invalid_choices(
    tmp_path,
):
    track = _track("correction", title="Correction", duration=360)
    original = _proposal(
        "correction", match_type="shorter_version", duration_ms=180_000,
    )
    spotify = PlaylistSpotify({"correction": original})
    transfer = Transfer(
        source=RekordboxSelection([track]),
        spotify=spotify,
        matching_knowledge=AuthorityRecordingKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=FilePublicationStorage(
            tmp_path / "publications.json"
        ),
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
    )
    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Selected",),
    ))
    report = transfer.execute_batch(plan, transfer_id=plan.batch_id)
    draft = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    )
    with pytest.raises(ValueError, match="different Spotify track"):
        transfer.record_qualification(
            draft.draft_id,
            draft.items[0].item_id,
            QualificationDecision.CORRECTION,
            TransferAuthorization(private_source=True),
            spotify_reference=original["uri"],
        )
    replacement = "spotify:track:replacement00000000000"
    corrected = transfer.record_qualification(
        draft.draft_id,
        draft.items[0].item_id,
        QualificationDecision.CORRECTION,
        TransferAuthorization(private_source=True),
        spotify_reference=replacement,
    )
    item = corrected.items[0]

    assert item.spotify_uri == replacement
    assert item.spotify_release == "Replacement Release"
    assert item.spotify_duration == 222
    assert item.match_type == "correction"
    assert item.score_reasons == ("explicit Qualification Correction",)
    assert item.attention_reasons == ("staged_correction",)
    assert "shorter_version" not in item.attention_reasons
    assert "duration_conflict" not in item.attention_reasons

    spotify.spotify_track = lambda uri: {
        "uri": uri,
        "name": "Unavailable",
        "artist": "Replacement Artist",
        "album": "Replacement Release",
        "duration_ms": 222_000,
        "is_playable": False,
    }
    with pytest.raises(ValueError, match="not an available"):
        transfer.record_qualification(
            draft.draft_id,
            item.item_id,
            QualificationDecision.CORRECTION,
            TransferAuthorization(private_source=True),
            spotify_reference=_proposal("unavailable")["uri"],
        )


def test_abandoned_qualification_approval_retires_local_audition_handles(
    tmp_path, monkeypatch,
):
    media = tmp_path / "selected-source.wav"
    media.write_bytes(b"synthetic media")
    track = _track(
        "abandoned", title="Abandoned", duration=181,
        location=media.as_uri(),
    )
    spotify = PlaylistSpotify({"abandoned": _proposal("abandoned")})
    audition = LocalSourceAudition()
    transfer = Transfer(
        source=RekordboxSelection([track]),
        spotify=spotify,
        matching_knowledge=AuthorityRecordingKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=FilePublicationStorage(
            tmp_path / "publications.json"
        ),
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
        local_audition=audition,
    )
    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Selected",),
        local_audio_audition=True,
    ))
    report = transfer.execute_batch(plan, transfer_id=plan.batch_id)
    draft = transfer.obtain_qualification(
        QualificationRequest(
            transfer_id=report.transfer_id,
            playlist_reference="Folder/Selected",
        ),
        TransferAuthorization(private_source=True),
    )
    transfer.record_qualification(
        draft.draft_id,
        draft.items[0].item_id,
        QualificationDecision.KEEP_PROPOSAL,
        TransferAuthorization(private_source=True),
    )
    transfer.apply_qualification(
        draft.draft_id,
        TransferAuthorization(private_source=True, spotify_write=True),
    )
    opened = transfer.audition_qualification(
        draft.draft_id,
        draft.items[0].item_id,
        TransferAuthorization(private_source=True),
    )
    monkeypatch.delattr(PlaylistSpotify, "ordered_playlist_items")
    spotify.provisional_playlist_track_uris = lambda playlist_id: None

    outcome = transfer.approve_qualification(
        draft.draft_id,
        TransferAuthorization(private_source=True, spotify_write=True),
    )

    assert outcome.status.value == "abandoned"
    with pytest.raises(AuditionHandleUnavailable):
        audition.stream(opened.handle)
    assert transfer.qualification(
        draft.draft_id, TransferAuthorization(private_source=True),
    ).status == QualificationStatus.REVIEW_REQUIRED
