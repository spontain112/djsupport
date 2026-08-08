"""Behavior tests for Rekordbox Qualification through the Transfer seam."""

from __future__ import annotations

from dataclasses import replace

import pytest

from djsupport.agent import AgentAuthorization, AgentTransferContract
from djsupport.rekordbox import Track
from djsupport.transfer import (
    AccountPublishingGuards,
    BatchPlanRequest,
    EphemeralMatchingKnowledge,
    FilePublicationStorage,
    FileTransferStorage,
    QualificationDecision,
    QualificationRequest,
    SourceSelection,
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
    )
    transfer.record_qualification(
        view.draft_id,
        item_ids["correct"],
        QualificationDecision.CORRECTION,
        spotify_reference="spotify:track:replacement00000000000",
    )
    deferred = transfer.record_qualification(
        view.draft_id,
        item_ids["defer"],
        QualificationDecision.DEFERRED,
        reason="Needs a different listening environment",
    )
    transfer.record_qualification(
        view.draft_id, item_ids["reject"], QualificationDecision.REJECT_PROPOSAL,
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

    approval = transfer.approve(playlist_id)

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
        )
    transfer.apply_qualification(
        view.draft_id,
        TransferAuthorization(private_source=True, spotify_write=True),
    )
    outcome = transfer.approve(report.playlists[0].spotify_playlist_id)

    assert outcome.status.value == "approved"
    assert outcome.collisions == ()
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
    assert document["next_actions"] == ["review"]
    rendered = str(document)
    assert "Private/Agent" not in rendered
    assert "Private Agent Review" not in rendered
    assert _proposal("agent")["uri"] not in rendered

    item_id = transfer.qualification(document["draft_id"]).items[0].item_id
    transfer.record_qualification(
        document["draft_id"], item_id, QualificationDecision.KEEP_PROPOSAL,
    )
    ready = contract.qualification_progress(
        document["draft_id"], AgentAuthorization(private_source=True),
    )
    denied_apply = contract.apply_qualification(
        document["draft_id"], AgentAuthorization(private_source=True),
    )

    assert ready["status"] == "ready"
    assert ready["next_actions"] == ["apply"]
    assert denied_apply["status"] == "authorization_required"
    assert denied_apply["required_authorizations"] == ["spotify_write"]
