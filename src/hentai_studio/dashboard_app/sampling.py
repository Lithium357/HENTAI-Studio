from __future__ import annotations

import os
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import DashboardState


@dataclass(slots=True)
class SamplingJobs:
    context: DashboardState
    sample_job: subprocess.Popen[bytes] | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    sample_started: float | None = None

    def samples(self) -> list[dict[str, object]]:
        self.context.sample_dir.mkdir(parents=True, exist_ok=True)
        files = list(self.context.sample_dir.glob("*.png"))
        now = time.time()
        # WSL can briefly inherit a bad clock around a Windows reboot. Repair
        # future-dated gallery files so they cannot permanently hide new samples.
        for path in files:
            if path.stat().st_mtime > now + 60:
                os.utime(path, (now - 86_400, now - 86_400))
        files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return [
            {
                "name": path.name,
                "url": f"/samples/{path.name}",
                "modifiedAt": path.stat().st_mtime,
                "size": path.stat().st_size,
            }
            for path in files[:12]
        ]

    def generate_sample(self, payload: dict[str, object]) -> None:
        with self.lock:
            if self.sample_job is not None and self.sample_job.poll() is None:
                raise RuntimeError("a sample is already being generated")
            tags = str(payload.get("tags", "1girl,solo,looking_at_viewer,smile,portrait"))
            steps = min(60, max(5, int(payload.get("steps", 20))))
            guidance = min(12.0, max(1.0, float(payload.get("guidance", 5.0))))
            historical = str(payload.get("source", "current")) == "historical"
            vae_active = (
                not historical
                and not self.context.is_sdxl_lora
                and not (self.context.run_dir / "models" / "vae").is_dir()
            )
            seed = secrets.randbits(63) if vae_active else int(payload.get("seed", 357))
            selected_run: Path | None = None
            selected_checkpoint: Path | None = None
            if historical:
                selected_run, selected_checkpoint = self.context.resolve_historical_checkpoint(
                    str(payload.get("runId", "")), str(payload.get("checkpointId", ""))
                )
                checkpoint_step = int(selected_checkpoint.name.split("-")[-1])
            else:
                checkpoints = self.context.checkpoints()
                checkpoint_step = int(checkpoints[0]["step"]) if checkpoints else 0
            prefix = selected_run.name if selected_run else ("vae" if vae_active else "step")
            filename = f"{prefix}-{checkpoint_step}_seed-{seed}_{int(time.time())}.png"
            output = self.context.sample_dir / filename
            env = os.environ.copy()
            env["OMP_NUM_THREADS"] = "6"
            if vae_active:
                command = [
                    sys.executable,
                    "-m",
                    "scratchtag.tools.vae_snapshot",
                    "--config",
                    str(self.context.config),
                    "--output",
                    str(output),
                    "--seed",
                    str(seed),
                    "--size",
                    "1080",
                ]
            else:
                selected_config = selected_run / "config.json" if selected_run else self.context.config
                command = [
                    sys.executable,
                    "-m",
                    ("scratchtag.tools.sdxl_checkpoint_sample" if self.context.is_sdxl_lora else "scratchtag.tools.diffusion_checkpoint_sample"),
                    "--config",
                    str(selected_config),
                    "--tags",
                    tags,
                    "--output",
                    str(output),
                    "--steps",
                    str(steps),
                    "--guidance",
                    str(guidance),
                    "--seed",
                    str(seed),
                ]
                if selected_checkpoint is not None:
                    command.extend(["--checkpoint", str(selected_checkpoint)])
            self.sample_job = subprocess.Popen(
                command,
                cwd=self.context.project,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
            )
            self.sample_started = time.time()

    def is_running(self) -> bool:
        with self.lock:
            if self.sample_job is not None and self.sample_job.poll() is not None:
                self.sample_job = None
                self.sample_started = None
            return self.sample_job is not None
