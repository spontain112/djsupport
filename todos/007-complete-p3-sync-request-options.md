---
status: complete
priority: p3
issue_id: "007"
tags: [code-review, architecture]
dependencies: []
---

# Web API Lacks Sync Configuration Options

## Problem Statement

The `POST /sync` endpoint only accepts `{"url": "..."}`. The CLI supports `--threshold`, `--dry-run`, `--prefix`, `--retry`, etc. An agent or power user cannot control these via the web API.

## Findings

- **Agent-Native Reviewer:** 0/6 CLI configuration options are API-accessible. Flagged as critical for agent parity.
- **Architecture Strategist:** Noted as deliberate scope limitation, not a bug.
- **Location:** `web.py:110-113` (`SyncRequest` model)

## Proposed Solutions

### Option A: Extend SyncRequest with optional fields
```python
class SyncRequest(BaseModel):
    url: str
    threshold: int = 80
    dry_run: bool = False
    prefix: str | None = "djsupport"
    retry: bool = False
```
- **Effort:** Medium
- **Risk:** Low — all fields optional with existing defaults

## Technical Details
- **Affected files:** `djsupport/web.py`

## Acceptance Criteria
- [ ] `SyncRequest` accepts threshold, dry_run, prefix, retry
- [ ] Defaults match CLI behavior
- [ ] Frontend can optionally expose controls (separate task)

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
