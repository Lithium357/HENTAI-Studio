from __future__ import annotations

import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path

from ...core.checkpoints import atomic_checkpoint, rotate_complete
from ...core.progress import append_progress
from .config import LLMConfig
from .dataset import fingerprint, jsonl_files, split_name, text_from_record
from .tokenizer import train_bpe


def _imports():
    try:
        import torch
        from safetensors.torch import load_file, save_file
        from tokenizers import Tokenizer
        from transformers import LlamaConfig, LlamaForCausalLM
    except ImportError as error:
        raise RuntimeError("LLM training backend is unavailable; install optional LLM dependencies") from error
    return torch, load_file, save_file, Tokenizer, LlamaConfig, LlamaForCausalLM


def _documents(config: LLMConfig):
    for file in jsonl_files(config.dataset.root):
        with file.open(encoding="utf-8") as handle:
            for raw in handle:
                if not raw.strip():
                    continue
                try:
                    text = text_from_record(json.loads(raw), config.dataset.schema)
                except (ValueError, json.JSONDecodeError):
                    continue
                if text.strip():
                    yield text


def _token_blocks(config: LLMConfig, tokenizer, split: str) -> list[list[int]]:
    eos = tokenizer.token_to_id("<eos>")
    if eos is None:
        raise RuntimeError("run tokenizer does not define <eos>")
    pending: list[int] = []
    blocks: list[list[int]] = []
    for text in _documents(config):
        if split_name(text, config.seed, config.dataset.validation_fraction) != split:
            continue
        pending.extend(tokenizer.encode(text).ids)
        pending.append(eos)
        while len(pending) >= config.dataset.context_length:
            blocks.append(pending[:config.dataset.context_length])
            pending = pending[config.dataset.context_length:]
    return blocks


def _model(config: LLMConfig, vocab_size: int, LlamaConfig, LlamaForCausalLM):
    spec = config.model
    return LlamaForCausalLM(LlamaConfig(
        vocab_size=vocab_size, hidden_size=spec.hidden_size, intermediate_size=spec.intermediate_size,
        num_hidden_layers=spec.num_hidden_layers, num_attention_heads=spec.num_attention_heads,
        num_key_value_heads=spec.num_key_value_heads, max_position_embeddings=spec.max_position_embeddings,
        pad_token_id=0, bos_token_id=2, eos_token_id=3, use_cache=False,
    ))


def _latest_resume(run_dir: Path) -> Path | None:
    root = run_dir / "checkpoints" / "resume"
    valid: list[tuple[int, Path]] = []
    for path in root.glob("step-*") if root.is_dir() else ():
        try:
            step = int(path.name.removeprefix("step-"))
        except ValueError:
            continue
        if all((path / name).is_file() for name in ("model.safetensors", "optimizer.pt", "trainer-state.json")):
            valid.append((step, path))
    return max(valid, default=(0, None))[1]


def train_scratch(config: LLMConfig, *, config_path: str | Path, resume: bool = True, device: str | None = None) -> None:
    """Train the project-owned scratch path. It reads configured dataset text and can use GPU."""
    if config.mode != "scratch":
        raise ValueError("train_scratch only accepts mode=scratch; fine-tuning is not wired yet")
    torch, load_file, save_file, Tokenizer, LlamaConfig, LlamaForCausalLM = _imports()
    run_dir = config.output.resolve()
    identity = run_dir / "run.json"
    if not identity.is_file():
        raise ValueError("run is not prepared; use llm-prepare before training")
    expected_fingerprint = json.loads((run_dir / "dataset-fingerprint.json").read_text(encoding="utf-8"))["fingerprint"]
    current_fingerprint = fingerprint(jsonl_files(config.dataset.root), config.dataset, f"{config.tokenizer.mode}:{config.tokenizer.base_model or config.tokenizer.vocab_size}")
    if expected_fingerprint != current_fingerprint:
        raise ValueError("dataset fingerprint changed since prepare; prepare a new run instead of silently changing resume data")
    tokenizer_dir = run_dir / "tokenizer"
    tokenizer_path = tokenizer_dir / "tokenizer.json"
    if not tokenizer_path.is_file():
        train_bpe(config.dataset, config.tokenizer, tokenizer_dir)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    train_blocks = _token_blocks(config, tokenizer, "train")
    if not train_blocks:
        raise ValueError("dataset produced no complete train token blocks")
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device != "cpu" and not torch.cuda.is_available():
        raise RuntimeError("requested accelerator is unavailable")
    torch.manual_seed(config.seed)
    model = _model(config, tokenizer.get_vocab_size(), LlamaConfig, LlamaForCausalLM).to(device)
    if config.training.gradient_checkpointing:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.training.learning_rate, weight_decay=config.training.weight_decay)
    start_step = 0
    resumed_from = 0
    if resume and (checkpoint := _latest_resume(run_dir)) is not None:
        model.load_state_dict(load_file(str(checkpoint / "model.safetensors"), device=device))
        optimizer.load_state_dict(torch.load(checkpoint / "optimizer.pt", map_location=device, weights_only=False))
        state = json.loads((checkpoint / "trainer-state.json").read_text(encoding="utf-8"))
        start_step = resumed_from = int(state["step"])
    session_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    progress_path = run_dir / "progress" / "train.csv"
    for step in range(start_step + 1, config.training.max_steps + 1):
        started = time.perf_counter()
        losses: list[float] = []
        for accumulation in range(config.training.gradient_accumulation):
            block = train_blocks[((step - 1) * config.training.gradient_accumulation + accumulation) % len(train_blocks)]
            tokens = torch.tensor([block], dtype=torch.long, device=device)
            loss = model(input_ids=tokens, labels=tokens, use_cache=False).loss / config.training.gradient_accumulation
            loss.backward()
            losses.append(float(loss.detach().cpu()) * config.training.gradient_accumulation)
        grad_norm = float(torch.nn.utils.clip_grad_norm_(model.parameters(), config.training.max_grad_norm).detach().cpu())
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)
        elapsed = max(time.perf_counter() - started, 1e-9)
        tokens_seen = step * config.training.gradient_accumulation * config.dataset.context_length
        append_progress(progress_path, {
            "timestamp_utc": datetime.now(UTC).isoformat(), "session_id": session_id, "resumed_from_step": resumed_from,
            "step": step, "total_steps": config.training.max_steps, "progress_percent": step / config.training.max_steps * 100,
            "train_loss": sum(losses) / len(losses), "learning_rate": config.training.learning_rate, "gradient_norm": grad_norm,
            "seconds_per_step": elapsed, "tokens_per_second": config.training.gradient_accumulation * config.dataset.context_length / elapsed,
            "tokens_seen": tokens_seen, "sequences_seen": step * config.training.gradient_accumulation,
            "micro_batch_size": config.training.micro_batch_size, "gradient_accumulation": config.training.gradient_accumulation,
            "context_length": config.dataset.context_length,
        })
        def weights_writer(destination: Path) -> None:
            save_file({key: value.detach().cpu().contiguous() for key, value in model.state_dict().items()}, str(destination / "model.safetensors"))
            (destination / "metadata.json").write_text(json.dumps({"step": step, "mode": "scratch", "tokens_seen": tokens_seen}) + "\n", encoding="utf-8")
        if step % config.checkpointing.weights_every == 0 or step == config.training.max_steps:
            atomic_checkpoint(run_dir / "checkpoints" / "weights", step, weights_writer, ("model.safetensors", "metadata.json"))
            rotate_complete(run_dir / "checkpoints" / "weights", config.checkpointing.keep_weights, ("model.safetensors", "metadata.json"))
        if step % config.checkpointing.resume_every == 0 or step == config.training.max_steps:
            def resume_writer(destination: Path) -> None:
                weights_writer(destination)
                torch.save(optimizer.state_dict(), destination / "optimizer.pt")
                (destination / "trainer-state.json").write_text(json.dumps({"step": step, "session_id": session_id}) + "\n", encoding="utf-8")
            atomic_checkpoint(run_dir / "checkpoints" / "resume", step, resume_writer, ("model.safetensors", "metadata.json", "optimizer.pt", "trainer-state.json"))
            rotate_complete(run_dir / "checkpoints" / "resume", config.checkpointing.keep_resume, ("model.safetensors", "metadata.json", "optimizer.pt", "trainer-state.json"))
