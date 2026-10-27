"""Contract tests emphasize complete caller workflows and stable machine behavior."""

import sys

import pytest
from fastapi.testclient import TestClient

from hentai_studio.api.app import create_app
from hentai_studio.jobs.files import atomic_json
from hentai_studio.models import Job, Project


@pytest.fixture
def client(tmp_path):
    with TestClient(
        create_app(tmp_path / "workspace"), base_url="http://127.0.0.1"
    ) as client:
        yield client


def create(client, tmp_path, **changes):
    body = {
        "root": str(tmp_path),
        "commands": {"train": [sys.executable, "-c", "print('ok')"]},
    } | changes
    result = client.post("/api/projects", json=body)
    assert result.status_code == 201, result.text
    assert result.headers["location"] == "/api/projects/" + result.json()["id"]
    return result.json()


def seed(client, project, id, state="succeeded", created="2026-10-27T00:00:00+00:00"):
    workspace = client.app.state.workspace
    directory = workspace.jobs / id
    directory.mkdir()
    (directory / "output").mkdir()
    job = Job(
        id=id,
        project_id=project["id"],
        project=Project.model_validate(project),
        command=next(iter(project["commands"])),
        state=state,
        created_at=created,
    )
    atomic_json(directory / "job.json", job.model_dump())
    return directory


def test_minimal_registration_and_partial_edits_preserve_omitted_fields(
    client, tmp_path
):
    project = create(client, tmp_path)
    assert project["name"] == tmp_path.name
    assert project["id"].startswith("project-")
    result = client.patch(f"/api/projects/{project['id']}", json={"name": "Updated"})
    assert result.status_code == 200
    assert result.json()["commands"] == project["commands"]
    assert result.json()["root"] == project["root"]
    assert result.json()["environment"] == {}
    result = client.patch(
        f"/api/projects/{project['id']}", json={"commands": {"train": []}}
    )
    assert result.status_code == 422
    assert result.json()["error"]["details"][0]["field"] == "/body/commands/train"
    assert client.get(f"/api/projects/{project['id']}").json()["name"] == "Updated"


@pytest.mark.parametrize(
    "payload", [{}, {"name": None}, {"id": "different"}, {"root": None}]
)
def test_invalid_patch_is_actionable(client, tmp_path, payload):
    project = create(client, tmp_path)
    response = client.patch(f"/api/projects/{project['id']}", json=payload)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["details"] and isinstance(error["details"][0]["field"], str)


def test_jobs_are_compact_public_resources_with_links_and_actions(client, tmp_path):
    project = create(
        client, tmp_path, environment={"PRIVATE_TOKEN": "do-not-echo-in-job-list"}
    )
    seed(client, project, "finished")
    response = client.get("/api/jobs/finished")
    job = response.json()
    assert job["project_name"] == project["name"]
    assert job["actions"] == {"can_stop": False, "can_resume": True}
    assert job["links"]["self"] == "/api/jobs/finished"
    for hidden in (
        "project",
        "worker_pid",
        "worker_created",
        "trainer_pid",
        "trainer_created",
    ):
        assert hidden not in job
    assert "do-not-echo-in-job-list" not in client.get("/api/jobs").text
    assert client.post("/api/jobs/finished/stop").status_code == 200
    assert client.post("/api/jobs/finished/stop").json()["state"] == "succeeded"


def test_filtered_keyset_pagination_is_stable_when_new_jobs_arrive(client, tmp_path):
    project = create(client, tmp_path)
    for index in range(4):
        seed(client, project, f"job{index}")
    first = client.get("/api/jobs?limit=2&state=succeeded").json()
    assert [job["id"] for job in first["items"]] == ["job3", "job2"]
    seed(client, project, "new-job", created="2026-10-28T00:00:00+00:00")
    second = client.get(
        "/api/jobs",
        params={"limit": 2, "state": "succeeded", "cursor": first["next_cursor"]},
    ).json()
    assert [job["id"] for job in second["items"]] == ["job1", "job0"]
    assert second["next_cursor"] is None
    assert (
        client.get("/api/jobs", params={"cursor": first["next_cursor"]}).status_code
        == 422
    )
    assert (
        client.get("/api/projects", params={"cursor": first["next_cursor"]}).status_code
        == 422
    )
    assert client.get("/api/jobs?cursor=nonsense").status_code == 422
    assert client.get("/api/jobs?limit=0").status_code == 422
    assert client.get("/api/jobs?state=unknown").status_code == 422


def test_resume_eligibility_reflects_workspace_repair(client, tmp_path):
    project = create(client, tmp_path)
    seed(client, project, "finished")
    (client.app.state.workspace.projects / "bad.json").write_text("broken")
    assert not client.get("/api/jobs/finished").json()["actions"]["can_resume"]


def test_logs_and_artifacts_have_explicit_cursors_and_download_links(client, tmp_path):
    project = create(client, tmp_path)
    directory = seed(client, project, "finished")
    (directory / "console.log").write_text("abcdefghij", encoding="utf-8")
    (directory / "output/weights #1.bin").write_bytes(b"weights")
    first = client.get("/api/jobs/finished/logs?offset=0&limit=4").json()
    assert first == {"text": "abcd", "next_offset": 4, "size": 10, "eof": False}
    assert client.get("/api/jobs/finished/logs?offset=4").json()["text"] == "efghij"
    tail = client.get("/api/jobs/finished/logs?tail=3").json()
    assert tail["text"] == "hij" and tail["eof"]
    assert client.get("/api/jobs/finished/logs?tail=3&offset=0").status_code == 422
    artifact = client.get("/api/jobs/finished/artifacts").json()["items"][0]
    assert artifact["download_url"].endswith("weights%20%231.bin")
    assert client.get(artifact["download_url"]).content == b"weights"


def test_openapi_uses_stable_operations_and_separate_input_output_models(client):
    schema = client.get("/api/openapi.json").json()
    assert schema["paths"]["/api/jobs"]["post"]["operationId"] == "start_job"
    assert (
        schema["paths"]["/api/jobs/{job_id}/resume"]["post"]["operationId"]
        == "resume_job"
    )
    assert "patch" in schema["paths"]["/api/projects/{project_id}"]
    assert "put" not in schema["paths"]["/api/projects/{project_id}"]
    assert "/api/projects/{project_id}/jobs" not in schema["paths"]
    assert "project" not in schema["components"]["schemas"]["JobView"]["properties"]
    assert "ProjectCreate" in schema["components"]["schemas"]


def test_invalid_timestamps_are_reported_as_workspace_issues(client, tmp_path):
    project = create(client, tmp_path)
    path = seed(client, project, "broken-time") / "job.json"
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["created_at"] = "not-a-timestamp"
    atomic_json(path, payload)
    assert client.get("/api/jobs").json()["items"] == []
    assert client.get("/api/health").json()["status"] == "degraded"


def test_patch_map_replacement_and_unregistration_do_not_reset_history(
    client, tmp_path
):
    project = create(client, tmp_path, environment={"OLD": "value"})
    seed(client, project, "archived")
    response = client.patch(f"/api/projects/{project['id']}", json={"environment": {}})
    assert response.status_code == 200 and response.json()["environment"] == {}
    assert client.delete(f"/api/projects/{project['id']}").status_code == 204
    result = client.get("/api/jobs/archived").json()
    assert result["project_name"] == project["name"]
    assert result["actions"]["can_resume"] is False


def test_default_command_requires_a_choice_only_when_ambiguous(client, tmp_path):
    project = create(
        client,
        tmp_path,
        commands={"evaluate": [sys.executable], "export": [sys.executable]},
    )
    response = client.post("/api/jobs", json={"project_id": project["id"]})
    assert (
        response.status_code == 422
        and response.json()["error"]["code"] == "command_required"
    )
    assert "evaluate" in response.json()["error"]["message"]
