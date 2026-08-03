"""Behavior tests for opt-in local audio identity at the Transfer seam."""

import json
from pathlib import Path

import pytest
import requests

from djsupport.cache import MatchCache
from djsupport.local_audio import LocalAudioCapability
from djsupport.rekordbox import Track
from djsupport.report import save_report
from djsupport.transfer import (
    AccountPublishingGuards,
    BatchPlanRequest,
    EphemeralMatchingKnowledge,
    FilePublicationStorage,
    FileTransferStorage,
    DriftResolution,
    LocalAudioObservation,
    MatchCacheKnowledge,
    SourceSelection,
    Transfer,
    TransferMode,
    TransferRequest,
)


def _track(*, track_id: str, artist: str, title: str) -> Track:
    return Track(
        track_id=track_id,
        artist=artist,
        name=title,
        album="",
        remixer="",
        label="",
        genre="",
        date_added="",
        duration=360,
        location="file:///synthetic/selected-track.wav",
    )


class SelectedSource:
    source_label = "Rekordbox"
    default_mode = TransferMode.MIRROR

    def __init__(self, track: Track) -> None:
        self.track = track

    def consume(self, reference: str) -> SourceSelection:
        return SourceSelection("Selected", reference, [self.track])

    def consume_batch(self, references, whole_library):
        return tuple(self.consume(reference) for reference in references)


class FixedLocalAudio:
    def __init__(self) -> None:
        self.observed = []

    def observe(self, track: Track) -> LocalAudioObservation:
        self.observed.append(track.track_id)
        return LocalAudioObservation.available(
            fingerprint="synthetic-fingerprint-001",
            algorithm="chromaprint",
            algorithm_version="1.6.0",
            duration=360,
        )

    def capability(self) -> LocalAudioCapability:
        return LocalAudioCapability(
            available=True,
            algorithm="chromaprint",
            algorithm_version="1.6.0",
        )


class SpotifyBoundary:
    def __init__(self, account_id="spotify-account-one") -> None:
        self._account_id = account_id
        self.searches = []
        self.playlists = {}

    def account_id(self):
        return self._account_id

    def match(self, track, threshold):
        self.searches.append((track.artist, track.name, threshold))
        return {
            "uri": "spotify:track:approved",
            "name": "Known Recording",
            "artist": "Known Artist",
            "score": 97.0,
            "match_type": "exact",
        }

    def publish_provisional_snapshot(
        self, name, track_uris, description, publication_key,
    ):
        playlist_id = "provisional-one"
        self.playlists[playlist_id] = list(track_uris)
        return playlist_id

    def delete_provisional_snapshot(self, playlist_id):
        self.playlists.pop(playlist_id, None)

    def provisional_playlist_track_uris(self, playlist_id):
        return list(self.playlists[playlist_id])

    def spotify_track(self, uri):
        return {"uri": uri, "is_playable": True}


def test_ordinary_transfer_does_not_persist_private_audio_location(tmp_path):
    state_path = tmp_path / "transfers.json"
    Transfer(
        source=SelectedSource(_track(
            track_id="rb-original", artist="Known Artist", title="Known Recording",
        )),
        spotify=SpotifyBoundary(),
        matching_knowledge=MatchCacheKnowledge(MatchCache(
            tmp_path / "matching-knowledge.json",
        )),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        transfer_storage=FileTransferStorage(state_path),
    ).execute(TransferRequest(
        source="Selected", preview=True, transfer_id="ordinary-transfer",
    ))

    rendered = state_path.read_text()
    assert "selected-track.wav" not in rendered
    assert '"location"' not in rendered


def test_approved_local_identity_recovers_damaged_metadata_without_spotify(tmp_path):
    spotify = SpotifyBoundary()
    cache_path = tmp_path / "matching-knowledge.json"
    cache = MatchCache(cache_path)
    publications = FilePublicationStorage(tmp_path / "publications.json")
    local_audio = FixedLocalAudio()
    first = Transfer(
        source=SelectedSource(_track(
            track_id="rb-original", artist="Known Artist", title="Known Recording",
        )),
        spotify=spotify,
        matching_knowledge=MatchCacheKnowledge(cache),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=publications,
        local_audio=local_audio,
    )

    published = first.execute(TransferRequest(
        source="Selected", local_audio_identity=True,
    ))
    first.approve(published.playlists[0].spotify_playlist_id)

    restored_cache = MatchCache(cache_path)
    restored_cache.load()
    later = Transfer(
        source=SelectedSource(_track(
            track_id="rb-later", artist="", title="Damaged Metadata",
        )),
        spotify=spotify,
        matching_knowledge=MatchCacheKnowledge(restored_cache),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        local_audio=local_audio,
    ).execute(TransferRequest(
        source="Selected", preview=True, local_audio_identity=True,
    ))

    assert spotify.searches == [("Known Artist", "Known Recording", 80)]
    assert later.total_matched == 1
    assert later.playlists[0].matched[0].spotify_uri == "spotify:track:approved"
    assert later.playlists[0].matched[0].match_type == "approved_local_audio"


def test_local_identity_requires_durable_matching_knowledge_before_audio_access(
    tmp_path,
):
    local_audio = FixedLocalAudio()
    transfer = Transfer(
        source=SelectedSource(_track(
            track_id="rb-original", artist="Known Artist", title="Known Recording",
        )),
        spotify=SpotifyBoundary(),
        matching_knowledge=EphemeralMatchingKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        local_audio=local_audio,
    )

    try:
        transfer.execute(TransferRequest(
            source="Selected", preview=True, local_audio_identity=True,
        ))
    except ValueError as exc:
        assert str(exc) == (
            "Local audio identity requires durable matching knowledge; "
            "remove --no-cache"
        )
    else:
        raise AssertionError("local identity should reject ephemeral knowledge")

    assert local_audio.observed == []


def test_batch_preflight_counts_local_work_without_calculating_fingerprints(tmp_path):
    local_audio = FixedLocalAudio()
    local_audio.preflight = lambda track: "eligible"
    cache = MatchCache(tmp_path / "matching-knowledge.json")
    transfer = Transfer(
        source=SelectedSource(_track(
            track_id="rb-original", artist="Known Artist", title="Known Recording",
        )),
        spotify=SpotifyBoundary(),
        matching_knowledge=MatchCacheKnowledge(cache),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        local_audio=local_audio,
    )

    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Selected",),
        preview=True,
        local_audio_identity=True,
    ))

    assert plan.local_audio_eligible == 1
    assert plan.local_audio_indexed == 0
    assert plan.local_audio_pending == 1
    assert plan.local_audio_unavailable == 0
    assert local_audio.observed == []


def test_batch_preflight_only_counts_compatible_fingerprint_evidence_as_indexed(
    tmp_path,
):
    track = _track(
        track_id="rb-original", artist="Known Artist", title="Known Recording",
    )
    local_audio = FixedLocalAudio()
    local_audio.preflight = lambda candidate: "eligible"
    cache = MatchCache(tmp_path / "matching-knowledge.json")
    cache.retain_fingerprint_observation(
        algorithm="chromaprint",
        algorithm_version="1.5.0",
        fingerprint="older-version-evidence",
        audio_duration=track.duration,
        source_track_id=track.track_id,
    )
    transfer = Transfer(
        source=SelectedSource(track),
        spotify=SpotifyBoundary(),
        matching_knowledge=MatchCacheKnowledge(cache),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        local_audio=local_audio,
    )

    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Selected",),
        preview=True,
        local_audio_identity=True,
    ))

    assert plan.local_audio_indexed == 0
    assert plan.local_audio_pending == 1


def test_completed_local_observation_is_not_recalculated_after_spotify_timeout(
    tmp_path,
):
    class RecoveringSpotify(SpotifyBoundary):
        def __init__(self):
            super().__init__()
            self.fail = True

        def match(self, track, threshold):
            if self.fail:
                raise requests.Timeout("synthetic timeout")
            return super().match(track, threshold)

    spotify = RecoveringSpotify()
    local_audio = FixedLocalAudio()
    cache = MatchCache(tmp_path / "matching-knowledge.json")
    state_path = tmp_path / "transfers.json"
    source = SelectedSource(_track(
        track_id="rb-original", artist="Known Artist", title="Known Recording",
    ))
    request = TransferRequest(
        source="Selected",
        preview=True,
        transfer_id="stable-transfer",
        local_audio_identity=True,
    )

    first = Transfer(
        source=source,
        spotify=spotify,
        matching_knowledge=MatchCacheKnowledge(cache),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        transfer_storage=FileTransferStorage(state_path),
        local_audio=local_audio,
    )
    with pytest.raises(requests.Timeout):
        first.execute(request)
    spotify.fail = False

    restored_cache = MatchCache(tmp_path / "matching-knowledge.json")
    restored_cache.load()
    resumed = Transfer(
        source=source,
        spotify=spotify,
        matching_knowledge=MatchCacheKnowledge(restored_cache),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        transfer_storage=FileTransferStorage(state_path),
        local_audio=local_audio,
    ).execute(request)

    assert resumed.total_matched == 1
    assert local_audio.observed == ["rb-original"]
    assert json.loads(state_path.read_text())["version"] == 3


def test_explicit_drift_revocation_removes_local_identity_authority(tmp_path):
    spotify = SpotifyBoundary()
    cache = MatchCache(tmp_path / "matching-knowledge.json")
    knowledge = MatchCacheKnowledge(cache)
    publications = FilePublicationStorage(tmp_path / "publications.json")
    local_audio = FixedLocalAudio()
    first = Transfer(
        source=SelectedSource(_track(
            track_id="rb-original", artist="Known Artist", title="Known Recording",
        )),
        spotify=spotify,
        matching_knowledge=knowledge,
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=publications,
        local_audio=local_audio,
    )
    published = first.execute(TransferRequest(
        source="Selected", local_audio_identity=True,
    ))
    playlist_id = published.playlists[0].spotify_playlist_id
    first.approve(playlist_id)
    spotify.playlists[playlist_id] = []

    damaged_source = SelectedSource(_track(
        track_id="rb-later", artist="", title="Damaged Metadata",
    ))
    Transfer(
        source=damaged_source,
        spotify=spotify,
        matching_knowledge=knowledge,
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=publications,
        local_audio=local_audio,
    ).execute(TransferRequest(
        source="Selected",
        local_audio_identity=True,
        drift_resolution=DriftResolution.REVOKE,
    ))

    after_revoke = Transfer(
        source=damaged_source,
        spotify=spotify,
        matching_knowledge=knowledge,
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        local_audio=local_audio,
    ).execute(TransferRequest(
        source="Selected", preview=True, local_audio_identity=True,
    ))

    assert after_revoke.playlists[0].local_audio_reused == 0
    assert spotify.searches == [
        ("Known Artist", "Known Recording", 80),
        ("", "Damaged Metadata", 80),
    ]


def test_unavailable_local_audio_falls_back_without_exposing_private_details(
    tmp_path,
):
    class UnavailableLocalAudio:
        def observe(self, track):
            return LocalAudioObservation.unavailable("missing_file")

    spotify = SpotifyBoundary()
    report = Transfer(
        source=SelectedSource(_track(
            track_id="rb-original", artist="Known Artist", title="Known Recording",
        )),
        spotify=spotify,
        matching_knowledge=MatchCacheKnowledge(
            MatchCache(tmp_path / "matching-knowledge.json")
        ),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        local_audio=UnavailableLocalAudio(),
    ).execute(TransferRequest(
        source="Selected", preview=True, local_audio_identity=True,
    ))

    playlist = report.playlists[0]
    assert report.total_matched == 1
    assert playlist.local_audio_eligible == 0
    assert playlist.local_audio_observed == 0
    assert playlist.local_audio_unavailable == 1
    assert playlist.local_audio_reused == 0
    report_path = tmp_path / "report.md"
    save_report(report, report_path)
    rendered = report_path.read_text()
    assert (
        "**Local audio:** 0 eligible | 0 observed | 0 Approved Match reuses "
        "| 1 unavailable"
    ) in rendered
    assert "selected-track.wav" not in rendered


def test_revocation_is_scoped_to_the_approving_spotify_account(tmp_path):
    cache = MatchCache(tmp_path / "matching-knowledge.json")
    knowledge = MatchCacheKnowledge(cache)
    publications = FilePublicationStorage(tmp_path / "publications.json")
    local_audio = FixedLocalAudio()

    def approve_for(account_id, artist, title):
        spotify = SpotifyBoundary(account_id)
        transfer = Transfer(
            source=SelectedSource(_track(
                track_id=f"rb-{account_id}", artist=artist, title=title,
            )),
            spotify=spotify,
            matching_knowledge=knowledge,
            publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
            publication_storage=publications,
            local_audio=local_audio,
        )
        published = transfer.execute(TransferRequest(
            source=f"Selected-{account_id}", local_audio_identity=True,
        ))
        playlist_id = published.playlists[0].spotify_playlist_id
        transfer.approve(playlist_id)
        return spotify, playlist_id

    spotify_a, playlist_a = approve_for(
        "spotify-account-a", "Account A Artist", "Account A Recording",
    )
    spotify_b, _ = approve_for(
        "spotify-account-b", "Account B Artist", "Account B Recording",
    )
    spotify_a.playlists[playlist_a] = []
    damaged = SelectedSource(_track(
        track_id="rb-damaged", artist="", title="Damaged Metadata",
    ))
    Transfer(
        source=damaged,
        spotify=spotify_a,
        matching_knowledge=knowledge,
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=publications,
        local_audio=local_audio,
    ).execute(TransferRequest(
        source="Selected-spotify-account-a",
        local_audio_identity=True,
        drift_resolution=DriftResolution.REVOKE,
    ))

    account_b_result = Transfer(
        source=damaged,
        spotify=spotify_b,
        matching_knowledge=knowledge,
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        local_audio=local_audio,
    ).execute(TransferRequest(
        source="Selected-spotify-account-b",
        preview=True,
        local_audio_identity=True,
    ))

    assert account_b_result.playlists[0].local_audio_reused == 1
    assert spotify_b.searches == [("Account B Artist", "Account B Recording", 80)]


def test_conflicting_fingerprint_approvals_suspend_automatic_reuse(tmp_path):
    class ConflictingSpotify(SpotifyBoundary):
        def __init__(self):
            super().__init__()
            self.next_playlist = 0

        def match(self, track, threshold):
            self.searches.append((track.artist, track.name, threshold))
            suffix = "a" if track.artist == "Artist A" else "b"
            return {
                "uri": f"spotify:track:{suffix}",
                "name": f"Recording {suffix.upper()}",
                "artist": track.artist,
                "score": 97.0,
                "match_type": "exact",
            }

        def publish_provisional_snapshot(
            self, name, track_uris, description, publication_key,
        ):
            self.next_playlist += 1
            playlist_id = f"provisional-{self.next_playlist}"
            self.playlists[playlist_id] = list(track_uris)
            return playlist_id

    spotify = ConflictingSpotify()
    cache = MatchCache(tmp_path / "matching-knowledge.json")
    knowledge = MatchCacheKnowledge(cache)
    publications = FilePublicationStorage(tmp_path / "publications.json")
    local_audio = FixedLocalAudio()

    def publish(reference, artist):
        transfer = Transfer(
            source=SelectedSource(_track(
                track_id=f"rb-{artist}", artist=artist, title="Recording",
            )),
            spotify=spotify,
            matching_knowledge=knowledge,
            publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
            publication_storage=publications,
            local_audio=local_audio,
        )
        report = transfer.execute(TransferRequest(
            source=reference, local_audio_identity=True,
        ))
        return transfer, report.playlists[0].spotify_playlist_id

    first, playlist_a = publish("Selection A", "Artist A")
    second, playlist_b = publish("Selection B", "Artist B")
    first.approve(playlist_a)

    conflict = second.approve(playlist_b)

    assert conflict.status.value == "needs review"
    assert len(conflict.conflicts) == 1
    searches_before = len(spotify.searches)
    after_conflict = Transfer(
        source=SelectedSource(_track(
            track_id="rb-damaged", artist="", title="Damaged Metadata",
        )),
        spotify=spotify,
        matching_knowledge=knowledge,
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        local_audio=local_audio,
    ).execute(TransferRequest(
        source="Damaged", preview=True, local_audio_identity=True,
    ))
    assert after_conflict.playlists[0].local_audio_reused == 0
    assert len(spotify.searches) == searches_before + 1
