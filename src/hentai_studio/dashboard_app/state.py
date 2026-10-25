from __future__ import annotations

import json
import shutil
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .checkpoints import CheckpointCatalog
from .controls import TrainingControls
from .processes import TrainerProcesses
from .progress import ProgressReader
from .sampling import SamplingJobs
from .telemetry import Telemetry


@dataclass(slots=True)
class DashboardState:
    """Application facade composing services for one configured diffusion run."""

    project: Path
    config: Path
    sample_dir: Path
    telemetry: Telemetry = field(init=False, repr=False)
    process_monitor: TrainerProcesses = field(init=False, repr=False)
    progress_reader: ProgressReader = field(init=False, repr=False)
    catalog: CheckpointCatalog = field(init=False, repr=False)
    controls: TrainingControls = field(init=False, repr=False)
    sampling: SamplingJobs = field(init=False, repr=False)
    control_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def __post_init__(self) -> None:
        self.project = self.project.resolve()
        self.config = (self.project / self.config).resolve()
        self.sample_dir = (self.project / self.sample_dir).resolve()
        self.telemetry = Telemetry(self)
        self.process_monitor = TrainerProcesses(self)
        self.progress_reader = ProgressReader(self)
        self.catalog = CheckpointCatalog(self)
        self.controls = TrainingControls(self)
        self.sampling = SamplingJobs(self)

    @property
    def run_dir(self) -> Path:
        raw = json.loads(self.config.read_text(encoding="utf-8"))
        run_dir = Path(raw["run_dir"])
        return run_dir if run_dir.is_absolute() else self.project / run_dir

    @property
    def raw_config(self) -> dict[str, object]:
        return json.loads(self.config.read_text(encoding="utf-8"))

    @property
    def is_sdxl_lora(self) -> bool:
        return str(self.raw_config.get("architecture", "")).startswith("sdxl_lora")

    @property
    def is_x4_latent(self) -> bool:
        return int(self.raw_config.get("latent_downsample_factor", 8)) == 4

    @property
    def training_name(self) -> str:
        if self.is_sdxl_lora:
            return "sdxl"
        return "scratch-v3-x4" if self.is_x4_latent else "scratch-v2"

    @property
    def pause_file(self) -> Path:
        return self.run_dir / "PAUSED"

    def snapshot(self) -> dict[str, object]:
        progress, history = self.progress()
        raw = self.raw_config
        vae_total = int(raw.get("vae_max_steps", 0))
        diffusion_total = int(raw.get("max_steps", 0))
        vae_complete = (self.run_dir / "models" / "vae").is_dir()
        active_stage = "diffusion" if vae_complete else "vae"
        active_step = int(progress.get("step", 0))
        vae_step = vae_total if vae_complete else min(active_step, vae_total)
        diffusion_step = min(active_step, diffusion_total) if vae_complete else 0
        overall_total = vae_total + diffusion_total
        stages = {
            "active": active_stage,
            "vae": {
                "step": vae_step,
                "total": vae_total,
                "percent": vae_step / vae_total * 100 if vae_total else 0,
            },
            "diffusion": {
                "step": diffusion_step,
                "total": diffusion_total,
                "percent": diffusion_step / diffusion_total * 100 if diffusion_total else 0,
            },
            "overall": {
                "step": vae_step + diffusion_step,
                "total": overall_total,
                "percent": (vae_step + diffusion_step) / overall_total * 100 if overall_total else 0,
            },
        }
        usage = shutil.disk_usage(self.project)
        sampling = self.sampling.is_running()
        pids = self.trainer_pids()
        return {
            "running": bool(pids),
            "architectureLabel": "SCRATCH V3 / 4X LATENT" if self.is_x4_latent else "SCRATCH V2 / 8X LATENT",
            "pids": pids,
            "watchdogRunning": bool(self.watchdog_pids()),
            "paused": self.pause_file.exists(),
            "progress": progress,
            "stages": stages,
            "lossHistory": history,
            "checkpoints": self.checkpoints(),
            "checkpointCatalog": self.checkpoint_catalog(),
            "samples": self.samples(),
            "sampling": sampling,
            "sampleStarted": self.sampling.sample_started,
            "checkpointEvery": int(self.raw_config.get("checkpoint_every", 1000)),
            "disk": {"free": usage.free, "total": usage.total},
            "hardware": self.hardware_metrics(pids),
            "serverTime": time.time(),
        }

    def trainer_pids(self) -> list[int]:
        return self.process_monitor.trainer_pids()

    def watchdog_pids(self) -> list[int]:
        return self.process_monitor.watchdog_pids()

    def hardware_metrics(self, roots: list[int]) -> dict[str, object]:
        return self.telemetry.hardware_metrics(roots)

    def progress(self) -> tuple[dict[str, object], list[dict[str, float]]]:
        return self.progress_reader.progress()

    def checkpoints(self) -> list[dict[str, object]]:
        return self.catalog.checkpoints()

    def checkpoint_catalog(self) -> list[dict[str, object]]:
        return self.catalog.checkpoint_catalog()

    def resolve_historical_checkpoint(self, run_id: str, checkpoint_id: str) -> tuple[Path, Path]:
        return self.catalog.resolve_historical_checkpoint(run_id, checkpoint_id)

    def samples(self) -> list[dict[str, object]]:
        return self.sampling.samples()

    def generate_sample(self, payload: dict[str, object]) -> None:
        return self.sampling.generate_sample(payload)

    def stop(self) -> None:
        with self.control_lock:
            self.controls.stop()

    def resume(self) -> None:
        with self.control_lock:
            self.controls.resume()

    def start_diffusion(self) -> None:
        with self.control_lock:
            self.controls.start_diffusion()
