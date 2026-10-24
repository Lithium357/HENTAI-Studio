from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .core.run_registry import RunRegistry
from .core.storage import StorageRoots
from .workloads.diffusion.adapter import DiffusionAdapter
from .workloads.llm.adapter import CausalLLMAdapter
from .workloads.llm.config import load_llm_config
from .workloads.llm.inference import LocalLLMChat


class StudioService:
    """Workload-neutral, dependency-light API service.

    It intentionally does not import Torch, Transformers, or the legacy dashboard.
    Legacy dashboard routes remain served by ``scratchtag dashboard`` during the
    migration; this service is the stable starting point for new multi-run UI.
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
    service = StudioService(Path(project), Path(storage_root))

    class Handler(BaseHTTPRequestHandler):
        server_version = "HENTAIStudio/2.0"

        def log_message(self, format: str, *args: object) -> None:
            return

        def send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:
            parts = [unquote(part) for part in urlparse(self.path).path.split("/") if part]
            try:
                if parts == ["api", "v1", "runs"]:
                    self.send_json({"runs": service.runs()})
                elif parts == ["api", "v1", "storage"]:
                    self.send_json(service.storage_status())
                elif len(parts) == 5 and parts[:3] == ["api", "v1", "runs"] and parts[4] == "status":
                    self.send_json(service.status(parts[3]))
                elif len(parts) == 5 and parts[:3] == ["api", "v1", "runs"] and parts[4] == "checkpoints":
                    self.send_json({"checkpoints": service.checkpoints(parts[3])})
                else:
                    self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except ValueError as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

        def do_POST(self) -> None:
            parts = [unquote(part) for part in urlparse(self.path).path.split("/") if part]
            if len(parts) != 5 or parts[:3] != ["api", "v1", "runs"] or parts[4] != "chat":
                self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            if int(self.headers.get("Content-Length", "0")) > 131_072:
                self.send_json({"error": "request too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                return
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
                self.send_json(service.chat(parts[3], payload.get("messages", []), int(payload.get("maxNewTokens", 256))))
            except (ValueError, OSError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"HENTAI Studio API: http://localhost:{port}", flush=True)
    server.serve_forever()
