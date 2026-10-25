# Studio development

`src/hentai_studio/dashboard.py` is the dashboard entry point; `dashboard_app/` contains its composed services. `studio.py` owns the workload API service and `web/` shares HTTP routing between dashboard and API-only modes. `core/` owns run identity, storage, and checkpoint utilities; `workloads/` contains the diffusion adapter and causal-LM backend. Browser ES modules are in `dashboard_static/` and the packaged hardware helper is in `bin/`. Native sources are in `windows/`, `hardware_probe/`, and `vendor/ADLX/`. See [architecture](ARCHITECTURE.md).

Install both local projects into a test environment with `python -m pip install -e ../HENTAI -e '.[dev,llm]'`, then run `python -m pytest -q` and `git diff --check`. Tests use temporary fixtures and synthetic models; they do not access production datasets, model weights, or GPU training runs.

Frontend logic tests require Node.js and no installed npm packages:

```bash
npm test
```

For the browser integration fixture:

```bash
npm install
npx playwright install chromium
PYTHON=/path/to/venv/bin/python npm run test:browser
```

`PYTHON` must point to the environment with Studio installed. `STUDIO_BROWSER_CHANNEL=msedge` uses an installed Edge browser instead of downloaded Chromium. `STUDIO_TEST_TMP` optionally selects a writable temporary directory. The fixture starts its own server on a free loopback port and closes it afterward.

Dashboard/API startup must remain free of Torch, Diffusers, Transformers, and PEFT imports. Diffusion integration belongs in the adapter or subprocess calls to installed engine modules. Keep `--project` explicit: the working directory must not silently select a different engine project. Preserve run/config/checkpoint formats and validate historical selections against the run catalog.

Build the Windows shell with `dotnet build windows/HENTAIStudio/HENTAIStudio.csproj --configuration Release`. `build.ps1` also installs the app and creates shortcuts. The shell requires the .NET Windows Desktop runtime and WebView2. See the README for launcher environment variables and hardware-helper rebuild steps.

To verify packaging, build both wheels with `python -m pip wheel --no-deps ../HENTAI . --wheel-dir dist`, install them together in a clean environment, and launch from outside either checkout. Confirm Studio owns its static assets and telemetry binary, and HENTAI owns the sampling modules. See [migration](MIGRATION.md).
