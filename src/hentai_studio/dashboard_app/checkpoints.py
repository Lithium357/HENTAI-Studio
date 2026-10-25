from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import DashboardState


@dataclass(slots=True)
class CheckpointCatalog:
    context: DashboardState

    def checkpoints(self) -> list[dict[str, object]]:
        if self.context.is_sdxl_lora:
            root = self.context.run_dir
        else:
            diffusion_root = self.context.run_dir / "checkpoints" / "diffusion"
            vae_root = self.context.run_dir / "checkpoints" / "vae"
            root = diffusion_root if (self.context.run_dir / "models" / "vae").is_dir() else vae_root
        pattern = "checkpoint-*" if self.context.is_sdxl_lora else "step-*"
        result: list[dict[str, object]] = []
        candidates = (path for path in root.glob(pattern) if path.is_dir() and path.name.split("-")[-1].isdigit())
        for path in sorted(candidates, key=lambda item: int(item.name.split("-")[-1]), reverse=True):
            size = sum(file.stat().st_size for file in path.rglob("*") if file.is_file())
            result.append(
                {
                    "name": path.name,
                    "step": int(path.name.split("-")[-1]),
                    "size": size,
                    "modifiedAt": path.stat().st_mtime,
                }
            )
        return result[:8]

    def checkpoint_catalog(self) -> list[dict[str, object]]:
        runs_root = (self.context.project / "runs").resolve()
        result: list[dict[str, object]] = []
        if not runs_root.is_dir():
            return result
        for run_dir in sorted(runs_root.iterdir(), key=lambda path: path.name):
            config_path = run_dir / "config.json"
            checkpoint_root = run_dir / "checkpoints" / "diffusion"
            if not config_path.is_file() or not checkpoint_root.is_dir():
                continue
            try:
                run_config = json.loads(config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            checkpoints: list[dict[str, object]] = []
            for checkpoint in sorted(
                (path for path in checkpoint_root.glob("step-*") if re.fullmatch(r"step-\d+", path.name)),
                key=lambda path: int(path.name.split("-")[-1]),
                reverse=True,
            ):
                complete = (
                    (checkpoint / "unet" / "config.json").is_file()
                    and any((checkpoint / "unet").glob("*.safetensors"))
                    and (checkpoint / "text_encoder.safetensors").is_file()
                    and (run_dir / "models" / "vae" / "config.json").is_file()
                    and (run_dir / "vocab.json").is_file()
                )
                if complete:
                    checkpoints.append(
                        {
                            "id": checkpoint.name,
                            "step": int(checkpoint.name.split("-")[-1]),
                            "modifiedAt": checkpoint.stat().st_mtime,
                        }
                    )
            if checkpoints:
                result.append(
                    {
                        "id": run_dir.name,
                        "label": run_dir.name.replace("-", " ").title(),
                        "resolution": int(run_config.get("resolution", 0)),
                        "checkpoints": checkpoints,
                    }
                )
        result.sort(
            key=lambda run: max(float(item["modifiedAt"]) for item in run["checkpoints"]),
            reverse=True,
        )
        return result

    def resolve_historical_checkpoint(self, run_id: str, checkpoint_id: str) -> tuple[Path, Path]:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", run_id) or not re.fullmatch(r"step-\d+", checkpoint_id):
            raise RuntimeError("invalid historical checkpoint selection")
        run_dir = (self.context.project / "runs" / run_id).resolve()
        checkpoint = (run_dir / "checkpoints" / "diffusion" / checkpoint_id).resolve()
        runs_root = (self.context.project / "runs").resolve()
        if not run_dir.is_relative_to(runs_root) or not checkpoint.is_relative_to(run_dir):
            raise RuntimeError("checkpoint selection escaped the runs directory")
        valid = any(
            run["id"] == run_id
            and any(item["id"] == checkpoint_id for item in run["checkpoints"])
            for run in self.checkpoint_catalog()
        )
        if not valid:
            raise RuntimeError("the selected diffusion checkpoint is missing or incomplete")
        return run_dir, checkpoint
