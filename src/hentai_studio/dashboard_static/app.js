import {
  bindChat
} from "./chat.js";
import {
  api
} from "./api.js";
import {
  createPoller
} from "./poller.js";
import {
  WorkspaceState
} from "./state.js";
import {
  $,
  renderControls,
  renderWorkspace,
  renderDetails
} from "./views.js";
import { bindOutputTools } from "./output-ui.js";
import {
  bindProjectEditor
} from "./editor.js";

const state = new WorkspaceState();
bindOutputTools();
const chat = bindChat(() => state);
let controller;
const callbacks = {
  selectProject(id) {
    state.selectProject(id);
    changed();
  },
  selectJob(id) {
    state.selectJob(id);
    changed();
  },
};

function render() {
  renderWorkspace(state, callbacks);
  chat.render();
}

function changed() {
  controller?.abort();
  $("resume").checked = false;
  $("jobDetail").hidden = true;
  render();
  poller.start();
}
async function refresh() {
  const revision = state.revision;
  controller = new AbortController();
  const options = {
    signal: controller.signal
  };
  const [health, projects, jobs] = await Promise.all([
    api.health(options), api.projects.list(options), api.jobs.list(state.projectId, options),
  ]);
  if (state.revision !== revision) return;
  state.health = health;
  state.issues = health.issues || [];
  state.connected = true;
  state.connectionError = "";
  state.setProjects(projects.items);
  if (state.revision !== revision) {
    changed();
    return;
  }
  state.setJobs(jobs.items);
  render();
  const job = state.job;
  if (!job) return;
  const detail = await api.jobs.get(job.id, options);
  if (state.revision !== revision) return;
  state.jobs = state.jobs.map(item => item.id === detail.id ? detail : item);
  render();
  const outputs = await Promise.allSettled([
    api.jobs.logs(job.id, options), api.jobs.metrics(job.id, options), api.jobs.artifacts(job.id, options),
  ]);
  if (state.revision === revision) renderDetails(detail, outputs);
}
const poller = createPoller(refresh, 2000, error => {
  if (error.name === "AbortError") return;
  state.connected = false;
  state.connectionError = error.message;
  renderControls(state);
});
async function mutate(task, {
  inline = false
} = {}) {
  if (state.busy) return;
  state.busy = true;
  state.actionError = "";
  state.revision++;
  controller?.abort();
  renderControls(state);
  try {
    await task();
    state.revision++;
    poller.start();
  } catch (error) {
    if (inline) throw error;
    state.actionError = error.message;
  } finally {
    state.busy = false;
    renderControls(state);
  }
}
const editor = bindProjectEditor((definition, update) => mutate(async () => {
  const saved = await api.projects.save(definition, update);
  state.setProjects([...state.projects.filter(item => item.id !== saved.id), saved]);
  state.selectProject(saved.id);
  state.jobs = [];
  state.jobId = null;
  state.loading = true;
}, {
  inline: true
}));
$("addProject").onclick = () => editor.open();
$("emptyAdd").onclick = () => editor.open();
$("editProject").onclick = () => editor.open(state.project);
$("removeProject").onclick = () => {
  const selected = state.projectId;
  if (confirm("Unregister this project? Project files and job history will be kept under All jobs."))
    void mutate(async () => {
      await api.projects.remove(selected);
      state.selectProject(null);
    });
};
$("command").onchange = () => state.commands.set(state.projectId, $("command").value);
$("start").onclick = () => {
  if (!state.canStart) return;
  const project = state.projectId,
    command = state.command,
    resume = $("resume").checked ? state.jobId : null;
  void mutate(async () => {
    const job = await api.jobs.start(project, command, resume);
    if (state.projectId === project) {
      state.jobs.unshift(job);
      state.jobId = job.id;
    }
    $("resume").checked = false;
    $("jobDetail").hidden = true;
  });
};
$("stop").onclick = () => {
  if (!state.canStop) return;
  const job = state.stopTarget.id;
  void mutate(() => api.jobs.stop(job));
};
$("refresh").onclick = () => poller.start();
$("jobFilter").oninput = render;
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    controller?.abort();
    poller.stop();
  } else poller.start();
});
window.addEventListener("pagehide", () => {
  controller?.abort();
  poller.stop();
});
render();
poller.start();
