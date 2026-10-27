from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import psutil
from pydantic import ValidationError

from ..errors import StudioError
from ..models import (
    Job,
    JobRequest,
    ProcessIdentity,
    Project,
    WorkspaceIssue,
)
from .files import ACTIVE, atomic_json, now, read_json
from .lease import WorkspaceLease
from .outputs import OutputReader
from .processes import terminate_tree, verified_process


class Workspace:
    """Persistence and commands; the worker is the sole writer of job lifecycle state."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.projects = self.root / "projects"
        self.jobs = self.root / "jobs"
        self.projects.mkdir(parents=True, exist_ok=True)
        self.jobs.mkdir(exist_ok=True)
        self._lock = threading.RLock()
        self._lease = WorkspaceLease(self.root)
        self._workers: list[subprocess.Popen] = []
        self.outputs = OutputReader(self.job_directory, self.get_job)

    def logs(self, *args, **kwargs):
        return self.outputs.logs(*args, **kwargs)

    def metrics(self, job_id):
        return self.outputs.metrics(job_id)

    def artifacts(self, job_id):
        return self.outputs.artifacts(job_id)

    def output_file(self, job_id, path):
        return self.outputs.output_file(job_id, path)

    def acquire(self):
        self._lease.acquire()

    def close(self):
        self._reap()
        self._lease.close()

    def _reap(self):
        self._workers = [worker for worker in self._workers if worker.poll() is None]

    @staticmethod
    def _identifier(value):
        import re

        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", value):
            raise StudioError(404, "not_found", "Unknown identifier.")
        return value

    def _load(self, path, model):
        try:
            value = model.model_validate(read_json(path))
            identifier = path.stem if model is Project else path.parent.name
            if value.id != identifier:
                raise ValueError("Stored identity does not match its file location.")
            return value
        except (OSError, ValueError, ValidationError) as error:
            raise StudioError(
                409,
                "invalid_workspace_record",
                f"Cannot read {path.relative_to(self.root)}. Restore or repair this workspace record.",
            ) from error

    def issues(self):
        issues = []
        seen = set()
        for path in sorted(self.projects.glob("*.json")):
            try:
                self._load(path, Project)
                if path.stem.casefold() in seen:
                    raise StudioError(
                        409,
                        "duplicate_project",
                        "Project IDs must be distinct ignoring case.",
                    )
                seen.add(path.stem.casefold())
            except StudioError as error:
                issues.append(
                    WorkspaceIssue(
                        resource=path.relative_to(self.root).as_posix(),
                        message=error.message,
                    )
                )
        for directory in sorted(self.jobs.iterdir()):
            if not directory.is_dir():
                continue
            try:
                job = self._load(directory / "job.json", Job)
                self._supervisor_identity(directory, job)
                self._owned_processes(directory)
            except StudioError as error:
                issues.append(
                    WorkspaceIssue(
                        resource=directory.relative_to(self.root).as_posix(),
                        message=error.message,
                    )
                )
        return issues

    def _require_healthy_history(self):
        if self.issues():
            raise StudioError(
                409,
                "workspace_needs_repair",
                "Repair the workspace records reported by /api/health before starting jobs or changing registrations.",
            )

    def list_projects(self):
        result = []
        for path in sorted(self.projects.glob("*.json")):
            try:
                result.append(self._load(path, Project))
            except StudioError:
                continue
        return result

    def _project_file(self, project_id):
        self._identifier(project_id)
        matches = [
            path
            for path in self.projects.glob("*.json")
            if path.stem.casefold() == project_id.casefold()
        ]
        if len(matches) > 1:
            raise StudioError(
                409,
                "duplicate_project",
                "Ambiguous project ID; repair duplicate registration files.",
            )
        return matches[0] if matches else self.projects / (project_id + ".json")

    def get_project(self, project_id):
        path = self._project_file(project_id)
        if not path.is_file():
            raise StudioError(404, "project_not_found", "Project does not exist.")
        return self._load(path, Project)

    def save_project(self, project: Project, *, create=False):
        with self._lock:
            self._require_healthy_history()
            path = self._project_file(project.id)
            if create and path.exists():
                raise StudioError(
                    409, "project_exists", "A project with this ID already exists."
                )
            if not create:
                existing = self.get_project(project.id)
                project = project.model_copy(update={"id": existing.id})
            if any(
                job.project_id == project.id and self._busy(job)
                for job in self.list_jobs()
            ):
                raise StudioError(
                    409,
                    "project_busy",
                    "Stop the active job before changing this project.",
                )
            root = Path(project.root).expanduser()
            if not root.is_absolute() or not root.is_dir():
                raise StudioError(
                    422,
                    "invalid_project_root",
                    "Project root must be an existing absolute directory on the Studio host.",
                )
            project = project.model_copy(update={"root": str(root.resolve())})
            atomic_json(path, project.model_dump())
            return project

    def delete_project(self, project_id):
        with self._lock:
            self._require_healthy_history()
            project = self.get_project(project_id)
            if any(
                job.project_id == project.id and self._busy(job)
                for job in self.list_jobs()
            ):
                raise StudioError(
                    409,
                    "project_busy",
                    "Stop the active job before removing this project.",
                )
            self._project_file(project_id).unlink()

    def job_directory(self, job_id):
        path = self.jobs / self._identifier(job_id)
        if (
            not path.resolve().is_relative_to(self.jobs.resolve())
            or not (path / "job.json").is_file()
        ):
            raise StudioError(404, "job_not_found", "Job does not exist.")
        return path

    @staticmethod
    def _busy(job):
        return job.state in ACTIVE or job.has_live_processes

    def _owned_processes(self, directory, job=None):
        path = directory / "processes.json"
        identities = []
        if path.exists():
            try:
                from ..models import ProcessIdentity

                identities = [
                    ProcessIdentity.model_validate(item) for item in read_json(path)
                ]
            except (OSError, ValueError, TypeError, ValidationError) as error:
                raise StudioError(
                    409,
                    "invalid_process_record",
                    "Cannot read job process identities; repair processes.json before restarting.",
                ) from error
        elif job and job.trainer_pid and job.trainer_created:
            from ..models import ProcessIdentity

            identities = [
                ProcessIdentity(pid=job.trainer_pid, created=job.trainer_created)
            ]
        processes = []
        for identity in identities:
            try:
                process = verified_process(identity.pid, identity.created)
                if process:
                    processes.append(process)
            except psutil.AccessDenied as error:
                raise StudioError(
                    409,
                    "process_access_denied",
                    "Cannot verify a job process; inspect its permissions before restarting.",
                ) from error
        return processes

    def _supervisor_identity(self, directory, job):
        if job.worker_pid and job.worker_created:
            return ProcessIdentity(pid=job.worker_pid, created=job.worker_created)
        path = directory / "supervisor.json"
        if not path.exists():
            return None
        try:
            return ProcessIdentity.model_validate(read_json(path))
        except (OSError, ValueError, ValidationError) as error:
            raise StudioError(
                409,
                "invalid_supervisor_record",
                "Cannot read supervisor identity; repair supervisor.json before restarting.",
            ) from error

    def get_job(self, job_id):
        with self._lock:
            directory = self.job_directory(job_id)
            job = self._load(directory / "job.json", Job)
            live = bool(self._owned_processes(directory, job))
            if job.state in ACTIVE:
                try:
                    identity = self._supervisor_identity(directory, job)
                    worker = (
                        verified_process(identity.pid, identity.created)
                        if identity
                        else None
                    )
                except psutil.AccessDenied:
                    worker = True  # Lack of permission is not evidence of death.
                if (
                    not worker
                    and time.time() - (directory / "job.json").stat().st_mtime > 5
                ):
                    job = job.model_copy(
                        update={
                            "state": "interrupted",
                            "finished_at": now(),
                            "error": "Job supervisor exited unexpectedly. Stop any surviving job processes before restarting.",
                        }
                    )
                    atomic_json(directory / "job.json", job.model_dump())
            return job.model_copy(update={"has_live_processes": live})

    def list_jobs(self, project_id=None):
        with self._lock:
            self._reap()
            jobs = []
            for path in self.jobs.glob("*/job.json"):
                try:
                    job = self.get_job(path.parent.name)
                    if (
                        project_id is None
                        or job.project_id.casefold() == project_id.casefold()
                    ):
                        jobs.append(job)
                except StudioError:
                    continue
            return sorted(jobs, key=lambda job: job.created_at, reverse=True)

    def start_job(self, project_id, request: JobRequest):
        with self._lock:
            self._require_healthy_history()
            project = self.get_project(project_id)
            project_id = project.id
            if request.command not in project.commands:
                raise StudioError(
                    422,
                    "unknown_command",
                    "This project has no command with that name.",
                )
            if any(self._busy(job) for job in self.list_jobs(project_id)):
                raise StudioError(
                    409, "project_busy", "This project already has an active job."
                )
            if request.resume_from:
                previous = self.get_job(request.resume_from)
                if previous.project_id != project_id or self._busy(previous):
                    raise StudioError(
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
                identity = psutil.Process(worker.pid)
                atomic_json(
                    directory / "supervisor.json",
                    {"pid": identity.pid, "created": identity.create_time()},
                )
            except (OSError, psutil.NoSuchProcess) as error:
                job = job.model_copy(
                    update={
                        "state": "failed",
                        "error": str(error),
                        "finished_at": now(),
                    }
                )
                atomic_json(directory / "job.json", job.model_dump())
                raise StudioError(503, "launch_failed", str(error)) from error
            return job

    def stop_job(self, job_id):
        with self._lock:
            job = self.get_job(job_id)
            directory = self.job_directory(job_id)
            if job.state not in ACTIVE and job.has_live_processes:
                processes = self._owned_processes(directory, job)
                if not processes:
                    raise StudioError(
                        409, "job_finished", "No verified job process remains to stop."
                    )
                for process in processes:
                    try:
                        terminate_tree(process)
                    except psutil.NoSuchProcess:
                        pass
                if self._owned_processes(directory, job):
                    raise StudioError(
                        409,
                        "stop_incomplete",
                        "Some job processes could not be stopped.",
                    )
                job = job.model_copy(
                    update={
                        "state": "stopped",
                        "has_live_processes": False,
                        "finished_at": now(),
                        "error": None,
                    }
                )
                atomic_json(directory / "job.json", job.model_dump())
                return job
            if job.state not in ACTIVE:
                raise StudioError(409, "job_finished", "This job has already finished.")
            (directory / "stop").touch()
            # The worker remains the sole writer while alive. Return current durable state.
            return job
