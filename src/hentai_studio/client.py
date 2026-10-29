"""Small synchronous Studio client using only the Python standard library.

with StudioClient() as studio:
    project = studio.create_project("/absolute/project", {"train": ["python", "train.py"]})
    job = studio.wait(studio.start_job(project["id"]))
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen


class StudioAPIError(Exception):
    """A structured API or transport failure; code and details are machine-readable."""

    def __init__(self, status, code, message, details=None):
        self.status, self.code, self.details = status, code, details or []
        super().__init__(message)


def _id(value):
    return quote(value["id"] if isinstance(value, dict) else value, safe="")


class StudioClient:
    def __init__(self, base_url="http://127.0.0.1:7860", *, timeout=15):
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "base_url must be the server origin, e.g. http://127.0.0.1:7860 (without /api)."
            )
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass  # urllib opens/closes each response; no session handles to retain.

    def _open(self, method, path, body=None):
        payload = (
            json.dumps(body, allow_nan=False).encode() if body is not None else None
        )
        request = Request(
            self.base_url + path,
            data=payload,
            method=method,
            headers={
                "Accept": "application/json",
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
        )
        try:
            return urlopen(request, timeout=self.timeout)
        except HTTPError as error:
            try:
                with error:
                    detail = json.load(error)["error"]
                raise StudioAPIError(
                    error.code, detail["code"], detail["message"], detail.get("details")
                ) from error
            except (ValueError, KeyError, TypeError):
                raise StudioAPIError(
                    error.code, "http_error", f"HTTP {error.code}: {error.reason}"
                ) from error
        except (URLError, TimeoutError) as error:
            raise StudioAPIError(
                None,
                "connection_error",
                f"Cannot reach Studio at {self.base_url}: {error}",
            ) from error

    def request(self, method, path, body=None):
        """Access any /api resource when a convenience method is not needed."""
        if not path.startswith("/api/"):
            raise ValueError("path must begin with /api/")
        try:
            with self._open(method, path, body) as response:
                if response.status == 204:
                    return None
                try:
                    return json.load(response)
                except ValueError as error:
                    raise StudioAPIError(
                        response.status,
                        "invalid_response",
                        "Studio returned a non-JSON response.",
                    ) from error
        except (URLError, OSError) as error:
            raise StudioAPIError(
                None, "connection_error", f"Cannot read the Studio response: {error}"
            ) from error

    def health(self):
        return self.request("GET", "/api/health")

    def _pages(self, path, *, page_size=50, **filters):
        if not 1 <= page_size <= 200:
            raise ValueError("page_size must be between 1 and 200")
        query = {key: value for key, value in filters.items() if value is not None}
        query["limit"] = page_size
        while True:
            page = self.request("GET", path + "?" + urlencode(query))
            yield from page["items"]
            if not page["next_cursor"]:
                return
            query["cursor"] = page["next_cursor"]

    def list_projects(self, *, page_size=50):
        return list(self._pages("/api/projects", page_size=page_size))

    def create_project(
        self,
        root,
        commands,
        *,
        name=None,
        id=None,
        environment=None,
        metrics_file="metrics.jsonl",
    ):
        body = {"root": str(root), "commands": commands, "metrics_file": metrics_file}
        for key, value in {"id": id, "name": name, "environment": environment}.items():
            if value is not None:
                body[key] = value
        return self.request("POST", "/api/projects", body)

    def get_project(self, project):
        return self.request("GET", f"/api/projects/{_id(project)}")

    def update_project(self, project, **changes):
        return self.request("PATCH", f"/api/projects/{_id(project)}", changes)

    def delete_project(self, project):
        return self.request("DELETE", f"/api/projects/{_id(project)}")

    def iter_jobs(self, *, project_id=None, state=None, page_size=50):
        return self._pages(
            "/api/jobs", page_size=page_size, project_id=project_id, state=state
        )

    def list_jobs(self, **filters):
        return list(self.iter_jobs(**filters))

    def start_job(self, project, command=None):
        body = {"project_id": project["id"] if isinstance(project, dict) else project}
        if command is not None:
            body["command"] = command
        return self.request("POST", "/api/jobs", body)

    def get_job(self, job):
        return self.request("GET", f"/api/jobs/{_id(job)}")

    def stop_job(self, job):
        return self.request("POST", f"/api/jobs/{_id(job)}/stop")

    def resume_job(self, job, command=None):
        return self.request(
            "POST",
            f"/api/jobs/{_id(job)}/resume",
            {"command": command} if command else {},
        )

    def wait(self, job, *, timeout=3600, poll_interval=0.5):
        if timeout <= 0 or poll_interval <= 0:
            raise ValueError("timeout and poll_interval must be positive")
        deadline = time.monotonic() + timeout
        while True:
            current = self.get_job(job)
            if current["state"] not in {"starting", "running", "stopping"}:
                return current
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Job {current['id']} is still {current['state']} after {timeout} seconds"
                )
            time.sleep(min(poll_interval, remaining))

    def logs(self, job, *, offset=None, limit=65536, tail=None):
        query = {
            key: value
            for key, value in {"offset": offset, "limit": limit, "tail": tail}.items()
            if value is not None
        }
        return self.request("GET", f"/api/jobs/{_id(job)}/logs?" + urlencode(query))

    def metrics(self, job):
        return self.request("GET", f"/api/jobs/{_id(job)}/metrics")

    def artifacts(self, job):
        return self.request("GET", f"/api/jobs/{_id(job)}/artifacts")

    def download_artifact(self, job, path, destination):
        url = f"/api/jobs/{_id(job)}/artifacts/{quote(path, safe='/')}"
        destination = Path(destination)
        with self._open("GET", url) as response, destination.open("wb") as target:
            shutil.copyfileobj(response, target)
        return destination

    def create_llm_project(
        self,
        root,
        *,
        model,
        tokenizer,
        dataset,
        python="python",
        name=None,
        id=None,
        **training,
    ):
        """Register a scratch-model project using local config, tokenizer and dataset paths."""
        body = {
            "root": str(root),
            "llm": {
                "model": str(model),
                "tokenizer": str(tokenizer),
                "dataset": str(dataset),
                "python": str(python),
                **training,
            },
        }
        if name is not None:
            body["name"] = name
        if id is not None:
            body["id"] = id
        return self.request("POST", "/api/projects", body)

    def chat_status(self, project):
        return self.request("GET", f"/api/projects/{_id(project)}/chat")

    def load_chat(self, project, checkpoint, *, job=None, device="cpu", tokenizer=""):
        body = {
            "checkpoint": str(checkpoint),
            "device": device,
            "tokenizer": str(tokenizer),
        }
        if job is not None:
            body["job_id"] = job["id"] if isinstance(job, dict) else job
        return self.request("POST", f"/api/projects/{_id(project)}/chat/load", body)

    def unload_chat(self, project):
        return self.request("POST", f"/api/projects/{_id(project)}/chat/unload")

    def chat(self, project, messages, *, temperature=0.7, max_tokens=128):
        return self.request(
            "POST",
            f"/api/projects/{_id(project)}/chat/completions",
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
