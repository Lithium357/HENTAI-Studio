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
    if (!response.ok) throw new Error(payload.error || `Studio request failed (${response.status})`);
    return payload;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

const runPath = id => `/api/v1/runs/${encodeURIComponent(id)}`;
const post = (path, payload, options = {}) => requestJSON(path, {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify(payload),
  ...options,
});

export const api = {
  status: signal => requestJSON("/api/status", {signal}),
  runs: signal => requestJSON("/api/v1/runs", {signal}),
  storage: signal => requestJSON("/api/v1/storage", {signal}),
  runStatus: (id, signal) => requestJSON(`${runPath(id)}/status`, {signal}),
  checkpoints: (id, signal) => requestJSON(`${runPath(id)}/checkpoints`, {signal}),
  action: payload => post("/api/action", payload, {timeout: 60000}),
  chat: (id, messages, signal) => post(`${runPath(id)}/chat`, {messages, maxNewTokens: 128}, {signal, timeout: 300000}),
};
