# Contributing

## Development setup

DJ Support is a Python 3.10+ package. The CLI uses Click, the optional local web
adapter uses FastAPI, and the Spotify boundary uses Spotipy. Install development
and web dependencies from the repository root:

```bash
python3 -m pip install -e ".[dev,web]"
```

Run the fully offline test suite and compilation checks with:

```bash
pytest
python3 -m compileall -q djsupport tests
```

Use `djsupport --help` and `djsupport <command> --help` for the current command
and option reference. Click declarations in `djsupport/cli.py` are the executable
source of truth; documentation should explain workflows instead of duplicating
every flag.

## Repository map

```text
djsupport/
  transfer.py    Durable Transfer policy, planning, checkpoints, and publication
  runtime.py     Private production assembly for Transfer client adapters
  operational_store/ Fail-closed selected-binding qualification before store access
  agent.py       Versioned, harness-neutral Transfer contract rendering
  readiness.py   Shared presence-only readiness for CLI and web adapters
  cli.py         Thin Click command-line adapter
  web.py         Optional thin FastAPI adapter and static web application
  rekordbox.py   Rekordbox XML intake
  beatport.py    Beatport chart intake
  beatport_export.py Strict local Beatport CLI V2 contract intake
  source_facts.py Canonical typed occurrence and source-evidence values
  label.py       Beatport label discovery and intake
  matcher.py     Spotify candidate scoring and selection
  spotify.py     Typed Spotify API boundary
  cache.py       Durable matching knowledge
  paths.py       Canonical private application-data locations
  config.py      Versioned Rekordbox path configuration and migration
  report.py      Terminal, Markdown, and review CSV reports
  backup.py      Versioned local-data backup and restore
  migration.py   Explicit legacy-data migration
  local_audio.py Optional local-only Chromaprint boundary
  local_audition.py Process-local, path-redacted selected-media boundary
tests/           Offline behavior, adapter, migration, privacy, and package tests
docs/adr/        Architecture decisions
docs/plans/      Product roadmap and retained implementation history
docs/research/   Durable research findings
docs/solutions/  Retained incident knowledge
```

The canonical domain language is in [`CONTEXT.md`](CONTEXT.md). Transfer owns
high-level behavior; CLI, web, and agent clients render the same public policy
instead of implementing separate matching, Approval, persistence, or Spotify
publication rules.

See [Architecture](docs/architecture.md) for the canonical module and adapter
map, then use the [documentation map](docs/index.md) for the conceptual domain,
lifecycle, and private-storage models.

## Engineering conventions

- The CLI entry point is `djsupport.cli:cli`.
- The version and package metadata live in `pyproject.toml`.
- Persistent schemas remain backward-readable across their documented support
  window or receive an explicit, preview-first migration.
- High-level tests use the public Transfer interface and synthetic adapters.
- CLI and web adapters stay thin and do not become policy owners.
- AI harnesses use the versioned Transfer contract with separate private-source
  and Spotify-write authorization. Conversation is never authority.
- Local audio identity is Rekordbox-only, selected-Batch-only, opt-in, exact,
  account-scoped, and subordinate to Approval. Never scan directories, upload
  evidence, emit paths or fingerprints, or require `fpcalc` as a package binary.
- Qualification is Rekordbox-only and Transfer-owned. Draft decisions carry no
  authority; draft application and playlist Approval are separate explicit
  operations. Web, CLI, and agent code only render and collect Transfer facts.
- Local audition is a separate opt-in capability from local audio identity. It
  accepts only the exact selected occurrence, uses process-local opaque handles,
  emits no paths or filenames, and never calculates a fingerprint.
- Update `CONTRIBUTING.md` when the project map, development commands, or these
  conventions change.

For recurring implementation patterns, see
[architectural patterns](.claude/docs/architectural_patterns.md). GitHub Issues
use the repository's [issue workflow](docs/agents/issue-tracker.md) and
[triage vocabulary](docs/agents/triage-labels.md).

## Protect local DJ data

Report suspected vulnerabilities according to [`SECURITY.md`](SECURITY.md).
Never put vulnerability details or sensitive evidence in a public issue or
pull request.

Keep user data out of Git. This includes credentials and tokens, source-library
files and paths, playlist state and identifiers, Transfer reports and review
CSVs, Approved Matches, Corrections, matching-knowledge files, and local
regression exports. These belong in djsupport's private application-data
directory; see ADR-0001.

The ignore rules cover common names for these artifacts, but they are only a
guardrail. Before staging changes, inspect the file list and confirm that no
generated or user-derived data is present. Never move private evidence into a
different fixture to make it trackable.

Matcher tests committed to the repository must use invented artists, titles,
identifiers, and expected results. A real regression case may be contributed
only after the user explicitly exports it for contribution, consents to sharing
it, and the diff is reviewed for credentials, local paths, playlist state, and
unrelated library data. Local regression export names are ignored by default;
adding an approved contribution therefore requires an intentional force-add.

## Live match accuracy

The live accuracy workflow reads Corrections from the versioned local
matching-knowledge file used by the application. It does not use a repository
fixture:

```bash
python3 -m tests.test_match_accuracy
```

Use `--knowledge-path PATH` to select another local matching-knowledge file.
This workflow calls Spotify and is not part of the offline test suite. Do not
attach its output to an issue or pull request unless it has been generalized
and privacy-reviewed.

## Release checks

Run the offline suite with `pytest`. Release preparation also compiles the
Python package, runs the repository privacy tests, builds both source and wheel
artifacts, inspects every archive member, and installs the wheel in a clean
temporary environment for CLI/import smoke tests. Live Spotify and Beatport
checks are separate, explicitly authorized workflows and are never part of the
offline release gate.

Follow the canonical [maintainer release checklist](docs/releasing.md) for the
separate validation, candidate, final-release, and return-to-development gates.

When adding, removing, or changing a direct runtime, optional, development, or
build dependency—or a documented external tool—update
[`THIRD_PARTY.md`](THIRD_PARTY.md) in the same pull request. Link the canonical
upstream project, state how DJ Support uses it, and verify the SPDX license from
upstream metadata. Do not copy a third-party license into DJ Support unless its
distribution terms require that exact notice; package artifacts must retain all
notices required for content they actually bundle.

When a persistent schema changes, keep its reader compatible with documented
older versions or provide an explicit migration. Add a synthetic backup/restore
test that covers the current schema and the supported upgrade boundary. Never
use an actual application-data directory for release validation.
