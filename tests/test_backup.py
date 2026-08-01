"""Public-seam behavior tests for local-data backup and restore."""

import json
import zipfile
from datetime import datetime

import pytest

from djsupport.backup import LocalDataBackup


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


class TestBackup:
    def test_creates_one_timestamped_archive_with_all_local_data(self, tmp_path):
        app_data = tmp_path / "app-data"
        _write_json(app_data / "matching-knowledge.json", {
            "version": 1, "entries": {"track": {"approval_status": "approved"}},
        })
        _write_json(app_data / "transfers.json", {
            "version": 1, "transfers": {"transfer-1": {}}, "batches": {},
        })
        _write_json(app_data / "publication-manifests.json", {
            "version": 3, "manifests": [{"spotify_playlist_id": "playlist-1"}],
            "approvals": [], "mirrors": [],
        })
        _write_json(app_data / "playlist-state.json", {
            "version": 2, "entries": {"playlist": {"spotify_id": "playlist-1"}},
        })
        (app_data / "reports").mkdir()
        (app_data / "reports" / "transfer-1.md").write_text("# Transfer report")

        archive = LocalDataBackup(app_data).create(
            tmp_path / "backups", now=datetime(2026, 8, 1, 12, 34, 56),
        )

        assert archive.name == "djsupport-backup-20260801T123456.zip"
        assert list((tmp_path / "backups").iterdir()) == [archive]
        with zipfile.ZipFile(archive) as bundle:
            assert set(bundle.namelist()) == {
                "backup-manifest.json", "matching-knowledge.json",
                "transfers.json", "publication-manifests.json",
                "playlist-state.json", "reports/transfer-1.md",
            }

    def test_excludes_credentials_tokens_secrets_and_unrelated_files(self, tmp_path):
        app_data = tmp_path / "app-data"
        _write_json(app_data / "matching-knowledge.json", {"version": 1, "entries": {}})
        for name in (".env", ".spotipy_cache", "oauth.json", "tokens.json", "notes.txt"):
            (app_data / name).write_text("CLIENT_SECRET=do-not-export")
        (app_data / "reports").mkdir()
        (app_data / "reports" / "credentials.md").write_text(
            "refresh_token=do-not-export"
        )

        archive = LocalDataBackup(app_data).create(tmp_path / "backups")

        with zipfile.ZipFile(archive) as bundle:
            exported = "\n".join(bundle.namelist()) + "\n" + b"\n".join(
                bundle.read(name) for name in bundle.namelist()
            ).decode()
        assert "do-not-export" not in exported
        assert "oauth" not in exported.casefold()
        assert "token" not in exported.casefold()

    def test_does_not_follow_report_symlinks_to_secrets(self, tmp_path):
        app_data = tmp_path / "app-data"
        _write_json(app_data / "matching-knowledge.json", {"version": 1, "entries": {}})
        secret = tmp_path / "oauth-secret.md"
        secret.write_text("refresh_token=never-export")
        (app_data / "reports").mkdir()
        (app_data / "reports" / "linked.md").symlink_to(secret)

        archive = LocalDataBackup(app_data).create(tmp_path / "backups")

        with zipfile.ZipFile(archive) as bundle:
            assert "reports/linked.md" not in bundle.namelist()

    @pytest.mark.parametrize(
        "credential",
        [
            "Authorization: Bearer spotify-oauth-token",
            "SPOTIPY_CLIENT_SECRET=spotify-secret",
            "SPOTIPY_CLIENT_ID=spotify-client-id",
        ],
    )
    def test_excludes_reports_with_common_oauth_credential_forms(
        self, tmp_path, credential,
    ):
        app_data = tmp_path / "app-data"
        _write_json(app_data / "matching-knowledge.json", {"version": 1})
        (app_data / "reports").mkdir()
        (app_data / "reports" / "unsafe.md").write_text(credential)

        archive = LocalDataBackup(app_data).create(tmp_path / "backups")

        with zipfile.ZipFile(archive) as bundle:
            assert "reports/unsafe.md" not in bundle.namelist()

    def test_refuses_supported_data_with_env_style_oauth_fields(self, tmp_path):
        app_data = tmp_path / "app-data"
        _write_json(app_data / "matching-knowledge.json", {
            "version": 1, "SPOTIPY_CLIENT_SECRET": "never-export",
        })

        with pytest.raises(ValueError, match="Credential fields"):
            LocalDataBackup(app_data).create(tmp_path / "backups")

        assert not (tmp_path / "backups").exists()


class TestRestorePreview:
    def test_validates_integrity_and_previews_without_mutating(self, tmp_path):
        source = tmp_path / "source"
        target = tmp_path / "target"
        _write_json(source / "matching-knowledge.json", {
            "version": 1, "entries": {"incoming": {"approval_status": None}},
        })
        _write_json(target / "matching-knowledge.json", {
            "version": 1, "entries": {"current": {"approval_status": "approved"}},
        })
        archive = LocalDataBackup(source).create(tmp_path / "backups")
        before = (target / "matching-knowledge.json").read_bytes()

        preview = LocalDataBackup(target).preview(archive)

        assert preview.valid is True
        assert preview.contents == ("matching-knowledge.json",)
        assert preview.changes == ("add matching knowledge: incoming",)
        assert preview.conflicts == ()
        assert (target / "matching-knowledge.json").read_bytes() == before

    def test_accepts_current_publication_manifest_schema(self, tmp_path):
        source = tmp_path / "source"
        _write_json(source / "publication-manifests.json", {
            "version": 4,
            "manifests": [],
            "approvals": [],
            "mirrors": [],
        })
        archive = LocalDataBackup(source).create(tmp_path / "backups")

        preview = LocalDataBackup(tmp_path / "target").preview(archive)

        assert preview.valid is True
        assert preview.contents == ("publication-manifests.json",)

    @pytest.mark.parametrize("damage", ["corrupt", "unsupported-backup", "unsupported-data"])
    def test_rejects_corrupt_or_unsupported_archive(self, tmp_path, damage):
        source = tmp_path / "source"
        _write_json(source / "matching-knowledge.json", {"version": 1, "entries": {}})
        archive = LocalDataBackup(source).create(tmp_path / "backups")
        if damage == "corrupt":
            archive.write_bytes(b"not a zip")
        else:
            with zipfile.ZipFile(archive, "a") as bundle:
                if damage == "unsupported-backup":
                    manifest = json.loads(bundle.read("backup-manifest.json"))
                    manifest["version"] = 999
                    bundle.writestr("backup-manifest.json", json.dumps(manifest))
                else:
                    bundle.writestr("matching-knowledge.json", json.dumps({"version": 999}))

        preview = LocalDataBackup(tmp_path / "target").preview(archive)

        assert preview.valid is False
        assert preview.errors


class TestRestore:
    def test_merges_non_conflicting_data_and_preserves_existing_knowledge(self, tmp_path):
        source = tmp_path / "source"
        target = tmp_path / "target"
        _write_json(source / "matching-knowledge.json", {
            "version": 1, "entries": {"incoming": {"spotify_uri": "new"}},
            "local_regressions": [], "approval_conflicts": [],
        })
        _write_json(target / "matching-knowledge.json", {
            "version": 1, "entries": {"current": {"spotify_uri": "keep"}},
            "local_regressions": [], "approval_conflicts": [],
        })
        archive = LocalDataBackup(source).create(tmp_path / "backups")

        result = LocalDataBackup(target).restore(archive)

        assert result.restored is True
        entries = json.loads((target / "matching-knowledge.json").read_text())["entries"]
        assert entries == {
            "current": {"spotify_uri": "keep"},
            "incoming": {"spotify_uri": "new"},
        }

    @pytest.mark.parametrize("kind", ["approval", "playlist-state"])
    def test_conflicts_require_resolution_and_leave_current_data_intact(self, tmp_path, kind):
        source = tmp_path / "source"
        target = tmp_path / "target"
        if kind == "approval":
            filename = "matching-knowledge.json"
            current = {"version": 1, "entries": {"track": {
                "approval_status": "approved", "spotify_uri": "current",
            }}}
            incoming = {"version": 1, "entries": {"track": {
                "approval_status": "approved", "spotify_uri": "incoming",
            }}}
        else:
            filename = "playlist-state.json"
            current = {"version": 2, "entries": {"playlist": {"spotify_id": "current"}}}
            incoming = {"version": 2, "entries": {"playlist": {"spotify_id": "incoming"}}}
        _write_json(source / filename, incoming)
        _write_json(target / filename, current)
        archive = LocalDataBackup(source).create(tmp_path / "backups")
        before = (target / filename).read_bytes()

        preview = LocalDataBackup(target).preview(archive)
        result = LocalDataBackup(target).restore(archive)

        assert preview.conflicts[0].kind == kind
        assert preview.conflicts[0].choices == ("current", "archive")
        assert result.restored is False
        assert result.conflicts == preview.conflicts
        assert (target / filename).read_bytes() == before

    def test_rolls_back_all_files_when_commit_fails(self, tmp_path):
        source = tmp_path / "source"
        target = tmp_path / "target"
        for root, suffix in ((source, "incoming"), (target, "current")):
            _write_json(root / "matching-knowledge.json", {
                "version": 1, "entries": {suffix: {}},
            })
            _write_json(root / "transfers.json", {
                "version": 1, "transfers": {suffix: {}}, "batches": {},
            })
        archive = LocalDataBackup(source).create(tmp_path / "backups")
        before = {path.name: path.read_bytes() for path in target.iterdir()}

        def fail_second_commit(source_path, target_path, count=[0]):
            count[0] += 1
            if count[0] == 2:
                raise OSError("disk failure")
            source_path.replace(target_path)

        with pytest.raises(OSError, match="disk failure"):
            LocalDataBackup(target, replace_file=fail_second_commit).restore(archive)

        assert {path.name: path.read_bytes() for path in target.iterdir()} == before

    def test_explicit_archive_resolution_replaces_only_the_named_conflict(self, tmp_path):
        source = tmp_path / "source"
        target = tmp_path / "target"
        current = {"version": 1, "entries": {"track": {
            "approval_status": "approved", "spotify_uri": "current",
        }}}
        incoming = {"version": 1, "entries": {"track": {
            "approval_status": "approved", "spotify_uri": "incoming",
        }}}
        _write_json(source / "matching-knowledge.json", incoming)
        _write_json(target / "matching-knowledge.json", current)
        archive = LocalDataBackup(source).create(tmp_path / "backups")
        service = LocalDataBackup(target)
        conflict = service.preview(archive).conflicts[0]

        result = service.restore(
            archive, resolutions={conflict.conflict_id: "archive"},
        )

        assert result.restored is True
        restored = json.loads((target / "matching-knowledge.json").read_text())
        assert restored["entries"]["track"]["spotify_uri"] == "incoming"

    def test_differing_reports_are_surfaced_and_never_silently_overwritten(
        self, tmp_path,
    ):
        source = tmp_path / "source"
        target = tmp_path / "target"
        for root, text in ((source, "archive report"), (target, "current report")):
            (root / "reports").mkdir(parents=True)
            (root / "reports" / "transfer.md").write_text(text)
        archive = LocalDataBackup(source).create(tmp_path / "backups")
        service = LocalDataBackup(target)

        preview = service.preview(archive)
        result = service.restore(archive)

        assert preview.conflicts[0].kind == "report"
        assert result.restored is False
        assert (target / "reports" / "transfer.md").read_text() == "current report"
