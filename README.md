# HENTAI Studio

A standalone local dashboard for managing training projects. Register any project directory, configure its commands, and monitor jobs, logs, metrics, and artifacts in a browser.

Studio does **not** install, import, or require HENTAI, PyTorch, or any training framework. Each project uses its own environment and executable. [HENTAI](https://github.com/Lithium357/HENTAI) is a separate diffusion trainer; it also works without Studio.

## Install and start

Requires Python 3.11+ on Windows or Linux.

```sh
python -m venv .venv
# Linux / WSL
.venv/bin/python -m pip install .
.venv/bin/hentai-studio serve --workspace ~/.hentai-studio
# Windows PowerShell
.venv\Scripts\python -m pip install .
.venv\Scripts\hentai-studio serve --workspace "$env:LOCALAPPDATA\HENTAI Studio\workspace"
```

Open <http://127.0.0.1:7860>. An empty workspace is ready to register projects immediately. The workspace contains Studio's registrations and job history; it can live anywhere writable. Training source code remains in each project's own directory.

The API executes local commands and has no authentication. Keep the service bound to loopback and use it as a local application. For Linux/ROCm training, run Studio inside Linux/WSL and register Linux project/interpreter paths. The Windows launcher is optional.

## Register any trainer

Click **Register** and enter an ID, a name, the absolute project directory, and named commands as JSON argument arrays:

```json
{
  "train": ["/home/me/project/.venv/bin/python", "-u", "train.py", "--output", "{output_dir}"],
  "resume": ["/home/me/project/.venv/bin/python", "-u", "train.py", "--resume-from-env"]
}
```

Use the trainer's real arguments; `--resume-from-env` above is an example, not a Studio flag. Studio executes the selected argument array directly in the project directory, with no shell or trainer imports. You can name commands `train`, `evaluate`, `export`, or anything else. Project-specific environments, GPUs, checkpoint formats, and training logic belong to the project.

Commands and environment values support `{project_root}` and `{output_dir}` substitutions. Studio also supplies:

| Variable | Meaning |
| --- | --- |
| `STUDIO_OUTPUT_DIR` | New job's absolute output directory |
| `STUDIO_JOB_ID` | Unique job ID |
| `STUDIO_PROJECT_ID` | Registered project ID |
| `STUDIO_RESUME_DIR` | Previous job's output directory, only when a resume source is selected |

Point your trainer's output argument at `{output_dir}`, read the environment variables, or use a small project-owned wrapper. Trainers that always write to an existing fixed directory still execute and stream logs, but those external files are not automatically imported into Studio. Studio never guesses checkpoint locations or model stages.

Write numeric rows to `metrics.jsonl` (or configure a relative `.csv`/`.jsonl` filename). Example:

```json
{"step": 1, "loss": 2.1, "accuracy": 0.6}
{"step": 2, "loss": 1.8, "accuracy": 0.7}
```

The dashboard plots any numeric column, uses `step` for the horizontal axis when present, and offers downloads for files inside the job output directory. Metrics are optional. See [the API](docs/API.md) for registration and job endpoints.

## Try without a model

[examples/demo_train.py](examples/demo_train.py) uses only the Python standard library. Register this repository as the project root and set commands to your Python executable followed by `-u`, `examples/demo_train.py`. The `train` and `resume` commands can use the same argument array: the demo reads `STUDIO_RESUME_DIR`. Run, stop, and resume from a selected finished job to test the full workflow. [examples/project.json](examples/project.json) is a registration template; replace its absolute paths first.

## Job behavior

- Each project may have one active job; different projects can run concurrently.
- Each job snapshots its project configuration and has separate logs and outputs.
- Stopping terminates the job's trainer process tree. It does not guarantee a final checkpoint; use the trainer's normal checkpoint schedule.
- Dashboard shutdown leaves job supervisors running. Reopen the same workspace to monitor or stop them.
- A missing supervisor becomes `interrupted`. Inspect the project processes before restarting; Studio does not terminate an unverified PID or adopt externally started trainers.
- Resume launches a new job using your selected command and supplies the previous output directory. Your trainer decides which checkpoint to load.
- Unregistering removes the registration only. Project source and job history stay on disk. Re-registering the same ID makes its history visible again.

## Optional tools and desktop shell

Existing causal-LM command line tools are available with `pip install '.[llm]'`; they are optional utilities, not dependencies of the dashboard. See [CLI](docs/CLI.md) and [LLM training](docs/LLM_TRAINING.md).

The optional Windows WebView2 shell uses `STUDIO_EXECUTABLE` (full path to `hentai-studio.exe`, or an executable on PATH) and `STUDIO_WORKSPACE`. It connects to localhost:7860 or starts Studio natively. It requires no HENTAI checkout, fixed user paths, or WSL installation. Build with `dotnet build windows/HENTAIStudio/HENTAIStudio.csproj --configuration Release`.

See [architecture](docs/ARCHITECTURE.md), [development](docs/DEVELOPMENT.md), and [migration](docs/MIGRATION.md). Licensing and extraction history are retained in `LICENSE`, `LICENSE.HENTAI`, and `SOURCE_PROVENANCE.md`.
