import assert from "node:assert/strict";
import {
  spawn
} from "node:child_process";
import {
  once
} from "node:events";
import {
  createInterface
} from "node:readline";
import {
  fileURLToPath
} from "node:url";
const {
  chromium
} = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const server = spawn(process.env.PYTHON || "python", ["-u", fileURLToPath(new URL("./server.py", import.meta.url))], {
  stdio: ["ignore", "pipe", "inherit"]
});
const reader = createInterface({
  input: server.stdout
});
let browser;
try {
  const [line] = await Promise.race([once(reader, "line"), once(server, "exit").then(([code]) => {
    throw new Error(`Server exited: ${code}`);
  })]);
  const {
    port,
    root,
    python
  } = JSON.parse(line);
  const base = `http://127.0.0.1:${port}`;
  browser = await chromium.launch({
    headless: true,
    channel: process.env.STUDIO_BROWSER_CHANNEL || undefined
  });
  const page = await browser.newPage({
    viewport: {
      width: 1440,
      height: 1100
    }
  });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(base);
  await page.waitForFunction(() => document.getElementById("connection").textContent.includes("Connected"));
  assert.equal(await page.locator("#empty").isVisible(), true);
  await page.locator("#emptyAdd").click();
  await page.locator("#fieldId").fill("external");
  await page.locator("#fieldName").fill("Trainer <example>");
  await page.locator("#fieldRoot").fill(root);
  await page.locator("#fieldCommands").fill(JSON.stringify({
    train: [python, "-u", "examples/demo_train.py", "--steps", "5", "--delay", ".1"],
    resume: [python, "-u", "examples/demo_train.py", "--steps", "5", "--delay", ".1"],
    long: [python, "-u", "examples/demo_train.py", "--steps", "1000", "--delay", ".1"]
  }));
  await page.locator("#saveProject").click();
  await page.waitForFunction(() => document.getElementById("projectName").textContent === "Trainer <example>");
  assert.equal(await page.locator("#projectName example").count(), 0);
  await page.locator("#start").click();
  await page.waitForFunction(() => document.getElementById("jobState").textContent.includes("succeeded"));
  assert.ok(await page.locator("#metricLine").getAttribute("d"));
  assert.match(await page.locator("#logs").textContent(), /Finished/);
  const checkpoint = page.locator("#artifacts a").filter({
    hasText: "checkpoint.json"
  });
  assert.equal(await checkpoint.count(), 1);
  const response = await page.request.get(base + await checkpoint.getAttribute("href"));
  assert.equal((await response.json()).step, 5);
  await page.locator("#metric").selectOption("accuracy");
  assert.match(await page.locator("#metricSummary").textContent(), /accuracy/);
  await page.locator("#command").selectOption("resume");
  await page.locator("#resume").check();
  await page.locator("#start").click();
  await page.waitForFunction(() => document.getElementById("jobState").textContent.includes("succeeded") && document.getElementById("logs").textContent.includes("from step 5"));
  assert.match(await page.locator("#resumeSource").textContent(), /Resume source/);
  await page.locator("#command").selectOption("long");
  await page.locator("#start").click();
  await page.waitForFunction(() => document.getElementById("jobState").textContent === "running");
  assert.equal(await page.locator("#start").isDisabled(), true);
  await page.locator("#stop").click();
  await page.waitForFunction(() => document.getElementById("jobState").textContent.includes("stopped"));
  await page.reload();
  await page.waitForFunction(() => document.querySelectorAll(".job-item").length === 3);
  if (process.env.STUDIO_SCREENSHOT) await page.screenshot({path: process.env.STUDIO_SCREENSHOT, fullPage: true});
  await page.setViewportSize({
    width: 390,
    height: 844
  });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  assert.equal(await page.locator("#start").isVisible(), true);
  assert.deepEqual(errors, []);
  console.log("Browser acceptance passed: register, train, metrics, artifact download, resume, stop, reload, mobile.");
} finally {
  await browser?.close();
  server.kill();
  await once(server, "exit");
  reader.close();
}
