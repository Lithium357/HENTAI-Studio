const $ = id => document.getElementById(id);

// Only project_root is known before launch. Output directories are assigned by
// the server when it creates a job; never present a guessed path as resolved.
export function launchDefinition(project, command) {
  return (project?.commands[command] || []).map(argument => argument.replaceAll("{project_root}", project.root));
}

export function renderLaunch(state) {
  const active = state.jobs.some(job => ["starting", "running", "stopping"].includes(job.state) || job.has_live_processes);
  const disclosure = $("launchPanel");
  if (!state.loading && (disclosure.dataset.project !== String(state.projectId) || disclosure.dataset.active !== String(active))) {
    disclosure.open = !active;
    disclosure.dataset.project = String(state.projectId);
    disclosure.dataset.active = String(active);
  }
  $("launchAvailability").textContent = active ? "Unavailable while this project has an active job" : "New command or resume from a finished job";
  const resume = state.launchMode === "resume";
  $("modeNew").checked = !resume;
  $("modeResume").checked = resume;
  $("modeNew").disabled = state.blocked;
  $("modeResume").disabled = !state.canResume;
  $("command").disabled = state.blocked;
  $("start").disabled = !state.canLaunch;
  $("start").textContent = resume ? "Resume run ↗" : "Start new run ↗";
  const reason = state.startReason || (resume && !state.canResume ? "Select a finished job in this project as the resume source." : "");
  $("start").title = reason;
  $("launchHint").textContent = state.project ? reason : "";
  $("launchSource").hidden = !resume;
  $("launchSource").textContent = resume && state.job
    ? `Resume source: ${state.job.command} · ${new Date(state.job.created_at).toLocaleString()} · ${state.job.id}. Studio supplies STUDIO_RESUME_DIR; your trainer decides what to restore.` : "Select a finished job to resume.";
  const argv = launchDefinition(state.project, state.command);
  $("launchDirectory").textContent = state.project?.root || "—";
  $("launchExecutable").textContent = argv[0] || "—";
  $("launchArguments").textContent = JSON.stringify(argv.slice(1), null, 2);
  $("launchSubstitutions").textContent = "Arguments run directly without a shell. {project_root} is expanded above; {output_dir} is assigned at launch. A bare executable name is resolved in the server’s process environment. This preview describes the next run, not the selected job’s historical configuration.";
}

export function bindLaunch(getState, render) {
  for (const [id, mode] of [["modeNew", "new"], ["modeResume", "resume"]]) {
    $(id).onchange = () => { getState().launchMode = mode; render(); };
  }
}
