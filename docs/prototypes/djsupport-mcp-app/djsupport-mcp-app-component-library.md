---
classification: concept
artifact: MCP App component library contract
---

# DJ Support MCP App: component library

This library turns the validated playlist journey into reusable UI rules. The Pencil file is the visual prototype; this document records the durable intent that implementation should preserve.

## Design intent

- Prefer compact inline cards. A surface grows only when the user must browse or compare several items.
- Give each surface one obvious next action.
- Describe user-visible outcomes instead of exposing domain or implementation terminology.
- Build confidence with observable promises: what Spotify will be checked for, what will change, and what the user can verify afterward.
- Use color to communicate state, not decoration.

## Semantic tokens

| Role | Prototype token | Meaning |
| --- | --- | --- |
| Canvas | `surface.canvas` | Chat-adjacent background |
| Card | `surface.card` | Primary inline app surface |
| Supporting surface | `surface.subtle` | Explanations, rows, and secondary regions |
| Primary text | `text.primary` | Headings, decisions, and important values |
| Secondary text | `text.secondary` | Explanations and metadata |
| Muted text | `text.muted` | Labels and tertiary context |
| Primary action | `action.primary` | The single next action |
| Success | `success.*` | Selected, ready, matched, or completed |
| Attention | `attention.*` | A choice still needs the user |
| Border | `border.subtle` | Quiet separation without extra chrome |

The prototype uses Inter, 7 px control corners, 12 px card corners, and pill corners for short statuses.

## Reusable component inventory

### Context and actions

- `Context / Tool Label` — identifies DJ Support and states what it just did.
- `Action / Primary` — the one dark next action.
- `Action / Secondary` — a quiet alternative such as Back.
- `Status / Success` — short achieved or selected state.
- `Status / Attention` — short state requiring a choice.
- `Status / Neutral` — supporting state such as privacy.

### Feedback and data

- `Notice / Success` — confirms a completed, verifiable outcome.
- `Notice / Information` — explains a boundary before an action.
- `Metric / Success` — count of songs confidently matched or added.
- `Metric / Attention` — count of songs requiring a choice.
- `Metric / Neutral` — total or supporting count.

### Content and composition

- `List / Playlist Row — Default` — selectable playlist summary.
- `List / Playlist Row — Selected` — selected playlist with an explicit state.
- `Track / Spotify Version Candidate` — listening, metadata, and selection for one Spotify version.
- `Review / Choice` — a plain-language decision with enough detail to distinguish versions.
- `Card / Inline Shell` — common MCP App structure with context, header, content, and action regions.

## Composition rules

1. Start with `Card / Inline Shell` at the smallest surface that fits the task.
2. Use a direct, outcome-focused heading and one explanatory sentence.
3. Add only the content needed for the current decision.
4. Put supporting or reversible actions before the primary action.
5. Use exactly one primary action per surface.
6. Use green only for achieved or selected states, amber only when input is needed, and grey for context.
7. Before changing Spotify, show the exact playlist name, privacy, song count, omissions, order, and one-time permission boundary.

## Surface sizes

- Compact: 720 px wide for upload, progress, confirmation, follow-up, and success.
- Medium: 920 px wide when the user browses playlists.
- Wide: 920 px wide when comparing Spotify versions inline.
- Large: 1040 px wide only for the multi-song review workspace.

These are prototype dimensions, not viewport requirements. The MCP host should preserve the hierarchy and allow the card to adapt to available inline width.

## Validation

On 2026-08-16, the Pencil document contained 16 reusable components. The component-library frame and the full 10-screen journey passed Pencil layout validation with no clipping or overflow problems.
