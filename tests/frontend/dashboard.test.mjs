import test from "node:test";
import assert from "node:assert/strict";
import {chartGeometry} from "../../src/hentai_studio/dashboard_static/charts.js";
import {requestJSON, api} from "../../src/hentai_studio/dashboard_static/api.js";
import {createPoller} from "../../src/hentai_studio/dashboard_static/poller.js";
import {escapeHTML} from "../../src/hentai_studio/dashboard_static/dom.js";

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

test("chart positions reflect actual steps, including sparse validation", () => {
  const result = chartGeometry([
    {step: 0, loss: 3}, {step: 1, loss: 2, evalLoss: 2.5}, {step: 10, loss: 1, evalLoss: 1.5},
  ], 120, 100, 10);
  assert.match(result.line, /L20\.0,/);
  assert.match(result.line, /L110\.0,/);
  assert.equal(result.markers.length, 2);
  assert.ok(!result.area.includes("NaN"));
});

test("chart handles missing, invalid, and constant losses", () => {
  assert.equal(chartGeometry([{step: 1, loss: NaN}]).line, "");
  const result = chartGeometry([{step: 1, loss: 1}, {step: 2, loss: 1}]);
  assert.ok(!result.line.includes("NaN"));
  assert.equal(result.validation, "");
});

test("metadata text is escaped before template rendering", () => {
  assert.equal(escapeHTML('<img src=x onerror="alert(1)">'), "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;");
});

test("API reports server errors and encodes selected run IDs", async t => {
  let requested;
  t.mock.method(globalThis, "fetch", async (path, options) => {
    requested = {path, options};
    return {ok: false, status: 400, json: async () => ({error: "checkpoint incomplete"})};
  });
  await assert.rejects(api.runStatus("run/name"), /checkpoint incomplete/);
  assert.equal(requested.path, "/api/v1/runs/run%2Fname/status");
  assert.equal(requested.options.cache, "no-store");
});

test("API propagates cancellation to the underlying fetch", async t => {
  t.mock.method(globalThis, "fetch", (path, {signal}) => new Promise((resolve, reject) => {
    signal.addEventListener("abort", () => reject(signal.reason), {once: true});
  }));
  const controller = new AbortController();
  const request = requestJSON("/api/status", {signal: controller.signal});
  controller.abort();
  await assert.rejects(request, {name: "AbortError"});
});

test("poller serializes refreshes even when restarted during a request", async () => {
  let calls = 0, active = 0, peak = 0;
  let release;
  const poller = createPoller(async () => {
    calls++; active++; peak = Math.max(peak, active);
    await new Promise(resolve => {release = resolve;});
    active--;
  }, 5);
  poller.start();
  poller.start();
  await sleep(15);
  assert.equal(calls, 1);
  release();
  await sleep(15);
  assert.equal(calls, 2);
  assert.equal(peak, 1);
  poller.stop();
  release();
  await sleep(15);
  assert.equal(calls, 2);
});

test("poller can recover after a refresh error", async () => {
  let calls = 0, errors = 0;
  const poller = createPoller(async () => {
    calls++;
    if (calls === 1) throw new Error("offline");
    poller.stop();
  }, 1, () => {errors++;});
  poller.start();
  await sleep(20);
  poller.stop();
  assert.equal(calls, 2);
  assert.equal(errors, 1);
});
