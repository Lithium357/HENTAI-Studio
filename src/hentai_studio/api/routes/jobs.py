"""One global job collection, with explicit lifecycle operations."""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Query, Response
from fastapi.responses import FileResponse

from ...errors import StudioError
from ...jobs.files import ACTIVE
from ...models import JobRequest, Metrics
from ..dependencies import WorkspaceDependency
from ..pagination import paginate
from ..presenters import JobPresenter, public_state
from ..schemas import (
    ArtifactList,
    ArtifactView,
    JobCreate,
    JobResume,
    JobState,
    JobView,
    Logs,
    Page,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get(
    "",
    response_model=Page[JobView],
    operation_id="list_jobs",
    summary="List jobs with optional project and state filters",
)
def list_jobs(
    workspace: WorkspaceDependency,
    project_id: str | None = None,
    state: JobState | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
):
    jobs = sorted(
        (
            job
            for job in workspace.list_jobs(project_id)
            if state is None or public_state(job, workspace) == state
        ),
        key=lambda job: (job.created_at, job.id),
        reverse=True,
    )
    page = paginate(
        jobs,
        key=lambda job: (job.created_at, job.id),
        limit=limit,
        cursor=cursor,
        scope=f"jobs:{(project_id or '').casefold()}:{state or ''}",
    )
    presenter = JobPresenter(workspace)
    return Page(
        items=[presenter.render(job) for job in page.items],
        next_cursor=page.next_cursor,
    )


@router.post(
    "",
    response_model=JobView,
    status_code=202,
    operation_id="start_job",
    summary="Start a configured project command",
)
def start_job(request: JobCreate, workspace: WorkspaceDependency, response: Response):
    project = workspace.get_project(request.project_id)
    command = request.command
    if command is None:
        command = (
            "train"
            if "train" in project.commands
            else (next(iter(project.commands)) if len(project.commands) == 1 else None)
        )
    if command is None:
        raise StudioError(
            422, "command_required", "Choose a command: " + ", ".join(project.commands)
        )
    job = workspace.start_job(project.id, JobRequest(command=command))
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return JobPresenter(workspace).render(job)


@router.get(
    "/{job_id}",
    response_model=JobView,
    operation_id="get_job",
    summary="Read current job status and available actions",
)
def get_job(job_id: str, workspace: WorkspaceDependency):
    return JobPresenter(workspace).render(workspace.get_job(job_id))


@router.post(
    "/{job_id}/stop",
    response_model=JobView,
    responses={202: {"model": JobView}},
    operation_id="stop_job",
    summary="Stop a job; safe to retry",
)
def stop_job(job_id: str, workspace: WorkspaceDependency, response: Response):
    try:
        job = workspace.stop_job(job_id)
    except StudioError as error:
        if error.code != "job_finished":
            raise
        job = workspace.get_job(job_id)
    response.status_code = 202 if job.state in ACTIVE else 200
    return JobPresenter(workspace).render(job)


@router.post(
    "/{job_id}/resume",
    response_model=JobView,
    status_code=202,
    operation_id="resume_job",
    summary="Create a new job using a finished job's outputs",
)
def resume_job(
    job_id: str,
    workspace: WorkspaceDependency,
    response: Response,
    request: JobResume = JobResume(),
):
    source = workspace.get_job(job_id)
    job = workspace.start_job(
        source.project_id,
        JobRequest(command=request.command or source.command, resume_from=source.id),
    )
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return JobPresenter(workspace).render(job)


@router.get(
    "/{job_id}/logs",
    response_model=Logs,
    operation_id="get_job_logs",
    summary="Read console output incrementally or by tail byte count",
)
def get_logs(
    job_id: str,
    workspace: WorkspaceDependency,
    offset: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=65536)] = 65536,
    tail: Annotated[int | None, Query(ge=1, le=65536)] = None,
):
    if offset is not None and tail is not None:
        raise StudioError(
            422,
            "conflicting_log_options",
            "Use offset for incremental reads or tail for a final byte count, not both.",
        )
    page = workspace.logs(job_id, offset or 0, tail or limit, tail is not None)
    return Logs(**page.model_dump(), eof=page.next_offset >= page.size)


@router.get(
    "/{job_id}/metrics",
    response_model=Metrics,
    operation_id="get_job_metrics",
    summary="Read recent numeric training metrics",
)
def get_metrics(job_id: str, workspace: WorkspaceDependency):
    return workspace.metrics(job_id)


@router.get(
    "/{job_id}/artifacts",
    response_model=ArtifactList,
    operation_id="list_job_artifacts",
    summary="List output files with ready-to-use download URLs",
)
def list_artifacts(job_id: str, workspace: WorkspaceDependency):
    files = workspace.artifacts(job_id)
    return ArtifactList(
        items=[
            ArtifactView(
                path=item.path,
                size=item.size,
                download_url=f"/api/jobs/{job_id}/artifacts/{quote(item.path, safe='/')}",
            )
            for item in files.items
        ],
        truncated=files.truncated,
    )


@router.get(
    "/{job_id}/artifacts/{path:path}",
    response_class=FileResponse,
    operation_id="download_job_artifact",
    summary="Download a job output file",
)
def download_artifact(job_id: str, path: str, workspace: WorkspaceDependency):
    target = workspace.output_file(job_id, path)
    return FileResponse(target, filename=target.name)
