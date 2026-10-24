# Causal-LM profiles

`llm-erp-qwen3-4b-cpt-v2-full-pass.json` is the long LoRA/CPT reference geometry. The smoke and benchmark profiles preserve the experiments documented in `../docs/ROCM_EXPERIMENT_LOG.md`.

Copy the nearest profile and change `dataset.root`, `dataset.packed_cache`, `tokenizer.base_model`, `model.base_model`, and `run_dir` for your machine. These profiles contain reference paths under `/mnt/d`, not bundled datasets or model weights. Never reuse a live run directory for another trainer.

Diffusion profiles remain in [HENTAI/configs](https://github.com/Lithium357/HENTAI/tree/main/configs).
