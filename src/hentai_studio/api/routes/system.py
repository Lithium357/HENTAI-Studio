from fastapi import APIRouter, Request

from ... import __version__
from ..dependencies import Runs
from ..schemas import Health, Storage

router = APIRouter(tags=["System"])


@router.get("/health", response_model=Health)
def health(request: Request):
    """Report availability without reading runs, datasets, or models."""
    return Health(version=__version__, diffusion_configured=request.app.state.diffusion is not None)


@router.get("/storage", response_model=Storage)
def storage(service: Runs):
    """Inspect free space at the configured bulk-storage root."""
    return service.get_storage()
