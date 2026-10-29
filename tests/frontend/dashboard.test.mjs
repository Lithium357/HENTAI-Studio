import test from "node:test";
import assert from "node:assert/strict";
import {
  metricGeometry, preferredMetric, readableConsole, metricMeasurements
} from "../../src/hentai_studio/dashboard_static/metrics.js";
import {
  requestJSON,
  api
} from "../../src/hentai_studio/dashboard_static/api.js";
import {
  createPoller
} from "../../src/hentai_studio/dashboard_static/poller.js";
import { launchDefinition } from "../../src/hentai_studio/dashboard_static/launch.js";

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

test("launch definitions expand only known paths and preserve exact argument boundaries", () => {
  const project = { root: "/project with spaces", commands: { train: ["{project_root}/.venv/bin/python", "train.py", "--output", "{output_dir}", "argument with spaces"] } };
  assert.deepEqual(launchDefinition(project, "train"), ["/project with spaces/.venv/bin/python", "train.py", "--output", "{output_dir}", "argument with spaces"]);
  assert.deepEqual(launchDefinition(null, "train"), []);
});

test("measurements preserve zero and distinguish absent telemetry from a real reading", () => {
  const result = metricMeasurements([{ step: 0, progress_percent: 0, gpu_usage_pct: 0, eta_seconds: 3661 }]);
  assert.deepEqual(result.performance[0], ["Step", "0 / —"]);
  assert.deepEqual(result.performance[1], ["Progress", "0%"]);
  assert.deepEqual(result.performance[4], ["Estimated remaining", "1h 1m"]);
  assert.deepEqual(result.hardware[0], ["GPU utilization", "0%"]);
  assert.deepEqual(result.hardware[1], ["VRAM", "—"]);
});

test("metric defaults prefer loss over metadata and preserve a valid selection", () => {
  const keys = ["resumed_from_step", "total_steps", "loss", "gpu_usage_pct"];
  assert.equal(preferredMetric(keys), "loss");
  assert.equal(preferredMetric(keys, "gpu_usage_pct"), "gpu_usage_pct");
  assert.equal(preferredMetric(keys, "missing"), "loss");
  assert.equal(preferredMetric([]), undefined);
});

test("terminal progress redraws collapse without swallowing warnings or CRLF logs", () => {
  assert.equal(readableConsole("start\r\n\x1b[32mstep 1\rstep 2\rstep 3\x1b[0m\nWARNING: check data\n"), "start\nstep 3\nWARNING: check data\n");
  assert.equal(readableConsole("\rprogress 1\rprogress 2\r"), "progress 2");
});

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


test("browser client follows pages and uses PATCH and the canonical job routes", async t => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({
      path,
      options
    });
    const page = path === "/api/projects" ? {
        items: [{
          id: "one"
        }],
        next_cursor: "opaque=="
      } :
      path.startsWith("/api/projects?cursor=") ? {
        items: [{
          id: "two"
        }],
        next_cursor: null
      } : {
        id: "saved"
      };
    return {
      ok: true,
      status: 200,
      json: async () => page
    };
  });
  assert.deepEqual((await api.projects.list()).items.map(item => item.id), ["one", "two"]);
  assert.equal(calls[1].path, "/api/projects?cursor=opaque%3D%3D");
  await api.projects.save({
    id: "one",
    name: "Changed"
  }, true);
  assert.equal(calls.at(-1).options.method, "PATCH");
  assert.deepEqual(JSON.parse(calls.at(-1).options.body), {
    name: "Changed"
  });
  await api.jobs.start("one", "train");
  assert.equal(calls.at(-1).path, "/api/jobs");
  assert.deepEqual(JSON.parse(calls.at(-1).options.body), {
    project_id: "one",
    command: "train"
  });
  await api.jobs.start("one", "resume", "old-job");
  assert.equal(calls.at(-1).path, "/api/jobs/old-job/resume");
});
