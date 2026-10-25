export async function requestJSON(path, {signal, timeout = 15000, ...options} = {}) {
  const controller = new AbortController();
  const abort = () => controller.abort(signal?.reason);
  if (signal?.aborted) abort();
  else signal?.addEventListener("abort", abort, {once: true});
  const timer = setTimeout(() => controller.abort(new Error("The local Studio request timed out")), timeout);
  try {
    const response = await fetch(path, {cache: "no-store", ...options, signal: controller.signal});
    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new Error("Studio returned an invalid response");
    }
    if (!response.ok) {
      const error = new Error(payload.error?.message || `Studio request failed (${response.status})`);
      error.code = payload.error?.code;
      error.details = payload.error?.details || [];
      error.status = response.status;
      throw error;
    }
    return payload;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

const runPath = id => `/api/runs/${encodeURIComponent(id)}`;
const get = (path, signal) => requestJSON(path, {signal});
const post = (path, payload, options = {}) => requestJSON(path, {
  method: "POST",
  ...(payload === undefined ? {} : {
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  }),
  ...options,
});

export const api = {
  system: {
    health: signal => get("/api/health", signal),
    storage: signal => get("/api/storage", signal),
  },
  runs: {
    list: (workload, signal) => get(`/api/runs${workload ? `?workload=${encodeURIComponent(workload)}` : ""}`, signal),
    get: (id, signal) => get(runPath(id), signal),
    checkpoints: (id, signal) => get(`${runPath(id)}/checkpoints`, signal),
    completeChat: (id, messages, signal) => post(`${runPath(id)}/chat/completions`, {messages, max_new_tokens: 128}, {signal, timeout: 300000}),
  },
  diffusion: {
    status: signal => get("/api/diffusion/status", signal),
    checkpoints: signal => get("/api/diffusion/checkpoints", signal),
    samples: signal => get("/api/diffusion/samples", signal),
    sampling: signal => get("/api/diffusion/sampling", signal),
    createSample: payload => post("/api/diffusion/samples", payload),
    pause: () => post("/api/diffusion/training/pause", undefined, {timeout: 60000}),
    resume: () => post("/api/diffusion/training/resume", undefined, {timeout: 60000}),
    promoteVae: () => post("/api/diffusion/training/promote-vae", undefined, {timeout: 60000}),
  },
};
