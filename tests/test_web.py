import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from hentai_studio.dashboard import DashboardState
from hentai_studio.studio import StudioService
from hentai_studio.web.application import StudioApplication


@pytest.fixture
def app(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"run_dir": "runs/active", "resolution": 512}))
    state = DashboardState(tmp_path, config, tmp_path / "samples")
    return StudioApplication(StudioService(tmp_path, tmp_path), state)


@pytest.mark.parametrize("body", [b"[]", b"null", b"42", b"{", b'"sample"', b"\xff"])
def test_bad_action_body_cannot_reach_controls(app, body):
    controls = app.dashboard.controls = Mock()
    response = app.dispatch("POST", "/api/action", body)
    assert response.status == 400
    assert "error" in json.loads(response.body)
    assert controls.mock_calls == []


def test_oversized_action_cannot_reach_controls(app):
    controls = app.dashboard.controls = Mock()
    assert app.dispatch("POST", "/api/action", b" " * 16_385).status == 413
    assert controls.mock_calls == []


def test_action_dispatches_once_and_returns_json(app):
    controls = app.dashboard.controls = Mock()
    response = app.dispatch("POST", "/api/action", b'{"action":"resume"}')
    assert response.status == 200
    assert json.loads(response.body) == {"ok": True}
    controls.resume.assert_called_once_with()


@pytest.mark.parametrize("path", ["/../README.md", "/%2e%2e/README.md", "/samples/%2e%2e/config.json", "/unknown.js"])
def test_files_are_confined_to_asset_and_sample_roots(app, path):
    assert app.dispatch("GET", path).status == 404


def test_module_assets_and_csv_download(app):
    index = app.dispatch("GET", "/")
    assert index.status == 200
    assert b'type="module"' in index.body
    for name in ("app", "api", "llm", "diffusion", "charts", "format", "dom", "poller"):
        asset = app.dispatch("GET", f"/{name}.js")
        assert asset.status == 200
        assert asset.content_type.startswith("text/javascript")
    progress = app.dashboard.run_dir / "progress"
    progress.mkdir(parents=True)
    (progress / "vae.csv").write_text("step,loss\n1,0.5\n")
    response = app.dispatch("GET", "/progress/vae.csv")
    assert response.status == 200
    assert b"1,0.5" in response.body
    assert "VAE-progress.csv" in response.headers["Content-Disposition"]


def test_dashboard_and_api_only_use_identical_run_routes(app):
    run = app.dashboard.project / "runs" / "fixture"
    run.mkdir(parents=True)
    (run / "config.json").write_text('{"run_dir":"runs/fixture","resolution":512}')
    api = StudioApplication(app.service)
    for path in ("/api/v1/runs", "/api/v1/runs/fixture/status", "/api/v1/runs/fixture/checkpoints", "/api/v1/storage"):
        assert app.dispatch("GET", path).body == api.dispatch("GET", path).body
    assert api.dispatch("GET", "/").status == 404
    assert api.dispatch("POST", "/api/action", b'{"action":"stop"}').status == 404


@pytest.mark.parametrize("payload", [
    {"messages": ["text"]}, {"messages": {}}, {"maxNewTokens": True},
    {"maxNewTokens": 0}, {"maxNewTokens": 257}, {"maxNewTokens": "128"},
])
def test_invalid_chat_is_rejected_before_model_dispatch(app, payload):
    app.service.chat = Mock()
    response = app.dispatch("POST", "/api/v1/runs/fixture/chat", json.dumps(payload).encode())
    assert response.status == 400
    app.service.chat.assert_not_called()
