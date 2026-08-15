# Release notes

Every pull request that changes distributable behavior adds one Markdown file to
this directory. Use a short unique filename and this shape:

```markdown
---
bump: minor
section: Added
---

Describe the consumer-visible change in one concise paragraph.
```

`bump` is `patch`, `minor`, or `major`. `section` is one of `Added`, `Changed`,
`Deprecated`, `Removed`, `Fixed`, or `Security`. The version pull request
consumes these files into `CHANGELOG.md`.

When the next version must be an explicit PEP 440 candidate or final promotion,
add a one-line `.release-notes/next-version` file such as `0.6.0rc1` or `0.6.0`.
The version PR consumes that override together with the pending records.
