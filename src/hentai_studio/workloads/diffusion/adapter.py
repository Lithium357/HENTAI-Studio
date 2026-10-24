from __future__ import annotations

import json
from pathlib import Path

from scratchtag.config import load_config
from ...core.workload import CheckpointInfo, RunDescription, ValidationResult


class DiffusionAdapter:
    """Read-only bridge; legacy trainer and checkpoint layout stay unchanged."""

    workload_type = "diffusion"

    def validate_config(self, path: Path) -> ValidationResult:
        try:
            load_config(path)
            return ValidationResult(True)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            return ValidationResult(False, (str(error),))

    def describe_run(self, run_dir: Path) -> RunDescription:
        return RunDescription(run_dir.name, run_dir.name.replace("-", " ").title(), self.workload_type, run_dir, "legacy", True)

    def status(self, run_dir: Path) -> dict[str, object]:
        return {"state": "legacy", "runDir": str(run_dir), "workloadType": self.workload_type}

    def checkpoints(self, run_dir: Path) -> list[CheckpointInfo]:
        result: list[CheckpointInfo] = []
        for stage in ("vae", "diffusion"):
            for path in (run_dir / "checkpoints" / stage).glob("step-*"):
                try:
                    step = int(path.name.removeprefix("step-"))
                except ValueError:
                    continue
                size = sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
                result.append(CheckpointInfo(f"{stage}/{path.name}", step, path, size > 0, path.stat().st_mtime, size))
        return sorted(result, key=lambda item: item.modified_at, reverse=True)
