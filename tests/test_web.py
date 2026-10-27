import sys
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from hentai_studio.api.app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path / "workspace")


@pytest.fixture
def client(app):
    with TestClient(
        app, raise_server_exceptions=False, base_url="http://127.0.0.1"
    ) as client:
        yield client


def definition(tmp_path):
    return {
        "id": "arbitrary",
        "name": "Any trainer",
        "root": str(tmp_path),
        "commands": {"train": [sys.executable, "-c", "print('hello')"]},
    }


def test_empty_workspace_serves_dashboard_and_typed_api(client):
    assert client.get("/api/projects").json() == {"items": []}
    assert client.get("/api/jobs").json() == {"items": []}
    assert client.get("/api/health").json()["version"] == "0.5.0"
    assert 'type="module"' in client.get("/").text
    for asset in ("api", "app", "metrics", "poller"):
        assert client.get(f"/assets/{asset}.js").status_code == 200
    schema = client.get("/api/openapi.json").json()
    assert "/api/projects/{project_id}/jobs" in schema["paths"]
    assert schema["components"]["schemas"]["Project"]["additionalProperties"] is False
    assert client.get("/api/docs").status_code == 200


def test_project_crud_is_persistent_and_never_changes_training_files(
    client, app, tmp_path
):
    body = definition(tmp_path)
    assert client.post("/api/projects", json=body).status_code == 201
    assert client.post("/api/projects", json=body).status_code == 409
    body["name"] = "Renamed"
    assert client.put("/api/projects/arbitrary", json=body).json()["name"] == "Renamed"
    assert app.state.workspace.get_project("arbitrary").name == "Renamed"
    assert client.put("/api/projects/other", json=body).status_code == 422
    assert client.delete("/api/projects/arbitrary").status_code == 204
    assert client.get("/api/projects/arbitrary").status_code == 404
    assert tmp_path.is_dir()


@pytest.mark.parametrize(
    "change",
    [
        {"commands": {"train": "python train.py"}},
        {"commands": {"train": []}},
        {"commands": {"train": [""]}},
        {"commands": {"../bad": ["python"]}},
        {"id": "../escape"},
        {"id": "CON"},
        {"id": "com1"},
        {"root": "relative/project"},
        {"metrics_file": "../private.jsonl"},
        {"metrics_file": r"\metrics.csv"},
        {"metrics_file": "file:stream.csv"},
        {"metrics_file": "C:\\secret.csv"},
        {"metrics_file": "/tmp/out.csv"},
        {"metrics_file": "file.txt"},
        {"environment": {"bad=key": "value"}},
        {"extra": True},
    ],
)
def test_invalid_project_is_rejected(client, tmp_path, change):
    assert (
        client.post("/api/projects", json=definition(tmp_path) | change).status_code
        == 422
    )


@pytest.mark.parametrize("body", [b"[]", b"null", b"42", b"{", b'"project"', b"\xff"])
def test_bad_json_never_reaches_project_registration(client, app, body):
    app.state.workspace.save_project = Mock()
    result = client.post(
        "/api/projects", content=body, headers={"Content-Type": "application/json"}
    )
    assert result.status_code in (400, 422)
    assert result.json()["error"]["code"] in ("validation_error", "http_error")
    app.state.workspace.save_project.assert_not_called()


def test_errors_and_limits_use_common_envelope(client, app):
    assert client.get("/api/jobs/missing").json()["error"]["code"] == "job_not_found"
    response = client.post("/api/health")
    assert (
        response.status_code == 405
        and response.json()["error"]["code"] == "method_not_allowed"
    )
    assert "GET" in response.headers["allow"]
    response = client.post("/api/projects", content=(b" " * 65536 for _ in range(3)))
    assert (
        response.status_code == 413
        and response.json()["error"]["code"] == "request_too_large"
    )
    app.state.workspace.list_projects = Mock(side_effect=TypeError("private detail"))
    response = client.get("/api/projects")
    assert response.status_code == 500 and "private detail" not in response.text


@pytest.mark.parametrize("length", ["-1", "invalid"])
def test_invalid_content_length(client, length):
    assert (
        client.post(
            "/api/projects", content=b"", headers={"Content-Length": length}
        ).status_code
        == 400
    )


@pytest.mark.parametrize(
    "path",
    ["/api/diffusion/status", "/api/runs", "/api/action", "/assets/%2e%2e/README.md"],
)
def test_old_model_routes_and_asset_traversal_are_absent(client, path):
    assert client.get(path).status_code == 404


def test_invalid_job_request_never_spawns(client, app):
    app.state.workspace.start_job = Mock()
    response = client.post(
        "/api/projects/any/jobs", json={"command": "train", "shell": "anything"}
    )
    assert response.status_code == 422
    app.state.workspace.start_job.assert_not_called()
    assert client.get("/api/jobs/any/logs?limit=1000000").status_code == 422


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "attacker.example"},
        {"Origin": "https://attacker.example"},
        {"Origin": "null"},
        {"Origin": "http://127.0.0.1:9999"},
    ],
)
def test_command_api_rejects_untrusted_browser_requests(client, app, headers):
    app.state.workspace.start_job = Mock()
    response = client.post(
        "/api/projects/any/jobs", json={"command": "train"}, headers=headers
    )
    assert (
        response.status_code == 403
        and response.json()["error"]["code"] == "untrusted_request"
    )
    app.state.workspace.start_job.assert_not_called()


def test_same_origin_and_cli_requests_are_allowed(client):
    assert (
        client.get("/api/health", headers={"Origin": "http://127.0.0.1"}).status_code
        == 200
    )
    assert client.get("/api/health").json()["application"] == "hentai-studio"


def test_workspace_corruption_is_reported_without_crashing_dashboard(client, app):
    (app.state.workspace.projects / "broken.json").write_text("invalid")
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["issues"][0]["resource"] == "projects/broken.json"
    assert client.get("/api/projects").json() == {"items": []}
    assert client.get("/").status_code == 200
