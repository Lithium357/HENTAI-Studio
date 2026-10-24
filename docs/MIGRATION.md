# Repository split (0.2)

| Responsibility | Repository / package |
|---|---|
| Image manifests, vocabulary, models, VAE/diffuser training, image inference | HENTAI / `scratchtag` |
| Diffusion configs, watchdogs, architecture and model probes | HENTAI |
| Installed CPU checkpoint samplers | HENTAI / `scratchtag.tools` |
| Dashboard HTTP server, static UI, run registry, process control | HENTAI-Studio / `hentai_studio` |
| Workload adapters, LLM training, caches, tokenizer, inference | HENTAI-Studio / `hentai_studio.workloads` |
| Windows launcher, telemetry helper, ADLX vendor tree | HENTAI-Studio |

The dependency points from Studio to `scratchtag-diffusion>=0.2,<0.3`. There is no Studio dependency in HENTAI. The Python namespaces are distinct; neither distribution installs files inside the other's namespace. Diffusion configs and checkpoint formats are unchanged.

## Existing installation

1. Keep diffusion datasets, configs, vocabularies, runs, logs, and the engine `.venv` where they are. No run data needs to be moved or converted.
2. Clone Studio alongside HENTAI and install both local packages into Studio's environment: `python -m pip install -e ../HENTAI -e '.[dev]'`. Install the appropriate Torch runtime for sampling. Add Studio's `[llm]` extra for LLM execution.
3. Replace `scratchtag dashboard --config FILE` with `hentai-studio dashboard --project /absolute/path/to/HENTAI --config FILE`.
4. Replace `scratchtag studio ...` with `hentai-studio studio --project /absolute/path/to/HENTAI ...`.
5. Replace `scratchtag llm-*` with `hentai-studio llm-*`; imports move from `scratchtag.workloads.llm` to `hentai_studio.workloads.llm`. LLM reference profiles now live in Studio's `configs/`. Update config paths in any external launch scripts.
6. Existing LLM storage roots, `run.json`, copied configs, packed caches, and checkpoints remain valid. Keep their configured absolute paths. Relative LLM paths retain their current-working-directory semantics.
7. Rebuild the Windows launcher from Studio. Set `HENTAI_STUDIO_WSL_PROJECT` to Studio and retain `HENTAI_WSL_PROJECT` for the engine. Studio's `.venv/bin/hentai-studio` launches the dashboard; HENTAI's `.venv/bin/scratchtag` still executes diffusion watchdog stages.
8. To use a custom rebuilt GPU probe, set `HENTAI_HARDWARE_PROBE` in the dashboard's environment. The installed Studio package otherwise supplies its bundled executable.

The legacy `scratchtag dashboard`, `scratchtag studio`, and `scratchtag llm-*` commands are removed. Install both split revisions before switching launchers. Existing running processes keep their loaded code; schedule upgrades between runs to avoid mixing old and new environments.

## Backend interface

Studio's diffusion adapter validates configs through `scratchtag.config.load_config` and reads the existing run/checkpoint files. Sampling uses `python -m scratchtag.tools.vae_snapshot`, `python -m scratchtag.tools.diffusion_checkpoint_sample`, or `python -m scratchtag.tools.sdxl_checkpoint_sample` with the Studio interpreter. Resume uses the engine's watchdog scripts. Static assets and the hardware executable resolve from the installed Studio package, never the engine checkout.

The original `scripts/*checkpoint_sample.py` and `scripts/vae_snapshot.py` paths remain compatibility wrappers in HENTAI. They delegate to the installed engine modules.
