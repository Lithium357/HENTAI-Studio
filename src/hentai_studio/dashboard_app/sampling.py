from __future__ import annotations

import os
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import quote

if TYPE_CHECKING:
    from .state import DashboardState


@dataclass(frozen=True, slots=True)
class SampleOptions:
    source: Literal["current", "checkpoint"] = "current"
    run_id: str | None = None
    checkpoint_id: str | None = None
    tags: tuple[str, ...] = ()
    seed: int = 357
    steps: int = 20
    guidance: float = 5.0


@dataclass(slots=True)
class SamplingJobs:
    context: DashboardState
    sample_job: subprocess.Popen[bytes] | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    sample_started: float | None = None
    sample_finished: float | None = None
    exit_code: int | None = None
    job_status: str = "idle"

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
                "url": f"/api/diffusion/samples/{quote(path.name, safe='')}",
                "modified_at": path.stat().st_mtime,
                "size_bytes": path.stat().st_size,
            }
            for path in files[:12]
        ]

    def start(self, options: SampleOptions) -> None:
        with self.lock:
            if self.sample_job is not None and self.sample_job.poll() is None:
                raise RuntimeError("a sample is already being generated")
            tags = ",".join(options.tags)
            steps = options.steps
            guidance = options.guidance
            historical = options.source == "checkpoint"
            vae_active = (
                not historical
                and not self.context.is_sdxl_lora
                and not (self.context.run_dir / "models" / "vae").is_dir()
            )
            seed = secrets.randbits(63) if vae_active else options.seed
            selected_run: Path | None = None
            selected_checkpoint: Path | None = None
            if historical:
                selected_run, selected_checkpoint = self.context.resolve_historical_checkpoint(
                    options.run_id, options.checkpoint_id
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
            self.context.sample_dir.mkdir(parents=True, exist_ok=True)
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
            self.sample_finished = None
            self.exit_code = None
            self.job_status = "running"

    def status(self) -> dict[str, object]:
        with self.lock:
            if self.sample_job is not None:
                code = self.sample_job.poll()
                if code is not None:
                    self.exit_code = code
                    self.job_status = "succeeded" if code == 0 else "failed"
                    self.sample_finished = time.time()
                    self.sample_job = None
            return {
                "status": self.job_status,
                "started_at": self.sample_started,
                "finished_at": self.sample_finished,
                "exit_code": self.exit_code,
            }

    def is_running(self) -> bool:
        return self.status()["status"] == "running"
