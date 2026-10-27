// UI state has no DOM or network dependencies; selections survive polling.
export const isBusy = job => !!job && (["starting", "running", "stopping"].includes(job.state) || job.has_live_processes);

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
    return !this.blocked && isBusy(this.job) && this.job.state !== "stopping";
  }
  get canResume() {
    return this.canStart && !!this.job && this.job.project_id === this.projectId && !isBusy(this.job);
  }
}
