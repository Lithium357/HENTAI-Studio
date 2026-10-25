from __future__ import annotations

from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")
RunId = Annotated[str, Field(pattern=r"^(diffusion|llm\.causal):[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]


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


class Health(Model):
    status: Literal["ok"] = "ok"
    version: str
    diffusion_configured: bool


class DiskUsage(Model):
    free_bytes: int
    total_bytes: int


class Storage(DiskUsage):
    root: str


class Run(Model):
    id: RunId
    display_name: str
    workload_type: Literal["diffusion", "llm.causal"]
    state: str


class Checkpoint(Model):
    id: str
    step: int
    complete: bool
    modified_at: float
    size_bytes: int


class LossPoint(Model):
    step: float
    loss: float
    eval_loss: float | None = None
    total_steps: int | None = None
    seconds_per_step: float | None = None
    tokens_per_second: float | None = None
    tokens_seen: int | None = None


class Hardware(Model):
    available: bool = False
    cpu_usage_pct: float | None = None
    cpu_ram_bytes: int | None = None
    cpu_ram_total_bytes: int | None = None
    cpu_temp_c: float | None = None
    cpu_package_power_w: float | None = None
    gpu_usage_pct: float | None = None
    gpu_vram_bytes: int | None = None
    gpu_vram_total_bytes: int | None = None
    gpu_temp_c: float | None = None
    gpu_hotspot_c: float | None = None
    gpu_fan_rpm: float | None = None
    gpu_board_power_w: float | None = None
    workload_power_w: float | None = None
    energy_kwh: float | None = None
    scope_note: str = ""


class LanguageProgress(Model):
    step: int | None = None
    total_steps: int | None = None
    loss: float | None = None
    eval_loss: float | None = None
    seconds_per_step: float | None = None
    tokens_per_second: float | None = None
    tokens_seen: int | None = None


class RunCapabilities(Model):
    chat: bool = False


class RunDetail(Run):
    pids: list[int] = Field(default_factory=list)
    progress: LanguageProgress = Field(default_factory=LanguageProgress)
    loss_history: list[LossPoint] = Field(default_factory=list)
    hardware: Hardware = Field(default_factory=Hardware)
    capabilities: RunCapabilities = Field(default_factory=RunCapabilities)


class ChatMessage(Model):
    role: Literal["user", "assistant", "system"]
    content: Annotated[str, Field(strict=True, min_length=1, max_length=32768)]


class ChatRequest(Model):
    messages: Annotated[list[ChatMessage], Field(min_length=1, max_length=48)]
    max_new_tokens: Annotated[int, Field(strict=True, ge=1, le=256)] = 128


class ChatCompletion(Model):
    message: ChatMessage
    checkpoint_id: str
    device: Literal["cpu"] = "cpu"


class SampleRequest(Model):
    source: Literal["current", "checkpoint"] = "current"
    run_id: Annotated[str | None, Field(pattern=r"^diffusion:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")] = None
    checkpoint_id: Annotated[str | None, Field(pattern=r"^step-\d+$")] = None
    tags: list[Annotated[str, Field(strict=True, min_length=1, max_length=128)]] = Field(default_factory=list, max_length=128)
    seed: Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)] = 357
    steps: Annotated[int, Field(strict=True, ge=5, le=60)] = 20
    guidance: Annotated[float, Field(strict=True, ge=1, le=12)] = 5

    @model_validator(mode="after")
    def validate_selection(self):
        if self.source == "checkpoint" and (not self.run_id or not self.checkpoint_id):
            raise ValueError("checkpoint sampling requires run_id and checkpoint_id")
        if self.source == "current" and (self.run_id is not None or self.checkpoint_id is not None):
            raise ValueError("current sampling must not specify a historical run or checkpoint")
        return self


class SamplingStatus(Model):
    status: Literal["idle", "running", "succeeded", "failed"]
    started_at: float | None = None
    finished_at: float | None = None
    exit_code: int | None = None


class Sample(Model):
    name: str
    url: str
    modified_at: float
    size_bytes: int


class Stage(Model):
    step: int
    total: int
    percent: float


class Stages(Model):
    active: Literal["vae", "diffusion"]
    vae: Stage
    diffusion: Stage
    overall: Stage


class DiffusionProgress(Model):
    step: int | None = None
    total: int | None = None
    percent: float | None = None
    loss: float | None = None
    seconds_per_step: float | None = None
    pace_window: int | None = None
    images_per_second: float | None = None
    eta_seconds: float | None = None
    log: str | None = None
    updated_at: float | None = None


class ActiveCheckpoint(Model):
    name: str
    step: int
    size_bytes: int
    modified_at: float


class CatalogCheckpoint(Model):
    id: str
    step: int
    modified_at: float


class CatalogRun(Model):
    id: RunId
    display_name: str
    resolution_px: int
    checkpoints: list[CatalogCheckpoint]


class DiffusionStatus(Model):
    running: bool
    architecture_label: str
    pids: list[int]
    watchdog_running: bool
    paused: bool
    progress: DiffusionProgress
    stages: Stages
    loss_history: list[LossPoint]
    checkpoints: list[ActiveCheckpoint]
    sampling: SamplingStatus
    checkpoint_every: int
    disk: DiskUsage
    hardware: Hardware
    server_time: float


class TrainingCommandResult(Model):
    command: Literal["pause", "resume", "promote_vae"]
    status: Literal["requested"] = "requested"
