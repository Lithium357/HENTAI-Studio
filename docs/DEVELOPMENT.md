# Development

Python 3.11+ and Node 20+. Install with `python -m pip install -e '.[dev]'`. No engine checkout or ML dependencies are required, including for the full test suite.

```sh
pytest
npm test
```

Python tests use temporary workspaces and real external Python trainers. Coverage includes admission, command execution, snapshots, stop/resume, owned trees, an actual server restart, dead-supervisor recovery, PID reuse, corrupt metadata, case-insensitive IDs, Windows sharing retries, output confinement, CSV/JSONL parsing, API validation and same-origin transport. Import hooks enforce both the model-independent application boundary and the web-independent job layer.

JavaScript tests exercise polling/cancellation, resource transport, generic metric geometry and pure UI state. They verify per-project command selections, orphan eligibility, stale-view controls, workspace issues and retained history.

## Browser acceptance

```sh
npm install
npx playwright install chromium
npm run test:browser
```

The browser test launches an empty server and registers the standard-library demo trainer. It checks training, metrics, downloads, resume, stop, reload, mobile layout, persistent mutation errors, output-panel failure isolation and history after unregistration. PYTHON selects the interpreter; PLAYWRIGHT_MODULE/STUDIO_BROWSER_CHANNEL allow a configured Playwright/browser installation; STUDIO_TEST_TMP selects temporary storage. STUDIO_SCREENSHOT optionally captures the UI.

## Packaging and desktop

Build a wheel and install it in a fresh environment. Run the entire Python and browser suites against that installed package without scratchtag, Lucy, Torch, Transformers, Diffusers or any training library. Check the wheel contains no historical workloads/core trainer tree, bundled project profiles, or compiled probe. ML requirements must be restricted to the optional llm extra; its standalone runner modules must be present. Clean stale build output after removing modules; package discovery excludes implicit namespaces and only declared browser assets are shipped.

`dotnet build windows/HENTAIStudio/HENTAIStudio.csproj --configuration Release` validates the native Windows client. Native runtime/UI launch is separate from compilation. build.ps1 publishes only unless -Install is explicitly supplied; installation creates a private backend venv and shortcuts without deleting workspace data.

GitHub Actions runs the standalone Python/JavaScript suites on Windows and Linux with Python 3.11 and 3.12. The native client checks also run on Windows CI; browser acceptance remains a separate step.

The API contract suite verifies registration defaults, atomic partial edits, public job redaction, links/actions, cursor scope/stability, idempotent stop, output URLs and stable OpenAPI operations. The Python client suite talks to a real local Uvicorn server and external trainer, covering the full register/start/wait/read/resume/download/error workflow. These tests run with the ordinary dev dependencies; the client itself needs only the standard library.

## Documentation screenshots

After the browser dependencies above are installed, run `npm run docs:screenshots`. The capture uses the real dashboard with deterministic illustrative API responses and a temporary static server on a free loopback port. It never connects to a Studio service, starts a trainer, or accesses a real workspace. The resulting Overview, Console, Files, registration, resume-definition, and compact desktop previews live in `docs/assets/`. The browser/module environment overrides described above also apply.

## Optional LLM checks

`npm run test:llm-browser` exercises the scratch profile form, explicit checkpoint loading, chat history, failure handling, project isolation, and mobile layout against a temporary server with a fake inference worker. It never loads a model or uses the GPU.

With the optional LLM dependencies installed, run `STUDIO_TEST_LLM=1 python -m pytest tests/test_llm_runtime.py` (set `$env:STUDIO_TEST_LLM = '1'` first in PowerShell). This test creates a tiny tokenizer and architecture locally, trains random weights on CPU, resumes a saved checkpoint, and generates text through the real inference worker. Set `CUDA_VISIBLE_DEVICES` to an empty value to keep the test explicitly CPU-only. No network access or model download is needed.

## Dense job-history layout

Run `npm run test:history` after installing Playwright. The check serves the real dashboard with 11 demo jobs and long project names, then verifies card containment, non-overlap, filtering, selection, and scrolling at desktop, short-window, split-screen, and phone sizes. It uses no training workspace or live service. `STUDIO_SCREENSHOT` optionally captures the repaired history panel.

## Native Windows acceptance

Hardware provider tests cover NVIDIA/Intel CSV parsing, AMD/Intel sysfs units, Windows adapter-LUID joins, per-engine utilization, missing sensors, cache freshness, and nonblocking reads. Native checks render the hardware table with all three vendors using the real Windows application message loop. `tests/browser/native_check.py` serializes fixture request logging across threads and times out hung clients.

```powershell
dotnet build windows/HENTAIStudio.Tests/HENTAIStudio.Tests.csproj --configuration Release
python tests/browser/native_check.py windows/HENTAIStudio.Tests/bin/Release/net8.0-windows/HENTAIStudio.Tests.exe
```

The runner starts an isolated API fixture and closes only that fixture afterward. Checks cover native control types, actual form resizing and non-overlapping history rows, pagination, metric step resets, artifact downloads, connection errors, cancellation, project edits, start/stop/resume requests, and native checkpoint load/chat/unload controls. The fixture never starts training or loads model weights. The request log verifies that the client requests only JSON API routes, with no browser assets. No extra .NET test packages are required.
