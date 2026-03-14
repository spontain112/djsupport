---
status: complete
priority: p3
issue_id: "004"
tags: [code-review, quality]
dependencies: []
---

# Consolidate Duplicated URL Validation Branches

## Problem Statement

The frontend URL validation has two near-identical branches for chart vs. label detection (lines 524-537). Only the hint text differs. This is a copy-paste drift risk.

## Findings

- **Code Simplicity Reviewer:** Most impactful clarity improvement. ~6 LOC reduction.
- **Python Reviewer:** Flagged as maintenance coupling with backend's `_detect_url_type`.
- **Architecture Strategist:** Noted as acceptable dual validation but drift risk.

## Proposed Solutions

### Option A: Single branch with ternary (Recommended)
```javascript
const isChart = url.includes('beatport.com/chart/');
const isLabel = url.includes('beatport.com/label/');
if (isChart || isLabel) {
    urlHint.textContent = isChart ? 'DETECTED: BEATPORT CHART' : 'DETECTED: BEATPORT LABEL';
    // ... shared logic
} else { ... }
```
- **Effort:** Small
- **Risk:** None

## Technical Details
- **Affected files:** `djsupport/static/index.html`

## Acceptance Criteria
- [ ] Chart and label detection share a single code path
- [ ] Redundant `&& data.detail` check on line 615 also simplified

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
