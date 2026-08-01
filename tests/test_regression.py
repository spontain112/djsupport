"""Tests for local matcher regression knowledge."""

import json

import pytest

from djsupport.regression import load_local_regressions


class TestLoadLocalRegressions:
    def test_reads_only_local_regression_knowledge(self, tmp_path):
        path = tmp_path / "matching-knowledge.json"
        path.write_text(json.dumps({
            "version": 1,
            "entries": {
                "synthetic artist||cached proposal": {
                    "spotify_uri": "spotify:track:0000000000000000000000",
                    "spotify_name": "Cached Proposal",
                    "spotify_artist": "Synthetic Artist",
                    "score": 90,
                    "matched": True,
                    "timestamp": "2026-01-01T00:00:00",
                    "threshold": 80,
                },
            },
            "local_regressions": [{
                "source_track_id": "synthetic-1",
                "source_artist": "Synthetic Artist",
                "source_title": "Synthetic Track",
                "spotify_uri": "spotify:track:1111111111111111111111",
            }],
        }))

        assert load_local_regressions(path) == [{
            "artist": "Synthetic Artist",
            "song": "Synthetic Track",
            "expected_uri": "spotify:track:1111111111111111111111",
            "duration": 0,
        }]

    def test_rejects_invalid_local_regression_rows(self, tmp_path):
        path = tmp_path / "matching-knowledge.json"
        path.write_text(json.dumps({
            "version": 1,
            "entries": {},
            "local_regressions": [{
                "source_artist": "Incomplete",
                "source_title": "Missing URI",
            }],
        }))

        with pytest.raises(ValueError, match="local regression row 1"):
            load_local_regressions(path)
