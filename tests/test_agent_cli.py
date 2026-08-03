"""Thin CLI mapping for the harness-neutral agent contract."""

import json

from click.testing import CliRunner

from djsupport.cli import cli


def test_capabilities_json_does_not_require_xml_or_spotify(monkeypatch):
    monkeypatch.setattr("djsupport.local_audio.shutil.which", lambda name: None)

    result = CliRunner().invoke(cli, ["capabilities", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "contract_version": 1,
        "phase": "capability",
        "status": "ready",
        "capabilities": {
            "local_audio_identity": {
                "available": False,
                "algorithm": "chromaprint",
                "algorithm_version": None,
                "reason": "binary_unavailable",
            },
        },
        "next_actions": ["plan"],
    }


def test_sync_json_requires_explicit_private_source_authorization(monkeypatch):
    monkeypatch.setattr(
        "djsupport.cli.get_client",
        lambda: (_ for _ in ()).throw(AssertionError("Spotify must stay untouched")),
    )

    result = CliRunner().invoke(cli, [
        "sync",
        "tests/fixtures/library.xml",
        "--playlist", "My Playlists/Peak Time",
        "--dry-run",
        "--json",
    ])

    assert result.exit_code == 2
    assert json.loads(result.output) == {
        "contract_version": 1,
        "phase": "plan",
        "status": "authorization_required",
        "required_authorizations": ["private_source"],
        "next_actions": ["authorize_private_source"],
    }


def test_authorized_publish_returns_bounded_plan_before_spotify_write_authority(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(
        "djsupport.cli.get_client",
        lambda: (_ for _ in ()).throw(AssertionError("Spotify must stay untouched")),
    )

    result = CliRunner().invoke(cli, [
        "sync", "tests/fixtures/library.xml",
        "--playlist", "My Playlists/Peak Time",
        "--json", "--authorize-private-source",
        "--cache-path", str(tmp_path / "knowledge.json"),
        "--state-path", str(tmp_path / "publications.json"),
    ])

    assert result.exit_code == 2
    plan = json.loads(result.output)
    assert plan["phase"] == "plan"
    assert plan["status"] == "ready"
    assert plan["required_authorizations"] == ["spotify_write"]
    assert len(plan["batch_id"]) == 64


def test_json_source_error_is_structured_and_does_not_echo_private_path(tmp_path):
    private_path = tmp_path / "private-library-name.xml"

    result = CliRunner().invoke(cli, [
        "sync", str(private_path), "--playlist", "Selected",
        "--dry-run", "--json", "--authorize-private-source",
    ])

    assert result.exit_code == 2
    assert json.loads(result.output) == {
        "contract_version": 1,
        "phase": "plan",
        "status": "error",
        "error": {"code": "private_source_unavailable"},
        "next_actions": ["inspect_private_source"],
    }
    assert "private-library-name" not in result.output


def test_authorized_sync_json_returns_only_structured_outcome(
    monkeypatch, tmp_path,
):
    class Spotify:
        def account_id(self):
            return "spotify-account-one"

        def match(self, track, threshold):
            return {
                "uri": f"spotify:track:{track.track_id}",
                "name": "Synthetic Result",
                "artist": "Synthetic Artist",
                "score": 95.0,
                "match_type": "exact",
            }

    spotify = Spotify()
    monkeypatch.setattr("djsupport.cli.get_client", lambda: object())
    monkeypatch.setattr(
        "djsupport.transfer.SpotifyMatcher", lambda client: spotify,
    )

    result = CliRunner().invoke(cli, [
        "sync",
        "tests/fixtures/library.xml",
        "--playlist", "My Playlists/Peak Time",
        "--dry-run",
        "--json",
        "--authorize-private-source",
        "--cache-path", str(tmp_path / "knowledge.json"),
        "--state-path", str(tmp_path / "publications.json"),
    ])

    assert result.exit_code == 0, result.output
    outcome = json.loads(result.output)
    assert outcome["contract_version"] == 1
    assert outcome["phase"] == "outcome"
    assert outcome["status"] == "completed"
    assert outcome["counts"] == {
        "playlists": 1,
        "matched": 2,
        "unmatched": 0,
        "spotify_api_lookups": 2,
        "local_audio_eligible": 0,
        "local_audio_observed": 0,
        "local_audio_unavailable": 0,
        "local_audio_reused": 0,
    }
    assert "My Playlists" not in result.output
    assert "Solomun" not in result.output
