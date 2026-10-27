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

Build a wheel and install it in a fresh environment. Run the entire Python and browser suites against that installed package without scratchtag, Lucy, Torch, Transformers, Diffusers or any training library. Check the wheel contains no workloads/core trainer tree, profiles, compiled probe, or ML requirements. Clean stale build output after removing modules; package discovery excludes implicit namespaces and only declared browser assets are shipped.

`dotnet build windows/HENTAIStudio/HENTAIStudio.csproj --configuration Release` validates the optional shell. Native runtime/UI launch is separate from compilation. build.ps1 publishes only unless -Install is explicitly supplied; installation creates a private backend venv and shortcuts without deleting workspace data.

GitHub Actions runs the standalone Python/JavaScript suites on Windows and Linux with Python 3.11 and 3.12. Browser and native runtime checks remain separate acceptance steps.

The API contract suite verifies registration defaults, atomic partial edits, public job redaction, links/actions, cursor scope/stability, idempotent stop, output URLs and stable OpenAPI operations. The Python client suite talks to a real local Uvicorn server and external trainer, covering the full register/start/wait/read/resume/download/error workflow. These tests run with the ordinary dev dependencies; the client itself needs only the standard library.
