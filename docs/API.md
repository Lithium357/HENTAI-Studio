# Studio API (0.3)

The API lives under `/api`. Run the dashboard on port 7860, then open `/api/docs` for interactive endpoint documentation or `/api/openapi.json` for the generated schema. API-only mode normally uses port 7861. Both modes expose the same schema; diffusion operations return `503 diffusion_not_configured` when no diffusion config was supplied at startup.

The previous `/api/v1`, `/api/status`, `/api/action`, and top-level download URLs are removed. Studio's browser client uses this API directly.

## Conventions

- JSON fields use `snake_case`. Byte counts end in `_bytes`; timestamps are Unix seconds. Resolutions use pixels.
- Collections return `{"items": [...]}`. A resource response is the resource itself, without another success envelope.
- Run IDs include their workload: `diffusion:main-run` or `llm.causal:my-run`. Encode IDs when placing them in a URL. Identically named diffusion and LLM runs are distinct resources.
- Checkpoint IDs are opaque strings. Use values returned by the checkpoint endpoints rather than constructing filesystem paths.
- Requests reject unknown fields, invalid types, and out-of-range values. JSON bodies are limited to 128 KiB, including streamed bodies.
- The server is local and unauthenticated. Training controls execute only against the configured diffusion project.

## Resources

| Method | Path | Result |
|---|---|---|
| GET | `/api/health` | Service version and whether diffusion is configured; no model loading |
| GET | `/api/storage` | Configured storage root, free bytes, and total bytes |
| GET | `/api/runs` | Registered runs; optionally filter with `?workload=diffusion` or `?workload=llm.causal` |
| GET | `/api/runs/{run_id}` | Run state, progress, telemetry, loss history, and capabilities |
| GET | `/api/runs/{run_id}/checkpoints` | Complete and incomplete checkpoints |
| POST | `/api/runs/{run_id}/chat/completions` | One CPU chat completion from the latest completed LoRA weights checkpoint |
| GET | `/api/diffusion/status` | Configured trainer state, progress, current checkpoints, telemetry, and sampling status |
| GET | `/api/diffusion/checkpoints` | Historical diffusion runs grouped with sampleable checkpoints |
| GET | `/api/diffusion/samples` | Newest generated images and their download URLs |
| POST | `/api/diffusion/samples` | Start a CPU sample; returns `202` and its sampling status |
| GET | `/api/diffusion/sampling` | Current or last sampling job, including its exit result |
| GET | `/api/diffusion/samples/{name}` | Download an image using the exact gallery filename |
| POST | `/api/diffusion/training/pause` | Request a pause and signal only this run's trainers and workers |
| POST | `/api/diffusion/training/resume` | Request watchdog startup or resume an existing paused watchdog |
| POST | `/api/diffusion/training/promote-vae` | Promote a safe VAE checkpoint and request diffuser startup |
| GET | `/api/diffusion/progress/{stage}.csv` | Download a progress log; stage is `vae` or `diffusion` |

`/api/runs` is a read-oriented registry spanning diffusion and LLM runs. `/api/diffusion` operates the one diffusion project/config selected at startup. It does not silently change the active trainer to a run selected in the registry or checkpoint catalog.

## Observe runs

```bash
curl 'http://127.0.0.1:7860/api/runs?workload=llm.causal'
curl 'http://127.0.0.1:7860/api/runs/llm.causal%3Amy-run'
curl 'http://127.0.0.1:7860/api/diffusion/status'
```

A run detail includes `capabilities.chat`. It is true only when local LoRA checkpoint chat can be attempted. A scratch-model checkpoint does not imply LoRA chat support. Clients should check the capability instead of guessing from checkpoint filenames.

The diffusion status response omits the historical catalog and gallery; fetch their collection endpoints separately. This keeps routine trainer status distinct from browsing saved artifacts.

## Training commands

```bash
curl -X POST http://127.0.0.1:7860/api/diffusion/training/pause
curl -X POST http://127.0.0.1:7860/api/diffusion/training/resume
```

These endpoints take no request body and return an acknowledgement such as:

```json
{"command":"resume","status":"requested"}
```

`202` acknowledges the request; it does not assert that a trainer has already reached a running state. Observe `/api/diffusion/status` afterward. VAE promotion uses the explicit `/training/promote-vae` endpoint and retains the existing irreversible stage-transition semantics. An incompatible fixed-path watchdog returns a conflict instead of launching a different run.

## Create a sample

```bash
curl -X POST http://127.0.0.1:7860/api/diffusion/samples \
  -H 'Content-Type: application/json' \
  -d '{"source":"current","tags":["portrait","blue_hair"],"seed":357,"steps":20,"guidance":5}'
```

For a historical checkpoint, choose the IDs returned by `/api/diffusion/checkpoints`:

```json
{
  "source": "checkpoint",
  "run_id": "diffusion:previous-run",
  "checkpoint_id": "step-110000",
  "tags": ["portrait"],
  "seed": 357,
  "steps": 20,
  "guidance": 5
}
```

`source` defaults to `current`. `checkpoint` requires both IDs; `current` rejects historical selection fields. Tags are an array, steps are 5–60, guidance is 1–12, and the seed is an integer from 0 through 2^63−1. Current sampling requires a saved checkpoint. VAE reconstruction selects a random record and seed as before.

The accepted response includes `Location: /api/diffusion/sampling`. Poll that resource for `idle`, `running`, `succeeded`, or `failed`. Completion retains `started_at`, `finished_at`, and `exit_code`; a failed worker is not reported as merely idle. Only one sample job runs at a time. Fetch the gallery after a successful job; download URLs are provided by the server.

## CPU chat

```bash
curl -X POST 'http://127.0.0.1:7860/api/runs/llm.causal%3Amy-run/chat/completions' \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Hello"}],"max_new_tokens":128}'
```

History contains 1–48 messages with `system`, `user`, or `assistant` roles and nonempty text. `max_new_tokens` is 1–256. A response identifies the selected checkpoint and execution device:

```json
{
  "message": {"role":"assistant","content":"Hello."},
  "checkpoint_id": "weights/step-500",
  "device": "cpu"
}
```

Model loading, reply generation, and conditional unloading are serialized so another request cannot unload an in-use model. The endpoint is synchronous; clients should allow time for CPU inference.

## Errors

Every application error has the same shape:

```json
{
  "error": {
    "code": "validation_error",
    "message": "The request does not match the API schema.",
    "details": [{"field":["body","steps"],"message":"Input should be less than or equal to 60","type":"less_than_equal"}]
  }
}
```

| Status | Meaning |
|---|---|
| 400 | Invalid HTTP body framing or an unreadable body |
| 404 | Resource or route not found |
| 405 | Method not supported for the resource |
| 408 | Body reception timed out |
| 409 | Valid request conflicts with run/checkpoint/training state |
| 413 | Body exceeds the size limit |
| 422 | Invalid JSON shape, field, type, or range |
| 500 | Unexpected server fault; details are logged rather than returned |
| 503 | A required configuration, storage root, engine, or model backend is unavailable |

Malformed HTTP that the server rejects before it reaches the application may use the HTTP server's own error response. The generated OpenAPI schema is the authoritative field-level contract.
