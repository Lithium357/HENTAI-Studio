"""Durable external-command supervisor. No model or web dependencies."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import psutil

from .files import atomic_json, now, read_json
from .processes import terminate_tree, verified_process


def run(directory: Path):
    job_file = directory / "job.json"
    job = read_json(job_file)
    worker = psutil.Process()
    job.update(
        worker_pid=worker.pid, worker_created=worker.create_time(), started_at=now()
    )
    atomic_json(job_file, job)
    process = None
    owned = {}  # PID + creation time protects recorded descendants across PID reuse.
    stopped = False
    signaled = False

    def stop_signal(*_):
        nonlocal signaled
        signaled = True

    def remember(candidate):
        identity = (candidate.pid, candidate.create_time())
        if identity not in owned:
            owned[identity] = candidate
            atomic_json(
                directory / "processes.json",
                [{"pid": pid, "created": created} for pid, created in owned],
            )

    def cleanup():
        failures = []
        for pid, created in list(owned):
            try:
                candidate = verified_process(pid, created)
                if candidate:
                    terminate_tree(candidate)
            except (psutil.Error, OSError) as error:
                failures.append(str(error))
        return failures

    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    try:
        # The parent persists ownership before the trainer is allowed to start.
        # This prevents a slow Python startup from looking like an abandoned job.
        deadline = time.monotonic() + 10
        while not (directory / "supervisor.json").exists():
            if time.monotonic() > deadline:
                raise RuntimeError(
                    "Supervisor launch was not committed; trainer was not started."
                )
            time.sleep(0.02)
        identity = read_json(directory / "supervisor.json")
        launcher = verified_process(identity["pid"], identity["created"])
        # Windows venv python.exe is a redirector that owns the actual interpreter.
        # Accept the committed launcher only when it is this process or an ancestor.
        if launcher is None or launcher.pid not in {
            worker.pid,
            *(parent.pid for parent in worker.parents()),
        }:
            raise RuntimeError("Supervisor launcher does not own this worker.")
        if signaled or (directory / "stop").exists():
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
            {
                (key.upper() if os.name == "nt" else key): expand(value)
                for key, value in project["environment"].items()
            }
        )
        env.update(
            STUDIO_OUTPUT_DIR=str(output),
            STUDIO_JOB_ID=job["id"],
            STUDIO_PROJECT_ID=job["project_id"],
        )
        env.setdefault("PYTHONUNBUFFERED", "1")
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
                start_new_session=os.name != "nt",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                owner = psutil.Process(process.pid)
                remember(owner)
                job.update(trainer_pid=owner.pid, trainer_created=owner.create_time())
            except psutil.NoSuchProcess:
                owner = None
            job["state"] = "running"
            atomic_json(job_file, job)
            while process.poll() is None:
                if owner:
                    try:
                        for child in owner.children(recursive=True):
                            remember(child)
                    except psutil.NoSuchProcess:
                        pass
                if signaled or (directory / "stop").exists():
                    stopped = True
                    job["state"] = "stopping"
                    atomic_json(job_file, job)
                    failures = cleanup()
                    if failures:
                        raise RuntimeError(
                            "Could not stop all job processes: " + "; ".join(failures)
                        )
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
        job.update(state="failed", error=str(error))
    finally:
        # Always finalize state, including errors during process enumeration or cleanup.
        failures = cleanup()
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired) as error:
                failures.append(str(error))
        if failures:
            job.update(
                state="failed",
                error="Could not clean up all job processes: " + "; ".join(failures),
            )
        job["finished_at"] = now()
        atomic_json(job_file, job)


if __name__ == "__main__":
    run(Path(sys.argv[1]).resolve())
