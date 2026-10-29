# Dashboard

Start `hentai-studio serve --workspace /absolute/workspace` and open localhost:7860.

1. Register an arbitrary project directory and its named command argument arrays. Use the trainer's own Python or executable.
2. Select a command and click Run command. The job list shows current state and history. One job per project can run; independent projects may run simultaneously.
3. Select a job to inspect its console, choose any numeric metric, and download output files.
4. Use **Stop job** in the sticky job-control toolbar. It remains visible while scrolling and identifies the target run. When viewing a project's history, it targets that project's active job even if an older run is selected. In All jobs, select the active job explicitly. Stop terminates the owned process tree; it does not promise a saved checkpoint. Disabled controls explain whether a job has finished, is stopping, or cannot be controlled while disconnected.
5. To resume, select a finished job, choose your resume command, enable Resume from selected job, and run. The new job receives STUDIO_RESUME_DIR. The trainer decides what to restore.
6. Edit registrations while idle. Unregister keeps source files and job history. All jobs keeps its history visible. Re-register the same ID to restore its project filter.

The dashboard starts empty without an engine checkout, configs, run folders or model libraries. It displays logs for any command. Metrics and artifact discovery require writing into STUDIO_OUTPUT_DIR (or passing {output_dir} to the trainer). Existing external output directories are not scanned. The demo in examples/demo_train.py exercises metrics, checkpoints and resume without an ML library.

The UI polls serially, pauses when the tab is hidden, and ignores obsolete project/job responses. Failed requests display a visible error and retry. The layout adapts to narrow screens. API docs are linked in the header.

Command choices are remembered separately per project during the session and are not reset by polling. Project/job switches cancel old requests, and controls are disabled while the new selection loads or the service is disconnected. Mutation errors remain visible until the next action rather than disappearing during a successful refresh. Logs, metrics and artifacts load independently; one failed panel does not disable stopping a job.

Interrupted jobs with recorded live processes show a recovery message and can still be stopped. Corrupt workspace records appear as visible health issues while valid job history remains readable. New jobs and registration changes are disabled until the damaged records are repaired.

The overview counts follow the current scope: all jobs across the workspace, or only the selected project. Finished jobs include all jobs without an active process (including failed and stopped jobs). The first summary shows registered projects in All jobs and available commands in a project. History can be filtered by command, project, state, or job ID; filtering never changes the selected job or stop target. Each history entry includes a short ID and elapsed duration. Resume sources link back to their job when available in the current scope.

Charts default to loss when available. Metric choices are grouped into training, performance, hardware, and run metadata, and remembered per job for the browser tab's session, including reloads. The chart labels its value range and step/sample range. Move over the chart or use the keyboard-accessible point slider to inspect exact values; polling preserves the inspected position. The plot shows recent bounded samples when the trainer has more history. Compact progress, throughput, step-time, and VRAM measurements appear when supplied by the trainer. Finished jobs with missing metrics or files show a final empty state rather than promising future output.

The console collapses carriage-return progress updates into the final update on each line and removes ANSI controls while preserving newline-delimited diagnostics. Follow scrolls with new output; scroll up to pause it. Filter lines, copy the visible text, or expand the console using its toolbar. This is a readable bounded log view, not a full terminal emulator. Output files are grouped by directory and can be filtered by path within the returned file list. Environment and output settings remain in the registration dialog’s expandable section.

Project and history buttons retain keyboard focus across background refreshes. The history becomes a horizontally scrollable strip on smaller screens, with the job details below it.

Scratch LLM projects have a dedicated configuration form and a Chat tester tab for explicit local checkpoint loading and conversation testing. See [the LLM guide](LLM.md). Generic projects retain their command-based workflow.
