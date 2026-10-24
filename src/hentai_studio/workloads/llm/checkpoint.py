"""Read-only integrity checks for local LoRA checkpoints."""
from __future__ import annotations

import json
from pathlib import Path


WEIGHTS_REQUIRED = ("adapter/adapter_config.json", "adapter/adapter_model.safetensors", "metadata.json")
RESUME_REQUIRED = (*WEIGHTS_REQUIRED, "optimizer.pt", "rng-state.pt", "trainer-state.json")


def _report(path: Path, required: tuple[str, ...], expected_step: int) -> dict[str, object]:
    missing = [item for item in required if not (path / item).is_file()]
    metadata: dict[str, object] = {}
    if not missing:
        try:
            metadata = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            missing.append("metadata.json (invalid)")
    if not missing and metadata.get("step") != expected_step:
        missing.append(f"metadata step does not match requested step {expected_step}")
    return {"path": str(path), "complete": not missing, "missing": missing, "step": metadata.get("step"), "baseModel": metadata.get("base_model")}


def verify_lora_checkpoint(run_dir: str | Path, step: int) -> dict[str, object]:
    root = Path(run_dir)
    weights = _report(root / "checkpoints" / "weights" / f"step-{step}", WEIGHTS_REQUIRED, step)
    resume = _report(root / "checkpoints" / "resume" / f"step-{step}", RESUME_REQUIRED, step)
    if resume["complete"]:
        resume_path = Path(str(resume["path"]))
        resume["rngState"] = (resume_path / "rng-state.pt").is_file()
    return {"step": step, "weights": weights, "resume": resume, "complete": bool(weights["complete"] and resume["complete"])}
