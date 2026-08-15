"""Behavior tests for the public-documentation impact gate."""

from __future__ import annotations

import importlib.util
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
