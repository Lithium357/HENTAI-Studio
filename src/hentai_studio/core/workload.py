from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ValidationResult:
    valid: bool
    messages: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RunDescription:
    run_id: str
    display_name: str
    workload_type: str
    run_dir: Path
    state: str
    legacy: bool = False


@dataclass(frozen=True, slots=True)
class CheckpointInfo:
    checkpoint_id: str
    step: int
    path: Path
    complete: bool
    modified_at: float
    size_bytes: int


class WorkloadAdapter(Protocol):
    """The dashboard-facing contract. Backends keep their own train semantics."""

    workload_type: str

    def validate_config(self, path: Path) -> ValidationResult: ...

    def describe_run(self, run_dir: Path) -> RunDescription: ...

    def status(self, run_dir: Path) -> dict[str, object]: ...

    def checkpoints(self, run_dir: Path) -> list[CheckpointInfo]: ...
