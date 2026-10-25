import test from "node:test";
import assert from "node:assert/strict";
import {
  metricGeometry
} from "../../src/hentai_studio/dashboard_static/metrics.js";
import {
  requestJSON,
  api
} from "../../src/hentai_studio/dashboard_static/api.js";
import {
  createPoller
} from "../../src/hentai_studio/dashboard_static/poller.js";

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

test("arbitrary metrics use actual step positions and discard invalid values", () => {
  const result = metricGeometry([{
    step: 0,
    accuracy: .1
  }, {
    step: 1,
    accuracy: .2
  }, {
    step: 10,
    accuracy: .9
  }], "accuracy", 120, 100);
  assert.match(result.path, /L20.0,/);
  assert.match(result.path, /L110.0,/);
  assert.match(result.summary, /accuracy/);
  assert.equal(metricGeometry([{
    loss: NaN
  }], "loss").path, "");
  assert.ok(!metricGeometry([{
    loss: 1
  }, {
    loss: 1
  }], "loss").path.includes("NaN"));
});

test("API reports server errors and encodes selected job IDs", async t => {
  let requested;
  t.mock.method(globalThis, "fetch", async (path, options) => {
    requested = {
      path,
      options
    };
    return {
      ok: false,
      status: 400,
      json: async () => ({
        error: {
          code: "checkpoint_incomplete",
          message: "checkpoint incomplete"
        }
      })
    };
  });
  await assert.rejects(api.jobs.get("job/name"), /checkpoint incomplete/);
  assert.equal(requested.path, "/api/jobs/job%2Fname");
  assert.equal(requested.options.cache, "no-store");
});

test("API propagates cancellation to the underlying fetch", async t => {
  t.mock.method(globalThis, "fetch", (path, {
    signal
  }) => new Promise((resolve, reject) => {
    signal.addEventListener("abort", () => reject(signal.reason), {
      once: true
    });
  }));
  const controller = new AbortController();
  const request = requestJSON("/api/health", {
    signal: controller.signal
  });
  controller.abort();
  await assert.rejects(request, {
    name: "AbortError"
  });
});

test("poller serializes refreshes even when restarted during a request", async () => {
  let calls = 0,
    active = 0,
    peak = 0;
  let release;
  const poller = createPoller(async () => {
    calls++;
    active++;
    peak = Math.max(peak, active);
    await new Promise(resolve => {
      release = resolve;
    });
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
  let calls = 0,
    errors = 0;
  const poller = createPoller(async () => {
    calls++;
    if (calls === 1) throw new Error("offline");
    poller.stop();
  }, 1, () => {
    errors++;
  });
  poller.start();
  await sleep(20);
  poller.stop();
  assert.equal(calls, 2);
  assert.equal(errors, 1);
});

test("project definitions are submitted as argument arrays and artifacts encode each segment", async t => {
  let request;
  t.mock.method(globalThis, "fetch", async (path, options) => {
    request = {
      path,
      options
    };
    return {
      ok: true,
      status: 201,
      json: async () => ({
        id: "my-project"
      })
    };
  });
  await api.projects.save({
    id: "my-project",
    commands: {
      train: ["python", "train.py"]
    }
  });
  assert.equal(request.path, "/api/projects");
  assert.deepEqual(JSON.parse(request.options.body).commands.train, ["python", "train.py"]);
  assert.equal(api.jobs.artifactURL("job", "a b/weights#.bin"), "/api/jobs/job/artifacts/a%20b/weights%23.bin");
});
