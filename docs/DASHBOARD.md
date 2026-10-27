# Dashboard

Start `hentai-studio serve --workspace /absolute/workspace` and open localhost:7860.

1. Register an arbitrary project directory and its named command argument arrays. Use the trainer's own Python or executable.
2. Select a command and click Run command. The job list shows current state and history. One job per project can run; independent projects may run simultaneously.
3. Select a job to inspect its console, choose any numeric metric, and download output files.
4. Stop terminates that job's process tree. It does not promise a saved checkpoint.
5. To resume, select a finished job, choose your resume command, enable Use selected job as resume source, and run. The new job receives STUDIO_RESUME_DIR. The trainer decides what to restore.
6. Edit registrations while idle. Unregister keeps source files and job history. All jobs keeps its history visible. Re-register the same ID to restore its project filter.

The dashboard starts empty without an engine checkout, configs, run folders or model libraries. It displays logs for any command. Metrics and artifact discovery require writing into STUDIO_OUTPUT_DIR (or passing {output_dir} to the trainer). Existing external output directories are not scanned. The demo in examples/demo_train.py exercises metrics, checkpoints and resume without an ML library.

The UI polls serially, pauses when the tab is hidden, and ignores obsolete project/job responses. Failed requests display a visible error and retry. The layout adapts to narrow screens. API docs are linked in the header.

Command choices are remembered separately per project during the session and are not reset by polling. Project/job switches cancel old requests, and controls are disabled while the new selection loads or the service is disconnected. Mutation errors remain visible until the next action rather than disappearing during a successful refresh. Logs, metrics and artifacts load independently; one failed panel does not disable stopping a job.

Interrupted jobs with recorded live processes show a recovery message and can still be stopped. Corrupt workspace records appear as visible health issues while valid job history remains readable. New jobs and registration changes are disabled until the damaged records are repaired.
