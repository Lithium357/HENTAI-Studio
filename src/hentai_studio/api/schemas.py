"""Public request/response contract; persistence models are never returned as jobs."""

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import ConfigDict, Field, field_validator, model_validator

from ..llm.config import LLMProfile
from ..models import Command, Identifier, Model, Project, WorkspaceIssue

T = TypeVar("T")
JobState = Literal[
    "starting", "running", "stopping", "succeeded", "failed", "stopped", "interrupted"
]


class FieldError(Model):
    field: str
    message: str
    type: str


class ErrorDetail(Model):
    code: str
    message: str
    details: list[FieldError] = Field(default_factory=list)


class ErrorResponse(Model):
    error: ErrorDetail


class Health(Model):
    application: Literal["hentai-studio"] = "hentai-studio"
    status: Literal["ok", "degraded"] = "ok"
    version: str
    workspace: str
    free_bytes: int
    issues: list[WorkspaceIssue] = Field(default_factory=list)


class Page(Model, Generic[T]):
    items: list[T]
    next_cursor: str | None = None


class ProjectCreate(Project):
    commands: dict[Identifier, Command] = Field(
        default_factory=dict, validate_default=True, min_length=1, max_length=32
    )
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "root": "/absolute/project",
                    "commands": {
                        "train": [
                            "/absolute/project/.venv/bin/python",
                            "train.py",
                            "--output",
                            "{output_dir}",
                        ]
                    },
                }
            ]
        }
    )
    id: Identifier | None = Field(
        default=None, description="Optional human-readable ID. Generated when omitted."
    )
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
        description="Defaults to the project directory name.",
    )


class ProjectPatch(Model):
    name: str | None = None
    root: str | None = None
    commands: dict[Identifier, list[str]] | None = None
    environment: dict[str, str] | None = None
    metrics_file: str | None = None
    llm: LLMProfile | None = None

    @field_validator("*")
    @classmethod
    def reject_null(cls, value, info):
        if value is None and info.field_name != "llm":
            raise ValueError(
                "Omit this field to keep its current value; null is supported only for llm (to remove its profile)."
            )
        return value

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set:
            raise ValueError("Supply at least one project field.")
        return self


class JobCreate(Model):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"project_id": "my-project"},
                {"project_id": "my-project", "command": "evaluate"},
            ]
        }
    )
    project_id: Identifier
    command: Identifier | None = Field(
        default=None, description="Defaults to train, or the project's only command."
    )


class JobResume(Model):
    command: Identifier | None = Field(
        default=None, description="Defaults to the source job's command."
    )


class JobActions(Model):
    can_stop: bool
    can_resume: bool


class JobLinks(Model):
    self: str
    logs: str
    metrics: str
    artifacts: str
    stop: str
    resume: str


class JobView(Model):
    id: str
    project_id: str
    project_name: str
    command: str
    resume_from: str | None
    state: JobState
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    exit_code: int | None
    error: str | None
    has_live_processes: bool
    actions: JobActions
    links: JobLinks


class Logs(Model):
    text: str
    next_offset: int
    size: int
    eof: bool


class ArtifactView(Model):
    path: str
    size: int
    download_url: str


class ArtifactList(Model):
    items: list[ArtifactView]
    truncated: bool
