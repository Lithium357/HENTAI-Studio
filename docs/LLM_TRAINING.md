# LLM training

HENTAI Studio supports two local-only paths: `mode: scratch`, a small decoder-only fixture model with a run-local BPE tokenizer, and `mode: lora`, continued pretraining of a locally stored causal base model through a LoRA adapter. The ERP Qwen3 4B run uses the LoRA path. Neither path downloads model weights at runtime.

Install the project only after the correct ROCm PyTorch build is present, then add the LLM extras:

```bash
.venv/bin/pip install -e '.[llm,dev]'
```

The extras provide Transformers, PEFT, and Tokenizers. Install your hardware-specific PyTorch wheel before the extras; follow the ROCm installation contract in [HENTAI Operations](https://github.com/Lithium357/HENTAI/blob/main/docs/OPERATIONS.md).

## Safe sequence

1. Run `hentai-studio llm-validate --config <config>`; this reads only configuration.
2. Run `hentai-studio llm-audit --config <config>`; this reads JSONL text but performs no GPU work.
3. Run `hentai-studio llm-smoke --config <config> --tiny`; it uses synthetic token IDs and validates a forward/backward/optimizer/safetensors round trip on CPU.
4. For LoRA/CPT, run `hentai-studio llm-build-packed-cache --config <config>`; it tokenizes the configured text into deterministic train/validation streams without using the GPU. This can take substantial storage and time.
5. Run `hentai-studio llm-prepare --config <config> --run-id <id>`; it creates an empty run directory and stores the input fingerprint.
6. Only when the GPU is not occupied by protected diffusion work, start `hentai-studio llm-train --config <config> --device cuda`.

The cache command writes to `dataset.packed_cache` unless `--output` is supplied. An existing compatible cache is reused. `--overwrite` replaces an incompatible destination only after the new cache has been built in a sibling staging directory.

`llm-train` can also use `--device cpu` for tiny fixtures. It appends one durable row per optimizer step to `progress/train.csv`; evaluation rows carry both `train_loss` and `eval_loss`. Studio exposes those as separate chart series and scopes process/GPU telemetry to the selected LLM run.

For LoRA runs, weights checkpoints contain `adapter/adapter_config.json`, `adapter/adapter_model.safetensors`, and metadata. Resume checkpoints additionally contain optimizer, trainer, and RNG state. A checkpoint is written to a temporary sibling directory and renamed only after every required artifact exists; incomplete saves are ignored. On resume, the packed-cache cursor is advanced to the saved batch and saved RNG state is restored.

The ERP profile uses 16 gradient-accumulation microbatches of 512 tokens, or 8,192 tokens per optimizer step. Its initial 10,000-step run is a controlled trial (~82M tokens), not an epoch over the ~53 GB archive. At the observed pace, full-corpus coverage would be on the order of 1.5M steps, so length should be decided from validation and checkpoint quality rather than assumed from file size.

## CPU-only checkpoint chat

The Studio chat pane remains disabled until a complete LoRA weights checkpoint exists. Once enabled, it loads the base model and selected adapter onto CPU only; it never uses the training GPU or its VRAM. This lets checkpoint responses be tested while GPU training continues.
