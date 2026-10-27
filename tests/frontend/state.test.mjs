import test from "node:test";
import assert from "node:assert/strict";
import {
  WorkspaceState,
  isBusy
} from "../../src/hentai_studio/dashboard_static/state.js";
const projects = [{
  id: "first",
  commands: {
    train: ["python"],
    evaluate: ["python"]
  }
}, {
  id: "second",
  commands: {
    train: ["python"],
    export: ["python"]
  }
}];

function ready() {
  const state = new WorkspaceState();
  state.connected = true;
  state.projects = projects;
  state.selectProject("first");
  state.setJobs([]);
  return state;
}
test("each project's command selection survives polling and project switches", () => {
  const state = ready();
  state.commands.set("first", "evaluate");
  state.setProjects(projects);
  state.setJobs([]);
  assert.equal(state.command, "evaluate");
  state.selectProject("second");
  state.commands.set("second", "export");
  state.selectProject("first");
  assert.equal(state.command, "evaluate");
  state.projects = [{
    id: "first",
    commands: {
      train: ["python"]
    }
  }];
  assert.equal(state.command, "train");
});
test("orphan processes block duplicate starts and remain stoppable", () => {
  const state = ready();
  state.setJobs([{
    id: "orphan",
    project_id: "first",
    state: "interrupted",
    has_live_processes: true
  }]);
  assert.equal(state.canStart, false);
  assert.equal(state.canStop, true);
  assert.equal(state.canResume, false);
  assert.equal(isBusy(state.job), true);
});
test("disconnected and loading views cannot launch or stop stale selections", () => {
  const state = ready();
  assert.equal(state.canStart, true);
  state.connected = false;
  assert.equal(state.canStart, false);
  state.connected = true;
  state.selectProject("second");
  assert.equal(state.canStart, false);
  state.setJobs([]);
  assert.equal(state.canStart, true);
});
test("unregistration falls back to workspace history, not a different project", () => {
  const state = ready();
  state.actionError = "Command failed";
  state.setProjects([projects[1]]);
  assert.equal(state.projectId, null);
  assert.equal(state.canStart, false);
  state.setJobs([{
    id: "old",
    project_id: "first",
    state: "succeeded"
  }]);
  assert.equal(state.job.id, "old");
  assert.equal(state.actionError, "Command failed");
});
test("workspace issues disable registration mutations without losing history", () => {
  const state = ready();
  state.issues = [{
    resource: "jobs/broken"
  }];
  assert.equal(state.canStart, false);
  assert.equal(state.canEdit, false);
  state.setJobs([{
    id: "running",
    project_id: "first",
    state: "running"
  }]);
  assert.equal(state.canStop, true);
});
