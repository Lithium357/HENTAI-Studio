# Development

Python 3.11+; Node 20+ for frontend checks. Install the project with `python -m pip install -e '.[dev]'`. No engine checkout is needed.

```sh
pytest tests/test_web.py tests/test_jobs.py tests/test_package_boundary.py tests/test_server_restart.py
npm install
npm test
npm run test:browser
```

The standalone tests use real external Python commands, temporary project directories and workspaces. They cover registration and validation, output contracts, logs/metrics, process ownership, stop, resume, snapshots, dashboard restart, workspace exclusion, failure codes, PID reuse and API transport. Import-boundary tests reject any attempted training framework or engine import.

Browser acceptance launches an empty server and registers the standard-library demo trainer through the UI. It verifies real training output, selectable metrics, artifact downloads, resume, stop, reload and mobile layout. Set PYTHON to the desired interpreter. Optional PLAYWRIGHT_MODULE and STUDIO_BROWSER_CHANNEL allow a configured Playwright installation/browser. STUDIO_TEST_TMP chooses the temporary parent directory.

The remaining `test_llm_*` suite exercises optional utilities and requires `pip install -e '.[dev,llm]'`. Run `pytest` for the complete suite in that environment. Default installation and application startup do not require those packages.

For release verification, build a wheel, install it in a fresh environment with neither scratchtag nor torch, start the server, and execute the demo as an external command. Clean stale build output before wheel builds after deleting modules. The optional Windows shell can be checked with `dotnet build windows/HENTAIStudio/HENTAIStudio.csproj --configuration Release`.
