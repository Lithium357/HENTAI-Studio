import json
import os
import subprocess
import sys
import time

import psutil
import pytest

from hentai_studio.errors import StudioError
from hentai_studio.jobs.files import ACTIVE, atomic_json
from hentai_studio.jobs.workspace import Workspace
from hentai_studio.models import JobRequest, Project


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
        with pytest.raises(StudioError) as error:
            action()
        assert error.value.status == 409
    workspace.stop_job(job.id)
    assert wait_job(workspace, job.id).state == "stopped"
    with pytest.raises(StudioError):
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
    with pytest.raises(StudioError):
        workspace.output_file(job.id, "../job.json")
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    try:
        (output / "escape.txt").symlink_to(secret)
    except OSError:
        return  # Windows without developer-mode symlink permission.
    assert "escape.txt" not in [item.path for item in workspace.artifacts(job.id).items]
    with pytest.raises(StudioError):
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
    with pytest.raises(StudioError) as error:
        workspace.start_job("example", JobRequest(command="unknown"))
    assert error.value.status == 422
    first = workspace.start_job("example", JobRequest(command="train"))
    wait_job(workspace, first.id)
    register(workspace, tmp_path, "print('ok')", id="other")
    with pytest.raises(StudioError) as error:
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


def test_dead_supervisor_can_stop_surviving_trainer_and_blocks_duplicate_start(
    workspace, tmp_path
):
    register(
        workspace, tmp_path, "import time; print('running', flush=True); time.sleep(60)"
    )
    job = workspace.start_job("example", JobRequest(command="train"))
    running = wait_job(workspace, job.id, {"running"})
    trainer = psutil.Process(running.trainer_pid)
    supervisor = psutil.Process(running.worker_pid)
    supervisor.kill()
    supervisor.wait(timeout=10)
    path = workspace.jobs / job.id / "job.json"
    os.utime(path, (time.time() - 10, time.time() - 10))
    interrupted = workspace.get_job(job.id)
    assert interrupted.state == "interrupted" and interrupted.has_live_processes
    with pytest.raises(StudioError) as error:
        workspace.start_job("example", JobRequest(command="train"))
    assert error.value.code == "project_busy"
    assert workspace.stop_job(job.id).state == "stopped"
    assert not trainer.is_running() or trainer.status() == psutil.STATUS_ZOMBIE


def test_corrupt_history_is_visible_and_fails_closed_without_hiding_valid_jobs(
    workspace, tmp_path
):
    register(workspace, tmp_path, "print('ok')")
    job = workspace.start_job("example", JobRequest(command="train"))
    wait_job(workspace, job.id)
    bad = workspace.jobs / "broken"
    bad.mkdir()
    (bad / "job.json").write_text("{")
    assert len(workspace.issues()) == 1
    assert workspace.list_jobs()[0].id == job.id
    with pytest.raises(StudioError) as error:
        workspace.start_job("example", JobRequest(command="train"))
    assert error.value.code == "workspace_needs_repair"
    assert workspace.logs(job.id).text.strip() == "ok"


def test_corrupt_registration_does_not_break_other_projects(workspace, tmp_path):
    register(workspace, tmp_path, "print('ok')")
    (workspace.projects / "broken.json").write_text('{"id":"wrong"}')
    assert [project.id for project in workspace.list_projects()] == ["example"]
    assert workspace.issues()[0].resource == "projects/broken.json"


def test_project_ids_cannot_collide_on_windows(workspace, tmp_path):
    project = register(workspace, tmp_path, "print('ok')", id="MixedCase")
    with pytest.raises(StudioError) as error:
        workspace.save_project(
            project.model_copy(update={"id": "mixedcase"}), create=True
        )
    assert error.value.code == "project_exists"
    saved = workspace.save_project(
        project.model_copy(update={"id": "mixedcase", "name": "Updated"})
    )
    assert saved.id == "MixedCase"
    assert workspace.get_project("MIXEDCASE").name == "Updated"
    assert not workspace.issues()


def test_empty_string_arguments_are_passed_literally(workspace, tmp_path):
    project = register(workspace, tmp_path, "import sys; print(repr(sys.argv[1]))")
    project.commands["train"].append("")
    workspace.save_project(project)
    job = workspace.start_job("example", JobRequest(command="train"))
    assert wait_job(workspace, job.id).state == "succeeded"
    assert workspace.logs(job.id).text.strip() == "''"


def test_csv_bom_and_oversized_field_do_not_break_job_observation(workspace, tmp_path):
    register(workspace, tmp_path, "print('ok')", metrics_file="progress.csv")
    job = workspace.start_job("example", JobRequest(command="train"))
    wait_job(workspace, job.id)
    path = workspace.jobs / job.id / "output/progress.csv"
    path.write_text("step,loss\n1,2\n2,1\n", encoding="utf-8-sig")
    assert workspace.metrics(job.id).items[-1] == {"step": 2.0, "loss": 1.0}
    path.write_text(
        "step,loss,note\n1,2," + '"' + "x" * 200000 + '"\n', encoding="utf-8"
    )
    assert workspace.metrics(job.id).items == []
    assert workspace.get_job(job.id).state == "succeeded"


def test_lease_double_acquire_cannot_release_original_lock(workspace):
    with pytest.raises(RuntimeError, match="already acquired"):
        workspace.acquire()
    other = Workspace(workspace.root)
    with pytest.raises(RuntimeError, match="already served"):
        other.acquire()
    workspace.close()
    other.acquire()
    other.close()


def test_windows_reader_lock_is_retried_without_reporting_corruption(
    tmp_path, monkeypatch
):
    from hentai_studio.jobs.files import read_json

    path = tmp_path / "job.json"
    path.write_text('{"state":"running"}')
    original = type(path).read_text
    calls = []

    def read(self, *args, **kwargs):
        calls.append(self)
        if len(calls) == 1:
            raise PermissionError("transient scanner lock")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(type(path), "read_text", read)
    assert read_json(path) == {"state": "running"}
    assert len(calls) == 2


def test_slow_supervisor_startup_does_not_admit_duplicate_job(
    workspace, tmp_path, monkeypatch
):
    import hentai_studio.jobs.workspace as module

    original = subprocess.Popen
    processes = []

    def slow_worker(*args, **kwargs):
        process = original(
            [sys.executable, "-c", "import time; time.sleep(60)"], **kwargs
        )
        processes.append(process)
        return process

    register(workspace, tmp_path, "print('never launched')")
    monkeypatch.setattr(module.subprocess, "Popen", slow_worker)
    try:
        job = workspace.start_job("example", JobRequest(command="train"))
        path = workspace.jobs / job.id / "job.json"
        os.utime(path, (time.time() - 20, time.time() - 20))
        assert workspace.get_job(job.id).state == "starting"
        with pytest.raises(StudioError) as error:
            workspace.start_job("example", JobRequest(command="train"))
        assert error.value.code == "project_busy"
    finally:
        for process in processes:
            process.terminate()
            process.wait(timeout=10)
        if processes:
            payload = json.loads(path.read_text(encoding="utf-8")) | {"state": "failed"}
            atomic_json(path, payload)
