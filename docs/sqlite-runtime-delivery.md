# Qualified SQLite runtime delivery

DJ Support pins APSW 3.53.4.0 as its sole production SQLite Python binding for
the future Operational Store. APSW remains private to the deep Operational
Store adapter; Transfer, the CLI, web, and Agent Client depend only on the
binding-neutral interface. Python's standard `sqlite3` never opens an
Operational Store.

JSON remains the production authority. This delivery work does not create a
database, enable WAL, migrate state, activate SQLite, access owner data, call a
live provider, create a tag or GitHub Release, or publish a package.

## Supported native cells

Support is evidence, not a version-floor claim. The versioned
`apsw-runtime-artifacts.v1.json` catalog names the exact official PyPI wheel,
SHA-256 digest, size, provenance endpoint, Python patch, OS runner, and native
architecture for every claimed cell. The qualification manifest separately
binds that archive to the loaded extension digest, APSW and SQLite identities,
compile options, ABI, GIL mode, exact OS facts, and runner image.

The 0.7 delivery contract claims these binary-only cells:

- Ubuntu 24.04 on x86-64 and ARM64, CPython 3.10–3.14;
- macOS 15 on Intel and Apple silicon, CPython 3.10–3.14; and
- Windows Server 2025 on x64, CPython 3.10–3.14.

Windows ARM, 32-bit platforms, musllinux, free-threaded Python, source builds,
other operating-system versions, and unlisted future runtimes are unsupported.
An official wheel existing on PyPI does not make an unclaimed cell supported.

## Installation and failure policy

Release qualification downloads APSW with pip's binary-only mode, verifies its
reviewed filename, size, and digest, cryptographically verifies the PyPI Trusted
Publisher attestation for `rogerbinns/apsw`, builds the DJ Support source and
wheel archives, installs them into a clean environment, and probes the binding
that would open the store. A missing wheel, source-build attempt, provenance
failure, runtime near-miss, revoked entry, or unknown cell fails before any
Operational Store path or state mutation.

Ordinary Python dependency metadata cannot require pip's binary-only resolver.
Installers therefore use `--only-binary=apsw`; a source build may install but is
never admitted by the extension digest and fail-closed runtime manifest. There
is no standard-library, rollback-journal, JSON-after-cutover, configuration,
warning-only, or checkpoint-scheduling fallback.

## Update and monitoring ownership

The DJ Support maintainer owns the qualification manifest and reviews the
official SQLite news, SQLite release notes and security guidance, the APSW
release feed, the PyPI artifact set and attestations, and repository dependency
alerts before changing the pin. A binding update requires a reviewed source and
artifact diff plus the complete native matrix; a numeric version alone is not
evidence.

A SQLite or APSW withdrawal, vulnerability, changed publisher identity,
attestation failure, removed wheel, or conflicting source identity triggers an
immediate fail-closed review. The maintainer revokes or supersedes affected
entries in the manifest and follows the repository security policy for private
coordination when details are sensitive. Revocation never silently selects a
different binding or restores JSON authority after cutover.
