import {
  isBusy
} from "./state.js";
import { renderOutputs } from "./output-ui.js";
import { renderLaunch } from "./launch.js";
export const $ = id => document.getElementById(id);

export function selectOptions(select, values, selected) {
  // Avoid replacing a focused dropdown on every poll.
  if ([...select.options].map(option => option.value).join("\0") !== values.join("\0"))
    select.replaceChildren(...values.map(value => new Option(value, value)));
  if (values.includes(selected)) select.value = selected;
}

export function renderControls(state) {
  renderLaunch(state);
  const target = state.stopTarget;
  $("stop").disabled = !state.canStop;
  $("stop").classList.toggle("available", state.canStop);
  $("stop").lastChild.textContent = target?.state === "stopping" ? " Stopping…" : " Stop job";
  $("controlTarget").textContent = target ? `${target.project_name} · ${target.command} · ${target.id.slice(0, 8)}` : "No job selected";
  $("controlHint").textContent = !state.connected ? "Disconnected — job state cannot be verified. Reconnect to control jobs."
    : state.busy ? "Applying your action…" : state.loading ? "Loading job state…"
    : target?.state === "stopping" ? "Stop requested. Waiting for the process tree to exit."
    : isBusy(target) ? "Stops this job’s process tree. A final checkpoint is not guaranteed."
    : target ? `This job is ${target.state}. No active process to stop.` : "Select an active job to stop it.";
  $("editProject").disabled = !state.canEdit;
  $("removeProject").disabled = !state.canEdit;
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
  const query = $("jobFilter").value.toLowerCase();
  const visibleJobs = state.jobs.filter(job => `${job.command} ${job.state} ${job.project_name} ${job.id}`.toLowerCase().includes(query));
  syncButtons($("jobs"), visibleJobs, job => job.id, (button, job) => {
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
    button.append(element("small", "job-history-meta", `${job.id.slice(0, 8)} · ${duration(job)}`));
    if (job.has_live_processes && !["running", "starting", "stopping"].includes(job.state)) button.append(element("small", "error", "Processes remain"));
    button.onclick = () => selectJob(job.id);
  });
  if (!visibleJobs.length) $("jobs").replaceChildren(element("p", "hint", state.loading ? "Loading jobs…" : query ? "No matching jobs." : "No jobs yet. Your runs will appear here."));
  $("noJob").hidden = !!state.job;
  if (!state.job) $("jobDetail").hidden = true;
  if (state.job) renderJobSummary(state.job, state.jobs, selectJob);
  renderControls(state);
}

export function duration(job) {
  const start = Date.parse(job.started_at || job.created_at);
  const finish = job.finished_at ? Date.parse(job.finished_at) : Date.now();
  if (!Number.isFinite(start) || !Number.isFinite(finish)) return "Duration unavailable";
  const seconds = Math.max(0, Math.floor((finish - start) / 1000));
  return seconds >= 3600 ? `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m` : seconds >= 60 ? `${Math.floor(seconds / 60)}m ${seconds % 60}s` : `${seconds}s`;
}

function renderJobSummary(job, jobs, selectJob) {
  $("jobTitle").textContent = `${job.command} · ${new Date(job.created_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}`;
  $("jobDuration").textContent = `${duration(job)} ${job.finished_at ? "elapsed" : "so far"}`;
  $("jobState").dataset.state = job.state;
  $("jobState").textContent = `${job.state}${job.exit_code != null ? ` · exit ${job.exit_code}` : ""}${job.has_live_processes && !["running", "starting", "stopping"].includes(job.state) ? " · processes remain" : ""}`;
  $("jobId").textContent = job.id;
  $("jobError").textContent = job.error || "";
  $("jobTiming").textContent = `Created ${new Date(job.created_at).toLocaleString()}${job.finished_at ? ` · Finished ${new Date(job.finished_at).toLocaleString()}` : ""}`;
  const source = jobs.find(item => item.id === job.resume_from);
  $("resumeSource").hidden = !job.resume_from;
  $("resumeSource").textContent = job.resume_from ? `Resume source: ${source ? `${source.command} · ${new Date(source.created_at).toLocaleString()}` : job.resume_from.slice(0, 8)} ↗` : "";
  $("resumeSource").disabled = !source;
  $("resumeSource").title = job.resume_from || "";
  $("resumeSource").onclick = () => { if (source) selectJob(source.id); };
}

export function renderDetails(job, results) {
  $("jobDetail").hidden = false;
  $("noJob").hidden = true;
  renderOutputs(job, results);
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
