# Contributing

## Protect local DJ data

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
python -m tests.test_match_accuracy
```

Use `--knowledge-path PATH` to select another local matching-knowledge file.
This workflow calls Spotify and is not part of the offline test suite. Do not
attach its output to an issue or pull request unless it has been generalized
and privacy-reviewed.

## Development and release checks

Install development and optional web dependencies with:

```bash
python -m pip install -e ".[dev,web]"
```

Run the offline suite with `pytest`. Release preparation also compiles the
Python package, runs the repository privacy tests, builds both source and wheel
artifacts, inspects every archive member, and installs the wheel in a clean
temporary environment for CLI/import smoke tests. Live Spotify and Beatport
checks are separate, explicitly authorized workflows and are never part of the
offline release gate.

When a persistent schema changes, keep its reader compatible with documented
older versions or provide an explicit migration. Add a synthetic backup/restore
test that covers the current schema and the supported upgrade boundary. Never
use an actual application-data directory for release validation.
