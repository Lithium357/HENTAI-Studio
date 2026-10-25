from typing import Literal

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse

from ...dashboard_app.sampling import SampleOptions
from ..dependencies import Diffusion
from ..schemas import CatalogRun, Collection, DiffusionStatus, Sample, SampleRequest, SamplingStatus, TrainingCommandResult

router = APIRouter(prefix="/diffusion", tags=["Configured diffusion project"])


@router.get("/status", response_model=DiffusionStatus)
def status(service: Diffusion):
    """Observe the configured trainer, active checkpoints, telemetry, and sampling job."""
    return service.get_status()


@router.get("/checkpoints", response_model=Collection[CatalogRun])
def checkpoints(service: Diffusion):
    """Browse historical runs with diffusion checkpoints that can be sampled."""
    return Collection(items=service.list_checkpoints())


@router.get("/samples", response_model=Collection[Sample])
def samples(service: Diffusion):
    """List the newest generated images."""
    return Collection(items=service.list_samples())


@router.post("/samples", response_model=SamplingStatus, status_code=202)
def create_sample(body: SampleRequest, response: Response, service: Diffusion):
    """Start the single CPU sampling job. Conflicts return 409; poll /diffusion/sampling."""
    options = SampleOptions(**{
        **body.model_dump(), "tags": tuple(body.tags),
        "run_id": body.run_id.removeprefix("diffusion:") if body.run_id else None,
    })
    result = service.start_sample(options)
    response.headers["Location"] = "/api/diffusion/sampling"
    return result


@router.get("/sampling", response_model=SamplingStatus)
def sampling(service: Diffusion):
    """Read the last sampling job, including success or failure after it exits."""
    return service.get_sampling()


@router.get("/samples/{name}", response_class=FileResponse, responses={200: {"content": {"image/png": {}}}})
def sample_image(name: str, service: Diffusion):
    """Download a gallery image by its exact filename."""
    return FileResponse(service.sample_file(name), media_type="image/png")


@router.post("/training/pause", response_model=TrainingCommandResult, status_code=202)
def pause_training(service: Diffusion):
    """Mark this run paused and signal only its trainers and workers."""
    return service.pause_training()


@router.post("/training/resume", response_model=TrainingCommandResult, status_code=202)
def resume_training(service: Diffusion):
    """Request watchdog startup or remove the pause marker from an existing watchdog."""
    return service.resume_training()


@router.post("/training/promote-vae", response_model=TrainingCommandResult, status_code=202)
def promote_vae(service: Diffusion):
    """Promote the latest safe VAE checkpoint and request diffuser startup."""
    return service.promote_vae()


@router.get("/progress/{stage}.csv", response_class=FileResponse, responses={200: {"content": {"text/csv": {}}}})
def progress_log(stage: Literal["vae", "diffusion"], service: Diffusion):
    """Download the configured run's VAE or diffusion training log."""
    return FileResponse(service.progress_file(stage), media_type="text/csv", filename=f"{stage}-progress.csv")
