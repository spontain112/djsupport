---
status: complete
priority: p3
issue_id: "002"
tags: [code-review, quality]
dependencies: []
---

# Dead `currentJobId` Variable

## Problem Statement

The `currentJobId` variable in `index.html` is assigned on line 573 and cleared in `resetUI()` but never read anywhere. It is dead code that adds confusion.

## Findings

- **Python Reviewer:** Flagged as dead code — set but never used.
- **Code Simplicity Reviewer:** Confirmed as YAGNI violation.
- **Location:** `index.html` lines 483, 573, 732

## Proposed Solutions

### Option A: Remove it (Recommended)
Delete all 3 references (`let currentJobId = null`, `currentJobId = data.job_id`, `currentJobId = null`).
- **Effort:** Small
- **Risk:** None

### Option B: Keep for future cancel button
Add a comment explaining intent. Only if cancel support is planned.
- **Effort:** Small
- **Risk:** Keeps dead code around

## Technical Details
- **Affected files:** `djsupport/static/index.html`

## Acceptance Criteria
- [ ] `currentJobId` removed or documented with clear future intent

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
