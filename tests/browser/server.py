"""Synthetic API/browser fixture with no production models or processes."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import socket

import uvicorn

from hentai_studio.api.app import create_app
from hentai_studio.api.services.diffusion import DiffusionService


class FakeRunService:
    def list_runs(self, workload=None):
        return [{"id": f"llm.causal:{name}", "display_name": f"{name.title()} <example>", "state": "prepared", "workload_type": "llm.causal"} for name in ("alpha", "beta")]

    def get_storage(self):
        return {"root": "/fixture", "free_bytes": 100_000_000, "total_bytes": 200_000_000}

    def get_run(self, run_id):
        name = run_id.split(":", 1)[1]
        return {"id": run_id, "display_name": f"{name.title()} <example>", "workload_type": "llm.causal", "state": "running", "capabilities": {"chat": True}, "progress": {"step": 100, "total_steps": 200, "seconds_per_step": 1, "tokens_per_second": 256}, "loss_history": [{"step": 1, "loss": 2}, {"step": 100, "loss": 1, "eval_loss": 1.5}]}

    def list_checkpoints(self, run_id):
        return [{"id": "weights/step-100", "step": 100, "complete": True, "modified_at": 1, "size_bytes": 1024}]


class FakeSampling:
    def status(self):
        return {"status": "idle"}


class FakeDashboard:
    def __init__(self, root):
        self.sample_dir = root / "samples"
        self.run_dir = root / "runs/fixture"
        self.sampling = FakeSampling()

    def snapshot(self):
        return {
            "running": False, "paused": True, "pids": [], "watchdog_running": False,
            "architecture_label": "HENTAI / 4X LATENT", "progress": {"step": 100, "total": 200},
            "stages": {"active": "diffusion", "vae": {"step": 100, "total": 100, "percent": 100}, "diffusion": {"step": 100, "total": 200, "percent": 50}, "overall": {"step": 200, "total": 300, "percent": 66}},
            "checkpoints": [{"name": "step-100", "step": 100, "size_bytes": 1024, "modified_at": 1}],
            "loss_history": [{"step": 1, "loss": 2}, {"step": 100, "loss": 1}],
            "sampling": False, "sample_started": None, "checkpoint_every": 100,
            "disk": {"free_bytes": 100_000_000, "total_bytes": 200_000_000}, "hardware": {}, "server_time": 1,
        }

    def checkpoint_catalog(self):
        return [{"id": "fixture", "label": "Fixture <run>", "resolution": 512, "checkpoints": [{"id": "step-100", "step": 100, "modified_at": 1}]}]

    def samples(self):
        return []

    def stop(self):
        pass

    def resume(self):
        pass

    def start_diffusion(self):
        pass

    def start_sample(self, options):
        pass


if __name__ == "__main__":
    with TemporaryDirectory(dir=os.environ.get("STUDIO_TEST_TMP")) as directory:
        app = create_app(FakeRunService(), DiffusionService(FakeDashboard(Path(directory))))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            print(json.dumps({"port": listener.getsockname()[1]}), flush=True)
            server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
            server.run(sockets=[listener])
