import json
import os
import subprocess
import sys
import time
import psutil
import pytest
from hentai_studio.api.errors import ApiError
from hentai_studio.api.schemas import JobRequest, Project
from hentai_studio.jobs.files import ACTIVE, atomic_json
from hentai_studio.jobs.workspace import Workspace


@pytest.fixture
def workspace(tmp_path):
    service = Workspace(tmp_path / "workspace")
    service.acquire()
    yield service
    for job in service.list_jobs():
        if job.state in ACTIVE:
            service.stop_job(job.id)
            wait_job(service, job.id)
    service.close()


def register(workspace, tmp_path, script, **kwargs):
    root = tmp_path / "external project"
    root.mkdir(exist_ok=True)
    (root / "train.py").write_text(script, encoding="utf-8")
    return workspace.save_project(
        Project(
            id=kwargs.pop("id", "example"),
            name="External project",
            root=str(root),
            commands={
                "train": [sys.executable, "-u", "train.py"],
                "resume": [sys.executable, "-u", "train.py"],
            },
            **kwargs,
        ),
        create=True,
    )


def wait_job(service, job_id, states=None):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        job = service.get_job(job_id)
        if job.state in states if states else job.state not in ACTIVE:
            return job
        time.sleep(0.05)
    raise AssertionError(f"Job did not reach expected state: {job.model_dump()}")


TRAINER = """
import json, os
from pathlib import Path
out = Path(os.environ['STUDIO_OUTPUT_DIR'])
print('external trainer', Path.cwd().name, os.environ['CUSTOM'], flush=True)
(out / 'context.json').write_text(json.dumps({'resume': os.environ.get('STUDIO_RESUME_DIR'), 'output': str(out)}))
(out / 'metrics.jsonl').write_text('{' + '"step":1,"loss":2' + '}\\n' + '{' + '"step":2,"loss":1' + '}\\n')
(out / 'weights.bin').write_bytes(b'checkpoint')
""".replace("\\n", "\\n")


def test_external_command_outputs_environment_metrics_and_resume(workspace, tmp_path):
    register(workspace, tmp_path, TRAINER, environment={"CUSTOM": "own-environment"})
    first = workspace.start_job("example", JobRequest(command="train"))
    assert wait_job(workspace, first.id).state == "succeeded"
    assert (
        "external trainer external project own-environment"
        in workspace.logs(first.id).text
    )
    assert workspace.metrics(first.id).items == [
        {"step": 1.0, "loss": 2.0},
        {"step": 2.0, "loss": 1.0},
    ]
    assert "weights.bin" in [item.path for item in workspace.artifacts(first.id).items]
    second = workspace.start_job(
        "example", JobRequest(command="resume", resume_from=first.id)
    )
    assert wait_job(workspace, second.id).state == "succeeded"
    context = json.loads(workspace.output_file(second.id, "context.json").read_text())
    assert context["resume"] == str(workspace.jobs / first.id / "output")
    assert context["output"] != context["resume"]
    assert workspace.get_job(second.id).project.commands["train"][0] == sys.executable


def test_active_project_cannot_duplicate_edit_or_unregister(workspace, tmp_path):
    project = register(workspace, tmp_path, "import time; time.sleep(60)")
    job = workspace.start_job(project.id, JobRequest(command="train"))
    for action in (
        lambda: workspace.start_job(project.id, JobRequest(command="train")),
        lambda: workspace.save_project(project),
        lambda: workspace.delete_project(project.id),
    ):
        with pytest.raises(ApiError) as error:
            action()
        assert error.value.status == 409
    workspace.stop_job(job.id)
    assert wait_job(workspace, job.id).state == "stopped"
    with pytest.raises(ApiError):
        workspace.stop_job(job.id)


def test_server_restart_keeps_worker_and_workspace_lock(workspace, tmp_path):
    register(
        workspace, tmp_path, "import time; print('alive', flush=True); time.sleep(60)"
    )
    job = workspace.start_job("example", JobRequest(command="train"))
    running = wait_job(workspace, job.id, {"running"})
    other = Workspace(workspace.root)
    with pytest.raises(RuntimeError, match="already served"):
        other.acquire()
    workspace.close()
    other.acquire()
    try:
        assert other.get_job(job.id).worker_pid == running.worker_pid
        assert other.list_projects()[0].id == "example"
        other.stop_job(job.id)
        assert wait_job(other, job.id).state == "stopped"
    finally:
        other.close()


def test_stop_only_owns_job_tree(workspace, tmp_path):
    register(
        workspace,
        tmp_path,
        """
import subprocess, sys, time, os
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
Path(os.environ['STUDIO_OUTPUT_DIR'], 'child.pid').write_text(str(child.pid))
while True: time.sleep(.1)
""",
    )
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        job = workspace.start_job("example", JobRequest(command="train"))
        path = workspace.jobs / job.id / "output/child.pid"
        deadline = time.monotonic() + 15
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        child = psutil.Process(int(path.read_text()))
        workspace.stop_job(job.id)
        assert wait_job(workspace, job.id).state == "stopped"
        assert not child.is_running() or child.status() == psutil.STATUS_ZOMBIE
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait()


def test_failed_command_retains_code_and_launch_error(workspace, tmp_path):
    project = register(workspace, tmp_path, "import sys; print('failure'); sys.exit(7)")
    job = workspace.start_job(project.id, JobRequest(command="train"))
    result = wait_job(workspace, job.id)
    assert (result.state, result.exit_code) == ("failed", 7)
    project.commands["train"] = [str(tmp_path / "missing-program")]
    workspace.save_project(project)
    job = workspace.start_job(project.id, JobRequest(command="train"))
    assert wait_job(workspace, job.id).error


def test_artifact_confinement_metrics_and_partial_rows(workspace, tmp_path):
    register(workspace, tmp_path, "print('ok')")
    job = workspace.start_job("example", JobRequest(command="train"))
    wait_job(workspace, job.id)
    output = workspace.jobs / job.id / "output"
    (output / "metrics.jsonl").write_text(
        '{"step":1,"loss":3,"label":"text"}\ninvalid\n{"loss":NaN}\n{"loss":2}\n{"loss":'
    )
    assert workspace.metrics(job.id).items == [
        {"step": 1.0, "loss": 3.0},
        {"loss": 2.0},
    ]
    with pytest.raises(ApiError):
        workspace.output_file(job.id, "../job.json")
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    try:
        (output / "escape.txt").symlink_to(secret)
    except OSError:
        return  # Windows without developer-mode symlink permission.
    assert "escape.txt" not in [item.path for item in workspace.artifacts(job.id).items]
    with pytest.raises(ApiError):
        workspace.output_file(job.id, "escape.txt")


def test_csv_metrics_bounded_log_paging_and_project_snapshot(workspace, tmp_path):
    register(workspace, tmp_path, "print('123456789')", metrics_file="progress.csv")
    job = workspace.start_job("example", JobRequest(command="train"))
    wait_job(workspace, job.id)
    output = workspace.jobs / job.id / "output"
    (output / "progress.csv").write_text("step,accuracy,note\n1,0.7,a\n2,0.8,b\n")
    assert workspace.metrics(job.id).items[-1] == {"step": 2.0, "accuracy": 0.8}
    page = workspace.logs(job.id, limit=4)
    assert page.text == "1234" and page.next_offset == 4
    assert workspace.logs(job.id, offset=4, limit=3).text == "567"
    workspace.delete_project("example")
    assert workspace.get_job(job.id).project.metrics_file == "progress.csv"


def test_unknown_command_and_cross_project_resume(workspace, tmp_path):
    register(workspace, tmp_path, "print('ok')")
    with pytest.raises(ApiError) as error:
        workspace.start_job("example", JobRequest(command="unknown"))
    assert error.value.status == 422
    first = workspace.start_job("example", JobRequest(command="train"))
    wait_job(workspace, first.id)
    register(workspace, tmp_path, "print('ok')", id="other")
    with pytest.raises(ApiError) as error:
        workspace.start_job("other", JobRequest(command="resume", resume_from=first.id))
    assert error.value.status == 409


def test_reused_pid_never_counts_as_live_supervisor(workspace, tmp_path):
    register(workspace, tmp_path, "print('ok')")
    job = workspace.start_job("example", JobRequest(command="train"))
    finished = wait_job(workspace, job.id)
    path = workspace.jobs / job.id / "job.json"
    payload = finished.model_dump() | {
        "state": "running",
        "worker_pid": os.getpid(),
        "worker_created": 1.0,
    }
    atomic_json(path, payload)
    os.utime(path, (time.time() - 10, time.time() - 10))
    assert workspace.get_job(job.id).state == "interrupted"


def test_atomic_state_retries_transient_windows_reader_lock(tmp_path, monkeypatch):
    import hentai_studio.jobs.files as files

    target = tmp_path / "state.json"
    original = os.replace
    calls = []

    def replace(source, destination):
        calls.append(source)
        if len(calls) < 3:
            raise PermissionError("temporary reader handle")
        original(source, destination)

    monkeypatch.setattr(files.os, "replace", replace)
    atomic_json(target, {"state": "succeeded"})
    assert json.loads(target.read_text()) == {"state": "succeeded"}
    assert len(calls) == 3
    assert list(tmp_path.iterdir()) == [target]


def test_independent_projects_run_concurrently(workspace, tmp_path):
    register(workspace, tmp_path, "import time; time.sleep(60)", id="first")
    register(workspace, tmp_path, "import time; time.sleep(60)", id="second")
    first = workspace.start_job("first", JobRequest(command="train"))
    second = workspace.start_job("second", JobRequest(command="train"))
    assert wait_job(workspace, first.id, {"running"}).state == "running"
    assert wait_job(workspace, second.id, {"running"}).state == "running"
    workspace.stop_job(first.id)
    assert wait_job(workspace, first.id).state == "stopped"
    assert workspace.get_job(second.id).state == "running"
