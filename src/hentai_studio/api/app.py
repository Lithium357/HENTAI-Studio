from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from .errors import register_error_handlers
from .middleware import RequestLimits, ResponseHeaders
from .routes import diffusion, runs, system
from .schemas import ErrorResponse
from .services.diffusion import DiffusionService
from .services.runs import RunService


def create_app(runs_service: RunService, diffusion_service: DiffusionService | None = None) -> FastAPI:
    app = FastAPI(
        title="HENTAI Studio API",
        description="Observe registered runs and explicitly control the configured diffusion project. All JSON fields use snake_case.",
        version=__version__,
        docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json",
        responses={code: {"model": ErrorResponse} for code in (400, 404, 405, 408, 409, 413, 422, 500, 503)},
    )
    app.state.runs = runs_service
    app.state.diffusion = diffusion_service
    app.include_router(system.router, prefix="/api")
    app.include_router(runs.router, prefix="/api")
    app.include_router(diffusion.router, prefix="/api")
    register_error_handlers(app)
    app.add_middleware(RequestLimits)
    app.add_middleware(ResponseHeaders)

    if diffusion_service is not None:
        assets = Path(__file__).parents[1] / "dashboard_static"
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/", include_in_schema=False)
        def dashboard():
            return FileResponse(assets / "index.html", media_type="text/html")

    return app
