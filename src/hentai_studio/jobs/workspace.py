from __future__ import annotations

import csv
import io
import json
import math
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import psutil

from ..api.errors import ApiError
from ..api.schemas import (
    Artifact,
    Artifacts,
    Job,
    JobRequest,
    LogPage,
    Metrics,
    Project,
)
from .files import ACTIVE, atomic_json, confined, now, read_json


class Workspace:
    """Persistence and commands; the worker is the sole writer of job lifecycle state."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.projects = self.root / "projects"
        self.jobs = self.root / "jobs"
        self.projects.mkdir(parents=True, exist_ok=True)
        self.jobs.mkdir(exist_ok=True)
        self._lock = threading.RLock()
        self._lease = None
        self._workers: list[subprocess.Popen] = []

    def acquire(self):
        self._lease = (self.root / "workspace.lock").open("a+b")
        self._lease.seek(0)
        self._lease.write(b"0")
        self._lease.flush()
        self._lease.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._lease.close()
            self._lease = None
            raise RuntimeError(
                "This workspace is already served by another Studio process."
            ) from None

    def close(self):
        # Workers deliberately survive a dashboard restart.
        self._reap()
        if self._lease:
            if os.name == "nt":
                import msvcrt

                self._lease.seek(0)
                msvcrt.locking(self._lease.fileno(), msvcrt.LK_UNLCK, 1)
            self._lease.close()
            self._lease = None

    def _reap(self):
        self._workers = [worker for worker in self._workers if worker.poll() is None]

    @staticmethod
    def _identifier(value):
        import re

        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", value):
            raise ApiError(404, "not_found", "Unknown identifier.")
        return value

    def list_projects(self):
        return [
            Project.model_validate(read_json(path))
            for path in sorted(self.projects.glob("*.json"))
        ]

    def get_project(self, project_id):
        path = self.projects / (self._identifier(project_id) + ".json")
        if not path.is_file():
            raise ApiError(404, "project_not_found", "Project does not exist.")
        return Project.model_validate(read_json(path))

    def save_project(self, project: Project, *, create=False):
        with self._lock:
            path = self.projects / (project.id + ".json")
            if create and path.exists():
                raise ApiError(
                    409, "project_exists", "A project with this ID already exists."
                )
            if not create:
                self.get_project(project.id)
            if any(
                job.project_id == project.id and job.state in ACTIVE
                for job in self.list_jobs()
            ):
                raise ApiError(
                    409,
                    "project_busy",
                    "Stop the active job before changing this project.",
                )
            root = Path(project.root).expanduser()
            if not root.is_absolute() or not root.is_dir():
                raise ApiError(
                    422,
                    "invalid_project_root",
                    "Project root must be an existing absolute directory on the Studio host.",
                )
            project = project.model_copy(update={"root": str(root.resolve())})
            atomic_json(path, project.model_dump())
            return project

    def delete_project(self, project_id):
        with self._lock:
            self.get_project(project_id)
            if any(
                job.project_id == project_id and job.state in ACTIVE
                for job in self.list_jobs()
            ):
                raise ApiError(
                    409,
                    "project_busy",
                    "Stop the active job before removing this project.",
                )
            (self.projects / (project_id + ".json")).unlink()

    def job_directory(self, job_id):
        path = self.jobs / self._identifier(job_id)
        if not (path / "job.json").is_file():
            raise ApiError(404, "job_not_found", "Job does not exist.")
        return path

    def get_job(self, job_id):
        with self._lock:
            directory = self.job_directory(job_id)
            job = Job.model_validate(read_json(directory / "job.json"))
            if job.state in ACTIVE:
                alive = False
                if job.worker_pid and job.worker_created:
                    try:
                        process = psutil.Process(job.worker_pid)
                        alive = (
                            process.is_running()
                            and abs(process.create_time() - job.worker_created) < 0.01
                            and process.status() != psutil.STATUS_ZOMBIE
                        )
                    except psutil.NoSuchProcess:
                        pass
                    except psutil.AccessDenied:
                        alive = True  # Do not misclassify a process we cannot inspect.
                # The initial file is durable before the worker starts and claims it.
                if (
                    not alive
                    and time.time() - (directory / "job.json").stat().st_mtime > 5
                ):
                    job = job.model_copy(
                        update={
                            "state": "interrupted",
                            "finished_at": now(),
                            "error": "Job supervisor exited unexpectedly; inspect console.log and project processes before restarting.",
                        }
                    )
                    atomic_json(directory / "job.json", job.model_dump())
            return job

    def list_jobs(self, project_id=None):
        self._reap()
        jobs = [self.get_job(path.parent.name) for path in self.jobs.glob("*/job.json")]
        return sorted(
            (job for job in jobs if project_id is None or job.project_id == project_id),
            key=lambda job: job.created_at,
            reverse=True,
        )

    def start_job(self, project_id, request: JobRequest):
        with self._lock:
            project = self.get_project(project_id)
            if request.command not in project.commands:
                raise ApiError(
                    422,
                    "unknown_command",
                    "This project has no command with that name.",
                )
            if any(job.state in ACTIVE for job in self.list_jobs(project_id)):
                raise ApiError(
                    409, "project_busy", "This project already has an active job."
                )
            if request.resume_from:
                previous = self.get_job(request.resume_from)
                if previous.project_id != project_id or previous.state in ACTIVE:
                    raise ApiError(
                        409,
                        "invalid_resume",
                        "Resume source must be a finished job from this project.",
                    )
            job_id = uuid.uuid4().hex
            directory = self.jobs / job_id
            directory.mkdir()
            (directory / "output").mkdir()
            job = Job(
                id=job_id,
                project_id=project_id,
                command=request.command,
                project=project,
                resume_from=request.resume_from,
                state="starting",
                created_at=now(),
            )
            atomic_json(directory / "job.json", job.model_dump())
            try:
                with (directory / "supervisor.log").open("ab") as log:
                    worker = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "hentai_studio.jobs.worker",
                            str(directory),
                        ],
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=os.name != "nt",
                        creationflags=subprocess.CREATE_NO_WINDOW
                        if os.name == "nt"
                        else 0,
                    )
                self._workers.append(worker)
            except OSError as error:
                job = job.model_copy(
                    update={
                        "state": "failed",
                        "error": str(error),
                        "finished_at": now(),
                    }
                )
                atomic_json(directory / "job.json", job.model_dump())
                raise ApiError(503, "launch_failed", str(error)) from error
            return job

    def stop_job(self, job_id):
        with self._lock:
            job = self.get_job(job_id)
            if job.state not in ACTIVE:
                raise ApiError(409, "job_finished", "This job has already finished.")
            (self.job_directory(job_id) / "stop").touch()
            return job

    def logs(self, job_id, offset=0, limit=65536, tail=False):
        path = self.job_directory(job_id) / "console.log"
        if not path.exists():
            return LogPage(text="", next_offset=0, size=0)
        with path.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - limit) if tail else min(offset, size))
            content = stream.read(limit)
            next_offset = stream.tell()
        return LogPage(
            text=content.decode("utf-8", errors="replace"),
            next_offset=next_offset,
            size=size,
        )

    def output_file(self, job_id, path):
        try:
            target = confined(self.job_directory(job_id) / "output", path)
        except (ValueError, OSError):
            raise ApiError(
                404,
                "artifact_not_found",
                "File does not exist inside this job's output directory.",
            ) from None
        if not target.is_file():
            raise ApiError(404, "artifact_not_found", "Artifact does not exist.")
        return target

    def metrics(self, job_id):
        job = self.get_job(job_id)
        try:
            path = self.output_file(job_id, job.project.metrics_file)
        except ApiError:
            return Metrics(items=[], truncated=False)
        limit = 1024 * 1024
        with path.open("rb") as stream:
            header = stream.readline(65536) if path.suffix == ".csv" else b""
            stream.seek(0, 2)
            size = stream.tell()
            truncated = size > limit
            stream.seek(max(len(header), size - limit) if truncated else len(header))
            if truncated:
                stream.readline(limit)  # Drop partial first row.
            data = stream.read(limit)
        # Ignore a row still being written by the trainer.
        if not data.endswith(b"\n"):
            data = data.rsplit(b"\n", 1)[0] + b"\n" if b"\n" in data else b""
        text = data.decode("utf-8", errors="replace")
        rows = (
            csv.DictReader(io.StringIO(header.decode("utf-8") + text))
            if header
            else text.splitlines()
        )
        items = []
        for row in rows:
            try:
                record = json.loads(row) if isinstance(row, str) else row
                if not isinstance(record, dict):
                    continue
                numeric = {}
                for key, value in record.items():
                    try:
                        number = float(value)
                    except (ValueError, TypeError):
                        continue
                    if math.isfinite(number):
                        numeric[str(key)] = number
                if numeric:
                    items.append(numeric)
            except (ValueError, TypeError):
                continue
        return Metrics(items=items[-1000:], truncated=truncated or len(items) > 1000)

    def artifacts(self, job_id):
        root = self.job_directory(job_id) / "output"
        items = []
        visited = 0
        # Do not traverse directory links or return file links outside the output root.
        for directory, directories, files in os.walk(root, followlinks=False):
            visited += 1
            if visited > 2000:
                return Artifacts(items=items, truncated=True)
            directories[:] = sorted(
                name
                for name in directories
                if not (Path(directory) / name).is_symlink()
                and (Path(directory) / name).resolve().is_relative_to(root.resolve())
            )
            for name in sorted(files):
                visited += 1
                if visited > 2000:
                    return Artifacts(items=items, truncated=True)
                path = Path(directory) / name
                try:
                    target = confined(root, path.relative_to(root))
                    items.append(
                        Artifact(
                            path=path.relative_to(root).as_posix(),
                            size=target.stat().st_size,
                        )
                    )
                except (ValueError, OSError):
                    continue
        return Artifacts(items=items, truncated=False)
