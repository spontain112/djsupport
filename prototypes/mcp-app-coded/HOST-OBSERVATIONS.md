---
classification: concept
artifact: MCP Apps host observations for issue 185
status: local-harness-verified
---

# Host observations

## Evidence boundary

The automated observations below come from the committed local host harness,
not ChatGPT. They prove the component's MCP Apps handshake and UI behavior in a
controlled iframe. Rows under **ChatGPT developer mode** must be filled only
after observing the real supported host through Secure MCP Tunnel.

## Local harness

| Question | Observed result |
| --- | --- |
| Bridge | `ui/initialize` completes before `ui/notifications/initialized`; the host sends the render result; four later actions use `tools/call` without remounting. |
| Model-visible data | Each tool returns a complete, generated `structuredContent` snapshot plus useful text. |
| UI-only data | The radio choice stays local until `select_playlist`; diagnostic facts are returned in result `_meta`. |
| File selection | `window.openai.selectFiles` is feature-detected but never called. No file bytes, path, file ID, or picker result enters the component or server. |
| State | The server owns the revisioned in-memory snapshot. UI selection is ephemeral and optionally copied to widget-scoped `privateContent`; neither is durable. |
| Remount | A newly mounted local harness creates a new journey. Re-rendering an existing live `journeyId` returns its server snapshot. |
| Navigation | No internal route or nested frame exists. All five surfaces render within one iframe instance. |
| Presentation modes | The component advertises inline and fullscreen support. The playlist surface requests `ui/request-display-mode`; the harness confirms the request/response and keeps journey authority unchanged. |
| Keyboard and focus | Native buttons and radios work with Enter/Space; each authoritative screen change focuses its heading; errors focus the alert. |
| Loading, empty, and error | Initial host-result latency shows a waiting state; an empty generated list has an explicit disabled state; tool calls mark the card busy; a rejected call shows a bounded alert without changing the screen. |
| Reduced width | The 320 px harness keeps content within the iframe; metrics and actions stack vertically. |
| Network and resources | The component performs no fetch, XHR, WebSocket, image, font, media, or nested-frame request. The diagnostic parent alone calls its loopback server. |
| CSP | UI metadata declares `connectDomains: []` and `resourceDomains: []`; permissions, dedicated domain, and nested-frame origins are omitted. |
| No-UI fallback | MCP integration tests complete the full journey from tool results alone. |
| Inline sequence | The harness deliberately keeps five bounded surfaces in one mounted component. Current guidance discourages multiple views in inline cards, so this is a test condition rather than a production verdict. |

Exact local dimensions and request origins are generated in
[`captures/local-harness-observations.json`](captures/local-harness-observations.json).

## ChatGPT host-access preflight

On 2026-08-19, the signed-in ChatGPT Plugins surface exposed the supported
**Create app** flow and its **Tunnel** connection route. The tunnel selector
reported **No tunnels yet** and linked to the OpenAI Platform organization
tunnel settings. That settings surface required a separate Platform sign-in,
so no tunnel, app connection, or external endpoint was created.

This is access evidence only. It does not count as a real-host component run,
and none of the pending observations below are inferred from it.

## ChatGPT developer mode

| Question | Observation |
| --- | --- |
| Connection route and host version | The Tunnel route is present, but no tunnel is available; host-version behavior remains pending a real-host run. |
| Compact inline dimensions | Pending real-host run. |
| Expanded/available display modes | Pending real-host run; the component advertises inline and fullscreen for this slice. |
| Optional file-selection capability | Pending feature-detection observation; it will not be invoked. |
| Widget-state restoration after remount | Pending real-host run. |
| Navigation away and back | Pending real-host run. |
| Reuse from a later turn | Pending real-host run. |
| Console or CSP errors | Pending real-host run. |
| Inline multi-view verdict | Pending real-host run; decide between separate tool-rendered cards and entering fullscreen for the multi-step portion. |

No production or privacy claim depends on a pending row.
