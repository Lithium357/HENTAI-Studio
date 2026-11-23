import { requestJSON } from "./api.js";
import { createPoller } from "./poller.js";

const value = (number, unit = "") => Number.isFinite(number) ? `${number.toLocaleString(undefined, { maximumFractionDigits: 1 })}${unit}` : "—";
export function hardwareText(snapshot) {
  if (snapshot.scope !== "backend_host") throw new Error("Invalid hardware response");
  const lines = [
    `${snapshot.hostname} · ${snapshot.platform} · ${snapshot.collecting ? "Collecting first sample…" : `Sampled ${snapshot.sampled_at} · age ${value(snapshot.age_seconds, "s")}${snapshot.stale ? " · STALE" : ""}`}`,
    `CPU ${value(snapshot.cpu_pct, "%")} · RAM ${value(snapshot.ram_used_mb)} / ${value(snapshot.ram_total_mb, " MiB")}`,
  ];
  for (const gpu of snapshot.gpus || []) lines.push(
    `${gpu.name} (${gpu.vendor}) · ${value(gpu.utilization_pct, "%")} · dedicated ${value(gpu.memory_used_mb)} / ${value(gpu.memory_total_mb, " MiB")} · shared ${value(gpu.shared_memory_mb, " MiB")} · ${value(gpu.temperature_c, " °C")} · ${value(gpu.power_w, " W")} · ${gpu.source}`
  );
  lines.push(...snapshot.issues || []);
  return lines.join("\n");
}

export function bindHardware() {
  const output = document.getElementById("hostHardwareText");
  let controller;
  const poller = createPoller(async () => {
    controller = new AbortController();
    const snapshot = await requestJSON("/api/hardware", { signal: controller.signal, timeout: 5000 });
    output.textContent = hardwareText(snapshot);
  }, 4000, error => { if (error.name !== "AbortError") output.textContent = "Hardware unavailable: " + error.message; });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { controller?.abort(); poller.stop(); } else poller.start();
  });
  window.addEventListener("pagehide", () => { controller?.abort(); poller.stop(); });
  poller.start();
}
