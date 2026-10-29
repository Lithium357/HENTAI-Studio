from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import Field, field_validator, model_validator

from .llm.config import LLMProfile
from .models_base import Model

T = TypeVar("T")
Command = Annotated[list[str], Field(min_length=1)]
Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")]


class Collection(Model, Generic[T]):
    items: list[T]


class Project(Model):
    id: Identifier
    name: str = Field(min_length=1, max_length=160)
    root: str = Field(min_length=1)
    commands: dict[Identifier, Command] = Field(min_length=1, max_length=32)
    environment: dict[str, str] = Field(default_factory=dict)
    metrics_file: str = "metrics.jsonl"
    llm: LLMProfile | None = None

    @model_validator(mode="before")
    @classmethod
    def llm_command(cls, value):
        if isinstance(value, dict) and value.get("llm") is not None:
            import json
            from pathlib import Path

            profile = LLMProfile.model_validate(value["llm"])
            training = profile.model_dump(exclude={"python"})
            # Only the generated train command is owned by the LLM profile.
            value = dict(value)
            commands = value.get("commands") or {}
            if not isinstance(commands, dict):
                raise ValueError(
                    "commands must be a JSON object of named argument arrays."
                )
            value["commands"] = commands | {
                "train": [
                    profile.python,
                    "-u",
                    str(Path(__file__).parent / "llm" / "train.py"),
                    "--config-json",
                    json.dumps(training),
                ]
            }
            value["metrics_file"] = "metrics.jsonl"
        return value

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value):
        if value is None:
            return value
        if not value.strip():
            raise ValueError("Project name cannot be blank.")
        return value.strip()

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
        if value is not None and value.upper() in reserved:
            raise ValueError("Project ID is a reserved Windows device name.")
        return value

    @field_validator("commands")
    @classmethod
    def valid_commands(cls, commands):
        for argv in commands.values():
            if not argv or any("\0" in part for part in argv) or not argv[0].strip():
                raise ValueError(
                    "Commands require a non-empty executable and arguments without NUL bytes."
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
            or "\0" in value
            or ":" in value
            or PurePosixPath(value).is_absolute()
            or PureWindowsPath(value).root
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
    command: Identifier
    project: Project
    resume_from: Identifier | None = None
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
    trainer_pid: int | None = None
    trainer_created: float | None = None
    worker_pid: int | None = None
    worker_created: float | None = None
    error: str | None = None
    has_live_processes: bool = False

    @field_validator("created_at", "started_at", "finished_at")
    @classmethod
    def valid_timestamp(cls, value):
        if value is not None:
            datetime.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def consistent_snapshot(self):
        if (
            self.project_id != self.project.id
            or self.command not in self.project.commands
        ):
            raise ValueError(
                "Job identity/command does not match its project snapshot."
            )
        return self


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


class WorkspaceIssue(Model):
    resource: str
    message: str


class ProcessIdentity(Model):
    pid: int = Field(gt=0)
    created: float = Field(gt=0)
