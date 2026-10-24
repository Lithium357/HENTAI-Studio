# ROCm experiment log
- Captured 2026-10-12: WSL kernel `6.18.33.2-microsoft-standard-WSL2`; PyTorch `2.13.0+rocm10.0.0` (HIP `7.15.26333`); Transformers `4.57.6`; PEFT `0.20.0`.

This is the evidence log for AMD/ROCm-specific training and inference work in HENTAI Studio. Every entry must distinguish a measured result from an inference. Preserve exact versions, commands, configurations, errors, and minimal reproduction steps.

## Environment baseline

- Workload: Qwen3-4B LoRA continued pretraining, BF16, 512-token sequences.
- GPU: AMD Radeon RX 7800 XT (16 GiB reported by Studio).
- Host: Windows + WSL2 Ubuntu.
- Trainer: local PyTorch/Transformers/PEFT stack. Exact package and driver versions must be captured for every future experiment.

## Observed issues

### ROCm SDPA memory-efficient attention is unavailable by default

- Date: 2026-10-10.
- Trigger: loading the Qwen3-4B LoRA trainer with `attn_implementation="sdpa"`.
- Exact warning:

  ```text
  Mem Efficient attention on Current AMD GPU is still experimental.
  Enable it with TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1.
  ```

- Effect: training falls back to a non-experimental SDPA path. No correctness failure or hardware fault was observed.
- Status: untested experimental candidate. Do not claim a performance gain until a fixed-step benchmark records tokens/sec, loss, and stability.
- Reproduction: launch `hentai-studio llm-train` with the ERP Qwen3-4B LoRA configuration on ROCm, leaving `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL` unset.
- Proposed experiment: enable `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1` for a dedicated benchmark run only; compare against the baseline with the same checkpoint, data cursor, batch geometry, and fixed number of measured steps.

### ROCm command-line telemetry was not present in the WSL environment

- Date: 2026-10-12.
- Checks: `rocm-smi` and `amdgpu_top` were not found in the WSL command path.
- Effect: the benchmark harness cannot currently collect independent CLI utilization, temperature, or power telemetry from WSL.
- Status: environment gap, not evidence of a ROCm runtime failure.
- Workaround: use Studio's hardware probe when available; record missing fields explicitly rather than fabricating values.

### 2x8 microbatch with activation checkpointing disabled stalled in WSL GPU synchronization

- Date: 2026-10-12.
- Configuration: Qwen3-4B LoRA, BF16, 512-token context, microbatch 2, gradient accumulation 8, gradient checkpointing disabled, same 8,192 tokens/optimizer update as the baseline. This was a separate prepared benchmark run and never wrote a progress row.
- Observed behavior: model checkpoint shards loaded successfully. Before the first training step was durably recorded, the trainer entered a long-running GPU wait. Process state was initially `Dsl+`, then `Rsl+`; CPU usage remained high, but no checkpoint or progress CSV existed.
- Kernel evidence from WSL2 6.18.33.2-microsoft-standard-WSL2:

  ```text
  WARNING: ... dxgvmb_send_wait_sync_object_gpu
  dxgk: dxgkio_wait_sync_object_cpu: wait_completion_interruptible: -512
  dxgk: dxgkio_wait_sync_object_cpu: Ioctl failed: -512
  ```

- Recovery: sent `SIGTERM` to only the benchmark PID. It exited; no active LLM trainer remained. No hardware reset, thermal fault, or corrupted checkpoint was observed.
- Classification: WSL dxgkrnl/ROCm GPU synchronization stall. This is not an out-of-memory conclusion because ROCm CLI telemetry was unavailable and no explicit OOM message was emitted.
- Decision: reject this exact `2x8 + no activation checkpointing` profile for now. Next test should reduce only one risk dimension: `1x16` with activation checkpointing disabled. Preserve identical model, sequence length, precision, and effective token batch.

### 1x16 microbatch with activation checkpointing disabled failed WSL GPU allocation before the first step

- Date: 2026-10-12.
- Configuration: Qwen3-4B LoRA, BF16, 512-token context, microbatch 1, gradient accumulation 16, gradient checkpointing disabled; this preserves the original pilot's batch geometry and its 8,192 tokens/optimizer update.
- Exact launch: `hentai-studio llm-train --config configs/llm-erp-qwen3-4b-cpt-bench-mb1-gc-off.json --device cuda`.
- Observed behavior: all three base-model checkpoint shards loaded. No `progress/train.csv` was written and no train step was completed. The process was interrupted with Ctrl-C after it remained pre-step for approximately one minute.
- Kernel evidence from WSL2 6.18.33.2-microsoft-standard-WSL2:

  ```text
  misc dxg: dxgk: create_existing_sysmem: get_user_pages_fast failed: 2534
  misc dxg: dxgk: dxgvmb_send_sync_msg: wait_for_completion failed: fffffe00
  misc dxg: dxgk: create_local_allocations: failed to destroy allocations: fffffe00
  misc dxg: dxgk: dxgkio_create_allocation: Ioctl failed: -12
  ```

- Recovery: interrupted only the benchmark process; it exited. No active LLM trainer, checkpoint mutation, GPU reset, or thermal event remained.
- Classification: WSL dxgkrnl allocation failure while using a larger activation footprint. `-12` is consistent with allocation/resource exhaustion, but this is **not** a confirmed VRAM-OOM diagnosis: WSL had no ROCm CLI telemetry and PyTorch emitted no explicit out-of-memory exception.
- Decision: reject `activation_checkpointing=false` at this model/context for the current WSL GPU path. The next safe benchmark must retain activation checkpointing and vary no more than one independent parameter. Do not enable experimental AOTriton or increase microbatch until a checkpointing-on control run establishes a stable baseline.

### Checkpointing-on AOTriton control stalled in the same WSL synchronization path

- Date: 2026-10-12.
- Configuration: Qwen3-4B LoRA, BF16, 512-token context, microbatch 1, gradient accumulation 16, activation checkpointing enabled, experimental AOTriton enabled only through `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1`.
- Observed behavior: all three base-model shards loaded, but no `progress/train.csv` and no first step appeared after approximately one minute. This is a control profile with the original pilot's stable geometry; it was started only after the prior allocation failure.
- Kernel evidence:

  ```text
  misc dxg: dxgk: dxgkio_wait_sync_object_cpu: wait_completion_interruptible: -512
  misc dxg: dxgk: dxgkio_wait_sync_object_cpu: Ioctl failed: -512
  ```

- Recovery: interrupted only the benchmark process; project tests then passed (`38 passed`).
- Classification: this result cannot evaluate AOTriton's performance or stability because the WSL GPU bridge was already unhealthy after the preceding allocation failure. It is not evidence that AOTriton itself is defective.
- Decision: do not retry or adopt AOTriton in the current WSL session. A controlled retry requires a user-approved WSL shutdown/restart, followed by a checkpointing-on baseline before any experimental attention comparison.

### Clean checkpointing-on SDPA control completed successfully after WSL reset

- Date: 2026-10-12.
- Configuration: Qwen3-4B LoRA, BF16, 512-token context, microbatch 1, gradient accumulation 16, activation checkpointing enabled, default non-experimental SDPA; 8,192 tokens/optimizer update.
- Result: all 250 steps completed. Across 248 non-evaluation steps, median step time was `14.367` seconds and median throughput was `570.20` tokens/sec.
- Validation: step 100 loss `2.871679`; step 200 loss `2.832617`. These are measurements from a fresh run, not a continuation of the halted pilot.
- Checkpoint: step-250 weights and resume checkpoints both verified complete; the resume checkpoint included optimizer and RNG state.
- Kernel status: no new dxgkrnl wait, allocation, reset, or thermal error was emitted during the benchmark.
- Decision: this is the only approved long-CPT geometry for the current WSL/ROCm stack: `1x16`, BF16, 512-token context, activation checkpointing enabled, default SDPA.

### Fresh AOTriton retry triggered a dxgkrnl warning despite a clean control run

- Date: 2026-10-12.
- Configuration: identical to the successful control except `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1`; separate prepared run directory `erp-qwen3-4b-cpt-bench-aotriton-v2`.
- Exact launch: `env TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1 hentai-studio llm-train --config configs/llm-erp-qwen3-4b-cpt-bench-aotriton-v2.json --device cuda`.
- Observed behavior: steps 1 and 2 completed at `507.66` and `715.93` tokens/sec respectively, but the second-step window emitted a WSL dxgkrnl warning. The run was stopped immediately; it was not permitted to continue to validation.
- Kernel evidence from WSL2 `6.18.33.2-microsoft-standard-WSL2`:

  ```text
  memcpy: detected field-spanning write ... drivers/hv/dxgkrnl/dxgvmbus.c:3095
  WARNING: ... dxgvmb_send_wait_sync_object_gpu
  dxgk: dxgkio_wait_sync_object_cpu: wait_completion_interruptible: -512
  dxgk: dxgkio_wait_sync_object_cpu: Ioctl failed: -512
  ```

- Recovery: interrupted only the AOTriton benchmark. No data or checkpoint was overwritten.
- Classification: a fresh-session reproduction links the experimental attention path to an unstable WSL dxgkrnl synchronization path. Two steps are insufficient to claim its apparent throughput gain.
- Decision: reject experimental AOTriton for the next long CPT on this stack. Retest only after a newer compatible WSL/Windows/ROCm stack is available, using this exact control protocol.

## Non-ROCm issue kept separate

### Transformers BF16 CPU checkpoint chat retained excessive host memory

- Date: 2026-10-12.
- Symptom: the dashboard retained a CPU-resident Qwen3-4B BF16 model after a chat probe, reaching roughly 97% dashboard-process memory use and temporarily increasing training step time from about 13.4 seconds to 16-18 seconds.
- Scope: host-RAM/CPU contention, not GPU or ROCm inference. The GPU trainer remained live.
- Mitigation: Studio now unloads the CPU chat model after a reply while an LLM trainer is active.
- Permanent direction: use a quantized llama.cpp GGUF base plus a separately converted GGUF LoRA adapter for CPU checkpoint evaluation.

## Required fields for every future experiment

| Field | Record |
| --- | --- |
| Identity | Date, Git revision, GPU, operating system, WSL distribution |
| Runtime | ROCm/driver, PyTorch, Transformers, PEFT, llama.cpp versions |
| Command | Exact environment variables and launch command |
| Data | Run/checkpoint, dataset fingerprint, context length, data cursor |
| Geometry | Microbatch, accumulation, checkpointing, attention backend, precision |
| Result | Median step time, tokens/sec, loss range, validation loss, peak VRAM/RAM |
| Stability | Completion status, warnings, errors, reset/OOM details, repro steps |
| Decision | Adopt, reject, or retest, with the reason |
