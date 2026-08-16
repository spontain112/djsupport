#!/usr/bin/env python3
"""Validate release records and prepare the next version pull request."""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / ".release-notes"
NEXT_VERSION = RECORDS / "next-version"
ALLOWED_BUMPS = {"patch": 0, "minor": 1, "major": 2}
ALLOWED_SECTIONS = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")
VERSION_PATTERN = re.compile(r'(?m)^version = "([^"]+)"$')
PUBLIC_ROOT_ARTIFACTS = frozenset(
    {
        ".env.example",
        "CHANGELOG.md",
        "CONTEXT.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "MANIFEST.in",
        "README.md",
        "SECURITY.md",
        "THIRD_PARTY.md",
        "pyproject.toml",
    }
)


@dataclass(frozen=True)
class ReleaseRecord:
    path: Path
    bump: str
    section: str
    summary: str


def _run_git(*args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


def _parse_record(path: Path) -> ReleaseRecord:
    text = path.read_text(encoding="utf-8")
    match = re.fullmatch(r"---\n(.*?)\n---\n+(.+?)\n?", text, re.DOTALL)
    if match is None:
        raise ValueError(f"{path.name}: expected YAML-style frontmatter and a summary")

    metadata = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            raise ValueError(f"{path.name}: invalid metadata line: {line}")
        metadata[key.strip()] = value.strip()

    bump = metadata.get("bump", "")
    section = metadata.get("section", "")
    summary = " ".join(match.group(2).split())
    if set(metadata) != {"bump", "section"}:
        raise ValueError(f"{path.name}: metadata must contain only bump and section")
    if bump not in ALLOWED_BUMPS:
        raise ValueError(f"{path.name}: bump must be patch, minor, or major")
    if section not in ALLOWED_SECTIONS:
        raise ValueError(f"{path.name}: unsupported changelog section {section!r}")
    if not summary:
        raise ValueError(f"{path.name}: summary must not be empty")
    return ReleaseRecord(path, bump, section, summary)


def load_records() -> list[ReleaseRecord]:
    return [_parse_record(path) for path in sorted(RECORDS.glob("*.md")) if path.name != "README.md"]


def _is_distributable(path: str) -> bool:
    return (
        path.startswith("djsupport/")
        or path in PUBLIC_ROOT_ARTIFACTS
        or (
            path.startswith("docs/")
            and path != "docs/releasing.md"
            and not path.startswith("docs/research/")
        )
    )


def check_range(base: str, head: str) -> None:
    changed = _run_git("diff", "--name-only", base, head).splitlines()
    if not any(_is_distributable(path) for path in changed):
        print("No distributable changes.")
        return

    added_records = _run_git(
        "diff", "--diff-filter=AM", "--name-only", base, head, "--", ".release-notes"
    ).splitlines()
    if any(path.endswith(".md") and not path.endswith("/README.md") for path in added_records):
        for record in load_records():
            _parse_record(record.path)
        print("Distributable change includes a release record.")
        return

    base_version = _run_git("show", f"{base}:pyproject.toml")
    head_version = _run_git("show", f"{head}:pyproject.toml")
    if VERSION_PATTERN.search(base_version).group(1) != VERSION_PATTERN.search(head_version).group(1):
        print("Distributable change is included in a version update.")
        return
    raise SystemExit(
        "Distributable behavior changed without a .release-notes/*.md record."
    )


def _next_version(current: str, records: list[ReleaseRecord]) -> str:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:(?:\.dev|rc)(\d+))?", current)
    if match is None:
        raise ValueError(f"unsupported project version: {current}")
    major, minor, patch = map(int, match.groups()[:3])
    if ".dev" in current:
        return f"{major}.{minor}.{patch}"
    if "rc" in current:
        candidate = int(match.group(4)) + 1
        return f"{major}.{minor}.{patch}rc{candidate}"
    bump = max(records, key=lambda record: ALLOWED_BUMPS[record.bump]).bump
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _add_summary(body: str, section: str, summary: str) -> str:
    heading = f"### {section}"
    addition = f"- {summary}\n"
    if heading not in body:
        section_body = f"{heading}\n\n{addition}"
        return f"{body.rstrip()}\n\n{section_body}" if body.strip() else section_body
    start = body.index(heading) + len(heading)
    next_heading = body.find("\n### ", start)
    insertion = len(body) if next_heading == -1 else next_heading
    return body[:insertion].rstrip() + "\n" + addition + "\n" + body[insertion:].lstrip("\n")


def prepare(date: str) -> str | None:
    records = load_records()
    if not records:
        print("No pending release records.")
        return None

    pyproject_path = ROOT / "pyproject.toml"
    pyproject = pyproject_path.read_text(encoding="utf-8")
    current = VERSION_PATTERN.search(pyproject).group(1)
    if NEXT_VERSION.exists():
        version = NEXT_VERSION.read_text(encoding="utf-8").strip()
        if re.fullmatch(r"\d+\.\d+\.\d+(?:rc\d+)?", version) is None:
            raise ValueError(f"unsupported next-version override: {version}")
    else:
        version = _next_version(current, records)

    changelog_path = ROOT / "CHANGELOG.md"
    changelog = changelog_path.read_text(encoding="utf-8")
    unreleased = "## [Unreleased]"
    start = changelog.index(unreleased) + len(unreleased)
    next_release = changelog.find("\n## [", start)
    body = changelog[start:next_release].strip() if next_release != -1 else changelog[start:].strip()
    for record in records:
        body = _add_summary(body, record.section, record.summary)
    replacement = f"## [Unreleased]\n\n## [{version}] - {date}\n\n{body.rstrip()}\n\n"
    end = next_release if next_release != -1 else len(changelog)

    pyproject_path.write_text(
        VERSION_PATTERN.sub(f'version = "{version}"', pyproject, count=1), encoding="utf-8"
    )
    changelog_path.write_text(
        changelog[: changelog.index(unreleased)]
        + replacement
        + changelog[end:].lstrip("\n"),
        encoding="utf-8",
    )
    for record in records:
        record.path.unlink()
    if NEXT_VERSION.exists():
        NEXT_VERSION.unlink()
    print(version)
    return version


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("base")
    check_parser.add_argument("head")
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--date", default=dt.date.today().isoformat())
    args = parser.parse_args()
    if args.command == "check":
        check_range(args.base, args.head)
    else:
        prepare(args.date)


if __name__ == "__main__":
    main()
