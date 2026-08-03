"""Public-seam tests for explicit 0.3.0 local-data migration."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from djsupport.backup import LocalDataBackup
from djsupport.cli import cli
from djsupport.migration import FoundationMigration, LegacyMigration


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def _cache_entry(uri_letter="A"):
    return {
        "spotify_uri": "spotify:track:" + uri_letter * 22,
        "spotify_name": "Synthetic result",
        "spotify_artist": "Synthetic artist",
        "score": 91.0,
        "matched": True,
        "timestamp": "2026-01-01T00:00:00",
        "threshold": 80,
        "match_type": "exact",
    }


class TestLegacyMigration:
    def test_migrate_legacy_directory_previews_without_mutation(
        self, tmp_path, monkeypatch,
    ):
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        _write_json(legacy / ".djsupport_cache.json", {
            "version": 1,
            "entries": {
                "synthetic artist||synthetic title": _cache_entry(),
            },
        })
        app_data = tmp_path / "app-data"
        monkeypatch.setattr("djsupport.backup.default_app_data_path", lambda: app_data)

        result = CliRunner().invoke(cli, ["migrate-0-3", str(legacy)])

        assert result.exit_code == 0
        assert "Preview only" in result.output
        assert "Detected files: 1" in result.output
        assert "Cache records: 1" in result.output
        assert "Proposed cache imports: 1" in result.output
        assert not app_data.exists()
        assert (legacy / ".djsupport_cache.json").exists()


    def test_preview_ignores_unknown_files_and_reports_absent_known_files(self, tmp_path):
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        (legacy / ".env").write_text("SPOTIPY_CLIENT_SECRET=synthetic-secret")
        (legacy / "report.md").write_text("/private/synthetic/path")

        report = LegacyMigration(tmp_path / "app-data").preview(legacy)

        assert report.valid
        assert report.detected_files == 0
        assert report.skipped == 0

    def test_unavailable_directory_error_does_not_echo_private_path(self, tmp_path):
        private_path = tmp_path / "private" / "missing"

        result = CliRunner().invoke(cli, ["migrate-0-3", str(private_path)])

        assert result.exit_code != 0
        assert "Selected legacy directory is unavailable" in result.output
        assert str(private_path) not in result.output


    @pytest.mark.parametrize("payload", [
        "not json",
        json.dumps({"version": 99, "entries": {}}),
        json.dumps({"version": 1, "entries": []}),
        json.dumps({
            "version": 1,
            "entries": {"synthetic": {
                **_cache_entry(), "spotify_uri": "not-a-spotify-track-uri",
            }},
        }),
        json.dumps({
            "version": 1,
            "entries": {"synthetic": {
                **_cache_entry(), "threshold": True,
                "match_type": "unknown",
            }},
        }),
    ])
    def test_preview_safely_rejects_malformed_or_unsupported_known_file(
        self,
        tmp_path, payload,
    ):
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        (legacy / ".djsupport_cache.json").write_text(payload)

        report = LegacyMigration(tmp_path / "app-data").preview(legacy)

        assert not report.valid
        assert report.errors == (".djsupport_cache.json: malformed or unsupported",)
        assert "/" not in report.errors[0]


    def test_apply_imports_both_caches_as_non_authoritative_and_current_wins(self, tmp_path):
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        _write_json(legacy / ".djsupport_cache.json", {
            "version": 1,
            "entries": {
                "new||track": _cache_entry("A"),
                "conflict||track": _cache_entry("B"),
            },
        })
        _write_json(legacy / ".djsupport_beatport_cache.json", {
            "version": 1, "entries": {"beatport||track": _cache_entry("C")},
        })
        app_data = tmp_path / "app-data"
        _write_json(app_data / "matching-knowledge.json", {
            "version": 1,
            "entries": {"conflict||track": {
                **_cache_entry("D"), "approval_status": "approved",
                "source_duration": 0,
            }},
            "local_regressions": [], "approval_conflicts": [],
        })

        result = LegacyMigration(app_data).apply(legacy)

        assert result.applied
        stored = json.loads((app_data / "matching-knowledge.json").read_text())
        assert stored["entries"]["conflict||track"]["spotify_uri"].endswith("D" * 22)
        assert stored["entries"]["new||track"]["approval_status"] is None
        assert stored["entries"]["beatport||track"]["approval_status"] is None
        assert result.report.proposed_cache_imports == 2
        assert result.report.conflicts == 1
        assert any((app_data / "backups").glob("djsupport-backup-*.zip"))

    def test_apply_preserves_version_two_local_audio_identity_knowledge(
        self, tmp_path,
    ):
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        _write_json(legacy / ".djsupport_cache.json", {
            "version": 1,
            "entries": {"new||track": _cache_entry("A")},
        })
        app_data = tmp_path / "app-data"
        association = {
            "algorithm": "chromaprint",
            "algorithm_version": "1.6.1",
            "fingerprint": "invented-private-evidence",
            "account_id": "spotify-account-one",
            "spotify_uri": "spotify:track:" + "B" * 22,
            "authority_status": "approved",
        }
        _write_json(app_data / "matching-knowledge.json", {
            "version": 2,
            "entries": {},
            "local_regressions": [],
            "approval_conflicts": [],
            "fingerprint_observations": {},
            "fingerprint_associations": [association],
        })

        result = LegacyMigration(app_data).apply(legacy)

        assert result.applied is True
        stored = json.loads((app_data / "matching-knowledge.json").read_text())
        assert stored["version"] == 2
        assert stored["fingerprint_associations"] == [association]
        assert "new||track" in stored["entries"]


    def test_ambiguous_cross_cache_entry_is_reported_and_not_imported(self, tmp_path):
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        _write_json(legacy / ".djsupport_cache.json", {
            "version": 1, "entries": {"ambiguous||track": _cache_entry("A")},
        })
        _write_json(legacy / ".djsupport_beatport_cache.json", {
            "version": 1, "entries": {"ambiguous||track": _cache_entry("B")},
        })

        result = LegacyMigration(tmp_path / "app-data").apply(legacy)

        stored = json.loads(
            (tmp_path / "app-data" / "matching-knowledge.json").read_text()
        )
        assert result.report.conflicts == 1
        assert result.report.skipped == 1
        assert "ambiguous||track" not in stored["entries"]


    def test_state_becomes_unmanaged_history_or_relink_candidate_without_guessing(self, tmp_path):
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        state = {
            "version": 2,
            "entries": {
                "Synthetic list": {
                    "spotify_id": "playlist-synthetic",
                    "spotify_name": "Synthetic list",
                    "source_path": "Synthetic/Source",
                    "last_synced": "2026-01-01T00:00:00",
                    "prefix_used": "djsupport",
                    "source_type": "rekordbox",
                },
            },
        }
        _write_json(legacy / ".djsupport_playlists.json", state)
        state["entries"]["Synthetic list"]["source_type"] = "beatport"
        _write_json(legacy / ".djsupport_beatport_playlists.json", state)

        result = LegacyMigration(tmp_path / "app-data").apply(legacy)

        records = json.loads(
            (tmp_path / "app-data" / "legacy-migration.json").read_text()
        )
        assert result.report.relink_required == 1
        assert result.report.historical_snapshots == 1
        assert records["relink_candidates"][0]["account_id"] is None
        assert records["relink_candidates"][0]["status"] == "relink_required"
        assert records["historical_snapshots"][0]["managed"] is False
        assert "mirrors" not in records


    def test_relink_candidate_uses_only_one_exact_current_account_match(self, tmp_path):
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        _write_json(legacy / ".djsupport_playlists.json", {
            "version": 2,
            "entries": {"Synthetic": {
                "spotify_id": "playlist-synthetic",
                "spotify_name": "A renamed destination",
                "source_path": "Synthetic/Exact Reference",
                "last_synced": "2026-01-01T00:00:00",
                "prefix_used": None,
                "source_type": "rekordbox",
            }},
        })
        app_data = tmp_path / "app-data"
        _write_json(app_data / "publication-manifests.json", {
            "version": 4,
            "manifests": [{
                "account_id": "account-synthetic",
                "spotify_playlist_id": "playlist-synthetic",
                "source_reference": "Synthetic/Exact Reference",
            }],
            "approvals": [], "mirrors": [],
        })

        result = LegacyMigration(app_data).apply(legacy)

        records = json.loads((app_data / "legacy-migration.json").read_text())
        assert result.applied
        assert records["relink_candidates"][0]["account_id"] == "account-synthetic"

    def test_ambiguous_exact_accounts_remain_unresolved(self, tmp_path):
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        state = {
            "spotify_id": "playlist-synthetic",
            "spotify_name": "Synthetic",
            "source_path": "Synthetic/Exact Reference",
            "last_synced": "2026-01-01T00:00:00",
            "prefix_used": None,
            "source_type": "rekordbox",
        }
        _write_json(legacy / ".djsupport_playlists.json", {
            "version": 2, "entries": {"Synthetic": state},
        })
        app_data = tmp_path / "app-data"
        _write_json(app_data / "publication-manifests.json", {
            "version": 4,
            "manifests": [
                {
                    "account_id": account,
                    "spotify_playlist_id": state["spotify_id"],
                    "source_reference": state["source_path"],
                }
                for account in ("account-one", "account-two")
            ],
            "approvals": [], "mirrors": [],
        })

        result = LegacyMigration(app_data).apply(legacy)

        records = json.loads((app_data / "legacy-migration.json").read_text())
        assert result.report.conflicts == 1
        assert records["relink_candidates"][0]["account_id"] is None


    @pytest.mark.parametrize("filename,source_type", [
        (".djsupport_playlists.json", "beatport"),
        (".djsupport_beatport_playlists.json", "rekordbox"),
    ])
    def test_mismatched_state_ownership_is_reported_without_guessing(
        self,
        tmp_path, filename, source_type,
    ):
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        _write_json(legacy / filename, {
            "version": 2,
            "entries": {"Synthetic": {
                "spotify_id": "playlist-synthetic",
                "spotify_name": "Synthetic",
                "source_path": "Synthetic/Source",
                "last_synced": "2026-01-01T00:00:00",
                "prefix_used": None,
                "source_type": source_type,
            }},
        })

        report = LegacyMigration(tmp_path / "app-data").preview(legacy)

        assert not report.valid
        assert report.relink_required == 0
        assert report.historical_snapshots == 0

    def test_malformed_state_prefix_is_not_converted(self, tmp_path):
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        _write_json(legacy / ".djsupport_playlists.json", {
            "version": 2,
            "entries": {"Synthetic": {
                "spotify_id": "playlist-synthetic",
                "spotify_name": "Synthetic",
                "source_path": "Synthetic/Source",
                "last_synced": "2026-01-01T00:00:00",
                "prefix_used": ["not", "a", "string"],
                "source_type": "rekordbox",
            }},
        })

        report = LegacyMigration(tmp_path / "app-data").preview(legacy)

        assert not report.valid
        assert report.relink_required == 0


    def test_apply_is_idempotent_and_leaves_legacy_files_byte_identical(self, tmp_path):
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        path = legacy / ".djsupport_cache.json"
        _write_json(path, {"version": 1, "entries": {"new||track": _cache_entry()}})
        original = path.read_bytes()
        migration = LegacyMigration(tmp_path / "app-data")

        first = migration.apply(legacy)
        first_data = (tmp_path / "app-data" / "matching-knowledge.json").read_bytes()
        second = migration.apply(legacy)

        assert first.applied and second.applied
        assert second.report.proposed_cache_imports == 0
        assert (tmp_path / "app-data" / "matching-knowledge.json").read_bytes() == first_data
        assert path.read_bytes() == original


    def test_cli_apply_reports_only_aggregates_and_never_initializes_spotify(
        self,
        tmp_path, monkeypatch,
    ):
        legacy = tmp_path / "private" / "legacy"
        legacy.mkdir(parents=True)
        private_metadata = "Never Print This Synthetic Track"
        _write_json(legacy / ".djsupport_cache.json", {
            "version": 1,
            "entries": {private_metadata: _cache_entry()},
        })
        app_data = tmp_path / "app-data"
        monkeypatch.setattr("djsupport.backup.default_app_data_path", lambda: app_data)
        monkeypatch.setattr(
            "djsupport.spotify.get_client",
            lambda: (_ for _ in ()).throw(AssertionError("Spotify must not be called")),
        )

        result = CliRunner().invoke(
            cli, ["migrate-0-3", str(legacy), "--apply"],
        )

        assert result.exit_code == 0
        assert "Migration completed" in result.output
        assert private_metadata not in result.output
        assert str(legacy) not in result.output
        assert "spotify:track:" not in result.output


    def test_backup_failure_and_commit_failure_leave_current_data_unchanged(
        self,
        tmp_path, monkeypatch,
    ):
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        _write_json(legacy / ".djsupport_cache.json", {
            "version": 1, "entries": {"new||track": _cache_entry()},
        })
        _write_json(legacy / ".djsupport_playlists.json", {
            "version": 2,
            "entries": {"Synthetic": {
                "spotify_id": "playlist-synthetic",
                "spotify_name": "Synthetic",
                "source_path": "Synthetic/Source",
                "last_synced": "2026-01-01T00:00:00",
                "prefix_used": None,
                "source_type": "rekordbox",
            }},
        })
        app_data = tmp_path / "app-data"
        current = {
            "version": 1, "entries": {}, "local_regressions": [],
            "approval_conflicts": [],
        }
        _write_json(app_data / "matching-knowledge.json", current)
        before = (app_data / "matching-knowledge.json").read_bytes()
        def fail_backup(*args, **kwargs):
            raise OSError("synthetic backup failure")

        monkeypatch.setattr(LocalDataBackup, "create", fail_backup)

        failed_backup = LegacyMigration(app_data).apply(legacy)

        assert not failed_backup.applied
        assert (app_data / "matching-knowledge.json").read_bytes() == before

        monkeypatch.undo()
        calls = 0

        def fail_second_replace(source: Path, target: Path):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic commit failure")
            source.replace(target)

        failed_commit = LegacyMigration(
            app_data, replace_file=fail_second_replace,
        ).apply(legacy)

        assert not failed_commit.applied
        assert (app_data / "matching-knowledge.json").read_bytes() == before
        assert list((app_data / "backups").glob("*.zip")) == []

        retry = LegacyMigration(app_data).apply(legacy)
        assert retry.applied


    def test_apply_verifies_backup_containing_current_publication_schema_v4(self, tmp_path):
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        _write_json(legacy / ".djsupport_cache.json", {
            "version": 1, "entries": {"new||track": _cache_entry()},
        })
        app_data = tmp_path / "app-data"
        _write_json(app_data / "publication-manifests.json", {
            "version": 4, "manifests": [], "approvals": [], "mirrors": [],
        })

        result = LegacyMigration(app_data).apply(legacy)

        assert result.applied
        archive = next((app_data / "backups").glob("*.zip"))
        assert LocalDataBackup(app_data).preview(archive).valid


def test_foundation_migration_is_backup_first_and_idempotent(tmp_path):
    app_data = tmp_path / "app-data"
    _write_json(app_data / "publication-manifests.json", {
        "version": 4,
        "manifests": [{"account_id": "legacy-profile", "spotify_playlist_id": "p"}],
        "approvals": [],
        "mirrors": [{"spotify_user_id": "legacy-profile"}],
    })

    migration = FoundationMigration(app_data)
    first = migration.apply("legacy-profile", "stable-account")
    second = migration.apply("legacy-profile", "stable-account")

    stored = json.loads((app_data / "publication-manifests.json").read_text())
    assert first.applied and first.backup_created and first.changed_records == 2
    assert not second.applied and not second.backup_created
    assert stored["manifests"][0]["account_id"] == "stable-account"
    assert stored["mirrors"][0]["account_id"] == "stable-account"
    archive = next((app_data / "backups").glob("*.zip"))
    assert LocalDataBackup(app_data).preview(archive).valid


def test_foundation_migration_stops_on_account_conflict_before_backup(tmp_path):
    app_data = tmp_path / "app-data"
    _write_json(app_data / "publication-manifests.json", {
        "version": 4,
        "manifests": [{"account_id": "another-account"}],
        "approvals": [], "mirrors": [],
    })

    with pytest.raises(ValueError, match="ownership conflicts"):
        FoundationMigration(app_data).apply("legacy-profile", "stable-account")

    assert not (app_data / "backups").exists()


def test_foundation_migration_preserves_conflicting_legacy_ownership(tmp_path):
    app_data = tmp_path / "app-data"
    original = {
        "version": 4,
        "manifests": [{"spotify_user_id": "another-account"}],
        "approvals": [], "mirrors": [],
    }
    _write_json(app_data / "publication-manifests.json", original)

    with pytest.raises(ValueError, match="Legacy account ownership conflicts"):
        FoundationMigration(app_data).apply("legacy-profile", "stable-account")

    assert json.loads(
        (app_data / "publication-manifests.json").read_text()
    ) == original
