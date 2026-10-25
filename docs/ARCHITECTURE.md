# Architecture

Studio controls external commands and observes standard files. No trainer or model framework participates in application startup. HENTAI's `scratchtag` package is neither a dependency nor an imported module. HENTAI itself has no Studio dependency.

- `cli.py` starts `serve` with a workspace, host, and port. Optional LLM utility commands import their implementations only when invoked.
- `studio.py` composes the application and Uvicorn transport.
- `api/app.py` declares typed project and job routes and serves the dashboard. `schemas.py` owns validation and the OpenAPI contract. `errors.py` and `middleware.py` own errors and transport limits.
- `jobs/workspace.py` owns registration persistence, job admission, history, output reads, and the workspace lease. It never imports training code.
- `jobs/worker.py` is a separate supervisor process per job. It launches argument arrays without a shell, captures stdout/stderr, observes stop requests, owns process-tree termination, and writes lifecycle state atomically. It survives dashboard shutdown.
- `jobs/files.py` owns atomic JSON replacement, timestamps and file confinement.
- `dashboard_static/` contains a small ES-module UI, typed-resource client, generic metric geometry and serialized polling. Dynamic metadata is written as text, and refreshes discard responses from obsolete selections.
- `workloads/llm/` and its supporting core utilities are optional standalone command line tools. They are not dashboard adapters or runtime requirements.

## Workspace layout

```text
workspace/
  workspace.lock          exclusive dashboard process lease
  projects/{id}.json      project definitions
  jobs/{uuid}/
    job.json              immutable configuration + current lifecycle state
    console.log           trainer stdout/stderr
    supervisor.log        supervisor diagnostics
    stop                  durable stop request, when requested
    output/               trainer-owned outputs, metrics, checkpoints
```

Project files live elsewhere and are not rewritten by registration. Each job captures a complete project definition so history survives edits or unregistration. The worker is the only normal writer of job lifecycle state. The server may mark a vanished worker interrupted, checking PID and process creation time rather than PID alone. One dashboard process may serve a workspace; independent jobs continue across dashboard restarts. The server's in-process lock serializes starts and edits, preventing duplicate jobs for a project.

Stop terminates only the selected supervisor's child tree, waits up to five seconds, then kills survivors. Observed descendants are cleaned up if the trainer exits first. Studio does not adopt external jobs, promise a graceful checkpoint, or manage remote schedulers. A supervisor killed externally may leave trainer processes behind; inspect them before restarting an interrupted job.

## Integration boundary

A project supplies its own executable, dependencies and checkpoint logic. Studio supplies the cwd, an output directory, environment variables and logs. Existing trainers can consume output CLI arguments or use a small wrapper owned by that project. JSONL/CSV numeric metrics are optional. No named model stages, model architecture enum, hardcoded watchdog script, training-config format or checkpoint layout is part of Studio's API.
