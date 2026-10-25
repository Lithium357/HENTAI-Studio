# Migrating to standalone Studio 0.4

This release intentionally replaces the model-specific API and CLI without compatibility aliases.

1. Install Studio alone. Remove any requirement to install a sibling HENTAI checkout. The default install needs only web/runtime dependencies; ML packages remain optional.
2. Launch `hentai-studio serve --workspace PATH`. Replace old dashboard/studio commands and engine/config/storage flags.
3. Register each trainer's directory and argument arrays through the UI or POST /api/projects. Point commands at the trainer's own interpreter. HENTAI is one possible external project, not a special workload type.
4. Route trainer output to {output_dir} or STUDIO_OUTPUT_DIR. If necessary, write a wrapper in the training project that reads its config, chooses output/checkpoint paths and emits generic numeric metrics. Studio does not modify HENTAI's config format or training implementation.
5. Replace /api/runs and /api/diffusion calls with /api/projects and /api/jobs. Use /api/docs for the current schema.
6. Replace HENTAI_WSL_PROJECT, HENTAI_CONFIG and launcher-specific engine variables with STUDIO_EXECUTABLE and optionally STUDIO_WORKSPACE for the Windows shell. Linux/WSL projects should be served by Studio running in that environment.

Old runs/checkpoints remain untouched. They are not imported or adopted automatically. Legacy diffusion sampling, VAE promotion, fixed watchdog scripts, LLM chat and workload-specific dashboard adapters are removed from the generic API. Invoke training, evaluation, generation or export tools as project commands instead. Existing optional LLM CLI utilities still work independently.

HENTAI's model package has no Studio dependency. No HENTAI source changes are needed to install or launch Studio. The two repositories can be installed, tested and released separately.
