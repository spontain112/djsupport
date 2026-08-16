"""Repository-level privacy guardrails for user-derived application data."""

from pathlib import Path
import subprocess

import pytest


REPOSITORY_ROOT = Path(__file__).parents[1]


class TestRepositoryPrivacy:
    @pytest.mark.parametrize(
        "path",
        [
            "reports/transfer.md",
            "docs/reports/private-transfer.md",
            "report.md",
            "transfer-report.md",
            "review.csv",
            "transfer-report.csv",
            "review.djsupport-report.csv",
            "matching-regressions.json",
            "local-regression-export.csv",
            "spotify-credentials.json",
            ".env.local",
            ".djsupport_config.json",
            "playlist-state.json",
            "festival-playlist-state.json",
            "operational-store.sqlite3",
            "operational-store.sqlite3-wal",
            "operational-store.sqlite3-shm",
            "operational-store.sqlite3-journal",
            "operational-store.authority.json",
            "operational-stores/01JTEST.sqlite3",
            "operational-stores/01JTEST.sqlite3-wal",
            "djsupport-snapshot-2026-08-16.sqlite3",
            "djsupport-snapshot-2026-08-16.sqlite3-wal",
            "djsupport-backup-2026-08-16.zip",
            "backup-manifest.json",
            "djsupport-migration-staging/candidate.sqlite3",
            "djsupport-restore-staging/operational-store.sqlite3",
            "djsupport-restore-extracted/backup-manifest.json",
            "djsupport-rollback-before-apply.sqlite3",
            "djsupport-operational-events.json",
            "djsupport-analytics.json",
            "djsupport-analytics.csv",
            "djsupport-analytics.tsv",
            "djsupport-diagnostics.json",
            "djsupport-query-export.csv",
            "matching-knowledge.json",
            "publication-manifests.json",
            "publication-manifests.transfers.json",
            "transfers.json",
            "legacy-migration.json",
            "foundation-migration.json",
            "config.json",
        ],
    )
    def test_user_derived_artifacts_are_ignored(self, path):
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "--no-index", path],
            cwd=REPOSITORY_ROOT,
            check=False,
        )

        assert result.returncode == 0, (
            f"privacy-sensitive artifact is not ignored: {path}"
        )

    def test_personal_evidence_fixtures_are_removed_from_repository(self):
        assert not (
            REPOSITORY_ROOT / "docs/reports/unmatched-tracks-2026-02-25.md"
        ).exists()
        assert not (
            REPOSITORY_ROOT / "tests/fixtures/match_test_data.csv"
        ).exists()

    def test_generated_sqlite_images_are_not_tracked(self):
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        sqlite_artifact_suffixes = (
            ".sqlite3",
            ".sqlite3-wal",
            ".sqlite3-shm",
            ".sqlite3-journal",
        )

        tracked_artifacts = [
            path
            for path in result.stdout.splitlines()
            if path.endswith(sqlite_artifact_suffixes)
        ]

        assert not tracked_artifacts, tracked_artifacts

    def test_obsolete_artifact_locations_are_ignored(self):
        for path in (
            "djsupport-datamodel.html",
            "matcher-playground.html",
            "djsupport/NewUI.pen",
        ):
            result = subprocess.run(
                ["git", "check-ignore", "--quiet", "--no-index", path],
                cwd=REPOSITORY_ROOT,
                check=False,
            )
            assert result.returncode == 0, f"generated artifact is not ignored: {path}"

    def test_only_runtime_html_is_tracked(self):
        result = subprocess.run(
            ["git", "ls-files", "*.html"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        existing = [
            path for path in result.stdout.splitlines()
            if (REPOSITORY_ROOT / path).exists()
        ]
        assert existing == ["djsupport/static/index.html"]

    def test_chrome_design_source_is_not_retained_in_core(self):
        assert not (REPOSITORY_ROOT / "docs/design/NewUI.pen").exists()
        assert not (REPOSITORY_ROOT / "djsupport/NewUI.pen").exists()
