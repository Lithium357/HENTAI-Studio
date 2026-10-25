"""Synthetic dashboard fixture: no production datasets, processes, or models."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os

from hentai_studio.web.application import StudioApplication
from hentai_studio.web.server import make_server


class FakeService:
    def runs(self):
        return [{"id": name, "displayName": f"{name.title()} <example>", "state": "prepared", "workloadType": "llm.causal"} for name in ("alpha", "beta")]

    def storage_status(self):
        return {"free": 100_000_000, "total": 200_000_000}

    def status(self, run_id):
        return {"state": "running", "progress": {"step": 100, "totalSteps": 200, "secondsPerStep": 1, "tokensPerSecond": 256}, "lossHistory": [{"step": 1, "loss": 2}, {"step": 100, "loss": 1, "evalLoss": 1.5}]}

    def checkpoints(self, run_id):
        return [{"id": "weights/step-100", "step": 100, "complete": True, "modifiedAt": 1, "size": 1024}]


class FakeDashboard:
    def __init__(self, root):
        self.sample_dir = root / "samples"
        self.run_dir = root / "runs/fixture"

    def snapshot(self):
        return {
            "running": False, "paused": True, "pids": [], "watchdogRunning": False,
            "architectureLabel": "HENTAI / 4X LATENT", "progress": {"step": 100, "total": 200},
            "stages": {"active": "diffusion", "vae": {"step": 100, "total": 100, "percent": 100}, "diffusion": {"step": 100, "total": 200, "percent": 50}, "overall": {"step": 200, "total": 300, "percent": 66}},
            "checkpoints": [{"name": "step-100", "step": 100, "size": 1024, "modifiedAt": 1}],
            "checkpointCatalog": [{"id": "fixture", "label": "Fixture <run>", "resolution": 512, "checkpoints": [{"id": "step-100", "step": 100}]}],
            "samples": [], "lossHistory": [{"step": 1, "loss": 2}, {"step": 100, "loss": 1}],
            "sampling": False, "disk": {"free": 100_000_000}, "serverTime": 1,
        }

    def checkpoint_catalog(self):
        return self.snapshot()["checkpointCatalog"]

    def stop(self):
        pass

    def resume(self):
        pass

    def start_diffusion(self):
        pass

    def generate_sample(self, payload):
        pass


if __name__ == "__main__":
    with TemporaryDirectory(dir=os.environ.get("STUDIO_TEST_TMP")) as directory:
        app = StudioApplication(FakeService(), FakeDashboard(Path(directory)))
        with make_server(app, "127.0.0.1", 0) as server:
            print(json.dumps({"port": server.server_port}), flush=True)
            server.serve_forever()
