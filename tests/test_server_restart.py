"""Accept a real server process restart while a trainer remains running."""

import json
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from hentai_studio.jobs.files import ACTIVE
from hentai_studio.jobs.workspace import Workspace


def test_external_job_survives_actual_server_restart(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "train.py").write_text(
        "import time; print('external trainer alive', flush=True); time.sleep(60)"
    )
    workspace = tmp_path / "workspace"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"

    def request(path, body=None):
        req = Request(
            base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=2) as response:
            return json.load(response)

    def start_server():
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "hentai_studio.cli",
                "serve",
                "--workspace",
                str(workspace),
                "--port",
                str(port),
                "--log-file",
                str(tmp_path / "server.log"),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                request("/api/health")
                return process
            except (URLError, OSError):
                assert process.poll() is None, "Server failed during startup"
                time.sleep(0.05)
        process.terminate()
        process.wait(timeout=10)
        raise AssertionError("Server did not start")

    def wait_state(job_id, states):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            job = request(f"/api/jobs/{job_id}")
            if job["state"] in states:
                return job
            time.sleep(0.05)
        raise AssertionError(f"Unexpected state: {job}")

    server = start_server()
    try:
        request(
            "/api/projects",
            {
                "id": "external",
                "name": "External",
                "root": str(root),
                "commands": {"train": [sys.executable, "-u", "train.py"]},
            },
        )
        job = request("/api/projects/external/jobs", {"command": "train"})
        running = wait_state(job["id"], {"running"})
        server.terminate()
        server.wait(timeout=10)
        server = start_server()
        reconnected = request(f"/api/jobs/{job['id']}")
        assert reconnected["state"] == "running"
        assert reconnected["worker_pid"] == running["worker_pid"]
        assert "Uvicorn running" in (tmp_path / "server.log").read_text(
            encoding="utf-8"
        )
        assert (
            "external trainer alive" in request(f"/api/jobs/{job['id']}/logs")["text"]
        )
        request(f"/api/jobs/{job['id']}/stop", {})
        assert wait_state(job["id"], {"stopped"})["state"] == "stopped"
    finally:
        server.terminate()
        server.wait(timeout=10)
        service = Workspace(workspace)
        for job in service.list_jobs():
            if job.state in ACTIVE:
                service.stop_job(job.id)
                deadline = time.monotonic() + 15
                while (
                    service.get_job(job.id).state in ACTIVE
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.05)
