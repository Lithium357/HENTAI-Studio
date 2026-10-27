# HENTAI Studio

A standalone local dashboard for training projects. Register a directory and the commands you already use, then manage jobs, logs, metrics, and artifacts in one workspace.

Studio is a process manager, not a trainer. It contains no diffusion models, LoRA/CPT implementation, dataset normalization pipeline, model-specific profiles, or ML dependencies. [HENTAI](https://github.com/Lithium357/HENTAI) and [Lucy](https://github.com/Lithium357/LUCY-ERP) are independent projects that can use Studio as an optional external manager.

## Install and launch

Requires Python 3.11+ on Windows, Linux, or WSL. From this repository:

```sh
python -m venv .venv
# Linux / WSL
.venv/bin/python -m pip install .
.venv/bin/hentai-studio serve
# Windows PowerShell
.venv\Scripts\python -m pip install .
.venv\Scripts\hentai-studio serve
```

Open [localhost:7860](http://127.0.0.1:7860). The default workspace is `~/.hentai-studio`, shared by the command line and desktop launcher. Override it with `--workspace PATH`. An empty workspace is ready to register projects; no engine checkout or training config is needed.

The API executes commands and is intended for local use. It binds to loopback by default and rejects foreign browser origins and unexpected Host headers. It has no account/authentication system. Run Studio inside the environment hosting your trainer: for Linux/ROCm projects, run it in Linux/WSL and use Linux paths.

## Connect a project

Register an ID, display name, absolute project directory and named commands as JSON argument arrays:

```json
{
  "train": ["/absolute/project/.venv/bin/python", "-u", "train.py", "--output", "{output_dir}"],
  "evaluate": ["/absolute/project/.venv/bin/python", "evaluate.py", "--output", "{output_dir}"]
}
```

Use the project's own executable and real flags. Studio executes each array directly, without a shell, in the registered directory. It doesn't activate environments, install project dependencies, guess checkpoint locations or modify project configs. Windows executables and paths work the same way; backslashes must be escaped inside JSON strings.

Commands and configured environment values support `{project_root}` and `{output_dir}` substitutions. Trainers receive:

| Variable | Meaning |
| --- | --- |
| `STUDIO_OUTPUT_DIR` | New job's absolute output directory |
| `STUDIO_JOB_ID` | Unique job ID |
| `STUDIO_PROJECT_ID` | Registered project ID |
| `STUDIO_RESUME_DIR` | Previous job's output directory, only when a resume source is selected |

Write checkpoints and other downloadable files into the supplied output directory. A small wrapper owned by the training project can adapt existing config/output conventions. Commands that write elsewhere still run and stream logs; their external outputs aren't automatically imported.

To plot metrics, write numeric newline-terminated JSONL records to `metrics.jsonl`, or configure a relative `.csv`/`.jsonl` path:

```json
{"step": 1, "loss": 2.1, "accuracy": 0.6}
{"step": 2, "loss": 1.8, "accuracy": 0.7}
```

Any numeric column can be plotted. Metrics are optional. [examples/project.json](examples/project.json) is a registration template; [examples/demo_train.py](examples/demo_train.py) is a standard-library demo with checkpoints, metrics and resume. Register this repository and use your Python executable followed by `examples/demo_train.py` to try it without a model.

## Use from Python

```python
from hentai_studio import StudioClient

studio = StudioClient()
project = studio.create_project("/absolute/project", {"train": ["python", "train.py"]})
job = studio.wait(studio.start_job(project))
print(job["state"], studio.logs(job, tail=8192)["text"])
```

The client handles registration defaults, pagination and structured errors. Project edits use PATCH; all jobs start through POST /api/jobs. See [the API guide](docs/API.md) for HTTP examples, stop/resume, downloads and error handling.

## Manage jobs

Each project can have one active job, while independent projects can run concurrently. Every job snapshots its command/configuration and owns separate output and console files. Dashboard shutdown leaves supervisors running; reopen the same workspace to reconnect.

Stop terminates the selected trainer tree. It does not guarantee a checkpoint. Resume starts a new job using your chosen command and supplies `STUDIO_RESUME_DIR`; your trainer chooses what to restore.

If a supervisor dies, Studio marks the job interrupted and checks recorded process identities. Verified survivors remain stoppable and block another launch for that project. Older jobs created before process identities were recorded may require manual inspection; Studio won't guess or signal an unverified PID.

**All jobs** preserves access to history after a project is unregistered. Unregistration removes only its definition. Project files and job outputs stay on disk. Broken workspace records are reported visibly; valid history stays readable, and launches/registration changes are blocked until the damaged records are repaired.

## Windows desktop shell

Requires .NET 8 Desktop Runtime and Microsoft WebView2 Runtime. Build with:

```powershell
dotnet build windows/HENTAIStudio/HENTAIStudio.csproj --configuration Release
```

The shell uses the same default workspace as the CLI, verifies `/api/health` identifies Studio, reports occupied ports, and writes backend logs to `<workspace>/logs/server.log`. It can reconnect to an existing backend or start one without keeping a console window open.

`windows/HENTAIStudio/build.ps1` publishes the shell only. `build.ps1 -Install -Python C:\path\to\python.exe` explicitly installs the shell, creates its own backend environment and installs Studio into it. Installation copies files without recursively deleting existing application/workspace directories.

Optional overrides: `STUDIO_EXECUTABLE` (backend executable), `STUDIO_WORKSPACE` (workspace directory), `STUDIO_URL` (HTTP loopback URL/port). Without an override the shell first looks for an installed `backend/Scripts/hentai-studio.exe` beside it, then uses PATH. For an existing Python installation, set `STUDIO_EXECUTABLE` to that environment's full `hentai-studio.exe` path.

## Development and documentation

```sh
python -m pip install -e '.[dev]'
pytest
npm test
```

No ML packages are needed for development or tests. [Development](docs/DEVELOPMENT.md) describes browser checks and clean-wheel verification. [API](docs/API.md), [architecture](docs/ARCHITECTURE.md), [dashboard](docs/DASHBOARD.md), [CLI](docs/CLI.md) and [migration](docs/MIGRATION.md) describe the current application.

Licensing and extraction history remain in `LICENSE`, `LICENSE.HENTAI`, and `SOURCE_PROVENANCE.md`.
