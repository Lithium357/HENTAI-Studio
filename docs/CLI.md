# Studio CLI

Run `hentai-studio --help` or `hentai-studio COMMAND --help` for the complete argument list.

```bash
hentai-studio dashboard --project /path/to/HENTAI --config configs/local-v3.json \
  --storage-root /mnt/d/HENTAI-Data --host 127.0.0.1 --port 7860
```

`--project` is required for `dashboard` and `studio`; relative diffusion configs resolve there. The API-only server defaults to port 7861. LLM commands use config paths relative to the shell's current directory. `llm-normalize-erp --source DIR --output DIR [--limit-files N]` converts a local CSV archive into cleaned JSONL without training. `llm-tokenizer --config FILE --output DIR` trains a run-local BPE tokenizer from configured text.

## Causal LLM workflow

```bash
.venv/bin/hentai-studio llm-validate --config configs/local-llm.json
.venv/bin/hentai-studio llm-audit --config configs/local-llm.json
.venv/bin/hentai-studio llm-smoke --config configs/local-llm.json --tiny
.venv/bin/hentai-studio llm-build-packed-cache --config configs/local-llm.json
.venv/bin/hentai-studio llm-prepare --config configs/local-llm.json --run-id local-llm
.venv/bin/hentai-studio llm-train --config configs/local-llm.json --device cuda
```

`llm-build-packed-cache` reads and tokenizes configured text but never opens image/GIF media and never uses the GPU. It defaults to `dataset.packed_cache`; `--output DIR` overrides that destination and `--overwrite` is required to replace an incompatible cache.

`llm-train` implements `scratch` and `lora`. LoRA requires a local base model plus a verified packed cache. `--no-resume` intentionally ignores complete resume checkpoints; do not use it against an established run unless a fresh start is intended.

```bash
.venv/bin/hentai-studio llm-checkpoint-verify \
  --run-dir /path/to/run --step 500

.venv/bin/hentai-studio studio --project /path/to/HENTAI \
  --storage-root /mnt/d/HENTAI-Data \
  --host 127.0.0.1 --port 7861
```
