from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Literal


def _strict(cls: type, raw: dict[str, Any], name: str):
    allowed = {field.name for field in fields(cls)}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"unknown {name} keys: {', '.join(unknown)}")
    return cls(**raw)


@dataclass(slots=True)
class DatasetConfig:
    root: str
    schema: Literal["text", "prompt_completion", "messages"]
    packed_cache: str | None = None
    validation_fraction: float = 0.01
    context_length: int = 2048
    packing: bool = True
    num_workers: int = 1
    mask_prompt_tokens: bool = True

    def __post_init__(self) -> None:
        if self.schema not in {"text", "prompt_completion", "messages"}:
            raise ValueError("dataset.schema must be text, prompt_completion, or messages")
        if not 0 < self.validation_fraction < 0.5:
            raise ValueError("dataset.validation_fraction must be greater than 0 and less than 0.5")
        if self.context_length < 16:
            raise ValueError("dataset.context_length must be at least 16")
        if self.num_workers < 0:
            raise ValueError("dataset.num_workers must be non-negative")


@dataclass(slots=True)
class TokenizerConfig:
    mode: Literal["train_bpe", "base_model"]
    vocab_size: int = 32000
    min_frequency: int = 2
    base_model: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"train_bpe", "base_model"}:
            raise ValueError("tokenizer.mode must be train_bpe or base_model")
        if self.vocab_size < 256:
            raise ValueError("tokenizer.vocab_size must be at least 256")
        if self.min_frequency < 1:
            raise ValueError("tokenizer.min_frequency must be positive")
        if self.mode == "base_model" and not self.base_model:
            raise ValueError("tokenizer.base_model is required when tokenizer.mode is base_model")


@dataclass(slots=True)
class ModelConfig:
    architecture: str = "llama"
    hidden_size: int = 768
    intermediate_size: int = 2048
    num_hidden_layers: int = 12
    num_attention_heads: int = 12
    num_key_value_heads: int = 4
    max_position_embeddings: int = 2048
    base_model: str | None = None
    lora_rank: int = 32
    lora_alpha: int = 64
    lora_dropout: float = 0.05

    def __post_init__(self) -> None:
        if self.architecture != "llama":
            raise ValueError("only llama decoder architecture is supported in the MVP")
        if self.hidden_size % self.num_attention_heads:
            raise ValueError("model.hidden_size must be divisible by model.num_attention_heads")
        if self.num_attention_heads % self.num_key_value_heads:
            raise ValueError("model.num_attention_heads must be divisible by model.num_key_value_heads")
        if min(self.hidden_size, self.intermediate_size, self.num_hidden_layers, self.max_position_embeddings) <= 0:
            raise ValueError("model dimensions must be positive")
        if self.lora_rank <= 0 or self.lora_alpha <= 0 or not 0 <= self.lora_dropout < 1:
            raise ValueError("invalid LoRA settings")


@dataclass(slots=True)
class TrainingConfig:
    micro_batch_size: int = 1
    gradient_accumulation: int = 16
    learning_rate: float = 3e-4
    weight_decay: float = 0.1
    warmup_steps: int = 1000
    max_steps: int = 100000
    mixed_precision: Literal["fp16", "bf16", "no"] = "fp16"
    gradient_checkpointing: bool = True
    max_grad_norm: float = 1.0

    def __post_init__(self) -> None:
        if min(self.micro_batch_size, self.gradient_accumulation, self.max_steps) <= 0:
            raise ValueError("training batch sizes and max_steps must be positive")
        if self.learning_rate <= 0 or self.weight_decay < 0 or self.warmup_steps < 0 or self.max_grad_norm <= 0:
            raise ValueError("invalid training optimizer settings")
        if self.mixed_precision not in {"fp16", "bf16", "no"}:
            raise ValueError("training.mixed_precision must be fp16, bf16, or no")


@dataclass(slots=True)
class CheckpointConfig:
    weights_every: int = 1000
    resume_every: int = 5000
    keep_weights: int = 5
    keep_resume: int = 2

    def __post_init__(self) -> None:
        if min(self.weights_every, self.resume_every, self.keep_weights, self.keep_resume) <= 0:
            raise ValueError("checkpointing values must be positive")


@dataclass(slots=True)
class EvaluationConfig:
    every: int = 1000
    max_batches: int = 100

    def __post_init__(self) -> None:
        if self.every <= 0 or self.max_batches <= 0:
            raise ValueError("evaluation values must be positive")


@dataclass(slots=True)
class LLMConfig:
    schema_version: int
    workload_type: Literal["llm.causal"]
    mode: Literal["scratch", "lora"]
    run_dir: str
    seed: int
    dataset: DatasetConfig
    tokenizer: TokenizerConfig
    model: ModelConfig
    training: TrainingConfig
    checkpointing: CheckpointConfig
    evaluation: EvaluationConfig

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("only LLM config schema_version 1 is supported")
        if self.workload_type != "llm.causal":
            raise ValueError("workload_type must be llm.causal")
        if self.mode not in {"scratch", "lora"}:
            raise ValueError("mode must be scratch or lora")
        if self.mode == "scratch" and self.tokenizer.mode != "train_bpe":
            raise ValueError("scratch mode requires tokenizer.mode train_bpe")
        if self.mode != "scratch" and not self.model.base_model:
            raise ValueError("fine-tuning modes require model.base_model")
        if self.dataset.context_length > self.model.max_position_embeddings:
            raise ValueError("dataset.context_length cannot exceed model.max_position_embeddings")

    @property
    def output(self) -> Path:
        return Path(self.run_dir).expanduser()


def load_llm_config(path: str | Path) -> LLMConfig:
    raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    allowed = {field.name for field in fields(LLMConfig)}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"unknown LLM config keys: {', '.join(unknown)}")
    for key in ("dataset", "tokenizer", "model", "training", "checkpointing", "evaluation"):
        if not isinstance(raw.get(key), dict):
            raise ValueError(f"{key} must be an object")
    raw["dataset"] = _strict(DatasetConfig, raw["dataset"], "dataset")
    raw["tokenizer"] = _strict(TokenizerConfig, raw["tokenizer"], "tokenizer")
    raw["model"] = _strict(ModelConfig, raw["model"], "model")
    raw["training"] = _strict(TrainingConfig, raw["training"], "training")
    raw["checkpointing"] = _strict(CheckpointConfig, raw["checkpointing"], "checkpointing")
    raw["evaluation"] = _strict(EvaluationConfig, raw["evaluation"], "evaluation")
    return LLMConfig(**raw)
