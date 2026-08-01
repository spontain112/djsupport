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
