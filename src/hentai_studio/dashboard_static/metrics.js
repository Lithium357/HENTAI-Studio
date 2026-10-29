export function metricGeometry(rows, key, width = 600, height = 150) {
  const values = rows.map((row, index) => ({
    x: Number.isFinite(row.step) ? row.step : index,
    y: row[key]
  })).filter(p => Number.isFinite(p.y));
  if (!values.length) return {
    path: "", values: [],
    summary: "No metrics yet."
  };
  const xs = values.map(p => p.x),
    ys = values.map(p => p.y);
  const minX = Math.min(...xs),
    maxX = Math.max(...xs),
    minY = Math.min(...ys),
    maxY = Math.max(...ys);
  for (const p of values) {
    p.px = 10 + (p.x-minX)/(maxX-minX || 1)*(width-20);
    p.py = maxY === minY ? height / 2 : height-10-(p.y-minY)/(maxY-minY)*(height-20);
  }
  const path = values.map((p, i) => `${i ? "L" : "M"}${p.px.toFixed(1)},${p.py.toFixed(1)}`).join(" ");
  return {
    path, values, minX, maxX, minY, maxY,
    xLabel: rows.every(row => Number.isFinite(row.step)) ? "Step" : "Sample",
    summary: `${key}: ${ys.at(-1).toPrecision(5)} · ${values.length} points · range ${minY.toPrecision(4)}–${maxY.toPrecision(4)}`
  };
}

export function metricGroup(key) {
  if (/^(gpu_|process_|cpu_|.*vram|.*ram_mb)/i.test(key)) return "Hardware";
  if (/^(resumed_from_step|total_steps|effective_batch_size|timestamp_unix|seed)$/i.test(key)) return "Run metadata";
  if (/^(.*per_second|seconds_per_.*|eta_.*|remaining_.*|progress_.*|images_seen|tokens_seen)$/i.test(key)) return "Performance";
  return "Training";
}

export function preferredMetric(keys, saved) {
  if (keys.includes(saved)) return saved;
  return ["loss", "train_loss", "training_loss", "eval_loss", "accuracy"].find(key => keys.includes(key))
    || keys.find(key => metricGroup(key) === "Training") || keys[0];
}

// Carriage returns redraw a terminal line. Keep the last update on each line,
// preserve newline-delimited diagnostics, and remove non-printing ANSI controls.
export function readableConsole(text) {
  return text.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, "").replace(/\r\n/g, "\n")
    .split("\n").map(line => line.split("\r").filter(Boolean).at(-1) || "").join("\n");
}
