---
title: Repo File Hygiene and Access Control
type: chore
status: active
date: 2026-02-22
---

# Repo File Hygiene and Access Control

## Overview

Ensure the public djsupport GitHub repo properly separates public code from private/local-only files. Tighten `.gitignore`, remove already-tracked internal docs from git, and enable GitHub security features to prevent accidental credential exposure.

## Problem Statement / Motivation

djsupport is a public open-source repo. The creator's local environment contains sensitive and personal files (Spotify credentials, Rekordbox XML exports with full music library, OAuth tokens, planning docs). While most are already gitignored, several gaps exist:

- `.claude/` directory (contains local file paths) is **not** gitignored
- `docs/plans/` is **tracked in git** and publicly visible — should be local-only
- No IDE/OS artifact patterns (`.DS_Store`, `.vscode/`, `.idea/`)
- No proactive patterns for future test artifacts
- GitHub security features (Dependabot, secret scanning) not enabled

**Current state is safe** — no secrets have ever been committed to git history (verified). This is a hardening pass to prevent future accidents.

## Proposed Solution

Three categories of changes:

### 1. Update `.gitignore` (comprehensive patterns)

Add the following to `.gitignore`:

```gitignore
# Claude Code / AI tools
.claude/

# Internal planning docs (local-only)
docs/plans/

# IDE files
.vscode/
.idea/
*.iml
*.swp
*.swo
*~

# OS artifacts
.DS_Store
Thumbs.db

# Testing (proactive)
.pytest_cache/
.coverage
htmlcov/
.tox/

# Python extras
.mypy_cache/
*.pyo

# Logs
*.log
```

### 2. Remove `docs/plans/` from git tracking

The file `docs/plans/2026-02-22-fix-playlist-targeting-safety-plan.md` is already committed and publicly visible. Steps:

1. `git rm --cached -r docs/plans/` — untracks the directory but **preserves local files**
2. Commit the removal + `.gitignore` update together
3. The file remains on your machine, just no longer in the repo

**Note:** The file will still be visible in old git history/commits. This is acceptable — it contains no secrets, just technical planning context.

### 3. Enable GitHub security features

Via GitHub repo settings (`Settings > Code security and analysis`):

- **Dependabot security alerts**: ON (monitors `pyproject.toml` deps for vulnerabilities)
- **Dependabot security updates**: ON (auto-creates PRs for vulnerable deps)
- **Secret scanning**: ON (scans for accidentally committed credentials)
- **Push protection**: ON (blocks pushes containing detected secrets)

Skip Dependabot *version* updates (too noisy for a small project without CI/tests).

## Technical Considerations

- **`git rm --cached`** only untracks files — does not delete them locally. Safe to run.
- **Pattern `docs/plans/`** covers all contents recursively (git default behavior).
- **`.claude/` vs `.claude`**: Use `.claude/` (trailing slash) to match directory only.
- **IDE patterns in repo `.gitignore`** (not global) — helps contributors who haven't set up `~/.gitignore_global`.
- **No history rewrite needed** — the planning doc contains no secrets, so leaving it in old commits is fine.
- **`.env.example`** already uses safe placeholders (`your_client_id`, `your_client_secret`) — no false positive risk with secret scanning.

## What's Already Protected (no changes needed)

| File/Pattern | Status | Contains |
|---|---|---|
| `.env` | gitignored | Spotify API credentials |
| `*.xml` | gitignored | Rekordbox library (personal music data) |
| `.spotipy_cache*` | gitignored | OAuth access/refresh tokens |
| `.djsupport_cache*` | gitignored | Match cache with Spotify URIs |
| `.djsupport_playlists*` | gitignored | Playlist state with Spotify IDs |
| `CLAUDE.md` | gitignored | Project instructions (developer-specific) |
| `.venv/` | gitignored | Virtual environment |
| `__pycache__/`, `*.pyc` | gitignored | Python bytecode |

## What's Public (and should stay public)

| File | Why it's fine |
|---|---|
| `djsupport/*.py` | Source code — no hardcoded secrets (verified) |
| `.env.example` | Safe placeholder values only |
| `README.md` | Public documentation |
| `CHANGELOG.md` | Version history |
| `LICENSE` | MIT license |
| `pyproject.toml` | Package metadata and deps |
| `.gitignore` | Safe to share |

## Acceptance Criteria

- [x] `.claude/` added to `.gitignore`
- [x] `docs/plans/` added to `.gitignore`
- [x] IDE patterns (`.vscode/`, `.idea/`, `*.swp`) added to `.gitignore`
- [x] OS artifact patterns (`.DS_Store`, `Thumbs.db`) added to `.gitignore`
- [x] Proactive test patterns (`.pytest_cache/`, `.coverage`) added to `.gitignore`
- [x] `docs/plans/` removed from git tracking via `git rm --cached -r docs/plans/`
- [x] Single commit with all `.gitignore` changes + file removal
- [x] GitHub Dependabot security alerts enabled
- [x] GitHub secret scanning + push protection enabled
- [x] `git status` confirms no sensitive files are tracked
- [x] Local files (`docs/plans/*.md`, `.claude/`, etc.) still exist on disk after changes

## Dependencies & Risks

**Low risk overall** — this is additive protection, not behavior change.

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| AI agent runs `git add .` before `.gitignore` update | Medium | `.claude/` committed with file paths | Update `.gitignore` first, commit immediately |
| Contributor confused by missing `docs/plans/` | Low | Thinks files were deleted | Clear commit message explains the change |
| Dependabot PR breaks compatibility | Low | No test suite to catch regressions | Only enable security updates, not version updates |
| Secret scanning false positive | Very Low | Alert fatigue | `.env.example` uses safe placeholders |

## Out of Scope (future improvements)

- `CONTRIBUTING.md` with file hygiene guidelines
- `SECURITY.md` with vulnerability reporting instructions
- Pre-commit hooks for secret detection
- Branch protection rules
- CI/CD pipeline or automated testing
- `.gitattributes` for line ending normalization

## Sources & References

- GitHub docs: [Configuring secret scanning](https://docs.github.com/en/code-security/secret-scanning)
- GitHub docs: [Configuring Dependabot](https://docs.github.com/en/code-security/dependabot)
- gitignore patterns verified against [gitignore.io](https://gitignore.io) for Python + macOS
- Git history audit: confirmed no secrets in commit history via `git log --all --full-history`
