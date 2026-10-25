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
      const [status, catalog, samples] = await Promise.all([
        api.diffusion.status(request.signal), api.diffusion.checkpoints(request.signal), api.diffusion.samples(request.signal),
      ]);
      const data = {...status, checkpoint_catalog: catalog.items, samples: samples.items};
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
      $("runSelect").innerHTML = checkpointCatalog.map(run => `<option value="${escapeHTML(run.id)}">${escapeHTML(run.display_name)} · ${run.resolution_px}px</option>`).join("");
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
    $("startDiffusionButton").disabled = actionPending || (latestStatus.sampling?.status === "running") || !latestStatus.checkpoints?.length;
    const historical = $("sourceMode").value === "historical";
    const samplingVae = activeStage === "vae" && !historical;
    const selectedCheckpoint = Boolean($("checkpointSelect").value);
    const latest = latestStatus.checkpoints?.[0];
    const waitingForVaeCheckpoint = samplingVae && !latest;
    const checkpointEvery = Number(latestStatus.checkpoint_every || 1000);
    const currentStep = Number(latestStatus.progress?.step || 0);
    const nextCheckpointStep = Math.max(checkpointEvery, Math.ceil((currentStep + 1) / checkpointEvery) * checkpointEvery);
    const stepsUntilCheckpoint = Math.max(0, nextCheckpointStep - currentStep);
    const checkpointEta = stepsUntilCheckpoint * Number(latestStatus.progress?.seconds_per_step || 0);
    $("historicalFields").hidden = !historical;
    ["tagsInput", "seedInput", "stepsInput", "guidanceInput"].forEach(id => { $(id).disabled = samplingVae; });
    $("sampleButton").disabled = actionPending || (latestStatus.sampling?.status === "running") || (historical ? !selectedCheckpoint : !latest);
    $("sampleButton").textContent = (latestStatus.sampling?.status === "running")
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
    if (latestStatus.sampling?.status === "failed") {
      $("sampleHelp").textContent = `The last sample failed (exit code ${latestStatus.sampling.exit_code}). Review the checkpoint and engine setup before retrying. ${$("sampleHelp").textContent}`;
    }
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
    $("stageEyebrow").textContent = `${data.architecture_label || "SCRATCH"} / ${stages.active === "diffusion" ? "DIFFUSION" : "VAE"}`;
    $("checkpointBadge").textContent = latest ? `${latest.name} safe` : "No checkpoint";
    [["vae", vae], ["diffusion", diffusion], ["overall", overall]].forEach(([name, stage]) => {
      $(`${name}ProgressFill`).style.width = `${Math.min(100, stage.percent || 0)}%`;
      $(`${name}PercentLabel`).textContent = `${formatNumber(stage.percent || 0, 2)}% complete`;
      $(`${name}Count`).textContent = `${formatNumber(stage.step)} / ${formatNumber(stage.total)}`;
    });
    $("vaeState").textContent = (vae.percent || 0) >= 100 ? "Complete" : (stages.active === "vae" ? "Training now" : "Waiting");
    $("diffusionState").textContent = (diffusion.percent || 0) >= 100 ? "Complete" : (stages.active === "diffusion" ? "Training now" : "Queued");
    $("etaLabel").textContent = p.eta_seconds ? `Rolling ETA ${formatDuration(p.eta_seconds)}` : "ETA —";
    $("lossValue").textContent = p.loss != null ? formatNumber(p.loss, 4) : "—";
    $("paceValue").textContent = p.seconds_per_step != null ? formatNumber(p.seconds_per_step, 2) : "—";
    $("throughputValue").textContent = p.images_per_second != null ? formatNumber(p.images_per_second, 2) : "—";
    $("safeStepValue").textContent = latest ? formatNumber(latest.step) : "—";
    $("healthTitle").textContent = data.running ? (data.watchdog_running ? "Trainer is protected" : "Trainer is healthy") : (data.paused ? "Trainer intentionally paused" : "Automatic recovery pending");
    $("healthCopy").textContent = data.running
      ? `Process ${data.pids.join(", ")} is active. ${data.watchdog_running ? "The watchdog will resume it after an unexpected exit." : "Automatic recovery is not active."}`
      : (data.paused ? "HENTAI Studio will leave training stopped until you press Resume." : "The watchdog will load the latest completed checkpoint automatically.");
    $("stopButton").disabled = !data.running;
    $("resumeButton").disabled = data.running;
    $("startDiffusionButton").hidden = !samplingVae;
    $("startDiffusionButton").disabled = (data.sampling?.status === "running") || !latest;
    $("trainerMicrocopy").textContent = samplingVae
      ? "The diffuser button discards only progress after the latest safe VAE checkpoint, calibrates that VAE, then starts diffusion automatically."
      : "Diffuser training is active. Stop and resume both preserve the latest completed checkpoint.";
    syncCheckpointMenus(data.checkpoint_catalog);
    updateSampleControls();
    $("diskLabel").textContent = `${formatBytes(data.disk?.free_bytes)} free`;
    const hw = data.hardware || {};
    $("gpuUsage").textContent = valueOrDash(hw.gpu_usage_pct, "%", 0);
    $("gpuVram").textContent = hw.gpu_vram_bytes == null ? "—" : `${formatBytes(hw.gpu_vram_bytes)} / ${formatBytes(hw.gpu_vram_total_bytes)}`;
    $("gpuTemp").textContent = hw.gpu_temp_c == null ? "—" : `${formatNumber(hw.gpu_temp_c, 0)}° / ${formatNumber(hw.gpu_hotspot_c, 0)}°C`;
    $("gpuFan").textContent = valueOrDash(hw.gpu_fan_rpm, " RPM", 0);
    $("cpuUsage").textContent = valueOrDash(hw.cpu_usage_pct, "%", 1);
    $("cpuTemp").textContent = hw.cpu_temp_c == null ? "N/A" : `${formatNumber(hw.cpu_temp_c, 0)}°C`;
    $("cpuRam").textContent = hw.cpu_ram_bytes == null ? "—" : formatBytes(hw.cpu_ram_bytes);
    $("workloadPower").textContent = valueOrDash(hw.workload_power_w, " W", 0);
    $("energyUsed").textContent = valueOrDash(hw.energy_kwh, " kWh", 3);
    $("powerDetail").textContent = hw.gpu_board_power_w == null ? "waiting for active workload" : `${formatNumber(hw.gpu_board_power_w, 0)} W GPU board + attributed CPU`;
    $("hardwareNote").textContent = hw.scope_note || "Hardware sensors unavailable.";
    $("hardwareScope").textContent = hw.available ? "LIVE · PROCESS + ATTRIBUTED" : "TRAINER IDLE";
    setMeter("gpuUsageBar", hw.gpu_usage_pct);
    setMeter("gpuVramBar", hw.gpu_vram_bytes && hw.gpu_vram_total_bytes ? hw.gpu_vram_bytes / hw.gpu_vram_total_bytes * 100 : 0);
    setMeter("cpuUsageBar", hw.cpu_usage_pct);
    setMeter("cpuRamBar", hw.cpu_ram_bytes && hw.cpu_ram_total_bytes ? hw.cpu_ram_bytes / hw.cpu_ram_total_bytes * 100 : 0);
    $("checkpointList").innerHTML = checkpoints.length ? checkpoints.map(cp => `<div class="checkpoint-item"><div class="checkpoint-icon">${escapeHTML(String(cp.step / 1000).replace(".0",""))}K</div><div><strong>${escapeHTML(cp.name)}</strong><small>${new Date(cp.modified_at * 1000).toLocaleString()}</small></div><span class="checkpoint-size">${formatBytes(cp.size_bytes)}</span></div>`).join("") : '<p class="empty">No completed checkpoints yet.</p>';
    drawChartInto("lossChart", data.loss_history);
    const latestSample = data.samples?.[0];
    const sampleStage = $("sampleStage");
    if (latestSample && /^\/api\/diffusion\/samples\/[^/]+$/.test(latestSample.url)) {
      const image = document.createElement("img");
      image.src = `${latestSample.url}?v=${Number(latestSample.modified_at)}`;
      image.alt = "Latest generated checkpoint sample";
      sampleStage.replaceChildren(image);
    } else {
      sampleStage.innerHTML = '<div class="sample-empty"><span>◇</span><p>No dashboard samples yet</p><small>Generate one from the latest checkpoint.</small></div>';
    }
    $("refreshLabel").textContent = `Updated ${new Date(data.server_time * 1000).toLocaleTimeString()}`;
  }

  async function runCommand(command, success) {
    if (actionPending) return;
    actionPending = true;
    updateSampleControls();
    try {
      await command();
      toast(success);
      await refresh();
    } catch (error) {
      toast(error.message);
    } finally {
      actionPending = false;
      updateSampleControls();
    }
  }



  $("stopButton").addEventListener("click", () => { if (confirm("Stop training now? Progress since the latest checkpoint will be repeated on resume.")) runCommand(api.diffusion.pause, "Trainer stop requested"); });
  $("resumeButton").addEventListener("click", () => runCommand(api.diffusion.resume, "Trainer resume requested"));
  $("startDiffusionButton").addEventListener("click", () => { if (confirm("End VAE training at the latest safe checkpoint and begin diffuser training? This cannot resume the same VAE run unless the promoted model is removed manually.")) runCommand(api.diffusion.promoteVae, "VAE checkpoint promoted; diffuser startup requested"); });
  $("sourceMode").addEventListener("change", updateSampleControls);
  $("runSelect").addEventListener("change", syncCheckpointOptions);
  $("checkpointSelect").addEventListener("change", updateSampleControls);
  $("sampleForm").addEventListener("submit", event => {
    event.preventDefault();
    const historical = $("sourceMode").value === "historical";
    runCommand(() => api.diffusion.createSample({
      source: historical ? "checkpoint" : "current",
      ...(historical ? {run_id: $("runSelect").value, checkpoint_id: $("checkpointSelect").value} : {}),
      tags: $("tagsInput").value.split(",").map(tag => tag.trim()).filter(Boolean),
      seed: Number($("seedInput").value),
      steps: Number($("stepsInput").value),
      guidance: Number($("guidanceInput").value)
    }), historical ? "Historical checkpoint sample started on CPU" : (activeStage === "vae" ? "Random VAE reconstruction started on CPU" : "Checkpoint sample started on CPU"));
  });

  return { refresh, deactivate() { controller?.abort(); } };
}
