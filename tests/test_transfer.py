"""Behavior tests at the public Transfer seam."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
import spotipy

from click.testing import CliRunner

from djsupport.cli import cli
from djsupport.cache import MatchCache
from djsupport.rekordbox import Track
from djsupport.report import PlaylistReport, SyncReport
from djsupport.spotify import RateLimitError
from djsupport.transfer import (
    AccountPublishingGuards,
    FilePublicationStorage,
    FileTransferStorage,
    MatchCacheKnowledge,
    PublishingTransferConflict,
    RetryPolicy,
    SpotifyMatcher,
    SourceSelection,
    Transfer,
    TransferRequest,
    ApprovalStatus,
    ApprovalOutcome,
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

    def provisional_playlist_track_uris(self, playlist_id):
        playlist = self.playlists.get(playlist_id)
        if playlist is None:
            return None
        return list(playlist["tracks"])

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
        self.approvals = []
        self.approved_matches = []
        self.rejected_matches = []

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

    def publication_for_playlist(self, account_id, playlist_id):
        return next(
            (
                manifest for manifest in self.publications
                if manifest.account_id == account_id
                and manifest.spotify_playlist_id == playlist_id
            ),
            None,
        )

    def retain_approval(self, outcome):
        self.approvals.append(outcome)

    def approve(self, item):
        self.approved_matches.append(item)

    def reject(self, item):
        self.rejected_matches.append(item)


FIXTURE = Path(__file__).parent / "fixtures" / "beatport_chart.json"
TEST_PUBLISHING_GUARDS = AccountPublishingGuards()


def _match(uri, name, artist):
    return {
        "uri": uri, "name": name, "artist": artist,
        "score": 96.0, "match_type": "exact",
    }


def _spotify_error(status, *, retry_after=None):
    headers = {} if retry_after is None else {"Retry-After": str(retry_after)}
    return spotipy.SpotifyException(
        status, -1, "Spotify failure", headers=headers,
    )


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
        publishing_guards=TEST_PUBLISHING_GUARDS,
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
        publishing_guards=TEST_PUBLISHING_GUARDS,
        source=FixtureBeatportSource(FIXTURE),
        spotify=spotify,
        matching_knowledge=storage,
    ).execute(TransferRequest(source="fixture", preview=True))

    assert report.overall_match_rate == 0.0
    assert report.total_matched == 0
    assert report.total_unmatched == 2
    assert storage.checkpoints >= 1
    assert spotify.playlists == {"existing": ["spotify:track:untouched"]}


class TestProtectedTransferBehavior:

    def test_previously_unmatched_tracks_retry_only_when_explicitly_requested(
        self, tmp_path,
    ):
        cache = MatchCache(str(tmp_path / "matching-knowledge.json"))
        for artist, title in (
            ("Known Artist", "Known Track"), ("New Artist", "New Track"),
        ):
            cache.store(artist, title, 80, None)
            cache.entries[cache.cache_key(artist, title)].timestamp = (
                datetime.now() - timedelta(days=30)
            ).isoformat()
        spotify = StatefulSpotify({
            ("Known Artist", "Known Track"): _match(
                "spotify:track:known", "Known Track", "Known Artist",
            ),
            ("New Artist", "New Track"): _match(
                "spotify:track:new", "New Track", "New Artist",
            ),
        })
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=MatchCacheKnowledge(cache),
        )

        skipped = transfer.execute(TransferRequest(source="fixture", preview=True))
        retried = transfer.execute(TransferRequest(
            source="fixture", preview=True, retry=True,
        ))

        assert skipped.total_unmatched == 2
        assert skipped.playlists[0].api_lookups == 0
        assert retried.total_matched == 2
        assert retried.playlists[0].api_lookups == 2


    def test_transient_timeouts_retry_with_bounded_backoff(self):
        class TimeoutThenMatch(StatefulSpotify):
            def __init__(self):
                super().__init__()
                self.attempts = 0

            def match(self, track, threshold):
                self.attempts += 1
                if self.attempts < 3:
                    raise requests.Timeout("Spotify timed out")
                return _match("spotify:track:known", track.name, track.artist)

        spotify = TimeoutThenMatch()
        sleeps = []
        report = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=InMemoryStorage(),
            retry_policy=RetryPolicy(sleep=sleeps.append),
        ).execute(TransferRequest(source="fixture", preview=True))

        assert report.total_matched == 2
        assert spotify.attempts == 4
        assert sleeps == [1.0, 2.0]


    def test_server_failure_retries_are_bounded(self):
        class UnavailableSpotify(StatefulSpotify):
            def __init__(self):
                super().__init__()
                self.attempts = 0

            def match(self, track, threshold):
                self.attempts += 1
                raise _spotify_error(503)

        spotify = UnavailableSpotify()
        with pytest.raises(spotipy.SpotifyException) as raised:
            Transfer(
                publishing_guards=TEST_PUBLISHING_GUARDS,
                source=FixtureBeatportSource(FIXTURE), spotify=spotify,
                matching_knowledge=InMemoryStorage(),
                retry_policy=RetryPolicy(sleep=lambda _delay: None),
            ).execute(TransferRequest(source="fixture", preview=True))

        assert raised.value.http_status == 503
        assert spotify.attempts == 3


    def test_short_rate_limit_retries_using_retry_after(self):
        class RateLimitedOnce(StatefulSpotify):
            def __init__(self):
                super().__init__()
                self.rate_limited = False

            def match(self, track, threshold):
                if not self.rate_limited:
                    self.rate_limited = True
                    raise _spotify_error(429, retry_after=4)
                return _match("spotify:track:match", track.name, track.artist)

        sleeps = []
        report = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=FixtureBeatportSource(FIXTURE), spotify=RateLimitedOnce(),
            matching_knowledge=InMemoryStorage(),
            retry_policy=RetryPolicy(sleep=sleeps.append),
        ).execute(TransferRequest(source="fixture", preview=True))

        assert report.total_matched == 2
        assert sleeps == [4]


    @pytest.mark.parametrize(
        ("failure", "expected_exception"),
        [
            (_spotify_error(401), spotipy.SpotifyException),
            (_spotify_error(429, retry_after=2), spotipy.SpotifyException),
            (_spotify_error(429, retry_after=3600), RateLimitError),
        ],
    )
    def test_shared_spotify_failures_checkpoint_and_stop_safely(
        self, tmp_path, failure, expected_exception,
    ):
        class FailingSpotify(StatefulSpotify):
            def match(self, track, threshold):
                raise failure

        state_path = tmp_path / "transfers.json"
        knowledge = InMemoryStorage()
        with pytest.raises(expected_exception):
            Transfer(
                publishing_guards=TEST_PUBLISHING_GUARDS,
                source=FixtureBeatportSource(FIXTURE), spotify=FailingSpotify(),
                matching_knowledge=knowledge,
                transfer_storage=FileTransferStorage(state_path),
                retry_policy=RetryPolicy(sleep=lambda _delay: None),
            ).execute(TransferRequest(source="fixture", preview=True))

        persisted = next(iter(FileTransferStorage(state_path).transfers.values()))
        assert persisted.status.value == "paused"
        assert persisted.next_track_index == 0
        assert knowledge.checkpoints >= 1


    def test_second_publishing_transfer_for_same_account_cannot_race_first(self):
        entered_publication = threading.Event()
        release_publication = threading.Event()

        class BlockingSpotify(StatefulSpotify):
            def publish_provisional_snapshot(self, *args):
                entered_publication.set()
                assert release_publication.wait(timeout=2)
                return super().publish_provisional_snapshot(*args)

        matches = {
            ("Known Artist", "Known Track"): _match(
                "spotify:track:known", "Known Track", "Known Artist",
            ),
            ("New Artist", "New Track"): _match(
                "spotify:track:new", "New Track", "New Artist",
            ),
        }
        spotify = BlockingSpotify(matches)

        def publish():
            storage = InMemoryStorage()
            return Transfer(
                publishing_guards=AccountPublishingGuards(),
                source=FixtureBeatportSource(FIXTURE), spotify=spotify,
                matching_knowledge=storage, publication_storage=storage,
            ).execute(TransferRequest(source="fixture"))

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(publish)
            assert entered_publication.wait(timeout=2)
            with pytest.raises(PublishingTransferConflict, match="spotify-user-1"):
                publish()
            release_publication.set()
            assert first.result(timeout=2).status == "completed"


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
            publishing_guards=TEST_PUBLISHING_GUARDS,
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
            publishing_guards=TEST_PUBLISHING_GUARDS,
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
                publishing_guards=TEST_PUBLISHING_GUARDS,
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
            publishing_guards=TEST_PUBLISHING_GUARDS,
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
                publishing_guards=TEST_PUBLISHING_GUARDS,
                source=FixtureBeatportSource(FIXTURE), spotify=spotify,
                matching_knowledge=InMemoryStorage(),
                publication_storage=InMemoryStorage(), transfer_storage=reloaded,
            ).execute(TransferRequest(
                source="fixture", transfer_id=paused.transfer_id,
            ))
        assert "snapshot-1" not in spotify.playlists

    def test_transfer_cannot_be_abandoned_by_another_spotify_account(self, tmp_path):
        spotify = StatefulSpotify()
        states = FileTransferStorage(tmp_path / "transfers.json")
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=InMemoryStorage(),
            publication_storage=InMemoryStorage(), transfer_storage=states,
        )
        transfer.pause()
        paused = transfer.execute(TransferRequest(source="fixture"))
        spotify.account_id = lambda: "spotify-user-2"

        with pytest.raises(ValueError, match="another Spotify account"):
            transfer.abandon(paused.transfer_id)

        assert states.load_transfer(paused.transfer_id).status.value == "paused"

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
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=knowledge, publication_storage=publications,
            transfer_storage=states,
        )

        with pytest.raises(KeyboardInterrupt):
            transfer.execute(TransferRequest(source="fixture"))
        transfer_id = next(iter(states.transfers))

        resumed = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=knowledge, publication_storage=publications,
            transfer_storage=FileTransferStorage(states.path),
        ).execute(TransferRequest(source="fixture", transfer_id=transfer_id))

        assert resumed.status == "completed"
        assert len([key for key in spotify.playlists if key.startswith("snapshot-")]) == 1
        assert len(publications.publications) == 1

        repeated = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
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
                publishing_guards=TEST_PUBLISHING_GUARDS,
                source=FixtureBeatportSource(FIXTURE), spotify=spotify,
                matching_knowledge=knowledge, publication_storage=publications,
                transfer_storage=states,
            ).execute(TransferRequest(source="fixture", transfer_id=transfer_id))

        Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=knowledge, publication_storage=publications,
            transfer_storage=FileTransferStorage(states.path),
        ).execute(TransferRequest(source="fixture", transfer_id=transfer_id))

        assert len([key for key in spotify.playlists if key.startswith("snapshot-")]) == 1

    def test_resume_rejects_a_different_spotify_account(self, tmp_path):
        spotify = StatefulSpotify()
        states = FileTransferStorage(tmp_path / "transfers.json")
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=InMemoryStorage(),
            publication_storage=InMemoryStorage(), transfer_storage=states,
        )
        transfer.pause()
        paused = transfer.execute(TransferRequest(source="fixture"))
        spotify.account_id = lambda: "spotify-user-2"

        with pytest.raises(ValueError, match="another Spotify account"):
            Transfer(
                publishing_guards=TEST_PUBLISHING_GUARDS,
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
            publishing_guards=TEST_PUBLISHING_GUARDS,
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
        assert manifest.account_id == "spotify-user-1"
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
            publishing_guards=TEST_PUBLISHING_GUARDS,
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
                publishing_guards=TEST_PUBLISHING_GUARDS,
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
            publishing_guards=TEST_PUBLISHING_GUARDS,
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
            publishing_guards=TEST_PUBLISHING_GUARDS,
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
                publishing_guards=TEST_PUBLISHING_GUARDS,
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
            publishing_guards=TEST_PUBLISHING_GUARDS,
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

    def test_file_publication_state_is_scoped_to_spotify_account(self, tmp_path):
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
        for account_id in ("spotify-user-1", "spotify-user-2"):
            spotify = StatefulSpotify(matches)
            spotify.account_id = lambda value=account_id: value
            Transfer(
                publishing_guards=TEST_PUBLISHING_GUARDS,
                source=FixtureBeatportSource(FIXTURE), spotify=spotify,
                matching_knowledge=InMemoryStorage(),
                publication_storage=storage,
            ).execute(TransferRequest(source="fixture"))

        reloaded = FilePublicationStorage(path)
        assert {
            item["account_id"]
            for item in reloaded.manifests_for_account("spotify-user-1")
        } == {"spotify-user-1"}
        assert {
            item["account_id"]
            for item in reloaded.manifests_for_account("spotify-user-2")
        } == {"spotify-user-2"}

class TestProvisionalPlaylistApproval:
    def publish(self):
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
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=storage, publication_storage=storage,
        )
        report = transfer.execute(TransferRequest(source="fixture"))
        return transfer, spotify, storage, report.playlists[0].spotify_playlist_id

    def test_approval_is_scoped_to_one_playlist_and_records_review_outcomes(self):
        transfer, spotify, storage, playlist_id = self.publish()
        spotify.playlists[playlist_id]["tracks"] = [
            "spotify:track:known", "spotify:track:manual",
        ]

        review = transfer.approve(playlist_id)

        assert review.status == ApprovalStatus.APPROVED
        assert [item.source_track_id for item in review.approved] == ["bp-1"]
        assert [item.source_track_id for item in review.rejected] == ["bp-2"]
        assert spotify.playlists[playlist_id]["tracks"] == [
            "spotify:track:known", "spotify:track:manual",
        ]
        assert storage.approvals == [review]
        assert storage.approved_matches == list(review.approved)
        assert storage.rejected_matches == list(review.rejected)

    def test_deleted_provisional_playlist_is_abandoned_with_history_retained(self):
        transfer, spotify, storage, playlist_id = self.publish()
        del spotify.playlists[playlist_id]

        review = transfer.approve(playlist_id)

        assert review.status == ApprovalStatus.ABANDONED
        assert review.approved == ()
        assert review.rejected == ()
        assert len(storage.publications) == 1
        assert storage.publications[0].spotify_playlist_id == playlist_id
        assert storage.approvals == [review]

    def test_cannot_approve_an_unknown_or_other_account_playlist(self):
        transfer, _, _, _ = self.publish()

        with pytest.raises(ValueError, match="No Provisional Playlist"):
            transfer.approve("not-owned")

    def test_file_storage_persists_review_without_removing_publication_history(
        self, tmp_path,
    ):
        transfer, spotify, memory, playlist_id = self.publish()
        path = tmp_path / "publication-manifests.json"
        storage = FilePublicationStorage(path)
        storage.retain_publication(memory.publications[0])
        spotify.playlists[playlist_id]["tracks"] = ["spotify:track:known"]
        file_transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=memory, publication_storage=storage,
        )

        file_transfer.approve(playlist_id)

        reloaded = FilePublicationStorage(path)
        assert len(reloaded.manifests) == 1
        assert reloaded.approvals[0]["status"] == "approved"
        assert [item["source_track_id"] for item in reloaded.approvals[0]["rejected"]] == [
            "bp-2",
        ]

    def test_colliding_proposals_are_withheld_for_explicit_resolution(self):
        transfer, spotify, storage, playlist_id = self.publish()
        manifest = storage.publications[0]
        duplicate = type(manifest)(
            **{
                **manifest.__dict__,
                "items": (
                    manifest.items[0],
                    type(manifest.items[1])(
                        **{
                            **manifest.items[1].__dict__,
                            "spotify_uri": manifest.items[0].spotify_uri,
                        }
                    ),
                ),
            }
        )
        storage.publications[0] = duplicate
        spotify.playlists[playlist_id]["tracks"] = [manifest.items[0].spotify_uri]

        outcome = transfer.approve(playlist_id)

        assert outcome.approved == ()
        assert outcome.rejected == ()
        assert outcome.status == ApprovalStatus.NEEDS_REVIEW
        assert [item.source_track_id for item in outcome.collisions] == ["bp-1", "bp-2"]

    def test_later_abandonment_appends_to_approval_history(self):
        transfer, spotify, storage, playlist_id = self.publish()
        transfer.approve(playlist_id)
        del spotify.playlists[playlist_id]

        transfer.approve(playlist_id)

        assert [outcome.status for outcome in storage.approvals] == [
            ApprovalStatus.APPROVED, ApprovalStatus.ABANDONED,
        ]


class TestSpotifyApprovalAdapter:
    def test_reads_all_current_playlist_track_uris(self):
        client = MagicMock()
        client.playlist_items.return_value = {
            "items": [{"track": {"uri": "spotify:track:one"}}],
            "next": "page-2",
        }
        client.next.return_value = {
            "items": [
                {"track": {"uri": "spotify:track:two"}},
                {"track": None},
            ],
            "next": None,
        }

        assert SpotifyMatcher(client).provisional_playlist_track_uris("snapshot-1") == [
            "spotify:track:one", "spotify:track:two",
        ]

    def test_missing_playlist_is_reported_without_hiding_other_errors(self):
        client = MagicMock()
        client.playlist_items.side_effect = _spotify_error(404)

        assert SpotifyMatcher(client).provisional_playlist_track_uris("gone") is None


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

    @patch("djsupport.transfer.FileTransferStorage.load_transfer")
    @patch("djsupport.transfer.Transfer.execute")
    @patch("djsupport.cli.get_client", return_value=MagicMock())
    def test_cli_can_resume_a_visible_transfer_id(
        self, mock_client, execute, load_transfer, tmp_path,
    ):
        load_transfer.return_value = MagicMock()
        execute.return_value = SyncReport(
            timestamp=datetime.now(), threshold=80, dry_run=False,
            playlists=[PlaylistReport(name="Fixture", path="fixture")],
            transfer_id="resume-me", status="completed",
        )

        result = CliRunner().invoke(cli, [
            "beatport", "https://www.beatport.com/chart/fixture/14",
            "--resume", "resume-me", "--state-path", str(tmp_path / "state.json"),
        ])

        assert result.exit_code == 0, result.output
        assert "Transfer ID: resume-me" in result.output
        assert execute.call_args.args[0].transfer_id == "resume-me"

    @patch("djsupport.transfer.Transfer.abandon")
    @patch("djsupport.cli.get_client", return_value=MagicMock())
    def test_cli_can_explicitly_abandon_a_transfer(
        self, mock_client, abandon, tmp_path,
    ):
        result = CliRunner().invoke(cli, [
            "beatport", "https://www.beatport.com/chart/fixture/14",
            "--abandon", "stop-me", "--state-path", str(tmp_path / "state.json"),
        ])

        assert result.exit_code == 0, result.output
        abandon.assert_called_once_with("stop-me")
        assert "Transfer stop-me abandoned" in result.output

    @patch("djsupport.transfer.Transfer.approve")
    @patch("djsupport.cli.get_client", return_value=MagicMock())
    def test_cli_approves_one_provisional_playlist(
        self, mock_client, approve, tmp_path,
    ):
        approve.return_value = ApprovalOutcome(
            account_id="spotify-user-1",
            spotify_playlist_id="snapshot-1",
            reviewed_at=datetime.now(),
            status=ApprovalStatus.APPROVED,
            approved=(MagicMock(),),
            rejected=(MagicMock(), MagicMock()),
        )

        result = CliRunner().invoke(cli, [
            "approve", "snapshot-1", "--state-path", str(tmp_path / "state.json"),
        ])

        assert result.exit_code == 0, result.output
        approve.assert_called_once_with("snapshot-1")
        assert "1 approved" in result.output
        assert "2 rejected" in result.output
