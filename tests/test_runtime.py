"""Production graph tests at the private Runtime Assembly interface."""

import json

import pytest

from djsupport.agent import AgentTransferContract
from djsupport.rekordbox import Track
from djsupport.runtime import (
    MatchingKnowledgeUnavailable,
    RuntimeAssembly,
    RuntimeDependencyUnavailable,
    RuntimePaths,
    RuntimeSettings,
    SpotifyAccess,
)
from djsupport.transfer import (
    BatchPlanRequest,
    SourceSelection,
    TransferMode,
    TransferRequest,
)


class SyntheticSource:
    source_label = "Synthetic"
    default_mode = TransferMode.SNAPSHOT

    def consume(self, reference):
        return SourceSelection(
            "Synthetic Selection",
            reference,
            [
                Track(
                    track_id="synthetic-1",
                    artist="Synthetic Artist",
                    name="Synthetic Track",
                    album="Synthetic Release",
                    remixer="",
                    label="Synthetic Label",
                    genre="Electronic",
                    date_added="",
                    duration=180,
                )
            ],
        )


class SyntheticSpotify:
    def account_id(self):
        return "synthetic-account"

    def match(self, track, threshold):
        del threshold
        return {
            "uri": "spotify:track:abcdefghijklmnopqrstuv",
            "name": track.name,
            "artist": track.artist,
            "album": track.album,
            "duration_ms": track.duration * 1000,
            "score": 100.0,
            "match_type": "exact",
            "score_reasons": [],
        }

    def publish_provisional_snapshot(
        self, name, track_uris, description, publication_key,
    ):
        del name, track_uris, description, publication_key
        return "synthetic-playlist"


def selected_paths(tmp_path):
    return RuntimePaths.selected(
        tmp_path / "matching-knowledge.json",
        tmp_path / "publication-manifests.json",
    )


class TestRuntimeAssembly:
    def test_capability_graph_never_constructs_spotify_or_reads_a_source(self):
        def forbidden_spotify():
            raise AssertionError("Spotify must stay untouched")

        transfer = RuntimeAssembly(
            spotify_factory=forbidden_spotify,
        ).capability_transfer()

        document = AgentTransferContract(transfer).capabilities()

        assert document["phase"] == "capability"
        assert (
            document["capabilities"]["local_audio_audition"]["available"]
            is True
        )
        with pytest.raises(
            RuntimeDependencyUnavailable,
            match="Private source access is unavailable",
        ):
            transfer.plan_batch(BatchPlanRequest(
                playlist_references=("private-selection",), preview=True,
            ))

    def test_disabled_spotify_fails_without_constructing_the_adapter(
        self, tmp_path,
    ):
        def forbidden_spotify():
            raise AssertionError("Spotify must stay untouched")

        graph = RuntimeAssembly(spotify_factory=forbidden_spotify).assemble(
            SyntheticSource(),
            RuntimeSettings(
                paths=selected_paths(tmp_path),
                spotify_access=SpotifyAccess.DISABLED,
                retain_matching_knowledge=False,
                retain_publications=False,
            ),
        )

        with pytest.raises(
            RuntimeDependencyUnavailable,
            match="Spotify access is unavailable",
        ):
            graph.transfer.execute(TransferRequest(
                source="synthetic-selection", preview=True,
            ))

    def test_active_graph_preserves_json_paths_and_storage_formats(
        self, tmp_path,
    ):
        paths = selected_paths(tmp_path)
        assembly = RuntimeAssembly(spotify_factory=SyntheticSpotify)
        graph = assembly.assemble(
            SyntheticSource(),
            RuntimeSettings(
                paths=paths,
                spotify_access=SpotifyAccess.REQUIRED,
            ),
        )

        report = graph.transfer.execute(TransferRequest(
            source="synthetic-selection",
        ))

        assert report.total_matched == 1
        assert graph.transfer_storage.path == paths.transfer_state
        assert assembly.transfer_storage(paths) is graph.transfer_storage
        assert json.loads(paths.matching_knowledge.read_text())["version"] == 3
        assert json.loads(paths.publication_state.read_text())["version"] == 7
        assert json.loads(paths.transfer_state.read_text())["version"] == 6

    def test_ephemeral_preview_omits_knowledge_and_publication_files(
        self, tmp_path,
    ):
        paths = selected_paths(tmp_path)
        graph = RuntimeAssembly(spotify_factory=SyntheticSpotify).assemble(
            SyntheticSource(),
            RuntimeSettings(
                paths=paths,
                spotify_access=SpotifyAccess.REQUIRED,
                retain_matching_knowledge=False,
                retain_publications=False,
            ),
        )

        report = graph.transfer.execute(TransferRequest(
            source="synthetic-selection",
            preview=True,
            retain_matching_knowledge=False,
        ))

        assert report.total_matched == 1
        assert not paths.matching_knowledge.exists()
        assert not paths.publication_state.exists()
        assert paths.transfer_state.exists()

    def test_local_audio_adapters_follow_only_explicit_facts(
        self, monkeypatch, tmp_path,
    ):
        monkeypatch.setattr(
            "djsupport.local_audio.shutil.which", lambda name: None,
        )
        paths = selected_paths(tmp_path)

        disabled = RuntimeAssembly().assemble(
            SyntheticSource(),
            RuntimeSettings(
                paths=paths,
                retain_matching_knowledge=False,
                retain_publications=False,
            ),
        ).transfer
        enabled = RuntimeAssembly().assemble(
            SyntheticSource(),
            RuntimeSettings(
                paths=paths,
                retain_matching_knowledge=False,
                retain_publications=False,
                local_audio_identity=True,
                local_audio_audition=True,
            ),
        ).transfer

        assert disabled.local_audio_capability().reason == "not_configured"
        assert disabled.local_audition_capability().reason == "not_configured"
        assert enabled.local_audio_capability().reason == "binary_unavailable"
        assert enabled.local_audition_capability().available is True

    def test_unsupported_knowledge_schema_has_a_runtime_error(self, tmp_path):
        paths = selected_paths(tmp_path)
        paths.matching_knowledge.write_text('{"version": 999}')

        with pytest.raises(MatchingKnowledgeUnavailable):
            RuntimeAssembly().assemble(
                SyntheticSource(), RuntimeSettings(paths=paths),
            )
