---
unit: djsupport
kind: product
owner: JC
template_pin: unit-card@1.1
status: active
---

# DJ Support

## Start here

DJ Support transfers Rekordbox and Beatport selections to Spotify through the durable Transfer domain. Read this card first, then `CONTEXT.md` for domain language, `CONTRIBUTING.md` for the engineering guide, and `README.md` for supported user workflows.

## What goes where

- `CONTEXT.md` and `docs/adr/` — CANONICAL domain language and architecture decisions
- `djsupport/transfer.py` — CANONICAL Transfer policy and workflow seam
- `pyproject.toml` — CANONICAL package metadata, version, dependencies, and wheel package data
- `CONTRIBUTING.md` — development setup, project map, tests, and engineering conventions
- `README.md` and `docs/` — user guidance, upgrade/release notes, plans, research, and solutions
- `tests/` — offline behavior, adapter, migration, privacy, and packaging verification
- GitHub Issues — work specifications, decisions, and backlog state

Generated reports, review CSVs, matching knowledge, playlist state, credentials, source libraries, and local regression evidence are private user data; they are not repository content.

## Boundaries

- **Safe:** inspect code and docs; run offline tests, compilation, privacy checks, package builds, and synthetic migration/backup validation; prepare changes in an isolated named branch/worktree.
- **Gated:** live Spotify or Beatport calls; reading user-selected Rekordbox/audio data; Spotify playlist mutation; publishing packages, tags, or releases; changing remotes; exporting any user-derived regression evidence.
- **Never:** commit credentials, local paths, personal playlists, reports, Corrections, Approved Matches, playlist state, or user-derived fixtures; infer Approval, Corrections, source relinking, or destructive playlist intent.
- **Git discipline:** real work rides a named branch — `t<NN>/<slug>` or `djsupport/<feature-slug>` — never directly on `main`; follow PAW `practices/worktree-lifecycle.md` through name → work → merge → prune.

## Capabilities

- Python 3.10+ package with Click CLI and optional FastAPI web adapter.
- Use `pytest` for the fully offline default suite; detailed install, test, and command guidance lives in `CONTRIBUTING.md`.
- Use the public Transfer interface for high-level behavior. CLI and web remain thin adapters; user-specific state stays in versioned platform application-data storage under ADR-0001.
- A distributable change includes a `.release-notes/*.md` record. Automation maintains the version PR and consumes records into `CHANGELOG.md`; tags, GitHub Releases, and package publication remain separately gated.

## Routes

- Product behavior and defects → GitHub Issues using the repository triage vocabulary
- Architecture decisions → `docs/adr/` and `CONTEXT.md`
- Research and durable engineering findings → the matching `docs/` area
- User data and generated operational artifacts → private platform application-data storage only
- Estate identity and lifecycle classification → the separate `workspace` unit registry

## 2-minute test

A fresh agent should be able to answer: DJ Support publishes durable Transfers as Mirrors or Snapshots; Transfer owns policy; live services and releases are gated; user music data never enters Git; work uses a named branch/worktree; domain truth starts in `CONTEXT.md` and `docs/adr/`.
