from pathlib import Path
from typing import Literal

from ...dashboard_app.sampling import SampleOptions
from ...dashboard_app.state import DashboardState
from ..errors import ApiError
from ..schemas import CatalogRun, DiffusionStatus, Sample, SamplingStatus, TrainingCommandResult


class DiffusionService:
    """Operate the single diffusion project selected when Studio starts."""

    def __init__(self, state: DashboardState):
        self.state = state

    def get_status(self) -> DiffusionStatus:
        raw = self.state.snapshot()
        raw.pop("sample_started", None)
        raw["sampling"] = self.get_sampling()
        return DiffusionStatus.model_validate(raw)

    def list_checkpoints(self) -> list[CatalogRun]:
        return [CatalogRun(id=f"diffusion:{item['id']}", display_name=item["label"],
                           resolution_px=item["resolution"], checkpoints=item["checkpoints"])
                for item in self.state.checkpoint_catalog()]

    def list_samples(self) -> list[Sample]:
        return [Sample.model_validate(item) for item in self.state.samples()]

    def get_sampling(self) -> SamplingStatus:
        return SamplingStatus.model_validate(self.state.sampling.status())

    def start_sample(self, options: SampleOptions) -> SamplingStatus:
        if options.source == "current" and not self.state.checkpoints():
            raise ApiError(409, "checkpoint_unavailable", "The current run has no checkpoint to sample yet.")
        try:
            self.state.start_sample(options)
        except (ValueError, RuntimeError) as error:
            raise ApiError(409, "sampling_conflict", str(error)) from error
        except OSError as error:
            raise ApiError(503, "sampling_unavailable", f"Cannot start the sampler: {error}") from error
        return self.get_sampling()

    def pause_training(self) -> TrainingCommandResult:
        return self._command("pause", self.state.stop)

    def resume_training(self) -> TrainingCommandResult:
        return self._command("resume", self.state.resume)

    def promote_vae(self) -> TrainingCommandResult:
        return self._command("promote_vae", self.state.start_diffusion)

    @staticmethod
    def _command(name, operation) -> TrainingCommandResult:
        try:
            operation()
        except (ValueError, RuntimeError) as error:
            raise ApiError(409, "training_conflict", str(error)) from error
        except OSError as error:
            raise ApiError(503, "engine_unavailable", f"Cannot execute the training command: {error}") from error
        return TrainingCommandResult(command=name)

    def sample_file(self, name: str) -> Path:
        target = (self.state.sample_dir / name).resolve()
        if target.parent != self.state.sample_dir.resolve() or target.suffix.lower() != ".png" or not target.is_file():
            raise ApiError(404, "sample_not_found", "The sample image was not found.")
        return target

    def progress_file(self, stage: Literal["vae", "diffusion"]) -> Path:
        target = self.state.run_dir / "progress" / ("vae.csv" if stage == "vae" else "diffuser.csv")
        if not target.is_file():
            raise ApiError(404, "progress_not_found", "The progress log is not available yet.")
        return target
