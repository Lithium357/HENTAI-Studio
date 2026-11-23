"""Local checkpoint chat; no remote inference providers."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import Field, model_validator

from ...llm.checkpoints import CheckpointSelection, latest_checkpoint
from ...models import Identifier, Model

router = APIRouter(prefix="/projects/{project_id}/chat", tags=["llm"])


class ChatLoad(Model):
    checkpoint: str = Field(min_length=1, max_length=4096)
    job_id: Identifier | None = None
    tokenizer: str = Field(default="", max_length=4096)
    device: Literal["cpu", "cuda"] = "cpu"


class ChatStatus(Model):
    loaded: bool
    busy: bool
    checkpoint: str | None
    device: str | None


class ChatLoadLatest(Model):
    job_id: Identifier | None = None
    tokenizer: str = Field(default="", max_length=4096)
    device: Literal["cpu", "cuda"] = "cpu"
    replace: bool = True


class ChatLatestStatus(ChatStatus):
    selection: CheckpointSelection


class Message(Model):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=8192)


class ChatCompletion(Model):
    messages: list[Message] = Field(min_length=1, max_length=64)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=128, ge=1, le=2048)

    @model_validator(mode="after")
    def bounded_conversation(self):
        if sum(len(m.content) for m in self.messages) > 48000:
            raise ValueError("Conversation is too long. Clear it before continuing.")
        if self.messages[-1].role != "user":
            raise ValueError("The last message must be from the user.")
        return self


class ChatReply(Model):
    content: str
    tokens: int


@router.get("", response_model=ChatStatus, operation_id="get_chat_status")
def status(project_id: str, request: Request):
    return request.app.state.chat.status(project_id)


@router.post("/load", response_model=ChatStatus, operation_id="load_chat_checkpoint")
def load(project_id: str, body: ChatLoad, request: Request):
    return request.app.state.chat.load(project_id, body)


@router.get(
    "/checkpoints/latest",
    response_model=CheckpointSelection,
    operation_id="get_latest_chat_checkpoint",
)
def latest(project_id: str, request: Request, job_id: Identifier | None = None):
    return latest_checkpoint(request.app.state.workspace, project_id, job_id)


@router.post(
    "/load-latest",
    response_model=ChatLatestStatus,
    operation_id="load_latest_chat_checkpoint",
)
def load_latest(project_id: str, request: Request, body: ChatLoadLatest | None = None):
    return request.app.state.chat.load_latest(project_id, body or ChatLoadLatest())


@router.post(
    "/unload", response_model=ChatStatus, operation_id="unload_chat_checkpoint"
)
def unload(project_id: str, request: Request):
    return request.app.state.chat.unload(project_id)


@router.post(
    "/completions",
    response_model=ChatReply,
    operation_id="create_local_chat_completion",
)
def complete(project_id: str, body: ChatCompletion, request: Request):
    return request.app.state.chat.complete(project_id, body)
