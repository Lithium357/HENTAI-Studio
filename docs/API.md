# Studio API 0.7

Register a project once, start its commands as jobs, and follow the returned job URL. The API works without any model framework or training-project import. Start `hentai-studio serve`; the default server is `http://127.0.0.1:7860`.

[Interactive docs](http://127.0.0.1:7860/api/docs) describe every request and response. OpenAPI is `/api/openapi.json`, with stable operation IDs for generated clients. JSON fields use snake_case. Internal process IDs, full project snapshots and configured environment values are excluded from job responses.

## Python: the complete workflow

The installed package provides a standard-library client; requests/httpx are not required:

```python
from hentai_studio import StudioClient, StudioAPIError

studio = StudioClient()  # or StudioClient("http://127.0.0.1:9000")
project = studio.create_project(
    "/absolute/project",
    {"train": ["/absolute/project/.venv/bin/python", "train.py", "--output", "{output_dir}"]},
)
# ID and display name are inferred/generated when omitted.
job = studio.start_job(project)  # defaults to "train", or the project's only command
finished = studio.wait(job, timeout=3600)
print(finished["state"], finished["exit_code"])
print(studio.logs(finished, tail=65536)["text"])
for file in studio.artifacts(finished)["items"]:
    print(file["path"], file["download_url"])
```

Pass either a resource dictionary or its ID to methods that select one project/job. Client methods return plain dictionaries matching the HTTP API. `wait` returns the first finished state, including failed/interrupted; inspect the returned state rather than assuming success. A client wait timeout raises `TimeoutError`; it does not stop training. Each HTTP request also has the client's configured timeout (15 seconds by default).

```python
studio.update_project(project, name="Renamed")  # only this field changes
studio.stop_job(job)                           # safe to repeat
resumed = studio.resume_job(finished)          # new job, same command by default
# Supply command="resume" instead only if that command is registered.

for job in studio.iter_jobs(project_id=project["id"], state="failed", page_size=50):
    print(job["id"], job["error"])

studio.download_artifact(finished, "checkpoints/weights.bin", "weights.bin")
```

`list_projects`/`list_jobs` follow pagination and return lists; `iter_jobs` yields one resource at a time. `request(method, "/api/...", body)` is an escape hatch for other resources. `StudioAPIError` exposes `status`, `code`, `details`, and a readable message. A network failure has status `None` and code `connection_error`. The client performs no hidden retries of job creation.

## HTTP: register, start, observe

1. Register with `POST /api/projects`:

```json
{
  "root": "/absolute/project",
  "commands": {"train": ["/absolute/project/.venv/bin/python", "train.py", "--output", "{output_dir}"]}
}
```

The 201 response contains the project definition, including its ID. `Location` points to `/api/projects/{id}`. Optional registration fields: `id`, `name`, `environment` (string map, default `{}`), and `metrics_file` (default `metrics.jsonl`). The directory must exist and be absolute on the Studio host. Generated IDs start with `project-`; default names use the directory name.

2. Start with `POST /api/jobs`:

```json
{"project_id": "the-id-from-registration"}
```

`command` is optional when the project has a `train` command or exactly one command; otherwise the 422 response lists the choices. A 202 response contains the job and `Location: /api/jobs/{id}`. The job includes `project_id`, `project_name`, `command`, `state`, timestamps, exit code/error, `has_live_processes`, `actions`, and ready-to-use `links` to status, logs, metrics, artifacts, stop and resume. No supervisor or trainer PID is part of the public contract.

3. Read the returned job URL and its `links.logs`. Jobs move through `starting`, `running`, `stopping`, then `succeeded`, `failed`, `stopped` or `interrupted`. Start/stop/resume are asynchronous: a 202 accepts the operation; it does not mean training has completed. Each project may have one busy job. Different projects can run concurrently.

## Resources

| Method | Path | Request / result |
| --- | --- | --- |
| GET | `/api/health` | Application identity, version, workspace diagnostics |
| POST | `/api/projects` | Register; 201 + project + Location |
| GET | `/api/projects` | Project page |
| GET | `/api/projects/{id}` | Project definition |
| PATCH | `/api/projects/{id}` | Change supplied fields only; 200 + project |
| DELETE | `/api/projects/{id}` | Unregister; 204; source files and history remain |
| POST | `/api/jobs` | Start; 202 + job + Location |
| GET | `/api/jobs` | Job page; filter by `project_id` and/or `state` |
| GET | `/api/jobs/{id}` | Current job, links and actions |
| POST | `/api/jobs/{id}/stop` | 202 while stopping, 200 when already finished |
| POST | `/api/jobs/{id}/resume` | New job; 202 + job + Location |
| GET | `/api/jobs/{id}/logs` | Text with byte offsets and EOF flag |
| GET | `/api/jobs/{id}/metrics` | Recent numeric rows and truncation flag |
| GET | `/api/jobs/{id}/artifacts` | Output files, sizes, download URLs, truncation flag |
| GET | `/api/jobs/{id}/artifacts/{path}` | Download the output file |

### Edits

`PATCH /api/projects/{id}` accepts any nonempty subset of `name`, `root`, `commands`, `environment`, `metrics_file`. No duplicated ID is required in the body. Omitted fields stay unchanged. Supplied command/environment maps replace their respective maps; send `environment: {}` to clear overrides. Null values and an empty patch are errors. Changes are validated and saved atomically; an invalid patch changes nothing. Busy projects cannot be edited or unregistered.

IDs/command names use alphanumeric characters, underscores and hyphens, up to 64 characters with an alphanumeric first character. Project IDs cannot collide by case, and Windows device names are rejected. Arguments execute directly without a shell. Empty argument strings are supported when the executable is nonempty. Use the project's own interpreter; Studio does not activate environments or install project packages.

### Resume and stop

`POST /api/jobs/{id}/resume` accepts no body, `{}`, or `{"command":"resume"}`. It starts a new job of the source's registered project, supplies that finished job's output directory as `STUDIO_RESUME_DIR`, and uses the source command unless overridden. Your trainer decides what to restore. Resume uses the current registered project definition; it does not restore an old environment or argument array. Resume is a creation operation: repeated calls can create another job once a previous job has finished. It is not automatically retried by the client.

Stop is idempotent. Repeated stop requests return the current job, including finished jobs; a missing job still returns 404. A durable stop request is immediately reflected as public state `stopping`. Verified orphan processes remain stoppable after a supervisor dies and block duplicate starts. Very old jobs without recorded process identities require manual inspection. `actions` reflects current eligibility and is advisory: another request may change workspace state before your action arrives.

### Pagination

Projects and jobs accept `limit` (1–200, default 50) and an opaque `cursor`:

```json
{"items": [], "next_cursor": null}
```

When `next_cursor` is non-null, send it as the next request's cursor with the same filters. Jobs are newest first with ID tie-breaking; projects sort by ID descending. Newly created jobs do not shift previously read pages or cause duplicates. Malformed cursors or cursors from another collection/filter return 422. Completed/archived jobs remain filterable after project unregistration. Invalid workspace records are omitted from lists and reported through health issues. Pagination limits response size; storage still reads local history to reconcile process state.

### Logs

Use `?offset=0&limit=65536` to read forward, then pass the returned `next_offset`. Or use `?tail=8192` for the final 8 KiB. Offset and tail are mutually exclusive. Byte counts are explicit; limit/tail range from 1 to 65,536.

```json
{"text":"training…\n", "next_offset":100, "size":100, "eof":true}
```

`eof` means the current file end, not that training has finished. Poll again at the same next offset for new output. stdout/stderr share one append-only log; invalid UTF-8 fragments are replaced. Missing output is an empty log. For supervisor diagnostics, inspect the local `supervisor.log` in the job's workspace directory.

### Metrics and artifacts

Metrics read the configured relative JSONL/CSV file inside the job output directory, returning `items` and `truncated`. Reads are bounded to recent 1 MiB/1,000 numeric rows; invalid/incomplete/nonfinite values are skipped. CSV needs a header and newline-terminated rows. Missing metrics yield an empty result.

Artifacts include `path`, `size` in bytes, and `download_url`; follow that URL directly, without constructing/escaping it yourself. The scan is capped at 2,000 entries and reports `truncated` when capped. Output-directory links and paths escaping the output directory are rejected. External run directories/processes are not automatically imported. See README.md for the generic output and environment contract.

## Errors

```json
{
  "error": {
    "code": "validation_error",
    "message": "The request does not match the API schema.",
    "details": [{"field":"/body/project_id", "message":"Field required", "type":"missing"}]
  }
}
```

Field locations are JSON-pointer-style strings rooted at `body`, `query` or `path`. Error `code` is the machine-readable discriminator; `message` explains the remedy. 404 means missing resource, 409 a lifecycle/workspace conflict, 422 invalid fields/options, and 503 failed supervisor launch. Unexpected failures use a generic 500 and server-side logging. Error details never echo supplied request values.

Bodies are capped at 128 KiB with a 15-second receive timeout. Responses disable caching and content sniffing. This is a local application without account authentication; foreign Origin/unexpected Host requests return 403. Health `application: "hentai-studio"` identifies the backend; degraded health reports broken workspace records. Those records must be repaired before launches/registration changes, while valid history and identifiable stop operations remain available.

## Migrating from 0.5

- Replace full-body PUT with PATCH, omitting the body ID.
- Replace POST `/api/projects/{id}/jobs` with POST `/api/jobs` and a `project_id` field.
- Replace start requests containing `resume_from` with POST `/api/jobs/{source_id}/resume`.
- Read `project_name` instead of `job.project.name`. Job process IDs/full snapshots are private persistence data.
- Follow `next_cursor` on project/job lists; do not assume a single response contains everything.
- Replace `tail=true` with a tail byte count such as `tail=65536`.

The dashboard and bundled client use this same contract. Removed endpoints are not compatibility aliases.

## Scratch LLM projects and local chat

Project definitions can include an `llm` profile that generates their scratch `train` command. Local checkpoint chat has dedicated status, load, unload, and completion routes. See [the LLM guide](LLM.md#api-and-python-client) for the full schema and client examples. Existing generic projects need no changes.
