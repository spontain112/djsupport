"""Behavior tests for the public-documentation impact gate."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_docs_impact", ROOT / "scripts" / "check_docs_impact.py"
)
check_docs_impact = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = check_docs_impact
SPEC.loader.exec_module(check_docs_impact)


def test_internal_only_change_needs_no_docs_declaration() -> None:
    errors = check_docs_impact.validate(
        ["tests/test_transfer.py"],
        "",
    )

    assert errors == []


def test_public_behavior_change_requires_docs_declaration() -> None:
    errors = check_docs_impact.validate(
        ["djsupport/transfer.py"],
        "This changes Transfer behavior.",
    )

    assert errors == [
        "Public behavior changed. Add `Docs: <djsupport-docs PR URL>` or "
        "`Docs: no-impact — <reason>` to the pull request body."
    ]


def test_linked_docs_pull_request_satisfies_gate() -> None:
    errors = check_docs_impact.validate(
        ["README.md", "djsupport/transfer.py"],
        "Docs: https://github.com/spontain112/djsupport-docs/pull/42",
    )

    assert errors == []


def test_explicit_no_impact_reason_satisfies_gate() -> None:
    errors = check_docs_impact.validate(
        ["djsupport/transfer.py"],
        "Docs: no-impact — Internal refactor; public behavior is unchanged.",
    )

    assert errors == []


def test_empty_no_impact_reason_is_rejected() -> None:
    errors = check_docs_impact.validate(
        ["djsupport/transfer.py"],
        "Docs: no-impact",
    )

    assert errors


def test_deleted_public_file_requires_docs_declaration(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True
    )
    public_file = tmp_path / "djsupport" / "public.py"
    public_file.parent.mkdir()
    public_file.write_text("PUBLIC = True\n")
    subprocess.run(["git", "add", str(public_file)], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "add public file"], cwd=tmp_path, check=True)
    public_file.unlink()
    subprocess.run(["git", "add", "-u"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "remove public file"], cwd=tmp_path, check=True)

    assert check_docs_impact.changed_files("HEAD~1", "HEAD", cwd=tmp_path) == [
        "djsupport/public.py"
    ]
