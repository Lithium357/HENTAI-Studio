import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from hentai_studio.api.app import create_app
from hentai_studio.api.services.diffusion import DiffusionService
from hentai_studio.api.services.runs import RunService
from hentai_studio.api.schemas import ChatCompletion, ChatMessage
from hentai_studio.dashboard import DashboardState


@pytest.fixture
def app(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"run_dir": "runs/active", "resolution": 512}))
    state = DashboardState(tmp_path, config, tmp_path / "samples")
    return create_app(RunService(tmp_path, tmp_path), DiffusionService(state))


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.mark.parametrize("body", [b"[]", b"null", b"42", b"{", b'"sample"', b"\xff"])
def test_bad_sample_body_cannot_reach_sampler(app, client, body):
    sampler = app.state.diffusion.state.sampling = Mock()
    response = client.post("/api/diffusion/samples", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code in (400, 422)
    assert response.json()["error"]["code"] in ("validation_error", "http_error")
    assert sampler.mock_calls == []


@pytest.mark.parametrize("payload", [
    {"steps": True}, {"steps": 61}, {"guidance": 0}, {"seed": -1},
    {"source": "checkpoint"}, {"source": "current", "run_id": "other"},
    {"source": "checkpoint", "run_id": "../outside", "checkpoint_id": "step-1"},
    {"tags": "comma,separated"}, {"unknown_field": 1},
])
def test_sample_selection_and_numeric_ranges_are_validated(app, client, payload):
    sampler = app.state.diffusion.state.sampling = Mock()
    response = client.post("/api/diffusion/samples", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["details"]
    assert sampler.mock_calls == []


def test_sample_creation_returns_job_location(app, client):
    sampler = app.state.diffusion.state.sampling = Mock()
    sampler.status.return_value = {"status": "running", "started_at": 123}
    app.state.diffusion.state.catalog = Mock()
    app.state.diffusion.state.catalog.checkpoints.return_value = [{"step": 1}]
    response = client.post("/api/diffusion/samples", json={"tags": ["portrait"], "steps": 5})
    assert response.status_code == 202
    assert response.headers["location"] == "/api/diffusion/sampling"
    assert response.json()["status"] == "running"
    command = sampler.start.call_args.args[0]
    assert command.tags == ("portrait",)
    assert command.steps == 5


def test_current_sampling_requires_a_checkpoint(app, client):
    sampler = app.state.diffusion.state.sampling = Mock()
    response = client.post("/api/diffusion/samples", json={})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "checkpoint_unavailable"
    sampler.start.assert_not_called()


def test_historical_sampling_uses_the_same_qualified_run_id_as_the_catalog(app, client):
    sampler = app.state.diffusion.state.sampling = Mock()
    sampler.status.return_value = {"status": "running", "started_at": 123}
    response = client.post("/api/diffusion/samples", json={
        "source": "checkpoint", "run_id": "diffusion:previous-run", "checkpoint_id": "step-10",
    })
    assert response.status_code == 202
    command = sampler.start.call_args.args[0]
    assert command.run_id == "previous-run"
    assert command.checkpoint_id == "step-10"


def test_status_catalog_and_gallery_are_separate_typed_resources(client):
    response = client.get("/api/diffusion/status")
    assert response.status_code == 200
    payload = response.json()
    assert "checkpoint_catalog" not in payload and "samples" not in payload
    assert payload["sampling"]["status"] == "idle"
    assert "architecture_label" in payload
    assert client.get("/api/diffusion/checkpoints").json() == {"items": []}
    assert client.get("/api/diffusion/samples").json() == {"items": []}


@pytest.mark.parametrize("command,method", [("pause", "stop"), ("resume", "resume"), ("promote-vae", "start_diffusion")])
def test_training_commands_have_separate_endpoints(app, client, command, method):
    controls = app.state.diffusion.state.controls = Mock()
    response = client.post(f"/api/diffusion/training/{command}")
    assert response.status_code == 202
    assert response.json()["command"] == command.replace("-", "_")
    getattr(controls, method).assert_called_once_with()


def test_conflict_not_found_and_unexpected_errors_are_distinct(app, client):
    controls = app.state.diffusion.state.controls = Mock()
    controls.resume.side_effect = RuntimeError("run is not ready")
    response = client.post("/api/diffusion/training/resume")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "training_conflict"
    assert client.get("/api/runs/llm.causal:missing").status_code == 404
    controls.resume.side_effect = TypeError("private implementation detail")
    response = client.post("/api/diffusion/training/resume")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "private implementation detail" not in response.text


def test_body_limit_also_covers_streamed_requests(app, client):
    sampler = app.state.diffusion.state.sampling = Mock()
    response = client.post("/api/diffusion/samples", content=(b" " * 65536 for _ in range(3)))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"
    assert sampler.mock_calls == []


@pytest.mark.parametrize("length", ["-1", "invalid"])
def test_invalid_content_length_is_rejected(client, length):
    response = client.post("/api/diffusion/samples", content=b"", headers={"Content-Length": length})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_content_length"


@pytest.mark.parametrize("path", ["/api/status", "/api/action", "/api/v1/runs", "/progress/vae.csv", "/app.js"])
def test_removed_routes_are_not_compatibility_aliases(client, path):
    assert client.get(path).status_code == 404


def test_read_only_resources_reject_wrong_http_methods(client):
    response = client.post("/api/health")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
    assert "GET" in response.headers["allow"]


def test_module_assets_and_progress_download(app, client):
    assert b'type="module"' in client.get("/").content
    for name in ("app", "api", "llm", "diffusion", "charts", "format", "dom", "poller"):
        asset = client.get(f"/assets/{name}.js")
        assert asset.status_code == 200
        assert "javascript" in asset.headers["content-type"]
    progress = app.state.diffusion.state.run_dir / "progress"
    progress.mkdir(parents=True)
    (progress / "vae.csv").write_text("step,loss\n1,0.5\n")
    response = client.get("/api/diffusion/progress/vae.csv")
    assert response.status_code == 200
    assert b"1,0.5" in response.content
    assert "vae-progress.csv" in response.headers["content-disposition"]


@pytest.mark.parametrize("path", ["/assets/%2e%2e/README.md", "/api/diffusion/samples/%2e%2e/config.json", "/api/diffusion/samples/config.json"])
def test_download_roots_are_confined(client, path):
    assert client.get(path).status_code == 404


def test_openapi_describes_routes_and_strict_request_models(client):
    schema = client.get("/api/openapi.json").json()
    assert "/api/diffusion/training/pause" in schema["paths"]
    assert "/api/action" not in schema["paths"]
    assert schema["components"]["schemas"]["SampleRequest"]["additionalProperties"] is False
    assert schema["components"]["schemas"]["ChatRequest"]["properties"]["max_new_tokens"]["maximum"] == 256
    assert client.get("/api/docs").status_code == 200


def test_api_only_mode_exposes_the_same_run_api_and_explicit_diffusion_unavailability(app):
    with TestClient(create_app(app.state.runs)) as client:
        assert client.get("/api/health").json()["diffusion_configured"] is False
        assert client.get("/api/runs").json() == {"items": []}
        response = client.get("/api/diffusion/status")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "diffusion_not_configured"
        assert client.get("/").status_code == 404


@pytest.mark.parametrize("payload", [
    {"messages": ["text"]}, {"messages": {}}, {"messages": []},
    {"messages": [{"role": "tool", "content": "hello"}]},
    {"messages": [{"role": "user", "content": 42}]},
    {"messages": [{"role": "user", "content": "hello"}], "max_new_tokens": True},
    {"messages": [{"role": "user", "content": "hello"}], "max_new_tokens": 257},
])
def test_invalid_chat_never_reaches_model_dispatch(app, client, payload):
    app.state.runs.complete_chat = Mock()
    response = client.post("/api/runs/llm.causal:fixture/chat/completions", json=payload)
    assert response.status_code == 422
    app.state.runs.complete_chat.assert_not_called()


def test_chat_completion_has_an_explicit_message_and_checkpoint(app, client):
    app.state.runs.complete_chat = Mock(return_value=ChatCompletion(
        message=ChatMessage(role="assistant", content="Hello"), checkpoint_id="weights/step-10",
    ))
    response = client.post("/api/runs/llm.causal:fixture/chat/completions", json={
        "messages": [{"role": "user", "content": "Hi"}], "max_new_tokens": 64,
    })
    assert response.status_code == 200
    assert response.json() == {"message": {"role": "assistant", "content": "Hello"},
                               "checkpoint_id": "weights/step-10", "device": "cpu"}
    run_id, messages, tokens = app.state.runs.complete_chat.call_args.args
    assert run_id == "llm.causal:fixture" and tokens == 64
    assert messages[0].content == "Hi"
