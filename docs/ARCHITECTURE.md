# Studio dashboard architecture

HENTAI is the diffusion engine. HENTAI Studio is the dashboard application that observes runs and requests explicit actions through the engine's installed tools and watchdog scripts.

```mermaid
flowchart TD
  Browser[ES module frontend] --> Web[FastAPI routers and typed schemas]
  Desktop[Windows WebView2 shell] --> Browser
  Web --> Studio[RunService: run registry and chat]
  Web --> Dashboard[DashboardState: diffusion facade]
  Dashboard --> Progress[ProgressReader]
  Dashboard --> Catalog[CheckpointCatalog]
  Dashboard --> Sampling[SamplingJobs]
  Dashboard --> Controls[TrainingControls]
  Dashboard --> Telemetry[Telemetry / TrainerProcesses]
  Sampling --> Engine[HENTAI engine]
  Controls --> Engine
  Studio --> Workloads[Diffusion adapter / causal-LM adapter]
```

## Python boundaries

`dashboard.py` and `studio.py` retain their public CLI entry points. `dashboard_app/state.py` composes the diffusion services and produces the existing status response. Each service owns its own state: sampling owns the subprocess and lock; telemetry owns its cache, timing, and energy accumulation. Training actions are serialized per dashboard instance.

`dashboard_app/processes.py` identifies trainers by the selected config or run directory and watchdogs by engine project and config. Stop signals only selected trainers and their worker descendants. Studio does not signal an entire shell process group. Resume passes the selected project/config to portable watchdogs; legacy fixed-path watchdogs are accepted only when their project, reference profile, and run match the selection. An incompatible script leaves training paused and returns an actionable error.

`api/app.py` constructs the FastAPI application and mounts its resource routers. `api/schemas.py` defines the request/response contracts; `api/routes/` groups system, run, and configured-diffusion endpoints. `api/services/` implements operations and maps expected domain failures to explicit errors. Dependencies are supplied through `api/dependencies.py`. `api/errors.py` owns the shared error format. The small ASGI middleware handles only body limits and response headers; Uvicorn handles HTTP framing. There is no custom path dispatcher or generic action payload.

Both server modes expose the same schema at `/api/openapi.json` and documentation at `/api/docs`. The API uses snake_case fields, collection `items`, workload-qualified run IDs, explicit training commands, and a retained sampling-job result. Status, checkpoint catalogs, and galleries are separate resources. Old routes are removed. See [API reference](API.md).

Model libraries remain lazy imports. Serving metadata, assets, progress, and run lists does not import Torch, Transformers, Diffusers, or PEFT.

## Browser boundaries

The browser loads standard ES modules directly, without a bundler or frontend runtime dependency:

| Module | Responsibility |
|---|---|
| `app.js` | Workspace selection, page lifecycle, and refresh scheduling |
| `diffusion.js` | Diffusion progress, sampling selection, and training actions |
| `llm.js` | LLM selection, progress, checkpoint chat, and conversation state |
| `api.js` | JSON requests, errors, cancellation, and bounded timeouts |
| `poller.js` | Refresh scheduling that waits for the previous request |
| `charts.js` | Shared training/validation geometry and SVG rendering |
| `dom.js`, `format.js` | Text escaping, connection state, notifications, and formatting |

Each workspace owns its state and cancels superseded status requests. The application suspends polling while the page is hidden. Run selection cancels the previous chat request and increments a selection version, so a late reply cannot enter another run's conversation. Status polling cannot enable duplicate chat submission while a reply is pending. Metadata is escaped before template rendering, and chat text is inserted as text.

Charts position points using actual optimizer steps. Invalid points are omitted and sparse validation measurements share the training loss scale. The layout and existing training/sample workflows remain familiar; the header describes Studio as the application, rather than expanding the diffusion model's name as the app's definition.

## Verification

Python tests cover service behavior, existing LLM lifecycle, checkpoint confinement, selected-run process discovery, resume arguments, typed resource routes, request validation, error semantics, and static modules. Node tests exercise chart geometry, request cancellation/error handling, escaping, and polling. The browser fixture exercises the real module graph and HTTP server with synthetic data, including sampling submission, chat pending state, run-switch races, reconnect, and mobile overflow. It never loads production models or signals real trainers.
