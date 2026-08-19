import assert from "node:assert/strict";
import { once } from "node:events";
import { spawn } from "node:child_process";
import { after, before, describe, test } from "node:test";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

const EXPECTED_RESOURCE_URI = "ui://djsupport/synthetic-playlist-check-v1.html";
const EXPECTED_TOOLS = [
  "advance_synthetic_playlist_check",
  "render_synthetic_playlist_check",
  "start_synthetic_playlist_check",
];

let child;
let client;
let endpoint;

async function startPrototype() {
  child = spawn(process.execPath, ["server.mjs", "--port", "0"], {
    cwd: new URL("..", import.meta.url),
    env: { ...process.env, NODE_ENV: "test" },
    stdio: ["ignore", "pipe", "pipe"],
  });

  let stderr = "";
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (chunk) => {
    stderr += chunk;
  });

  const ready = await Promise.race([
    new Promise((resolve, reject) => {
      child.stdout.setEncoding("utf8");
      let buffered = "";
      child.stdout.on("data", (chunk) => {
        buffered += chunk;
        const newline = buffered.indexOf("\n");
        if (newline === -1) return;
        try {
          resolve(JSON.parse(buffered.slice(0, newline)));
        } catch (error) {
          reject(error);
        }
      });
      child.once("exit", (code) => {
        reject(new Error(`prototype exited early (${code}): ${stderr}`));
      });
    }),
    new Promise((_, reject) =>
      setTimeout(() => reject(new Error(`prototype did not start: ${stderr}`)), 5000),
    ),
  ]);

  assert.equal(ready.type, "ready");
  assert.match(ready.endpoint, /^http:\/\/127\.0\.0\.1:\d+\/mcp$/);
  endpoint = ready.endpoint;
  client = new Client({ name: "djsupport-prototype-tests", version: "1.0.0" });
  await client.connect(new StreamableHTTPClientTransport(new URL(endpoint)));
}

async function stopPrototype() {
  if (client) await client.close();
  if (child && child.exitCode === null) {
    child.kill("SIGTERM");
    await once(child, "exit");
  }
}

async function call(name, args = {}) {
  const result = await client.callTool({ name, arguments: args });
  assert.equal(result.isError, undefined);
  return result;
}

describe("public MCP contract", () => {
  before(startPrototype);
  after(stopPrototype);

  test("advertises three read-only, closed-world synthetic tools", async () => {
    const listed = await client.listTools();
    assert.deepEqual(
      listed.tools.map(({ name }) => name).sort(),
      EXPECTED_TOOLS,
    );

    for (const tool of listed.tools) {
      assert.deepEqual(tool.annotations, {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: tool.name !== "start_synthetic_playlist_check",
        openWorldHint: false,
      });
    }

    const dataTools = listed.tools.filter(({ name }) => name !== "render_synthetic_playlist_check");
    assert.ok(dataTools.every((tool) => tool._meta?.ui?.resourceUri === undefined));
    assert.equal(
      listed.tools.find(({ name }) => name === "render_synthetic_playlist_check")._meta.ui.resourceUri,
      EXPECTED_RESOURCE_URI,
    );
  });

  test("keeps the data-only journey useful without a UI", async () => {
    const started = await call("start_synthetic_playlist_check");
    assert.equal(started.structuredContent.screen, "choose_file");
    assert.equal(started.structuredContent.revision, 0);
    assert.equal(started.structuredContent.spotifyChanged, false);
    assert.equal(started.structuredContent.synthetic, true);
    assert.match(started.structuredContent.journeyId, /^synthetic-[a-f0-9-]+$/);
    assert.deepEqual(started.structuredContent.source, {
      displayName: "Generated Rekordbox playlist file",
      kind: "synthetic_rekordbox_playlist_file",
    });
    assert.match(started.content[0].text, /generated synthetic data/i);
    assert.deepEqual(started._meta.djsupportPrototype, {
      componentScreen: "choose_file",
      filePickerInvoked: false,
      presentationStateDurable: false,
    });
    assert.equal(started.structuredContent.djsupportPrototype, undefined);
    assert.doesNotMatch(JSON.stringify(started), /[/\\](Users|home|private|tmp)[/\\]/i);
  });

  test("serves a portable no-network MCP App resource", async () => {
    const resources = await client.listResources();
    assert.deepEqual(resources.resources.map(({ uri }) => uri), [EXPECTED_RESOURCE_URI]);

    const resource = await client.readResource({ uri: EXPECTED_RESOURCE_URI });
    assert.equal(resource.contents.length, 1);
    const [content] = resource.contents;
    assert.equal(content.mimeType, "text/html;profile=mcp-app");
    assert.equal(content.uri, EXPECTED_RESOURCE_URI);
    assert.equal(content._meta.ui.prefersBorder, true);
    assert.deepEqual(content._meta.ui.csp, {
      connectDomains: [],
      resourceDomains: [],
    });
    assert.match(content.text, /classification: concept/);
    assert.match(content.text, /ui\/initialize/);
    assert.match(content.text, /ui\/notifications\/tool-result/);
    assert.match(content.text, /tools\/call/);
    assert.doesNotMatch(content.text, /https?:\/\//);
    assert.doesNotMatch(content.text, /\b(?:fetch|XMLHttpRequest|WebSocket|EventSource)\s*\(/);
    assert.doesNotMatch(content.text, /(?:innerHTML|insertAdjacentHTML)/);
    assert.doesNotMatch(content.text, /selectFiles\s*\(/);
  });

  test("advances the five authoritative synthetic screens with revision checks", async () => {
    const start = (await call("start_synthetic_playlist_check")).structuredContent;
    const rendered = await call("render_synthetic_playlist_check", {
      journeyId: start.journeyId,
    });
    assert.deepEqual(rendered.structuredContent, start);

    const preparing = (
      await call("advance_synthetic_playlist_check", {
        journeyId: start.journeyId,
        expectedRevision: 0,
        action: "choose_synthetic_file",
      })
    ).structuredContent;
    assert.equal(preparing.screen, "preparing");
    assert.equal(preparing.revision, 1);

    const stale = await client.callTool({
      name: "advance_synthetic_playlist_check",
      arguments: {
        journeyId: start.journeyId,
        expectedRevision: 0,
        action: "choose_synthetic_file",
      },
    });
    assert.equal(stale.isError, true);
    assert.match(stale.content[0].text, /revision is stale/i);
    assert.deepEqual(
      (await call("render_synthetic_playlist_check", { journeyId: start.journeyId })).structuredContent,
      preparing,
    );

    const chooser = (
      await call("advance_synthetic_playlist_check", {
        journeyId: start.journeyId,
        expectedRevision: 1,
        action: "show_playlists",
      })
    ).structuredContent;
    assert.equal(chooser.screen, "choose_playlist");
    assert.equal(chooser.playlists.length, 4);
    assert.deepEqual(chooser.playlists[0], {
      id: "playlist-07",
      name: "Playlist 07",
      songCount: 34,
      recency: "Updated today",
    });

    const confirmation = (
      await call("advance_synthetic_playlist_check", {
        journeyId: start.journeyId,
        expectedRevision: 2,
        action: "select_playlist",
        playlistId: "playlist-07",
      })
    ).structuredContent;
    assert.equal(confirmation.screen, "confirm_check");
    assert.equal(confirmation.selectedPlaylist.name, "Playlist 07");

    const results = (
      await call("advance_synthetic_playlist_check", {
        journeyId: start.journeyId,
        expectedRevision: 3,
        action: "find_matches",
      })
    ).structuredContent;
    assert.equal(results.screen, "match_results");
    assert.deepEqual(results.summary, {
      likelyMatches: 28,
      needReview: 4,
      noMatchYet: 2,
      reviewSongs: 6,
    });
    assert.equal(results.spotifyChanged, false);
    assert.deepEqual(
      (await call("render_synthetic_playlist_check", { journeyId: start.journeyId })).structuredContent,
      results,
    );
  });

  test("fails closed for stale or invented journey transitions", async () => {
    const result = await client.callTool({
      name: "advance_synthetic_playlist_check",
      arguments: {
        journeyId: "synthetic-invented",
        expectedRevision: 0,
        action: "choose_synthetic_file",
      },
    });
    assert.equal(result.isError, true);
    assert.match(result.content[0].text, /unknown synthetic journey/i);
  });
});
