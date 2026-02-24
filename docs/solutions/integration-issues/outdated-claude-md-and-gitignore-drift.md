---
title: "Outdated CLAUDE.md and Gitignore Documentation Drift"
date: 2026-02-24
problem_type: integration-issues
severity: medium
components_affected:
  - documentation
  - project-configuration
  - version-control
tags:
  - documentation
  - gitignore
  - claude-md
  - onboarding
  - configuration-drift
symptoms:
  - CLAUDE.md referenced v0.1.0 while project was at v0.2.0
  - Only 4 modules listed when 8 existed
  - "No test suite" stated despite 143 pytest tests
  - CLI flags undocumented (--playlist, --threshold, --all, --report, --no-cache, --retry, --prefix, --incremental)
  - CLAUDE.md and docs/ were gitignored, hiding project guidance from collaborators
---

# Outdated CLAUDE.md and Gitignore Documentation Drift

## Problem

CLAUDE.md was written during initial v0.1.0 development and never updated as the project grew to v0.2.0. This caused AI tools to give inaccurate guidance — suggesting the project had no tests, missing 4 modules from project structure, and not documenting any of the new CLI flags.

Additionally, `.gitignore` had been configured to exclude `CLAUDE.md` and `docs/plans/` from version control, meaning collaborators couldn't access project guidance or planning documents.

## Root Cause

CLAUDE.md was treated as a one-time setup file rather than living documentation. There was no process to update it alongside feature development. The gitignore entries were added during a cleanup that was too aggressive about privacy — treating all AI/planning files as personal rather than distinguishing between project guidance (shareable) and personal data (private).

## Investigation Steps

1. **Read CLAUDE.md** — Found stale v0.1.0 content: only 4 modules, "No test suite", 3 CLI commands
2. **Read pyproject.toml** — Confirmed actual version is 0.2.0 with pytest/pytest-cov dev deps
3. **Ran `djsupport sync --help`** — Discovered all current flags (--playlist, --threshold, --all, --report, --no-cache, --retry, --prefix, --incremental, etc.)
4. **Ran `djsupport library --help`** — Found set/show subcommands
5. **Globbed `djsupport/*.py`** — Confirmed 8 modules: cli, rekordbox, matcher, spotify, config, cache, state, report
6. **Read .gitignore** — Found `CLAUDE.md` and `docs/plans/` were excluded from tracking

## Solution

### 1. Rewrote CLAUDE.md for v0.2.0

Updated all sections to match current repo state:
- **Tech stack**: Added pytest, pytest-cov
- **Project structure**: Added config.py, cache.py, state.py, report.py, tests/, docs/
- **Key commands**: Added `library set/show`, all sync flags, test commands
- **Version**: Updated to 0.2.0
- **Conventions**: Added new gitignored files, docs/ reference

### 2. Fixed .gitignore

Removed entries that excluded project documentation:

```diff
- CLAUDE.md
- # Internal planning docs (local-only)
- docs/plans/
+ # Claude Code session data (local-only)
  .claude/
```

The key distinction: `.claude/` (session data) stays private, but `CLAUDE.md` and `docs/` are shared project resources.

### 3. Updated CHANGELOG.md

Added 0.2.1 section for the unreleased feature work and noted the documentation fixes in [Unreleased].

## Gitignore Decision Framework

```
Does this file contain:
+-- PII or user-specific data (playlists, paths)?     -> GITIGNORE
+-- Credentials (API keys, tokens)?                    -> GITIGNORE
+-- User-specific state (.cache, .config)?             -> GITIGNORE
+-- Build artifacts (__pycache__, dist)?                -> GITIGNORE
+-- Does it help collaborators understand the project?
    +-- YES (architecture, plans, test data)            -> TRACK IT
    +-- NO (IDE settings, OS artifacts)                 -> GITIGNORE
```

| File | Decision | Reason |
|------|----------|--------|
| `.env` | Gitignore | Spotify credentials |
| `*.xml` | Gitignore | User's personal DJ library |
| `.djsupport_*.json` | Gitignore | User-specific runtime state |
| `.spotipy_cache*` | Gitignore | OAuth tokens |
| `.claude/` | Gitignore | AI session data |
| `CLAUDE.md` | Track | Project guidance for all developers |
| `docs/` | Track | Shared plans and reports |
| `tests/fixtures/*.xml` | Track | Reproducible test data |

## Prevention

1. **Update CLAUDE.md in the same PR as feature changes** — When adding modules, CLI flags, or dependencies, update CLAUDE.md in the same commit
2. **Pre-release audit** — Before tagging a release, verify CLAUDE.md matches:
   - `pyproject.toml` version
   - `ls djsupport/*.py` module list
   - `djsupport --help` CLI output
3. **PR checklist** — Add a checkbox: "Updated CLAUDE.md if project structure, CLI, or conventions changed"

## Related Documentation

- `docs/plans/2026-02-22-chore-repo-file-hygiene-and-access-control-plan.md` — Original plan that introduced the gitignore cleanup
- `CHANGELOG.md` — Documents all version changes
- `docs/isrc-mutagen-plan.md` — Example of tracked planning doc
