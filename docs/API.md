# Studio API 0.4

The API manages arbitrary local projects and external jobs. Start with `hentai-studio serve --workspace /absolute/workspace`. Swagger UI: `/api/docs`; OpenAPI: `/api/openapi.json`. JSON fields use snake_case. Collection resources return `{"items": [...]}`. No model-specific routes or workload adapters are required.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/api/health` | Version, workspace path, free disk bytes |
| GET / POST | `/api/projects` | List / register (201) |
| GET / PUT / DELETE | `/api/projects/{id}` | Read / replace / unregister (204) |
| GET | `/api/jobs?project_id=example` | List history, newest first; omit filter for all projects |
| POST | `/api/projects/{id}/jobs` | Start configured command (202) |
| GET | `/api/jobs/{id}` | Snapshot and current lifecycle state |
| POST | `/api/jobs/{id}/stop` | Request process-tree termination (202) |
| GET | `/api/jobs/{id}/logs` | UTF-8 console output with byte offsets |
| GET | `/api/jobs/{id}/metrics` | Recent numeric JSONL / CSV records |
| GET | `/api/jobs/{id}/artifacts` | Output files and byte sizes |
| GET | `/api/jobs/{id}/artifacts/{path}` | Download a file inside the output directory |

## Register a project

`POST /api/projects`:

```json
{
  "id": "my-trainer",
  "name": "My trainer",
  "root": "/home/me/trainer",
  "commands": {
    "train": ["/home/me/trainer/.venv/bin/python", "-u", "train.py", "--output", "{output_dir}"]
  },
  "environment": {"CUDA_VISIBLE_DEVICES": "0"},
  "metrics_file": "metrics.jsonl"
}
```

The root must exist and be absolute on the Studio host. IDs and command names use letters, numbers, underscores and hyphens (1–64 characters, first alphanumeric). Commands are nonempty argument arrays; unknown fields are rejected. Environment values are strings. `metrics_file` must be a relative `.jsonl` or `.csv` path inside the job output. PUT replaces the definition and requires the body ID to equal the URL ID. Active projects cannot be edited or unregistered.

Studio executes commands with the project root as cwd, inherits its own process environment, and overlays configured environment values. It does not activate environments automatically: use the project's interpreter or executable. `{project_root}` and `{output_dir}` substitutions work in arguments and environment values. See the README for supplied `STUDIO_*` variables. Definitions, including configured environment values, are stored in the local workspace; use it as private application data.

## Start and resume

`POST /api/projects/my-trainer/jobs`:

```json
{"command": "train", "resume_from": null}
```

The result includes the job ID, immutable project snapshot, command, timestamps, state, exit code, supervisor identity and optional error. A resume source must be a finished job of the same project. Studio supplies its output directory as `STUDIO_RESUME_DIR`; it does not infer or load a checkpoint. Select the appropriate command for the trainer.

States: `starting`, `running`, `stopping`, `succeeded`, `failed`, `stopped`, `interrupted`. A successful exit is `succeeded`; nonzero exit or failure to launch is `failed`. Stop is asynchronous and uses a durable request file. A second start for an active project returns 409. Different projects may run at once. A missing supervisor is marked interrupted after a short startup grace period, without signaling any PID.

## Output observation

Logs accept `offset` (nonnegative byte offset), `limit` (1–65536; default 65536), and `tail=true` (ignore offset and read the final limit bytes). Result: `text`, `next_offset`, `size`. Invalid UTF-8 fragments are replaced. stdout and stderr share one append-only console log. For supervisor diagnostics inspect `jobs/{id}/supervisor.log` in the workspace.

Metrics return `items` and `truncated`. The service reads at most the recent 1 MiB and returns at most 1,000 numeric rows. Invalid/incomplete JSONL records and nonnumeric/nonfinite values are skipped. CSV requires a header row and newline-terminated records; use one record per line without embedded line breaks. `step` is optional. A missing metrics file returns an empty collection.

Artifacts return `items` with relative `path` and byte `size`, plus `truncated`. Traversal is capped at 2,000 entries; directory links are not followed, and paths resolving outside the output directory cannot be downloaded. External run directories and pre-existing training processes are not discovered automatically.

## Errors and transport

```json
{"error": {"code": "project_busy", "message": "This project already has an active job.", "details": []}}
```

404 identifies missing resources, 409 lifecycle conflicts, 422 invalid fields or command selection, 503 supervisor launch failures. Unexpected failures return a generic 500 and are logged on the server. JSON bodies are capped at 128 KiB, including streamed requests, with a 15-second receive timeout. Responses disable caching and content sniffing. The local service has no authentication; keep it bound to loopback.
