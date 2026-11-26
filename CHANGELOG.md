# Changelog

## 0.9.2 — 2026-11-25

- Defined Studio's acronym as **Hub for Experiments, Neural Training, Analysis & Inference**, independently of the original HENTAI model.
- Updated the native connection screen and About dialog, browser branding/accessibility metadata, CLI help, API description, package/executable metadata, installer shortcut descriptions, documentation, and repository banner.
- Adopted the tagline **Your models. Your hardware. One workspace.**

## 0.9.1 — 2026-11-23

- Added an explicit **Sampling** selector to the native and browser model testers: CPU by default, or GPU through CUDA/ROCm.
- Added opt-in shared GPU sampling through **Allow GPU sampling alongside training**. Shared test models allow existing training to continue and do not block new training admission. GPU memory and compute are shared with the trainer.
- Added `allow_training_overlap` to manual and latest-checkpoint load requests, chat status responses, and Python client helpers. Its default is false, retaining reserved-GPU behavior unless sharing is requested.
- Added loaded-model status that distinguishes CPU, reserved GPU, and shared GPU sampling.
- Covered training preservation, overlap policy, and native/browser sampling controls with tests.

## 0.9.0 — 2026-11-23

- Reorganized the native app into **Runs**, **Test model**, and **Hardware**. Runs has separate **Metrics**, **Console**, and **Output files** inspection tabs.
- Added `GET /api/projects/{id}/chat/checkpoints/latest` for discovery and `POST /api/projects/{id}/chat/load-latest` for discovery plus loading. Added equivalent Python client helpers.
- Added one-click latest-checkpoint loading and opt-in automatic loading when entering the tester. Moved manual paths and generation settings under Advanced options.
- Discovery searches runs in creation order, prefers a successful run's final model, and otherwise selects its highest complete numeric checkpoint. It checks supported weight files/shards, skips incomplete saves, confines paths to the run output, and checks completion state for active runs.
- Reuses an already-loaded checkpoint and permits replacement of the selected project's idle inference worker. Different weights clear the UI conversation.
- Improved large-history refresh performance by filtering absent process IDs before checking recorded identities. Existing IDs still require PID/creation-time verification.
- Verified the full scratch-train → save → discover latest → load → generate workflow with a tiny offline CPU model.

## 0.8 — native desktop and hardware monitoring

- Replaced the embedded WebView2 Windows shell with a native .NET 8 Windows Forms client. The browser dashboard remains an independent optional client.
- Retained the port picker, independent multi-window connections, Local/Cloud titles, DPI support, and compact layouts.
- Added background backend-host monitoring through `GET /api/hardware`, a native Hardware view, and a browser hardware disclosure.
- Added NVIDIA SMI, Windows vendor-neutral DXGI/WDDM counters, AMD/Linux DRM/sysfs sensors, and Intel XPU-SMI support with OS fallbacks. GPU rows remain separate; unavailable values, provider errors, and sample freshness are explicit.
- Kept live hardware readings separate from historical trainer metrics and kept helper execution out of request handlers.

## Earlier versions

Studio 0.7 introduced optional scratch LLM profiles and local checkpoint chat. Earlier standalone releases separated the project/job manager from historical HENTAI/Lucy training workloads and introduced the resource-oriented API and standard-library Python client. See [Migration](docs/MIGRATION.md) for workspace and older API guidance.

## Updating

Update the Windows executable and each backend you connect to. Restart only the Studio API server to activate new routes, keeping the same workspace and independent training supervisors. Installing an updated client alone does not update an AWS/WSL/remote backend. See [Windows installation](docs/WINDOWS.md), [hardware support](docs/HARDWARE.md), and [scratch-model testing](docs/LLM.md).
