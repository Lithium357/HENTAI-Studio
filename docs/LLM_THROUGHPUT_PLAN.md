# ERP LoRA throughput plan

## Measured decision

The pilot was stopped at its verified step-9500 checkpoint. A fresh, isolated control run then established the configuration to use on this machine:

- Qwen3-4B LoRA, BF16, 512-token context, microbatch 1, accumulation 16, and activation checkpointing enabled.
- 250 clean steps completed with median `14.367` seconds/step and `570.20` tokens/sec over non-evaluation steps.
- Validation loss was `2.871679` at step 100 and `2.832617` at step 200.
- The verified step-250 adapter and resume checkpoints include optimizer and RNG state.
- Disabling activation checkpointing failed before useful progress in both `1x16` and `2x8` variants. Experimental AOTriton reproduced a WSL `dxgkrnl` warning in a fresh session and is rejected for this run.

## Full-pass estimate and launch gate

A deterministic 12,000-row Qwen sample measured `0.2303956` tokens per source character. A constant-memory full scan of the local 53.3 GB archive counted 34,884,764 non-empty message rows and 41,339,347,419 source characters. That projects to:

- 9.524B total tokens and 9.429B training tokens after the deterministic 1% validation split.
- 1,151,021 optimizer steps at 8,192 tokens/update.
- Roughly 191 days at the measured control throughput, before outages and checkpoint overhead.

`configs/llm-erp-qwen3-4b-cpt-v2-full-pass.json` uses that estimated target, 500-step weights/resume checkpoints, and 500-step validation. Its launch gate was satisfied by the versioned packed-token cache: fixed 512-token train/validation blocks are memory-mapped from disk, and resume advances directly to the saved logical block offset instead of replaying raw CSV rows.

The `cpt-v1` pilot is complete, and the long `cpt-v2-full-pass` run uses the approved control geometry. Do not alter a live training job to change batch geometry, checkpointing, attention kernels, or compilation.

## Fixed comparison geometry

Every candidate keeps one optimizer update at 8,192 tokens:

| Profile | Microbatch | Accumulation | Gradient checkpointing | Purpose |
| --- | ---: | ---: | --- | --- |
| Baseline | 1 | 16 | on | Current pilot reference |
| A | 1 | 16 | off | Measure activation-recompute cost |
| B | 2 | 8 | off | First higher-throughput candidate |
| C | 4 | 4 | off | Test only after B is stable |

The shipped benchmark config is profile B and runs for 1,000 steps. It is not a full-pass launch.

## Promotion gate

For each profile:

1. Prepare a distinct run directory and execute the normal config validation and smoke checks.
2. Run at least 500 measured steps after any warmup behavior.
3. Record median step time, tokens/sec, train loss range, validation loss, warnings, and any OOM/reset.
4. Add the result to `ROCM_EXPERIMENT_LOG.md`.
5. Promote only a configuration that is stable and materially faster without a loss/validation regression.

## Experimental ROCm work

`TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1` is opt-in and must be benchmarked in a dedicated run. Capture the full warning/error output and reproduce failures with the smallest practical configuration. Do not enable it in the long run by default.

## Data-path result

The original trainer normalized CSV/HTML and tokenized synchronously for every block. The production path now consumes a versioned, fingerprinted packed-token cache with fixed 512-token blocks and separate deterministic train/validation streams. Cache generation is exposed as `hentai-studio llm-build-packed-cache`; cache files remain local artifacts and are excluded from Git.
