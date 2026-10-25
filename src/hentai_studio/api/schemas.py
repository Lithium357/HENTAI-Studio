from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

T = TypeVar("T")
Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Collection(Model, Generic[T]):
    items: list[T]


class ErrorDetail(Model):
    code: str
    message: str
    details: list[dict] = Field(default_factory=list)


class ErrorResponse(Model):
    error: ErrorDetail


class Project(Model):
    id: Identifier
    name: str = Field(min_length=1, max_length=160)
    root: str = Field(min_length=1)
    commands: dict[Identifier, list[str]] = Field(min_length=1, max_length=32)
    environment: dict[str, str] = Field(default_factory=dict)
    metrics_file: str = "metrics.jsonl"

    @field_validator("id")
    @classmethod
    def portable_id(cls, value):
        reserved = {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }
        if value.upper() in reserved:
            raise ValueError("Project ID is a reserved Windows device name.")
        return value

    @field_validator("commands")
    @classmethod
    def valid_commands(cls, commands):
        for argv in commands.values():
            if not argv or any(not part or "\0" in part for part in argv):
                raise ValueError(
                    "Commands must be non-empty argument arrays without empty or NUL arguments."
                )
        return commands

    @field_validator("environment")
    @classmethod
    def valid_environment(cls, environment):
        if any(
            not key or "=" in key or "\0" in key + value
            for key, value in environment.items()
        ):
            raise ValueError("Invalid environment variable.")
        return environment

    @field_validator("metrics_file")
    @classmethod
    def valid_metrics(cls, value):
        from pathlib import PurePosixPath, PureWindowsPath

        if (
            not value
            or PurePosixPath(value).is_absolute()
            or PureWindowsPath(value).drive
            or ".." in value.replace("\\", "/").split("/")
        ):
            raise ValueError(
                "metrics_file must be a relative path inside the job output directory."
            )
        if not value.endswith((".jsonl", ".csv")):
            raise ValueError("metrics_file must end with .jsonl or .csv.")
        return value


class JobRequest(Model):
    command: Identifier
    resume_from: Identifier | None = None


class Job(Model):
    id: Identifier
    project_id: Identifier
    command: str
    project: Project
    resume_from: str | None = None
    state: Literal[
        "starting",
        "running",
        "stopping",
        "succeeded",
        "failed",
        "stopped",
        "interrupted",
    ]
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    worker_pid: int | None = None
    worker_created: float | None = None
    error: str | None = None


class LogPage(Model):
    text: str
    next_offset: int
    size: int


class Metrics(Model):
    items: list[dict[str, float]]
    truncated: bool


class Artifact(Model):
    path: str
    size: int


class Artifacts(Model):
    items: list[Artifact]
    truncated: bool


class Health(Model):
    status: Literal["ok"] = "ok"
    version: str
    workspace: str
    free_bytes: int
