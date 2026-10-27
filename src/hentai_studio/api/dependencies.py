from typing import Annotated

from fastapi import Depends, Request

from ..jobs.workspace import Workspace


def workspace(request: Request) -> Workspace:
    return request.app.state.workspace


WorkspaceDependency = Annotated[Workspace, Depends(workspace)]
