"""Local-only LoRA continued pretraining for the ERP CSV archive."""
from __future__ import annotations

import atexit
import csv
import html
import json
import math
import os
import random
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from ...core.checkpoints import atomic_checkpoint, rotate_complete
from ...core.progress import append_progress
from .config import LLMConfig
from .dataset import split_name

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def _write_run_state(run_dir: Path, state: str, **details: object) -> None:
    """Atomically update the small dashboard identity record for this run."""
    identity_path = run_dir / "run.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity["state"] = state
    identity["updated_at"] = datetime.now(UTC).isoformat()
    identity.update(details)
    temporary = run_dir / ".run.json.tmp"
    temporary.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
    temporary.replace(identity_path)


def configure_csv_field_limit() -> None:
    """Accept long archive rows instead of inheriting csv's 128 KiB default."""
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def _normalise(raw: str) -> str:
    text = html.unescape(raw)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = _TAG.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(_SPACE.sub(" ", line).strip() for line in text.split("\n")).strip()


class ArchiveBlocks:
    def __init__(self, root: Path, tokenizer, length: int, seed: int, validation_fraction: float, validation: bool, limit: int | None = None):
        self.paths = sorted([*root.glob("*.csv"), *root.glob("*.jsonl")]); self.tokenizer = tokenizer; self.length = length
        self.seed = seed; self.validation_fraction = validation_fraction; self.validation = validation; self.limit = limit

    def __iter__(self):
        paths = self.paths.copy(); random.Random(self.seed).shuffle(paths)
        buffer: list[int] = []; emitted = 0; eos = self.tokenizer.eos_token_id
        for path in paths:
            with path.open("r", encoding="utf-8", errors="replace", newline="") as stream:
                if path.suffix == ".csv":
                    configure_csv_field_limit()
                    records = (row.get("message", "") for row in csv.DictReader(stream))
                else:
                    def jsonl_records():
                        for raw in stream:
                            try:
                                value = json.loads(raw)
                            except json.JSONDecodeError:
                                continue
                            if isinstance(value, dict) and isinstance(value.get("text"), str):
                                yield value["text"]
                    records = jsonl_records()
                for raw in records:
                    text = _normalise(raw)
                    if not text or (split_name(text, self.seed, self.validation_fraction) == "validation") != self.validation:
                        continue
                    buffer.extend(self.tokenizer(text, add_special_tokens=False)["input_ids"]); buffer.append(eos)
                    while len(buffer) >= self.length:
                        chunk, buffer = buffer[:self.length], buffer[self.length:]
                        yield chunk; emitted += 1
                        if self.limit is not None and emitted >= self.limit: return


def _imports():
    import torch
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer
    return torch, LoraConfig, PeftModel, get_peft_model, AutoModelForCausalLM, AutoTokenizer


def _complete_resume(path: Path) -> bool:
    required = ("adapter/adapter_config.json", "adapter/adapter_model.safetensors", "optimizer.pt", "rng-state.pt", "trainer-state.json", "metadata.json")
    return all((path / item).is_file() for item in required)


def _complete_weights(path: Path) -> bool:
    return all((path / item).is_file() for item in ("adapter/adapter_config.json", "adapter/adapter_model.safetensors", "metadata.json"))


def _save_rng_state(torch, destination: Path) -> None:
    torch.save({
        "python": random.getstate(),
        "torch": torch.get_rng_state(),
        "cuda": torch.cuda.get_rng_state_all(),
    }, destination / "rng-state.pt")


def _restore_rng_state(torch, source: Path) -> None:
    state_path = source / "rng-state.pt"
    if not state_path.is_file():
        return
    state = torch.load(state_path, map_location="cpu", weights_only=False)
    random.setstate(state["python"])
    torch.set_rng_state(state["torch"])
    torch.cuda.set_rng_state_all(state["cuda"])


def run_lora_cpt(config: LLMConfig, *, resume: bool = True) -> None:
    if config.mode != "lora": raise ValueError("LoRA CPT requires mode=lora")
    torch, LoraConfig, PeftModel, get_peft_model, AutoModelForCausalLM, AutoTokenizer = _imports()
    run_dir = config.output.resolve(); base_path = Path(config.model.base_model or "")
    if not (run_dir / "run.json").is_file() or not base_path.is_dir(): raise ValueError("prepared run and local base_model are required")
    tokenizer = AutoTokenizer.from_pretrained(base_path, local_files_only=True)
    tokenizer_identity = str(config.tokenizer.base_model or config.model.base_model or "unknown")
    if tokenizer.pad_token_id is None: tokenizer.pad_token = tokenizer.eos_token
    latest = max((path for path in (run_dir / "checkpoints" / "resume").glob("step-*") if _complete_resume(path)), key=lambda p: int(p.name[5:]), default=None)
    base = AutoModelForCausalLM.from_pretrained(base_path, local_files_only=True, dtype=torch.bfloat16, attn_implementation="sdpa")
    base.config.use_cache = False; base.enable_input_require_grads()
    if latest and resume:
        model = PeftModel.from_pretrained(base, str(latest / "adapter"), is_trainable=True)
        state = json.loads((latest / "trainer-state.json").read_text()); start = int(state["step"])
    else:
        model = get_peft_model(base, LoraConfig(r=config.model.lora_rank, lora_alpha=config.model.lora_alpha, lora_dropout=config.model.lora_dropout, bias="none", task_type="CAUSAL_LM", target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"]))
        start = 0
    model.to("cuda")
    if config.training.gradient_checkpointing:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.train()
    optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=config.training.learning_rate, weight_decay=config.training.weight_decay)
    if latest and resume:
        optimizer.load_state_dict(torch.load(latest / "optimizer.pt", map_location="cpu", weights_only=False))
        _restore_rng_state(torch, latest)
    archive = Path(config.dataset.root)
    if not config.dataset.packed_cache: raise ValueError("LoRA CPT requires dataset.packed_cache; build it with llm-build-packed-cache before training")
    from .packed_cache import PackedBlocks, load_manifest
    manifest = load_manifest(config.dataset.packed_cache, config, tokenizer_identity)
    blocks_per_step = config.training.micro_batch_size * config.training.gradient_accumulation
    if start * blocks_per_step >= manifest.train_blocks: raise ValueError("resume step has consumed every cached training block")
    train_iter = iter(PackedBlocks(config.dataset.packed_cache, "train", config.dataset.context_length, manifest.train_blocks, start=start * blocks_per_step, shuffle_seed=config.seed))
    validation = PackedBlocks(config.dataset.packed_cache, "validation", config.dataset.context_length, manifest.validation_blocks, limit=config.evaluation.max_batches)
    session = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"); progress = run_dir / "progress" / "train.csv"
    lifecycle: dict[str, object] = {"state": "interrupted", "session_id": session, "final_step": start}
    _write_run_state(run_dir, "running", session_id=session, resumed_from_step=start)

    def write_final_state() -> None:
        _write_run_state(run_dir, str(lifecycle["state"]), session_id=session, final_step=lifecycle["final_step"])

    # This covers ordinary exceptions and clean Python exits. A forced process
    # kill still has the systemd event log and the last complete resume point.
    atexit.register(write_final_state)
    for step in range(start + 1, config.training.max_steps + 1):
        began = time.monotonic(); losses = []
        for _ in range(config.training.gradient_accumulation):
            batch = [next(train_iter) for _ in range(config.training.micro_batch_size)]
            tokens = torch.tensor(batch, device="cuda", dtype=torch.long)
            loss = model(input_ids=tokens, labels=tokens, use_cache=False).loss / config.training.gradient_accumulation; loss.backward(); losses.append(float(loss.detach()) * config.training.gradient_accumulation)
        norm = float(torch.nn.utils.clip_grad_norm_(model.parameters(), config.training.max_grad_norm)); optimizer.step(); optimizer.zero_grad(set_to_none=True)
        eval_loss = None
        if step % config.evaluation.every == 0:
            model.eval(); values=[]
            with torch.no_grad():
                for block in validation:
                    tokens=torch.tensor([block],device="cuda",dtype=torch.long); values.append(float(model(input_ids=tokens,labels=tokens,use_cache=False).loss.detach()))
            eval_loss = sum(values)/len(values) if values else None; model.train()
        elapsed=time.monotonic()-began; seen=step*blocks_per_step*config.dataset.context_length
        append_progress(progress,{"timestamp_utc":datetime.now(UTC).isoformat(),"session_id":session,"resumed_from_step":start,"step":step,"total_steps":config.training.max_steps,"progress_percent":step/config.training.max_steps*100,"train_loss":sum(losses)/len(losses),"eval_loss":eval_loss,"perplexity":math.exp(eval_loss) if eval_loss is not None and eval_loss < 20 else "","learning_rate":config.training.learning_rate,"gradient_norm":norm,"seconds_per_step":elapsed,"tokens_per_second":blocks_per_step*config.dataset.context_length/elapsed,"tokens_seen":seen,"sequences_seen":step*blocks_per_step,"micro_batch_size":config.training.micro_batch_size,"gradient_accumulation":config.training.gradient_accumulation,"context_length":config.dataset.context_length})
        if step % config.checkpointing.weights_every == 0 or step == config.training.max_steps:
            def save(dest: Path):
                model.save_pretrained(dest / "adapter", safe_serialization=True); (dest / "metadata.json").write_text(json.dumps({"step":step,"base_model":str(base_path)})+"\n")
            atomic_checkpoint(run_dir / "checkpoints" / "weights", step, save, ("adapter/adapter_config.json","adapter/adapter_model.safetensors","metadata.json")); rotate_complete(run_dir / "checkpoints" / "weights",config.checkpointing.keep_weights,("adapter/adapter_config.json","adapter/adapter_model.safetensors","metadata.json"))
        if step % config.checkpointing.resume_every == 0 or step == config.training.max_steps:
            def save_resume(dest: Path):
                model.save_pretrained(dest / "adapter", safe_serialization=True); torch.save(optimizer.state_dict(),dest/"optimizer.pt"); _save_rng_state(torch, dest); (dest/"trainer-state.json").write_text(json.dumps({"step":step,"session_id":session})+"\n"); (dest/"metadata.json").write_text(json.dumps({"step":step,"base_model":str(base_path)})+"\n")
            atomic_checkpoint(run_dir / "checkpoints" / "resume",step,save_resume,("adapter/adapter_config.json","adapter/adapter_model.safetensors","optimizer.pt","rng-state.pt","trainer-state.json","metadata.json")); rotate_complete(run_dir / "checkpoints" / "resume",config.checkpointing.keep_resume,("trainer-state.json","rng-state.pt"))
        lifecycle["final_step"] = step
    lifecycle["state"] = "completed"
