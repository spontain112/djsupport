---
status: complete
priority: p3
issue_id: "003"
tags: [code-review, quality]
dependencies: []
---

# Hardcoded Color Values Outside CSS Custom Properties

## Problem Statement

Two CSS rules use raw hex colors instead of the established CSS custom properties, creating theme inconsistency.

## Findings

- **Python Reviewer:** Lines 347 (`#333`) and 353 (`#94A3B8`) bypass the CSS variable system.
- **Location:** `index.html:347` and `index.html:353`

## Proposed Solutions

### Option A: Replace with existing variables (Recommended)
- `#333` -> `var(--border)` (which is `#2A2A2E`, close enough)
- `#94A3B8` -> `var(--score-text)` (which is `#9CA3AF`, nearly identical)
- **Effort:** Small
- **Risk:** None

## Technical Details
- **Affected files:** `djsupport/static/index.html`

## Acceptance Criteria
- [ ] No raw hex values outside `:root` CSS variables block

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
