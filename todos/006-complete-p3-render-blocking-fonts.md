---
status: complete
priority: p3
issue_id: "006"
tags: [code-review, performance]
dependencies: []
---

# Google Fonts Are Render-Blocking

## Problem Statement

The Google Fonts CSS link blocks initial page render, adding 200-800ms to first contentful paint. Also breaks font loading entirely when offline.

## Findings

- **Performance Oracle:** Flagged as critical performance issue for page load.
- **Location:** `index.html:7-9`

## Proposed Solutions

### Option A: Make non-render-blocking with media trick
```html
<link href="..." rel="stylesheet" media="print" onload="this.media='all'">
```
- **Effort:** Small
- **Risk:** Brief FOUT (flash of unstyled text)

### Option B: Self-host fonts in static/
Download IBM Plex Mono and Inter, serve from `/static/fonts/`. Eliminates CDN dependency.
- **Effort:** Medium
- **Risk:** None — but increases repo size

## Technical Details
- **Affected files:** `djsupport/static/index.html`, optionally `djsupport/static/fonts/`

## Acceptance Criteria
- [ ] Fonts do not block initial page render
- [ ] Page is usable while fonts load

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
