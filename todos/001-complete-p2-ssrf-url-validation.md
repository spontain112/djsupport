---
status: complete
priority: p2
issue_id: "001"
tags: [code-review, security]
dependencies: []
---

# SSRF via Loose URL Validation

## Problem Statement

The `_detect_url_type()` function in `web.py` checks for substring presence (`"beatport.com/chart/" in url`) without anchoring to the actual hostname. A crafted URL like `http://internal-service.local/beatport.com/chart/exploit` would pass validation and cause the server to make a request to an attacker-controlled or internal host. The frontend mirrors this loose check.

**Known Pattern:** Past XSS/security fixes documented in `docs/solutions/security-issues/web-frontend-xss-and-type-safety-fixes.md`.

## Findings

- **Security Sentinel:** Identified as the most actionable finding. Substring-based URL matching is not anchored to the domain.
- **Location:** `web.py:114-124` (`_detect_url_type`), `index.html:524-531` (frontend mirror)
- **Risk:** SSRF if the tool is ever exposed beyond localhost.

## Proposed Solutions

### Option A: Use `urlparse` to validate hostname (Recommended)
```python
from urllib.parse import urlparse

def _detect_url_type(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname not in ("beatport.com", "www.beatport.com"):
        raise ValueError("URL must be a Beatport URL")
    if "/chart/" in parsed.path:
        return "chart"
    if "/label/" in parsed.path:
        return "label"
    raise ValueError("URL must be a Beatport chart or label URL")
```
- **Pros:** Properly anchors validation, prevents SSRF
- **Cons:** None
- **Effort:** Small
- **Risk:** Low

## Recommended Action

## Technical Details
- **Affected files:** `djsupport/web.py`, `djsupport/static/index.html`

## Acceptance Criteria
- [ ] URL validation uses `urlparse` to check hostname
- [ ] Frontend validation updated to match (or relaxed to just check `beatport.com` domain)
- [ ] Malicious URLs like `http://evil.com/beatport.com/chart/x` are rejected

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|

## Resources
- Security Sentinel agent report
- `docs/solutions/security-issues/web-frontend-xss-and-type-safety-fixes.md`
