"""Thin CLI mapping for the harness-neutral agent contract."""

import json
from unittest.mock import MagicMock

from click.testing import CliRunner

from djsupport.cli import cli


def test_first_transfer_json_renders_one_input_required_action(monkeypatch):
    transfer = MagicMock()
    monkeypatch.setattr(
        "djsupport.cli._first_transfer_readiness",
        lambda xml_path: (False, False, False, False, None),
    )
    monkeypatch.setattr(
        "djsupport.cli._first_transfer_contract",
        lambda **kwargs: __import__(
            "djsupport.agent", fromlist=["AgentTransferContract"]
        ).AgentTransferContract(transfer),
    )

    result = CliRunner().invoke(cli, ["first-transfer", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "contract_version": 2,
        "phase": "first_rekordbox_transfer",
        "status": "input_required",
        "next_action": "configure_spotify",
        "required_input": {
            "kind": "spotify_configuration",
            "redirect_uri": "http://127.0.0.1:8888/callback",
            "callback_policy": "add_without_replacing_existing",
        },
    }
    transfer.assert_not_called()


def test_first_transfer_cli_maps_explicit_inputs_to_public_contract(monkeypatch):
    contract = MagicMock()
    contract.first_rekordbox_transfer.return_value = {
        "contract_version": 2,
        "phase": "first_rekordbox_transfer",
        "status": "ready",
        "next_action": "preview",
        "required_input": {
            "kind": "action_confirmation", "action": "preview",
        },
    }
    monkeypatch.setattr(
        "djsupport.cli._first_transfer_readiness",
        lambda xml_path: (True, True, True, True, "/private/library.xml"),
    )
    monkeypatch.setattr(
        "djsupport.cli._first_transfer_contract",
        lambda **kwargs: contract,
    )

    result = CliRunner().invoke(cli, [
        "first-transfer", "--playlist", "Private/Selection",
        "--no-local-audio-identity", "--authorize-private-source", "--json",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["next_action"] == "preview"
    request, authorization = contract.first_rekordbox_transfer.call_args.args
    assert request.playlist_reference == "Private/Selection"
    assert request.local_audio_identity is False
    assert request.spotify_configured is True
    assert request.spotify_authenticated is True
    assert authorization.private_source is True
    assert authorization.spotify_write is False


def test_first_transfer_json_never_prompts_and_input_required_is_success(
    monkeypatch,
):
    monkeypatch.setattr(
        "djsupport.cli._first_transfer_readiness",
        lambda xml_path: (True, True, True, True, "/private/library.xml"),
    )
    contract = MagicMock()
    contract.first_rekordbox_transfer.return_value = {
        "contract_version": 2,
        "phase": "first_rekordbox_transfer",
        "status": "decision_required",
        "next_action": "choose_local_audio_identity",
        "required_input": {"kind": "boolean", "default": False},
    }
    monkeypatch.setattr(
        "djsupport.cli._first_transfer_contract", lambda **kwargs: contract,
    )

    result = CliRunner().invoke(cli, [
        "first-transfer", "--playlist", "Private/Selection", "--json",
    ], input="this must never be consumed\n")

    assert result.exit_code == 0
    assert "[y/N]" not in result.output
    assert json.loads(result.output)["status"] == "decision_required"


def test_capabilities_json_does_not_require_xml_or_spotify(monkeypatch):
    monkeypatch.setattr("djsupport.local_audio.shutil.which", lambda name: None)

    result = CliRunner().invoke(cli, ["capabilities", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "contract_version": 2,
        "phase": "capability",
        "status": "ready",
        "capabilities": {
            "local_audio_identity": {
                "available": False,
                "algorithm": "chromaprint",
                "algorithm_version": None,
                "reason": "binary_unavailable",
                "default_enabled": False,
                "authority": "approved_match_reuse_only",
                "first_run_discovery": "none_until_explicit_approval",
                "execution_order": "after_retained_knowledge_before_spotify_search",
            },
            "local_audio_audition": {
                "available": True,
                "default_enabled": False,
                "authority": "none",
                "requires_local_audio_identity": False,
                "requires_durable_matching_knowledge": False,
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
        "contract_version": 2,
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
        "contract_version": 2,
        "phase": "plan",
        "status": "error",
        "error": {"code": "private_source_unavailable"},
        "next_actions": ["inspect_private_source"],
    }
    assert "private-library-name" not in result.output


def test_json_directory_source_error_cannot_bypass_the_redacted_contract(tmp_path):
    private_directory = tmp_path / "private-library-directory"
    private_directory.mkdir()

    result = CliRunner().invoke(cli, [
        "sync", str(private_directory), "--playlist", "Selected",
        "--dry-run", "--json", "--authorize-private-source",
    ])

    assert result.exit_code == 2
    assert json.loads(result.output)["error"]["code"] == (
        "private_source_unavailable"
    )
    assert "private-library-directory" not in result.output


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
    assert outcome["contract_version"] == 2
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


def test_audition_intent_is_independent_and_compatible_with_no_cache(
    monkeypatch, tmp_path,
):
    class Spotify:
        def account_id(self):
            return "spotify-account-one"

        def match(self, track, threshold):
            return {
                "uri": f"spotify:track:{track.track_id}",
                "name": "Synthetic Result", "artist": "Synthetic Artist",
                "score": 95.0, "match_type": "exact",
            }

    monkeypatch.setattr("djsupport.cli.get_client", lambda: object())
    monkeypatch.setattr(
        "djsupport.transfer.SpotifyMatcher", lambda client: Spotify(),
    )

    result = CliRunner().invoke(cli, [
        "sync", "tests/fixtures/library.xml",
        "--playlist", "My Playlists/Peak Time",
        "--json", "--authorize-private-source",
        "--local-audio-audition", "--no-cache",
        "--state-path", str(tmp_path / "publications.json"),
    ])

    assert result.exit_code == 2, result.output
    document = json.loads(result.output)
    assert document["requested_effects"] == [
        "private_source", "local_audio_audition", "spotify_write",
    ]
    assert document["local_audio"]["identity_requested"] is False
    assert document["local_audio"]["audition_requested"] is True


def test_human_audition_intent_requires_private_source_authorization_before_intake(
    monkeypatch,
):
    monkeypatch.setattr(
        "djsupport.cli._resolve_xml_path",
        lambda path: (_ for _ in ()).throw(
            AssertionError("private source intake must stay untouched")
        ),
    )

    result = CliRunner().invoke(cli, [
        "sync", "tests/fixtures/library.xml",
        "--playlist", "My Playlists/Peak Time",
        "--local-audio-audition",
    ])

    assert result.exit_code == 2
    assert "--authorize-private-source" in result.output


def test_qualification_cli_denies_private_intake_through_versioned_contract(
    tmp_path,
):
    private_path = tmp_path / "owner-library-name.xml"

    result = CliRunner().invoke(cli, [
        "qualification", "batch-opaque-1", str(private_path),
        "--playlist", "Private/Selection", "--json",
    ])

    assert result.exit_code == 2
    assert json.loads(result.output) == {
        "contract_version": 2,
        "phase": "qualification",
        "status": "authorization_required",
        "required_authorizations": ["private_source"],
        "next_actions": ["authorize_private_source"],
    }
    assert "owner-library-name" not in result.output


def test_authorized_qualification_source_error_stays_structured_and_redacted(
    monkeypatch, tmp_path,
):
    private_path = tmp_path / "owner-library-name.xml"
    monkeypatch.setattr(
        "djsupport.cli.get_client",
        lambda: (_ for _ in ()).throw(
            AssertionError("Spotify must stay untouched")
        ),
    )

    result = CliRunner().invoke(cli, [
        "qualification", "batch-opaque-1", str(private_path),
        "--playlist", "Private/Selection", "--json",
        "--authorize-private-source",
        "--state-path", str(tmp_path / "publications.json"),
    ])

    assert result.exit_code == 2
    assert json.loads(result.output) == {
        "contract_version": 2,
        "phase": "qualification",
        "status": "error",
        "error": {"code": "private_source_unavailable"},
        "next_actions": ["inspect_private_source"],
    }
    assert "owner-library-name" not in result.output


def test_qualification_cli_exposes_explicit_draft_and_apply_operations():
    result = CliRunner().invoke(cli, ["qualification", "--help"])

    assert result.exit_code == 0
    assert "--item-id" in result.output
    assert "--decision" in result.output
    assert "--apply" in result.output
    assert "--authorize-private-source" in result.output
    assert "--authorize-spotify-write" in result.output
