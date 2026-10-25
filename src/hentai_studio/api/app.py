import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Query, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..jobs.workspace import Workspace
from .errors import ApiError, register_error_handlers
from .middleware import RequestLimits, ResponseHeaders
from .schemas import (
    Artifacts,
    Collection,
    ErrorResponse,
    Health,
    Job,
    JobRequest,
    LogPage,
    Metrics,
    Project,
)


def create_app(workspace: Path | str) -> FastAPI:
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
        version=__version__,
        description="Standalone project registration and external training jobs. Commands run on the Studio host.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
        responses={
            code: {"model": ErrorResponse}
            for code in (400, 404, 405, 408, 409, 413, 422, 500, 503)
        },
    )
    app.state.workspace = service
    register_error_handlers(app)
    app.add_middleware(RequestLimits)
    app.add_middleware(ResponseHeaders)

    @app.get("/api/health", response_model=Health, tags=["system"])
    def health():
        return Health(
            version=__version__,
            workspace=str(service.root),
            free_bytes=shutil.disk_usage(service.root).free,
        )

    @app.get("/api/projects", response_model=Collection[Project], tags=["projects"])
    def projects():
        return Collection(items=service.list_projects())

    @app.post(
        "/api/projects", response_model=Project, status_code=201, tags=["projects"]
    )
    def register(project: Project):
        return service.save_project(project, create=True)

    @app.get("/api/projects/{project_id}", response_model=Project, tags=["projects"])
    def project(project_id: str):
        return service.get_project(project_id)

    @app.put("/api/projects/{project_id}", response_model=Project, tags=["projects"])
    def update_project(project_id: str, project: Project):
        if project.id != project_id:
            raise ApiError(
                422, "project_id_mismatch", "The body ID must match the URL."
            )
        return service.save_project(project)

    @app.delete("/api/projects/{project_id}", status_code=204, tags=["projects"])
    def delete_project(project_id: str):
        service.delete_project(project_id)
        return Response(status_code=204)

    @app.get("/api/jobs", response_model=Collection[Job], tags=["jobs"])
    def jobs(project_id: str | None = None):
        return Collection(items=service.list_jobs(project_id))

    @app.post(
        "/api/projects/{project_id}/jobs",
        response_model=Job,
        status_code=202,
        tags=["jobs"],
    )
    def start_job(project_id: str, request: JobRequest):
        return service.start_job(project_id, request)

    @app.get("/api/jobs/{job_id}", response_model=Job, tags=["jobs"])
    def job(job_id: str):
        return service.get_job(job_id)

    @app.post(
        "/api/jobs/{job_id}/stop", response_model=Job, status_code=202, tags=["jobs"]
    )
    def stop_job(job_id: str):
        return service.stop_job(job_id)

    @app.get("/api/jobs/{job_id}/logs", response_model=LogPage, tags=["jobs"])
    def logs(
        job_id: str,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=65536)] = 65536,
        tail: bool = False,
    ):
        return service.logs(job_id, offset, limit, tail)

    @app.get("/api/jobs/{job_id}/metrics", response_model=Metrics, tags=["jobs"])
    def metrics(job_id: str):
        return service.metrics(job_id)

    @app.get("/api/jobs/{job_id}/artifacts", response_model=Artifacts, tags=["jobs"])
    def artifacts(job_id: str):
        return service.artifacts(job_id)

    @app.get(
        "/api/jobs/{job_id}/artifacts/{path:path}",
        response_class=FileResponse,
        tags=["jobs"],
    )
    def download(job_id: str, path: str):
        target = service.output_file(job_id, path)
        return FileResponse(target, filename=target.name)

    assets = Path(__file__).parents[1] / "dashboard_static"
    app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(assets / "index.html", media_type="text/html")

    return app
