"""Owns inference workers only. Training supervisors are never signaled here."""

import json
import os
import queue
import subprocess
import threading
from pathlib import Path

import psutil

from ..errors import StudioError
from ..jobs.processes import terminate_tree, verified_process


class Session:
    def __init__(self, process, checkpoint, device):
        self.process = process
        self.created = psutil.Process(process.pid).create_time()
        self.checkpoint = str(checkpoint)
        self.device = device
        self.lock = threading.Lock()
        self.responses = queue.Queue()
        self.ready = False
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            while line := self.process.stdout.readline(2_000_001):
                if len(line) > 2_000_000:
                    raise ValueError("Inference response exceeded the size limit.")
                response = json.loads(line)
                if not isinstance(response, dict):
                    raise TypeError("Expected an inference response object.")
                self.responses.put(response)
        except (OSError, ValueError, TypeError):
            self.responses.put(
                {"error": "The inference worker returned an invalid response."}
            )
        finally:
            self.responses.put(
                {
                    "error": "The inference worker exited. Check the inference log in the workspace's chat directory."
                }
            )

    def receive(self, timeout):
        try:
            response = self.responses.get(timeout=timeout)
        except queue.Empty as error:
            raise StudioError(
                504,
                "inference_timeout",
                "The local model did not respond in time. Unload it and try a smaller model or prompt.",
            ) from error
        if "error" in response:
            raise StudioError(502, "inference_failed", str(response["error"])[:2000])
        return response

    def close(self):
        process = verified_process(self.process.pid, self.created)
        if process:
            terminate_tree(process)
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        for pipe in (self.process.stdin, self.process.stdout):
            try:
                pipe.close()
            except OSError:
                pass

    def status(self):
        alive = self.process.poll() is None
        return {
            "loaded": self.ready and alive,
            "busy": self.lock.locked(),
            "checkpoint": self.checkpoint if alive else None,
            "device": self.device if alive else None,
        }


class ChatService:
    def __init__(self, workspace, *, runner=None):
        self.workspace = workspace
        self.runner = runner or Path(__file__).with_name("infer.py")
        self.sessions = {}
        self.lock = threading.RLock()

    def _project(self, project_id):
        project = self.workspace.get_project(project_id)
        if project.llm is None:
            raise StudioError(
                409,
                "not_llm_project",
                "Configure this project as an LLM project first.",
            )
        return project

    def status(self, project_id):
        project = self._project(project_id)
        with self.lock:
            session = self.sessions.get(project.id)
        return (
            session.status()
            if session
            else {"loaded": False, "busy": False, "checkpoint": None, "device": None}
        )

    def load(self, project_id, request):
        project = self._project(project_id)
        if request.job_id:
            job = self.workspace.get_job(request.job_id)
            if job.project_id != project.id:
                raise StudioError(
                    422, "wrong_project", "Choose a checkpoint from this project."
                )
            output = self.workspace.job_directory(job.id) / "output"
            checkpoint = (output / request.checkpoint).resolve()
            if not checkpoint.is_relative_to(output.resolve()):
                raise StudioError(
                    422,
                    "invalid_checkpoint",
                    "The selected checkpoint must stay inside the job's output directory.",
                )
        else:
            checkpoint = Path(request.checkpoint).expanduser()
            if not checkpoint.is_absolute():
                checkpoint = Path(project.root) / checkpoint
            checkpoint = checkpoint.resolve()
        if not checkpoint.is_dir() or not (checkpoint / "config.json").is_file():
            raise StudioError(
                422,
                "invalid_checkpoint",
                "Choose a local model/checkpoint directory containing config.json and saved model weights.",
            )
        tokenizer = request.tokenizer or project.llm.tokenizer
        tokenizer_path = Path(tokenizer).expanduser()
        if not tokenizer_path.is_absolute():
            tokenizer_path = Path(project.root) / tokenizer_path
        with self.workspace._lock, self.lock:
            if self.workspace.get_project(project.id) != project:
                raise StudioError(
                    409,
                    "project_changed",
                    "The project changed during model loading. Try again.",
                )
            if request.device == "cuda" and any(
                self.workspace._busy(job) for job in self.workspace.list_jobs()
            ):
                raise StudioError(
                    409,
                    "training_active",
                    "GPU inference is disabled while a training job is active. Use CPU chat or wait for training to finish.",
                )
            existing = self.sessions.get(project.id)
            if existing and existing.process.poll() is None:
                raise StudioError(
                    409,
                    "model_loaded",
                    "Unload the current chat model before loading another checkpoint.",
                )
            if existing:
                existing.close()
            # Inference is opt-in, with at most one loaded model per Studio service.
            if any(s.process.poll() is None for s in self.sessions.values()):
                raise StudioError(
                    409,
                    "model_loaded",
                    "Unload the chat model in the other project first.",
                )
            log_root = self.workspace.root / "chat"
            log_root.mkdir(exist_ok=True)
            env = os.environ.copy()
            env.update(project.environment)
            env.update(
                HF_HUB_OFFLINE="1",
                TRANSFORMERS_OFFLINE="1",
                TOKENIZERS_PARALLELISM="false",
            )
            try:
                with (log_root / (project.id + ".log")).open("ab") as log:
                    process = subprocess.Popen(
                        [project.llm.python, "-u", str(self.runner)],
                        cwd=project.root,
                        env=env,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=log,
                        text=True,
                        encoding="utf-8",
                        start_new_session=os.name != "nt",
                        creationflags=subprocess.CREATE_NO_WINDOW
                        if os.name == "nt"
                        else 0,
                    )
                session = Session(process, checkpoint, request.device)
                self.sessions[project.id] = session
            except (OSError, psutil.Error) as error:
                raise StudioError(
                    503,
                    "inference_launch_failed",
                    "Cannot start the inference Python executable. Check the project configuration.",
                ) from error
        try:
            with session.lock:
                session.process.stdin.write(
                    json.dumps(
                        {
                            "checkpoint": str(checkpoint),
                            "tokenizer": str(tokenizer_path),
                            "device": request.device,
                        }
                    )
                    + "\n"
                )
                session.process.stdin.flush()
                response = session.receive(120)
                if response.get("ready") is not True:
                    raise StudioError(
                        502,
                        "inference_failed",
                        "The local inference worker did not report ready.",
                    )
                session.ready = True
        except (StudioError, OSError) as error:
            session.close()
            if isinstance(error, StudioError):
                raise
            raise StudioError(
                502,
                "inference_failed",
                "The inference worker disconnected during model loading.",
            ) from error
        return session.status()

    def unload(self, project_id):
        project = self._project(project_id)
        with self.lock:
            session = self.sessions.get(project.id)
        if session:
            session.close()
            with self.lock:
                if self.sessions.get(project.id) is session:
                    self.sessions.pop(project.id, None)
        return {"loaded": False, "busy": False, "checkpoint": None, "device": None}

    def complete(self, project_id, request):
        project = self._project(project_id)
        with self.lock:
            session = self.sessions.get(project.id)
        if not session or not session.status()["loaded"]:
            raise StudioError(
                409,
                "model_not_loaded",
                "Load a local checkpoint in the chat panel first.",
            )
        if not session.lock.acquire(blocking=False):
            raise StudioError(
                409,
                "inference_busy",
                "This model is already responding. Wait before sending another prompt.",
            )
        try:
            session.process.stdin.write(request.model_dump_json() + "\n")
            session.process.stdin.flush()
            response = session.receive(120)
            return {"content": response["content"], "tokens": response["tokens"]}
        except (OSError, KeyError) as error:
            session.close()
            raise StudioError(
                502,
                "inference_failed",
                "The local inference worker disconnected or returned an invalid response.",
            ) from error
        except StudioError as error:
            if error.code == "inference_timeout":
                session.close()
            raise
        finally:
            session.lock.release()

    def require_project_editable(self, project):
        with self.lock:
            session = self.sessions.get(project.id)
            if session and session.process.poll() is None:
                raise StudioError(
                    409,
                    "chat_model_loaded",
                    "Unload this project's chat model before editing or unregistering it.",
                )

    def require_training_available(self, project, request):
        with self.lock:
            if any(
                s.device == "cuda" and s.process.poll() is None
                for s in self.sessions.values()
            ):
                raise StudioError(
                    409,
                    "gpu_chat_active",
                    "Unload the GPU chat model before starting another job.",
                )

    def close(self):
        for session in list(self.sessions.values()):
            session.close()
