from typing import Annotated

from fastapi import Depends, Request

from .errors import ApiError
from .services.diffusion import DiffusionService
from .services.runs import RunService


def run_service(request: Request) -> RunService:
    return request.app.state.runs


def diffusion_service(request: Request) -> DiffusionService:
    service = request.app.state.diffusion
    if service is None:
        raise ApiError(503, "diffusion_not_configured", "Start Studio with a diffusion config to use this resource.")
    return service


Runs = Annotated[RunService, Depends(run_service)]
Diffusion = Annotated[DiffusionService, Depends(diffusion_service)]
