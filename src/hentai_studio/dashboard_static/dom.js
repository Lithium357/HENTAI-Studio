export const $ = id => document.getElementById(id);

export function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"})[char]);
}

export function setMeter(id, value) {
  $(id).style.width = `${Math.max(0, Math.min(100, Number(value) || 0))}%`;
}

let toastTimer;
export function toast(message) {
  const node = $("toast");
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove("show"), 3200);
}

export function setConnection(message, connected = false) {
  const pill = $("livePill");
  pill.className = `live-pill ${connected ? "running" : "stopped"}`;
  pill.querySelector("span").textContent = message;
}
