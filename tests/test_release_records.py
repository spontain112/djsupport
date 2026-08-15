"""Tests for the Python-native release-record binding."""

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "release_records", ROOT / "scripts" / "release_records.py"
)
release_records = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release_records
SPEC.loader.exec_module(release_records)


def test_distributable_paths_exclude_internal_research_only():
    distributable = (
        "djsupport/transfer.py",
        "README.md",
        "pyproject.toml",
        "docs/architecture.md",
        "docs/storage.md",
        "docs/backup-and-restore.md",
    )
    internal = (
        "docs/releasing.md",
        "docs/research/operational-store-contract.md",
        "tests/test_transfer.py",
        ".github/workflows/ci.yml",
    )

    assert all(release_records._is_distributable(path) for path in distributable)
    assert not any(release_records._is_distributable(path) for path in internal)


def test_release_record_parser_requires_bump_section_and_summary(tmp_path):
    record = tmp_path / "change.md"
    record.write_text(
        "---\nbump: minor\nsection: Added\n---\n\nAdd a bounded public workflow.\n",
        encoding="utf-8",
    )

    parsed = release_records._parse_record(record)

    assert parsed.bump == "minor"
    assert parsed.section == "Added"
    assert parsed.summary == "Add a bounded public workflow."


def test_development_version_finalizes_before_later_bumps(tmp_path, monkeypatch):
    records_dir = tmp_path / ".release-notes"
    records_dir.mkdir()
    (records_dir / "change.md").write_text(
        "---\nbump: minor\nsection: Added\n---\n\nAdd a public workflow.\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "djsupport"\nversion = "0.6.0.dev0"\n', encoding="utf-8"
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- Legacy fix.\n\n## [0.5.0] - 2026-08-02\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(release_records, "ROOT", tmp_path)
    monkeypatch.setattr(release_records, "RECORDS", records_dir)
    monkeypatch.setattr(release_records, "NEXT_VERSION", records_dir / "next-version")

    version = release_records.prepare("2026-08-15")

    assert version == "0.6.0"
    assert 'version = "0.6.0"' in (tmp_path / "pyproject.toml").read_text()
    changelog = (tmp_path / "CHANGELOG.md").read_text()
    assert "## [0.6.0] - 2026-08-15" in changelog
    assert "- Legacy fix." in changelog
    assert "- Add a public workflow." in changelog
    assert not (records_dir / "change.md").exists()


def test_stable_version_uses_highest_pending_bump():
    records = [
        release_records.ReleaseRecord(Path("fix.md"), "patch", "Fixed", "Fix it."),
        release_records.ReleaseRecord(Path("feature.md"), "minor", "Added", "Add it."),
    ]

    assert release_records._next_version("0.6.0", records) == "0.7.0"


def test_release_candidate_advances_unless_next_version_overrides_it():
    records = [
        release_records.ReleaseRecord(Path("fix.md"), "patch", "Fixed", "Fix it.")
    ]

    assert release_records._next_version("0.6.0rc1", records) == "0.6.0rc2"


def test_next_version_override_is_applied_once(tmp_path, monkeypatch):
    records_dir = tmp_path / ".release-notes"
    records_dir.mkdir()
    record = records_dir / "change.md"
    record.write_text(
        "---\nbump: minor\nsection: Added\n---\n\nAdd a public workflow.\n",
        encoding="utf-8",
    )
    next_version = records_dir / "next-version"
    next_version.write_text("0.6.0\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "djsupport"\nversion = "0.6.0.dev0"\n',
        encoding="utf-8",
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [0.5.0] - 2026-08-02\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(release_records, "ROOT", tmp_path)
    monkeypatch.setattr(release_records, "RECORDS", records_dir)
    monkeypatch.setattr(release_records, "NEXT_VERSION", next_version)

    version = release_records.prepare("2026-08-15")

    assert version == "0.6.0"
    changelog = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.6.0] - 2026-08-15\n\n### Added" in changelog
    assert "- Add a public workflow.\n\n## [0.5.0]" in changelog
    assert not record.exists()
    assert not next_version.exists()
