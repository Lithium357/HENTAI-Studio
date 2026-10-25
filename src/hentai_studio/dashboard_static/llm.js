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
      const [runPayload, storage] = await Promise.all([api.runs.list("llm.causal", request.signal), api.system.storage(request.signal)]);
      const candidates = runPayload.items.filter(run => run.workload_type === "llm.causal");
      const runId = candidates.some(run => run.id === selectedLLMRun) ? selectedLLMRun : candidates[0]?.id || "";
      const [status, checkpointPayload] = runId ? await Promise.all([
        api.runs.get(runId, request.signal), api.runs.checkpoints(runId, request.signal),
      ]) : [null, {items: []}];
      if (request.signal.aborted || version !== selectionVersion) return;
      if (selectedLLMRun && selectedLLMRun !== runId) resetConversation();
      selectedLLMRun = runId;
      $("llmRunSelect").value = runId;
      ready = Boolean(status?.capabilities?.chat);
      renderLLM(runPayload.items, storage, status, checkpointPayload.items);
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
      const payload = await api.runs.completeChat(runId, llmConversation, request.signal);
      if (request.signal.aborted || selectionVersion !== version || selectedLLMRun !== runId) return;
      llmConversation.push({role: "assistant", content: payload.message.content});
      pending.querySelector("p").textContent = payload.message.content;
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
    llmRuns = runs.filter(run => run.workload_type === "llm.causal");
    const selector = $("llmRunSelect");
    const before = selector.value || selectedLLMRun;
    selector.innerHTML = llmRuns.length ? llmRuns.map(run => `<option value="${escapeHTML(run.id)}">${escapeHTML(run.display_name)} · ${escapeHTML(run.state)}</option>`).join("") : '<option value="">No prepared LLM runs</option>';
    selectedLLMRun = llmRuns.some(run => run.id === before) ? before : (llmRuns[0]?.id || "");
    selector.value = selectedLLMRun;
    const run = llmRuns.find(item => item.id === selectedLLMRun);
    const liveState = selectedStatus?.state || run?.state || "No run selected";
    $("llmTitle").textContent = run ? run.display_name : "No prepared LLM run";
    $("llmModeBadge").textContent = liveState;
    $("llmSummary").textContent = run ? `Workload: ${run.workload_type}. It is managed separately from the diffusion trainer.` : "Prepare a run from a validated LLM profile before it appears here.";
    const progress = selectedStatus?.progress || {}, totalSteps = Number(progress.total_steps || 0), step = Number(progress.step || 0), seconds = Number(progress.seconds_per_step || 0);
    const hasPlan = totalSteps > 0;
    $("llmStep").textContent = step ? `${formatNumber(step)}${hasPlan ? ` / ${formatNumber(totalSteps)}` : ""}` : "—";
    $("llmProgressFill").style.width = `${hasPlan ? Math.min(100, step / totalSteps * 100) : 0}%`;
    $("llmProgressLabel").textContent = step ? (hasPlan ? `${formatNumber(step / totalSteps * 100, 2)}% complete` : "Training in progress") : "Waiting for first durable step";
    $("llmEta").textContent = seconds && step && hasPlan ? `Rolling ETA ${formatDuration((totalSteps - step) * seconds)}` : "ETA —";
    $("llmStepTime").textContent = seconds ? formatNumber(seconds, 2) : "—";
    $("llmThroughput").textContent = progress.tokens_per_second ? formatNumber(progress.tokens_per_second, 0) : "—";
    $("llmTokensSeen").textContent = progress.tokens_seen ? formatNumber(progress.tokens_seen) : "—";
    $("llmStorage").textContent = storage ? formatBytes(storage.free_bytes) : "—";
    $("llmRunState").textContent = liveState;
    const chatReady = ready;
    $("llmChatStatus").textContent = chatReady ? "CPU ONLY" : (run ? "CHECKPOINT REQUIRED" : "SELECT A RUN");
    $("llmChatInput").disabled = !chatReady || chatPending;
    $("llmChatSend").disabled = !chatReady || chatPending;
    $("llmChatHelp").textContent = chatReady ? "Replies are generated locally on CPU; GPU training and VRAM are untouched." : (run ? "Chat unlocks at the first completed adapter checkpoint." : "Select a prepared LLM run first.");
    $("llmCheckpointList").innerHTML = checkpoints?.length ? checkpoints.map(cp => `<div class="checkpoint-item"><div class="checkpoint-icon">${escapeHTML(String(cp.step || 0))}</div><div><strong>${escapeHTML(cp.id)}</strong><small>${cp.complete ? "Complete" : "Incomplete — ignored"} · ${new Date(cp.modified_at * 1000).toLocaleString()}</small></div><span class="checkpoint-size">${formatBytes(cp.size_bytes)}</span></div>`).join("") : '<p class="empty">No complete LLM checkpoints yet.</p>';
    drawChartInto("llmLossChart", selectedStatus?.loss_history || []);
    const validations = (selectedStatus?.loss_history || []).filter(point => point.eval_loss != null);
    $("llmValidationStatus").textContent = validations.length
      ? `Latest VL ${formatNumber(validations.at(-1).eval_loss, 4)} · step ${formatNumber(validations.at(-1).step)}`
      : "No validation result yet";
    renderLLMHardware(selectedStatus?.hardware);
    setConnection(run ? `${run.display_name} · ${liveState}` : "No LLM run selected", liveState === "running");
  }

  function renderLLMHardware(hw = {}) {
    const available = Boolean(hw.available);
    $("llmHardwareScope").textContent = available ? "LLM TRAINER · PROCESS ATTRIBUTED" : "LLM TRAINER IDLE";
    $("llmGpuUsage").textContent = valueOrDash(hw.gpu_usage_pct, "%", 0); $("llmGpuVram").textContent = hw.gpu_vram_bytes == null ? "—" : `${formatBytes(hw.gpu_vram_bytes)} / ${formatBytes(hw.gpu_vram_total_bytes)}`;
    $("llmGpuTemp").textContent = hw.gpu_temp_c == null ? "—" : `${formatNumber(hw.gpu_temp_c, 0)}° / ${formatNumber(hw.gpu_hotspot_c, 0)}°C`; $("llmGpuFan").textContent = valueOrDash(hw.gpu_fan_rpm, " RPM", 0);
    $("llmCpuUsage").textContent = valueOrDash(hw.cpu_usage_pct, "%", 1); $("llmCpuRam").textContent = hw.cpu_ram_bytes == null ? "—" : formatBytes(hw.cpu_ram_bytes); $("llmWorkloadPower").textContent = valueOrDash(hw.workload_power_w, " W", 0); $("llmEnergyUsed").textContent = valueOrDash(hw.energy_kwh, " kWh", 3);
    setMeter("llmGpuUsageBar", hw.gpu_usage_pct); setMeter("llmGpuVramBar", hw.gpu_vram_bytes && hw.gpu_vram_total_bytes ? hw.gpu_vram_bytes / hw.gpu_vram_total_bytes * 100 : 0); setMeter("llmCpuUsageBar", hw.cpu_usage_pct); setMeter("llmCpuRamBar", hw.cpu_ram_bytes && hw.cpu_ram_total_bytes ? hw.cpu_ram_bytes / hw.cpu_ram_total_bytes * 100 : 0);
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
