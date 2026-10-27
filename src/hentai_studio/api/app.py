import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..jobs.workspace import Workspace
from .errors import register_error_handlers
from .middleware import LocalRequests, RequestLimits, ResponseHeaders
from .routes import jobs, projects
from .schemas import ErrorResponse, Health


def create_app(workspace: Path | str, *, host: str = "127.0.0.1") -> FastAPI:
    service = Workspace(Path(workspace))

    @asynccontextmanager
    async def lifespan(app):
        service.acquire()
        try:
            yield
        finally:
            service.close()

    app = FastAPI(
        title="HENTAI Studio API",
        openapi_tags=[
            {
                "name": "system",
                "description": "Service identity and workspace diagnostics.",
            },
            {
                "name": "projects",
                "description": "Register a project once; edit individual fields later.",
            },
            {
                "name": "jobs",
                "description": "Start, observe, stop and resume external commands.",
            },
        ],
        version=__version__,
        description="Standalone project registration and external training jobs. Commands run on the Studio host.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
        responses={
            code: {"model": ErrorResponse}
            for code in (400, 403, 404, 405, 408, 409, 413, 422, 500, 503)
        },
    )
    app.state.workspace = service
    register_error_handlers(app)
    app.add_middleware(RequestLimits)
    app.add_middleware(LocalRequests, hosts=["localhost", "127.0.0.1", "::1", host])
    app.add_middleware(ResponseHeaders)

    @app.get("/api/health", response_model=Health, tags=["system"])
    def health():
        issues = service.issues()
        return Health(
            status="degraded" if issues else "ok",
            issues=issues,
            version=__version__,
            workspace=str(service.root),
            free_bytes=shutil.disk_usage(service.root).free,
        )

    app.include_router(projects.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")

    assets = Path(__file__).parents[1] / "dashboard_static"
    app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(assets / "index.html", media_type="text/html")

    return app
