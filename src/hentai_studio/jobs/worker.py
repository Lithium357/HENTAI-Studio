"""Durable job supervisor. Survives dashboard restarts; only owns its child tree."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import psutil

from .files import atomic_json, now, read_json


def terminate_tree(process):
    try:
        descendants = process.children(recursive=True)
    except psutil.NoSuchProcess:
        descendants = []
    owned = descendants + [process]
    for child in owned:
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(owned, timeout=5)
    for child in alive:
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(alive, timeout=5)


def run(directory):
    job_file = directory / "job.json"
    job = read_json(job_file)
    worker = psutil.Process()
    job.update(
        worker_pid=worker.pid, worker_created=worker.create_time(), started_at=now()
    )
    process = None
    stopped = False
    descendants = []

    def stop_signal(*_):
        (directory / "stop").touch()

    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    try:
        if (directory / "stop").exists():
            job["state"] = "stopped"
            return
        project = job["project"]
        output = directory / "output"
        output.mkdir(exist_ok=True)
        substitutions = {"{output_dir}": str(output), "{project_root}": project["root"]}

        def expand(value):
            for token, replacement in substitutions.items():
                value = value.replace(token, replacement)
            return value

        env = os.environ.copy()
        env.update(
            {key: expand(value) for key, value in project["environment"].items()}
        )
        env.update(
            STUDIO_OUTPUT_DIR=str(output),
            STUDIO_JOB_ID=job["id"],
            STUDIO_PROJECT_ID=job["project_id"],
        )
        # Never inherit another job's resume marker.
        env.pop("STUDIO_RESUME_DIR", None)
        if job["resume_from"]:
            env["STUDIO_RESUME_DIR"] = str(
                directory.parent / job["resume_from"] / "output"
            )
        argv = [expand(part) for part in project["commands"][job["command"]]]
        with (directory / "console.log").open("ab", buffering=0) as log:
            process = subprocess.Popen(
                argv,
                cwd=project["root"],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                shell=False,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                if os.name == "nt"
                else 0,
                start_new_session=os.name != "nt",
            )
            try:
                owner = psutil.Process(process.pid)
            except psutil.NoSuchProcess:
                owner = None
            job["state"] = "running"
            atomic_json(job_file, job)
            while process.poll() is None:
                if owner:
                    try:
                        descendants.extend(
                            child
                            for child in owner.children(recursive=True)
                            if child not in descendants
                        )
                    except psutil.NoSuchProcess:
                        pass
                if (directory / "stop").exists():
                    stopped = True
                    job["state"] = "stopping"
                    atomic_json(job_file, job)
                    if owner:
                        terminate_tree(owner)
                    break
                time.sleep(0.1)
            code = process.wait()
            job.update(
                exit_code=code,
                state="stopped"
                if stopped
                else ("succeeded" if code == 0 else "failed"),
            )
    except Exception as error:
        if process is not None and process.poll() is None:
            terminate_tree(psutil.Process(process.pid))
        job.update(state="failed", error=str(error))
    finally:
        # A trainer may leave background workers behind after its main process exits.
        # psutil Process objects retain creation time to avoid acting on reused PIDs.
        for child in descendants:
            if child.is_running():
                terminate_tree(child)
        job["finished_at"] = now()
        atomic_json(job_file, job)


if __name__ == "__main__":
    run(Path(sys.argv[1]).resolve())
