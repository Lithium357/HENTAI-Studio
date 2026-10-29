import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from hentai_studio.api.app import create_app
from hentai_studio.llm.data import format_messages, read_records


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "workspace")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client


def definition(tmp_path):
    return {
        "id": "scratch",
        "name": "Scratch model",
        "root": str(tmp_path),
        "llm": {
            "python": sys.executable,
            "model": "config",
            "tokenizer": "tokenizer",
            "dataset": "train.jsonl",
        },
    }


def test_profile_generates_train_command_and_round_trips(client, tmp_path):
    created = client.post("/api/projects", json=definition(tmp_path))
    assert created.status_code == 201, created.text
    project = created.json()
    assert project["llm"]["learning_rate"] == 0.0003
    argv = project["commands"]["train"]
    assert argv[:2] == [sys.executable, "-u"]
    assert Path(argv[2]).name == "train.py"
    assert json.loads(argv[4])["tokenizer"] == "tokenizer"
    assert client.get("/api/projects/scratch").json() == project
    changed = client.patch(
        "/api/projects/scratch", json={"llm": project["llm"] | {"batch_size": 2}}
    )
    assert json.loads(changed.json()["commands"]["train"][4])["batch_size"] == 2
    assert (
        client.patch(
            "/api/projects/scratch",
            json={"llm": None, "commands": {"train": ["python", "custom.py"]}},
        ).json()["llm"]
        is None
    )


@pytest.mark.parametrize(
    "change",
    [
        {"max_steps": 0},
        {"learning_rate": 0},
        {"dataset": " "},
        {"precision": "auto"},
        {"max_length": 1},
        {"tokenizer": ""},
    ],
)
def test_invalid_llm_profile_never_saves(client, tmp_path, change):
    body = definition(tmp_path)
    body["llm"].update(change)
    assert client.post("/api/projects", json=body).status_code == 422
    assert client.get("/api/projects").json()["items"] == []


def test_local_chat_requires_profile_and_explicit_load(client, tmp_path):
    body = definition(tmp_path)
    body.pop("llm")
    body["commands"] = {"train": ["python", "train.py"]}
    client.post("/api/projects", json=body)
    assert client.get("/api/projects/scratch/chat").status_code == 409
    assert (
        client.post(
            "/api/projects/scratch/chat/completions",
            json={"messages": [{"role": "user", "content": "hello"}]},
        ).status_code
        == 409
    )


def test_chat_load_invalid_paths_and_input_bounds(client, tmp_path):
    client.post("/api/projects", json=definition(tmp_path))
    assert client.get("/api/projects/scratch/chat").json()["loaded"] is False
    assert (
        client.post(
            "/api/projects/scratch/chat/load", json={"checkpoint": "not-a-model"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/projects/scratch/chat/completions",
            json={"messages": [{"role": "assistant", "content": "hello"}]},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/projects/scratch/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 99999,
            },
        ).status_code
        == 422
    )


def test_owned_chat_worker_handles_turns_and_unloads_without_touching_training(
    client, tmp_path, monkeypatch
):
    client.post("/api/projects", json=definition(tmp_path))
    checkpoint = tmp_path / "model"
    checkpoint.mkdir()
    (checkpoint / "config.json").write_text("{}")
    fake = tmp_path / "fake_infer.py"
    fake.write_text("""import sys,json
config=json.loads(sys.stdin.readline())
print(json.dumps({"ready": True}),flush=True)
for line in sys.stdin:
 request=json.loads(line)
 print(json.dumps({"content": "Local reply: " + request["messages"][-1]["content"], "tokens": 3}),flush=True)
""")
    client.app.state.chat.runner = fake
    client.app.state.workspace.stop_job = Mock(
        side_effect=AssertionError("Chat must never stop training")
    )
    loaded = client.post(
        "/api/projects/scratch/chat/load", json={"checkpoint": str(checkpoint)}
    )
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["device"] == "cpu"
    duplicate = client.post(
        "/api/projects/scratch/chat/load", json={"checkpoint": str(checkpoint)}
    )
    assert duplicate.status_code == 409
    reply = client.post(
        "/api/projects/scratch/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert reply.json() == {"content": "Local reply: hello", "tokens": 3}
    assert (
        client.patch("/api/projects/scratch", json={"llm": None}).json()["error"][
            "code"
        ]
        == "chat_model_loaded"
    )
    assert client.delete("/api/projects/scratch").status_code == 409
    client.app.state.chat.sessions["scratch"].device = "cuda"
    assert (
        client.post("/api/jobs", json={"project_id": "scratch"}).json()["error"]["code"]
        == "gpu_chat_active"
    )
    client.app.state.chat.sessions["scratch"].device = "cpu"
    assert client.post("/api/projects/scratch/chat/unload").json()["loaded"] is False
    assert client.get("/api/projects/scratch/chat").json()["loaded"] is False
    client.app.state.workspace.stop_job.assert_not_called()


def test_gpu_chat_refuses_to_compete_with_active_training(
    client, tmp_path, monkeypatch
):
    client.post("/api/projects", json=definition(tmp_path))
    (tmp_path / "model").mkdir()
    (tmp_path / "model/config.json").write_text("{}")
    monkeypatch.setattr(
        client.app.state.workspace,
        "list_jobs",
        lambda: [SimpleNamespace(state="running", has_live_processes=True)],
    )
    assert (
        client.post(
            "/api/projects/scratch/chat/load",
            json={"checkpoint": "model", "device": "cuda"},
        ).json()["error"]["code"]
        == "training_active"
    )


def test_dataset_formatting_is_shared_by_train_and_chat(tmp_path):
    tokenizer = SimpleNamespace(chat_template=None)
    messages = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello"},
    ]
    assert format_messages(tokenizer, messages) == "user: Hi\nassistant: Hello\n"
    assert (
        format_messages(tokenizer, messages[:1], generation=True)
        == "user: Hi\nassistant: "
    )
    path = tmp_path / "data.jsonl"
    path.write_text(
        json.dumps({"text": "hello"}) + "\n" + json.dumps({"messages": messages}) + "\n"
    )
    assert len(list(read_records(path))) == 2
    path.write_text("{bad json}\n")
    with pytest.raises(ValueError, match="line 1"):
        list(read_records(path))
