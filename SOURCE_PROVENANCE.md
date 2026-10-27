# Source provenance

Studio source, assets, Windows launcher, telemetry code, LLM workloads, tests, profiles, and related documentation were extracted from `Lithium357/HENTAI` at commit `b525af1` during the 0.2 repository split. Import namespaces and entry points changed; model/checkpoint formats were preserved.

The extracted HENTAI material retains its original proprietary source terms in [LICENSE.HENTAI](LICENSE.HENTAI). The pre-existing Studio repository license is retained in [LICENSE](LICENSE). This extraction does not relicense upstream material. Vendored ADLX and Rust bindings retain their licenses under `vendor/ADLX/`.

## Standalone cleanup (0.5)

The active Studio package no longer includes the extracted training workloads, LLM-only helpers, ERP/Qwen profiles, experiment notes or training CLI commands. Their final bundled revision is 67fa43832d6d8e15d388548e93848a5164c723e9 and remains in Git history. Application refactoring does not change the retained source licenses. The native ADLX utility source/vendor licenses remain outside the Python package; no probe executable or GPU/ML dependency is required or installed by Studio.
