import { metricGeometry, metricGroup, preferredMetric, readableConsole, metricMeasurements } from "./metrics.js";
import { isBusy } from "./state.js";
import { api } from "./api.js";

const $ = id => document.getElementById(id);
const preferences = new Map();
const inspections = new Map();
const tabs = new Map();
const inspectionPanels = ["overview", "console", "files"];
let currentJob, rows = [], geometry = { values: [] }, truncated = false;
let rawLog = "", logSize = 0, files = [], fileTruncated = false, fileError = "", logError = "";
const number = value => Number(value.toPrecision(5)).toLocaleString(undefined, { maximumSignificantDigits: 5 });
function savedMetric(job) {
  try { return sessionStorage.getItem(`studio.metric.${job}`) || preferences.get(job); }
  catch { return preferences.get(job); }
}
function rememberMetric() {
  if (!currentJob) return;
  preferences.set(currentJob.id, $("metric").value);
  try { sessionStorage.setItem(`studio.metric.${currentJob.id}`, $("metric").value); } catch { /* Memory fallback. */ }
}
function metricOptions(keys, selected) {
  const signature = keys.join("\0");
  if ($("metric").dataset.keys !== signature) {
    $("metric").replaceChildren();
    for (const label of ["Training", "Performance", "Hardware", "Run metadata"]) {
      const group = document.createElement("optgroup");
      group.label = label;
      for (const key of keys.filter(key => metricGroup(key) === label)) group.append(new Option(key, key));
      if (group.children.length) $("metric").append(group);
    }
    $("metric").dataset.keys = signature;
  }
  if (selected) $("metric").value = selected;
  $("metric").disabled = !keys.length;
}

function inspect(index) {
  const point = geometry.values[index];
  $("metricPoint").toggleAttribute("hidden", !point);
  if (!point) { $("pointReadout").textContent = "No points to inspect"; return; }
  $("metricPoint").setAttribute("cx", point.px);
  $("metricPoint").setAttribute("cy", point.py);
  const label = `${geometry.xLabel} ${number(point.x)} · ${$("metric").value}: ${number(point.y)}`;
  $("pointReadout").textContent = label;
  $("metricScrubber").setAttribute("aria-valuetext", label);
}

export function plot() {
  geometry = metricGeometry(rows, $("metric").value);
  $("metricLine").setAttribute("d", geometry.path);
  const points = geometry.values;
  $("metricArea").setAttribute("d", points.length > 1 ? `${geometry.path} L${points.at(-1).px},150 L${points[0].px},150 Z` : "");
  $("chartEmpty").hidden = !!points.length;
  $("chartEmpty").textContent = isBusy(currentJob) ? "Waiting for metrics from this job…" : "No metrics found for this job.";
  $("metricValue").textContent = points.length ? number(points.at(-1).y) : "—";
  $("metricName").textContent = points.length ? $("metric").value : isBusy(currentJob) ? "Awaiting metrics" : "No recorded metrics";
  $("metricSummary").textContent = points.length ? geometry.summary + (truncated ? " · recent samples only" : "")
    : "Studio reads numeric JSONL or CSV metrics written into this job’s output directory.";
  $("axisMax").textContent = points.length ? number(geometry.maxY) : "";
  $("axisMin").textContent = points.length ? number(geometry.minY) : "";
  $("axisStart").textContent = points.length ? `${geometry.xLabel} ${number(geometry.minX)}` : "";
  $("axisEnd").textContent = points.length ? `${geometry.xLabel} ${number(geometry.maxX)}` : "";
  $("metricScrubber").disabled = !points.length;
  $("metricScrubber").max = Math.max(0, points.length - 1);
  const selectedX = inspections.get(`${currentJob?.id}:${$("metric").value}`);
  const index = selectedX === undefined || !points.length ? points.length - 1
    : points.reduce((best, point, i) => Math.abs(point.x - selectedX) < Math.abs(points[best].x - selectedX) ? i : best, 0);
  $("metricScrubber").value = Math.max(0, index);
  inspect(index);
  $("metricChart").setAttribute("aria-label", points.length ? `${$("metric").value} by ${geometry.xLabel.toLowerCase()}. ${geometry.summary}` : "No recorded metrics");
}

function renderSignals() {
  const measurements = metricMeasurements(rows);
  for (const group of ["performance", "hardware"]) {
    const list = $(group + "Signals");
    list.replaceChildren();
    for (const [label, value] of measurements[group]) {
      const item = document.createElement("div"), term = document.createElement("dt"), detail = document.createElement("dd");
      term.textContent = label; detail.textContent = value;
      detail.className = value === "—" || value === "— / —" ? "unavailable" : "";
      item.append(term, detail); list.append(item);
    }
  }
  $("measurementContext").textContent = isBusy(currentJob)
    ? "Latest measurements reported by this job. — means the trainer has not supplied a value."
    : "Recorded measurements from this finished job; these are not current machine readings. — means no value was supplied.";
}

function selectInspectionTab(name) {
  if (currentJob) tabs.set(currentJob.id, name);
  for (const item of inspectionPanels) {
    $(item + "Panel").hidden = item !== name;
    $(item + "Tab").setAttribute("aria-selected", String(item === name));
    $(item + "Tab").tabIndex = item === name ? 0 : -1;
  }
  if (name === "console") renderLog();
}

function renderLog() {
  const pre = $("logs"), query = $("logFilter").value.toLowerCase();
  const text = readableConsole(rawLog);
  const lines = text.split("\n"), matches = query ? lines.filter(line => line.toLowerCase().includes(query)) : lines;
  pre.textContent = logError || (query ? matches.join("\n") || "No matching console lines." : text || (isBusy(currentJob) ? "Waiting for console output…" : "No console output recorded for this job."));
  $("logInfo").textContent = logError ? "Console unavailable" : query ? `${matches.length} matching lines` : logSize > 65536 ? "Recent 64 KiB · progress updates collapsed" : "Progress updates collapsed";
  if ($("followLogs").checked) pre.scrollTop = pre.scrollHeight;
}

function renderFiles() {
  const list = $("artifacts"), query = $("artifactFilter").value.toLowerCase();
  list.replaceChildren();
  if (fileError) { list.textContent = fileError; return; }
  const matches = files.filter(file => file.path.toLowerCase().includes(query));
  const groups = new Map();
  for (const file of matches) {
    const slash = file.path.lastIndexOf("/"), directory = slash < 0 ? "Job output" : file.path.slice(0, slash);
    if (!groups.has(directory)) groups.set(directory, []);
    groups.get(directory).push(file);
  }
  for (const [directory, entries] of groups) {
    const li = document.createElement("li"), heading = document.createElement("p");
    heading.className = "file-group"; heading.textContent = `${directory} · ${entries.length}`; li.append(heading);
    for (const file of entries) {
      const link = document.createElement("a"), name = document.createElement("span"), size = document.createElement("span");
      name.className = "file-name"; name.textContent = file.path.split("/").at(-1);
      size.className = "file-size"; size.textContent = file.size < 1024 ? `${file.size} B` : file.size < 1048576 ? `${(file.size / 1024).toFixed(1)} KB` : `${(file.size / 1048576).toFixed(1)} MB`;
      link.title = file.path; link.setAttribute("aria-label", `Download ${file.path}`);
      link.href = api.jobs.artifactURL(currentJob.id, file.path); link.download = file.path.split("/").at(-1);
      link.append(name, size); li.append(link);
    }
    list.append(li);
  }
  if (!matches.length) list.textContent = query ? "No matching output files." : isBusy(currentJob) ? "Waiting for output files…" : "No output files found for this job.";
  if (fileTruncated) list.append("Showing a limited list. Refine your filter within the files returned by Studio.");
}

export function renderOutputs(job, [logs, metrics, artifacts]) {
  const switched = currentJob?.id !== job.id;
  currentJob = job;
  if (switched) {
    $("logFilter").value = ""; $("artifactFilter").value = ""; $("followLogs").checked = true;
  }
  rows = metrics.status === "fulfilled" ? metrics.value.items : [];
  truncated = metrics.status === "fulfilled" && metrics.value.truncated;
  const keys = [...new Set(rows.flatMap(row => Object.keys(row)))].filter(key => key !== "step" && rows.some(row => Number.isFinite(row[key])));
  metricOptions(keys, preferredMetric(keys, savedMetric(job.id)));
  plot(); renderSignals();
  if (metrics.status === "rejected") {
    $("metricName").textContent = "Metrics unavailable";
    $("chartEmpty").textContent = "Metrics unavailable. Job controls remain available.";
    $("metricSummary").textContent = `Metrics unavailable: ${metrics.reason.message}`;
  }
  rawLog = logs.status === "fulfilled" ? logs.value.text : "";
  logSize = logs.status === "fulfilled" ? logs.value.size || 0 : 0;
  logError = logs.status === "rejected" ? `Console unavailable: ${logs.reason.message}` : "";
  renderLog();
  files = artifacts.status === "fulfilled" ? artifacts.value.items : [];
  fileTruncated = artifacts.status === "fulfilled" && artifacts.value.truncated;
  fileError = artifacts.status === "rejected" ? `Artifacts unavailable: ${artifacts.reason.message}` : "";
  renderFiles();
  // Only change panels for a new selection. Polling never moves focus or tabs.
  if (switched) selectInspectionTab(tabs.get(job.id) || "overview");
}

export function bindOutputTools() {
  for (const [index, name] of inspectionPanels.entries()) {
    $(name + "Tab").onclick = () => selectInspectionTab(name);
    $(name + "Tab").onkeydown = event => {
      const next = event.key === "Home" ? 0 : event.key === "End" ? 2 : event.key === "ArrowRight" ? (index + 1) % 3 : event.key === "ArrowLeft" ? (index + 2) % 3 : null;
      if (next === null) return;
      event.preventDefault();
      selectInspectionTab(inspectionPanels[next]);
      $(inspectionPanels[next] + "Tab").focus();
    };
  }
  $("metric").onchange = () => { rememberMetric(); plot(); };
  const selectPoint = index => {
    const point = geometry.values[index];
    if (point) inspections.set(`${currentJob?.id}:${$("metric").value}`, point.x);
    inspect(index);
  };
  $("metricScrubber").oninput = () => selectPoint(Number($("metricScrubber").value));
  $("metricChart").onpointermove = event => {
    const rect = $("metricChart").getBoundingClientRect(), x = (event.clientX - rect.left) / rect.width * 600;
    if (!geometry.values.length) return;
    const nearest = geometry.values.reduce((best, point, index) => Math.abs(point.px - x) < Math.abs(geometry.values[best].px - x) ? index : best, 0);
    $("metricScrubber").value = nearest; selectPoint(nearest);
  };
  $("logFilter").oninput = renderLog;
  $("artifactFilter").oninput = renderFiles;
  $("followLogs").onchange = renderLog;
  $("logs").onscroll = () => {
    const pre = $("logs");
    $("followLogs").checked = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 30;
  };
  $("expandLogs").onclick = () => {
    const expanded = $("logs").classList.toggle("expanded");
    $("expandLogs").textContent = expanded ? "Collapse" : "Expand";
    $("expandLogs").setAttribute("aria-expanded", String(expanded));
  };
  $("copyLogs").onclick = async () => {
    try { await navigator.clipboard.writeText($("logs").textContent); $("logInfo").textContent = "Console copied"; }
    catch { $("logInfo").textContent = "Copy unavailable. Select console text to copy manually."; }
  };
}
