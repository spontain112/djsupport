"""Contract tests for private local-source audition media."""

from __future__ import annotations

import json

import pytest

from djsupport.local_audition import (
    AuditionHandleUnavailable,
    AuditionRangeNotSatisfiable,
    LocalSourceAudition,
)
from djsupport.rekordbox import Track
from djsupport.transfer import (
    AccountPublishingGuards,
    BatchPlanRequest,
    EphemeralMatchingKnowledge,
    FileTransferStorage,
    LocalAuditionResult,
    QualificationRequest,
    SourceSelection,
    Transfer,
    TransferAuthorization,
    TransferMode,
)


def _track(location: str) -> Track:
    return Track(
        track_id="selected-occurrence",
        name="Invented Source",
        artist="Invented Artist",
        album="Invented Release",
        remixer="",
        label="Invented Label",
        genre="Synthetic",
        date_added="2026-08-08",
        duration=180,
        location=location,
    )


class SelectedSource:
    source_label = "Rekordbox"
    default_mode = TransferMode.MIRROR

    def __init__(self, track: Track) -> None:
        self.track = track

    def consume(self, reference):
        return SourceSelection("Selected", reference, [self.track])

    def consume_batch(self, references, whole_library):
        return tuple(self.consume(reference) for reference in references)


class PreviewSpotify:
    def account_id(self):
        return "spotify-account-one"

    def match(self, track, threshold):
        return {
            "uri": "spotify:track:proposal000000000000",
            "name": "Invented Proposal",
            "artist": "Invented Spotify Artist",
            "album": "Invented Spotify Release",
            "duration_ms": 180_000,
            "score": 96.0,
            "match_type": "exact",
        }


class RecordingAudition:
    def __init__(self) -> None:
        self.opened = []

    def open(self, transfer_id, item_id, track):
        self.opened.append((transfer_id, item_id, track.track_id, track.location))
        return LocalAuditionResult(
            status="available",
            handle="opaque-process-handle",
            media_type="audio/wav",
            content_length=16,
        )


class ForbiddenIdentity:
    def observe(self, track):
        raise AssertionError("audition must not calculate a fingerprint")


def test_transfer_authorizes_only_the_selected_audition_occurrence(tmp_path):
    private_location = "file:///owner/private/owner-only-name.wav"
    audition = RecordingAudition()
    storage_path = tmp_path / "transfers.json"
    transfer = Transfer(
        source=SelectedSource(_track(private_location)),
        spotify=PreviewSpotify(),
        matching_knowledge=EphemeralMatchingKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        transfer_storage=FileTransferStorage(storage_path),
        local_audio=ForbiddenIdentity(),
        local_audition=audition,
    )
    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Selected",),
        preview=True,
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
    item_id = draft.items[0].item_id

    with pytest.raises(PermissionError, match="private_source"):
        transfer.audition_qualification(
            draft.draft_id, item_id, TransferAuthorization(),
        )
    with pytest.raises(ValueError, match="outside the selected"):
        transfer.audition_qualification(
            draft.draft_id, "unselected-item",
            TransferAuthorization(private_source=True),
        )
    result = transfer.audition_qualification(
        draft.draft_id,
        item_id,
        TransferAuthorization(private_source=True, spotify_write=False),
    )

    assert result.status == "available"
    assert result.handle == "opaque-process-handle"
    assert audition.opened == [(
        draft.transfer_id, item_id, "selected-occurrence", private_location,
    )]
    persisted = storage_path.read_text()
    assert "owner-only-name" not in persisted
    assert "opaque-process-handle" not in persisted
    assert "fingerprint" not in persisted


def test_local_audition_streams_full_and_bounded_ranges_without_path_disclosure(
    tmp_path,
):
    media = tmp_path / "owner-private-name.wav"
    media.write_bytes(b"0123456789abcdef")
    now = [100.0]
    adapter = LocalSourceAudition(
        ttl_seconds=10,
        max_range_bytes=8,
        clock=lambda: now[0],
    )

    opened = adapter.open("transfer-one", "item-one", _track(media.as_uri()))
    full = adapter.stream(opened.handle)
    partial = adapter.stream(opened.handle, "bytes=2-7")

    assert opened.status == "available"
    assert opened.media_type == "audio/wav"
    assert opened.content_length == 16
    assert "owner-private-name" not in repr(opened)
    assert full.status_code == 200
    assert full.content_length == 16
    assert b"".join(full.body) == b"0123456789abcdef"
    assert partial.status_code == 206
    assert partial.content_range == "bytes 2-7/16"
    assert partial.content_length == 6
    assert b"".join(partial.body) == b"234567"

    with pytest.raises(AuditionRangeNotSatisfiable) as excessive:
        adapter.stream(opened.handle, "bytes=0-12")
    assert excessive.value.total_size == 16
    with pytest.raises(AuditionRangeNotSatisfiable):
        adapter.stream(opened.handle, "bytes=99-100")
    now[0] = 111.0
    with pytest.raises(AuditionHandleUnavailable):
        adapter.stream(opened.handle)


@pytest.mark.parametrize(
    ("location", "reason"),
    [
        ("", "missing_location"),
        ("https://example.test/audio.wav", "unsupported_location"),
        ("file://remote-host/private.wav", "unsupported_location"),
        ("file:///private/*.wav", "unsafe_location"),
        ("file:///private/missing.wav", "missing_file"),
        ("file:///private/source.txt", "unsupported_format"),
    ],
)
def test_local_audition_unavailability_is_path_free(tmp_path, location, reason):
    adapter = LocalSourceAudition()

    result = adapter.open("transfer-one", "item-one", _track(location))

    assert result.status == "unavailable"
    assert result.reason == reason
    assert result.handle is None
    if location:
        assert location not in json.dumps(result.__dict__)


def test_regenerated_handle_invalidates_prior_handle_and_transfer_scope(tmp_path):
    media = tmp_path / "private-source.wav"
    media.write_bytes(b"synthetic")
    adapter = LocalSourceAudition()

    first = adapter.open("transfer-one", "item-one", _track(media.as_uri()))
    second = adapter.open("transfer-one", "item-one", _track(media.as_uri()))

    assert first.handle != second.handle
    with pytest.raises(AuditionHandleUnavailable):
        adapter.stream(first.handle)
    assert b"".join(adapter.stream(second.handle).body) == b"synthetic"
    adapter.invalidate_transfer("transfer-one")
    with pytest.raises(AuditionHandleUnavailable):
        adapter.stream(second.handle)


def test_empty_supported_media_has_truthful_zero_length_response(tmp_path):
    media = tmp_path / "empty-source.wav"
    media.write_bytes(b"")
    adapter = LocalSourceAudition()
    opened = adapter.open("transfer-one", "item-one", _track(media.as_uri()))

    stream = adapter.stream(opened.handle)

    assert stream.status_code == 200
    assert stream.content_length == 0
    assert b"".join(stream.body) == b""


def test_unreadable_media_is_a_path_free_per_track_outcome(tmp_path, monkeypatch):
    media = tmp_path / "owner-private-unreadable.wav"
    media.write_bytes(b"synthetic")
    real_open = type(media).open

    def denied_open(path, *args, **kwargs):
        if path == media:
            raise PermissionError("synthetic denial")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(type(media), "open", denied_open)

    result = LocalSourceAudition().open(
        "transfer-one", "item-one", _track(media.as_uri()),
    )

    assert result.status == "unavailable"
    assert result.reason == "unreadable_media"
    assert "owner-private-unreadable" not in repr(result)


def test_qualification_fact_honestly_reports_missing_selected_media(tmp_path):
    missing = tmp_path / "private-missing-source.wav"
    transfer = Transfer(
        source=SelectedSource(_track(missing.as_uri())),
        spotify=PreviewSpotify(),
        matching_knowledge=EphemeralMatchingKnowledge(),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
        local_audition=LocalSourceAudition(),
    )
    plan = transfer.plan_batch(BatchPlanRequest(
        playlist_references=("Folder/Selected",),
        preview=True,
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

    assert draft.items[0].audition_status == "unavailable"
    assert draft.items[0].audition_reason == "missing_file"
    assert "private-missing-source" not in json.dumps(
        draft.items[0].__dict__, default=str,
    )
