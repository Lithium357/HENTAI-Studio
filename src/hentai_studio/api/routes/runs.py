from typing import Literal

from fastapi import APIRouter

from ..dependencies import Runs
from ..schemas import ChatCompletion, ChatRequest, Checkpoint, Collection, Run, RunDetail, RunId

router = APIRouter(prefix="/runs", tags=["Runs"])


@router.get("", response_model=Collection[Run])
def list_runs(service: Runs, workload: Literal["diffusion", "llm.causal"] | None = None):
    """List registered runs. IDs include the workload, for example llm.causal:my-run."""
    return Collection(items=service.list_runs(workload))


@router.get("/{run_id}", response_model=RunDetail)
def get_run(run_id: RunId, service: Runs):
    """Read live progress, telemetry, and capabilities for one registered run."""
    return service.get_run(run_id)


@router.get("/{run_id}/checkpoints", response_model=Collection[Checkpoint])
def list_checkpoints(run_id: RunId, service: Runs):
    """List complete and incomplete checkpoints; IDs are opaque strings."""
    return Collection(items=service.list_checkpoints(run_id))


@router.post("/{run_id}/chat/completions", response_model=ChatCompletion)
def complete_chat(run_id: RunId, body: ChatRequest, service: Runs):
    """Generate one CPU reply from the latest completed LoRA weights checkpoint."""
    return service.complete_chat(run_id, body.messages, body.max_new_tokens)
