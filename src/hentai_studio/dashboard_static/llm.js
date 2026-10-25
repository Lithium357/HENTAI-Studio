import { $, escapeHTML, setMeter, toast, setConnection } from "./dom.js";
import { formatNumber, formatBytes, formatDuration, valueOrDash } from "./format.js";
import { drawChartInto } from "./charts.js";
import { api } from "./api.js";

export function createLLMWorkspace() {
  let llmRuns = [];
  let selectedLLMRun = "";
  let llmConversation = [];
  let chatPending = false;
  let ready = false;
  let controller;
  let chatController;
  let selectionVersion = 0;

  async function refresh() {
    controller?.abort();
    const request = controller = new AbortController();
    const version = selectionVersion;
    try {
      const [runPayload, storage] = await Promise.all([api.runs(request.signal), api.storage(request.signal)]);
      const candidates = runPayload.runs.filter(run => run.workloadType === "llm.causal");
      const runId = candidates.some(run => run.id === selectedLLMRun) ? selectedLLMRun : candidates[0]?.id || "";
      const [status, checkpointPayload] = runId ? await Promise.all([
        api.runStatus(runId, request.signal), api.checkpoints(runId, request.signal),
      ]) : [null, {checkpoints: []}];
      if (request.signal.aborted || version !== selectionVersion) return;
      if (selectedLLMRun && selectedLLMRun !== runId) resetConversation();
      selectedLLMRun = runId;
      $("llmRunSelect").value = runId;
      ready = checkpointPayload.checkpoints.some(item => item.complete && item.id.startsWith("weights/"));
      renderLLM(runPayload.runs, storage, status, checkpointPayload.checkpoints);
    } catch (error) {
      if (!request.signal.aborted) {
        setConnection("LLM workspace disconnected");
        toast(error.message);
      }
    }
  }

  function resetConversation() {
    chatController?.abort();
    chatPending = false;
    ready = false;
    llmConversation = [];
    $("llmChatTranscript").innerHTML = '<div class="chat-empty"><span>◇</span><p>Start a new local conversation.</p><small>Replies run on CPU.</small></div>';
    $("llmChatInput").disabled = true;
    $("llmChatSend").disabled = true;
  }

  async function sendChat(event) {
    event.preventDefault();
    const message = $("llmChatInput").value.trim();
    if (!message || !selectedLLMRun || !ready || chatPending) return;
    const version = selectionVersion;
    const runId = selectedLLMRun;
    const request = chatController = new AbortController();
    const transcript = $("llmChatTranscript");
    if (!llmConversation.length) transcript.replaceChildren();
    llmConversation.push({role: "user", content: message});
    transcript.insertAdjacentHTML("beforeend", `<div class="chat-message user"><strong>You</strong><p>${escapeHTML(message)}</p></div>`);
    const pending = document.createElement("div");
    pending.className = "chat-message assistant pending";
    pending.innerHTML = '<strong>Model · CPU</strong><p>Generating…</p>';
    transcript.append(pending);
    transcript.scrollTop = transcript.scrollHeight;
    chatPending = true;
    $("llmChatInput").value = "";
    $("llmChatInput").disabled = true;
    $("llmChatSend").disabled = true;
    try {
      const payload = await api.chat(runId, llmConversation, request.signal);
      if (request.signal.aborted || selectionVersion !== version || selectedLLMRun !== runId) return;
      llmConversation.push({role: "assistant", content: payload.reply});
      pending.querySelector("p").textContent = payload.reply;
    } catch (error) {
      if (request.signal.aborted || selectionVersion !== version) return;
      llmConversation.pop();
      pending.querySelector("p").textContent = error.message;
      toast(error.message);
    } finally {
      if (selectionVersion === version && !request.signal.aborted) {
        chatPending = false;
        pending.classList.remove("pending");
        $("llmChatInput").disabled = !ready;
        $("llmChatSend").disabled = !ready;
        $("llmChatInput").focus();
      }
    }
  }

  function renderLLM(runs, storage, selectedStatus, checkpoints) {
    llmRuns = runs.filter(run => run.workloadType === "llm.causal");
    const selector = $("llmRunSelect");
    const before = selector.value || selectedLLMRun;
    selector.innerHTML = llmRuns.length ? llmRuns.map(run => `<option value="${escapeHTML(run.id)}">${escapeHTML(run.displayName)} · ${escapeHTML(run.state)}</option>`).join("") : '<option value="">No prepared LLM runs</option>';
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
    $("llmChatInput").disabled = !chatReady || chatPending;
    $("llmChatSend").disabled = !chatReady || chatPending;
    $("llmChatHelp").textContent = chatReady ? "Replies are generated locally on CPU; GPU training and VRAM are untouched." : (run ? "Chat unlocks at the first completed adapter checkpoint." : "Select a prepared LLM run first.");
    $("llmCheckpointList").innerHTML = checkpoints?.length ? checkpoints.map(cp => `<div class="checkpoint-item"><div class="checkpoint-icon">${escapeHTML(String(cp.step || 0))}</div><div><strong>${escapeHTML(cp.id)}</strong><small>${cp.complete ? "Complete" : "Incomplete — ignored"} · ${new Date(cp.modifiedAt * 1000).toLocaleString()}</small></div><span class="checkpoint-size">${formatBytes(cp.size)}</span></div>`).join("") : '<p class="empty">No complete LLM checkpoints yet.</p>';
    drawChartInto("llmLossChart", selectedStatus?.lossHistory || []);
    const validations = (selectedStatus?.lossHistory || []).filter(point => point.evalLoss != null);
    $("llmValidationStatus").textContent = validations.length
      ? `Latest VL ${formatNumber(validations.at(-1).evalLoss, 4)} · step ${formatNumber(validations.at(-1).step)}`
      : "No validation result yet";
    renderLLMHardware(selectedStatus?.hardware);
    setConnection(run ? `${run.displayName} · ${liveState}` : "No LLM run selected", liveState === "running");
  }

  function renderLLMHardware(hw = {}) {
    const available = Boolean(hw.available);
    $("llmHardwareScope").textContent = available ? "LLM TRAINER · PROCESS ATTRIBUTED" : "LLM TRAINER IDLE";
    $("llmGpuUsage").textContent = valueOrDash(hw.gpuUsagePct, "%", 0); $("llmGpuVram").textContent = hw.gpuVramBytes == null ? "—" : `${formatBytes(hw.gpuVramBytes)} / ${formatBytes(hw.gpuVramTotalBytes)}`;
    $("llmGpuTemp").textContent = hw.gpuTempC == null ? "—" : `${formatNumber(hw.gpuTempC, 0)}° / ${formatNumber(hw.gpuHotspotC, 0)}°C`; $("llmGpuFan").textContent = valueOrDash(hw.gpuFanRpm, " RPM", 0);
    $("llmCpuUsage").textContent = valueOrDash(hw.cpuUsagePct, "%", 1); $("llmCpuRam").textContent = hw.cpuRamBytes == null ? "—" : formatBytes(hw.cpuRamBytes); $("llmWorkloadPower").textContent = valueOrDash(hw.workloadPowerW, " W", 0); $("llmEnergyUsed").textContent = valueOrDash(hw.energyKwh, " kWh", 3);
    setMeter("llmGpuUsageBar", hw.gpuUsagePct); setMeter("llmGpuVramBar", hw.gpuVramBytes && hw.gpuVramTotalBytes ? hw.gpuVramBytes / hw.gpuVramTotalBytes * 100 : 0); setMeter("llmCpuUsageBar", hw.cpuUsagePct); setMeter("llmCpuRamBar", hw.cpuRamBytes && hw.cpuRamTotalBytes ? hw.cpuRamBytes / hw.cpuRamTotalBytes * 100 : 0);
  }

  $("llmRunSelect").addEventListener("change", () => {
    selectionVersion++;
    selectedLLMRun = $("llmRunSelect").value;
    resetConversation();
    refresh();
  });
  $("llmChatForm").addEventListener("submit", sendChat);
  return { refresh, deactivate() { controller?.abort(); } };
}
