---
classification: concept
artifact: DJ Support MCP Apps coded host-validation prototype
issue: https://github.com/spontain112/djsupport/issues/185
---

# DJ Support MCP Apps coded prototype

This is the permanent throwaway implementation for issue #185. It exercises a
five-screen, fully synthetic DJ Support journey through a real streamable HTTP
MCP server and the MCP Apps `postMessage` bridge. It is evidence, not production
DJ Support code.

Keep this work on `t185/mcp-app-coded-prototype`. Do not open a pull request to
`main`, publish the component, add a release-note record, or connect it to the
public `Transfer` interface. The server reads no Rekordbox file, contacts no
provider, stores nothing durably, and performs no Spotify mutation.

## What runs

The prototype exposes three tools:

- `start_synthetic_playlist_check` creates an in-memory journey and returns a
  complete model-readable snapshot with no UI dependency.
- `advance_synthetic_playlist_check` validates one revision-bound transition
  and returns the next complete snapshot.
- `render_synthetic_playlist_check` returns the MCP App resource for an existing
  journey. Only this render tool advertises `_meta.ui.resourceUri`.

The component initializes the standard MCP Apps bridge, receives
`ui/notifications/tool-result`, and uses `tools/call` for later actions. Every
dynamic field is treated as untrusted and written with DOM text APIs. The
resource declares empty `connectDomains` and `resourceDomains` arrays, embeds
all CSS and JavaScript, requests no permissions, and loads no nested frame.

## Run locally

Node.js 20 or newer is required.

```bash
npm ci --ignore-scripts
npm run check
npm start
```

The server prints a JSON line containing the loopback `/mcp` endpoint and the
local diagnostic harness. It binds only to `127.0.0.1`. The harness simulates a
standards-conforming host so the bridge can be tested and captured without a
ChatGPT account; it is not evidence of ChatGPT behavior.

For the browser checks and captures, point `CHROME_PATH` at a locally installed
Chromium-compatible browser:

```bash
CHROME_PATH=/path/to/chrome npm test
CHROME_PATH=/path/to/chrome npm run capture
```

MCP Inspector can list and call the server tools directly. For ChatGPT host
validation, follow OpenAI's [Connect and test your plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt)
guide and use Secure MCP Tunnel rather than publishing this prototype. Start
with `start_synthetic_playlist_check`, then call
`render_synthetic_playlist_check` using the returned `journeyId`.

## Boundary findings encoded in the slice

- **Synthetic source choice:** the first action chooses a generated source fact;
  it never opens a file picker. The component feature-detects the optional
  `window.openai.selectFiles` extension for evidence but never invokes it.
- **Model-visible state:** `structuredContent` contains only the synthetic
  journey revision, current screen, generated playlists, selected playlist,
  and result counts. The accompanying text remains useful in a client that
  renders no UI.
- **UI-only detail:** tool-result `_meta.djsupportPrototype` records component
  diagnostics; it is not model-visible. The selected radio is presentation
  state until the component calls the server tool.
- **Remount and later turns:** server state survives only while this process is
  alive and can be re-rendered from the opaque synthetic `journeyId`. Optional
  `window.openai` widget state may restore the radio choice within one rendered
  UI instance; it is never authoritative. A server restart intentionally makes
  the journey unknown.
- **Future production seam:** a separately approved adapter may translate an
  authorized user selection into a call to the existing public `Transfer`
  interface and return a versioned snapshot. The component remains a renderer
  and intent collector; it does not gain Transfer policy or storage authority.

The real ChatGPT host observations—actual container dimensions, extension
availability, remount/navigation behavior, and later-turn behavior—belong in
[`HOST-OBSERVATIONS.md`](HOST-OBSERVATIONS.md). Do not infer them from the local
harness.

## Inline host question

This coded slice deliberately keeps the bounded five-surface sequence in one
mounted component so remount and server-authority behavior can be observed.
Current OpenAI UI guidance discourages multiple views inside an inline card;
this test condition is not a production recommendation. The real-host verdict
must decide whether production splits the sequence across tool-rendered cards
or enters fullscreen before the multi-step portion.

## Language boundary

The slice uses the accepted issue #185 presentation language: **Rekordbox
playlist file**, **Selected playlist**, **Playlist entry**, **Check Spotify**,
**Find matches**, **Suggested Spotify match**, **Likely match**, **Needs
review**, **No match yet**, **Same Spotify track suggested twice**, and
**Spotify unchanged**. The final surface says exactly:

- `28 likely matches`
- `4 need review`
- `2 no match yet`
- `Review 6 songs`

The disabled final action notes that later review must keep **Wait for Spotify**
and **Stop looking** separate. **Try again** and **Start looking again** remain
reserved for that later flow. This prototype does not implement issue #184.

## Dependency containment

`node_modules/` and local logs are ignored because they are reproducible or
diagnostic. `package-lock.json`, the six screenshots, and the observation
manifest are tracked. This prototype has its own
[`THIRD_PARTY.md`](THIRD_PARTY.md) because none of its JavaScript dependencies
ship in the Python package or belong on `main`.
