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
async function allPages(path, options) {
  const items = [];
  let cursor;
  do {
    const separator = path.includes("?") ? "&" : "?";
    const page = await requestJSON(path + (cursor ? `${separator}cursor=${id(cursor)}` : ""), options);
    items.push(...page.items);
    cursor = page.next_cursor;
  } while (cursor);
  return {
    items
  };
}
export const api = {
  health: options => requestJSON("/api/health", options),
  projects: {
    list: options => allPages("/api/projects", options),
    save: (project, update = false) => {
      const {
        id: projectId,
        ...fields
      } = project;
      return requestJSON(`/api/projects${update ? `/${id(projectId)}` : ""}`, {
        method: update ? "PATCH" : "POST",
        body: JSON.stringify(update ? fields : project),
      });
    },
    remove: project => requestJSON(`/api/projects/${id(project)}`, {
      method: "DELETE"
    }),
  },
  jobs: {
    list: (project, options) => allPages(`/api/jobs${project ? `?project_id=${id(project)}` : ""}`, options),
    get: (job, options) => requestJSON(`/api/jobs/${id(job)}`, options),
    start: (project_id, command, resume_from = null) => resume_from ?
      requestJSON(`/api/jobs/${id(resume_from)}/resume`, {
        method: "POST",
        body: JSON.stringify({
          command
        })
      }) :
      requestJSON("/api/jobs", {
        method: "POST",
        body: JSON.stringify({
          project_id,
          command
        })
      }),
    stop: job => requestJSON(`/api/jobs/${id(job)}/stop`, {
      method: "POST"
    }),
    logs: (job, options) => requestJSON(`/api/jobs/${id(job)}/logs?tail=65536`, options),
    metrics: (job, options) => requestJSON(`/api/jobs/${id(job)}/metrics`, options),
    artifacts: (job, options) => requestJSON(`/api/jobs/${id(job)}/artifacts`, options),
    artifactURL: (job, path) => `/api/jobs/${id(job)}/artifacts/${path.split("/").map(id).join("/")}`,
  },
};
