"""Tests for djsupport.config — ConfigManager and validate_rekordbox_xml."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from djsupport.backup import default_app_data_path
from djsupport.cli import cli
from djsupport.config import ConfigManager, validate_rekordbox_xml, CONFIG_VERSION
from djsupport import paths


@pytest.fixture
def cfg(tmp_path):
    return ConfigManager(path=str(tmp_path / "config.json"))


class TestConfigManager:
    def test_default_path_is_private_platform_application_data(self):
        assert ConfigManager().path == default_app_data_path() / "config.json"

    @pytest.mark.parametrize(
        ("platform", "environment", "value", "fallback"),
        (
            ("linux", "XDG_DATA_HOME", "", Path(".local/share")),
            ("linux", "XDG_DATA_HOME", "relative-data", Path(".local/share")),
            ("win32", "LOCALAPPDATA", "", Path("AppData/Local")),
            ("win32", "LOCALAPPDATA", "relative-data", Path("AppData/Local")),
        ),
    )
    def test_empty_or_relative_platform_data_root_uses_absolute_fallback(
        self, monkeypatch, platform, environment, value, fallback,
    ):
        monkeypatch.setattr(paths.sys, "platform", platform)
        monkeypatch.setenv(environment, value)

        result = paths.default_app_data_path()

        assert result == Path.home() / fallback / "djsupport"
        assert result.is_absolute()

    def test_default_xml_path_is_none(self, cfg):
        assert cfg.get_rekordbox_xml_path() is None

    def test_set_and_get_path(self, cfg, tmp_path):
        target = str(tmp_path / "library.xml")
        cfg.set_rekordbox_xml_path(target)
        assert cfg.get_rekordbox_xml_path() == target

    def test_save_and_load_roundtrip(self, tmp_path):
        path = str(tmp_path / "config.json")
        lib = str(tmp_path / "lib.xml")

        c1 = ConfigManager(path=path)
        c1.set_rekordbox_xml_path(lib)
        c1.save()

        c2 = ConfigManager(path=path)
        c2.load()
        assert c2.get_rekordbox_xml_path() == lib

    def test_saved_file_has_correct_version(self, tmp_path):
        path = tmp_path / "config.json"
        c = ConfigManager(path=str(path))
        c.save()
        data = json.loads(path.read_text())
        assert data["version"] == CONFIG_VERSION

    def test_save_creates_the_private_application_data_directory(self, tmp_path):
        path = tmp_path / "missing" / "app-data" / "config.json"

        ConfigManager(path=path).save()

        assert json.loads(path.read_text()) == {
            "version": CONFIG_VERSION,
            "rekordbox_xml_path": None,
            "last_set_at": None,
        }

    def test_failed_save_leaves_existing_configuration_unchanged(
        self, tmp_path, monkeypatch,
    ):
        path = tmp_path / "config.json"
        manager = ConfigManager(path=path)
        manager.set_rekordbox_xml_path("/synthetic/current.xml")
        manager.save()
        before = path.read_bytes()
        manager.set_rekordbox_xml_path("/synthetic/replacement.xml")

        def fail_replace(source, target):
            raise OSError("synthetic replace failure")

        monkeypatch.setattr("djsupport.config.os.replace", fail_replace)

        with pytest.raises(OSError, match="synthetic replace failure"):
            manager.save()

        assert path.read_bytes() == before

    def test_load_nonexistent_file_is_noop(self, cfg):
        cfg.load()
        assert cfg.get_rekordbox_xml_path() is None

    def test_load_corrupt_json_is_noop(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text("}{not json")
        c = ConfigManager(path=str(p))
        c.load()
        assert c.get_rekordbox_xml_path() is None

    def test_load_wrong_version_is_noop(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"version": 999, "rekordbox_xml_path": "/some/path.xml"}))
        c = ConfigManager(path=str(p))
        c.load()
        assert c.get_rekordbox_xml_path() is None

    def test_set_path_expands_home_tilde(self, cfg):
        cfg.set_rekordbox_xml_path("~/music/library.xml")
        result = cfg.get_rekordbox_xml_path()
        assert not result.startswith("~")
        assert "music/library.xml" in result

    def test_set_path_records_timestamp(self, cfg, tmp_path):
        cfg.set_rekordbox_xml_path(str(tmp_path / "lib.xml"))
        assert cfg.config.last_set_at is not None

    def test_legacy_migration_previews_without_writing_canonical_config(
        self, tmp_path, monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        legacy = tmp_path / ".djsupport_config.json"
        legacy.write_text(json.dumps({
            "version": CONFIG_VERSION,
            "rekordbox_xml_path": "/synthetic/library.xml",
            "last_set_at": "2026-08-09T10:00:00",
        }))
        canonical = tmp_path / "app-data" / "config.json"

        result = ConfigManager(path=canonical).migrate_legacy()

        assert result.status == "ready"
        assert result.applied is False
        assert not canonical.exists()

    def test_legacy_migration_apply_copies_but_never_deletes_legacy_config(
        self, tmp_path, monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        legacy = tmp_path / ".djsupport_config.json"
        legacy_data = {
            "version": CONFIG_VERSION,
            "rekordbox_xml_path": "/synthetic/library.xml",
            "last_set_at": "2026-08-09T10:00:00",
        }
        legacy.write_text(json.dumps(legacy_data))
        before = legacy.read_bytes()
        canonical = tmp_path / "app-data" / "config.json"

        result = ConfigManager(path=canonical).migrate_legacy(apply=True)

        assert result.status == "migrated"
        assert result.applied is True
        assert json.loads(canonical.read_text()) == legacy_data
        assert legacy.read_bytes() == before

    def test_legacy_migration_rejects_a_link_outside_the_current_directory(
        self, tmp_path, monkeypatch,
    ):
        working = tmp_path / "working"
        working.mkdir()
        outside = tmp_path / "outside-config.json"
        outside.write_text(json.dumps({
            "version": CONFIG_VERSION,
            "rekordbox_xml_path": "/synthetic/library.xml",
            "last_set_at": None,
        }))
        (working / ".djsupport_config.json").symlink_to(outside)
        monkeypatch.chdir(working)
        canonical = tmp_path / "app-data" / "config.json"

        result = ConfigManager(path=canonical).migrate_legacy(apply=True)

        assert result.status == "invalid"
        assert result.applied is False
        assert not canonical.exists()

    @pytest.mark.parametrize(
        "legacy_data",
        (
            [],
            {"version": CONFIG_VERSION, "rekordbox_xml_path": 42},
            {"version": CONFIG_VERSION, "last_set_at": ["not", "text"]},
        ),
    )
    def test_legacy_migration_rejects_structurally_invalid_configuration(
        self, tmp_path, monkeypatch, legacy_data,
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".djsupport_config.json").write_text(
            json.dumps(legacy_data)
        )
        canonical = tmp_path / "app-data" / "config.json"

        result = ConfigManager(path=canonical).migrate_legacy(apply=True)

        assert result.status == "invalid"
        assert result.applied is False
        assert not canonical.exists()

    def test_legacy_migration_never_chooses_between_different_configs(
        self, tmp_path, monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        legacy = tmp_path / ".djsupport_config.json"
        canonical = tmp_path / "app-data" / "config.json"
        canonical.parent.mkdir()
        legacy.write_text(json.dumps({
            "version": CONFIG_VERSION,
            "rekordbox_xml_path": "/synthetic/legacy.xml",
            "last_set_at": None,
        }))
        canonical.write_text(json.dumps({
            "version": CONFIG_VERSION,
            "rekordbox_xml_path": "/synthetic/current.xml",
            "last_set_at": None,
        }))
        before = canonical.read_bytes()

        result = ConfigManager(path=canonical).migrate_legacy(apply=True)

        assert vars(result) == {"status": "conflict", "applied": False}
        assert canonical.read_bytes() == before


class TestConfigMigrationCli:
    def test_structurally_invalid_legacy_config_returns_safe_cli_error(
        self, tmp_path, monkeypatch,
    ):
        app_data = tmp_path / "app-data"
        monkeypatch.setattr(
            "djsupport.config.default_app_data_path", lambda: app_data,
        )
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path(".djsupport_config.json").write_text("[]")

            result = runner.invoke(
                cli, ["library", "migrate-config", "--apply"],
            )

        assert result.exit_code == 1
        assert "invalid and was not migrated" in result.output
        assert not (app_data / "config.json").exists()

    def test_preview_is_path_private_and_explains_explicit_apply(
        self, tmp_path, monkeypatch,
    ):
        app_data = tmp_path / "app-data"
        monkeypatch.setattr(
            "djsupport.config.default_app_data_path", lambda: app_data,
        )
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path(".djsupport_config.json").write_text(json.dumps({
                "version": CONFIG_VERSION,
                "rekordbox_xml_path": "/private/synthetic/library.xml",
                "last_set_at": None,
            }))

            result = runner.invoke(cli, ["library", "migrate-config"])

        assert result.exit_code == 0
        assert "ready to migrate" in result.output
        assert "--apply" in result.output
        assert "/private/synthetic/library.xml" not in result.output
        assert not (app_data / "config.json").exists()

    def test_apply_migrates_without_deleting_or_printing_the_legacy_path(
        self, tmp_path, monkeypatch,
    ):
        app_data = tmp_path / "app-data"
        monkeypatch.setattr(
            "djsupport.config.default_app_data_path", lambda: app_data,
        )
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            legacy = Path(".djsupport_config.json")
            legacy.write_text(json.dumps({
                "version": CONFIG_VERSION,
                "rekordbox_xml_path": "/private/synthetic/library.xml",
                "last_set_at": None,
            }))

            result = runner.invoke(
                cli, ["library", "migrate-config", "--apply"],
            )

            assert legacy.exists()
        assert result.exit_code == 0
        assert "migrated to private application data" in result.output
        assert "/private/synthetic/library.xml" not in result.output
        assert json.loads((app_data / "config.json").read_text())[
            "rekordbox_xml_path"
        ] == "/private/synthetic/library.xml"

    def test_conflict_stops_and_routes_to_explicit_library_set(
        self, tmp_path, monkeypatch,
    ):
        app_data = tmp_path / "app-data"
        app_data.mkdir()
        current = {
            "version": CONFIG_VERSION,
            "rekordbox_xml_path": "/private/synthetic/current.xml",
            "last_set_at": None,
        }
        (app_data / "config.json").write_text(json.dumps(current))
        monkeypatch.setattr(
            "djsupport.config.default_app_data_path", lambda: app_data,
        )
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path(".djsupport_config.json").write_text(json.dumps({
                "version": CONFIG_VERSION,
                "rekordbox_xml_path": "/private/synthetic/legacy.xml",
                "last_set_at": None,
            }))

            result = runner.invoke(
                cli, ["library", "migrate-config", "--apply"],
            )

        assert result.exit_code == 1
        assert "Choose explicitly" in result.output
        assert "/private/synthetic/" not in result.output
        assert json.loads((app_data / "config.json").read_text()) == current


class TestValidateRekordboxXml:
    def test_valid_rekordbox_xml(self, library_xml):
        ok, err = validate_rekordbox_xml(library_xml)
        assert ok is True
        assert err is None

    def test_missing_file(self):
        ok, err = validate_rekordbox_xml("/nonexistent/path/library.xml")
        assert ok is False
        assert err is not None
        assert "not found" in err.lower() or "no such" in err.lower()

    def test_path_is_a_directory(self, tmp_path):
        ok, err = validate_rekordbox_xml(tmp_path)
        assert ok is False
        assert err is not None

    def test_invalid_xml_content(self, tmp_path):
        p = tmp_path / "bad.xml"
        p.write_text("this is not xml at all {{{")
        ok, err = validate_rekordbox_xml(p)
        assert ok is False
        assert err is not None

    def test_xml_missing_rekordbox_nodes(self, tmp_path):
        p = tmp_path / "other.xml"
        p.write_text("<root><something_else/></root>")
        ok, err = validate_rekordbox_xml(p)
        assert ok is False
        assert "COLLECTION" in err or "PLAYLISTS" in err

    def test_xml_with_only_collection_is_valid(self, tmp_path):
        p = tmp_path / "partial.xml"
        p.write_text('<DJ_PLAYLISTS><COLLECTION Entries="0"/></DJ_PLAYLISTS>')
        ok, err = validate_rekordbox_xml(p)
        assert ok is True

    def test_xml_with_only_playlists_is_valid(self, tmp_path):
        p = tmp_path / "partial2.xml"
        p.write_text('<DJ_PLAYLISTS><PLAYLISTS><NODE Type="0" Name="ROOT"/></PLAYLISTS></DJ_PLAYLISTS>')
        ok, err = validate_rekordbox_xml(p)
        assert ok is True
