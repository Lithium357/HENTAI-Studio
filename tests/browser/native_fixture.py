"""Temporary API-only fixture for native Windows integration tests. No jobs or ML processes."""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

request_log = Path(sys.argv[1]) if len(sys.argv) > 1 else None
log_lock = threading.Lock()
names = [
    "Pakao 498M — full cleaned corpus · 100M ceiling",
    "Morderca 498M with Sample-Code (attempt 4)",
    "Mirtis — open-ended outcome training",
]
projects = [
    {
        "id": "demo",
        "name": "Scratch model experiments",
        "root": "/demo/project",
        "commands": {
            "train": ["python", "train.py"],
            "evaluate": ["python", "evaluate.py"],
        },
        "environment": {},
        "metrics_file": "metrics.jsonl",
        "llm": None,
    },
    {
        "id": "llm",
        "name": "Scratch LLM chat",
        "root": "/demo/llm",
        "commands": {"train": ["python", "train.py"]},
        "environment": {},
        "metrics_file": "metrics.jsonl",
        "llm": {
            "python": "python",
            "model": "config",
            "tokenizer": "tokenizer",
            "dataset": "train.jsonl",
        },
    },
]
jobs = [
    {
        "id": f"job-{i}",
        "project_id": "demo",
        "project_name": names[i % 3],
        "command": "train",
        "state": "running" if i == 0 else "succeeded",
        "created_at": f"2026-11-{22 - i:02}T11:19:00Z",
        "started_at": f"2026-11-{22 - i:02}T11:19:00Z",
        "finished_at": None if i == 0 else f"2026-11-{22 - i:02}T13:19:00Z",
        "has_live_processes": i == 0,
        "exit_code": None if i == 0 else 0,
        "error": None,
        "resume_from": None,
    }
    for i in range(11)
]
loaded = False


class API(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def response(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_request_path(self):
        if request_log:
            with log_lock, request_log.open("a", encoding="utf-8") as log:
                log.write(self.command + " " + self.path + "\n")

    def do_GET(self):
        self.log_request_path()
        path = urlsplit(self.path).path
        q = parse_qs(urlsplit(self.path).query)
        if path == "/api/hardware":
            return self.response(
                200,
                {
                    "scope": "backend_host",
                    "hostname": "training-host",
                    "platform": "Linux",
                    "sampled_at": "2026-11-23T12:00:00Z",
                    "age_seconds": 1,
                    "stale": False,
                    "collecting": False,
                    "cpu_pct": 12,
                    "ram_used_mb": 4096,
                    "ram_total_mb": 32768,
                    "gpus": [
                        {
                            "id": vendor,
                            "name": vendor + " test GPU",
                            "vendor": vendor,
                            "source": "fixture",
                            "utilization_pct": 0,
                            "memory_used_mb": 1024,
                            "memory_total_mb": 16384,
                            "shared_memory_mb": None,
                            "temperature_c": None,
                            "power_w": None,
                        }
                        for vendor in ("NVIDIA", "AMD", "Intel")
                    ],
                    "issues": [],
                },
            )
        if path == "/api/health":
            return self.response(
                200,
                {
                    "application": "hentai-studio",
                    "version": "native-fixture",
                    "status": "ok",
                    "location": "cloud",
                    "workspace": "/demo/workspace",
                    "issues": [],
                },
            )
        if path == "/api/projects":
            return self.response(
                200,
                {
                    "items": projects[1:] if "cursor" in q else projects[:1],
                    "next_cursor": None if "cursor" in q else "projects-2",
                },
            )
        if path == "/api/jobs":
            items = [
                j
                for j in jobs
                if not q.get("project_id") or j["project_id"] == q["project_id"][0]
            ]
            return self.response(
                200,
                {
                    "items": items[6:] if "cursor" in q else items[:6],
                    "next_cursor": "jobs-2"
                    if "cursor" not in q and len(items) > 6
                    else None,
                },
            )
        if path.endswith("/logs"):
            return self.response(
                200,
                {
                    "text": "Starting scratch trainer\nstep 1\rstep 2\rstep 3\nCheckpoint saved.\n",
                    "size": 70,
                },
            )
        if path.endswith("/metrics"):
            return self.response(
                200,
                {
                    "items": [
                        {
                            "step": i % 32,
                            "loss": 4 / (i / 10 + 1) + 0.02 * (i % 3),
                            "steps_per_second": 2.5,
                            "total_steps": 1000,
                        }
                        for i in range(64)
                    ],
                    "truncated": False,
                },
            )
        if path.endswith("/artifacts"):
            return self.response(
                200,
                {
                    "items": [{"path": "checkpoint.json", "size": 120}],
                    "truncated": False,
                },
            )
        if path.endswith("/artifacts/checkpoint.json"):
            return self.response(200, {"step": 64})
        if path.endswith("/chat"):
            return self.response(
                200,
                {
                    "loaded": loaded,
                    "busy": False,
                    "checkpoint": "/demo/model" if loaded else None,
                    "device": "cpu" if loaded else None,
                },
            )
        if path == "/api/repeated":
            return self.response(200, {"items": [], "next_cursor": "same"})
        if path == "/api/redirect":
            self.send_response(302)
            self.send_header("Location", "http://example.invalid/")
            self.end_headers()
            return
        if path == "/api/broken":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"not json")
            return
        for job in jobs:
            if path == "/api/jobs/" + job["id"]:
                return self.response(200, job)
        return self.response(404, {"error": {"message": "No such resource"}})

    def do_POST(self):
        global loaded
        self.log_request_path()
        path = urlsplit(self.path).path
        body = json.loads(
            self.rfile.read(int(self.headers.get("Content-Length", 0))) or "{}"
        )
        if path.endswith("/chat/load"):
            loaded = True
            return self.response(
                200,
                {
                    "loaded": True,
                    "device": "cpu",
                    "checkpoint": "/demo/model",
                    "busy": False,
                },
            )
        if path.endswith("/chat/unload"):
            loaded = False
            return self.response(
                200,
                {"loaded": False, "device": None, "checkpoint": None, "busy": False},
            )
        if path.endswith("/chat/completions"):
            return self.response(
                200,
                {
                    "content": "Local scratch reply: "
                    + body["messages"][-1]["content"],
                    "tokens": 8,
                },
            )
        if path.endswith("/stop"):
            job = next(j for j in jobs if j["id"] == path.split("/")[3])
            job.update(state="stopped", has_live_processes=False)
            return self.response(200, job)
        if path == "/api/projects":
            projects.append(body)
            return self.response(201, body)
        if path == "/api/jobs" or path.endswith("/resume"):
            job = jobs[-1].copy()
            job.update(id=f"new-job-{len(jobs)}", command=body.get("command", "train"))
            jobs.insert(0, job)
            return self.response(201, job)
        return self.response(404, {"error": {"message": "No such resource"}})

    def do_PATCH(self):
        self.log_request_path()
        body = json.loads(
            self.rfile.read(int(self.headers.get("Content-Length", 0))) or "{}"
        )
        p = next(p for p in projects if p["id"] == self.path.split("/")[3])
        p.update(body)
        self.response(200, p)

    def do_DELETE(self):
        self.log_request_path()
        projects[:] = [p for p in projects if p["id"] != self.path.split("/")[3]]
        self.send_response(204)
        self.end_headers()


server = ThreadingHTTPServer(("127.0.0.1", 0), API)
print(json.dumps({"port": server.server_port}), flush=True)
server.serve_forever()
