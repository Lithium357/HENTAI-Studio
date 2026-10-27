# Architecture

Studio runs external commands and observes standard files. Domain/application code does not import FastAPI, any training framework, HENTAI or Lucy. Model and dataset logic belong to each external project.

| Component | Responsibility |
| --- | --- |
| `models.py`, `errors.py` | Validated project/job/output types and application errors |
| `cli.py`, `studio.py` | Workspace selection and application composition |
| `api/` | FastAPI routes, error translation, request limits, origin/Host checks and Uvicorn logging |
| `jobs/workspace.py` | Project registry, admission checks, history, reconciliation and orphan recovery |
| `jobs/lease.py` | Exclusive dashboard ownership of one workspace |
| `jobs/worker.py` | Durable per-job external-command supervisor |
| `jobs/processes.py` | PID/creation-time verification and owned-tree termination |
| `jobs/outputs.py` | Bounded logs, JSONL/CSV metrics and confined artifacts |
| `jobs/files.py` | Atomic persistence, Windows sharing retries, timestamps and confinement |
| `dashboard_static/state.js` | Pure selection, lifecycle and control eligibility state |
| `dashboard_static/views.js` | Safe text rendering and independent output panels |
| `dashboard_static/editor.js` | Registration form and validation feedback |
| `dashboard_static/app.js` | Polling, cancellation and mutation coordination |
| `dashboard_static/api.js`, `metrics.js`, `poller.js` | Transport, generic geometry and serialized refresh scheduling |

## Workspace

```text
workspace/
  workspace.lock
  projects/{id}.json
  jobs/{uuid}/
    job.json
    processes.json
    supervisor.json
    console.log
    supervisor.log
    stop
    output/
```

A job snapshots its project definition, command and resume source. The worker owns normal lifecycle writes and records trainer/descendant PID creation times in processes.json. The parent records supervisor identity in supervisor.json, and the worker waits for that launch commitment before starting the trainer. This prevents a slow Python startup from admitting a duplicate job. Output files remain project-owned. The server serializes registration changes and starts with an in-process lock, while the workspace lease excludes a second server process.

The server checks supervisor identity when reading active jobs. After the startup grace period, a missing supervisor marks the job interrupted. Live recorded trainer processes block duplicate starts, edits, unregistration and resume. Stop can recover and terminate verified survivors after the supervisor dies. Unknown old processes are never adopted or signaled by guessed names. A worker that exits between creating a process and durably recording its identity can still leave an unrecorded process; inspect the project if that exceptional startup window is interrupted.

Malformed metadata is surfaced as workspace health issues. Valid records remain readable. New launches and registration mutations fail closed until records are repaired; this avoids starting a duplicate trainer whose previous metadata cannot be interpreted. Case-insensitive project identity prevents registrations that would collide on Windows.

Output reads are independent of lifecycle control. Metrics read recent bounded JSONL/CSV rows and discard invalid, incomplete and nonfinite values. Artifact paths must remain under the job output root; linked output roots are rejected. A failed output panel doesn't make the frontend lose access to status or stopping.

## Boundaries

The CLI contains only Studio commands; no LLM extra, trainer, tokenizer, data normalizer or project-specific profile is installed. Historical training code remains recoverable from Git, with migration instructions in MIGRATION.md. The standalone ADLX probe source and vendored licenses remain in hardware_probe/ and vendor/ as a separate native utility; it is not packaged or loaded by the Python app.

The Windows shell verifies application identity through HTTP and launches the backend with file logging. It does not own trainer lifetime or redirect backend logs through pipes that would disappear when the shell closes. Its default workspace matches the Python CLI.

## Public API boundary (0.6)

The app factory composes resource routers rather than defining the entire API in closures. api/routes/projects.py owns registration and partial edits; api/routes/jobs.py owns the global job collection, lifecycle and outputs. api/schemas.py defines separate public inputs/responses. api/presenters.py translates persistence Job records into compact caller resources with links/actions, keeping process identities, full snapshots and environment overrides private. api/pagination.py owns filter-scoped keyset cursors. Dependencies are explicit and operation IDs are stable in OpenAPI.

client.py is a synchronous standard-library Python client. It follows pagination and exposes registration, partial updates, jobs, wait/stop/resume, logs, metrics and artifact downloads. It uses the same HTTP contract as the browser; no in-process service shortcuts or hidden job-creation retries are involved. Input DTOs, public jobs and persistence models remain distinct.
