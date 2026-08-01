# Repository Artifact Audit

Audit baseline: `5ad78c5894e9ff3eae640a81d7a63f8e9b767e87` (2026-08-01).
Usage was checked through imports, file reads, FastAPI routes, package manifests,
tests, documentation references, archive contents, and file-specific Git history.

## Complete tracked-file classification

The classifications are the numbered categories requested by the audit.

| Class | Tracked files at the audited result |
| --- | --- |
| 1. Runtime-required | `djsupport/__init__.py`, `backup.py`, `beatport.py`, `cache.py`, `cli.py`, `config.py`, `label.py`, `matcher.py`, `migration.py`, `regression.py`, `rekordbox.py`, `report.py`, `spotify.py`, `transfer.py`, `web.py`; `djsupport/static/index.html`, `favicon.png`, `logo.png` |
| 2. Package/build-required | `pyproject.toml`, `MANIFEST.in`, `LICENSE`, `CHANGELOG.md`, `CONTRIBUTING.md`, `README.md`, `docs/backup-and-restore.md`, `docs/release-notes-0.4.0.md`, `docs/upgrading.md` |
| 3. Test fixture/verification | `tests/__init__.py`, `conftest.py`, all `tests/test_*.py`; `tests/fixtures/beatport_chart.json`, `beatport_label_page.json`, `library.xml`, `rekordbox_mirror_refresh.json`, `rekordbox_missing_track.xml` |
| 4. Canonical documentation/configuration | `.gitignore`, `.env.example`, `AGENTS.md`, `CONTEXT.md`, `agent.md`, `CLAUDE.md`, `.claude/docs/architectural_patterns.md`, `docs/adr/0001-keep-user-data-out-of-the-repository.md`, `docs/agents/domain.md`, `issue-tracker.md`, `triage-labels.md`, `legacy-document-triage.md`, this audit |
| 5. Historical but intentionally retained | Core completed/converted plans under `docs/plans/` (all remaining files); `docs/research/2026-08-01-playlist-management-api-review.md`; resolved knowledge under `docs/solutions/` (all files); completed review records `todos/001` through `todos/007` |
| 6. Design source/reference | `docs/design/NewUI.pen`, retained as the authored source for the core web-UI redesign introduced in `4663b67` and populated/updated in `464b225`; it is not runtime or package content |
| 7. Generated/private and ignored | No tracked files. `.gitignore` covers credentials, application state, source XML except synthetic fixtures, matching/regression evidence, reports, build/cache/editor output, root HTML explorations, runtime-folder `.pen` files, and design exports |
| 8. Obsolete/unused | No tracked files remain. Removed artifacts are listed below and recoverable from Git |

`git ls-files` supplied the population for this table. Python modules are imported
by adapters/tests or form the installed package. Package/build files are selected
by `pyproject.toml`, `MANIFEST.in`, and setuptools defaults. Tests and synthetic
fixtures are read by the offline suite. Markdown references and repository policy
establish the documentation categories.

## HTML findings

| File at baseline | Loader/server | Wheel/sdist | Role and disposition |
| --- | --- | --- | --- |
| `djsupport/static/index.html` | `djsupport.web.create_app()` reads it for `GET /`; `/static` serves its image references. `tests/test_web.py::TestIndexPage` exercises the route | Included in both by `[tool.setuptools.package-data]` and `MANIFEST.in`; confirmed by archive inspection | Core web UI; retained in place |
| `djsupport-datamodel.html` | No import, file read, route, test, or documentation link | Excluded from both because it was outside the package and `MANIFEST.in` selections | Standalone exploratory data-model visualizer, added in `504f34c`; removed |
| `matcher-playground.html` | No import, file read, route, test, or documentation link | Excluded from both for the same reason | Standalone matcher exploration, added in `504f34c`; removed |

None of the HTML files was Chrome-extension material. The separate extension plan
was documentation only and explicitly marked out of scope.

## Removed artifacts

| File | Evidence and rationale | Recovery |
| --- | --- | --- |
| `djsupport-datamodel.html` | Unreferenced exploratory HTML; stale terminology and state examples; never packaged or served | `git show 504f34c:djsupport-datamodel.html` |
| `matcher-playground.html` | Unreferenced standalone simulation; not executable verification and never packaged or served | `git show 504f34c:matcher-playground.html` |
| `docs/plans/2026-02-22-chore-repo-file-hygiene-and-access-control-plan.md` | Its own policy was reversed by later project guidance and superseded by ADR-0001 | `git show 5ad78c5:<path>` |
| `docs/plans/2026-03-22-feat-chrome-extension-beatport-to-spotify-plan.md` | Marked out of scope by the repository scope guard and legacy triage; not relocated across units | `git show 5ad78c5:<path>` |

No user-derived data, credentials, application data, or files outside this
worktree were removed.
