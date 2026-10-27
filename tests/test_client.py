"""Use the public Python client against a real server and external trainer."""

import socket
import sys
import threading
import time

import pytest
import uvicorn

from hentai_studio import StudioAPIError, StudioClient
from hentai_studio.api.app import create_app
from hentai_studio.jobs.files import ACTIVE


@pytest.fixture
def studio(tmp_path):
    app = create_app(tmp_path / "workspace")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    client = StudioClient(f"http://127.0.0.1:{sock.getsockname()[1]}")
    yield client
    for job in app.state.workspace.list_jobs():
        if job.state in ACTIVE:
            app.state.workspace.stop_job(job.id)
            deadline = time.monotonic() + 15
            while (
                app.state.workspace.get_job(job.id).state in ACTIVE
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
    server.should_exit = True
    thread.join(timeout=15)
    sock.close()
    assert not thread.is_alive()


def test_client_register_train_wait_logs_resume_download_and_errors(studio, tmp_path):
    root = tmp_path / "trainer"
    root.mkdir()
    (root / "train.py").write_text(
        r"""
import os, json
from pathlib import Path
output = Path(os.environ['STUDIO_OUTPUT_DIR'])
print('training', flush=True)
(output/'weights.bin').write_bytes(b'weights')
(output/'metrics.jsonl').write_text('{"step":1,"loss":0.5}\n')
print('done', flush=True)
""",
        encoding="utf-8",
    )
    with studio:
        project = studio.create_project(root, {"train": [sys.executable, "train.py"]})
        assert project["name"] == "trainer"
        assert studio.update_project(project, name="Renamed")["name"] == "Renamed"
        launched = studio.start_job(project)
        finished = studio.wait(launched, timeout=15, poll_interval=0.05)
        assert finished["state"] == "succeeded"
        assert studio.logs(finished, tail=65536)["text"].strip().endswith("done")
        assert studio.metrics(finished)["items"] == [{"step": 1.0, "loss": 0.5}]
        artifact = studio.artifacts(finished)["items"]
        assert any(item["download_url"] for item in artifact)
        target = studio.download_artifact(
            finished, "weights.bin", tmp_path / "download.bin"
        )
        assert target.read_bytes() == b"weights"
        resumed = studio.wait(
            studio.resume_job(finished), timeout=15, poll_interval=0.05
        )
        assert resumed["resume_from"] == finished["id"]
        assert len(studio.list_jobs(project_id=project["id"], page_size=1)) == 2
        assert studio.stop_job(resumed)["state"] == "succeeded"
        assert len(studio.list_projects(page_size=1)) == 1
        with pytest.raises(StudioAPIError) as failure:
            studio.update_project(project, metrics_file="../private.csv")
        assert failure.value.status == 422 and failure.value.code == "invalid_project"
        assert failure.value.details[0]["field"] == "/body/metrics_file"
        studio.delete_project(project)
        assert len(studio.list_jobs()) == 2


@pytest.mark.parametrize(
    "url", ["localhost:7860", "ftp://localhost", "http://localhost/api"]
)
def test_client_rejects_ambiguous_base_urls(url):
    with pytest.raises(ValueError):
        StudioClient(url)
