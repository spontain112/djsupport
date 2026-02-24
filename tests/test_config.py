"""Tests for djsupport.config — ConfigManager and validate_rekordbox_xml."""

import json
from pathlib import Path

import pytest

from djsupport.config import ConfigManager, validate_rekordbox_xml, CONFIG_VERSION


@pytest.fixture
def cfg(tmp_path):
    return ConfigManager(path=str(tmp_path / "config.json"))


class TestConfigManager:
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
