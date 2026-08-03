# Simplest Chrome-to-DJ Support product boundary

**Date:** 2026-08-01

**Status:** Planning research only. No production code, live service call, private
music data, or Chrome-project file was changed.

## Decision in one sentence

For the single-user product, the simplest credible path is **Chrome as a
one-click capture and status surface, backed by the existing loopback web app
and the durable `Transfer` authority**; open the local web UI only when setup,
review, recovery, or richer management needs more room. Later, a packaged
native launcher can remove the terminal/startup step without moving product
policy into Chrome.

The ordinary extension click means “make this playlist now.” It does not imply
“follow this source,” “save for later,” or “make this a Mirror.” Those remain
separate future intents.

## Why this is the smallest coherent shape

DJ Support already has most of the local application boundary needed for the
journey: a FastAPI adapter creates a durable Transfer ID before background
execution, exposes resumable progress and result routes, and delegates to
`Transfer` ([web adapter](../../djsupport/web.py#L113-L206), [progress and
resume](../../djsupport/web.py#L208-L255)). Its current web UI already checks
Spotify connection, posts a Beatport URL, persists the active Transfer ID,
reattaches after reload, streams progress, and opens the finished Spotify
playlist ([web UI](../../djsupport/static/index.html#L507-L539), [start and
progress](../../djsupport/static/index.html#L573-L652), [completion](../../djsupport/static/index.html#L660-L690)).

The core boundary is explicit: adapters supply a `TransferRequest`, while
`Transfer` owns matching, persistence ordering, Preview policy, and publication
([Transfer seam](../../djsupport/transfer.py#L1-L6), [request](../../djsupport/transfer.py#L90-L105)).
Private retained state already belongs in platform application data rather than
the repository ([storage path](../../djsupport/transfer.py#L63-L71)).

The Chrome project supplies the complementary interaction: its content script
recognizes the current Beatport page and handles single-page navigation
([content script](https://github.com/spontain112/djsupport-chrome/blob/e26bdcacdbe6d66725fad489ff29690e42dea808/src/entrypoints/content.ts#L8-L38));
the side panel turns that context into a short ready-to-progress journey
([side-panel state](https://github.com/spontain112/djsupport-chrome/blob/e26bdcacdbe6d66725fad489ff29690e42dea808/src/entrypoints/sidepanel/App.tsx#L5-L49),
[one main action](https://github.com/spontain112/djsupport-chrome/blob/e26bdcacdbe6d66725fad489ff29690e42dea808/src/entrypoints/sidepanel/App.tsx#L172-L213)).
But its service worker currently owns a second cache, matcher, Spotify login,
and playlist writer ([background](https://github.com/spontain112/djsupport-chrome/blob/e26bdcacdbe6d66725fad489ff29690e42dea808/src/entrypoints/background.ts#L1-L8),
[matching](https://github.com/spontain112/djsupport-chrome/blob/e26bdcacdbe6d66725fad489ff29690e42dea808/src/entrypoints/background.ts#L82-L170),
[publication](https://github.com/spontain112/djsupport-chrome/blob/e26bdcacdbe6d66725fad489ff29690e42dea808/src/entrypoints/background.ts#L173-L181)).
That is the duplication to retire, not the interaction to discard.

## Options compared

| Option | Setup and lifecycle | Auth/security | UX and evolution | Verdict |
| --- | --- | --- | --- | --- |
| **A. Full extension GUI + local DJ Support service** | Still requires installing and starting the local service; additionally duplicates a large UI and reconnect logic inside an extension service-worker lifecycle. | Can centralize Spotify tokens in the service, but adds a privileged extension-to-loopback API surface. | Keeps everything in the side panel, yet every richer Transfer/recovery capability needs two presentation adapters. | Credible, but not simplest. Use the panel only for small status and actions. |
| **B. Chrome capture/status + existing local web UI** | Smallest current delta: the service and web UI already exist. The initial single-user version can require `djsupport web`; later packaging can hide startup. | One local authority can own OAuth tokens and Spotify mutation. Bind to `127.0.0.1`, accept only a narrow source-intent request, validate the expected extension origin, and require a per-install pairing secret. | Preserves the in-context click and feedback; opens the web UI only for connect/setup, exceptions, review, or recovery. It naturally grows into the full non-terminal GUI. | **Recommended now.** |
| **C. Browser-only extension with duplicated logic** | One extension install and no companion process is superficially easiest. Store distribution can auto-update it. | It currently stores a Spotify refresh token in extension-local storage ([token storage](https://github.com/spontain112/djsupport-chrome/blob/e26bdcacdbe6d66725fad489ff29690e42dea808/src/lib/spotify-auth.ts#L174-L214)) and directly performs mutations. | Fast current journey, but matching knowledge, publication, recovery, and policy diverge from durable Transfer. Migration gets harder with every capability. | Reject as the product architecture. It is a useful interaction reference only. |
| **D. Native-messaging launcher/bridge + local web UI** | Chrome can launch a native host per message or keep one alive, removing the manual server-start step. However, each OS needs host registration (manifest paths on macOS/Linux; registry on Windows) and an installed executable. | Native-host manifests allowlist exact extension origins; the protocol should still accept only a validated source and explicit intent. | Best eventual “click and it works” local-app experience while retaining one web GUI and Transfer authority. | **Best packaging evolution, not the first slice.** |

## Platform facts that constrain the choice

- Extension pages and service workers may make cross-origin requests only with
  matching host permissions; content scripts remain subject to the page's
  origin. A loopback integration should therefore use the extension worker and
  a narrow `http://127.0.0.1/...` host permission, not arbitrary hosts
  ([Chrome cross-origin requests](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests)).
- Chrome is also evolving Local Network Access controls and classifies loopback
  as local-network access. A loopback bridge remains viable, but it must be
  tested against current stable Chrome and should not be treated as permanently
  friction-free browser transport ([Chrome Local Network Access](https://developer.chrome.com/blog/local-network-access),
  [loopback transition note](https://developer.chrome.com/blog/pna-permission-prompt-ot-end)).
- Native Messaging requires the `nativeMessaging` permission and an installed
  host manifest. `sendNativeMessage()` starts a process for one response;
  `connectNative()` keeps the process alive until its port closes. Host manifests
  allowlist exact `chrome-extension://<id>/` origins
  ([Chrome Native Messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging),
  [permission warning](https://developer.chrome.com/docs/extensions/reference/permissions-list)).
- Loading an unpacked extension is adequate for this owner's experiment. A
  broadly simple install eventually means Chrome Web Store distribution;
  self-hosted installation on Windows and macOS is restricted to enterprise
  policy. Store updates require a version bump, upload, and review
  ([Chrome distribution](https://developer.chrome.com/docs/extensions/how-to/distribute),
  [update lifecycle](https://developer.chrome.com/docs/extensions/develop/concepts/extensions-update-lifecycle),
  [Web Store update](https://developer.chrome.com/docs/webstore/update/)).
- Spotify recommends Authorization Code with PKCE where a client secret cannot
  be safely stored, including browser and desktop clients. Loopback redirects
  must use an explicit IP such as `http://127.0.0.1:PORT`; `localhost` is not
  allowed under the current redirect rules
  ([Spotify authorization](https://developer.spotify.com/documentation/web-api/concepts/authorization),
  [PKCE](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow),
  [redirect URIs](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri)).
  This reinforces keeping one OAuth owner in the local app instead of keeping
  the extension's separate token lifecycle.

## Recommended staged product

### Stage 1 — prove the boundary for the owner

Keep the unpacked extension. On a supported Beatport page, its ordinary click
sends only the canonical page URL and explicit “start Snapshot now” intent to a
loopback endpoint. DJ Support validates and re-reads the source, prepares the
Transfer, and returns a durable Transfer ID. The panel shows detected source,
progress, paused/error state, and “Open in Spotify” on straightforward
completion. “Open DJ Support” hands setup, Spotify connection, exceptions,
review, and recovery to the existing web UI.

Do not send the extension's parsed track list as authority. It may use locally
observed title/count as provisional feedback, but the Transfer must establish
the source facts it will publish. Do not expose arbitrary URL fetching,
commands, filesystem paths, or Spotify credentials through the bridge.

Before calling even this owner-only slice complete, decide and test: fixed
loopback address/port discovery, extension pairing/rotation, expected-Origin
checks, no permissive CORS, URL allowlisting, service-unavailable guidance, and
reattachment by Transfer ID after panel/browser closure. These are planning
gates, not implementation authorization.

### Stage 2 — remove terminal setup

Package DJ Support as a small first-party local application that installs and
starts the web service, opens the setup UI, and owns updates/data migration.
Only after that installer exists, add a Native Messaging launcher/bridge so an
extension click can wake the app when it is not running. Native messaging is
the cleaner eventual launcher, but implementing its OS-specific registration
before the product boundary is proven would front-load packaging work.

### Stage 3 — let the web UI become the GUI

Grow the local web UI—not the extension—into the non-terminal home for Transfer
history, Rekordbox selection, Approval/Correction, recovery, and later explicit
following or enrichment workflows. Keep Chrome specialized around the moment
of browser discovery. A future mobile or other-site capture adapter can then
use the same narrow intake contract without becoming another policy authority.

## Decision tickets for the Wayfinder frontier

1. **Define the browser capture contract:** exact supported URL kinds, explicit
   Snapshot-now intent, provisional display facts, idempotency, and response.
2. **Choose the owner-only pairing and reconnect model:** fixed or discovered
   loopback port, secret lifecycle, expected extension ID/origin, Transfer-ID
   persistence, and failure copy.
3. **Define the handoff rule:** which completed states remain in the panel and
   which review/setup/recovery states open the local web UI.
4. **Choose the no-terminal release gate:** whether a first-party installer and
   auto-start are required before calling the workflow generally usable.
5. **Research native-host packaging only after that gate:** macOS, Windows, and
   Linux registration/update/uninstall behavior, without changing Transfer's
   authority.

This recommendation deliberately does not revive the dropped standalone
Mirror/Drift UX study or PR #76. It asks a broader product question: how can the
browser remain the easiest doorway while the local application becomes the one
durable place where DJ Support works?
