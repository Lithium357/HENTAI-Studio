from __future__ import annotations

import shutil
import threading
from pathlib import Path

from ...core.run_registry import RunRegistry
from ...core.storage import StorageRoots
from ...core.workload import RunDescription
from ...workloads.diffusion.adapter import DiffusionAdapter
from ...workloads.llm.adapter import CausalLLMAdapter
from ...workloads.llm.config import load_llm_config
from ...workloads.llm.inference import LocalLLMChat
from ..errors import ApiError
from ..schemas import ChatCompletion, ChatMessage, Checkpoint, Run, RunCapabilities, RunDetail, Storage


class RunService:
    """Read registered runs and execute CPU checkpoint chat."""

    def __init__(self, project: Path, storage_root: Path):
        self.storage = StorageRoots(storage_root.resolve())
        self.registry = RunRegistry(project.resolve(), self.storage.runs)
        self.adapters = {"diffusion": DiffusionAdapter(), "llm.causal": CausalLLMAdapter()}
        self.chat_backend = LocalLLMChat()
        self.chat_lock = threading.Lock()

    @staticmethod
    def _summary(description: RunDescription) -> Run:
        return Run(
            id=f"{description.workload_type}:{description.run_id}",
            display_name=description.display_name,
            workload_type=description.workload_type,
            state=description.state,
        )

    def _describe(self, run_id: str) -> RunDescription:
        for description in self.registry.discover():
            if self._summary(description).id == run_id:
                return description
        raise ApiError(404, "run_not_found", f"Run '{run_id}' was not found.")

    def list_runs(self, workload: str | None = None) -> list[Run]:
        return [self._summary(item) for item in self.registry.discover() if workload is None or item.workload_type == workload]

    def get_run(self, run_id: str) -> RunDetail:
        description = self._describe(run_id)
        try:
            status = self.adapters[description.workload_type].status(description.run_dir)
        except (ValueError, OSError) as error:
            raise ApiError(409, "run_unavailable", f"Run metadata cannot be read: {error}") from error
        can_chat = False
        if description.workload_type == "llm.causal":
            try:
                self._chat_context(description)
                can_chat = True
            except ApiError:
                pass
        fields = self._summary(description).model_dump()
        fields["state"] = status["state"]
        return RunDetail(
            **fields,
            pids=status.get("pids", []),
            progress=status.get("progress", {}),
            loss_history=status.get("loss_history", []),
            hardware=status.get("hardware", {}),
            capabilities=RunCapabilities(chat=can_chat),
        )

    def list_checkpoints(self, run_id: str) -> list[Checkpoint]:
        description = self._describe(run_id)
        try:
            checkpoints = self.adapters[description.workload_type].checkpoints(description.run_dir)
        except (ValueError, OSError) as error:
            raise ApiError(409, "run_unavailable", f"Checkpoints cannot be read: {error}") from error
        return [Checkpoint(id=item.checkpoint_id, step=item.step, complete=item.complete,
                           modified_at=item.modified_at, size_bytes=item.size_bytes) for item in checkpoints]

    def get_storage(self) -> Storage:
        try:
            disk = shutil.disk_usage(self.storage.root)
        except OSError as error:
            raise ApiError(503, "storage_unavailable", "The configured storage root is unavailable.") from error
        return Storage(root=str(self.storage.root), free_bytes=disk.free, total_bytes=disk.total)

    def _chat_context(self, description: RunDescription):
        if description.workload_type != "llm.causal":
            raise ApiError(409, "chat_unavailable", "Chat requires a causal language-model run.")
        try:
            config = load_llm_config(description.run_dir / "config.json")
            checkpoints = self.adapters["llm.causal"].checkpoints(description.run_dir)
        except (ValueError, OSError) as error:
            raise ApiError(409, "chat_unavailable", "This run does not have readable language-model metadata.") from error
        checkpoint = next((item for item in checkpoints if item.complete
                           and item.checkpoint_id.startswith("weights/")
                           and (item.path / "adapter/adapter_config.json").is_file()), None)
        if config.mode != "lora" or not config.model.base_model or not Path(config.model.base_model).is_dir() or checkpoint is None:
            raise ApiError(409, "chat_unavailable", "Chat requires a local base model and a completed LoRA weights checkpoint.")
        return config, checkpoint

    def complete_chat(self, run_id: str, messages: list[ChatMessage], max_new_tokens: int) -> ChatCompletion:
        description = self._describe(run_id)
        config, checkpoint = self._chat_context(description)
        # Loading, generating, and unloading are one operation: another request
        # must not unload the model while a reply is being generated.
        with self.chat_lock:
            training_active = self.adapters["llm.causal"].status(description.run_dir).get("state") == "running"
            try:
                reply = self.chat_backend.reply(
                    base_model=Path(config.model.base_model), adapter=checkpoint.path / "adapter",
                    messages=[item.model_dump() for item in messages], max_new_tokens=max_new_tokens,
                )
            except (ValueError, RuntimeError, OSError, ImportError) as error:
                raise ApiError(503, "chat_backend_unavailable", f"Local CPU chat failed: {error}") from error
            finally:
                if training_active:
                    self.chat_backend.unload()
        return ChatCompletion(message=ChatMessage(role="assistant", content=reply), checkpoint_id=checkpoint.checkpoint_id)
