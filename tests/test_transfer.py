"""Behavior tests at the public Transfer seam."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from click.testing import CliRunner

from djsupport.cli import cli
from djsupport.rekordbox import Track
from djsupport.report import PlaylistReport, SyncReport
from djsupport.transfer import (
    FilePublicationStorage,
    FileTransferStorage,
    SourceSelection,
    Transfer,
    TransferRequest,
)


class FixtureBeatportSource:
    source_label = "Beatport"

    def __init__(self, fixture: Path) -> None:
        self.fixture = fixture

    def consume(self, reference: str) -> SourceSelection:
        data = json.loads(self.fixture.read_text())
        tracks = [
            Track(
                track_id=item["track_id"], artist=item["artist"], name=item["name"],
                album="", remixer="", label="", genre="", date_added="",
            )
            for item in data["tracks"]
        ]
        return SourceSelection(data["name"], data["reference"], tracks)


class StatefulSpotify:
    def __init__(self, matches=None) -> None:
        self.matches = matches or {}
        self.searches = []
        self.playlists = {"existing": ["spotify:track:untouched"]}
        self.publication_keys = {}

    def account_id(self):
        return "spotify-user-1"

    def publish_provisional_snapshot(
        self, name, track_uris, description, publication_key,
    ):
        if publication_key in self.publication_keys:
            playlist_id = self.publication_keys[publication_key]
            self.playlists[playlist_id]["tracks"] = list(track_uris)
            return playlist_id
        playlist_id = f"snapshot-{len(self.playlists)}"
        self.playlists[playlist_id] = {
            "name": name,
            "tracks": list(track_uris),
            "description": description,
        }
        self.publication_keys[publication_key] = playlist_id
        return playlist_id

    def delete_provisional_snapshot(self, playlist_id):
        del self.playlists[playlist_id]

    def match(self, track, threshold):
        self.searches.append((track.artist, track.name, threshold))
        return self.matches.get((track.artist, track.name))


class InMemoryStorage:
    def __init__(self) -> None:
        self.matches = {}
        self.failures = set()
        self.checkpoints = 0
        self.playlist_state = {"must": "remain unchanged"}
        self.playlist_writes = 0
        self.publications = []

    def lookup(self, track, threshold):
        result = self.matches.get((track.artist, track.name))
        return result if result and result["score"] >= threshold else None

    def should_retry(self, track, threshold, retry_days, force):
        key = (track.artist, track.name)
        return key not in self.failures or force

    def retain(self, track, threshold, result):
        key = (track.artist, track.name)
        if result is None:
            self.failures.add(key)
        else:
            self.matches[key] = result

    def checkpoint(self):
        self.checkpoints += 1

    def retain_publication(self, manifest):
        self.publications.append(manifest)
        self.playlist_writes += 1


FIXTURE = Path(__file__).parent / "fixtures" / "beatport_chart.json"


def _match(uri, name, artist):
    return {
        "uri": uri, "name": name, "artist": artist,
        "score": 96.0, "match_type": "exact",
    }


def test_preview_reuses_and_retains_matching_knowledge_without_playlist_writes():
    source = FixtureBeatportSource(FIXTURE)
    spotify = StatefulSpotify({
        ("New Artist", "New Track"): _match(
            "spotify:track:new", "New Track", "New Artist",
        ),
    })
    storage = InMemoryStorage()
    storage.matches[("Known Artist", "Known Track")] = _match(
        "spotify:track:known", "Known Track", "Known Artist",
    )
    original_playlists = dict(spotify.playlists)
    original_state = dict(storage.playlist_state)

    report = Transfer(
        source=source, spotify=spotify, matching_knowledge=storage,
    ).execute(TransferRequest(source="fixture", preview=True))

    playlist = report.playlists[0]
    assert report.dry_run is True
    assert playlist.action == "preview"
    assert playlist.match_rate == 100.0
    assert playlist.cache_hits == 1
    assert playlist.api_lookups == 1
    assert spotify.searches == [("New Artist", "New Track", 80)]
    assert ("New Artist", "New Track") in storage.matches
    assert storage.checkpoints >= 1
    assert spotify.playlists == original_playlists
    assert storage.playlist_state == original_state
    assert storage.playlist_writes == 0


def test_preview_with_zero_acceptable_matches_succeeds_with_zero_percent():
    spotify = StatefulSpotify()
    storage = InMemoryStorage()

    report = Transfer(
        source=FixtureBeatportSource(FIXTURE),
        spotify=spotify,
        matching_knowledge=storage,
    ).execute(TransferRequest(source="fixture", preview=True))

    assert report.overall_match_rate == 0.0
    assert report.total_matched == 0
    assert report.total_unmatched == 2
    assert storage.checkpoints >= 1
    assert spotify.playlists == {"existing": ["spotify:track:untouched"]}


class TestSnapshotPublication:

    def test_paused_transfer_reloads_and_resumes_without_repeating_work(self, tmp_path):
        matches = {
            ("Known Artist", "Known Track"): _match(
                "spotify:track:known", "Known Track", "Known Artist",
            ),
            ("New Artist", "New Track"): _match(
                "spotify:track:new", "New Track", "New Artist",
            ),
        }
        spotify = StatefulSpotify(matches)
        knowledge = InMemoryStorage()
        state_path = tmp_path / "transfers.json"
        first = Transfer(
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=knowledge, publication_storage=knowledge,
            transfer_storage=FileTransferStorage(state_path),
        )
        first.pause()

        paused = first.execute(TransferRequest(source="fixture"))

        assert paused.status == "paused"
        assert paused.playlists[0].action == "paused"
        assert spotify.searches == [("Known Artist", "Known Track", 80)]
        assert "snapshot-1" not in spotify.playlists

        resumed_knowledge = InMemoryStorage()
        resumed = Transfer(
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=resumed_knowledge, publication_storage=knowledge,
            transfer_storage=FileTransferStorage(state_path),
        ).execute(TransferRequest(source="fixture", transfer_id=paused.transfer_id))

        assert resumed.status == "completed"
        assert resumed.playlists[0].action == "provisional snapshot created"
        assert spotify.searches == [
            ("Known Artist", "Known Track", 80),
            ("New Artist", "New Track", 80),
        ]
        assert len(knowledge.publications) == 1
        assert list(spotify.playlists).count("snapshot-1") == 1

    def test_user_cancellation_is_persisted_as_paused_by_default(self, tmp_path):
        class CancellingSpotify(StatefulSpotify):
            def __init__(self):
                super().__init__({
                    ("Known Artist", "Known Track"): _match(
                        "spotify:track:known", "Known Track", "Known Artist",
                    ),
                })

            def match(self, track, threshold):
                if track.track_id == "bp-2":
                    raise KeyboardInterrupt
                return super().match(track, threshold)

        states = FileTransferStorage(tmp_path / "transfers.json")
        with pytest.raises(KeyboardInterrupt):
            Transfer(
                source=FixtureBeatportSource(FIXTURE), spotify=CancellingSpotify(),
                matching_knowledge=InMemoryStorage(),
                publication_storage=InMemoryStorage(), transfer_storage=states,
            ).execute(TransferRequest(source="fixture"))

        persisted = next(iter(FileTransferStorage(states.path).transfers.values()))
        assert persisted.status.value == "paused"
        assert persisted.next_track_index == 1

    def test_abandonment_is_explicit_persisted_and_cannot_be_resumed(self, tmp_path):
        spotify = StatefulSpotify({
            ("Known Artist", "Known Track"): _match(
                "spotify:track:known", "Known Track", "Known Artist",
            ),
        })
        state_path = tmp_path / "transfers.json"
        transfer = Transfer(
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=InMemoryStorage(),
            publication_storage=InMemoryStorage(),
            transfer_storage=FileTransferStorage(state_path),
        )
        transfer.pause()
        paused = transfer.execute(TransferRequest(source="fixture"))

        transfer.abandon(paused.transfer_id)

        reloaded = FileTransferStorage(state_path)
        assert reloaded.load_transfer(paused.transfer_id).status.value == "abandoned"
        with pytest.raises(ValueError, match="abandoned"):
            Transfer(
                source=FixtureBeatportSource(FIXTURE), spotify=spotify,
                matching_knowledge=InMemoryStorage(),
                publication_storage=InMemoryStorage(), transfer_storage=reloaded,
            ).execute(TransferRequest(
                source="fixture", transfer_id=paused.transfer_id,
            ))
        assert "snapshot-1" not in spotify.playlists

    def test_resume_after_publishing_does_not_duplicate_spotify_effect(self, tmp_path):
        class InterruptedPublicationStorage(InMemoryStorage):
            def __init__(self):
                super().__init__()
                self.interrupt = True

            def retain_publication(self, manifest):
                if self.interrupt:
                    self.interrupt = False
                    raise KeyboardInterrupt
                super().retain_publication(manifest)

        matches = {
            ("Known Artist", "Known Track"): _match(
                "spotify:track:known", "Known Track", "Known Artist",
            ),
            ("New Artist", "New Track"): _match(
                "spotify:track:new", "New Track", "New Artist",
            ),
        }
        spotify = StatefulSpotify(matches)
        knowledge = InMemoryStorage()
        publications = InterruptedPublicationStorage()
        states = FileTransferStorage(tmp_path / "transfers.json")
        transfer = Transfer(
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=knowledge, publication_storage=publications,
            transfer_storage=states,
        )

        with pytest.raises(KeyboardInterrupt):
            transfer.execute(TransferRequest(source="fixture"))
        transfer_id = next(iter(states.transfers))

        resumed = Transfer(
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=knowledge, publication_storage=publications,
            transfer_storage=FileTransferStorage(states.path),
        ).execute(TransferRequest(source="fixture", transfer_id=transfer_id))

        assert resumed.status == "completed"
        assert len([key for key in spotify.playlists if key.startswith("snapshot-")]) == 1
        assert len(publications.publications) == 1

        repeated = Transfer(
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=knowledge, publication_storage=publications,
            transfer_storage=FileTransferStorage(states.path),
        ).execute(TransferRequest(source="fixture", transfer_id=transfer_id))

        assert repeated.status == "completed"
        assert len([key for key in spotify.playlists if key.startswith("snapshot-")]) == 1
        assert len(publications.publications) == 1

    def test_crash_before_publication_checkpoint_reuses_idempotency_key(self, tmp_path):
        class CrashAfterSpotifyCreate(StatefulSpotify):
            def __init__(self, matches):
                super().__init__(matches)
                self.crash = True

            def publish_provisional_snapshot(self, *args):
                playlist_id = super().publish_provisional_snapshot(*args)
                if self.crash:
                    self.crash = False
                    raise KeyboardInterrupt
                return playlist_id

        matches = {
            ("Known Artist", "Known Track"): _match(
                "spotify:track:known", "Known Track", "Known Artist",
            ),
            ("New Artist", "New Track"): _match(
                "spotify:track:new", "New Track", "New Artist",
            ),
        }
        spotify = CrashAfterSpotifyCreate(matches)
        knowledge = InMemoryStorage()
        publications = InMemoryStorage()
        states = FileTransferStorage(tmp_path / "transfers.json")
        transfer_id = "durable-publication"

        with pytest.raises(KeyboardInterrupt):
            Transfer(
                source=FixtureBeatportSource(FIXTURE), spotify=spotify,
                matching_knowledge=knowledge, publication_storage=publications,
                transfer_storage=states,
            ).execute(TransferRequest(source="fixture", transfer_id=transfer_id))

        Transfer(
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=knowledge, publication_storage=publications,
            transfer_storage=FileTransferStorage(states.path),
        ).execute(TransferRequest(source="fixture", transfer_id=transfer_id))

        assert len([key for key in spotify.playlists if key.startswith("snapshot-")]) == 1

    def test_resume_rejects_a_different_spotify_account(self, tmp_path):
        spotify = StatefulSpotify()
        states = FileTransferStorage(tmp_path / "transfers.json")
        transfer = Transfer(
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=InMemoryStorage(),
            publication_storage=InMemoryStorage(), transfer_storage=states,
        )
        transfer.pause()
        paused = transfer.execute(TransferRequest(source="fixture"))
        spotify.account_id = lambda: "spotify-user-2"

        with pytest.raises(ValueError, match="another Spotify account"):
            Transfer(
                source=FixtureBeatportSource(FIXTURE), spotify=spotify,
                matching_knowledge=InMemoryStorage(),
                publication_storage=InMemoryStorage(), transfer_storage=states,
            ).execute(TransferRequest(
                source="fixture", transfer_id=paused.transfer_id,
            ))

    def test_publish_creates_provisional_snapshot_and_exact_manifest_after_matching(self):
        spotify = StatefulSpotify({
            ("Known Artist", "Known Track"): _match(
                "spotify:track:known", "Known Track", "Known Artist",
            ),
            ("New Artist", "New Track"): _match(
                "spotify:track:new", "New Track", "New Artist",
            ),
        })
        storage = InMemoryStorage()

        report = Transfer(
            source=FixtureBeatportSource(FIXTURE),
            spotify=spotify,
            matching_knowledge=storage,
            publication_storage=storage,
        ).execute(TransferRequest(source="fixture"))

        playlist = report.playlists[0]
        assert playlist.action == "provisional snapshot created"
        assert playlist.spotify_playlist_id == "snapshot-1"
        published = spotify.playlists["snapshot-1"]
        assert published["tracks"] == ["spotify:track:known", "spotify:track:new"]
        assert "Beatport" in published["description"]
        assert "https://www.beatport.com/chart/fixture/14" in published["description"]
        assert len(storage.publications) == 1
        manifest = storage.publications[0]
        assert manifest.spotify_playlist_id == "snapshot-1"
        assert playlist.publication_manifest is manifest
        assert manifest.source_label == "Beatport"
        assert manifest.source_reference == "https://www.beatport.com/chart/fixture/14"
        assert [item.spotify_uri for item in manifest.items] == [
            "spotify:track:known", "spotify:track:new",
        ]
        assert [item.source_track_id for item in manifest.items] == ["bp-1", "bp-2"]
        assert storage.checkpoints >= 1


    def test_repeated_snapshot_is_distinct_and_never_updates_previous_snapshot(self):
        matches = {
            ("Known Artist", "Known Track"): _match(
                "spotify:track:known", "Known Track", "Known Artist",
            ),
            ("New Artist", "New Track"): _match(
                "spotify:track:new", "New Track", "New Artist",
            ),
        }
        spotify = StatefulSpotify(matches)
        storage = InMemoryStorage()
        transfer = Transfer(
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=storage, publication_storage=storage,
        )

        first = transfer.execute(TransferRequest(source="fixture"))
        first_id = first.playlists[0].spotify_playlist_id
        first_snapshot = dict(spotify.playlists[first_id])
        second = transfer.execute(TransferRequest(source="fixture"))
        second_id = second.playlists[0].spotify_playlist_id

        assert second_id != first_id
        assert second.playlists[0].name != first.playlists[0].name
        assert spotify.playlists[first_id] == first_snapshot
        assert len(storage.publications) == 2


    def test_matching_failure_checkpoints_knowledge_without_partial_publication(self):
        class InterruptedSpotify(StatefulSpotify):
            def match(self, track, threshold):
                if track.track_id == "bp-2":
                    raise RuntimeError("matching interrupted")
                return _match("spotify:track:known", "Known Track", "Known Artist")

        spotify = InterruptedSpotify()
        storage = InMemoryStorage()

        with pytest.raises(RuntimeError, match="matching interrupted"):
            Transfer(
                source=FixtureBeatportSource(FIXTURE), spotify=spotify,
                matching_knowledge=storage, publication_storage=storage,
            ).execute(TransferRequest(source="fixture"))

        assert spotify.playlists == {"existing": ["spotify:track:untouched"]}
        assert storage.publications == []
        assert storage.checkpoints >= 1


    def test_incomplete_matching_does_not_publish_snapshot(self):
        spotify = StatefulSpotify({
            ("Known Artist", "Known Track"): _match(
                "spotify:track:known", "Known Track", "Known Artist",
            ),
        })
        storage = InMemoryStorage()

        report = Transfer(
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=storage, publication_storage=storage,
        ).execute(TransferRequest(source="fixture"))

        assert report.playlists[0].action == "not published: incomplete matching"
        assert spotify.playlists == {"existing": ["spotify:track:untouched"]}
        assert storage.publications == []

    def test_empty_chart_does_not_publish_snapshot(self):
        class EmptySource:
            source_label = "Beatport"

            def consume(self, reference):
                return SourceSelection("Empty Chart", reference, [])

        spotify = StatefulSpotify()
        storage = InMemoryStorage()

        report = Transfer(
            source=EmptySource(), spotify=spotify,
            matching_knowledge=storage, publication_storage=storage,
        ).execute(TransferRequest(source="empty"))

        assert report.playlists[0].action == "not published: empty source"
        assert spotify.playlists == {"existing": ["spotify:track:untouched"]}
        assert storage.publications == []


    def test_publication_storage_failure_removes_provisional_playlist(self):
        class FailingPublicationStorage(InMemoryStorage):
            def retain_publication(self, manifest):
                raise OSError("disk full")

        matches = {
            ("Known Artist", "Known Track"): _match(
                "spotify:track:known", "Known Track", "Known Artist",
            ),
            ("New Artist", "New Track"): _match(
                "spotify:track:new", "New Track", "New Artist",
            ),
        }
        spotify = StatefulSpotify(matches)

        with pytest.raises(OSError, match="disk full"):
            Transfer(
                source=FixtureBeatportSource(FIXTURE), spotify=spotify,
                matching_knowledge=InMemoryStorage(),
                publication_storage=FailingPublicationStorage(),
            ).execute(TransferRequest(source="fixture"))

        assert spotify.playlists == {"existing": ["spotify:track:untouched"]}


    def test_file_publication_manifest_survives_reload_through_transfer(self, tmp_path):
        matches = {
            ("Known Artist", "Known Track"): _match(
                "spotify:track:known", "Known Track", "Known Artist",
            ),
            ("New Artist", "New Track"): _match(
                "spotify:track:new", "New Track", "New Artist",
            ),
        }
        path = tmp_path / "publication-manifests.json"
        storage = FilePublicationStorage(path)

        report = Transfer(
            source=FixtureBeatportSource(FIXTURE), spotify=StatefulSpotify(matches),
            matching_knowledge=InMemoryStorage(), publication_storage=storage,
        ).execute(TransferRequest(source="fixture"))

        reloaded = FilePublicationStorage(path)
        assert reloaded.manifests[0]["spotify_playlist_id"] == (
            report.playlists[0].spotify_playlist_id
        )
        assert [item["source_track_id"] for item in reloaded.manifests[0]["items"]] == [
            "bp-1", "bp-2",
        ]



class TestBeatportCliTransfer:

    @patch("djsupport.transfer.Transfer.execute")
    @patch("djsupport.cli.get_client", return_value=MagicMock())
    def test_cli_beatport_dry_run_enters_transfer_interface(
        self, mock_client, execute,
    ):
        execute.return_value = SyncReport(
            timestamp=datetime.now(), threshold=80, dry_run=True,
            playlists=[PlaylistReport(name="Fixture", path="fixture", action="preview")],
            cache_enabled=True, source_label="Beatport",
        )

        result = CliRunner().invoke(cli, [
            "beatport", "https://www.beatport.com/chart/fixture/14",
            "--dry-run", "--cache-path", "preview-cache.json",
        ])

        assert result.exit_code == 0, result.output
        request = execute.call_args.args[0]
        assert request.preview is True
        assert request.source == "https://www.beatport.com/chart/fixture/14"


    @patch("djsupport.transfer.Transfer.execute")
    @patch("djsupport.cli.get_client", return_value=MagicMock())
    def test_cli_beatport_publish_enters_transfer_interface(
        self, mock_client, execute, tmp_path,
    ):
        execute.return_value = SyncReport(
            timestamp=datetime.now(), threshold=80, dry_run=False,
            playlists=[PlaylistReport(
                name="Fixture — unique", path="fixture",
                action="provisional snapshot created",
                spotify_playlist_id="snapshot-1",
            )],
            cache_enabled=False, source_label="Beatport",
        )

        result = CliRunner().invoke(cli, [
            "beatport", "https://www.beatport.com/chart/fixture/14",
            "--no-cache", "--state-path", str(tmp_path / "publications.json"),
        ])

        assert result.exit_code == 0, result.output
        request = execute.call_args.args[0]
        assert request.preview is False
        assert request.source == "https://www.beatport.com/chart/fixture/14"
