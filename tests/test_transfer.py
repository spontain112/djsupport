"""Behavior tests at the public Transfer seam."""

import json
import csv
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
from djsupport.regression import load_local_regressions
from djsupport.report import PlaylistReport, SyncReport, save_report, save_review_csv
from djsupport.spotify import QuotaExceededError, RateLimitError
from djsupport.transfer import (
    AccountPublishingGuards,
    BatchPlan,
    BatchPlanRequest,
    FilePublicationStorage,
    FileTransferStorage,
    MatchCacheKnowledge,
    PublishingTransferConflict,
    RetryPolicy,
    SpotifyMatcher,
    SpotifyItemKind,
    SpotifyPlaylistHead,
    SpotifyPlaylistItem,
    SpotifyPlaylistPage,
    SourceSelection,
    Transfer,
    TransferMode,
    TransferRequest,
    DriftResolution,
    ApprovalStatus,
    ApprovalOutcome,
    BeatportChartSource,
    BeatportLabelSource,
    RekordboxPlaylistSource,
    MirrorRelationship,
    MirrorDisposition,
    SourceNotFound,
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
                duration=item.get("duration", 0),
            )
            for item in data["tracks"]
        ]
        return SourceSelection(data["name"], data["reference"], tracks)


class MissingRekordboxSource:
    source_label = "Rekordbox"
    default_mode = TransferMode.MIRROR

    def consume(self, reference):
        raise SourceNotFound(f"Rekordbox playlist not found: {reference}")


class StatefulSpotify:
    def __init__(self, matches=None) -> None:
        self.matches = matches or {}
        self.searches = []
        self.playlists = {"existing": ["spotify:track:untouched"]}
        self.publication_keys = {}
        self.playlist_replacements = 0

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

    def delete_playlist(self, playlist_id):
        del self.playlists[playlist_id]

    def provisional_playlist_track_uris(self, playlist_id):
        playlist = self.playlists.get(playlist_id)
        if playlist is None:
            return None
        return list(playlist["tracks"])

    def replace_provisional_playlist_tracks(self, playlist_id, track_uris):
        self.playlist_replacements += 1
        self.playlists[playlist_id]["tracks"] = list(track_uris)

    def spotify_track(self, uri):
        track_id = uri.removeprefix("spotify:track:")
        return {
            "uri": uri,
            "name": f"Corrected {track_id}",
            "artist": "Correction Artist",
        }

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
        self.corrections = []
        self.mirrors = []

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

    def retain_mirror(self, relationship):
        self.mirrors.append(relationship)

    def mirror_for_source(self, account_id, source_label, source_reference):
        return next((
            mirror for mirror in self.mirrors
            if mirror.account_id == account_id
            and mirror.source_label == source_label
            and mirror.source_reference == source_reference
        ), None)

    def mirror_for_playlist(self, account_id, playlist_id):
        return next((
            mirror for mirror in self.mirrors
            if mirror.account_id == account_id
            and mirror.spotify_playlist_id == playlist_id
        ), None)

    def retain_relinked_publication(self, previous, replacement, manifest):
        self.retain_publication(manifest)
        self.mirrors = [
            mirror for mirror in self.mirrors
            if not (
                mirror.account_id == previous.account_id
                and mirror.spotify_playlist_id == previous.spotify_playlist_id
            )
        ]
        self.mirrors.append(replacement)

    def remove_mirror(self, relationship):
        self.mirrors = [
            mirror for mirror in self.mirrors
            if not (
                mirror.account_id == relationship.account_id
                and mirror.spotify_playlist_id == relationship.spotify_playlist_id
            )
        ]

    def approve(self, item):
        self.approved_matches.append(item)

    def reject(self, item):
        self.rejected_matches.append(item)

    def correct(self, item):
        self.corrections.append(item)

    def revoke(self, item):
        self.matches.pop((item.source_artist, item.source_title), None)


FIXTURE = Path(__file__).parent / "fixtures" / "beatport_chart.json"
REKORDBOX_FIXTURE = Path(__file__).parent / "fixtures" / "library.xml"
INCOMPLETE_REKORDBOX_FIXTURE = (
    Path(__file__).parent / "fixtures" / "rekordbox_missing_track.xml"
)
LABEL_FIXTURE = Path(__file__).parent / "fixtures" / "beatport_label_page.json"
MIRROR_REFRESH_FIXTURE = (
    Path(__file__).parent / "fixtures" / "rekordbox_mirror_refresh.json"
)
TEST_PUBLISHING_GUARDS = AccountPublishingGuards()


class TestBeatportChartSource:
    @staticmethod
    def _track():
        return Track(
            track_id="bp-60", artist="Ada DJ", name="Signal",
            album="", remixer="", label="", genre="", date_added="",
        )

    def test_curator_precedes_chart_name(self, monkeypatch):
        monkeypatch.setattr(
            "djsupport.beatport.fetch_chart",
            lambda url: ("Synthetic Chart", "Ada DJ", []),
        )

        selection = BeatportChartSource().consume(
            "https://www.beatport.com/chart/synthetic-chart/60"
        )

        assert selection.name == "Ada DJ - Synthetic Chart"

    @pytest.mark.parametrize("curator", ["", "Unknown"])
    def test_missing_curator_falls_back_to_chart_name(self, monkeypatch, curator):
        monkeypatch.setattr(
            "djsupport.beatport.fetch_chart",
            lambda url: ("Synthetic Chart", curator, []),
        )

        selection = BeatportChartSource().consume(
            "https://www.beatport.com/chart/synthetic-chart/60"
        )

        assert selection.name == "Synthetic Chart"

    def test_transfer_preserves_curator_first_name_in_preview(self, monkeypatch):
        monkeypatch.setattr(
            "djsupport.beatport.fetch_chart",
            lambda url: ("Synthetic Chart", "Ada DJ", [self._track()]),
        )
        spotify = StatefulSpotify({
            ("Ada DJ", "Signal"): _match(
                "spotify:track:signal", "Signal", "Ada DJ",
            ),
        })

        report = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=BeatportChartSource(), spotify=spotify,
            matching_knowledge=InMemoryStorage(),
        ).execute(TransferRequest(
            source="https://www.beatport.com/chart/synthetic-chart/60",
            preview=True,
        ))

        assert report.playlists[0].name == "Ada DJ - Synthetic Chart"

    def test_transfer_preserves_curator_first_name_in_publication(self, monkeypatch):
        monkeypatch.setattr(
            "djsupport.beatport.fetch_chart",
            lambda url: ("Synthetic Chart", "Ada DJ", [self._track()]),
        )
        spotify = StatefulSpotify({
            ("Ada DJ", "Signal"): _match(
                "spotify:track:signal", "Signal", "Ada DJ",
            ),
        })
        storage = InMemoryStorage()

        report = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=BeatportChartSource(), spotify=spotify,
            matching_knowledge=storage, publication_storage=storage,
        ).execute(TransferRequest(
            source="https://www.beatport.com/chart/synthetic-chart/60",
            playlist_prefix=None,
        ))

        playlist = report.playlists[0]
        assert playlist.name.startswith("Ada DJ - Synthetic Chart — ")
        assert spotify.playlists[playlist.spotify_playlist_id]["name"] == playlist.name

    def test_curator_first_name_survives_pause_reload_and_resume(
        self, monkeypatch, tmp_path,
    ):
        fixture_selection = FixtureBeatportSource(FIXTURE).consume("fixture")
        intake_calls = []

        def fetch_chart(url):
            intake_calls.append(url)
            return "Synthetic Chart", "Ada DJ", fixture_selection.tracks

        monkeypatch.setattr("djsupport.beatport.fetch_chart", fetch_chart)
        spotify = StatefulSpotify({
            ("Known Artist", "Known Track"): _match(
                "spotify:track:known", "Known Track", "Known Artist",
            ),
            ("New Artist", "New Track"): _match(
                "spotify:track:new", "New Track", "New Artist",
            ),
        })
        knowledge = InMemoryStorage()
        publications = InMemoryStorage()
        state_path = tmp_path / "transfers.json"
        request = TransferRequest(
            source="https://www.beatport.com/chart/synthetic-chart/60",
            playlist_prefix=None,
        )
        first = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=BeatportChartSource(), spotify=spotify,
            matching_knowledge=knowledge, publication_storage=publications,
            transfer_storage=FileTransferStorage(state_path),
        )
        first.pause()

        paused = first.execute(request)
        resumed = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=BeatportChartSource(), spotify=spotify,
            matching_knowledge=knowledge, publication_storage=publications,
            transfer_storage=FileTransferStorage(state_path),
        ).execute(TransferRequest(
            source=request.source, transfer_id=paused.transfer_id,
        ))

        playlist = resumed.playlists[0]
        assert paused.status == "paused"
        assert resumed.status == "completed"
        assert playlist.name.startswith("Ada DJ - Synthetic Chart — ")
        assert spotify.playlists[playlist.spotify_playlist_id]["name"] == playlist.name
        assert intake_calls == [request.source]


class TestBeatportLabelSource:
    def test_production_intake_parses_fixture_order_and_deduplicates(self, monkeypatch):
        fixture_data = LABEL_FIXTURE.read_text()
        fixture_html = f'<script id="__NEXT_DATA__">{fixture_data}</script>'
        monkeypatch.setattr("djsupport.label._fetch_page", lambda url, page: fixture_html)

        selection = BeatportLabelSource().consume(
            "https://www.beatport.com/label/fixture/21"
        )

        assert selection.name == "Fixture Label"
        assert selection.reference == "https://www.beatport.com/label/fixture/21"
        assert [track.track_id for track in selection.tracks] == [
            "bp-label-2101", "bp-label-2103",
        ]
        assert [track.name for track in selection.tracks] == [
            "Known Track", "New Track (Extended Mix)",
        ]


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


def test_transfer_retry_policy_distinguishes_quota_exhaustion():
    error = spotipy.SpotifyException(
        429, -1, "QUOTA_EXCEEDED", headers={"Retry-After": "1"},
    )
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        raise error

    with pytest.raises(QuotaExceededError):
        RetryPolicy(sleep=lambda _: None).run(operation)

    assert calls == 1


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


def test_preview_preserves_shorter_version_reason_for_review_without_publication():
    reason = "Spotify version is 31s shorter than source (6:29 vs 7:00)"
    spotify = StatefulSpotify({
        ("New Artist", "New Track"): {
            **_match("spotify:track:shorter", "New Track", "New Artist"),
            "match_type": "shorter_version",
            "score_reasons": ["source artist similarity", reason],
        },
    })
    storage = InMemoryStorage()
    original_playlists = dict(spotify.playlists)

    report = Transfer(
        publishing_guards=TEST_PUBLISHING_GUARDS,
        source=FixtureBeatportSource(FIXTURE), spotify=spotify,
        matching_knowledge=storage, publication_storage=storage,
    ).execute(TransferRequest(source="fixture", preview=True))

    proposal = report.playlists[0].matched[0]
    review_item = report.playlists[0].review_items[1]
    assert proposal.match_type == "shorter_version"
    assert reason in proposal.score_reasons
    assert reason in review_item.score_reasons
    assert spotify.playlists == original_playlists
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

    def test_below_threshold_candidates_are_reported_but_not_published(self):
        spotify = StatefulSpotify({
            ("Known Artist", "Known Track"): _match(
                "spotify:track:known", "Known Track", "Known Artist",
            ),
            ("New Artist", "New Track"): {
                "alternatives": [
                    {
                        "uri": f"spotify:track:alternative-{rank}",
                        "name": f"New Track Candidate {rank}",
                        "artist": "New Artist",
                        "version": "Extended Mix" if rank == 1 else "Radio Edit",
                        "duration_ms": 360000 - rank * 1000,
                        "score": 79.0 - rank,
                        "score_reasons": [
                            "title similarity 92",
                            "artist similarity 88",
                        ],
                    }
                    for rank in range(1, 5)
                ],
            },
        })
        storage = InMemoryStorage()

        report = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=storage, publication_storage=storage,
        ).execute(TransferRequest(source="fixture", threshold=80))

        playlist = report.playlists[0]
        assert playlist.action == "provisional snapshot created"
        assert spotify.playlists[playlist.spotify_playlist_id]["tracks"] == [
            "spotify:track:known",
        ]
        assert len(playlist.unmatched) == 1
        assert [candidate.rank for candidate in playlist.alternatives[0].candidates] == [
            1, 2, 3,
        ]
        assert playlist.alternatives[0].candidates[0].score_reasons == (
            "title similarity 92", "artist similarity 88",
        )

    def test_match_collision_is_reported_and_retained_for_correction(self, tmp_path):
        shared = _match("spotify:track:shared", "Shared", "Artist")
        spotify = StatefulSpotify({
            ("Known Artist", "Known Track"): shared,
            ("New Artist", "New Track"): shared,
        })
        storage = InMemoryStorage()

        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=storage, publication_storage=storage,
        )
        report = transfer.execute(TransferRequest(source="fixture"))

        playlist = report.playlists[0]
        assert report.total_matched == 0
        assert report.total_unmatched == 2
        assert [item.source_track_id for item in playlist.match_collisions] == [
            "bp-1", "bp-2",
        ]
        assert [
            item.source_track_id for item in playlist.publication_manifest.items
        ] == ["bp-1", "bp-2"]
        assert spotify.playlists[playlist.spotify_playlist_id]["tracks"] == []

        review_csv = tmp_path / "collisions.csv"
        review_csv.write_text(
            "source_track_id,spotify_url\n"
            "bp-1,spotify:track:abcdefghijklmnopqrstuv\n"
        )
        partial = transfer.approve(
            playlist.spotify_playlist_id, corrections=review_csv,
        )

        assert partial.status == ApprovalStatus.NEEDS_REVIEW
        assert [item.source_track_id for item in partial.approved] == ["bp-1"]
        assert [item.source_track_id for item in partial.collisions] == ["bp-2"]
        assert partial.rejected == ()

        review_csv.write_text(
            "source_track_id,spotify_url\n"
            "bp-1,spotify:track:abcdefghijklmnopqrstuv\n"
            "bp-2,spotify:track:zyxwvutsrqponmlkjihgfe\n"
        )
        outcome = transfer.approve(
            playlist.spotify_playlist_id, corrections=review_csv,
        )

        assert outcome.status == ApprovalStatus.APPROVED
        assert [item.source_track_id for item in outcome.approved] == ["bp-1", "bp-2"]
        assert spotify.playlists[playlist.spotify_playlist_id]["tracks"] == [
            "spotify:track:abcdefghijklmnopqrstuv",
            "spotify:track:zyxwvutsrqponmlkjihgfe",
        ]

    def test_repeated_occurrence_of_same_source_track_is_not_a_collision(self):
        class RepeatedSource:
            source_label = "Rekordbox"

            def consume(self, reference):
                track = Track(
                    track_id="rb-1", artist="Artist", name="Track", album="",
                    remixer="", label="", genre="", date_added="",
                )
                return SourceSelection("Repeated", reference, [track, track])

        spotify = StatefulSpotify({
            ("Artist", "Track"): _match(
                "spotify:track:shared", "Track", "Artist",
            ),
        })
        storage = InMemoryStorage()

        report = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=RepeatedSource(), spotify=spotify,
            matching_knowledge=storage, publication_storage=storage,
        ).execute(TransferRequest(source="playlist"))

        assert report.playlists[0].match_collisions == []
        assert spotify.playlists[report.playlists[0].spotify_playlist_id]["tracks"] == [
            "spotify:track:shared",
            "spotify:track:shared",
        ]

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
                return _match(
                    f"spotify:track:{track.track_id}", track.name, track.artist,
                )

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
                return _match(
                    f"spotify:track:{track.track_id}", track.name, track.artist,
                )

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
    def test_beatport_label_defaults_to_distinct_snapshots_after_approval(self):
        class FixtureLabelSource(FixtureBeatportSource):
            source_label = "Beatport label"

        spotify = StatefulSpotify({
            ("Known Artist", "Known Track"): _match(
                "spotify:track:known", "Known Track", "Known Artist",
            ),
            ("New Artist", "New Track"): _match(
                "spotify:track:new", "New Track", "New Artist",
            ),
        })
        storage = InMemoryStorage()
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=FixtureLabelSource(FIXTURE), spotify=spotify,
            matching_knowledge=storage, publication_storage=storage,
        )

        first = transfer.execute(TransferRequest(source="fixture-label"))
        transfer.approve(first.playlists[0].spotify_playlist_id)
        second = transfer.execute(TransferRequest(source="fixture-label"))

        assert first.playlists[0].spotify_playlist_id != second.playlists[0].spotify_playlist_id
        assert first.playlists[0].action == "provisional snapshot created"
        assert second.playlists[0].action == "provisional snapshot created"
        assert first.playlists[0].publication_manifest.mode == TransferMode.SNAPSHOT

    def test_beatport_source_can_explicitly_recur_as_one_mirror(self):
        spotify = StatefulSpotify({
            ("Known Artist", "Known Track"): _match(
                "spotify:track:known", "Known Track", "Known Artist",
            ),
            ("New Artist", "New Track"): _match(
                "spotify:track:new", "New Track", "New Artist",
            ),
        })
        storage = InMemoryStorage()
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=storage, publication_storage=storage,
        )

        first = transfer.execute(TransferRequest(
            source="fixture", mode=TransferMode.MIRROR,
        ))
        transfer.approve(first.playlists[0].spotify_playlist_id)
        second = transfer.execute(TransferRequest(
            source="fixture", mode=TransferMode.MIRROR,
        ))

        assert second.playlists[0].spotify_playlist_id == first.playlists[0].spotify_playlist_id
        assert second.playlists[0].action == "provisional mirror updated"
        assert second.playlists[0].publication_manifest.mode == TransferMode.MIRROR


class TestRekordboxMirror:
    def test_missing_exact_source_becomes_orphan_without_spotify_deletion(self, tmp_path):
        spotify = StatefulSpotify()
        storage = FilePublicationStorage(tmp_path / "publications.json")
        storage.retain_mirror(MirrorRelationship(
            account_id="spotify-user-1",
            source_label="Rekordbox",
            source_reference="Folder/Original",
            spotify_playlist_id="existing",
            spotify_playlist_name="Original",
            approved_at=datetime(2026, 8, 1),
        ))

        report = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=MissingRekordboxSource(), spotify=spotify,
            matching_knowledge=storage, publication_storage=storage,
        ).execute(TransferRequest(source="Folder/Original"))

        assert report.status == "orphaned mirror"
        assert report.playlists[0].spotify_playlist_id == "existing"
        assert report.playlists[0].action == "disposition required"
        assert report.playlists[0].mirror_dispositions == tuple(
            choice.value for choice in MirrorDisposition
        )
        assert spotify.playlists == {
            "existing": ["spotify:track:untouched"],
        }
        orphan = FilePublicationStorage(
            tmp_path / "publications.json"
        ).mirror_for_source("spotify-user-1", "Rekordbox", "Folder/Original")
        assert orphan.orphaned_at is not None
        report_path = tmp_path / "orphan.md"
        save_report(report, str(report_path))
        assert "Orphaned Mirror" in report_path.read_text()
        assert "keep, relink, or delete" in report_path.read_text()

    def test_renamed_source_can_explicitly_relink_to_existing_mirror(self, tmp_path):
        fixture = json.loads(MIRROR_REFRESH_FIXTURE.read_text())

        class RenamedSource:
            source_label = "Rekordbox"
            default_mode = TransferMode.MIRROR

            def consume(self, reference):
                assert reference == "Moved/Renamed"
                item = fixture["initial"][0]
                return SourceSelection(
                    "Renamed", reference,
                    [Track(
                        track_id=item["track_id"], artist=item["artist"],
                        name=item["name"], duration=item["duration"], album="",
                        remixer="", label="", genre="", date_added="",
                    )],
                )

        spotify = StatefulSpotify({
            ("Artist One", "First Track"): _match(
                "spotify:track:first", "First Track", "Artist One",
            ),
        })
        spotify.playlists["mirror-1"] = {
            "name": "Original", "tracks": ["spotify:track:old"],
            "description": "managed",
        }
        storage = FilePublicationStorage(tmp_path / "publications.json")
        storage.retain_mirror(MirrorRelationship(
            account_id="spotify-user-1", source_label="Rekordbox",
            source_reference="Original/Playlist",
            spotify_playlist_id="mirror-1", spotify_playlist_name="Original",
            approved_at=datetime(2026, 8, 1),
        ))

        report = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=RenamedSource(), spotify=spotify,
            matching_knowledge=InMemoryStorage(), publication_storage=storage,
        ).execute(TransferRequest(
            source="Moved/Renamed",
            mirror_disposition=MirrorDisposition.RELINK,
            mirror_playlist_id="mirror-1",
        ))

        assert report.playlists[0].spotify_playlist_id == "mirror-1"
        assert report.playlists[0].action == "mirror relinked"
        assert report.playlists[0].mirror_disposition == "relink"
        assert spotify.playlists["mirror-1"]["tracks"] == ["spotify:track:first"]
        assert storage.mirror_for_source(
            "spotify-user-1", "Rekordbox", "Original/Playlist",
        ) is None
        assert storage.mirror_for_source(
            "spotify-user-1", "Rekordbox", "Moved/Renamed",
        ).spotify_playlist_id == "mirror-1"

    def test_relink_reports_existing_playlist_drift_before_mutating(self, tmp_path):
        fixture = json.loads(MIRROR_REFRESH_FIXTURE.read_text())

        class MovableSource:
            source_label = "Rekordbox"
            default_mode = TransferMode.MIRROR
            reference = "Original/Playlist"

            def consume(self, reference):
                item = fixture["initial"][0]
                return SourceSelection(
                    "Mirror", reference,
                    [Track(
                        track_id=item["track_id"], artist=item["artist"],
                        name=item["name"], duration=item["duration"], album="",
                        remixer="", label="", genre="", date_added="",
                    )],
                )

        source = MovableSource()
        spotify = StatefulSpotify({
            ("Artist One", "First Track"): _match(
                "spotify:track:first", "First Track", "Artist One",
            ),
        })
        knowledge = MatchCacheKnowledge(MatchCache(tmp_path / "knowledge.json"))
        storage = FilePublicationStorage(tmp_path / "publications.json")
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=source, spotify=spotify, matching_knowledge=knowledge,
            publication_storage=storage,
        )
        initial = transfer.execute(TransferRequest(source=source.reference))
        playlist_id = initial.playlists[0].spotify_playlist_id
        transfer.approve(playlist_id)
        spotify.playlists[playlist_id]["tracks"] = []

        drifted = transfer.execute(TransferRequest(
            source="Moved/Renamed",
            mirror_disposition=MirrorDisposition.RELINK,
            mirror_playlist_id=playlist_id,
        ))

        assert drifted.status == "playlist drift"
        assert drifted.playlists[0].action == "restore or revoke required"
        assert spotify.playlists[playlist_id]["tracks"] == []
        assert storage.mirror_for_source(
            "spotify-user-1", "Rekordbox", "Original/Playlist",
        ) is not None

    def test_relink_storage_failure_preserves_existing_spotify_mirror(self):
        class MovedSource:
            source_label = "Rekordbox"
            default_mode = TransferMode.MIRROR

            def consume(self, reference):
                return SourceSelection(
                    "Renamed", reference,
                    [Track(
                        track_id="rb-1", artist="Artist One", name="First Track",
                        duration=301, album="", remixer="", label="", genre="",
                        date_added="",
                    )],
                )

        class FailingStorage(InMemoryStorage):
            def retain_relinked_publication(self, previous, replacement, manifest):
                raise OSError("disk full")

        spotify = StatefulSpotify({
            ("Artist One", "First Track"): _match(
                "spotify:track:first", "First Track", "Artist One",
            ),
        })
        spotify.playlists["mirror-1"] = {
            "name": "Original", "tracks": ["spotify:track:old"],
            "description": "managed",
        }
        storage = FailingStorage()
        storage.retain_mirror(MirrorRelationship(
            account_id="spotify-user-1", source_label="Rekordbox",
            source_reference="Original/Playlist", spotify_playlist_id="mirror-1",
            spotify_playlist_name="Original", approved_at=datetime(2026, 8, 1),
        ))

        with pytest.raises(OSError, match="disk full"):
            Transfer(
                publishing_guards=TEST_PUBLISHING_GUARDS,
                source=MovedSource(), spotify=spotify,
                matching_knowledge=storage, publication_storage=storage,
            ).execute(TransferRequest(
                source="Moved/Renamed",
                mirror_disposition=MirrorDisposition.RELINK,
                mirror_playlist_id="mirror-1",
            ))

        assert spotify.playlists["mirror-1"]["tracks"] == ["spotify:track:old"]

    def test_keep_disposition_releases_orphan_as_ordinary_playlist(self, tmp_path):
        spotify = StatefulSpotify()
        storage = FilePublicationStorage(tmp_path / "publications.json")
        storage.retain_mirror(MirrorRelationship(
            account_id="spotify-user-1", source_label="Rekordbox",
            source_reference="Folder/Original", spotify_playlist_id="existing",
            spotify_playlist_name="Original", approved_at=datetime(2026, 8, 1),
        ))

        report = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=MissingRekordboxSource(), spotify=spotify,
            matching_knowledge=InMemoryStorage(), publication_storage=storage,
        ).execute(TransferRequest(
            source="Folder/Original",
            mirror_disposition=MirrorDisposition.KEEP,
        ))

        assert report.status == "completed"
        assert report.playlists[0].action == "mirror kept as ordinary playlist"
        assert report.playlists[0].mirror_disposition == "keep"
        assert spotify.playlists == {"existing": ["spotify:track:untouched"]}
        assert storage.mirror_for_source(
            "spotify-user-1", "Rekordbox", "Folder/Original",
        ) is None

    def test_delete_disposition_is_explicit_and_account_scoped(self, tmp_path):
        spotify = StatefulSpotify()
        storage = FilePublicationStorage(tmp_path / "publications.json")
        for account_id, playlist_id in (
            ("spotify-user-1", "existing"),
            ("spotify-user-2", "other-account-mirror"),
        ):
            storage.retain_mirror(MirrorRelationship(
                account_id=account_id, source_label="Rekordbox",
                source_reference="Folder/Original",
                spotify_playlist_id=playlist_id,
                spotify_playlist_name="Original", approved_at=datetime(2026, 8, 1),
            ))

        report = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=MissingRekordboxSource(), spotify=spotify,
            matching_knowledge=InMemoryStorage(), publication_storage=storage,
        ).execute(TransferRequest(
            source="Folder/Original",
            mirror_disposition=MirrorDisposition.DELETE,
        ))

        assert report.status == "completed"
        assert report.playlists[0].action == "mirror explicitly deleted"
        assert report.playlists[0].mirror_disposition == "delete"
        assert "existing" not in spotify.playlists
        assert storage.mirror_for_source(
            "spotify-user-1", "Rekordbox", "Folder/Original",
        ) is None
        assert storage.mirror_for_source(
            "spotify-user-2", "Rekordbox", "Folder/Original",
        ).spotify_playlist_id == "other-account-mirror"

    def test_similar_source_name_never_relinks_without_explicit_identity(self):
        storage = InMemoryStorage()
        storage.retain_mirror(MirrorRelationship(
            account_id="spotify-user-1", source_label="Rekordbox",
            source_reference="Folder/Original Mixes",
            spotify_playlist_id="existing", spotify_playlist_name="Original Mixes",
            approved_at=datetime(2026, 8, 1),
        ))

        with pytest.raises(
            ValueError, match="Rekordbox playlist not found: Folder/Original Mix",
        ):
            Transfer(
                publishing_guards=TEST_PUBLISHING_GUARDS,
                source=MissingRekordboxSource(), spotify=StatefulSpotify(),
                matching_knowledge=storage, publication_storage=storage,
            ).execute(TransferRequest(source="Folder/Original Mix"))

    def test_identical_source_contents_never_relink_without_explicit_identity(self):
        track = Track(
            track_id="rb-1", artist="Artist One", name="First Track",
            duration=301, album="", remixer="", label="", genre="",
            date_added="",
        )

        class MovedSource:
            source_label = "Rekordbox"
            default_mode = TransferMode.MIRROR

            def consume(self, reference):
                return SourceSelection("Renamed", reference, [track])

        spotify = StatefulSpotify({
            (track.artist, track.name): _match(
                "spotify:track:first", track.name, track.artist,
            ),
        })
        spotify.playlists["old-mirror"] = {
            "name": "Original", "tracks": ["spotify:track:first"],
            "description": "managed",
        }
        storage = InMemoryStorage()
        storage.retain_mirror(MirrorRelationship(
            account_id="spotify-user-1", source_label="Rekordbox",
            source_reference="Original/Playlist", spotify_playlist_id="old-mirror",
            spotify_playlist_name="Original", approved_at=datetime(2026, 8, 1),
        ))

        report = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=MovedSource(), spotify=spotify,
            matching_knowledge=storage, publication_storage=storage,
        ).execute(TransferRequest(source="Moved/Renamed"))

        assert report.playlists[0].spotify_playlist_id != "old-mirror"
        assert spotify.playlists["old-mirror"]["tracks"] == ["spotify:track:first"]

    def test_source_validation_failure_does_not_orphan_an_existing_mirror(self):
        class InvalidSource:
            source_label = "Rekordbox"
            default_mode = TransferMode.MIRROR

            def consume(self, reference):
                raise ValueError("Rekordbox playlist has missing track references: 42")

        storage = InMemoryStorage()
        storage.retain_mirror(MirrorRelationship(
            account_id="spotify-user-1", source_label="Rekordbox",
            source_reference="Folder/Original", spotify_playlist_id="existing",
            spotify_playlist_name="Original", approved_at=datetime(2026, 8, 1),
        ))

        with pytest.raises(ValueError, match="missing track references"):
            Transfer(
                publishing_guards=TEST_PUBLISHING_GUARDS,
                source=InvalidSource(), spotify=StatefulSpotify(),
                matching_knowledge=storage, publication_storage=storage,
            ).execute(TransferRequest(source="Folder/Original"))

    def test_refresh_reports_playlist_drift_without_silently_restoring(self, tmp_path):
        fixture = json.loads(MIRROR_REFRESH_FIXTURE.read_text())

        class MirrorSource:
            source_label = "Rekordbox"
            default_mode = TransferMode.MIRROR

            def consume(self, reference):
                return SourceSelection(
                    fixture["name"], fixture["reference"],
                    [Track(
                        track_id=item["track_id"], artist=item["artist"],
                        name=item["name"], duration=item["duration"], album="",
                        remixer="", label="", genre="", date_added="",
                    ) for item in fixture["initial"]],
                )

        spotify = StatefulSpotify({
            ("Artist One", "First Track"): _match(
                "spotify:track:first", "First Track", "Artist One",
            ),
            ("Artist Two", "Second Track"): _match(
                "spotify:track:second", "Second Track", "Artist Two",
            ),
        })
        knowledge = MatchCacheKnowledge(MatchCache(tmp_path / "knowledge.json"))
        publications = FilePublicationStorage(tmp_path / "publications.json")
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS, source=MirrorSource(),
            spotify=spotify, matching_knowledge=knowledge,
            publication_storage=publications,
        )
        initial = transfer.execute(TransferRequest(source=fixture["reference"]))
        playlist_id = initial.playlists[0].spotify_playlist_id
        transfer.approve(playlist_id)
        spotify.playlists[playlist_id]["tracks"] = ["spotify:track:second"]

        drifted = transfer.execute(TransferRequest(source=fixture["reference"]))

        assert drifted.status == "playlist drift"
        assert drifted.playlists[0].action == "restore or revoke required"
        assert [item.source_track_id for item in drifted.playlists[0].playlist_drift] == [
            "rb-1"
        ]
        assert drifted.playlists[0].drift_choices == (
            DriftResolution.RESTORE.value, DriftResolution.REVOKE.value,
        )
        assert spotify.playlists[playlist_id]["tracks"] == ["spotify:track:second"]

        restored = transfer.execute(TransferRequest(
            source=fixture["reference"],
            drift_resolution=DriftResolution.RESTORE,
        ))

        assert restored.status == "completed"
        assert spotify.playlists[playlist_id]["tracks"] == [
            "spotify:track:first", "spotify:track:second",
        ]

    def test_refresh_can_explicitly_revoke_a_drifted_approved_match(self, tmp_path):
        fixture = json.loads(MIRROR_REFRESH_FIXTURE.read_text())

        class MirrorSource:
            source_label = "Rekordbox"
            default_mode = TransferMode.MIRROR

            def consume(self, reference):
                return SourceSelection(
                    fixture["name"], fixture["reference"],
                    [Track(
                        track_id=item["track_id"], artist=item["artist"],
                        name=item["name"], duration=item["duration"], album="",
                        remixer="", label="", genre="", date_added="",
                    ) for item in fixture["initial"]],
                )

        spotify = StatefulSpotify({
            ("Artist One", "First Track"): _match(
                "spotify:track:first", "First Track", "Artist One",
            ),
            ("Artist Two", "Second Track"): _match(
                "spotify:track:second", "Second Track", "Artist Two",
            ),
        })
        cache = MatchCache(tmp_path / "knowledge.json")
        knowledge = MatchCacheKnowledge(cache)
        publications = FilePublicationStorage(tmp_path / "publications.json")
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS, source=MirrorSource(),
            spotify=spotify, matching_knowledge=knowledge,
            publication_storage=publications,
        )
        initial = transfer.execute(TransferRequest(source=fixture["reference"]))
        playlist_id = initial.playlists[0].spotify_playlist_id
        transfer.approve(playlist_id)
        spotify.playlists[playlist_id]["tracks"] = ["spotify:track:second"]

        revoked = transfer.execute(TransferRequest(
            source=fixture["reference"],
            drift_resolution=DriftResolution.REVOKE,
        ))

        assert revoked.status == "completed"
        assert spotify.playlists[playlist_id]["tracks"] == ["spotify:track:second"]
        assert knowledge.lookup(
            Track(
                track_id="rb-1", artist="Artist One", name="First Track",
                duration=301, album="", remixer="", label="", genre="",
                date_added="",
            ), 80,
        ) is None

    def test_refresh_reuses_approved_matches_without_repeated_review(self, tmp_path):
        fixture = json.loads(MIRROR_REFRESH_FIXTURE.read_text())

        class RefreshSource:
            source_label = "Rekordbox"
            default_mode = TransferMode.MIRROR
            phase = "initial"

            def consume(self, reference):
                tracks = [
                    Track(
                        track_id=item["track_id"], artist=item["artist"],
                        name=item["name"], duration=item["duration"], album="",
                        remixer="", label="", genre="", date_added="",
                    )
                    for item in fixture[self.phase]
                ]
                return SourceSelection(fixture["name"], fixture["reference"], tracks)

        source = RefreshSource()
        spotify = StatefulSpotify({
            ("Artist One", "First Track"): _match(
                "spotify:track:first", "First Track", "Artist One",
            ),
            ("Artist Two", "Second Track"): _match(
                "spotify:track:second", "Second Track", "Artist Two",
            ),
            ("Artist Three", "Third Track"): _match(
                "spotify:track:third", "Third Track", "Artist Three",
            ),
        })
        knowledge = MatchCacheKnowledge(MatchCache(tmp_path / "knowledge.json"))
        publications = FilePublicationStorage(tmp_path / "publications.json")
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS, source=source,
            spotify=spotify, matching_knowledge=knowledge,
            publication_storage=publications,
        )
        initial = transfer.execute(TransferRequest(source=fixture["reference"]))
        transfer.approve(initial.playlists[0].spotify_playlist_id)

        source.phase = "refreshed"
        refreshed = transfer.execute(TransferRequest(source=fixture["reference"]))

        assert spotify.searches.count(("Artist Two", "Second Track", 80)) == 1
        assert [
            item.source_track_id
            for item in refreshed.playlists[0].publication_manifest.items
        ] == ["rb-3"]

    def test_unavailable_approved_track_is_not_a_genuine_source_removal(self, tmp_path):
        fixture = json.loads(MIRROR_REFRESH_FIXTURE.read_text())

        class MirrorSource:
            source_label = "Rekordbox"
            default_mode = TransferMode.MIRROR

            def consume(self, reference):
                return SourceSelection(
                    fixture["name"], fixture["reference"],
                    [Track(
                        track_id=item["track_id"], artist=item["artist"],
                        name=item["name"], duration=item["duration"], album="",
                        remixer="", label="", genre="", date_added="",
                    ) for item in fixture["initial"]],
                )

        spotify = StatefulSpotify({
            ("Artist One", "First Track"): _match(
                "spotify:track:first", "First Track", "Artist One",
            ),
            ("Artist Two", "Second Track"): _match(
                "spotify:track:second", "Second Track", "Artist Two",
            ),
        })
        knowledge = MatchCacheKnowledge(MatchCache(tmp_path / "knowledge.json"))
        publications = FilePublicationStorage(tmp_path / "publications.json")
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS, source=MirrorSource(),
            spotify=spotify, matching_knowledge=knowledge,
            publication_storage=publications,
        )
        initial = transfer.execute(TransferRequest(source=fixture["reference"]))
        playlist_id = initial.playlists[0].spotify_playlist_id
        transfer.approve(playlist_id)
        original_spotify_track = spotify.spotify_track
        spotify.spotify_track = lambda uri: (
            {**original_spotify_track(uri), "is_playable": False}
            if uri == "spotify:track:first" else original_spotify_track(uri)
        )

        refreshed = transfer.execute(TransferRequest(source=fixture["reference"]))

        assert refreshed.playlists[0].source_removals == []
        assert [
            item.source_track_id
            for item in refreshed.playlists[0].unavailable_approved
        ] == ["rb-1"]
        assert spotify.playlists[playlist_id]["tracks"] == [
            "spotify:track:first", "spotify:track:second",
        ]

    def test_refresh_preserves_occurrences_order_and_reports_genuine_source_removals(
        self, tmp_path,
    ):
        fixture = json.loads(MIRROR_REFRESH_FIXTURE.read_text())

        class RefreshSource:
            source_label = "Rekordbox"
            default_mode = TransferMode.MIRROR
            phase = "initial"

            def consume(self, reference):
                return SourceSelection(
                    fixture["name"], fixture["reference"],
                    [Track(
                        track_id=item["track_id"], artist=item["artist"],
                        name=item["name"], duration=item["duration"], album="",
                        remixer="", label="", genre="", date_added="",
                    ) for item in fixture[self.phase]],
                )

        source = RefreshSource()
        spotify = StatefulSpotify({
            ("Artist One", "First Track"): _match(
                "spotify:track:first", "First Track", "Artist One",
            ),
            ("Artist Two", "Second Track"): _match(
                "spotify:track:second", "Second Track", "Artist Two",
            ),
            ("Artist Three", "Third Track"): _match(
                "spotify:track:third", "Third Track", "Artist Three",
            ),
        })
        knowledge = MatchCacheKnowledge(MatchCache(tmp_path / "knowledge.json"))
        publications = FilePublicationStorage(tmp_path / "publications.json")
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS, source=source,
            spotify=spotify, matching_knowledge=knowledge,
            publication_storage=publications,
        )
        initial = transfer.execute(TransferRequest(source=fixture["reference"]))
        transfer.approve(initial.playlists[0].spotify_playlist_id)

        source.phase = "refreshed"
        refreshed = transfer.execute(TransferRequest(source=fixture["reference"]))
        playlist = refreshed.playlists[0]

        assert spotify.playlists[playlist.spotify_playlist_id]["tracks"] == [
            "spotify:track:second", "spotify:track:third",
            "spotify:track:second",
        ]
        assert [removal.source_track_id for removal in playlist.source_removals] == [
            "rb-1"
        ]
        report_path = tmp_path / "refresh-report.md"
        save_report(refreshed, str(report_path))
        assert "rb-1: Artist One - First Track" in report_path.read_text()

        transfer.approve(playlist.spotify_playlist_id)
        source.phase = "final"
        final = transfer.execute(TransferRequest(source=fixture["reference"]))

        assert [removal.source_track_id for removal in final.playlists[0].source_removals] == [
            "rb-2", "rb-2-copy",
        ]

    def test_missing_rekordbox_track_stops_before_matching_or_publication(self):
        spotify = StatefulSpotify()
        storage = InMemoryStorage()

        with pytest.raises(ValueError, match="missing track references: missing"):
            Transfer(
                publishing_guards=TEST_PUBLISHING_GUARDS,
                source=RekordboxPlaylistSource(INCOMPLETE_REKORDBOX_FIXTURE),
                spotify=spotify, matching_knowledge=storage,
                publication_storage=storage,
            ).execute(TransferRequest(source="Incomplete"))

        assert spotify.searches == []
        assert spotify.playlists == {"existing": ["spotify:track:untouched"]}
        assert storage.publications == []

    def test_one_selected_playlist_previews_publishes_and_approval_retains_mirror(
        self, tmp_path,
    ):
        matches = {
            ("Solomun", "Vultora (Original Mix)"): _match(
                "spotify:track:vultora", "Vultora (Original Mix)", "Solomun",
            ),
            ("Eagles & Butterflies", "Sapphire (Joris Voorn Remix)"): _match(
                "spotify:track:sapphire", "Sapphire (Joris Voorn Remix)",
                "Eagles & Butterflies",
            ),
        }
        spotify = StatefulSpotify(matches)
        cache = MatchCache(str(tmp_path / "matching-knowledge.json"))
        knowledge = MatchCacheKnowledge(cache)
        publications = FilePublicationStorage(tmp_path / "playlist-state.json")
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=RekordboxPlaylistSource(REKORDBOX_FIXTURE), spotify=spotify,
            matching_knowledge=knowledge, publication_storage=publications,
        )

        preview = transfer.execute(TransferRequest(
            source="My Playlists/Peak Time", preview=True,
        ))
        published = transfer.execute(TransferRequest(
            source="My Playlists/Peak Time",
        ))

        playlist = published.playlists[0]
        assert preview.playlists[0].action == "preview"
        assert preview.total_matched == 2
        assert spotify.searches == [
            ("Solomun", "Vultora (Original Mix)", 80),
            ("Eagles & Butterflies", "Sapphire (Joris Voorn Remix)", 80),
        ]
        assert playlist.action == "provisional mirror updated"
        assert playlist.publication_manifest.mode == TransferMode.MIRROR
        assert spotify.playlists[playlist.spotify_playlist_id]["tracks"] == [
            "spotify:track:vultora", "spotify:track:sapphire",
        ]
        assert publications.mirrors_for_account("spotify-user-1") == []

        approval = transfer.approve(playlist.spotify_playlist_id)

        assert approval.status == ApprovalStatus.APPROVED
        reloaded_state = FilePublicationStorage(tmp_path / "playlist-state.json")
        mirrors = reloaded_state.mirrors_for_account("spotify-user-1")
        assert len(mirrors) == 1
        assert mirrors[0].source_reference == "My Playlists/Peak Time"
        assert mirrors[0].spotify_playlist_id == playlist.spotify_playlist_id
        assert MatchCacheKnowledge(cache).lookup(
            Track(
                track_id="another-source-id", name="Vultora (Original Mix)",
                artist="Solomun", album="", remixer="", label="", genre="",
                date_added="", duration=412,
            ),
            80,
        )["authoritative"] is True


class TestRekordboxBatchPlanning:
    def test_preview_plan_executes_without_publication_state(self, tmp_path):
        spotify = StatefulSpotify({
            ("Solomun", "Vultora (Original Mix)"): _match(
                "spotify:track:vultora", "Vultora (Original Mix)", "Solomun",
            ),
            ("Eagles & Butterflies", "Sapphire (Joris Voorn Remix)"): _match(
                "spotify:track:sapphire", "Sapphire (Joris Voorn Remix)",
                "Eagles & Butterflies",
            ),
        })
        storage = InMemoryStorage()
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=RekordboxPlaylistSource(REKORDBOX_FIXTURE), spotify=spotify,
            matching_knowledge=storage, publication_storage=storage,
            transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
        )

        plan = transfer.plan_batch(BatchPlanRequest(
            playlist_references=("My Playlists/Peak Time",), preview=True,
        ))
        report = transfer.execute_batch(plan)

        assert report.dry_run is True
        assert report.playlists[0].action == "preview"
        assert storage.publications == []
        assert spotify.playlists == {"existing": ["spotify:track:untouched"]}

    def test_explicit_playlists_are_planned_without_spotify_or_state_mutation(self):
        spotify = StatefulSpotify()
        knowledge = InMemoryStorage()
        knowledge.matches[("Solomun", "Vultora (Original Mix)")] = {
            **_match("spotify:track:vultora", "Vultora (Original Mix)", "Solomun"),
            "authoritative": True,
        }
        knowledge.matches[(
            "Eagles & Butterflies", "Sapphire (Joris Voorn Remix)",
        )] = _match(
            "spotify:track:sapphire", "Sapphire (Joris Voorn Remix)",
            "Eagles & Butterflies",
        )
        storage = InMemoryStorage()
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=RekordboxPlaylistSource(REKORDBOX_FIXTURE), spotify=spotify,
            matching_knowledge=knowledge, publication_storage=storage,
            transfer_storage=storage,
        )

        plan = transfer.plan_batch(BatchPlanRequest(playlist_references=(
            "My Playlists/Peak Time", "My Playlists/Deep",
        )))

        assert [playlist.reference for playlist in plan.playlists] == [
            "My Playlists/Peak Time", "My Playlists/Deep",
        ]
        assert plan.total_tracks == 3
        assert plan.approved_match_hits == 1
        assert plan.cache_hits == 1
        assert plan.expected_uncached_lookups == 1
        assert spotify.searches == []
        assert spotify.playlists == {"existing": ["spotify:track:untouched"]}
        assert storage.publications == []
        assert storage.playlist_writes == 0
        assert storage.matches == {}
        assert knowledge.checkpoints == 0

    def test_omitted_selection_is_not_inferred_as_the_whole_library(self):
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=RekordboxPlaylistSource(REKORDBOX_FIXTURE),
            spotify=StatefulSpotify(), matching_knowledge=InMemoryStorage(),
        )

        with pytest.raises(ValueError, match="select at least one playlist"):
            transfer.plan_batch(BatchPlanRequest())

        whole_library = transfer.plan_batch(BatchPlanRequest(whole_library=True))

        assert [playlist.reference for playlist in whole_library.playlists] == [
            "My Playlists/Peak Time", "My Playlists/Deep",
        ]
        assert whole_library.total_tracks == 3

    def test_expensive_plan_requires_confirmation_without_a_lookup_ceiling(self):
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=RekordboxPlaylistSource(REKORDBOX_FIXTURE),
            spotify=StatefulSpotify(), matching_knowledge=InMemoryStorage(),
        )

        unconfirmed = transfer.plan_batch(BatchPlanRequest(
            whole_library=True,
        ))
        confirmed = transfer.plan_batch(BatchPlanRequest(
            whole_library=True, confirm_expensive=True,
        ))

        assert unconfirmed.expected_uncached_lookups == 3
        assert unconfirmed.confirmation_required is True
        assert unconfirmed.ready is False
        assert confirmed.expected_uncached_lookups == 3
        assert confirmed.confirmation_required is False
        assert confirmed.ready is True

    def test_duplicate_playlist_references_are_not_a_batch_set(self):
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=RekordboxPlaylistSource(REKORDBOX_FIXTURE),
            spotify=StatefulSpotify(), matching_knowledge=InMemoryStorage(),
        )

        with pytest.raises(ValueError, match="duplicate playlist"):
            transfer.plan_batch(BatchPlanRequest(playlist_references=(
                "Deep", "My Playlists/Deep",
            )))

    def test_positive_and_negative_cache_entries_are_not_expected_lookups(
        self, tmp_path,
    ):
        cache = MatchCache(str(tmp_path / "matching-knowledge.json"))
        cache.record_approval(
            "Solomun", "Vultora (Original Mix)", "approved",
            _match("spotify:track:vultora", "Vultora (Original Mix)", "Solomun"),
            412,
        )
        cache.store(
            "Eagles & Butterflies", "Sapphire (Joris Voorn Remix)", 80,
            _match(
                "spotify:track:sapphire", "Sapphire (Joris Voorn Remix)",
                "Eagles & Butterflies",
            ),
        )
        cache.store("Âme", "Für Immer", 80, None)
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=RekordboxPlaylistSource(REKORDBOX_FIXTURE),
            spotify=StatefulSpotify(),
            matching_knowledge=MatchCacheKnowledge(cache),
        )

        plan = transfer.plan_batch(BatchPlanRequest(whole_library=True))

        assert plan.approved_match_hits == 1
        assert plan.cache_hits == 2
        assert plan.expected_uncached_lookups == 0


class TestRekordboxBatchExecution:
    def test_playlist_failure_preserves_completed_work_and_continues(self, tmp_path):
        class PlaylistFailureSpotify(StatefulSpotify):
            def match(self, track, threshold):
                if track.name == "Für Immer":
                    raise ValueError("playlist-specific bad track")
                return super().match(track, threshold)

        spotify = PlaylistFailureSpotify({
            ("Solomun", "Vultora (Original Mix)"): _match(
                "spotify:track:vultora", "Vultora (Original Mix)", "Solomun",
            ),
            ("Eagles & Butterflies", "Sapphire (Joris Voorn Remix)"): _match(
                "spotify:track:sapphire", "Sapphire (Joris Voorn Remix)",
                "Eagles & Butterflies",
            ),
        })
        storage = InMemoryStorage()
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=RekordboxPlaylistSource(REKORDBOX_FIXTURE), spotify=spotify,
            matching_knowledge=storage, publication_storage=storage,
            transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
        )
        plan = transfer.plan_batch(BatchPlanRequest(
            playlist_references=(
                "My Playlists/Peak Time", "My Playlists/Deep",
            ),
        ))

        report = transfer.execute_batch(plan)

        assert report.status == "partial success"
        assert [playlist.outcome for playlist in report.playlists] == [
            "completed", "failed",
        ]
        assert len(storage.publications) == 1
        assert spotify.playlists["snapshot-1"]["tracks"] == [
            "spotify:track:vultora", "spotify:track:sapphire",
        ]

    def test_playlist_failure_does_not_block_a_later_independent_playlist(
        self, tmp_path,
    ):
        class PlaylistFailureSpotify(StatefulSpotify):
            def match(self, track, threshold):
                if track.name == "Für Immer":
                    raise ValueError("playlist-specific bad track")
                return super().match(track, threshold)

        spotify = PlaylistFailureSpotify({
            ("Solomun", "Vultora (Original Mix)"): _match(
                "spotify:track:vultora", "Vultora (Original Mix)", "Solomun",
            ),
            ("Eagles & Butterflies", "Sapphire (Joris Voorn Remix)"): _match(
                "spotify:track:sapphire", "Sapphire (Joris Voorn Remix)",
                "Eagles & Butterflies",
            ),
        })
        storage = InMemoryStorage()
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=RekordboxPlaylistSource(REKORDBOX_FIXTURE), spotify=spotify,
            matching_knowledge=storage, publication_storage=storage,
            transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
        )

        report = transfer.execute_batch(transfer.plan_batch(BatchPlanRequest(
            playlist_references=(
                "My Playlists/Deep", "My Playlists/Peak Time",
            ),
        )))

        assert [playlist.outcome for playlist in report.playlists] == [
            "failed", "completed",
        ]
        assert spotify.playlists["snapshot-1"]["tracks"] == [
            "spotify:track:vultora", "spotify:track:sapphire",
        ]

    def test_shared_failure_stops_and_skips_later_playlists(self, tmp_path):
        class RateLimitedSpotify(StatefulSpotify):
            def match(self, track, threshold):
                raise RateLimitError(3600)

        storage = InMemoryStorage()
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=RekordboxPlaylistSource(REKORDBOX_FIXTURE),
            spotify=RateLimitedSpotify(), matching_knowledge=storage,
            publication_storage=storage,
            transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
        )
        plan = transfer.plan_batch(BatchPlanRequest(
            playlist_references=(
                "My Playlists/Peak Time", "My Playlists/Deep",
            ),
        ))

        report = transfer.execute_batch(plan)

        assert report.status == "paused"
        assert [playlist.outcome for playlist in report.playlists] == [
            "pending", "skipped",
        ]
        assert report.playlists[1].action == "skipped after shared failure"
        assert storage.publications == []
        durable = FileTransferStorage(tmp_path / "transfers.json").load_batch(
            report.transfer_id
        )
        assert [(item.phase, item.outcome) for item in durable.playlists] == [
            ("paused", "pending"), ("pending", "skipped"),
        ]
        assert durable.status == "paused"

    def test_resume_after_shared_failure_keeps_completed_publication(self, tmp_path):
        class RecoveringSpotify(StatefulSpotify):
            unavailable = True
            authentication_unavailable = False

            def account_id(self):
                if self.authentication_unavailable:
                    raise spotipy.SpotifyException(401, -1, "expired token")
                return super().account_id()

            def match(self, track, threshold):
                if track.name == "Für Immer" and self.unavailable:
                    raise requests.ConnectionError("Spotify unavailable")
                return super().match(track, threshold)

        spotify = RecoveringSpotify({
            ("Solomun", "Vultora (Original Mix)"): _match(
                "spotify:track:vultora", "Vultora (Original Mix)", "Solomun",
            ),
            ("Eagles & Butterflies", "Sapphire (Joris Voorn Remix)"): _match(
                "spotify:track:sapphire", "Sapphire (Joris Voorn Remix)",
                "Eagles & Butterflies",
            ),
            ("Âme", "Für Immer"): _match(
                "spotify:track:fur-immer", "Für Immer", "Âme",
            ),
        })
        publications = InMemoryStorage()
        states = FileTransferStorage(tmp_path / "transfers.json")
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=RekordboxPlaylistSource(REKORDBOX_FIXTURE), spotify=spotify,
            matching_knowledge=InMemoryStorage(), publication_storage=publications,
            transfer_storage=states,
            retry_policy=RetryPolicy(max_attempts=1, sleep=lambda _: None),
        )
        plan = transfer.plan_batch(BatchPlanRequest(
            playlist_references=(
                "My Playlists/Peak Time", "My Playlists/Deep",
            ),
        ))

        stopped = transfer.execute_batch(plan)

        assert stopped.status == "partial success"
        assert [playlist.outcome for playlist in stopped.playlists] == [
            "completed", "pending",
        ]
        assert len(publications.publications) == 1
        completed_searches = list(spotify.searches)

        spotify.authentication_unavailable = True
        auth_stopped = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=RekordboxPlaylistSource(REKORDBOX_FIXTURE), spotify=spotify,
            matching_knowledge=InMemoryStorage(), publication_storage=publications,
            transfer_storage=FileTransferStorage(states.path),
            retry_policy=RetryPolicy(max_attempts=1, sleep=lambda _: None),
        ).execute_batch(plan, transfer_id=stopped.transfer_id)

        assert auth_stopped.status == "partial success"
        assert [playlist.outcome for playlist in auth_stopped.playlists] == [
            "completed", "pending",
        ]
        assert len(publications.publications) == 1

        spotify.authentication_unavailable = False
        spotify.unavailable = False
        resumed = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=RekordboxPlaylistSource(REKORDBOX_FIXTURE), spotify=spotify,
            matching_knowledge=InMemoryStorage(), publication_storage=publications,
            transfer_storage=FileTransferStorage(states.path),
            retry_policy=RetryPolicy(max_attempts=1, sleep=lambda _: None),
        ).execute_batch(plan, transfer_id=stopped.transfer_id)

        assert resumed.status == "completed"
        assert spotify.searches[:2] == completed_searches
        assert spotify.searches.count(
            ("Solomun", "Vultora (Original Mix)", 80)
        ) == 1
        assert len(publications.publications) == 2

    def test_authentication_failure_before_account_discovery_is_checkpointed(
        self, tmp_path,
    ):
        class UnauthenticatedSpotify(StatefulSpotify):
            def account_id(self):
                raise spotipy.SpotifyException(401, -1, "expired token")

        states = FileTransferStorage(tmp_path / "transfers.json")
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=RekordboxPlaylistSource(REKORDBOX_FIXTURE),
            spotify=UnauthenticatedSpotify(), matching_knowledge=InMemoryStorage(),
            publication_storage=InMemoryStorage(), transfer_storage=states,
        )
        plan = transfer.plan_batch(BatchPlanRequest(
            playlist_references=(
                "My Playlists/Peak Time", "My Playlists/Deep",
            ),
        ))

        report = transfer.execute_batch(plan)

        assert report.status == "paused"
        assert [playlist.outcome for playlist in report.playlists] == [
            "pending", "pending",
        ]
        durable = FileTransferStorage(states.path).load_batch(report.transfer_id)
        assert durable.status == "paused"
        assert durable.account_id is None

    def test_failed_playlist_report_retains_completed_matching_progress(self, tmp_path):
        class SecondTrackFailureSpotify(StatefulSpotify):
            def match(self, track, threshold):
                if track.name == "Sapphire (Joris Voorn Remix)":
                    raise ValueError("playlist-specific bad track")
                return super().match(track, threshold)

        spotify = SecondTrackFailureSpotify({
            ("Solomun", "Vultora (Original Mix)"): _match(
                "spotify:track:vultora", "Vultora (Original Mix)", "Solomun",
            ),
        })
        storage = InMemoryStorage()
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=RekordboxPlaylistSource(REKORDBOX_FIXTURE), spotify=spotify,
            matching_knowledge=storage, publication_storage=storage,
            transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
        )

        report = transfer.execute_batch(transfer.plan_batch(BatchPlanRequest(
            playlist_references=("My Playlists/Peak Time",),
        )))

        assert report.playlists[0].outcome == "failed"
        assert [match.source_name for match in report.playlists[0].matched] == [
            "Solomun - Vultora (Original Mix)",
        ]

    def test_paused_batch_reloads_and_resumes_without_repeating_effects(self, tmp_path):
        matches = {
            ("Solomun", "Vultora (Original Mix)"): _match(
                "spotify:track:vultora", "Vultora (Original Mix)", "Solomun",
            ),
            ("Eagles & Butterflies", "Sapphire (Joris Voorn Remix)"): _match(
                "spotify:track:sapphire", "Sapphire (Joris Voorn Remix)",
                "Eagles & Butterflies",
            ),
            ("Âme", "Für Immer"): _match(
                "spotify:track:fur-immer", "Für Immer", "Âme",
            ),
        }
        spotify = StatefulSpotify(matches)
        publications = InMemoryStorage()
        state_path = tmp_path / "transfers.json"
        first = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=RekordboxPlaylistSource(REKORDBOX_FIXTURE), spotify=spotify,
            matching_knowledge=InMemoryStorage(), publication_storage=publications,
            transfer_storage=FileTransferStorage(state_path),
        )
        plan = first.plan_batch(BatchPlanRequest(
            playlist_references=(
                "My Playlists/Peak Time", "My Playlists/Deep",
            ),
        ))
        first.pause()

        paused = first.execute_batch(plan)

        assert paused.status == "paused"
        assert [playlist.outcome for playlist in paused.playlists] == [
            "pending", "pending",
        ]
        assert spotify.searches == [("Solomun", "Vultora (Original Mix)", 80)]

        resumed = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=RekordboxPlaylistSource(REKORDBOX_FIXTURE), spotify=spotify,
            matching_knowledge=InMemoryStorage(), publication_storage=publications,
            transfer_storage=FileTransferStorage(state_path),
        ).execute_batch(plan, transfer_id=paused.transfer_id)

        assert resumed.status == "completed"
        assert [playlist.outcome for playlist in resumed.playlists] == [
            "completed", "completed",
        ]
        assert spotify.searches == [
            ("Solomun", "Vultora (Original Mix)", 80),
            ("Eagles & Butterflies", "Sapphire (Joris Voorn Remix)", 80),
            ("Âme", "Für Immer", 80),
        ]
        assert len(publications.publications) == 2

        report_path = tmp_path / "batch-report.md"
        save_report(resumed, str(report_path))
        text = report_path.read_text()
        assert "**Outcome:** completed" in text
        assert "**Status:** completed" in text


class TestTransferPublicationLifecycle:
    def test_transfer_state_schema_four_remains_readable(self, tmp_path):
        state_path = tmp_path / "transfers.json"
        state_path.write_text(json.dumps({
            "version": 4,
            "transfers": {},
            "batches": {},
            "qualifications": {},
        }))

        storage = FileTransferStorage(state_path)

        assert storage.transfers == {}
        assert storage.batches == {}
        assert storage.qualifications == {}

    @pytest.mark.parametrize("stored", [
        '{"version": 99, "transfers": {"private": {}}}',
        '{"version": 4, "qualifications": {"private": {"draft_id": "x"}}}',
        '{"version": 4, "transfers": ',
    ])
    def test_transfer_state_fails_closed_without_rewriting_unknown_data(
        self, tmp_path, stored,
    ):
        state_path = tmp_path / "transfers.json"
        state_path.write_text(stored)
        original = state_path.read_bytes()

        with pytest.raises(ValueError, match="Transfer state"):
            FileTransferStorage(state_path)

        assert state_path.read_bytes() == original

    def test_settled_playlist_copy_hides_recovery_key_and_retains_curator(self, tmp_path):
        class LifecycleSpotify(StatefulSpotify):
            def set_playlist_description(self, playlist_id, description):
                self.playlists[playlist_id]["description"] = description

        class ChartSource(FixtureBeatportSource):
            def consume(self, reference):
                selection = super().consume(reference)
                return SourceSelection(
                    "Synthetic Chart — Ada DJ", selection.reference, selection.tracks,
                    chart_title="Synthetic Chart", curator="Ada DJ",
                )

        spotify = LifecycleSpotify({
            ("Known Artist", "Known Track"): _match(
                "spotify:track:known", "Known Track", "Known Artist",
            ),
        })
        report = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=ChartSource(FIXTURE), spotify=spotify,
            matching_knowledge=InMemoryStorage(),
            publication_storage=InMemoryStorage(),
            transfer_storage=FileTransferStorage(tmp_path / "transfers.json"),
        ).execute(TransferRequest(source="fixture", transfer_id="transfer-private"))

        playlist = spotify.playlists[report.playlists[0].spotify_playlist_id]
        assert report.playlists[0].name.startswith(
            "djsupport / Synthetic Chart — Ada DJ"
        )
        assert "awaiting review and Approval" in playlist["description"]
        assert "fixture" in playlist["description"]
        assert "transfer-private" not in playlist["description"]
        assert "Created " not in playlist["description"]
    def test_mixed_publication_retains_one_review_entry_per_source_track(
        self, tmp_path,
    ):
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
        manifest = report.playlists[0].publication_manifest
        review_csv = tmp_path / "review.csv"
        save_review_csv(report, str(review_csv))

        assert [item.source_track_id for item in manifest.items] == ["bp-1", "bp-2"]
        assert [item.spotify_uri for item in manifest.items] == [
            "spotify:track:known", "",
        ]
        with review_csv.open(newline="") as csv_file:
            rows = list(csv.DictReader(csv_file))
        assert [row["source_track_id"] for row in rows] == ["bp-1", "bp-2"]
        assert rows[1] == {
            "source_track_id": "bp-2",
            "source_track": "New Artist - New Track",
            "source_artist": "New Artist",
            "source_title": "New Track",
            "source_release": "",
            "source_label": "",
            "source_version": "",
            "source_duration": "420",
            "spotify_url": "",
            "spotify_track": "",
            "spotify_release": "",
            "spotify_duration": "0",
            "authority_status": "proposal",
            "score": "",
            "match_type": "unmatched",
            "score_reasons": "",
        }

    def test_prepared_transfer_is_visible_before_source_intake_and_resumes(self, tmp_path):
        class CountingSource(FixtureBeatportSource):
            consumptions = 0

            def consume(self, reference):
                self.consumptions += 1
                return super().consume(reference)

        source = CountingSource(FIXTURE)
        spotify = StatefulSpotify()
        state_path = tmp_path / "transfers.json"
        request = TransferRequest(
            source="fixture", preview=True, transfer_id="prepared-transfer",
        )
        Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=source, spotify=spotify, matching_knowledge=InMemoryStorage(),
            transfer_storage=FileTransferStorage(state_path),
        ).prepare(request)

        reloaded = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=source, spotify=spotify, matching_knowledge=InMemoryStorage(),
            transfer_storage=FileTransferStorage(state_path),
        )
        progress = reloaded.progress("prepared-transfer")
        report = reloaded.execute(request)

        assert progress.status == "matching"
        assert (progress.current, progress.total) == (0, 0)
        assert source.consumptions == 1
        assert report.status == "completed"

    def test_failure_is_a_durable_observable_outcome(self, tmp_path):
        class FailingSource:
            source_label = "Beatport"
            recovered = False

            def consume(self, reference):
                if not self.recovered:
                    raise ValueError("fixture intake failed")
                return SourceSelection("Recovered", reference, [])

        state_path = tmp_path / "transfers.json"
        request = TransferRequest(
            source="fixture", preview=True, transfer_id="failed-transfer",
        )
        source = FailingSource()
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=source, spotify=StatefulSpotify(),
            matching_knowledge=InMemoryStorage(),
            transfer_storage=FileTransferStorage(state_path),
        )
        transfer.prepare(request)
        with pytest.raises(ValueError, match="fixture intake failed"):
            transfer.execute(request)

        progress = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=FailingSource(), spotify=StatefulSpotify(),
            matching_knowledge=InMemoryStorage(),
            transfer_storage=FileTransferStorage(state_path),
        ).progress("failed-transfer")

        assert progress.status == "paused"
        assert progress.error == "fixture intake failed"

        source.recovered = True
        transfer.prepare(request)
        resumed_progress = transfer.progress("failed-transfer")
        resumed = transfer.execute(request)

        assert resumed_progress.status == "matching"
        assert resumed_progress.error is None
        assert resumed.status == "completed"

    def test_progress_reloads_from_durable_state_without_resuming_work(self, tmp_path):
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

        progress = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=InMemoryStorage(),
            publication_storage=InMemoryStorage(),
            transfer_storage=FileTransferStorage(state_path),
        ).progress(paused.transfer_id)

        assert progress.status == "paused"
        assert progress.current == 1
        assert progress.total == 2
        assert progress.source == "fixture"
        assert spotify.searches == [("Known Artist", "Known Track", 80)]

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


    def test_unmatched_tracks_are_omitted_from_provisional_snapshot(self):
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

        playlist = report.playlists[0]
        assert playlist.action == "provisional snapshot created"
        assert spotify.playlists[playlist.spotify_playlist_id]["tracks"] == [
            "spotify:track:known",
        ]
        assert len(storage.publications) == 1

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

    def test_version_one_publication_state_migrates_when_mirror_state_is_saved(
        self, tmp_path,
    ):
        path = tmp_path / "publication-manifests.json"
        path.write_text(json.dumps({
            "version": 1,
            "manifests": [],
            "approvals": [],
        }))
        storage = FilePublicationStorage(path)

        storage.retain_mirror(MirrorRelationship(
            account_id="spotify-user-1",
            source_label="Rekordbox",
            source_reference="My Playlists/Peak Time",
            spotify_playlist_id="mirror-1",
            spotify_playlist_name="Peak Time",
            approved_at=datetime(2026, 8, 1),
        ))

        assert json.loads(path.read_text())["version"] == 6
        assert len(FilePublicationStorage(path).mirrors_for_account(
            "spotify-user-1"
        )) == 1

    def test_version_three_publication_without_unmatched_entries_remains_readable(
        self, tmp_path,
    ):
        path = tmp_path / "publication-manifests.json"
        path.write_text(json.dumps({
            "version": 3,
            "manifests": [{
                "account_id": "spotify-user-1",
                "spotify_playlist_id": "legacy-playlist",
                "spotify_playlist_name": "Legacy",
                "source_label": "Beatport",
                "source_reference": "legacy-chart",
                "created_at": "2026-07-31T12:00:00",
                "mode": "snapshot",
                "items": [{
                    "source_track_id": "legacy-1",
                    "source_name": "Legacy Artist - Legacy Track",
                    "source_artist": "Legacy Artist",
                    "source_title": "Legacy Track",
                    "spotify_uri": "spotify:track:abcdefghijklmnopqrstuv",
                    "spotify_name": "Legacy Track",
                    "spotify_artist": "Legacy Artist",
                    "score": 95.0,
                    "match_type": "exact",
                }],
            }],
            "approvals": [],
            "mirrors": [],
        }))

        manifest = FilePublicationStorage(path).publication_for_playlist(
            "spotify-user-1", "legacy-playlist",
        )

        assert manifest is not None
        assert manifest.items[0].source_duration == 0
        assert manifest.items[0].authoritative is False
        assert manifest.managed_items == manifest.items

class TestProvisionalPlaylistApproval:
    def test_changed_head_discards_ordered_approval_read(self):
        transfer, spotify, storage, playlist_id = self.publish()
        spotify.playlist_head = MagicMock(side_effect=[
            SpotifyPlaylistHead("before"), SpotifyPlaylistHead("after"),
        ])
        spotify.ordered_playlist_items = MagicMock(return_value=SpotifyPlaylistPage((
            SpotifyPlaylistItem(
                0, SpotifyItemKind.TRACK, "spotify:track:known",
            ),
        )))

        with pytest.raises(Exception, match="changed during Approval"):
            transfer.approve(playlist_id)

        assert storage.approvals == []
        assert storage.approved_matches == []
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

    def test_review_csv_corrections_repair_playlist_and_become_local_truth(
        self, tmp_path,
    ):
        transfer, spotify, storage, playlist_id = self.publish()
        spotify.playlists[playlist_id]["tracks"] = [
            "spotify:track:abcdefghijklmnopqrstuv",
            "spotify:track:known",
            "spotify:track:new",
            "spotify:track:manual",
        ]
        review_csv = tmp_path / "review.csv"
        with review_csv.open("w", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=[
                "source_track_id", "source_track", "spotify_url",
                "spotify_track", "score", "match_type",
            ])
            writer.writeheader()
            writer.writerow({
                "source_track_id": "bp-2",
                "spotify_url": (
                    "https://open.spotify.com/track/abcdefghijklmnopqrstuv"
                    "?si=review"
                ),
            })

        review = transfer.approve(playlist_id, corrections=review_csv)

        assert spotify.playlists[playlist_id]["tracks"] == [
            "spotify:track:known",
            "spotify:track:abcdefghijklmnopqrstuv",
            "spotify:track:manual",
        ]
        assert [item.source_track_id for item in review.approved] == ["bp-1", "bp-2"]
        assert [item.spotify_uri for item in review.approved] == [
            "spotify:track:known", "spotify:track:abcdefghijklmnopqrstuv",
        ]
        assert review.rejected == ()
        assert review.corrections == (review.approved[1],)
        assert storage.corrections == [review.approved[1]]

    def test_unmatched_row_can_be_corrected_in_source_order_and_is_idempotent(
        self, tmp_path,
    ):
        spotify = StatefulSpotify({
            ("Known Artist", "Known Track"): _match(
                "spotify:track:known", "Known Track", "Known Artist",
            ),
        })
        storage = InMemoryStorage()
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=storage, publication_storage=storage,
        )
        report = transfer.execute(TransferRequest(source="fixture"))
        playlist_id = report.playlists[0].spotify_playlist_id
        spotify.playlists[playlist_id]["tracks"] = [
            "spotify:track:manual-before",
            "spotify:track:known",
            "spotify:track:manual-after",
        ]
        review_csv = tmp_path / "review.csv"
        review_csv.write_text(
            "source_track_id,spotify_url\n"
            "bp-2,spotify:track:abcdefghijklmnopqrstuv\n"
        )

        first = transfer.approve(playlist_id, corrections=review_csv)
        second = transfer.approve(playlist_id, corrections=review_csv)

        assert spotify.playlists[playlist_id]["tracks"] == [
            "spotify:track:manual-before",
            "spotify:track:known",
            "spotify:track:manual-after",
            "spotify:track:abcdefghijklmnopqrstuv",
        ]
        assert [item.source_track_id for item in first.approved] == ["bp-1", "bp-2"]
        assert first.rejected == ()
        assert first.corrections == (first.approved[1],)
        assert second.approved == first.approved
        assert spotify.playlist_replacements == 1
        assert storage.corrections == [first.approved[1], second.approved[1]]

    def test_blank_unmatched_row_remains_unresolved_not_rejected(self, tmp_path):
        spotify = StatefulSpotify({
            ("Known Artist", "Known Track"): _match(
                "spotify:track:known", "Known Track", "Known Artist",
            ),
        })
        storage = InMemoryStorage()
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=storage, publication_storage=storage,
        )
        report = transfer.execute(TransferRequest(source="fixture"))
        playlist_id = report.playlists[0].spotify_playlist_id
        review_csv = tmp_path / "review.csv"
        review_csv.write_text("source_track_id,spotify_url\nbp-2,\n")

        outcome = transfer.approve(playlist_id, corrections=review_csv)

        assert [item.source_track_id for item in outcome.approved] == ["bp-1"]
        assert outcome.rejected == ()
        assert storage.rejected_matches == []

    def test_preview_reports_unmatched_review_rows_without_publication(
        self, tmp_path,
    ):
        spotify = StatefulSpotify({
            ("Known Artist", "Known Track"): _match(
                "spotify:track:known", "Known Track", "Known Artist",
            ),
        })
        storage = InMemoryStorage()
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=storage, publication_storage=storage,
        )

        report = transfer.execute(TransferRequest(source="fixture", preview=True))
        review_csv = tmp_path / "preview.csv"
        save_review_csv(report, str(review_csv))

        with review_csv.open(newline="") as csv_file:
            rows = list(csv.DictReader(csv_file))
        assert [(row["source_track_id"], row["spotify_url"]) for row in rows] == [
            ("bp-1", "https://open.spotify.com/track/known"), ("bp-2", ""),
        ]
        assert storage.publications == []
        assert spotify.playlists == {"existing": ["spotify:track:untouched"]}
        with pytest.raises(ValueError, match="No Provisional Playlist"):
            transfer.approve("preview-only", corrections=review_csv)

    def test_unchanged_review_rows_are_ordinary_approvals(self, tmp_path):
        transfer, _, storage, playlist_id = self.publish()
        review_csv = tmp_path / "review.csv"
        with review_csv.open("w", newline="") as csv_file:
            writer = csv.DictWriter(
                csv_file, fieldnames=["source_track_id", "spotify_url"],
            )
            writer.writeheader()
            writer.writerow({
                "source_track_id": "bp-1",
                "spotify_url": "spotify:track:known",
            })

        review = transfer.approve(playlist_id, corrections=review_csv)

        assert [item.source_track_id for item in review.approved] == ["bp-1", "bp-2"]
        assert storage.corrections == []

    @pytest.mark.parametrize(
        ("rows", "message"),
        [
            ([{"source_track_id": "missing", "spotify_url": "spotify:track:abcdefghijklmnopqrstuv"}], "unknown source_track_id"),
            ([{"source_track_id": "", "spotify_url": "spotify:track:abcdefghijklmnopqrstuv"}], "unknown source_track_id"),
            ([{"source_track_id": "bp-1", "spotify_url": "https://example.com/track/abcdefghijklmnopqrstuv"}], "invalid Spotify track"),
            ([{"source_track_id": "bp-1", "spotify_url": "https://example.com/track/known"}], "invalid Spotify track"),
            ([
                {"source_track_id": "bp-1", "spotify_url": "spotify:track:abcdefghijklmnopqrstuv"},
                {"source_track_id": "bp-1", "spotify_url": "spotify:track:zyxwvutsrqponmlkjihgfe"},
            ], "repeats source_track_id"),
            ([
                {"source_track_id": "bp-1", "spotify_url": "spotify:track:known"},
                {"source_track_id": "bp-1", "spotify_url": "spotify:track:abcdefghijklmnopqrstuv"},
            ], "repeats source_track_id"),
            ([
                {"source_track_id": "bp-1", "spotify_url": ""},
                {"source_track_id": "bp-1", "spotify_url": "spotify:track:abcdefghijklmnopqrstuv"},
            ], "repeats source_track_id"),
        ],
    )
    def test_invalid_corrections_are_rejected_before_playlist_changes(
        self, tmp_path, rows, message,
    ):
        transfer, spotify, storage, playlist_id = self.publish()
        original = list(spotify.playlists[playlist_id]["tracks"])
        review_csv = tmp_path / "review.csv"
        with review_csv.open("w", newline="") as csv_file:
            writer = csv.DictWriter(
                csv_file, fieldnames=["source_track_id", "spotify_url"],
            )
            writer.writeheader()
            writer.writerows(rows)

        with pytest.raises(ValueError, match=message):
            transfer.approve(playlist_id, corrections=review_csv)

        assert spotify.playlists[playlist_id]["tracks"] == original
        assert storage.approvals == []
        assert storage.corrections == []

    def test_unresolvable_correction_fails_before_playlist_or_knowledge_mutation(
        self, tmp_path,
    ):
        transfer, spotify, storage, playlist_id = self.publish()
        original = list(spotify.playlists[playlist_id]["tracks"])
        spotify.spotify_track = lambda uri: {
            "uri": "spotify:track:zyxwvutsrqponmlkjihgfe",
            "name": "Different Track",
            "artist": "Different Artist",
        }
        review_csv = tmp_path / "review.csv"
        review_csv.write_text(
            "source_track_id,spotify_url\n"
            "bp-2,spotify:track:abcdefghijklmnopqrstuv\n"
        )

        with pytest.raises(ValueError, match="did not resolve"):
            transfer.approve(playlist_id, corrections=review_csv)

        assert spotify.playlists[playlist_id]["tracks"] == original
        assert spotify.playlist_replacements == 0
        assert storage.approvals == []
        assert storage.approved_matches == []
        assert storage.rejected_matches == []
        assert storage.corrections == []

    def test_correction_is_durable_approved_knowledge_and_local_regression(
        self, tmp_path,
    ):
        _, spotify, publications, playlist_id = self.publish()
        cache_path = tmp_path / "matching-knowledge.json"
        cache = MatchCache(str(cache_path))
        transfer = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=MatchCacheKnowledge(cache),
            publication_storage=publications,
        )
        review_csv = tmp_path / "review.csv"
        with review_csv.open("w", newline="") as csv_file:
            writer = csv.DictWriter(
                csv_file, fieldnames=["source_track_id", "spotify_url"],
            )
            writer.writeheader()
            writer.writerow({
                "source_track_id": "bp-2",
                "spotify_url": "spotify:track:abcdefghijklmnopqrstuv",
            })

        transfer.approve(playlist_id, corrections=review_csv)

        reloaded = MatchCache(str(cache_path))
        reloaded.load()
        approved = reloaded.lookup("New Artist", "New Track", 100)
        assert approved is not None
        assert approved.spotify_uri == "spotify:track:abcdefghijklmnopqrstuv"
        assert approved.approval_status == "approved"
        assert reloaded.local_regressions == [{
            "source_track_id": "bp-2",
            "source_artist": "New Artist",
            "source_title": "New Track",
            "source_duration": 420,
            "spotify_uri": "spotify:track:abcdefghijklmnopqrstuv",
            "spotify_name": "Corrected abcdefghijklmnopqrstuv",
            "spotify_artist": "Correction Artist",
        }]
        assert load_local_regressions(cache_path)[0]["duration"] == 420

    def test_approved_match_is_reused_across_sources_with_specific_identity(
        self, tmp_path,
    ):
        cache = MatchCache(str(tmp_path / "matching-knowledge.json"))
        beatport_spotify = StatefulSpotify({
            ("Shared Artist", "Shared Track (Extended Mix)"): _match(
                "spotify:track:approved", "Shared Track (Extended Mix)",
                "Shared Artist",
            ),
        })

        class Source:
            def __init__(self, label, track_id, duration=420):
                self.source_label = label
                self.track_id = track_id
                self.duration = duration

            def consume(self, reference):
                return SourceSelection(reference, reference, [Track(
                    track_id=self.track_id,
                    artist="Shared Artist",
                    name="Shared Track (Extended Mix)",
                    album="", remixer="", label="", genre="", date_added="",
                    duration=self.duration,
                )])

        publications = InMemoryStorage()
        beatport = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=Source("Beatport", "bp-42"), spotify=beatport_spotify,
            matching_knowledge=MatchCacheKnowledge(cache),
            publication_storage=publications,
        )
        published = beatport.execute(TransferRequest(source="chart"))
        beatport.approve(published.playlists[0].spotify_playlist_id)

        rekordbox_spotify = StatefulSpotify()
        reused = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=Source("Rekordbox", "rb-99"), spotify=rekordbox_spotify,
            matching_knowledge=MatchCacheKnowledge(cache),
        ).execute(TransferRequest(source="playlist", preview=True))

        assert reused.total_matched == 1
        assert reused.playlists[0].matched[0].spotify_uri == (
            "spotify:track:approved"
        )
        assert rekordbox_spotify.searches == []

        different_version_spotify = StatefulSpotify()
        different_version = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=Source("Rekordbox", "rb-100", duration=210),
            spotify=different_version_spotify,
            matching_knowledge=MatchCacheKnowledge(cache),
        ).execute(TransferRequest(source="playlist", preview=True))

        assert different_version.total_matched == 0
        assert different_version_spotify.searches == [
            ("Shared Artist", "Shared Track (Extended Mix)", 80),
        ]

        duration_missing_spotify = StatefulSpotify()
        duration_missing = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=Source("Beatport", "bp-101", duration=0),
            spotify=duration_missing_spotify,
            matching_knowledge=MatchCacheKnowledge(cache),
        ).execute(TransferRequest(source="chart", preview=True))

        assert duration_missing.total_matched == 1
        assert duration_missing_spotify.searches == []

    def test_conflicting_correction_does_not_overwrite_approved_truth(self, tmp_path):
        transfer, spotify, publications, playlist_id = self.publish()
        cache = MatchCache(str(tmp_path / "matching-knowledge.json"))
        durable = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=MatchCacheKnowledge(cache),
            publication_storage=publications,
        )
        durable.approve(playlist_id)
        review_csv = tmp_path / "review.csv"
        review_csv.write_text(
            "source_track_id,spotify_url\n"
            "bp-1,spotify:track:abcdefghijklmnopqrstuv\n"
        )

        conflict = durable.approve(playlist_id, corrections=review_csv)

        assert conflict.status == ApprovalStatus.NEEDS_REVIEW
        assert len(conflict.conflicts) == 1
        assert conflict.conflicts[0].approved_spotify_uri == "spotify:track:known"
        assert conflict.conflicts[0].proposed_spotify_uri == (
            "spotify:track:abcdefghijklmnopqrstuv"
        )
        reloaded = MatchCache(str(tmp_path / "matching-knowledge.json"))
        reloaded.load()
        assert reloaded.lookup("Known Artist", "Known Track", 100).spotify_uri == (
            "spotify:track:known"
        )

    def test_unavailable_approved_match_is_reported_without_replacement(self, tmp_path):
        class UnavailableApprovedSpotify(StatefulSpotify):
            def spotify_track(self, uri):
                if uri == "spotify:track:approved":
                    raise _spotify_error(404)
                return super().spotify_track(uri)

        cache = MatchCache(str(tmp_path / "matching-knowledge.json"))
        reason = "Spotify version is 31s shorter than source (5:29 vs 6:00)"
        approved = _match(
            "spotify:track:approved", "Known Track", "Known Artist",
        )
        approved["match_type"] = "shorter_version"
        approved["score_reasons"] = [reason]
        cache.record_approval(
            "Known Artist", "Known Track", "approved",
            approved,
        )
        cache.save()
        spotify = UnavailableApprovedSpotify({
            ("Known Artist", "Known Track"): _match(
                "spotify:track:replacement", "Known Track", "Known Artist",
            ),
        })

        report = Transfer(
            publishing_guards=TEST_PUBLISHING_GUARDS,
            source=FixtureBeatportSource(FIXTURE), spotify=spotify,
            matching_knowledge=MatchCacheKnowledge(cache),
        ).execute(TransferRequest(source="fixture", preview=True))

        assert [item.spotify_uri for item in report.playlists[0].unavailable_approved] == [
            "spotify:track:approved",
        ]
        assert ("Known Artist", "Known Track", 80) not in spotify.searches
        assert cache.lookup("Known Artist", "Known Track", 100).spotify_uri == (
            "spotify:track:approved"
        )
        approved_review = report.playlists[0].review_items[0]
        assert approved_review.match_type == "shorter_version"
        assert approved_review.score_reasons == (reason,)

    def test_missing_correction_is_added_once_across_repeated_approval(self, tmp_path):
        transfer, spotify, _, playlist_id = self.publish()
        spotify.playlists[playlist_id]["tracks"] = [
            "spotify:track:known", "spotify:track:manual",
        ]
        review_csv = tmp_path / "review.csv"
        review_csv.write_text(
            "source_track_id,spotify_url\n"
            "bp-2,spotify:track:abcdefghijklmnopqrstuv\n"
        )

        transfer.approve(playlist_id, corrections=review_csv)
        transfer.approve(playlist_id, corrections=review_csv)

        assert spotify.playlists[playlist_id]["tracks"] == [
            "spotify:track:known",
            "spotify:track:manual",
            "spotify:track:abcdefghijklmnopqrstuv",
        ]
        assert spotify.playlist_replacements == 1

    def test_ambiguous_source_reference_cannot_receive_a_correction(self, tmp_path):
        transfer, _, storage, playlist_id = self.publish()
        manifest = storage.publications[0]
        storage.publications[0] = type(manifest)(
            **{
                **manifest.__dict__,
                "items": (
                    manifest.items[0],
                    type(manifest.items[1])(
                        **{
                            **manifest.items[1].__dict__,
                            "source_track_id": manifest.items[0].source_track_id,
                        }
                    ),
                ),
            }
        )
        review_csv = tmp_path / "review.csv"
        review_csv.write_text(
            "source_track_id,spotify_url\n"
            "bp-1,spotify:track:abcdefghijklmnopqrstuv\n"
        )

        with pytest.raises(ValueError, match="not a unique stable source reference"):
            transfer.approve(playlist_id, corrections=review_csv)

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
    def test_recurring_mirror_marker_survives_adapter_reconstruction(self):
        client = MagicMock()
        playlists = []
        client.current_user.return_value = {"id": "spotify-user-1"}
        client.current_user_playlists.side_effect = lambda limit: {
            "items": list(playlists), "next": None,
        }

        def create_playlist(route, payload=None):
            assert route == "me/playlists"
            assert payload["public"] is False
            playlist = {"id": "mirror-1", "description": payload["description"]}
            playlists.append(playlist)
            return playlist

        client._post.side_effect = create_playlist

        first_id = SpotifyMatcher(client).publish_provisional_snapshot(
            "Fixture Mirror", ["spotify:track:first"], "description", "stable-key",
        )
        second_id = SpotifyMatcher(client).publish_provisional_snapshot(
            "Fixture Mirror", ["spotify:track:second"], "description", "stable-key",
        )

        assert first_id == second_id == "mirror-1"
        assert client._post.call_count == 1
        assert client.playlist_replace_items.call_args.args == (
            "mirror-1", ["spotify:track:second"],
        )

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
        assert request.mode == TransferMode.SNAPSHOT

    @patch("djsupport.transfer.Transfer.execute")
    @patch("djsupport.cli.get_client", return_value=MagicMock())
    def test_cli_beatport_can_explicitly_choose_mirror(
        self, mock_client, execute, tmp_path,
    ):
        execute.return_value = SyncReport(
            timestamp=datetime.now(), threshold=80, dry_run=False,
            playlists=[PlaylistReport(name="Fixture", path="fixture")],
            source_label="Beatport",
        )

        result = CliRunner().invoke(cli, [
            "beatport", "https://www.beatport.com/chart/fixture/14", "--mirror",
            "--state-path", str(tmp_path / "publications.json"),
        ])

        assert result.exit_code == 0, result.output
        assert execute.call_args.args[0].mode == TransferMode.MIRROR

    @patch("djsupport.transfer.Transfer.execute")
    @patch("djsupport.cli.get_client", return_value=MagicMock())
    def test_cli_label_defaults_to_snapshot_through_transfer(
        self, mock_client, execute, tmp_path,
    ):
        execute.return_value = SyncReport(
            timestamp=datetime.now(), threshold=80, dry_run=False,
            playlists=[PlaylistReport(name="Fixture Label", path="fixture")],
            source_label="Beatport label",
        )

        result = CliRunner().invoke(cli, [
            "label", "https://www.beatport.com/label/fixture/21",
            "--state-path", str(tmp_path / "publications.json"),
        ])

        assert result.exit_code == 0, result.output
        request = execute.call_args.args[0]
        assert request.source == "https://www.beatport.com/label/fixture/21"
        assert request.mode == TransferMode.SNAPSHOT

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
    @patch("djsupport.transfer.FileTransferStorage")
    @patch("djsupport.cli.get_client", return_value=MagicMock())
    def test_cli_approves_one_provisional_playlist(
        self, mock_client, transfer_storage, approve, tmp_path,
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
        transfer_storage.assert_called_once_with(
            str((tmp_path / "state.json").with_suffix(".transfers.json"))
        )
        assert "1 approved" in result.output
        assert "2 rejected" in result.output

    @patch("djsupport.transfer.Transfer.approve")
    @patch("djsupport.cli.get_client", return_value=MagicMock())
    def test_cli_applies_an_edited_review_csv(
        self, mock_client, approve, tmp_path,
    ):
        approve.return_value = ApprovalOutcome(
            account_id="spotify-user-1",
            spotify_playlist_id="snapshot-1",
            reviewed_at=datetime.now(),
            status=ApprovalStatus.APPROVED,
        )
        review_csv = tmp_path / "review.csv"
        review_csv.write_text("source_track_id,spotify_url\n")

        result = CliRunner().invoke(cli, [
            "approve", "snapshot-1", "--review-csv", str(review_csv),
            "--state-path", str(tmp_path / "state.json"),
        ])

        assert result.exit_code == 0, result.output
        approve.assert_called_once_with("snapshot-1", corrections=str(review_csv))


class TestRekordboxCliTransfer:
    @patch("djsupport.transfer.Transfer.execute_batch")
    @patch("djsupport.transfer.Transfer.plan_batch")
    @patch("djsupport.transfer.FileTransferStorage")
    @patch("djsupport.transfer.FilePublicationStorage")
    @patch("djsupport.cache.MatchCache")
    @patch("djsupport.cli.get_client", return_value=MagicMock())
    def test_cli_defaults_to_shared_application_data_storage(
        self, mock_client, match_cache, publication_storage, transfer_storage,
        plan_batch, execute_batch,
    ):
        from djsupport.cli import (
            DEFAULT_MATCHING_KNOWLEDGE_PATH,
            DEFAULT_PUBLICATION_MANIFEST_PATH,
        )

        plan_batch.return_value = BatchPlan(())
        execute_batch.return_value = SyncReport(
            timestamp=datetime.now(), threshold=80, dry_run=False,
            playlists=[], source_label="Rekordbox", status="completed",
        )

        result = CliRunner().invoke(cli, [
            "sync", str(REKORDBOX_FIXTURE), "--playlist", "Peak Time",
        ])

        assert result.exit_code == 0, result.output
        match_cache.assert_called_once_with(DEFAULT_MATCHING_KNOWLEDGE_PATH)
        publication_storage.assert_called_once_with(
            DEFAULT_PUBLICATION_MANIFEST_PATH
        )
        transfer_storage.assert_called_once_with(
            str(Path(DEFAULT_PUBLICATION_MANIFEST_PATH).with_suffix(
                ".transfers.json"
            ))
        )

    @patch("djsupport.transfer.Transfer.execute_batch")
    @patch("djsupport.transfer.Transfer.plan_batch")
    @patch("djsupport.cli.get_client", return_value=MagicMock())
    def test_cli_selected_playlist_enters_transfer_batch(
        self, mock_client, plan_batch, execute_batch, tmp_path,
    ):
        plan_batch.return_value = BatchPlan((), threshold=87)
        execute_batch.return_value = SyncReport(
            timestamp=datetime.now(), threshold=87, dry_run=False,
            playlists=[], source_label="Rekordbox", status="completed",
        )

        result = CliRunner().invoke(cli, [
            "sync", str(REKORDBOX_FIXTURE),
            "--playlist", "My Playlists/Peak Time", "--threshold", "87",
            "--state-path", str(tmp_path / "publications.json"),
            "--cache-path", str(tmp_path / "knowledge.json"),
        ])

        assert result.exit_code == 0, result.output
        request = plan_batch.call_args.args[0]
        assert request.playlist_references == ("My Playlists/Peak Time",)
        assert request.whole_library is False
        assert request.threshold == 87
        execute_batch.assert_called_once_with(plan_batch.return_value)

    @patch("djsupport.transfer.Transfer.execute_batch")
    @patch("djsupport.transfer.Transfer.plan_batch")
    @patch("djsupport.cli.get_client", return_value=MagicMock())
    def test_cli_preview_is_owned_by_transfer_batch(
        self, mock_client, plan_batch, execute_batch, tmp_path,
    ):
        plan_batch.return_value = BatchPlan((), preview=True)
        execute_batch.return_value = SyncReport(
            timestamp=datetime.now(), threshold=80, dry_run=True,
            playlists=[], source_label="Rekordbox", status="completed",
        )

        result = CliRunner().invoke(cli, [
            "sync", str(REKORDBOX_FIXTURE), "--playlist", "Peak Time",
            "--dry-run", "--state-path", str(tmp_path / "publications.json"),
            "--cache-path", str(tmp_path / "knowledge.json"),
        ])

        assert result.exit_code == 0, result.output
        assert plan_batch.call_args.args[0].preview is True

    def test_cli_requires_explicit_rekordbox_selection(self):
        result = CliRunner().invoke(cli, ["sync", str(REKORDBOX_FIXTURE)])

        assert result.exit_code != 0
        assert "select at least one playlist" in result.output.lower()
