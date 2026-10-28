# Source provenance

Studio source, assets, Windows launcher, telemetry code, LLM workloads, tests, profiles, and related documentation were extracted from `Lithium357/HENTAI` at commit `b525af1` during the 0.2 repository split. Import namespaces and entry points changed; model/checkpoint formats were preserved.

HENTAI Studio, including the retained first-party material extracted from HENTAI, is licensed under the [GNU General Public License v3.0](LICENSE). At the repository owner’s direction, GPLv3 is now the sole project license and the separate proprietary license has been removed. Earlier revisions retain their historical notices in Git.

Vendored ADLX and Rust bindings retain their third-party licenses under `vendor/ADLX/`; these notices are separate from Studio’s project license.

## Standalone cleanup (0.5)

The active Studio package no longer includes the extracted training workloads, LLM-only helpers, ERP/Qwen profiles, experiment notes or training CLI commands. Their final bundled revision is 67fa43832d6d8e15d388548e93848a5164c723e9 and remains in Git history. The native ADLX utility source/vendor licenses remain outside the Python package; no probe executable or GPU/ML dependency is required or installed by Studio.
