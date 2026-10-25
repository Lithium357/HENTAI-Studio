import {
  api
} from "./api.js";
import {
  createPoller
} from "./poller.js";
import {
  metricGeometry
} from "./metrics.js";
const $ = id => document.getElementById(id);
const active = job => job && ["starting", "running", "stopping"].includes(job.state);
let projects = [],
  jobs = [],
  projectId = null,
  jobId = null,
  rows = [],
  editing = false,
  busy = false,
  revision = 0;
const error = message => {
  $("notice").textContent = message;
  $("notice").hidden = !message;
};

function option(value, text = value) {
  return new Option(text, value);
}

function selectOptions(select, values, selected) {
  select.replaceChildren(...values.map(value => option(value)));
  if (values.includes(selected)) select.value = selected;
}

function project() {
  return projects.find(item => item.id === projectId);
}

function currentJob() {
  return jobs.find(item => item.id === jobId);
}

function controls() {
  const running = jobs.some(active),
    selected = currentJob();
  $("start").disabled = busy || running || !project();
  $("stop").disabled = busy || !active(selected) || selected?.state === "stopping";
  $("editProject").disabled = busy || running;
  $("removeProject").disabled = busy || running;
  $("resume").disabled = busy || running || !selected || active(selected);
  if ($("resume").disabled) $("resume").checked = false;
}

function renderProjects() {
  $("projects").replaceChildren(...projects.map(item => {
    const button = document.createElement("button");
    button.className = "project-item" + (item.id === projectId ? " selected" : "");
    button.textContent = item.name;
    button.onclick = () => {
      projectId = item.id;
      jobId = null;
      jobs = [];
      revision++;
      $("resume").checked = false;
      renderProjects();
      renderProject();
      poller.start();
    };
    return button;
  }));
}

function renderProject() {
  const item = project();
  $("empty").hidden = !!item;
  $("projectView").hidden = !item;
  if (!item) return;
  $("projectName").textContent = item.name;
  $("projectRoot").textContent = item.root;
  selectOptions($("command"), Object.keys(item.commands), $("command").value);
  renderJobs();
  controls();
}

function renderJobs() {
  $("jobs").replaceChildren(...jobs.map(job => {
    const button = document.createElement("button");
    button.className = "job-item" + (job.id === jobId ? " selected" : "");
    button.textContent = `${job.command} · ${job.state}`;
    const time = document.createElement("small");
    time.textContent = new Date(job.created_at).toLocaleString();
    button.append(time);
    button.onclick = () => {
      jobId = job.id;
      revision++;
      $("resume").checked = false;
      renderJobs();
      $("jobDetail").hidden = true;
      controls();
      poller.start();
    };
    return button;
  }));
  if (!jobs.length) $("jobs").textContent = "No jobs yet. Choose a command to begin.";
  if (!currentJob()) $("jobDetail").hidden = true;
}

function plot() {
  const geometry = metricGeometry(rows, $("metric").value);
  $("metricLine").setAttribute("d", geometry.path);
  $("metricSummary").textContent = geometry.summary;
}
async function refresh() {
  const initialRevision = revision;
  const [health, listing] = await Promise.all([api.health(), api.projects.list()]);
  if (revision !== initialRevision) return;
  projects = listing.items;
  if (!projects.some(p => p.id === projectId)) {
    projectId = projects[0]?.id || null;
    jobId = null;
  }
  $("workspace").textContent = health.workspace;
  $("connection").textContent = `Connected · v${health.version}`;
  error("");
  renderProjects();
  if (!projectId) {
    renderProject();
    return;
  }
  const selectedProject = projectId;
  const listingJobs = await api.jobs.list(selectedProject);
  if (revision !== initialRevision || selectedProject !== projectId) return;
  jobs = listingJobs.items;
  if (!jobs.some(job => job.id === jobId)) jobId = jobs[0]?.id || null;
  renderProject();
  if (!jobId) return;
  const selectedJob = jobId;
  const [job, logs, metrics, artifacts] = await Promise.all([api.jobs.get(selectedJob), api.jobs.logs(selectedJob), api.jobs.metrics(selectedJob), api.jobs.artifacts(selectedJob)]);
  if (revision !== initialRevision || selectedJob !== jobId) return;
  jobs = jobs.map(item => item.id === job.id ? job : item);
  $("jobDetail").hidden = false;
  renderJobs();
  controls();
  $("jobTitle").textContent = job.command;
  $("jobId").textContent = job.id;
  $("jobState").textContent = `${job.state}${job.exit_code !== null ? ` · exit ${job.exit_code}` : ""}`;
  $("jobError").textContent = job.error || "";
  $("jobTiming").textContent = `Created ${new Date(job.created_at).toLocaleString()}${job.finished_at ? ` · Finished ${new Date(job.finished_at).toLocaleString()}` : ""}`;
  $("resumeSource").textContent = job.resume_from ? `Resume source: ${job.resume_from}` : "";
  rows = metrics.items;
  const keys = [...new Set(rows.flatMap(row => Object.keys(row)))].filter(key => key !== "step");
  selectOptions($("metric"), keys, $("metric").value);
  plot();
  if (metrics.truncated) $("metricSummary").textContent += " · showing recent metrics";
  const atBottom = $("logs").scrollTop + $("logs").clientHeight >= $("logs").scrollHeight - 30;
  $("logs").textContent = logs.text || "Waiting for console output…";
  if (atBottom) $("logs").scrollTop = $("logs").scrollHeight;
  $("artifacts").replaceChildren(...artifacts.items.map(item => {
    const li = document.createElement("li"),
      link = document.createElement("a");
    link.textContent = `${item.path} (${item.size.toLocaleString()} bytes)`;
    link.href = api.jobs.artifactURL(job.id, item.path);
    link.download = item.path.split("/").at(-1);
    li.append(link);
    return li;
  }));
  if (!artifacts.items.length) $("artifacts").textContent = "No output files yet.";
  if (artifacts.truncated) $("artifacts").append("Showing the first 2,000 files.");
}
const poller = createPoller(refresh, 2000, failure => {
  $("connection").textContent = "Disconnected";
  error(failure.message);
});
async function action(task) {
  if (busy) return;
  busy = true;
  controls();
  error("");
  try {
    await task();
    revision++;
    poller.start();
  } catch (failure) {
    error(failure.message);
  } finally {
    busy = false;
    controls();
  }
}

function openEditor(update = false) {
  editing = update;
  const item = update ? project() : {
    id: "",
    name: "",
    root: "",
    commands: {
      train: ["/path/to/project/.venv/bin/python", "train.py", "--output", "{output_dir}"]
    },
    environment: {},
    metrics_file: "metrics.jsonl"
  };
  $("editorTitle").textContent = update ? "Edit project" : "Register project";
  $("fieldId").value = item.id;
  $("fieldId").disabled = update;
  $("fieldName").value = item.name;
  $("fieldRoot").value = item.root;
  $("fieldCommands").value = JSON.stringify(item.commands, null, 2);
  $("fieldEnv").value = JSON.stringify(item.environment, null, 2);
  $("fieldMetrics").value = item.metrics_file;
  $("formError").textContent = "";
  $("editor").showModal();
}
$("addProject").onclick = () => openEditor();
$("emptyAdd").onclick = () => openEditor();
$("editProject").onclick = () => openEditor(true);
$("closeEditor").onclick = () => $("editor").close();
$("projectForm").onsubmit = async event => {
  event.preventDefault();
  $("saveProject").disabled = true;
  try {
    const item = {
      id: $("fieldId").value,
      name: $("fieldName").value,
      root: $("fieldRoot").value,
      commands: JSON.parse($("fieldCommands").value),
      environment: JSON.parse($("fieldEnv").value),
      metrics_file: $("fieldMetrics").value
    };
    await api.projects.save(item, editing);
    projectId = item.id;
    jobId = null;
    jobs = [];
    revision++;
    $("editor").close();
    poller.start();
  } catch (failure) {
    $("formError").textContent = failure.message;
  } finally {
    $("saveProject").disabled = false;
  }
};
$("removeProject").onclick = () => {
  if (confirm("Unregister this project? Project files and job history will be kept.")) void action(async () => {
    await api.projects.remove(projectId);
    projectId = null;
    jobId = null;
    jobs = [];
  });
};
$("start").onclick = () => {
  const selected = projectId,
    command = $("command").value,
    source = $("resume").checked ? jobId : null;
  void action(async () => {
    const job = await api.jobs.start(selected, command, source);
    if (projectId === selected) {
      jobId = job.id;
      jobs.unshift(job);
    }
    $("resume").checked = false;
  });
};
$("stop").onclick = () => {
  const selected = jobId;
  void action(() => api.jobs.stop(selected));
};
$("refresh").onclick = () => poller.start();
$("metric").onchange = plot;
document.addEventListener("visibilitychange", () => document.hidden ? poller.stop() : poller.start());
window.addEventListener("pagehide", () => poller.stop());
poller.start();
