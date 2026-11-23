import test from "node:test";
import assert from "node:assert/strict";
import { hardwareText } from "../../src/hentai_studio/dashboard_static/hardware-ui.js";

test("live hardware is explicit about backend scope, freshness, and unavailable sensors", () => {
  const text = hardwareText({ scope: "backend_host", hostname: "aws-trainer", platform: "Linux", sampled_at: "today", age_seconds: 20, stale: true, cpu_pct: 0, ram_used_mb: 100, ram_total_mb: 200,
    gpus: [{name:"Arc", vendor:"Intel", source:"Windows", utilization_pct:0, temperature_c:null, power_w:null}], issues:["Sensor unavailable"] });
  assert.match(text, /aws-trainer/);
  assert.match(text, /STALE/);
  assert.match(text, /CPU 0%/);
  assert.match(text, /Arc \(Intel\) · 0%/);
  assert.match(text, /· — · — · Windows/);
  assert.match(text, /Sensor unavailable/);
  assert.throws(() => hardwareText({}), /Invalid hardware response/);
});
