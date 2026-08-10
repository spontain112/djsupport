"""Contract tests for local Beatport CLI V2 intake."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from djsupport.beatport_export import BeatportExportError
from djsupport.cache import MatchCache
from djsupport.cli import cli
from djsupport.report import PlaylistReport, SyncReport
from djsupport.transfer import (
    AccountPublishingGuards,
    BeatportExportSource,
    FilePublicationStorage,
    FileTransferStorage,
    MatchCacheKnowledge,
    Transfer,
    TransferMode,
    TransferRequest,
)


PRODUCER_GOLDEN = Path(__file__).parent / "fixtures" / "beatport_export_v2.json"


def _entity(kind: str, value: int, name: str) -> dict:
    return {
        "entity_id": f"beatport:{kind}:{value}",
        "beatport_id": value,
        "name": name,
    }


def _track(value: int, *, mix: str, duration_ms: int) -> dict:
    return {
        "entity_id": f"beatport:track:{value}",
        "beatport_id": value,
        "canonical_url": f"https://www.beatport.com/track/invented-track/{value}",
        "title": "Invented Track",
        "mix_name": mix,
        "artists": [_entity("artist", 11, "Invented Artist")],
        "remixers": [],
        "duration": {"display": "6:04", "milliseconds": duration_ms},
        "isrc": f"ZZAAA26{value:05d}",
        "bpm": 128,
        "genre": _entity("genre", 5, "Techno"),
        "key": {
            "id": 1,
            "name": "A Minor",
            "camelot_letter": "A",
            "camelot_number": 8,
        },
        "release": _entity("release", 501, "Invented Release"),
        "label": _entity("label", 601, "Invented Label"),
        "catalog_number": "INV001",
        "dates": {"published": "2026-07-01", "released": "2026-07-08"},
        "availability": {"enabled": False},
        "commerce": {"currency": "EUR", "status": "published"},
        "preview": {},
        "raw_public_facts": {"id": value, "enabled": False},
    }


def _document() -> dict:
    return {
        "schema_version": "beatport.export/v2",
        "source": {
            "kind": "chart",
            "beatport_id": 4242,
            "canonical_url": (
                "https://www.beatport.com/chart/invented-chart/4242"
            ),
            "name": "Invented Chart",
            "curator": _entity("curator", 77, "Invented Selector"),
        },
        "extracted_at": "2026-08-10T12:00:00Z",
        "track_count": 2,
        "occurrences": [
            {
                "position": 1,
                "occurrence_id": "beatport:chart:4242:1",
                "track": _track(101, mix="Original Mix", duration_ms=364000),
            },
            {
                "position": 2,
                "occurrence_id": "beatport:chart:4242:2",
                "track": _track(101, mix="Extended Mix", duration_ms=432000),
            },
        ],
    }


def test_v2_file_becomes_an_occurrence_safe_snapshot_selection(tmp_path):
    export_path = tmp_path / "selected-export.json"
    export_path.write_text(json.dumps(_document()))

    source = BeatportExportSource(export_path)
    selection = source.consume(source.selection_reference)

    assert source.default_mode is TransferMode.SNAPSHOT
    assert selection.name == "Invented Chart"
    assert selection.reference == "https://www.beatport.com/chart/invented-chart/4242"
    assert selection.curator == "Invented Selector"
    assert [track.track_id for track in selection.tracks] == [
        "beatport:track:101",
        "beatport:track:101",
    ]
    assert [track.occurrence_id for track in selection.tracks] == [
        "beatport:chart:4242:1",
        "beatport:chart:4242:2",
    ]
    assert [track.version for track in selection.tracks] == [
        "Original Mix",
        "Extended Mix",
    ]
    assert [track.duration for track in selection.tracks] == [364, 432]
    assert selection.tracks[0].source_facts["isrc"] == "ZZAAA2600101"
    assert selection.tracks[0].source_facts["availability"] == {"enabled": False}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(schema_version="beatport.export/v1"),
        lambda value: value.update(schema_version="beatport.export/v3"),
        lambda value: value.update(unexpected=True),
        lambda value: value.update(track_count=99),
        lambda value: value["occurrences"][1].update(position=3),
        lambda value: value["occurrences"][1].update(
            occurrence_id="beatport:chart:4242:99"
        ),
        lambda value: value["occurrences"][0]["track"].pop("availability"),
    ],
)
def test_invalid_exports_fail_closed_without_disclosing_the_selected_path(
    tmp_path, mutate,
):
    document = _document()
    mutate(document)
    export_path = tmp_path / "private-selected-export.json"
    export_path.write_text(json.dumps(document))

    with pytest.raises(BeatportExportError) as raised:
        source = BeatportExportSource(export_path)
        source.consume(source.selection_reference)

    assert str(export_path) not in str(raised.value)


def test_invalid_export_is_rejected_before_spotify_access(tmp_path):
    document = _document()
    document["track_count"] = 99
    export_path = tmp_path / "selected-export.json"
    export_path.write_text(json.dumps(document))
    source = BeatportExportSource(export_path)

    class NoSpotifyAccess:
        def __getattr__(self, name):
            raise AssertionError(f"Spotify must not be accessed: {name}")

    transfer = Transfer(
        source=source,
        spotify=NoSpotifyAccess(),
        matching_knowledge=MatchCacheKnowledge(
            MatchCache(str(tmp_path / "matching-knowledge.json"))
        ),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
    )

    with pytest.raises(BeatportExportError):
        transfer.execute(TransferRequest(
            source=source.selection_reference,
            preview=True,
        ))


def test_selected_export_cannot_change_before_it_is_consumed(tmp_path):
    export_path = tmp_path / "selected-export.json"
    export_path.write_text(json.dumps(_document()))
    source = BeatportExportSource(export_path)
    changed = _document()
    changed["source"]["name"] = "Changed After Selection"
    export_path.write_text(json.dumps(changed))

    with pytest.raises(BeatportExportError, match="changed after selection"):
        source.consume(source.selection_reference)


class _MatchingSpotify:
    def account_id(self):
        return "spotify-fixture-account"

    def match(self, track, threshold):
        suffix = "extended" if track.version == "Extended Mix" else "original"
        return {
            "uri": f"spotify:track:{suffix:0<22}",
            "name": track.name,
            "artist": track.artist,
            "album": track.album,
            "duration_ms": track.duration * 1000,
            "score": 100.0,
            "match_type": "exact",
        }


class _PublishingSpotify(_MatchingSpotify):
    def __init__(self):
        self.published = None

    def publish_provisional_snapshot(
        self, name, track_uris, description, publication_key,
    ):
        self.published = {
            "name": name,
            "track_uris": track_uris,
            "description": description,
            "publication_key": publication_key,
        }
        return "spotify-playlist-fixture"

    def delete_provisional_snapshot(self, playlist_id):
        raise AssertionError("validated publication must not roll back")


def test_preview_checkpoints_occurrences_and_review_facts_without_path_leak(
    tmp_path,
):
    export_path = tmp_path / "private-selected-export.json"
    export_path.write_text(json.dumps(_document()))
    source = BeatportExportSource(export_path)
    state_path = tmp_path / "transfer-state.json"
    transfer = Transfer(
        source=source,
        spotify=_MatchingSpotify(),
        matching_knowledge=MatchCacheKnowledge(
            MatchCache(str(tmp_path / "matching-knowledge.json"))
        ),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        transfer_storage=FileTransferStorage(state_path),
    )

    report = transfer.execute(TransferRequest(
        source=source.selection_reference,
        preview=True,
        transfer_id="beatport-v2-preview",
    ))

    state_text = state_path.read_text()
    assert str(export_path) not in state_text
    assert report.playlists[0].path == (
        "https://www.beatport.com/chart/invented-chart/4242"
    )
    assert [item.occurrence_id for item in report.playlists[0].review_items] == [
        "beatport:chart:4242:1",
        "beatport:chart:4242:2",
    ]
    first_facts = report.playlists[0].review_items[0].source_facts
    assert first_facts["isrc"] == "ZZAAA2600101"
    assert first_facts["bpm"] == 128
    assert first_facts["availability"] == {"enabled": False}
    assert "raw_public_facts" not in first_facts
    stored = json.loads(state_text)["transfers"]["beatport-v2-preview"]
    assert stored["selection"]["tracks"][0]["occurrence_id"] == (
        "beatport:chart:4242:1"
    )
    assert stored["selection"]["tracks"][0]["source_facts"][
        "raw_public_facts"
    ] == {"id": 101, "enabled": False}


def test_paused_v2_transfer_reloads_and_resumes_without_losing_occurrences(
    tmp_path,
):
    export_path = tmp_path / "selected-export.json"
    export_path.write_text(json.dumps(_document()))
    source = BeatportExportSource(export_path)
    state_path = tmp_path / "transfer-state.json"
    knowledge_path = tmp_path / "matching-knowledge.json"

    def build_transfer():
        return Transfer(
            source=BeatportExportSource(export_path),
            spotify=_MatchingSpotify(),
            matching_knowledge=MatchCacheKnowledge(
                MatchCache(str(knowledge_path))
            ),
            publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
            transfer_storage=FileTransferStorage(state_path),
        )

    first = build_transfer()
    first.pause()
    paused = first.execute(TransferRequest(
        source=source.selection_reference,
        preview=True,
        transfer_id="beatport-v2-resume",
    ))
    assert paused.status == "paused"

    resumed = build_transfer().execute(TransferRequest(
        source=source.selection_reference,
        preview=True,
        transfer_id="beatport-v2-resume",
    ))

    assert resumed.status == "completed"
    assert [item.occurrence_id for item in resumed.playlists[0].review_items] == [
        "beatport:chart:4242:1",
        "beatport:chart:4242:2",
    ]
    assert [item.source_position for item in resumed.playlists[0].review_items] == [
        1,
        2,
    ]
    assert resumed.playlists[0].review_items[1].source_facts["duration"] == {
        "display": "6:04",
        "milliseconds": 432000,
    }


def test_beatport_cli_selects_a_v2_file_without_passing_its_path_to_transfer(
    tmp_path, monkeypatch,
):
    export_path = tmp_path / "private-selected-export.json"
    export_path.write_text(json.dumps(_document()))
    captured = {}

    class CapturingTransfer:
        def __init__(self, **kwargs):
            captured["source"] = kwargs["source"]

        def execute(self, request):
            captured["request"] = request
            return SyncReport(
                timestamp=__import__("datetime").datetime.now(),
                threshold=request.threshold,
                dry_run=request.preview,
                playlists=[PlaylistReport("Invented Chart", "public-reference")],
                source_label="Beatport",
            )

    monkeypatch.setattr("djsupport.transfer.Transfer", CapturingTransfer)
    monkeypatch.setattr("djsupport.cli.get_client", lambda: object())
    result = CliRunner().invoke(cli, [
        "beatport", "--export-file", str(export_path), "--dry-run",
    ])

    assert result.exit_code == 0, result.output
    assert isinstance(captured["source"], BeatportExportSource)
    assert captured["request"].source.startswith("beatport-export-v2:")
    assert str(export_path) not in captured["request"].source


def test_exact_producer_golden_is_accepted_without_transformation():
    document = json.loads(PRODUCER_GOLDEN.read_text())
    source = BeatportExportSource(PRODUCER_GOLDEN)

    selection = source.consume(source.selection_reference)

    assert selection.reference == document["source"]["canonical_url"]
    assert [track.occurrence_id for track in selection.tracks] == [
        item["occurrence_id"] for item in document["occurrences"]
    ]
    assert [track.source_facts for track in selection.tracks] == [
        item["track"] for item in document["occurrences"]
    ]
    assert selection.tracks[0].track_id == selection.tracks[3].track_id
    assert selection.tracks[0].occurrence_id != selection.tracks[3].occurrence_id
    assert selection.tracks[0].source_facts["availability"]["enabled"] is False
    assert selection.tracks[1].source_facts["availability"] == {}


def test_v2_publication_is_an_occurrence_safe_path_redacted_snapshot(tmp_path):
    export_path = tmp_path / "private-selected-export.json"
    export_path.write_text(json.dumps(_document()))
    source = BeatportExportSource(export_path)
    spotify = _PublishingSpotify()
    publication_path = tmp_path / "publication-manifests.json"
    transfer_path = tmp_path / "transfer-state.json"
    transfer = Transfer(
        source=source,
        spotify=spotify,
        matching_knowledge=MatchCacheKnowledge(
            MatchCache(str(tmp_path / "matching-knowledge.json"))
        ),
        publishing_guards=AccountPublishingGuards(tmp_path / "locks"),
        publication_storage=FilePublicationStorage(publication_path),
        transfer_storage=FileTransferStorage(transfer_path),
    )

    report = transfer.execute(TransferRequest(
        source=source.selection_reference,
        transfer_id="beatport-v2-publication",
    ))

    assert report.playlists[0].action == "provisional snapshot created"
    assert report.playlists[0].publication_manifest.mode is TransferMode.SNAPSHOT
    manifest_items = report.playlists[0].publication_manifest.items
    assert [item.occurrence_id for item in manifest_items] == [
        "beatport:chart:4242:1",
        "beatport:chart:4242:2",
    ]
    assert manifest_items[0].source_facts["isrc"] == "ZZAAA2600101"
    assert "raw_public_facts" not in manifest_items[0].source_facts
    publication_text = publication_path.read_text()
    transfer_text = transfer_path.read_text()
    assert str(export_path) not in publication_text
    assert str(export_path) not in transfer_text
    assert str(export_path) not in spotify.published["description"]
    assert json.loads(publication_text)["version"] == 7
    assert json.loads(transfer_text)["version"] == 6
