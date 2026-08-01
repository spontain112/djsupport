"""Repository-level privacy guardrails for user-derived application data."""

from pathlib import Path
import subprocess

import pytest


REPOSITORY_ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize(
    "path",
    [
        "reports/transfer.md",
        "docs/reports/private-transfer.md",
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
def test_user_derived_artifacts_are_ignored(path):
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", path],
        cwd=REPOSITORY_ROOT,
        check=False,
    )

    assert result.returncode == 0, f"privacy-sensitive artifact is not ignored: {path}"


def test_personal_evidence_fixtures_are_removed_from_repository():
    assert not (REPOSITORY_ROOT / "docs/reports/unmatched-tracks-2026-02-25.md").exists()
    assert not (REPOSITORY_ROOT / "tests/fixtures/match_test_data.csv").exists()

