from typing import Literal

from pydantic import Field

from ..models import Model, WorkspaceIssue


class ErrorDetail(Model):
    code: str
    message: str
    details: list[dict] = Field(default_factory=list)


class ErrorResponse(Model):
    error: ErrorDetail


class Health(Model):
    application: Literal["hentai-studio"] = "hentai-studio"
    status: Literal["ok", "degraded"] = "ok"
    version: str
    workspace: str
    free_bytes: int
    issues: list[WorkspaceIssue] = Field(default_factory=list)
