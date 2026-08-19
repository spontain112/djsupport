import { randomUUID } from "node:crypto";
import process from "node:process";

import { LATEST_PROTOCOL_VERSION } from "@modelcontextprotocol/ext-apps";
import {
  RESOURCE_MIME_TYPE,
  registerAppResource,
  registerAppTool,
} from "@modelcontextprotocol/ext-apps/server";
import { createMcpExpressApp } from "@modelcontextprotocol/sdk/server/express.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { z } from "zod/v4";

import { buildComponentHtml } from "./component.mjs";

const HOST = "127.0.0.1";
const RESOURCE_URI = "ui://djsupport/synthetic-playlist-check-v1.html";
const journeys = new Map();

const PLAYLISTS = Object.freeze([
  Object.freeze({ id: "playlist-07", name: "Playlist 07", songCount: 34, recency: "Updated today" }),
  Object.freeze({ id: "playlist-03", name: "Playlist 03", songCount: 27, recency: "Updated yesterday" }),
  Object.freeze({ id: "playlist-11", name: "Playlist 11", songCount: 41, recency: "Updated 3 days ago" }),
  Object.freeze({ id: "playlist-05", name: "Playlist 05", songCount: 18, recency: "Updated 1 week ago" }),
]);

const snapshotOutputSchema = {
  journeyId: z.string(),
  revision: z.number().int().nonnegative(),
  screen: z.enum(["choose_file", "preparing", "choose_playlist", "confirm_check", "match_results"]),
  synthetic: z.literal(true),
  spotifyChanged: z.literal(false),
  source: z.object({
    displayName: z.string(),
    kind: z.literal("synthetic_rekordbox_playlist_file"),
  }),
  playlists: z.array(z.object({
    id: z.string(),
    name: z.string(),
    songCount: z.number().int().nonnegative(),
    recency: z.string(),
  })),
  selectedPlaylist: z.object({
    id: z.string(),
    name: z.string(),
    songCount: z.number().int().nonnegative(),
    recency: z.string(),
  }).nullable(),
  progress: z.object({
    found: z.number().int().nonnegative(),
    total: z.number().int().nonnegative(),
  }).nullable(),
  summary: z.object({
    likelyMatches: z.number().int().nonnegative(),
    needReview: z.number().int().nonnegative(),
    noMatchYet: z.number().int().nonnegative(),
    reviewSongs: z.number().int().nonnegative(),
  }).nullable(),
};

const READ_ONLY_ANNOTATIONS = Object.freeze({
  readOnlyHint: true,
  destructiveHint: false,
  idempotentHint: true,
  openWorldHint: false,
});

function freezeSnapshot(snapshot) {
  return Object.freeze({
    ...snapshot,
    source: Object.freeze({ ...snapshot.source }),
    playlists: Object.freeze(snapshot.playlists.map((playlist) => Object.freeze({ ...playlist }))),
    selectedPlaylist: snapshot.selectedPlaylist ? Object.freeze({ ...snapshot.selectedPlaylist }) : null,
    progress: snapshot.progress ? Object.freeze({ ...snapshot.progress }) : null,
    summary: snapshot.summary ? Object.freeze({ ...snapshot.summary }) : null,
  });
}

function initialSnapshot({ hostileDisplayName = false } = {}) {
  return freezeSnapshot({
    journeyId: `synthetic-${randomUUID()}`,
    revision: 0,
    screen: "choose_file",
    synthetic: true,
    spotifyChanged: false,
    source: {
      displayName: hostileDisplayName ? "<img src=x onerror=alert(1)>" : "Generated Rekordbox playlist file",
      kind: "synthetic_rekordbox_playlist_file",
    },
    playlists: [],
    selectedPlaylist: null,
    progress: null,
    summary: null,
  });
}

function retain(snapshot) {
  if (journeys.size >= 100) journeys.delete(journeys.keys().next().value);
  journeys.set(snapshot.journeyId, snapshot);
  return snapshot;
}

function startJourney(options) {
  return retain(initialSnapshot(options));
}

function getJourney(journeyId) {
  const snapshot = journeys.get(journeyId);
  if (!snapshot) throw new Error("Unknown synthetic journey.");
  return snapshot;
}

function advanceJourney({ journeyId, expectedRevision, action, playlistId }) {
  const current = getJourney(journeyId);
  if (current.revision !== expectedRevision) throw new Error("The synthetic journey revision is stale.");

  let next;
  if (current.screen === "choose_file" && action === "choose_synthetic_file") {
    next = { ...current, revision: 1, screen: "preparing", progress: { found: 12, total: 12 } };
  } else if (current.screen === "preparing" && action === "show_playlists") {
    next = { ...current, revision: 2, screen: "choose_playlist", playlists: PLAYLISTS, progress: null };
  } else if (current.screen === "choose_playlist" && action === "select_playlist") {
    const selectedPlaylist = current.playlists.find(({ id }) => id === playlistId);
    if (!selectedPlaylist) throw new Error("Choose one of the generated playlists.");
    next = { ...current, revision: 3, screen: "confirm_check", selectedPlaylist };
  } else if (current.screen === "confirm_check" && action === "find_matches") {
    next = {
      ...current,
      revision: 4,
      screen: "match_results",
      summary: { likelyMatches: 28, needReview: 4, noMatchYet: 2, reviewSongs: 6 },
    };
  } else {
    throw new Error("That action is not available for the current synthetic screen.");
  }
  return retain(freezeSnapshot(next));
}

function textFor(snapshot) {
  if (snapshot.screen === "choose_file") {
    return `Synthetic journey ${snapshot.journeyId} is ready. It uses generated synthetic data and no local file.`;
  }
  if (snapshot.screen === "preparing") return "Generated playlists are prepared. Spotify unchanged.";
  if (snapshot.screen === "choose_playlist") return "Four generated playlists are available for selection.";
  if (snapshot.screen === "confirm_check") {
    return `${snapshot.selectedPlaylist.name} has ${snapshot.selectedPlaylist.songCount} playlist entries. The simulated Spotify check has not run.`;
  }
  return `${snapshot.summary.likelyMatches} likely matches, ${snapshot.summary.needReview} need review, and ${snapshot.summary.noMatchYet} no match yet. Spotify unchanged.`;
}

function toolResult(snapshot) {
  return {
    structuredContent: snapshot,
    content: [{ type: "text", text: textFor(snapshot) }],
    _meta: {
      djsupportPrototype: {
        componentScreen: snapshot.screen,
        filePickerInvoked: false,
        presentationStateDurable: false,
      },
    },
  };
}

function errorResult(error) {
  return {
    isError: true,
    content: [{ type: "text", text: error instanceof Error ? error.message : "Synthetic journey failed." }],
  };
}

function registerPrototypeContract(server, componentHtml) {
  registerAppResource(
    server,
    "DJ Support synthetic playlist check",
    RESOURCE_URI,
    {
      description: "No-network concept UI for the generated five-screen playlist journey.",
      _meta: {
        ui: {
          prefersBorder: true,
          csp: { connectDomains: [], resourceDomains: [] },
        },
      },
    },
    async () => ({
      contents: [{
        uri: RESOURCE_URI,
        mimeType: RESOURCE_MIME_TYPE,
        text: componentHtml,
        _meta: {
          ui: {
            prefersBorder: true,
            csp: { connectDomains: [], resourceDomains: [] },
          },
        },
      }],
    }),
  );

  server.registerTool(
    "start_synthetic_playlist_check",
    {
      title: "Start a synthetic DJ Support playlist check",
      description: "Start an in-memory journey using generated Rekordbox-shaped playlist data. Call this before rendering the prototype. It reads no file and contacts no provider.",
      outputSchema: snapshotOutputSchema,
      annotations: { ...READ_ONLY_ANNOTATIONS, idempotentHint: false },
    },
    async () => toolResult(startJourney()),
  );

  server.registerTool(
    "advance_synthetic_playlist_check",
    {
      title: "Advance a synthetic DJ Support playlist check",
      description: "Advance one validated step of an existing generated journey. Returns complete model-readable state without requiring the UI.",
      inputSchema: {
        journeyId: z.string().startsWith("synthetic-"),
        expectedRevision: z.number().int().nonnegative(),
        action: z.enum(["choose_synthetic_file", "show_playlists", "select_playlist", "find_matches"]),
        playlistId: z.string().optional(),
      },
      outputSchema: snapshotOutputSchema,
      annotations: READ_ONLY_ANNOTATIONS,
    },
    async (args) => {
      try {
        return toolResult(advanceJourney(args));
      } catch (error) {
        return errorResult(error);
      }
    },
  );

  registerAppTool(
    server,
    "render_synthetic_playlist_check",
    {
      title: "Render a synthetic DJ Support playlist check",
      description: "Render the journey returned by start_synthetic_playlist_check. Call the start tool first, then pass its journeyId here.",
      inputSchema: { journeyId: z.string().startsWith("synthetic-") },
      outputSchema: snapshotOutputSchema,
      annotations: READ_ONLY_ANNOTATIONS,
      _meta: { ui: { resourceUri: RESOURCE_URI } },
    },
    async ({ journeyId }) => {
      try {
        return toolResult(getJourney(journeyId));
      } catch (error) {
        return errorResult(error);
      }
    },
  );
}

function createServer(componentHtml) {
  const server = new McpServer({
    name: "djsupport-synthetic-mcp-app-prototype",
    version: "0.0.0",
  });
  registerPrototypeContract(server, componentHtml);
  return server;
}

function harnessHtml(protocolVersion) {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <!-- classification: concept -->
  <title>DJ Support MCP Apps host harness</title>
  <style>
    html, body { margin: 0; background: #f7f7f5; font-family: system-ui, sans-serif; }
    main { width: min(100%, 920px); margin: 0 auto; padding: 12px; }
    iframe { display: block; width: 100%; min-height: 620px; border: 0; background: transparent; }
  </style>
</head>
<body>
  <main><iframe title="DJ Support MCP App" src="/component" sandbox="allow-scripts"></iframe></main>
  <script>
    const frame = document.querySelector("iframe");
    const query = new URLSearchParams(location.search);
    const hostile = query.get("hostile") === "1";
    const fail = query.get("fail") === "1";
    const empty = query.get("empty") === "1";
    const slow = query.get("slow") === "1";
    let failedOnce = false;

    function send(message) { frame.contentWindow.postMessage(message, "*"); }
    async function json(url, options) {
      const response = await fetch(url, options);
      if (!response.ok) throw new Error("Harness request failed");
      return response.json();
    }
    window.addEventListener("message", async (event) => {
      if (event.source !== frame.contentWindow) return;
      const message = event.data;
      if (!message || message.jsonrpc !== "2.0") return;
      if (message.method === "ui/initialize") {
        send({
          jsonrpc: "2.0",
          id: message.id,
          result: {
            protocolVersion: ${JSON.stringify(protocolVersion)},
            hostInfo: { name: "DJ Support synthetic host harness", version: "0.0.0" },
            hostCapabilities: {
              serverTools: {},
              sandbox: { csp: { connectDomains: [], resourceDomains: [] } },
            },
            hostContext: {
              theme: "light",
              displayMode: "inline",
              availableDisplayModes: ["inline", "fullscreen"],
              containerDimensions: { width: frame.clientWidth, maxHeight: 760 },
              locale: "en",
              platform: "web",
            },
          },
        });
        return;
      }
      if (message.method === "ui/notifications/initialized") {
        if (slow) await new Promise((resolve) => setTimeout(resolve, 300));
        const result = await json("/harness/start?hostile=" + (hostile ? "1" : "0"));
        send({ jsonrpc: "2.0", method: "ui/notifications/tool-result", params: result });
        return;
      }
      if (message.method === "ui/notifications/size-changed") {
        const height = Math.min(760, Math.max(420, Number(message.params?.height) || 620));
        frame.style.height = height + "px";
        return;
      }
      if (message.method === "ui/request-display-mode") {
        const mode = message.params?.mode === "fullscreen" ? "fullscreen" : "inline";
        send({ jsonrpc: "2.0", id: message.id, result: { mode } });
        send({
          jsonrpc: "2.0",
          method: "ui/notifications/host-context-changed",
          params: { displayMode: mode, containerDimensions: { width: frame.clientWidth, maxHeight: 760 } },
        });
        return;
      }
      if (message.method === "tools/call") {
        if (fail && !failedOnce) {
          failedOnce = true;
          send({ jsonrpc: "2.0", id: message.id, error: { code: -32603, message: "Synthetic harness failure" } });
          return;
        }
        const result = await json("/harness/call", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(message.params),
        });
        if (empty && result.structuredContent?.screen === "choose_playlist") {
          result.structuredContent.playlists = [];
        }
        send({ jsonrpc: "2.0", id: message.id, result });
      }
    });
  </script>
</body>
</html>`;
}

function parsePort(argv) {
  const index = argv.indexOf("--port");
  const raw = index === -1 ? "8787" : argv[index + 1];
  const port = Number(raw);
  if (!Number.isInteger(port) || port < 0 || port > 65535) throw new Error("--port must be an integer from 0 to 65535");
  return port;
}

const componentHtml = buildComponentHtml(LATEST_PROTOCOL_VERSION);
const app = createMcpExpressApp({ host: HOST });

app.post("/mcp", async (request, response) => {
  const server = createServer(componentHtml);
  const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
  try {
    await server.connect(transport);
    await transport.handleRequest(request, response, request.body);
  } catch {
    if (!response.headersSent) {
      response.status(500).json({
        jsonrpc: "2.0",
        error: { code: -32603, message: "Synthetic MCP request failed." },
        id: null,
      });
    }
  } finally {
    await transport.close();
    await server.close();
  }
});

for (const method of ["get", "delete", "put", "patch"]) {
  app[method]("/mcp", (_request, response) => {
    response.status(405).json({
      jsonrpc: "2.0",
      error: { code: -32000, message: "Method not allowed." },
      id: null,
    });
  });
}

app.get("/component", (_request, response) => {
  response.set("content-type", "text/html;profile=mcp-app");
  response.set("content-security-policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'");
  response.send(componentHtml);
});

app.get("/harness", (_request, response) => {
  response.set("content-security-policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'");
  response.send(harnessHtml(LATEST_PROTOCOL_VERSION));
});

app.get("/harness/start", (request, response) => {
  response.json(toolResult(startJourney({ hostileDisplayName: request.query.hostile === "1" })));
});

app.post("/harness/call", (request, response) => {
  if (request.body?.name !== "advance_synthetic_playlist_check") {
    response.status(400).json(errorResult(new Error("Unsupported harness tool.")));
    return;
  }
  try {
    response.json(toolResult(advanceJourney(request.body.arguments ?? {})));
  } catch (error) {
    response.json(errorResult(error));
  }
});

const listener = app.listen(parsePort(process.argv.slice(2)), HOST, (error) => {
  if (error) {
    process.stderr.write("DJ Support synthetic MCP prototype could not bind its loopback port.\n");
    process.exitCode = 1;
    return;
  }
  const address = listener.address();
  if (typeof address !== "object" || address === null) {
    process.stderr.write("DJ Support synthetic MCP prototype has no loopback address.\n");
    process.exitCode = 1;
    return;
  }
  const port = address.port;
  process.stdout.write(`${JSON.stringify({
    type: "ready",
    endpoint: `http://${HOST}:${port}/mcp`,
    harness: `http://${HOST}:${port}/harness`,
  })}\n`);
});

function shutdown() {
  listener.close(() => process.exit(0));
}

process.once("SIGINT", shutdown);
process.once("SIGTERM", shutdown);
