// UI state has no DOM or network dependencies; selections survive polling.
export const isBusy = job => !!job && (["starting", "running", "stopping"].includes(job.state) || !!job.has_live_processes);

export class WorkspaceState {
  constructor() {
    this.projects = [];
    this.jobs = [];
    this.projectId = null;
    this.jobId = null;
    this.commands = new Map();
    this.jobSelections = new Map();
    this.revision = 0;
    this.connected = false;
    this.loading = true;
    this.busy = false;
    this.issues = [];
    this.health = null;
    this.actionError = "";
    this.connectionError = "";
  }
  get project() {
    return this.projects.find(item => item.id === this.projectId);
  }
  get job() {
    return this.jobs.find(item => item.id === this.jobId);
  }
  get command() {
    const commands = Object.keys(this.project?.commands || {});
    const selected = this.commands.get(this.projectId);
    return commands.includes(selected) ? selected : commands[0];
  }
  selectProject(id) {
    if (this.projectId === id) return;
    this.jobSelections.set(this.projectId, this.jobId);
    this.projectId = id;
    this.jobId = this.jobSelections.get(id) || null;
    this.jobs = [];
    this.loading = true;
    this.revision++;
  }
  selectJob(id) {
    this.jobId = id;
    this.revision++;
  }
  setProjects(projects) {
    this.projects = projects;
    if (this.projectId && !this.project) this.selectProject(null);
  }
  setJobs(jobs) {
    this.jobs = jobs;
    if (!jobs.some(job => job.id === this.jobId)) this.jobId = jobs[0]?.id || null;
    this.loading = false;
  }
  get blocked() {
    return this.busy || this.loading || !this.connected;
  }
  get canStart() {
    return !this.blocked && !this.issues.length && !!this.project && !this.jobs.some(isBusy);
  }
  get canEdit() {
    return this.canStart;
  }
  get canStop() {
    return !this.blocked && isBusy(this.stopTarget) && this.stopTarget.state !== "stopping";
  }
  get stopTarget() {
    // Inspecting an older run must not hide the current project's stop action.
    return isBusy(this.job) ? this.job : this.projectId ? this.jobs.find(isBusy) || this.job : this.job;
  }
  get startReason() {
    if (!this.connected) return "Reconnect to Studio to run commands.";
    if (this.loading) return "Loading project jobs…";
    if (this.busy) return "Applying your action…";
    if (this.issues.length) return "Repair the workspace issues shown above before starting a job.";
    if (!this.project) return "Select a registered project to run a command.";
    if (this.jobs.some(isBusy)) return "This project has an active job. Stop it or wait for it to finish.";
    return "";
  }
  get canResume() {
    return this.canStart && !!this.job && this.job.project_id === this.projectId && !isBusy(this.job);
  }
}
