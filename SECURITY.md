# Security policy

DJ Support handles Spotify credentials and private local music-library state.
Please report suspected security vulnerabilities privately and share only the
minimum evidence needed to reproduce the issue.

## Supported versions

| Version | Security support |
| --- | --- |
| Latest final GitHub Release | Supported |
| Exact pre-release candidates | Best effort while under test |
| Older releases and the moving `main` branch | Not supported |

Upgrade to the [latest final release](https://github.com/spontain112/djsupport/releases/latest)
before reporting an issue that may already be fixed.

## Report a vulnerability

Do not disclose vulnerability details in a public issue, discussion, pull
request, log, or test fixture. In particular, never include credentials,
tokens, real library or playlist data, local paths, reports, Corrections,
Approved Matches, matching knowledge, or application-data archives.

If available, use GitHub's
[private security advisory form](https://github.com/spontain112/djsupport/security/advisories/new).
If that form is unavailable, open a
[public issue](https://github.com/spontain112/djsupport/issues/new) containing
only a request for a private security contact. Do not describe the
vulnerability in that issue.

In the private report, include:

- the affected release or exact commit;
- the security impact and affected boundary;
- minimal reproduction steps using synthetic data; and
- any relevant environment details with secrets and local paths removed.

This is a volunteer-maintained open-source project. Reports are handled on a
best-effort basis; no response deadline, fix deadline, or bug bounty is
promised. The maintainer may validate the report with synthetic data,
coordinate a fix and advisory, and publish a patched release.

## Scope

Security reports include suspected credential or token exposure, unauthorized
access to local files or private Transfer state, path traversal, authorization
bypasses for Spotify mutation or Approval, unsafe handling of imported data or
backups, unintended exposure by the loopback web adapter, and exploitable
dependency or supply-chain behavior.

Ordinary matching errors, feature requests, provider outages, and support
questions belong in public issues unless they create a confidentiality,
integrity, or authorization failure.

## Safe research and coordinated disclosure

Use your own accounts and synthetic data. Do not access another person's data,
mutate playlists without authorization, perform denial-of-service testing, or
violate a provider's terms. Give the maintainer a reasonable opportunity to
investigate and release a fix before public disclosure.

If the root cause is in an upstream project, report it through that project's
security process. Also notify DJ Support privately when its integration is
affected. See [Open-source acknowledgements](THIRD_PARTY.md) for the upstream
projects used directly by DJ Support.
