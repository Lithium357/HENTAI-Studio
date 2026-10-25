export async function requestJSON(path, {
  timeout = 15000,
  signal,
  ...options
} = {}) {
  const controller = new AbortController();
  const abort = () => controller.abort(signal.reason);
  if (signal?.aborted) abort();
  else signal?.addEventListener("abort", abort, {
    once: true
  });
  const timer = setTimeout(() => controller.abort(new Error("Request timed out")), timeout);
  try {
    const response = await fetch(path, {
      ...options,
      cache: "no-store",
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...options.headers
      }
    });
    if (response.status === 204) return null;
    const body = await response.json();
    if (!response.ok) throw new Error(body.error?.message || `Request failed (${response.status})`);
    return body;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}
const id = encodeURIComponent;
export const api = {
  health: () => requestJSON("/api/health"),
  projects: {
    list: () => requestJSON("/api/projects"),
    save: (project, update = false) => requestJSON(`/api/projects${update ? `/${id(project.id)}` : ""}`, {
      method: update ? "PUT" : "POST",
      body: JSON.stringify(project)
    }),
    remove: project => requestJSON(`/api/projects/${id(project)}`, {
      method: "DELETE"
    }),
  },
  jobs: {
    list: project => requestJSON(`/api/jobs?project_id=${id(project)}`),
    get: job => requestJSON(`/api/jobs/${id(job)}`),
    start: (project, command, resume_from = null) => requestJSON(`/api/projects/${id(project)}/jobs`, {
      method: "POST",
      body: JSON.stringify({
        command,
        resume_from
      })
    }),
    stop: job => requestJSON(`/api/jobs/${id(job)}/stop`, {
      method: "POST"
    }),
    logs: job => requestJSON(`/api/jobs/${id(job)}/logs?tail=true`),
    metrics: job => requestJSON(`/api/jobs/${id(job)}/metrics`),
    artifacts: job => requestJSON(`/api/jobs/${id(job)}/artifacts`),
    artifactURL: (job, path) => `/api/jobs/${id(job)}/artifacts/${path.split("/").map(id).join("/")}`,
  },
};
