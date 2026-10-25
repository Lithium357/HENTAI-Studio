import { $, escapeHTML, setMeter, toast, setConnection } from "./dom.js";
import { formatNumber, formatBytes, formatDuration, valueOrDash } from "./format.js";
import { drawChartInto } from "./charts.js";
import { api } from "./api.js";

export function createDiffusionWorkspace() {
  let activeStage = "vae";
  let checkpointCatalog = [];
  let latestStatus = {};
  let actionPending = false;
  let controller;

  async function refresh() {
    controller?.abort();
    const request = controller = new AbortController();
    try {
      const data = await api.status(request.signal);
      if (!request.signal.aborted) render(data);
    } catch (error) {
      if (!request.signal.aborted) setConnection("Dashboard disconnected");
    }
  }

  function syncCheckpointMenus(catalog) {
    checkpointCatalog = catalog || [];
    const previousRun = $("runSelect").value;
    const signature = checkpointCatalog.map(run => `${escapeHTML(run.id)}:${run.checkpoints.map(cp => cp.id).join(",")}`).join("|");
    if ($("runSelect").dataset.signature !== signature) {
      $("runSelect").innerHTML = checkpointCatalog.map(run => `<option value="${escapeHTML(run.id)}">${escapeHTML(run.label)} · ${run.resolution}px</option>`).join("");
      $("runSelect").dataset.signature = signature;
      if (checkpointCatalog.some(run => run.id === previousRun)) $("runSelect").value = previousRun;
      syncCheckpointOptions();
    }
  }

  function syncCheckpointOptions() {
    const run = checkpointCatalog.find(item => item.id === $("runSelect").value);
    const previous = $("checkpointSelect").value;
    $("checkpointSelect").innerHTML = run ? run.checkpoints.map(cp => `<option value="${escapeHTML(cp.id)}">Step ${formatNumber(cp.step)}</option>`).join("") : '<option value="">No diffusion checkpoints found</option>';
    if (run?.checkpoints.some(cp => cp.id === previous)) $("checkpointSelect").value = previous;
    updateSampleControls();
  }

  function updateSampleControls() {
    $("stopButton").disabled = actionPending || !latestStatus.running;
    $("resumeButton").disabled = actionPending || latestStatus.running;
    $("startDiffusionButton").disabled = actionPending || latestStatus.sampling || !latestStatus.checkpoints?.length;
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
    $("sampleButton").disabled = actionPending || Boolean(latestStatus.sampling) || (historical ? !selectedCheckpoint : !latest);
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
    $("checkpointList").innerHTML = checkpoints.length ? checkpoints.map(cp => `<div class="checkpoint-item"><div class="checkpoint-icon">${escapeHTML(String(cp.step / 1000).replace(".0",""))}K</div><div><strong>${escapeHTML(cp.name)}</strong><small>${new Date(cp.modifiedAt * 1000).toLocaleString()}</small></div><span class="checkpoint-size">${formatBytes(cp.size)}</span></div>`).join("") : '<p class="empty">No completed checkpoints yet.</p>';
    drawChartInto("lossChart", data.lossHistory);
    const latestSample = data.samples?.[0];
    const sampleStage = $("sampleStage");
    if (latestSample && /^\/samples\/[^/]+$/.test(latestSample.url)) {
      const image = document.createElement("img");
      image.src = `${latestSample.url}?v=${Number(latestSample.modifiedAt)}`;
      image.alt = "Latest generated checkpoint sample";
      sampleStage.replaceChildren(image);
    } else {
      sampleStage.innerHTML = '<div class="sample-empty"><span>◇</span><p>No dashboard samples yet</p><small>Generate one from the latest checkpoint.</small></div>';
    }
    $("refreshLabel").textContent = `Updated ${new Date(data.serverTime * 1000).toLocaleTimeString()}`;
  }

  async function action(payload, success) {
    if (actionPending) return;
    actionPending = true;
    updateSampleControls();
    try {
      await api.action(payload);
      toast(success);
      await refresh();
    } catch (error) {
      toast(error.message);
    } finally {
      actionPending = false;
      updateSampleControls();
    }
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

  return { refresh, deactivate() { controller?.abort(); } };
}
