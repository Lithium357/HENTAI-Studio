from __future__ import annotations

from pathlib import Path

from .core.run_registry import RunRegistry
from .core.storage import StorageRoots
from .workloads.diffusion.adapter import DiffusionAdapter
from .workloads.llm.adapter import CausalLLMAdapter
from .workloads.llm.config import load_llm_config
from .workloads.llm.inference import LocalLLMChat


class StudioService:
    """Workload-neutral, dependency-light API service.

    It intentionally does not import Torch, Transformers, or the legacy dashboard.
    The dashboard and API-only server share this service and the same routes.
    """

    def __init__(self, project: Path, storage_root: Path) -> None:
        self.project = project.resolve()
        self.storage = StorageRoots(storage_root.resolve())
        self.registry = RunRegistry(self.project, self.storage.runs)
        self.adapters = {"diffusion": DiffusionAdapter(), "llm.causal": CausalLLMAdapter()}
        self.llm_chat = LocalLLMChat()

    def runs(self) -> list[dict[str, object]]:
        return [
            {
                "id": item.run_id,
                "displayName": item.display_name,
                "workloadType": item.workload_type,
                "state": item.state,
                "legacy": item.legacy,
            }
            for item in self.registry.discover()
        ]

    def status(self, run_id: str) -> dict[str, object]:
        description = self.registry.get(run_id)
        adapter = self.adapters[description.workload_type]
        return {"run": {"id": description.run_id, "displayName": description.display_name, "workloadType": description.workload_type, "legacy": description.legacy}, **adapter.status(description.run_dir)}

    def checkpoints(self, run_id: str) -> list[dict[str, object]]:
        description = self.registry.get(run_id)
        adapter = self.adapters[description.workload_type]
        return [
            {
                "id": item.checkpoint_id,
                "step": item.step,
                "complete": item.complete,
                "modifiedAt": item.modified_at,
                "size": item.size_bytes,
            }
            for item in adapter.checkpoints(description.run_dir)
        ]

    def storage_status(self) -> dict[str, object]:
        import shutil

        disk = shutil.disk_usage(self.storage.root)
        return {"root": str(self.storage.root), "free": disk.free, "total": disk.total}

    def chat(self, run_id: str, messages: list[dict[str, str]], max_new_tokens: int = 128) -> dict[str, str]:
        description = self.registry.get(run_id)
        if description.workload_type != "llm.causal":
            raise ValueError("chat is only available for causal LLM runs")
        checkpoint = next((item for item in self.adapters["llm.causal"].checkpoints(description.run_dir) if item.complete and item.checkpoint_id.startswith("weights/")), None)
        if checkpoint is None:
            raise ValueError("a completed adapter checkpoint is required before local CPU chat is available")
        config = load_llm_config(description.run_dir / "config.json")
        if not config.model.base_model:
            raise ValueError("this run has no compatible base model")
        adapter = checkpoint.path / "adapter"
        training_active = self.adapters["llm.causal"].status(description.run_dir).get("state") == "running"
        try:
            reply = self.llm_chat.reply(base_model=Path(config.model.base_model), adapter=adapter, messages=messages, max_new_tokens=max_new_tokens)
            return {"reply": reply}
        finally:
            # Keeping a BF16 4B model resident on CPU competes with training
            # for host RAM after a one-off checkpoint probe has completed.
            if training_active:
                self.llm_chat.unload()



def run_studio(project: str | Path, storage_root: str | Path, host: str = "127.0.0.1", port: int = 7861) -> None:
    from .web.application import StudioApplication
    from .web.server import serve

    serve(StudioApplication(StudioService(Path(project), Path(storage_root))), host, port)
