const $ = (id) => document.getElementById(id);
let toastTimer;
let activeStage = "vae";
let checkpointCatalog = [];
let latestStatus = {};
let activeWorkspace = "diffusion";
let llmRuns = [];
let selectedLLMRun = "";
let llmConversation = [];

function formatNumber(value, digits = 0) { return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits }); }
function formatBytes(bytes) { const units = ["B","KB","MB","GB","TB"]; let value = Number(bytes || 0), unit = 0; while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit++; } return `${value.toFixed(unit > 1 ? 1 : 0)} ${units[unit]}`; }
function formatDuration(seconds) { seconds = Math.max(0, Number(seconds || 0)); const days = Math.floor(seconds / 86400); const hours = Math.floor(seconds % 86400 / 3600); const minutes = Math.floor(seconds % 3600 / 60); return days ? `${days}d ${hours}h` : hours ? `${hours}h ${minutes}m` : `${minutes}m`; }
function valueOrDash(value, suffix, digits = 0) { return value == null ? "—" : `${formatNumber(value, digits)}${suffix}`; }
function setMeter(id, value) { $(id).style.width = `${Math.max(0, Math.min(100, Number(value || 0)))}%`; }
function toast(message) { const node = $("toast"); node.textContent = message; node.classList.add("show"); clearTimeout(toastTimer); toastTimer = setTimeout(() => node.classList.remove("show"), 3200); }

function setWorkspace(workspace) {
  activeWorkspace = workspace;
  $("diffusionWorkspace").hidden = workspace !== "diffusion";
  $("llmWorkspace").hidden = workspace !== "llm";
  document.querySelectorAll(".workspace-tab").forEach(button => button.classList.toggle("active", button.dataset.workspace === workspace));
  if (workspace === "llm") refreshLLM(); else refresh();
}

function renderLLM(runs, storage, selectedStatus, checkpoints) {
  llmRuns = runs.filter(run => run.workloadType === "llm.causal");
  const selector = $("llmRunSelect");
  const before = selector.value || selectedLLMRun;
  selector.innerHTML = llmRuns.length ? llmRuns.map(run => `<option value="${run.id}">${run.displayName} · ${run.state}</option>`).join("") : '<option value="">No prepared LLM runs</option>';
  selectedLLMRun = llmRuns.some(run => run.id === before) ? before : (llmRuns[0]?.id || "");
  selector.value = selectedLLMRun;
  const run = llmRuns.find(item => item.id === selectedLLMRun);
  const liveState = selectedStatus?.state || run?.state || "No run selected";
  $("llmTitle").textContent = run ? run.displayName : "No prepared LLM run";
  $("llmModeBadge").textContent = liveState;
  $("llmSummary").textContent = run ? `Workload: ${run.workloadType}. It is managed separately from the diffusion trainer.` : "Prepare a run from a validated LLM profile before it appears here.";
  const progress = selectedStatus?.progress || {}, totalSteps = Number(progress.totalSteps || 0), step = Number(progress.step || 0), seconds = Number(progress.secondsPerStep || 0);
  const hasPlan = totalSteps > 0;
  $("llmStep").textContent = step ? `${formatNumber(step)}${hasPlan ? ` / ${formatNumber(totalSteps)}` : ""}` : "—";
  $("llmProgressFill").style.width = `${hasPlan ? Math.min(100, step / totalSteps * 100) : 0}%`;
  $("llmProgressLabel").textContent = step ? (hasPlan ? `${formatNumber(step / totalSteps * 100, 2)}% complete` : "Training in progress") : "Waiting for first durable step";
  $("llmEta").textContent = seconds && step && hasPlan ? `Rolling ETA ${formatDuration((totalSteps - step) * seconds)}` : "ETA —";
  $("llmStepTime").textContent = seconds ? formatNumber(seconds, 2) : "—";
  $("llmThroughput").textContent = progress.tokensPerSecond ? formatNumber(progress.tokensPerSecond, 0) : "—";
  $("llmTokensSeen").textContent = progress.tokensSeen ? formatNumber(progress.tokensSeen) : "—";
  $("llmStorage").textContent = storage ? formatBytes(storage.free) : "—";
  $("llmRunState").textContent = liveState;
  const chatReady = Boolean(checkpoints?.some(item => item.complete && item.id.startsWith("weights/")));
  $("llmChatStatus").textContent = chatReady ? "CPU ONLY" : (run ? "CHECKPOINT REQUIRED" : "SELECT A RUN");
  $("llmChatInput").disabled = !chatReady;
  $("llmChatSend").disabled = !chatReady;
  $("llmChatHelp").textContent = chatReady ? "Replies are generated locally on CPU; GPU training and VRAM are untouched." : (run ? "Chat unlocks at the first completed adapter checkpoint." : "Select a prepared LLM run first.");
  $("llmCheckpointList").innerHTML = checkpoints?.length ? checkpoints.map(cp => `<div class="checkpoint-item"><div class="checkpoint-icon">${String(cp.step || 0)}</div><div><strong>${cp.id}</strong><small>${cp.complete ? "Complete" : "Incomplete — ignored"} · ${new Date(cp.modifiedAt * 1000).toLocaleString()}</small></div><span class="checkpoint-size">${formatBytes(cp.size)}</span></div>`).join("") : '<p class="empty">No complete LLM checkpoints yet.</p>';
  drawChartInto("llmLossChart", selectedStatus?.lossHistory || []);
  const validations = (selectedStatus?.lossHistory || []).filter(point => point.evalLoss != null);
  $("llmValidationStatus").textContent = validations.length
    ? `Latest VL ${formatNumber(validations.at(-1).evalLoss, 4)} · step ${formatNumber(validations.at(-1).step)}`
    : "No validation result yet";
  renderLLMHardware(selectedStatus?.hardware);
}

async function refreshLLM() {
  try {
    const [runsResponse, storageResponse] = await Promise.all([fetch("/api/v1/runs", { cache: "no-store" }), fetch("/api/v1/storage", { cache: "no-store" })]);
    if (!runsResponse.ok || !storageResponse.ok) throw new Error("LLM workspace unavailable");
    const runPayload = await runsResponse.json(), storage = await storageResponse.json();
    const candidates = runPayload.runs.filter(run => run.workloadType === "llm.causal");
    const runId = candidates.some(run => run.id === selectedLLMRun) ? selectedLLMRun : candidates[0]?.id;
    let checkpoints = [], status = null;
    if (runId) {
      const [statusResponse, checkpointResponse] = await Promise.all([fetch(`/api/v1/runs/${encodeURIComponent(runId)}/status`), fetch(`/api/v1/runs/${encodeURIComponent(runId)}/checkpoints`)]);
      if (statusResponse.ok) status = await statusResponse.json();
      if (checkpointResponse.ok) checkpoints = (await checkpointResponse.json()).checkpoints || [];
    }
    renderLLM(runPayload.runs, storage, status, checkpoints);
  } catch (error) { toast("LLM workspace could not reach the local Studio API"); }
}

function syncCheckpointMenus(catalog) {
  checkpointCatalog = catalog || [];
  const previousRun = $("runSelect").value;
  const signature = checkpointCatalog.map(run => `${run.id}:${run.checkpoints.map(cp => cp.id).join(",")}`).join("|");
  if ($("runSelect").dataset.signature !== signature) {
    $("runSelect").innerHTML = checkpointCatalog.map(run => `<option value="${run.id}">${run.label} · ${run.resolution}px</option>`).join("");
    $("runSelect").dataset.signature = signature;
    if (checkpointCatalog.some(run => run.id === previousRun)) $("runSelect").value = previousRun;
    syncCheckpointOptions();
  }
}

function syncCheckpointOptions() {
  const run = checkpointCatalog.find(item => item.id === $("runSelect").value);
  const previous = $("checkpointSelect").value;
  $("checkpointSelect").innerHTML = run ? run.checkpoints.map(cp => `<option value="${cp.id}">Step ${formatNumber(cp.step)}</option>`).join("") : '<option value="">No diffusion checkpoints found</option>';
  if (run?.checkpoints.some(cp => cp.id === previous)) $("checkpointSelect").value = previous;
  updateSampleControls();
}

function updateSampleControls() {
  const historical = $("sourceMode").value === "historical";
  const samplingVae = activeStage === "vae" && !historical;
  const selectedCheckpoint = Boolean($("checkpointSelect").value);
  const latest = latestStatus.checkpoints?.[0];
  const waitingForVaeCheckpoint = samplingVae && !latest;
  const checkpointEvery = Number(latestStatus.checkpointEvery || 1000);
  const currentStep = Number(latestStatus.progress?.step || 0);
  const nextCheckpointStep = Math.max(checkpointEvery, Math.ceil((currentStep + 1) / checkpointEvery) * checkpointEvery);
  const stepsUntilCheckpoint = Math.max(0, nextCheckpointStep - currentStep);
  const checkpointEta = stepsUntilCheckpoint * Number(latestStatus.progress?.secondsPerStep || 0);
  $("historicalFields").hidden = !historical;
  ["tagsInput", "seedInput", "stepsInput", "guidanceInput"].forEach(id => { $(id).disabled = samplingVae; });
  $("sampleButton").disabled = Boolean(latestStatus.sampling) || (historical ? !selectedCheckpoint : !latest);
  $("sampleButton").textContent = latestStatus.sampling
    ? "Generating on CPU…"
    : (waitingForVaeCheckpoint
      ? `First VAE checkpoint at step ${formatNumber(nextCheckpointStep)}`
      : (samplingVae ? "Reconstruct random image" : "Generate from selected checkpoint"));
  $("sampleEyebrow").textContent = historical ? "HISTORICAL CHECKPOINT LAB" : (samplingVae ? "RANDOM VAE RECONSTRUCTION" : "FIXED-SEED OBSERVATORY");
  $("sampleHelp").textContent = historical
    ? "Loads the exact saved diffuser checkpoint selected below. CPU inference leaves active GPU training alone."
    : (waitingForVaeCheckpoint
      ? `The new VAE has not saved a checkpoint yet. Reconstruction unlocks at step ${formatNumber(nextCheckpointStep)}${checkpointEta ? ` (about ${formatDuration(checkpointEta)})` : ""}. Historical diffuser generation remains available.`
      : (samplingVae
        ? "Selects a fresh random training record and reconstructs it through the latest VAE checkpoint. Runs on CPU."
        : "Runs on CPU so the RX 7800 XT can keep training. Samples use the latest completed checkpoint."));
}

function drawChart(points) {
  const svg = $("lossChart"), line = svg.querySelector(".line"), area = svg.querySelector(".area"), grid = svg.querySelector(".grid-lines");
  const width = 760, height = 240, pad = 16;
  grid.innerHTML = [0.2,0.4,0.6,0.8].map(r => `<line x1="0" x2="${width}" y1="${height*r}" y2="${height*r}" />`).join("");
  if (!points || points.length < 2) { line.setAttribute("d", ""); area.setAttribute("d", ""); return; }
  const losses = points.map(p => p.loss), min = Math.min(...losses), max = Math.max(...losses), spread = Math.max(.001, max - min);
  const coords = points.map((p, index) => [pad + index / (points.length - 1) * (width - pad * 2), pad + (max - p.loss) / spread * (height - pad * 2)]);
  const path = coords.map((point, index) => `${index ? "L" : "M"}${point[0].toFixed(1)},${point[1].toFixed(1)}`).join(" ");
  line.setAttribute("d", path); area.setAttribute("d", `${path} L${coords.at(-1)[0]},${height} L${coords[0][0]},${height} Z`);
}

function drawChartInto(svgId, points) {
  const svg = $(svgId), line = svg.querySelector(".line"), area = svg.querySelector(".area"), evalLine = svg.querySelector(".eval-line"), evalMarkers = svg.querySelector(".eval-points"), grid = svg.querySelector(".grid-lines"), width = 760, height = 240, pad = 16;
  grid.innerHTML = [0.2,0.4,0.6,0.8].map(r => `<line x1="0" x2="${width}" y1="${height*r}" y2="${height*r}" />`).join("");
  if (!points || points.length < 2) { line.setAttribute("d", ""); area.setAttribute("d", ""); if (evalLine) evalLine.setAttribute("d", ""); if (evalMarkers) evalMarkers.innerHTML = ""; return; }
  const losses = points.flatMap(p => [p.loss, p.evalLoss].filter(value => value != null)), min = Math.min(...losses), max = Math.max(...losses), spread = Math.max(.001, max - min);
  const coords = points.map((p, index) => [pad + index / (points.length - 1) * (width - pad * 2), pad + (max - p.loss) / spread * (height - pad * 2)]);
  const path = coords.map((point, index) => `${index ? "L" : "M"}${point[0].toFixed(1)},${point[1].toFixed(1)}`).join(" ");
  line.setAttribute("d", path); area.setAttribute("d", `${path} L${coords.at(-1)[0]},${height} L${coords[0][0]},${height} Z`);
  if (evalLine) {
    const evalPoints = points.map((point, index) => point.evalLoss == null ? null : [pad + index / (points.length - 1) * (width - pad * 2), pad + (max - point.evalLoss) / spread * (height - pad * 2)]);
    let drawing = false;
    evalLine.setAttribute("d", evalPoints.map(point => { if (!point) { drawing = false; return ""; } const segment = `${drawing ? "L" : "M"}${point[0].toFixed(1)},${point[1].toFixed(1)}`; drawing = true; return segment; }).join(" "));
    if (evalMarkers) evalMarkers.innerHTML = evalPoints.filter(Boolean).map(point => `<circle cx="${point[0].toFixed(1)}" cy="${point[1].toFixed(1)}" r="4"></circle>`).join("");
  }
}

function renderLLMHardware(hw = {}) {
  const available = Boolean(hw.available);
  $("llmHardwareScope").textContent = available ? "LLM TRAINER · PROCESS ATTRIBUTED" : "LLM TRAINER IDLE";
  $("llmGpuUsage").textContent = valueOrDash(hw.gpuUsagePct, "%", 0); $("llmGpuVram").textContent = hw.gpuVramBytes == null ? "—" : `${formatBytes(hw.gpuVramBytes)} / ${formatBytes(hw.gpuVramTotalBytes)}`;
  $("llmGpuTemp").textContent = hw.gpuTempC == null ? "—" : `${formatNumber(hw.gpuTempC, 0)}° / ${formatNumber(hw.gpuHotspotC, 0)}°C`; $("llmGpuFan").textContent = valueOrDash(hw.gpuFanRpm, " RPM", 0);
  $("llmCpuUsage").textContent = valueOrDash(hw.cpuUsagePct, "%", 1); $("llmCpuRam").textContent = hw.cpuRamBytes == null ? "—" : formatBytes(hw.cpuRamBytes); $("llmWorkloadPower").textContent = valueOrDash(hw.workloadPowerW, " W", 0); $("llmEnergyUsed").textContent = valueOrDash(hw.energyKwh, " kWh", 3);
  setMeter("llmGpuUsageBar", hw.gpuUsagePct); setMeter("llmGpuVramBar", hw.gpuVramBytes && hw.gpuVramTotalBytes ? hw.gpuVramBytes / hw.gpuVramTotalBytes * 100 : 0); setMeter("llmCpuUsageBar", hw.cpuUsagePct); setMeter("llmCpuRamBar", hw.cpuRamBytes && hw.cpuRamTotalBytes ? hw.cpuRamBytes / hw.cpuRamTotalBytes * 100 : 0);
}

function render(data) {
  latestStatus = data;
  const p = data.progress || {}, stages = data.stages || {}, checkpoints = data.checkpoints || [], latest = checkpoints[0];
  const vae = stages.vae || {}, diffusion = stages.diffusion || {}, overall = stages.overall || {};
  activeStage = stages.active || "vae";
  const samplingVae = activeStage === "vae";
  $("livePill").className = `live-pill ${data.running ? "running" : "stopped"}`;
  $("livePill").querySelector("span").textContent = data.running ? "Training live" : "Trainer stopped";
  $("stepTitle").textContent = p.step != null ? `Step ${formatNumber(p.step)} of ${formatNumber(p.total)}` : "No progress detected";
  $("stageEyebrow").textContent = `${data.architectureLabel || "SCRATCH"} / ${stages.active === "diffusion" ? "DIFFUSION" : "VAE"}`;
  $("checkpointBadge").textContent = latest ? `${latest.name} safe` : "No checkpoint";
  [["vae", vae], ["diffusion", diffusion], ["overall", overall]].forEach(([name, stage]) => {
    $(`${name}ProgressFill`).style.width = `${Math.min(100, stage.percent || 0)}%`;
    $(`${name}PercentLabel`).textContent = `${formatNumber(stage.percent || 0, 2)}% complete`;
    $(`${name}Count`).textContent = `${formatNumber(stage.step)} / ${formatNumber(stage.total)}`;
  });
  $("vaeState").textContent = (vae.percent || 0) >= 100 ? "Complete" : (stages.active === "vae" ? "Training now" : "Waiting");
  $("diffusionState").textContent = (diffusion.percent || 0) >= 100 ? "Complete" : (stages.active === "diffusion" ? "Training now" : "Queued");
  $("etaLabel").textContent = p.etaSeconds ? `Rolling ETA ${formatDuration(p.etaSeconds)}` : "ETA —";
  $("lossValue").textContent = p.loss != null ? formatNumber(p.loss, 4) : "—";
  $("paceValue").textContent = p.secondsPerStep != null ? formatNumber(p.secondsPerStep, 2) : "—";
  $("throughputValue").textContent = p.imagesPerSecond != null ? formatNumber(p.imagesPerSecond, 2) : "—";
  $("safeStepValue").textContent = latest ? formatNumber(latest.step) : "—";
  $("healthTitle").textContent = data.running ? (data.watchdogRunning ? "Trainer is protected" : "Trainer is healthy") : (data.paused ? "Trainer intentionally paused" : "Automatic recovery pending");
  $("healthCopy").textContent = data.running
    ? `Process ${data.pids.join(", ")} is active. ${data.watchdogRunning ? "The watchdog will resume it after an unexpected exit." : "Automatic recovery is not active."}`
    : (data.paused ? "HENTAI Studio will leave training stopped until you press Resume." : "The watchdog will load the latest completed checkpoint automatically.");
  $("stopButton").disabled = !data.running;
  $("resumeButton").disabled = data.running;
  $("startDiffusionButton").hidden = !samplingVae;
  $("startDiffusionButton").disabled = data.sampling || !latest;
  $("trainerMicrocopy").textContent = samplingVae
    ? "The diffuser button discards only progress after the latest safe VAE checkpoint, calibrates that VAE, then starts diffusion automatically."
    : "Diffuser training is active. Stop and resume both preserve the latest completed checkpoint.";
  syncCheckpointMenus(data.checkpointCatalog);
  updateSampleControls();
  $("diskLabel").textContent = `${formatBytes(data.disk?.free)} free`;
  const hw = data.hardware || {};
  $("gpuUsage").textContent = valueOrDash(hw.gpuUsagePct, "%", 0);
  $("gpuVram").textContent = hw.gpuVramBytes == null ? "—" : `${formatBytes(hw.gpuVramBytes)} / ${formatBytes(hw.gpuVramTotalBytes)}`;
  $("gpuTemp").textContent = hw.gpuTempC == null ? "—" : `${formatNumber(hw.gpuTempC, 0)}° / ${formatNumber(hw.gpuHotspotC, 0)}°C`;
  $("gpuFan").textContent = valueOrDash(hw.gpuFanRpm, " RPM", 0);
  $("cpuUsage").textContent = valueOrDash(hw.cpuUsagePct, "%", 1);
  $("cpuTemp").textContent = hw.cpuTempC == null ? "N/A" : `${formatNumber(hw.cpuTempC, 0)}°C`;
  $("cpuRam").textContent = hw.cpuRamBytes == null ? "—" : formatBytes(hw.cpuRamBytes);
  $("workloadPower").textContent = valueOrDash(hw.workloadPowerW, " W", 0);
  $("energyUsed").textContent = valueOrDash(hw.energyKwh, " kWh", 3);
  $("powerDetail").textContent = hw.gpuBoardPowerW == null ? "waiting for active workload" : `${formatNumber(hw.gpuBoardPowerW, 0)} W GPU board + attributed CPU`;
  $("hardwareNote").textContent = hw.scopeNote || "Hardware sensors unavailable.";
  $("hardwareScope").textContent = hw.available ? "LIVE · PROCESS + ATTRIBUTED" : "TRAINER IDLE";
  setMeter("gpuUsageBar", hw.gpuUsagePct);
  setMeter("gpuVramBar", hw.gpuVramBytes && hw.gpuVramTotalBytes ? hw.gpuVramBytes / hw.gpuVramTotalBytes * 100 : 0);
  setMeter("cpuUsageBar", hw.cpuUsagePct);
  setMeter("cpuRamBar", hw.cpuRamBytes && hw.cpuRamTotalBytes ? hw.cpuRamBytes / hw.cpuRamTotalBytes * 100 : 0);
  $("checkpointList").innerHTML = checkpoints.length ? checkpoints.map(cp => `<div class="checkpoint-item"><div class="checkpoint-icon">${String(cp.step / 1000).replace(".0","")}K</div><div><strong>${cp.name}</strong><small>${new Date(cp.modifiedAt * 1000).toLocaleString()}</small></div><span class="checkpoint-size">${formatBytes(cp.size)}</span></div>`).join("") : '<p class="empty">No corrected checkpoints yet.</p>';
  drawChart(data.lossHistory);
  const latestSample = data.samples?.[0];
  $("sampleStage").innerHTML = latestSample ? `<img src="${latestSample.url}?v=${latestSample.modifiedAt}" alt="Latest generated checkpoint sample" />` : '<div class="sample-empty"><span>◇</span><p>No dashboard samples yet</p><small>Generate one from the latest checkpoint.</small></div>';
  $("refreshLabel").textContent = `Updated ${new Date(data.serverTime * 1000).toLocaleTimeString()}`;
}

async function refresh() {
  if (activeWorkspace !== "diffusion") return;
  try { const response = await fetch("/api/status", { cache: "no-store" }); if (!response.ok) throw new Error("status unavailable"); render(await response.json()); }
  catch (error) { $("livePill").className = "live-pill stopped"; $("livePill").querySelector("span").textContent = "Dashboard disconnected"; }
}

async function action(payload, success) {
  try { const response = await fetch("/api/action", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); const data = await response.json(); if (!response.ok) throw new Error(data.error || "Action failed"); toast(success); setTimeout(refresh, 700); }
  catch (error) { toast(error.message); }
}

$("stopButton").addEventListener("click", () => { if (confirm("Stop training now? Progress since the latest checkpoint will be repeated on resume.")) action({ action: "stop" }, "Trainer stop requested"); });
$("resumeButton").addEventListener("click", () => action({ action: "resume" }, "Trainer resume requested"));
$("startDiffusionButton").addEventListener("click", () => { if (confirm("End VAE training at the latest safe checkpoint and begin diffuser training? This cannot resume the same VAE run unless the promoted model is removed manually.")) action({ action: "start_diffusion" }, "VAE checkpoint promoted; diffuser startup requested"); });
$("sourceMode").addEventListener("change", updateSampleControls);
$("runSelect").addEventListener("change", syncCheckpointOptions);
$("checkpointSelect").addEventListener("change", updateSampleControls);
$("sampleForm").addEventListener("submit", event => {
  event.preventDefault();
  const historical = $("sourceMode").value === "historical";
  action({
    action: "sample",
    source: historical ? "historical" : "current",
    runId: $("runSelect").value,
    checkpointId: $("checkpointSelect").value,
    tags: $("tagsInput").value,
    seed: Number($("seedInput").value),
    steps: Number($("stepsInput").value),
    guidance: Number($("guidanceInput").value)
  }, historical ? "Historical checkpoint sample started on CPU" : (activeStage === "vae" ? "Random VAE reconstruction started on CPU" : "Checkpoint sample started on CPU"));
});

document.querySelectorAll(".workspace-tab").forEach(button => button.addEventListener("click", () => setWorkspace(button.dataset.workspace)));
$("llmRunSelect").addEventListener("change", () => { selectedLLMRun = $("llmRunSelect").value; llmConversation = []; $("llmChatTranscript").innerHTML = '<div class="chat-empty"><span>◇</span><p>Start a new local conversation.</p><small>Replies run on CPU and leave GPU training alone.</small></div>'; refreshLLM(); });
$("llmChatForm").addEventListener("submit", event => {
  event.preventDefault();
  const message = $("llmChatInput").value.trim();
  if (!message) return;
  const escape = value => value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\"/g, "&quot;");
  const transcript = $("llmChatTranscript");
  if (!llmConversation.length) transcript.innerHTML = "";
  llmConversation.push({ role: "user", content: message });
  transcript.insertAdjacentHTML("beforeend", `<div class="chat-message user"><strong>You</strong><p>${escape(message)}</p></div><div class="chat-message assistant pending"><strong>Model · CPU</strong><p>Generating…</p></div>`);
  transcript.scrollTop = transcript.scrollHeight;
  $("llmChatInput").value = ""; $("llmChatInput").disabled = true; $("llmChatSend").disabled = true;
  fetch(`/api/v1/runs/${encodeURIComponent(selectedLLMRun)}/chat`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ messages: llmConversation, maxNewTokens: 128 }) })
    .then(async response => { const payload = await response.json(); if (!response.ok) throw new Error(payload.error || "Chat generation failed"); return payload.reply; })
    .then(reply => { llmConversation.push({ role: "assistant", content: reply }); const pending = transcript.querySelector(".pending"); pending.classList.remove("pending"); pending.innerHTML = `<strong>Model · CPU</strong><p>${escape(reply)}</p>`; })
    .catch(error => { llmConversation.pop(); const pending = transcript.querySelector(".pending"); pending.classList.remove("pending"); pending.innerHTML = `<strong>Model · CPU</strong><p>${escape(error.message)}</p>`; toast(error.message); })
    .finally(() => { $("llmChatInput").disabled = false; $("llmChatSend").disabled = false; $("llmChatInput").focus(); });
});

refresh(); setInterval(() => activeWorkspace === "llm" ? refreshLLM() : refresh(), 4000);
