# Historical checkpoint browser

Status: completed 2026-09-30.

## Purpose

Allow HENTAI Studio to generate from an explicitly selected historical diffusion checkpoint without interrupting active GPU training.

## Implemented contract

- `GET /api/diffusion/checkpoints` returns compatible historical runs and diffusion checkpoints.
- The generation panel provides run and checkpoint selectors.
- `POST /api/diffusion/samples` with `source: "checkpoint"` accepts a catalog run ID and checkpoint ID.
- Backend selection is confined to the project `runs/` directory; arbitrary paths and traversal are rejected.
- Current-run VAE reconstruction behavior remains available while the current stage is VAE.
- Historical diffusion generation runs on CPU so active GPU training is not disturbed.
- The exact selected checkpoint is used rather than silently substituting the newest checkpoint.

## Completion evidence

- Initial live catalog exposed `main-256` checkpoints at steps 114,000, 112,000, and 110,000.
- Historical generation remained available during a different active VAE run.
- Tests cover complete-checkpoint filtering, traversal rejection, and exact checkpoint command wiring.
- The native Windows shell required no special browser feature beyond the embedded dashboard UI.

This record is retained as a design note; operator behavior is documented in [HENTAI Studio](../DASHBOARD.md#historical-checkpoint-lab).
