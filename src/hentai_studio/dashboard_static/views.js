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
  $("connection").textContent = state.connected ? `Connected · v${state.health?.version || ""}` : "Disconnected";
}

export function renderWorkspace(state, {
  selectProject,
  selectJob
}) {
  const all = document.createElement("button");
  all.textContent = "All jobs";
  all.className = "project-item" + (state.projectId === null ? " selected" : "");
  all.onclick = () => selectProject(null);
  $("projects").replaceChildren(all, ...state.projects.map(project => {
    const button = document.createElement("button");
    button.className = "project-item" + (project.id === state.projectId ? " selected" : "");
    button.textContent = project.name;
    button.onclick = () => selectProject(project.id);
    return button;
  }));
  $("workspace").textContent = state.health?.workspace || "";
  const empty = !state.projects.length && !state.jobs.length;
  $("empty").hidden = !empty;
  $("projectView").hidden = empty;
  $("projectName").textContent = state.project?.name || "All jobs";
  $("projectRoot").textContent = state.project?.root || "History across your workspace, including unregistered projects";
  $("launchPanel").hidden = !state.project;
  $("projectActions").hidden = !state.project;
  selectOptions($("command"), Object.keys(state.project?.commands || {}), state.command);
  $("jobs").replaceChildren(...state.jobs.map(job => {
    const button = document.createElement("button");
    button.className = "job-item" + (job.id === state.jobId ? " selected" : "");
    button.textContent = `${state.projectId ? "" : job.project.name + " · "}${job.command} · ${job.state}${job.has_live_processes && !["running", "starting", "stopping"].includes(job.state) ? " · processes remain" : ""}`;
    const time = document.createElement("small");
    time.textContent = new Date(job.created_at).toLocaleString();
    button.append(time);
    button.onclick = () => selectJob(job.id);
    return button;
  }));
  if (!state.jobs.length) $("jobs").textContent = state.loading ? "Loading jobs…" : "No jobs yet.";
  if (!state.job) $("jobDetail").hidden = true;
  renderControls(state);
}

let rows = [];
let truncated = false;
export function plot() {
  const result = metricGeometry(rows, $("metric").value);
  $("metricLine").setAttribute("d", result.path);
  $("metricSummary").textContent = result.summary + (truncated ? " · showing recent metrics" : "");
}

export function renderDetails(job, results) {
  $("jobDetail").hidden = false;
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
    plot();
  } else {
    rows = [];
    $("metricLine").setAttribute("d", "");
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
      link.textContent = `${artifact.path} (${artifact.size.toLocaleString()} bytes)`;
      link.href = api.jobs.artifactURL(job.id, artifact.path);
      link.download = artifact.path.split("/").at(-1);
      li.append(link);
      $("artifacts").append(li);
    }
    if (!artifacts.value.items.length) $("artifacts").textContent = "No output files yet.";
    if (artifacts.value.truncated) $("artifacts").append("Showing a limited list of output files.");
  } else $("artifacts").textContent = `Artifacts unavailable: ${artifacts.reason.message}`;
}
