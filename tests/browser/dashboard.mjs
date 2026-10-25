import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {once} from "node:events";
import {createInterface} from "node:readline";
import {fileURLToPath} from "node:url";

const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const server = spawn(process.env.PYTHON || "python", ["-u", fileURLToPath(new URL("./server.py", import.meta.url))], {stdio: ["ignore", "pipe", "inherit"]});
const reader = createInterface({input: server.stdout});
let browser;
try {
  const [line] = await Promise.race([
    once(reader, "line"),
    once(server, "exit").then(([code]) => {throw new Error(`Fixture server exited: ${code}`);}),
  ]);
  const {port} = JSON.parse(line);
  browser = await chromium.launch({headless: true, channel: process.env.STUDIO_BROWSER_CHANNEL || undefined});
  const page = await browser.newPage({viewport: {width: 1440, height: 1100}});
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${port}`);
  await page.waitForFunction(() => document.getElementById("stepTitle").textContent === "Step 100 of 200");
  assert.ok(await page.locator("#lossChart .line").getAttribute("d"));
  await page.locator("#sourceMode").selectOption("historical");
  assert.equal(await page.locator("#runSelect option").textContent(), "Fixture <run> · 512px");
  const actionRequests = [];
  await page.route("**/api/action", async route => {
    actionRequests.push(route.request().postDataJSON());
    await route.fulfill({json: {ok: true}});
  });
  await page.locator("#sampleButton").click();
  await page.waitForFunction(() => document.getElementById("toast").textContent.includes("Historical"));
  assert.equal(actionRequests[0].runId, "fixture");
  assert.equal(actionRequests[0].checkpointId, "step-100");

  await page.locator('[data-workspace="llm"]').click();
  await page.waitForFunction(() => document.getElementById("llmTitle").textContent === "Alpha <example>");
  assert.equal(await page.locator("#llmTitle example").count(), 0);
  const pending = [];
  await page.route("**/chat", route => {pending.push(route);});
  await page.locator("#llmChatInput").fill("hello alpha");
  await page.locator("#llmChatSend").click();
  await page.waitForTimeout(4300);
  assert.equal(await page.locator("#llmChatSend").isDisabled(), true, "polling must not enable duplicate chat requests");
  assert.equal(pending.length, 1);
  await page.locator("#llmRunSelect").selectOption("beta");
  await page.waitForFunction(() => document.getElementById("llmTitle").textContent === "Beta <example>");
  await pending[0].fulfill({json: {reply: "late alpha reply"}}).catch(() => {});
  assert.ok(!(await page.locator("#llmChatTranscript").textContent()).includes("late alpha reply"));
  await page.locator("#llmChatInput").fill("hello beta");
  await page.locator("#llmChatSend").click();
  await page.waitForTimeout(100);
  assert.equal(pending.length, 2);
  assert.ok(pending[1].request().url().includes("/beta/chat"));
  await pending[1].fulfill({json: {reply: "beta reply"}});
  await page.waitForFunction(() => document.getElementById("llmChatTranscript").textContent.includes("beta reply"));

  await page.route("**/api/status", route => route.fulfill({status: 503, json: {error: "fixture offline"}}));
  await page.locator('[data-workspace="diffusion"]').click();
  await page.waitForFunction(() => document.getElementById("livePill").textContent.includes("disconnected"));
  await page.unroute("**/api/status");
  await page.locator('[data-workspace="llm"]').click();
  await page.locator('[data-workspace="diffusion"]').click();
  await page.waitForFunction(() => document.getElementById("livePill").textContent.includes("Trainer stopped"));

  await page.setViewportSize({width: 390, height: 844});
  assert.ok(await page.locator("#sampleButton").isVisible());
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  assert.deepEqual(errors, []);
  console.log("Browser checks passed: charts, historical sampling, escaped metadata, chat polling, run-switch races, reconnect, mobile layout");
} finally {
  await browser?.close();
  reader.close();
  server.kill();
}
