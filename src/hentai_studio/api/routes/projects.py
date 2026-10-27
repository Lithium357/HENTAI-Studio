"""Project registration and partial edits."""

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query, Response
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from ...models import Project
from ..dependencies import WorkspaceDependency
from ..pagination import paginate
from ..schemas import Page, ProjectCreate, ProjectPatch

router = APIRouter(prefix="/projects", tags=["projects"])


def validated_project(payload):
    try:
        return Project.model_validate(payload)
    except ValidationError as error:
        raise RequestValidationError(
            [{**item, "loc": ("body", *item["loc"])} for item in error.errors()]
        ) from error


@router.get(
    "",
    response_model=Page[Project],
    operation_id="list_projects",
    summary="List registered projects",
)
def list_projects(
    workspace: WorkspaceDependency,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
):
    projects = sorted(
        workspace.list_projects(), key=lambda p: (p.id.casefold(), p.id), reverse=True
    )
    return paginate(
        projects,
        key=lambda p: (p.id.casefold(), p.id),
        limit=limit,
        cursor=cursor,
        scope="projects",
    )


@router.post(
    "",
    response_model=Project,
    status_code=201,
    operation_id="create_project",
    summary="Register an external training project",
)
def create_project(
    request: ProjectCreate, workspace: WorkspaceDependency, response: Response
):
    payload = request.model_dump()
    payload["id"] = request.id or "project-" + uuid.uuid4().hex[:12]
    payload["name"] = request.name or Path(request.root).name or payload["id"]
    project = workspace.save_project(validated_project(payload), create=True)
    response.headers["Location"] = f"/api/projects/{project.id}"
    return project


@router.get(
    "/{project_id}",
    response_model=Project,
    operation_id="get_project",
    summary="Read a project definition",
)
def get_project(project_id: str, workspace: WorkspaceDependency):
    return workspace.get_project(project_id)


@router.patch(
    "/{project_id}",
    response_model=Project,
    operation_id="update_project",
    summary="Edit only the supplied project fields",
    description="Omitted fields stay unchanged. commands and environment replace their respective maps; use {} to clear environment.",
)
def update_project(
    project_id: str, request: ProjectPatch, workspace: WorkspaceDependency
):
    # Hold the same admission lock across read/merge/write so independent patches cannot lose updates.
    return workspace.update_project(project_id, request.model_dump(exclude_unset=True))


@router.delete(
    "/{project_id}",
    status_code=204,
    operation_id="delete_project",
    summary="Unregister a project, retaining files and job history",
)
def delete_project(project_id: str, workspace: WorkspaceDependency):
    workspace.delete_project(project_id)
    return Response(status_code=204)
