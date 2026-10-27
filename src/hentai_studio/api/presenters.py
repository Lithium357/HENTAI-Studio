from ..jobs.files import ACTIVE
from ..models import Job
from .schemas import JobActions, JobLinks, JobView


def public_state(job: Job, workspace):
    stopping = (
        workspace.job_directory(job.id) / "stop"
    ).exists() and job.state in ACTIVE
    return "stopping" if stopping else job.state


class JobPresenter:
    def __init__(self, workspace):
        self.workspace = workspace
        self.registered = {project.id for project in workspace.list_projects()}
        self.busy_projects = {
            job.project_id
            for job in workspace.list_jobs()
            if job.state in ACTIVE or job.has_live_processes
        }
        self.needs_repair = bool(workspace.issues())

    def render(self, job: Job) -> JobView:
        state = public_state(job, self.workspace)
        busy = state in ACTIVE or job.has_live_processes
        base = f"/api/jobs/{job.id}"
        return JobView(
            id=job.id,
            project_id=job.project_id,
            project_name=job.project.name,
            command=job.command,
            resume_from=job.resume_from,
            state=state,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            exit_code=job.exit_code,
            error=job.error,
            has_live_processes=job.has_live_processes,
            actions=JobActions(
                can_stop=busy and state != "stopping",
                can_resume=not busy
                and not self.needs_repair
                and job.project_id in self.registered
                and job.project_id not in self.busy_projects,
            ),
            links=JobLinks(
                self=base,
                logs=base + "/logs",
                metrics=base + "/metrics",
                artifacts=base + "/artifacts",
                stop=base + "/stop",
                resume=base + "/resume",
            ),
        )
