import json
import struct
import sys
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from hentai_studio.api.app import create_app
from hentai_studio.jobs.files import atomic_json
from hentai_studio.llm.checkpoints import complete_weights, latest_checkpoint
from hentai_studio.models import Job, Project


@pytest.fixture
def client(tmp_path):
    with TestClient(
        create_app(tmp_path / "workspace"), base_url="http://127.0.0.1"
    ) as client:
        project = client.post(
            "/api/projects",
            json={
                "id": "scratch",
                "root": str(tmp_path),
                "llm": {
                    "python": sys.executable,
                    "model": "config",
                    "tokenizer": "tokenizer",
                    "dataset": "data.jsonl",
                },
            },
        )
        assert project.status_code == 201
        yield client


def seed(
    client,
    name="run-a",
    created="2026-11-23T12:00:00Z",
    state="succeeded",
    project="scratch",
):
    workspace = client.app.state.workspace
    directory = workspace.jobs / name
    (directory / "output").mkdir(parents=True)
    atomic_json(
        directory / "job.json",
        Job(
            id=name,
            project_id=project,
            project=Project.model_validate(
                client.get("/api/projects/" + project).json()
            ),
            command="train",
            state=state,
            created_at=created,
        ).model_dump(),
    )
    return directory / "output"


def weights(directory, name="model.safetensors"):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "config.json").write_text('{"model_type":"gpt2"}')
    header = json.dumps(
        {"test": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}}
    ).encode()
    (directory / name).write_bytes(struct.pack("<Q", len(header)) + header + b"\0" * 4)


def test_latest_uses_newest_complete_run_and_numeric_steps(client):
    older = seed(client)
    weights(older / "checkpoint-900")
    newer = seed(client, "run-b", "2026-11-23T13:00:00Z")
    weights(newer / "checkpoint-9")
    weights(newer / "checkpoint-100")
    weights(newer / "checkpoint-101")
    (newer / "checkpoint-101/model.safetensors").write_bytes(b"partial")
    result = client.get("/api/projects/scratch/chat/checkpoints/latest")
    assert result.status_code == 200, result.text
    assert result.json()["job_id"] == "run-b" and result.json()["step"] == 100
    assert (
        client.get("/api/projects/scratch/chat/checkpoints/latest?job_id=run-a").json()[
            "step"
        ]
        == 900
    )
    weights(newer / "model")
    assert (
        client.get("/api/projects/scratch/chat/checkpoints/latest").json()["checkpoint"]
        == "model"
    )
    empty_newest = seed(client, "run-c", "2026-11-23T14:00:00Z")
    (empty_newest / "checkpoint-200").mkdir()
    assert (
        client.get("/api/projects/scratch/chat/checkpoints/latest").json()["job_id"]
        == "run-b"
    )


def test_shards_must_exist_and_stay_in_output(tmp_path):
    directory = tmp_path / "output/checkpoint-10"
    weights(directory, "part-1.safetensors")
    index = directory / "model.safetensors.index.json"
    index.write_text(
        json.dumps(
            {"weight_map": {"a": "part-1.safetensors", "b": "part-2.safetensors"}}
        )
    )
    assert not complete_weights(directory, tmp_path / "output")
    weights(directory, "part-2.safetensors")
    assert complete_weights(directory, tmp_path / "output")
    index.write_text(
        json.dumps({"weight_map": {"a": str(tmp_path / "external.safetensors")}})
    )
    (tmp_path / "external.safetensors").write_bytes(
        (directory / "part-1.safetensors").read_bytes()
    )
    assert not complete_weights(directory, tmp_path / "output")
    index.write_text('{"weight_map":{"a":[]}}')
    assert not complete_weights(directory, tmp_path / "output")


def test_active_run_requires_completed_trainer_state(client, monkeypatch):
    output = seed(client)
    weights(output / "checkpoint-10")
    workspace = client.app.state.workspace
    job = workspace.get_job("run-a").model_copy(update={"state": "running"})
    monkeypatch.setattr(workspace, "list_jobs", lambda project_id=None: [job])
    with pytest.raises(Exception, match="No complete saved checkpoint"):
        latest_checkpoint(workspace, "scratch")
    (output / "checkpoint-10/trainer_state.json").write_text('{"global_step":10}')
    assert latest_checkpoint(workspace, "scratch").step == 10
    (output / "checkpoint-10/trainer_state.json").write_text('{"global_step":9}')
    with pytest.raises(Exception, match="No complete saved checkpoint"):
        latest_checkpoint(workspace, "scratch")


def test_latest_not_found_and_project_isolation(client, tmp_path):
    assert (
        client.post("/api/projects/scratch/chat/load-latest").json()["error"]["code"]
        == "checkpoint_not_found"
    )
    body = client.get("/api/projects/scratch").json() | {"id": "other"}
    assert client.post("/api/projects", json=body).status_code == 201
    output = seed(client, "other-run", project="other")
    weights(output / "model")
    assert (
        client.get(
            "/api/projects/scratch/chat/checkpoints/latest?job_id=other-run"
        ).json()["error"]["code"]
        == "wrong_project"
    )
    assert (
        client.post(
            "/api/projects/scratch/chat/load-latest", json={"device": "invalid"}
        ).status_code
        == 422
    )


def test_load_latest_is_idempotent_and_replaces_only_idle_inference(
    client, tmp_path, monkeypatch
):
    output = seed(client)
    weights(output / "checkpoint-10")
    runner = tmp_path / "fake-infer.py"
    runner.write_text(
        "import sys,json\njson.loads(sys.stdin.readline())\nprint(json.dumps({'ready':True}),flush=True)\nfor line in sys.stdin:\n r=json.loads(line)\n print(json.dumps({'content':'test reply','tokens':2}),flush=True)\n"
    )
    chat = client.app.state.chat
    chat.runner = runner
    client.app.state.workspace.stop_job = Mock(
        side_effect=AssertionError("Must preserve training")
    )
    route = "/api/projects/scratch/chat/load-latest"
    first = client.post(route)
    assert first.status_code == 200, first.text
    assert first.json()["selection"]["step"] == 10
    session = chat.sessions["scratch"]
    assert client.post(route).json()["loaded"]
    assert chat.sessions["scratch"] is session
    weights(output / "checkpoint-20")
    assert client.post(route, json={"replace": False}).status_code == 409
    assert chat.sessions["scratch"] is session and session.status()["loaded"]
    session.lock.acquire()
    try:
        assert client.post(route).json()["error"]["code"] == "inference_busy"
    finally:
        session.lock.release()
    assert client.post(route).json()["selection"]["step"] == 20
    assert chat.sessions["scratch"] is not session
    assert session.process.poll() is not None
    assert (
        client.post(
            "/api/projects/scratch/chat/completions",
            json={"messages": [{"role": "user", "content": "Hi"}]},
        ).json()["content"]
        == "test reply"
    )
    client.app.state.workspace.stop_job.assert_not_called()
    current = chat.sessions["scratch"]
    workspace = client.app.state.workspace
    active = workspace.get_job("run-a").model_copy(update={"state": "running"})
    (output / "checkpoint-20/trainer_state.json").write_text('{"global_step":20}')
    monkeypatch.setattr(workspace, "list_jobs", lambda project_id=None: [active])
    assert (
        client.post(route, json={"device": "cuda"}).json()["error"]["code"]
        == "training_active"
    )
    assert chat.sessions["scratch"] is current and current.status()["loaded"]
    shared = client.post(route, json={"device": "cuda", "allow_training_overlap": True})
    assert shared.status_code == 200, shared.text
    assert shared.json()["allow_training_overlap"] is True
    assert shared.json()["device"] == "cuda"
    shared_session = chat.sessions["scratch"]
    chat.require_training_available(workspace.get_project("scratch"), None)
    assert (
        client.post(route, json={"device": "cuda"}).json()["error"]["code"]
        == "training_active"
    )
    assert chat.sessions["scratch"] is shared_session
    workspace.stop_job.assert_not_called()
