"""Local scratch-model training configuration; no ML imports."""

from typing import Literal

from pydantic import Field, field_validator

from ..models_base import Model


class LLMProfile(Model):
    python: str = Field(default="python", min_length=1, max_length=4096)
    model: str = Field(
        min_length=1,
        max_length=4096,
        description="Local directory containing a Transformers config.json. Weights are initialized from scratch.",
    )
    tokenizer: str = Field(
        min_length=1, max_length=4096, description="Local tokenizer directory."
    )
    dataset: str = Field(
        min_length=1,
        max_length=4096,
        description="Local JSONL dataset: text or messages records.",
    )
    max_length: int = Field(default=1024, ge=16, le=131072)
    batch_size: int = Field(default=1, ge=1, le=1024)
    gradient_accumulation: int = Field(default=8, ge=1, le=65536)
    learning_rate: float = Field(default=0.0003, gt=0, le=1)
    epochs: float = Field(default=1, gt=0, le=10000)
    max_steps: int = Field(default=-1, ge=-1, le=100000000)
    save_steps: int = Field(default=100, ge=1)
    precision: Literal["fp32", "bf16", "fp16"] = "fp32"
    gradient_checkpointing: bool = True
    seed: int = Field(default=42, ge=0, le=4294967295)

    @field_validator("python", "model", "tokenizer", "dataset")
    @classmethod
    def nonblank(cls, value):
        if not value.strip() or "\0" in value:
            raise ValueError("Supply a non-blank value without NUL bytes.")
        return value.strip()

    @field_validator("max_steps")
    @classmethod
    def valid_steps(cls, value):
        if value == 0:
            raise ValueError(
                "Use -1 for epoch-based training or a positive step count."
            )
        return value
