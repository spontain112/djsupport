import assert from "node:assert/strict";
import { once } from "node:events";
import { spawn } from "node:child_process";
import { after, before, describe, test } from "node:test";

import { chromium } from "playwright-core";

const chromePath = process.env.CHROME_PATH;
let browser;
let child;
let harnessUrl;

async function startPrototype() {
  child = spawn(process.execPath, ["server.mjs", "--port", "0"], {
    cwd: new URL("..", import.meta.url),
    env: { ...process.env, NODE_ENV: "test" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.setEncoding("utf8");
  const [chunk] = await once(child.stdout, "data");
  const ready = JSON.parse(chunk.trim());
  harnessUrl = ready.harness;
  browser = await chromium.launch({ executablePath: chromePath, headless: true });
}

async function stopPrototype() {
  if (browser) await browser.close();
  if (child && child.exitCode === null) {
    child.kill("SIGTERM");
    await once(child, "exit");
  }
}

describe("MCP Apps bridge component", { skip: !chromePath }, () => {
  before(startPrototype);
  after(stopPrototype);

  test("completes all five screens through postMessage tool calls", async () => {
    const page = await browser.newPage({ viewport: { width: 720, height: 700 } });
    await page.goto(harnessUrl);
    const app = page.frameLocator("iframe");

    await assert.doesNotReject(() => app.getByRole("heading", { name: "Start with your Rekordbox playlists" }).waitFor());
    assert.equal(await app.getByText("DJ Support", { exact: true }).count(), 0);
    assert.equal(await app.locator(".mark").count(), 0);
    const fallbackContrast = await app.locator("body").evaluate(() => {
      function channels(color) {
        return color.match(/[\d.]+/g).slice(0, 3).map(Number);
      }
      function luminance(color) {
        return channels(color)
          .map((channel) => channel / 255)
          .map((channel) => channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4)
          .reduce((sum, channel, index) => sum + channel * [0.2126, 0.7152, 0.0722][index], 0);
      }
      function ratio(foreground, background) {
        const values = [luminance(foreground), luminance(background)].sort((left, right) => right - left);
        return (values[0] + 0.05) / (values[1] + 0.05);
      }
      const context = document.querySelector(".context-copy");
      const metadata = document.querySelector(".meta");
      return {
        context: ratio(getComputedStyle(context).color, getComputedStyle(document.querySelector(".card")).backgroundColor),
        metadata: ratio(getComputedStyle(metadata).color, getComputedStyle(metadata.closest(".file-card")).backgroundColor),
      };
    });
    assert.ok(fallbackContrast.context >= 4.5);
    assert.ok(fallbackContrast.metadata >= 4.5);
    await app.getByRole("button", { name: "Use synthetic file" }).click();
    const preparingHeading = app.getByRole("heading", { name: "Preparing your playlists" });
    await assert.doesNotReject(() => preparingHeading.waitFor());
    assert.equal(await preparingHeading.evaluate((node) => node === document.activeElement), true);
    assert.equal(await app.getByText("Found 12 of 12 playlists").count(), 1);

    await app.getByRole("button", { name: "Choose a playlist" }).click();
    const playlistHeading = app.getByRole("heading", { name: "Which playlist should we check?" });
    await assert.doesNotReject(() => playlistHeading.waitFor());
    assert.equal(await playlistHeading.evaluate((node) => node === document.activeElement), true);
    await app.getByRole("button", { name: "Open larger" }).click();
    assert.equal(await app.locator("html").getAttribute("data-display-mode"), "fullscreen");
    const inlineModeButton = app.getByRole("button", { name: "Use inline view" });
    assert.equal(await inlineModeButton.count(), 1);
    assert.equal(await inlineModeButton.evaluate((node) => node === document.activeElement), true);
    const playlist11 = app.getByRole("radio", { name: /Playlist 11/ });
    await playlist11.press("Space");
    assert.equal(await playlist11.evaluate((node) => node === document.activeElement), true);
    await app.getByRole("button", { name: "Check 41 songs" }).click();

    const confirmationHeading = app.getByRole("heading", { name: "Check 41 songs on Spotify?" });
    await assert.doesNotReject(() => confirmationHeading.waitFor());
    assert.equal(await confirmationHeading.evaluate((node) => node === document.activeElement), true);
    await app.getByRole("button", { name: "Find matches" }).click();
    const resultsHeading = app.getByRole("heading", { name: "Spotify check complete" });
    await assert.doesNotReject(() => resultsHeading.waitFor());
    assert.equal(await resultsHeading.evaluate((node) => node === document.activeElement), true);

    assert.equal(await app.getByLabel("28 likely matches", { exact: true }).count(), 1);
    assert.equal(await app.getByLabel("4 need review", { exact: true }).count(), 1);
    assert.equal(await app.getByLabel("2 no match yet", { exact: true }).count(), 1);
    assert.equal(await app.getByRole("button", { name: "Review 6 songs" }).count(), 1);
    assert.equal(await app.getByText("Spotify unchanged", { exact: true }).count(), 1);

    const visibleText = await app.locator("body").innerText();
    for (const forbidden of ["not found", "not on Spotify", "matched", "skip", "Preview", "Publish"]) {
      assert.equal(visibleText.includes(forbidden), false, `visible copy included ${forbidden}`);
    }
    await page.close();
  });

  test("sanitizes hostile tool output and keeps focus useful at reduced width", async () => {
    const page = await browser.newPage({ viewport: { width: 320, height: 760 } });
    await page.goto(`${harnessUrl}?hostile=1`);
    const app = page.frameLocator("iframe");
    const heading = app.getByRole("heading", { name: "Start with your Rekordbox playlists" });
    await heading.waitFor();
    assert.equal(await app.locator("script[data-hostile]").count(), 0);
    assert.equal(await app.getByText("<img src=x onerror=alert(1)>", { exact: true }).count(), 1);

    await app.getByRole("button", { name: "Use synthetic file" }).focus();
    assert.equal(await app.getByRole("button", { name: "Use synthetic file" }).evaluate((node) => node === document.activeElement), true);
    await page.keyboard.press("Enter");
    await app.getByRole("heading", { name: "Preparing your playlists" }).waitFor();
    assert.equal(await app.locator("body").evaluate((body) => body.scrollWidth <= document.documentElement.clientWidth), true);
    await page.close();
  });

  test("shows a bounded error and preserves the current screen", async () => {
    const page = await browser.newPage({ viewport: { width: 480, height: 700 } });
    await page.goto(`${harnessUrl}?fail=1`);
    const app = page.frameLocator("iframe");
    await app.getByRole("button", { name: "Use synthetic file" }).click();
    const alert = app.getByRole("alert");
    await assert.doesNotReject(() => alert.waitFor());
    assert.match(await alert.innerText(), /couldn’t continue the synthetic check/i);
    assert.equal(await alert.evaluate((node) => node === document.activeElement), true);
    assert.equal(await app.getByRole("heading", { name: "Start with your Rekordbox playlists" }).count(), 1);
    await page.close();
  });

  test("shows initial loading and an explicit empty playlist state", async () => {
    const page = await browser.newPage({ viewport: { width: 480, height: 700 } });
    await page.goto(`${harnessUrl}?slow=1&empty=1`);
    const app = page.frameLocator("iframe");
    await assert.doesNotReject(() => app.getByText("Waiting for generated results…", { exact: true }).waitFor());
    await app.getByRole("button", { name: "Use synthetic file" }).click();
    await app.getByRole("button", { name: "Choose a playlist" }).click();
    await assert.doesNotReject(() => app.getByText("No generated playlists are available.", { exact: true }).waitFor());
    assert.equal(await app.getByRole("button", { name: "Choose a playlist" }).isDisabled(), true);
    await page.close();
  });
});
