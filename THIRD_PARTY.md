# Open-source acknowledgements

DJ Support is possible because people maintain and share excellent open-source
software. Thank you to every author, maintainer, reviewer, documentarian, and
contributor behind the projects below.

This is an acknowledgement and navigation index, not a replacement for the
projects' license texts. DJ Support does not vendor these projects. Python
package installers resolve them separately under their own licenses and may
also install transitive dependencies; inspect the installed distributions for
the exact version and complete license material in a particular environment.

## Runtime dependencies

| Project | How DJ Support uses it | License |
| --- | --- | --- |
| [APSW](https://github.com/rogerbinns/apsw) | Sole private Python binding for the qualified local Operational Store; pinned to 3.53.4.0 for the 0.7 release train | [Any OSI-approved license](https://rogerbinns.github.io/apsw/copyright.html) |
| [SQLite](https://sqlite.org/) | Embedded by the approved APSW binary artifacts as the local transactional database engine; pinned runtime 3.53.4 | [Public domain](https://sqlite.org/copyright.html) |
| [Spotipy](https://github.com/spotipy-dev/spotipy) | Spotify authentication and Web API access | MIT |
| [Click](https://github.com/pallets/click) | Command-line interface | BSD-3-Clause |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | Optional environment-file loading | BSD-3-Clause |
| [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) | Source-to-Spotify similarity scoring | MIT |
| [Requests](https://github.com/psf/requests) | HTTP access for supported Beatport sources | Apache-2.0 |
| [jsonschema](https://github.com/python-jsonschema/jsonschema) | Strict Beatport export contract validation | MIT |

## Optional local web dependencies

| Project | How DJ Support uses it | License |
| --- | --- | --- |
| [FastAPI](https://github.com/fastapi/fastapi) | Local web adapter | MIT |
| [Uvicorn](https://github.com/Kludex/uvicorn) | Local ASGI server | BSD-3-Clause |

## Development and build tools

| Project | How DJ Support uses it | License |
| --- | --- | --- |
| [Python](https://github.com/python/cpython) | Language and standard library | PSF-2.0 |
| [Git](https://github.com/git/git) | Source history and contribution workflow | GPL-2.0-only |
| [setuptools](https://github.com/pypa/setuptools) | Package build backend | MIT |
| [wheel](https://github.com/pypa/wheel) | Wheel build format tooling | MIT |
| [build](https://github.com/pypa/build) | Isolated source and wheel builds | MIT |
| [pytest](https://github.com/pytest-dev/pytest) | Offline behavior tests | MIT |
| [pytest-cov](https://github.com/pytest-dev/pytest-cov) | Test coverage | MIT |
| [HTTPX](https://github.com/encode/httpx) | Local web-adapter tests | BSD-3-Clause |
| [PyYAML](https://github.com/yaml/pyyaml) | Release-workflow validation tests | MIT |
| [Tomli](https://github.com/hukkin/tomli) | TOML parsing on Python 3.10 | MIT |

## Continuous integration tools

| Project | How DJ Support uses it | License |
| --- | --- | --- |
| [checkout](https://github.com/actions/checkout) | GitHub Actions source checkout | MIT |
| [setup-python](https://github.com/actions/setup-python) | GitHub Actions Python toolchains | MIT |
| [CodeQL](https://github.com/github/codeql-action) | Static security analysis for Python and GitHub Actions workflows | MIT |
| [certifi](https://github.com/certifi/python-certifi) | CA bundle for CI-only PyPI attestation HTTPS verification | MPL-2.0 |
| [PyPI Attestations](https://github.com/pypi/pypi-attestations) | Pinned CI verifier for APSW wheel Trusted Publisher attestations | Apache-2.0 |

## Independent external tools

These tools are not Python dependencies and are not bundled with DJ Support.
Users install or run them separately under their own licenses.

| Project | How DJ Support interoperates with it | License |
| --- | --- | --- |
| [Chromaprint](https://github.com/acoustid/chromaprint) / `fpcalc` | Optional, local-only audio fingerprint calculation | LGPL-2.1-only |
| `beatport-pp-cli` | Optional producer of the occurrence-safe Beatport V2 JSON consumed by DJ Support | Unverified; do not infer an upstream or installation route until [issue #133](https://github.com/spontain112/djsupport/issues/133) is resolved |

Spotify, Beatport, and Rekordbox are third-party products and trademarks, not
open-source dependencies of DJ Support. Interoperability does not imply their
endorsement of this project.

## Maintenance rule

Any change to direct dependencies, build tools, or documented external-tool
interoperability must update this file in the same pull request. Release
validation checks that the direct dependency groups in `pyproject.toml` remain
represented here and that this acknowledgement ships in the source archive.
