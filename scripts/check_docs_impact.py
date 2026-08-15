#!/usr/bin/env python3
"""Require a public-documentation decision for public behavior changes."""

from __future__ import annotations

import argparse
import re
import subprocess


PUBLIC_PATHS = {
    ".env.example",
    "CONTEXT.md",
    "README.md",
    "pyproject.toml",
    "docs/architecture.md",
    "docs/backup-and-restore.md",
    "docs/domain-model.md",
    "docs/lifecycles.md",
    "docs/storage.md",
    "docs/upgrading.md",
}
PUBLIC_PREFIXES = ("djsupport/",)
DOCS_PR = re.compile(
    r"(?im)^Docs:\s+https://github\.com/spontain112/djsupport-docs/pull/\d+\s*$"
)
NO_IMPACT = re.compile(r"(?im)^Docs:\s+no-impact\s+(?:—|-)\s+\S.+$")


def affects_public_behavior(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


def validate(changed_files: list[str], pr_body: str) -> list[str]:
    if not any(affects_public_behavior(path) for path in changed_files):
        return []
    if DOCS_PR.search(pr_body) or NO_IMPACT.search(pr_body):
        return []
    return [
        "Public behavior changed. Add `Docs: <djsupport-docs PR URL>` or "
        "`Docs: no-impact — <reason>` to the pull request body."
    ]


def changed_files(base: str, head: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--diff-filter=AM", "--name-only", base, head],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--pr-body", default="")
    parser.add_argument("--changed-file", action="append", default=[])
    args = parser.parse_args()

    paths = args.changed_file
    if not paths:
        if not args.base or not args.head:
            parser.error("provide --changed-file or both --base and --head")
        paths = changed_files(args.base, args.head)

    errors = validate(paths, args.pr_body)
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        return 1
    print("Documentation impact is declared or no public behavior changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
