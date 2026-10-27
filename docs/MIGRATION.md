# Migrating to Studio 0.5

Studio now owns only local project/job management. HENTAI and Lucy are external training projects; Studio does not contain their model/data implementations or require either repository.

## Removed project code

The former bundled `workloads/llm`, LLM-only core helpers, `llm-*` commands, `[llm]` extra, ERP/Qwen profiles, dataset/token-estimation scripts and ROCm experiment notes have been removed from the active application. Their last complete revision is [67fa438](https://github.com/Lithium357/HENTAI-Studio/tree/67fa43832d6d8e15d388548e93848a5164c723e9). Git history preserves the source and licensing; no dataset, model or run directory is deleted by this change.

If an existing workflow invokes those commands, keep its historical environment while moving the needed implementation into the training project's own maintained tooling. Studio no longer provides those training entry points. Register the external executable/arguments in the dashboard instead. The public Lucy repository is referenced for project context; this cleanup does not copy private Studio implementations into it or modify it.

## Existing workspaces

Project definitions and job history from Studio 0.4 remain readable. No bulk conversion is required. New jobs record trainer/descendant process identities so Studio can safely stop survivors after a supervisor crash. Older jobs lack that evidence; interrupted old trainers need manual inspection rather than process-name matching.

Project IDs are unique ignoring case. If an old Linux workspace contains IDs differing only by case, repair those registrations before starting new jobs. Broken/ambiguous metadata is reported through health issues and the dashboard. Restore damaged records from backups or move them out of the workspace while the server is stopped; valid history remains readable and stop remains available for identifiable jobs.

The All jobs view shows history after unregistration. Re-register the original ID if you want the project's historical jobs under a project filter again.

The desktop shell now defaults to `~/.hentai-studio`, matching the CLI. If you previously used its LocalAppData workspace, set STUDIO_WORKSPACE to that existing directory, or start the CLI with --workspace pointing there. The shell validates backend identity, so an unrelated process on port 7860 is reported instead of displayed as Studio. STUDIO_URL can select a different local port.

## Older model-specific API

The earlier `/api/runs`, `/api/diffusion`, and dashboard/studio CLI modes remain removed. Use `/api/projects` and `/api/jobs`, with explicit project-owned commands, output arguments and resume behavior. Studio never rewrites trainer configs, guesses watchdogs or imports checkpoint formats. See API.md and the demo trainer for the generic contract.
