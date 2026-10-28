import {
  isBusy
} from "./state.js";
import {
  metricGeometry
} from "./metrics.js";
import {
  api
} from "./api.js";
export const $ = id => document.getElementById(id);

export function selectOptions(select, values, selected) {
  // Avoid replacing a focused dropdown on every poll.
  if ([...select.options].map(option => option.value).join("\0") !== values.join("\0"))
    select.replaceChildren(...values.map(value => new Option(value, value)));
  if (values.includes(selected)) select.value = selected;
}

export function renderControls(state) {
  $("start").disabled = !state.canStart;
  $("stop").disabled = !state.canStop;
  $("editProject").disabled = !state.canEdit;
  $("removeProject").disabled = !state.canEdit;
  $("resume").disabled = !state.canResume;
  if (!state.canResume) $("resume").checked = false;
  $("addProject").disabled = state.busy || !state.connected || !!state.issues.length;
  $("emptyAdd").disabled = $("addProject").disabled;
  const notices = [state.actionError, state.connectionError,
    ...state.issues.map(issue => `${issue.resource}: ${issue.message}`)
  ].filter(Boolean);
  $("notice").textContent = notices.join("\n");
  $("notice").hidden = !notices.length;
  $("connection").dataset.connected = String(state.connected);
  $("connection").title = state.connected ? "Studio is connected" : "Studio is disconnected";
  $("connection").textContent = state.connected ? `Connected · v${state.health?.version || ""}` : "Disconnected";
}

export function renderWorkspace(state, {
  selectProject,
  selectJob
}) {
  const projects = [{
    id: null,
    name: "All jobs"
  }, ...state.projects];
  syncButtons($("projects"), projects, project => project.id ?? "__all__", (button, project) => {
    button.className = "project-item" + (project.id === state.projectId ? " selected" : "");
    button.setAttribute("aria-current", project.id === state.projectId ? "page" : "false");
    button.replaceChildren(element("span", "nav-icon", project.id ? "◇" : "▦"), element("span", "nav-name", project.name));
    if (project.id === state.projectId) button.append(element("span", "count", String(state.jobs.length)));
    button.onclick = () => selectProject(project.id);
  });
  $("workspace").textContent = state.health?.workspace || "";
  const empty = !state.projects.length && !state.jobs.length;
  $("empty").hidden = !empty;
  $("projectView").hidden = empty;
  $("projectName").textContent = state.project?.name || "All jobs";
  $("projectRoot").textContent = state.project?.root || "History across your workspace, including unregistered projects";
  $("launchPanel").hidden = !state.project;
  $("projectActions").hidden = !state.project;
  selectOptions($("command"), Object.keys(state.project?.commands || {}), state.command);
  $("breadcrumbName").textContent = state.project?.name || "Overview";
  $("viewEyebrow").textContent = state.project ? "PROJECT WORKSPACE" : "WORKSPACE OVERVIEW";
  $("scopeLabel").textContent = state.project ? "Available commands" : "Registered projects";
  $("projectCount").textContent = state.project ? Object.keys(state.project.commands).length : state.projects.length;
  $("activeCount").textContent = state.jobs.filter(isBusy).length;
  $("completedCount").textContent = state.jobs.filter(job => !isBusy(job)).length;
  $("jobCount").textContent = state.jobs.length;
  syncButtons($("jobs"), state.jobs, job => job.id, (button, job) => {
    button.className = "job-item" + (job.id === state.jobId ? " selected" : "");
    button.setAttribute("aria-pressed", String(job.id === state.jobId));
    const row = element("span", "job-row");
    const badge = element("span", "status", job.state);
    badge.dataset.state = job.state;
    row.append(element("span", "job-command", job.command), badge);
    button.replaceChildren(row);
    if (!state.projectId) button.append(element("span", "job-project", job.project_name));
    button.append(element("small", "", new Date(job.created_at).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    })));
    if (job.has_live_processes && !["running", "starting", "stopping"].includes(job.state)) button.append(element("small", "error", "Processes remain"));
    button.onclick = () => selectJob(job.id);
  });
  if (!state.jobs.length) $("jobs").replaceChildren(element("p", "hint", state.loading ? "Loading jobs…" : "No jobs yet. Your runs will appear here."));
  $("noJob").hidden = !!state.job;
  if (!state.job) $("jobDetail").hidden = true;
  renderControls(state);
}

let rows = [];
let truncated = false;
export function plot() {
  const result = metricGeometry(rows, $("metric").value);
  $("metricLine").setAttribute("d", result.path);
  const points = result.path.match(/(?:M|L)([\d.-]+),([\d.-]+)/g) || [];
  const firstX = points[0]?.slice(1).split(",")[0];
  const lastX = points.at(-1)?.slice(1).split(",")[0];
  $("metricArea").setAttribute("d", points.length > 1 ? `${result.path} L${lastX},150 L${firstX},150 Z` : "");
  $("chartEmpty").hidden = !!result.path;
  const key = $("metric").value;
  const latest = rows.filter(row => Number.isFinite(row[key])).at(-1)?.[key];
  $("metricValue").textContent = latest === undefined ? "—" : Number(latest.toPrecision(5)).toLocaleString(undefined, {
    maximumSignificantDigits: 5
  });
  $("metricName").textContent = latest === undefined ? "Awaiting metrics" : key;
  $("metricSummary").textContent = result.summary + (truncated ? " · showing recent metrics" : "");
}

export function renderDetails(job, results) {
  $("jobDetail").hidden = false;
  $("noJob").hidden = true;
  $("jobState").dataset.state = job.state;
  $("jobTitle").textContent = job.command;
  $("jobId").textContent = job.id;
  $("jobState").textContent = `${job.state}${job.exit_code !== null ? ` · exit ${job.exit_code}` : ""}${job.has_live_processes && !["running", "starting", "stopping"].includes(job.state) ? " · training processes remain; use Stop job" : ""}`;
  $("jobError").textContent = job.error || "";
  $("jobTiming").textContent = `Created ${new Date(job.created_at).toLocaleString()}${job.finished_at ? ` · Finished ${new Date(job.finished_at).toLocaleString()}` : ""}`;
  $("resumeSource").textContent = job.resume_from ? `Resume source: ${job.resume_from}` : "";
  const [logs, metrics, artifacts] = results;
  if (metrics.status === "fulfilled") {
    rows = metrics.value.items;
    truncated = metrics.value.truncated;
    const keys = [...new Set(rows.flatMap(row => Object.keys(row)))].filter(key => key !== "step");
    selectOptions($("metric"), keys, $("metric").value);
    $("metric").disabled = !keys.length;
    plot();
  } else {
    rows = [];
    $("metric").disabled = true;
    $("metricLine").setAttribute("d", "");
    $("metricArea").setAttribute("d", "");
    $("metricValue").textContent = "—";
    $("metricName").textContent = "Metrics unavailable";
    $("chartEmpty").hidden = false;
    $("metricSummary").textContent = `Metrics unavailable: ${metrics.reason.message}`;
  }
  if (logs.status === "fulfilled") {
    const atBottom = $("logs").scrollTop + $("logs").clientHeight >= $("logs").scrollHeight - 30;
    $("logs").textContent = logs.value.text || (isBusy(job) ? "Waiting for console output…" : "No console output.");
    if (atBottom) $("logs").scrollTop = $("logs").scrollHeight;
  } else $("logs").textContent = `Console unavailable: ${logs.reason.message}`;
  $("artifacts").replaceChildren();
  if (artifacts.status === "fulfilled") {
    for (const artifact of artifacts.value.items) {
      const li = document.createElement("li"),
        link = document.createElement("a");
      const size = artifact.size < 1024 ? `${artifact.size} B` : artifact.size < 1048576 ? `${(artifact.size / 1024).toFixed(1)} KB` : `${(artifact.size / 1048576).toFixed(1)} MB`;
      link.append(element("span", "file-icon", "▤"), element("span", "file-name", artifact.path), element("span", "file-size", size), element("span", "file-download", "↓"));
      link.href = api.jobs.artifactURL(job.id, artifact.path);
      link.download = artifact.path.split("/").at(-1);
      li.append(link);
      $("artifacts").append(li);
    }
    if (!artifacts.value.items.length) $("artifacts").textContent = "No output files yet.";
    if (artifacts.value.truncated) $("artifacts").append("Showing a limited list of output files.");
  } else $("artifacts").textContent = `Artifacts unavailable: ${artifacts.reason.message}`;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  node.className = className;
  if (["nav-icon", "file-icon", "file-download"].includes(className)) node.setAttribute("aria-hidden", "true");
  node.textContent = text;
  return node;
}

// Keep keyed buttons mounted so polling preserves keyboard focus and scroll.
function syncButtons(container, items, key, render) {
  const existing = new Map([...container.children].filter(node => node.tagName === "BUTTON").map(node => [node.dataset.key, node]));
  const keys = new Set(items.map(item => String(key(item))));
  for (const node of [...container.children])
    if (!keys.has(node.dataset.key)) node.remove();
  items.forEach((item, index) => {
    const id = String(key(item));
    const button = existing.get(id) || document.createElement("button");
    button.dataset.key = id;
    render(button, item);
    if (container.children[index] !== button) container.insertBefore(button, container.children[index] || null);
  });
}
