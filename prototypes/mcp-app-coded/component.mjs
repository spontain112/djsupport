const STYLES = String.raw`
:root {
  color-scheme: light dark;
  font-family: var(--font-sans, Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif);
  --canvas: var(--color-background-secondary, #f7f7f5);
  --card: var(--color-background-primary, #ffffff);
  --subtle: var(--color-background-tertiary, #f3f3f1);
  --text: var(--color-text-primary, #1a1a1a);
  --secondary: var(--color-text-secondary, #666666);
  --muted: var(--color-text-tertiary, #666666);
  --border: var(--color-border-secondary, #e5e5e5);
  --action: var(--color-background-inverse, #252525);
  --action-text: var(--color-text-inverse, #ffffff);
  --success: var(--color-text-success, #327a56);
  --success-bg: var(--color-background-success, #eaf4ed);
  --success-border: var(--color-border-success, #bfd8c8);
  --attention: var(--color-text-warning, #8a5a13);
  --attention-bg: var(--color-background-warning, #fff4de);
  --radius-control: var(--border-radius-sm, 7px);
  --radius-card: var(--border-radius-lg, 12px);
}

* { box-sizing: border-box; }

html, body { margin: 0; min-width: 0; background: transparent; color: var(--text); }
body { padding: 8px; }
button, input { font: inherit; }

.app { width: 100%; min-width: 0; }
.card {
  width: 100%;
  min-width: 0;
  overflow: hidden;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-sm, 0 2px 10px rgb(0 0 0 / 0.06));
}
.context {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 12px 18px;
  border-bottom: 1px solid var(--border);
  color: var(--secondary);
  font-size: 13px;
}
.context-copy { min-width: 0; color: var(--muted); }
.content { padding: 22px; }
.eyebrow {
  margin: 0 0 8px;
  color: var(--success);
  font-size: 11px;
  font-weight: 750;
  letter-spacing: 0.07em;
  text-transform: uppercase;
}
h1 { margin: 0; font-size: clamp(22px, 5vw, 28px); line-height: 1.15; font-weight: 560; letter-spacing: -0.025em; }
h1:focus { outline: none; }
.lede { margin: 7px 0 0; color: var(--secondary); font-size: 14px; line-height: 1.5; }
.file-card {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 20px;
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  background: var(--subtle);
}
.file-copy, .playlist-copy { min-width: 0; flex: 1; }
.file-name, .playlist-name { overflow-wrap: anywhere; font-weight: 650; }
.meta { margin-top: 3px; color: var(--muted); font-size: 12px; }
.notice, .error {
  display: flex;
  gap: 9px;
  margin-top: 16px;
  padding: 11px 12px;
  border-radius: var(--radius-control);
  background: var(--subtle);
  color: var(--secondary);
  font-size: 12px;
  line-height: 1.45;
}
.error { border: 1px solid #d38b86; background: #fff0ef; color: #7f2e28; }
.actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
.button {
  min-height: 40px;
  padding: 9px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  background: var(--card);
  color: var(--text);
  cursor: pointer;
  font-weight: 620;
}
.button.primary { border-color: var(--action); background: var(--action); color: var(--action-text); }
.button:disabled { cursor: not-allowed; opacity: 0.58; }
.button:focus-visible, .playlist-row:has(input:focus-visible) {
  outline: 3px solid color-mix(in srgb, var(--success) 45%, transparent);
  outline-offset: 2px;
}
.progress-shell { margin: 26px 0 6px; height: 8px; overflow: hidden; border-radius: 99px; background: var(--border); }
.progress-value { width: 100%; height: 100%; border-radius: inherit; background: var(--success); }
.progress-label { color: var(--success); text-align: center; font-size: 13px; font-weight: 650; }
.playlist-list { display: grid; gap: 1px; margin-top: 18px; overflow: hidden; border: 1px solid var(--border); border-radius: var(--radius-control); background: var(--border); }
.playlist-row { display: flex; gap: 12px; align-items: center; padding: 15px 16px; background: var(--card); cursor: pointer; }
.playlist-row.selected { box-shadow: inset 3px 0 var(--success); background: var(--success-bg); }
.playlist-row input { width: 18px; height: 18px; margin: 0; accent-color: var(--success); }
.selection { margin-top: 16px; color: var(--success); font-size: 13px; font-weight: 650; }
.facts { display: grid; gap: 0; margin-top: 18px; border-top: 1px solid var(--border); }
.fact { display: flex; justify-content: space-between; gap: 18px; padding: 11px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
.fact dt { color: var(--secondary); }
.fact dd { margin: 0; text-align: right; font-weight: 650; }
.status {
  display: inline-flex;
  align-items: center;
  margin-left: auto;
  padding: 5px 9px;
  border-radius: 99px;
  background: var(--success-bg);
  color: var(--success);
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}
.metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 18px; }
.metric { min-width: 0; padding: 16px 14px; border-radius: 9px; background: var(--subtle); }
.metric.success { background: var(--success-bg); color: var(--success); }
.metric.attention { border: 1px solid #e8c477; background: var(--attention-bg); color: var(--attention); }
.metric strong { display: block; font-size: 25px; line-height: 1; }
.metric span { display: block; margin-top: 8px; overflow-wrap: anywhere; font-size: 12px; font-weight: 620; }
.later { margin: 14px 0 0; color: var(--secondary); font-size: 12px; line-height: 1.45; }
.loading { padding: 28px; color: var(--secondary); text-align: center; }

@media (max-width: 440px) {
  body { padding: 4px; }
  .context { align-items: center; padding: 11px 13px; }
  .content { padding: 17px 14px; }
  .file-card { align-items: flex-start; flex-direction: column; padding: 14px; }
  .metrics { grid-template-columns: 1fr; }
  .actions { align-items: stretch; flex-direction: column; }
  .actions .button { width: 100%; }
  .status { margin: 0 0 0 auto; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; }
}
`;

function bootComponent(protocolVersion) {
  const root = document.getElementById("app");
  const pending = new Map();
  const screens = new Set(["choose_file", "preparing", "choose_playlist", "confirm_check", "match_results"]);
  let requestId = 1;
  let snapshot = null;
  let selectedPlaylistId = null;
  let busy = false;
  let errorMessage = null;
  let initialized = false;
  let hostContext = { displayMode: "inline", availableDisplayModes: ["inline"] };

  document.documentElement.dataset.hostFilePicker = typeof window.openai?.selectFiles === "function" ? "available" : "unavailable";

  function node(tag, options = {}, children = []) {
    const element = document.createElement(tag);
    if (options.className) element.className = options.className;
    if (options.text !== undefined) element.textContent = String(options.text);
    if (options.type) element.type = options.type;
    if (options.role) element.setAttribute("role", options.role);
    if (options.ariaLabel) element.setAttribute("aria-label", options.ariaLabel);
    if (options.tabIndex !== undefined) element.tabIndex = options.tabIndex;
    if (options.disabled) element.disabled = true;
    if (options.name) element.name = options.name;
    if (options.value) element.value = options.value;
    if (options.checked) element.checked = true;
    if (options.onClick) element.addEventListener("click", options.onClick);
    if (options.onChange) element.addEventListener("change", options.onChange);
    for (const [name, value] of Object.entries(options.attributes ?? {})) {
      element.setAttribute(name, String(value));
    }
    for (const child of children) {
      element.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return element;
  }

  function isRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function integer(value) {
    return Number.isSafeInteger(value) && value >= 0 ? value : null;
  }

  function normalizePlaylist(value) {
    if (!isRecord(value)) throw new Error("Invalid playlist result");
    if (!/^playlist-\d{2}$/.test(value.id) || typeof value.name !== "string" || value.name.length > 80) {
      throw new Error("Invalid playlist result");
    }
    const songCount = integer(value.songCount);
    if (songCount === null || typeof value.recency !== "string" || value.recency.length > 80) {
      throw new Error("Invalid playlist result");
    }
    return { id: value.id, name: value.name, songCount, recency: value.recency };
  }

  function normalizeSnapshot(value) {
    if (!isRecord(value) || typeof value.journeyId !== "string" || !value.journeyId.startsWith("synthetic-")) {
      throw new Error("Invalid synthetic journey result");
    }
    const revision = integer(value.revision);
    if (revision === null || !screens.has(value.screen) || value.synthetic !== true || value.spotifyChanged !== false) {
      throw new Error("Invalid synthetic journey result");
    }
    if (!isRecord(value.source) || value.source.kind !== "synthetic_rekordbox_playlist_file" || typeof value.source.displayName !== "string" || value.source.displayName.length > 120) {
      throw new Error("Invalid synthetic source result");
    }
    const playlists = Array.isArray(value.playlists) ? value.playlists.map(normalizePlaylist) : [];
    const selectedPlaylist = value.selectedPlaylist === null || value.selectedPlaylist === undefined
      ? null
      : normalizePlaylist(value.selectedPlaylist);
    let progress = null;
    if (value.progress !== null && value.progress !== undefined) {
      if (!isRecord(value.progress)) throw new Error("Invalid preparation result");
      const found = integer(value.progress.found);
      const total = integer(value.progress.total);
      if (found === null || total === null || found > total) throw new Error("Invalid preparation result");
      progress = { found, total };
    }
    let summary = null;
    if (value.summary !== null && value.summary !== undefined) {
      if (!isRecord(value.summary)) throw new Error("Invalid summary result");
      const likelyMatches = integer(value.summary.likelyMatches);
      const needReview = integer(value.summary.needReview);
      const noMatchYet = integer(value.summary.noMatchYet);
      const reviewSongs = integer(value.summary.reviewSongs);
      if ([likelyMatches, needReview, noMatchYet, reviewSongs].includes(null) || reviewSongs !== needReview + noMatchYet) {
        throw new Error("Invalid summary result");
      }
      summary = { likelyMatches, needReview, noMatchYet, reviewSongs };
    }
    return {
      journeyId: value.journeyId,
      revision,
      screen: value.screen,
      synthetic: true,
      spotifyChanged: false,
      source: { kind: value.source.kind, displayName: value.source.displayName },
      playlists,
      selectedPlaylist,
      progress,
      summary,
    };
  }

  function send(message) {
    window.parent.postMessage(message, "*");
  }

  function request(method, params) {
    const id = requestId++;
    send({ jsonrpc: "2.0", id, method, params });
    return new Promise((resolve, reject) => {
      const timer = window.setTimeout(() => {
        pending.delete(id);
        reject(new Error("Host request timed out"));
      }, 15000);
      pending.set(id, {
        resolve(value) { window.clearTimeout(timer); resolve(value); },
        reject(reason) { window.clearTimeout(timer); reject(reason); },
      });
    });
  }

  function notify(method, params) {
    const message = { jsonrpc: "2.0", method };
    if (params !== undefined) message.params = params;
    send(message);
  }

  function acceptToolResult(result) {
    if (!isRecord(result) || result.isError === true) throw new Error("Tool returned an error");
    snapshot = normalizeSnapshot(result.structuredContent);
    if (snapshot.screen === "choose_playlist") {
      const restored = window.openai?.widgetState?.privateContent?.selectedPlaylistId;
      selectedPlaylistId = snapshot.playlists.some(({ id }) => id === restored)
        ? restored
        : snapshot.playlists[0]?.id ?? null;
    } else if (snapshot.selectedPlaylist) {
      selectedPlaylistId = snapshot.selectedPlaylist.id;
    }
    errorMessage = null;
    render(true);
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window.parent) return;
    const message = event.data;
    if (!isRecord(message) || message.jsonrpc !== "2.0") return;
    if (message.id !== undefined && pending.has(message.id)) {
      const waiting = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) waiting.reject(new Error("Host rejected the request"));
      else waiting.resolve(message.result);
      return;
    }
    if (message.method === "ui/notifications/tool-result") {
      try {
        acceptToolResult(message.params);
      } catch {
        errorMessage = "DJ Support couldn’t read the host result. The synthetic journey stayed unchanged.";
        render(false);
      }
    }
    if (message.method === "ui/notifications/host-context-changed" && isRecord(message.params)) {
      hostContext = { ...hostContext, ...message.params };
      if (typeof message.params.displayMode === "string") document.documentElement.dataset.displayMode = message.params.displayMode;
      const width = message.params.containerDimensions?.width ?? message.params.containerDimensions?.maxWidth;
      if (Number.isFinite(width)) document.documentElement.dataset.hostWidth = String(width);
    }
  }, { passive: true });

  function context(label, withStatus = false) {
    const children = [node("span", { className: "context-copy", text: label })];
    if (withStatus) children.push(node("span", { className: "status", text: "Spotify unchanged" }));
    return node("div", { className: "context" }, children);
  }

  function heading(text) {
    return node("h1", { text, tabIndex: -1 });
  }

  function primaryButton(label, onClick, disabled = false) {
    return node("button", {
      className: "button primary",
      text: busy ? "Working…" : label,
      type: "button",
      disabled,
      onClick,
    });
  }

  function errorNotice() {
    if (!errorMessage) return null;
    return node("div", { className: "error", role: "alert", tabIndex: -1, text: errorMessage });
  }

  async function advance(action, playlistId) {
    if (!snapshot || busy) return;
    busy = true;
    errorMessage = null;
    render(false);
    try {
      const args = {
        journeyId: snapshot.journeyId,
        expectedRevision: snapshot.revision,
        action,
      };
      if (playlistId) args.playlistId = playlistId;
      const result = await request("tools/call", {
        name: "advance_synthetic_playlist_check",
        arguments: args,
      });
      busy = false;
      acceptToolResult(result);
    } catch {
      busy = false;
      errorMessage = "DJ Support couldn’t continue the synthetic check. Try the action again.";
      render(false);
    }
  }

  async function requestDisplayMode(mode) {
    if (busy) return;
    busy = true;
    errorMessage = null;
    let modeChanged = false;
    render(false);
    try {
      const result = await request("ui/request-display-mode", { mode });
      if (!isRecord(result) || !["inline", "fullscreen", "pip"].includes(result.mode)) {
        throw new Error("Invalid display mode result");
      }
      hostContext = { ...hostContext, displayMode: result.mode };
      document.documentElement.dataset.displayMode = result.mode;
      modeChanged = true;
    } catch {
      errorMessage = "This host couldn’t change the component size. The synthetic journey stayed unchanged.";
    } finally {
      busy = false;
      render(false);
      if (modeChanged) root.querySelector('[data-focus-key="display-mode"]')?.focus({ preventScroll: true });
    }
  }

  function chooseFileScreen() {
    const fileCopy = node("div", { className: "file-copy" }, [
      node("div", { className: "file-name", text: snapshot.source.displayName }),
      node("div", { className: "meta", text: "Generated for this host-validation prototype" }),
    ]);
    const content = node("div", { className: "content" }, [
      heading("Start with your Rekordbox playlists"),
      node("p", { className: "lede", text: "Use generated data shaped like a Rekordbox playlist file. No local file is selected or read." }),
      node("div", { className: "file-card" }, [fileCopy, primaryButton("Use synthetic file", () => advance("choose_synthetic_file"), busy)]),
      node("div", { className: "notice", text: "This prototype uses invented playlist entries and will not change Spotify." }),
      errorNotice(),
    ].filter(Boolean));
    return [context("Generated source ready"), content];
  }

  function preparingScreen() {
    const progress = snapshot.progress ?? { found: 0, total: 0 };
    const content = node("div", { className: "content" }, [
      node("p", { className: "eyebrow", text: "Synthetic setup" }),
      heading("Preparing your playlists"),
      node("p", { className: "lede", text: "Checking generated data and finding synthetic playlists. Spotify unchanged." }),
      node("div", {
        className: "progress-shell",
        role: "progressbar",
        ariaLabel: "Playlist preparation complete",
        attributes: { "aria-valuemin": 0, "aria-valuemax": progress.total, "aria-valuenow": progress.found },
      }, [node("div", { className: "progress-value" })]),
      node("div", { className: "progress-label", text: `Found ${progress.found} of ${progress.total} playlists` }),
      node("div", { className: "actions" }, [primaryButton("Choose a playlist", () => advance("show_playlists"), busy)]),
      errorNotice(),
    ].filter(Boolean));
    return [context("Generated playlists prepared"), content];
  }

  function choosePlaylistScreen() {
    const list = node("div", { className: "playlist-list", role: "radiogroup", ariaLabel: "Synthetic playlists" });
    for (const playlist of snapshot.playlists) {
      const selected = selectedPlaylistId === playlist.id;
      const radio = node("input", {
        type: "radio",
        name: "playlist",
        value: playlist.id,
        checked: selected,
        ariaLabel: `${playlist.name}, ${playlist.songCount} songs, ${playlist.recency}`,
        onChange: () => {
          selectedPlaylistId = playlist.id;
          window.openai?.setWidgetState?.({ privateContent: { selectedPlaylistId } });
          render(false);
          [...root.querySelectorAll('input[name="playlist"]')]
            .find((input) => input.value === playlist.id)
            ?.focus({ preventScroll: true });
        },
      });
      list.append(node("label", { className: `playlist-row${selected ? " selected" : ""}` }, [
        radio,
        node("div", { className: "playlist-copy" }, [
          node("div", { className: "playlist-name", text: playlist.name }),
          node("div", { className: "meta", text: `${playlist.songCount} songs · ${playlist.recency}` }),
        ]),
      ]));
    }
    const selected = snapshot.playlists.find(({ id }) => id === selectedPlaylistId) ?? null;
    if (snapshot.playlists.length === 0) {
      list.append(node("div", { className: "notice", role: "status", text: "No generated playlists are available." }));
    }
    const canFullscreen = hostContext.availableDisplayModes?.includes("fullscreen") === true;
    const modeButton = canFullscreen
      ? node("button", {
        className: "button",
        text: hostContext.displayMode === "fullscreen" ? "Use inline view" : "Open larger",
        type: "button",
        disabled: busy,
        attributes: { "data-focus-key": "display-mode" },
        onClick: () => requestDisplayMode(hostContext.displayMode === "fullscreen" ? "inline" : "fullscreen"),
      })
      : null;
    const content = node("div", { className: "content" }, [
      node("p", { className: "eyebrow", text: "Choose one playlist" }),
      heading("Which playlist should we check?"),
      node("p", { className: "lede", text: "We’ll look for these songs on Spotify. Nothing will change yet." }),
      list,
      node("div", { className: "notice", text: "Only the selected playlist is represented in the synthetic check." }),
      selected ? node("div", { className: "selection", text: `${selected.name} · ${selected.songCount} songs` }) : null,
      node("div", { className: "actions" }, [
        modeButton,
        primaryButton(selected ? `Check ${selected.songCount} songs` : "Choose a playlist", () => advance("select_playlist", selected?.id), busy || !selected),
      ].filter(Boolean)),
      errorNotice(),
    ].filter(Boolean));
    return [context("Choose a generated playlist"), content];
  }

  function confirmScreen() {
    const playlist = snapshot.selectedPlaylist;
    const facts = node("dl", { className: "facts" }, [
      node("div", { className: "fact" }, [node("dt", { text: "Selected playlist" }), node("dd", { text: playlist?.name ?? "—" })]),
      node("div", { className: "fact" }, [node("dt", { text: "Playlist entries" }), node("dd", { text: playlist?.songCount ?? 0 })]),
    ]);
    const content = node("div", { className: "content" }, [
      node("p", { className: "eyebrow", text: "Check only · Spotify will not change" }),
      heading(`Check ${playlist?.songCount ?? 0} songs on Spotify?`),
      facts,
      node("div", { className: "notice", text: "This simulated check returns invented suggestions. It does not contact Spotify." }),
      node("div", { className: "actions" }, [primaryButton("Find matches", () => advance("find_matches"), busy)]),
      errorNotice(),
    ].filter(Boolean));
    return [context("Ready for a simulated Spotify check"), content];
  }

  function resultScreen() {
    const summary = snapshot.summary ?? { likelyMatches: 0, needReview: 0, noMatchYet: 0, reviewSongs: 0 };
    const playlist = snapshot.selectedPlaylist;
    const content = node("div", { className: "content" }, [
      heading("Spotify check complete"),
      node("p", { className: "lede", text: `${playlist?.name ?? "Selected playlist"} · ${playlist?.songCount ?? 0} songs checked using generated results` }),
      node("div", { className: "metrics" }, [
        node("div", { className: "metric success", ariaLabel: `${summary.likelyMatches} likely matches` }, [node("strong", { text: summary.likelyMatches }), node("span", { text: "likely matches" })]),
        node("div", { className: "metric attention", ariaLabel: `${summary.needReview} need review` }, [node("strong", { text: summary.needReview }), node("span", { text: "need review" })]),
        node("div", { className: "metric", ariaLabel: `${summary.noMatchYet} no match yet` }, [node("strong", { text: summary.noMatchYet }), node("span", { text: "no match yet" })]),
      ]),
      node("div", { className: "actions" }, [node("button", { className: "button primary", text: `Review ${summary.reviewSongs} songs`, type: "button", disabled: true })]),
      node("p", { className: "later", text: "Later review will keep Wait for Spotify and Stop looking as separate choices. That behavior is outside this prototype." }),
      errorNotice(),
    ].filter(Boolean));
    return [context("Generated Spotify check complete", true), content];
  }

  function render(moveFocus) {
    if (!snapshot) {
      root.replaceChildren(node("div", { className: "card loading", text: initialized ? "Waiting for generated results…" : "Connecting to the MCP Apps host…" }));
      return;
    }
    document.body.dataset.screen = snapshot.screen;
    const builders = {
      choose_file: chooseFileScreen,
      preparing: preparingScreen,
      choose_playlist: choosePlaylistScreen,
      confirm_check: confirmScreen,
      match_results: resultScreen,
    };
    const card = node("section", { className: "card" }, builders[snapshot.screen]());
    card.setAttribute("aria-busy", busy ? "true" : "false");
    root.replaceChildren(card);
    if (moveFocus) root.querySelector("h1")?.focus({ preventScroll: true });
    if (errorMessage) root.querySelector("[role=alert]")?.focus({ preventScroll: true });
  }

  function setupResizeNotifications() {
    if (typeof ResizeObserver !== "function") return;
    let previous = "";
    const report = () => {
      const size = `${Math.ceil(window.innerWidth)}:${Math.ceil(document.documentElement.scrollHeight)}`;
      if (size === previous) return;
      previous = size;
      const [width, height] = size.split(":").map(Number);
      notify("ui/notifications/size-changed", { width, height });
    };
    const observer = new ResizeObserver(report);
    observer.observe(document.documentElement);
    observer.observe(document.body);
    report();
  }

  async function connect() {
    render(false);
    try {
      const result = await request("ui/initialize", {
        appInfo: { name: "DJ Support synthetic playlist check", version: "0.0.0" },
        appCapabilities: { availableDisplayModes: ["inline", "fullscreen"] },
        protocolVersion,
      });
      initialized = true;
      if (isRecord(result?.hostContext)) {
        hostContext = { ...hostContext, ...result.hostContext };
        document.documentElement.dataset.displayMode = result.hostContext.displayMode ?? "inline";
        const width = result.hostContext.containerDimensions?.width ?? result.hostContext.containerDimensions?.maxWidth;
        if (Number.isFinite(width)) document.documentElement.dataset.hostWidth = String(width);
      }
      notify("ui/notifications/initialized");
      setupResizeNotifications();
      render(false);
    } catch {
      initialized = false;
      root.replaceChildren(node("div", { className: "card" }, [
        node("div", { className: "content" }, [
          heading("DJ Support couldn’t connect"),
          node("div", { className: "error", role: "alert", text: "This host did not complete the MCP Apps handshake." }),
        ]),
      ]));
    }
  }

  connect();
}

export function buildComponentHtml(protocolVersion) {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <!-- classification: concept -->
  <title>DJ Support synthetic playlist check</title>
  <style>${STYLES}</style>
</head>
<body>
  <main id="app" class="app" aria-live="polite"></main>
  <script>(${bootComponent.toString()})(${JSON.stringify(protocolVersion)});</script>
</body>
</html>`;
}
