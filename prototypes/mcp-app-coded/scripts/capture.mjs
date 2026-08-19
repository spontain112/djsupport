import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright-core";

const chromePath = process.env.CHROME_PATH;
if (!chromePath) throw new Error("Set CHROME_PATH to a Chromium-compatible browser executable.");

const prototypeDirectory = fileURLToPath(new URL("..", import.meta.url));
const captureDirectory = fileURLToPath(new URL("../captures/", import.meta.url));
await mkdir(captureDirectory, { recursive: true });

const child = spawn(process.execPath, ["server.mjs", "--port", "0"], {
  cwd: prototypeDirectory,
  env: { ...process.env, NODE_ENV: "capture" },
  stdio: ["ignore", "pipe", "pipe"],
});

let browser;
try {
  child.stdout.setEncoding("utf8");
  const [chunk] = await once(child.stdout, "data");
  const ready = JSON.parse(chunk.trim());
  browser = await chromium.launch({ executablePath: chromePath, headless: true });
  const page = await browser.newPage({ viewport: { width: 720, height: 800 }, deviceScaleFactor: 1 });
  const requestOrigins = new Set();
  page.on("request", (request) => requestOrigins.add(new URL(request.url()).origin));
  await page.goto(ready.harness);
  const app = page.frameLocator("iframe");
  const frameElement = page.locator("iframe");
  const observations = [];

  async function capture(fileName, screen, heading) {
    await app.getByRole("heading", { name: heading }).waitFor();
    const box = await frameElement.boundingBox();
    assert.ok(box);
    const dimensions = await app.locator("body").evaluate((body) => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: body.scrollWidth,
      scrollHeight: body.scrollHeight,
    }));
    observations.push({ screen, viewportWidth: page.viewportSize().width, iframeWidth: Math.round(box.width), ...dimensions });
    await frameElement.screenshot({ path: `${captureDirectory}/${fileName}` });
  }

  await capture("01-choose-synthetic-file.png", "choose_file", "Start with your Rekordbox playlists");
  await app.getByRole("button", { name: "Use synthetic file" }).click();
  await capture("02-preparing-playlists.png", "preparing", "Preparing your playlists");
  await app.getByRole("button", { name: "Choose a playlist" }).click();
  await page.setViewportSize({ width: 920, height: 800 });
  await capture("03-choose-playlist.png", "choose_playlist", "Which playlist should we check?");
  await app.getByRole("radio", { name: /Playlist 07/ }).check();
  await app.getByRole("button", { name: "Check 34 songs" }).click();
  await page.setViewportSize({ width: 720, height: 800 });
  await capture("04-confirm-spotify-check.png", "confirm_check", "Check 34 songs on Spotify?");
  await app.getByRole("button", { name: "Find matches" }).click();
  await capture("05-match-results.png", "match_results", "Spotify check complete");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 320, height: 800 });
  await capture("06-reduced-width-results.png", "match_results_reduced_width", "Spotify check complete");

  assert.ok(observations.every(({ clientWidth, scrollWidth }) => scrollWidth <= clientWidth));
  assert.deepEqual([...requestOrigins], [new URL(ready.harness).origin]);
  await writeFile(
    `${captureDirectory}/local-harness-observations.json`,
    `${JSON.stringify({
      classification: "concept",
      evidenceSource: "local MCP Apps host harness, not ChatGPT",
      externalNetworkRequests: 0,
      observedOrigins: ["loopback harness origin"],
      observations,
    }, null, 2)}\n`,
    "utf8",
  );
} finally {
  if (browser) await browser.close();
  if (child.exitCode === null) {
    child.kill("SIGTERM");
    await once(child, "exit");
  }
}
