"""Behavior tests at the public Transfer seam."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from djsupport.cli import cli
from djsupport.rekordbox import Track
from djsupport.report import PlaylistReport, SyncReport
from djsupport.transfer import SourceSelection, Transfer, TransferRequest


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
    assert storage.checkpoints == 1
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
    assert storage.checkpoints == 1
    assert spotify.playlists == {"existing": ["spotify:track:untouched"]}


@patch("djsupport.transfer.Transfer.execute")
@patch("djsupport.cli.get_client", return_value=MagicMock())
def test_cli_beatport_dry_run_enters_transfer_interface(mock_client, execute):
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
