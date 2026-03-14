---
status: complete
priority: p3
issue_id: "005"
tags: [code-review, performance]
dependencies: []
---

# Replace DOM-Based `esc()` with String Replacement

## Problem Statement

The `esc()` XSS helper creates a temporary DOM element for every call. At 100+ tracks, this creates 300+ temporary DOM nodes during result rendering, causing unnecessary GC pressure.

## Findings

- **Performance Oracle:** ~10x faster with string replacement approach. Measurable at 100+ tracks on mobile.
- **Location:** `index.html:487-491`

## Proposed Solutions

### Option A: Pure string replacement (Recommended)
```javascript
function esc(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
```
- **Effort:** Small
- **Risk:** Low — well-established XSS escaping pattern

## Technical Details
- **Affected files:** `djsupport/static/index.html`

## Acceptance Criteria
- [ ] `esc()` uses string replacement instead of DOM allocation
- [ ] All existing XSS protections maintained

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
