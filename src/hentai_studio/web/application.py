from __future__ import annotations

import json
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit

if TYPE_CHECKING:
    from ..dashboard_app.state import DashboardState
    from ..studio import StudioService


@dataclass(frozen=True, slots=True)
class Response:
    body: bytes
    content_type: str = "application/json; charset=utf-8"
    status: int = HTTPStatus.OK
    headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def json(cls, payload: object, status: int = HTTPStatus.OK) -> Response:
        return cls(json.dumps(payload).encode("utf-8"), status=status)


class RequestError(ValueError):
    def __init__(self, message: str, status: int = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = status


def parse_object(body: bytes) -> dict:
    try:
        payload = json.loads(body or b"{}")
    except (ValueError, UnicodeError) as error:
        raise RequestError("request body must be valid UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise RequestError("request body must be a JSON object")
    return payload


class StudioApplication:
    """Transport-independent routing, shared by both server modes."""

    def __init__(self, service: StudioService, dashboard: DashboardState | None = None):
        self.service = service
        self.dashboard = dashboard
        self.static_root = Path(__file__).parents[1] / "dashboard_static"

    def dispatch(self, method: str, target: str, body: bytes = b"") -> Response:
        try:
            path = unquote(urlsplit(target).path)
            parts = path.strip("/").split("/")
            if parts[:3] == ["api", "v1", "runs"]:
                if method == "GET" and len(parts) == 3:
                    return Response.json({"runs": self.service.runs()})
                if len(parts) == 5:
                    run_id, operation = parts[3:]
                    if method == "GET" and operation == "status":
                        return Response.json(self.service.status(run_id))
                    if method == "GET" and operation == "checkpoints":
                        return Response.json({"checkpoints": self.service.checkpoints(run_id)})
                    if method == "POST" and operation == "chat":
                        payload = parse_object(body)
                        messages = payload.get("messages", [])
                        if not isinstance(messages, list) or not all(isinstance(item, dict) for item in messages):
                            raise RequestError("messages must be a list of chat messages")
                        tokens = payload.get("maxNewTokens", 128)
                        if isinstance(tokens, bool) or not isinstance(tokens, int) or not 1 <= tokens <= 256:
                            raise RequestError("maxNewTokens must be an integer between 1 and 256")
                        return Response.json(self.service.chat(run_id, messages, tokens))
            if method == "GET" and path == "/api/v1/storage":
                return Response.json(self.service.storage_status())
            if self.dashboard is not None:
                return self._dashboard_route(method, path, body)
            return Response.json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except RequestError as error:
            return Response.json({"error": str(error)}, error.status)
        except (ValueError, RuntimeError, OSError, TypeError) as error:
            return Response.json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _dashboard_route(self, method: str, path: str, body: bytes) -> Response:
        state = self.dashboard
        if method == "POST" and path == "/api/action":
            if len(body) > 16_384:
                raise RequestError("request too large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            payload = parse_object(body)
            action = payload.get("action")
            if action == "sample":
                state.generate_sample(payload)
            else:
                actions = {"stop": state.stop, "resume": state.resume, "start_diffusion": state.start_diffusion}
                if not isinstance(action, str) or action not in actions:
                    raise RequestError("unknown action")
                actions[action]()
            return Response.json({"ok": True})
        if method != "GET":
            return Response.json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        if path == "/api/status":
            return Response.json(state.snapshot())
        if path == "/api/checkpoint-catalog":
            return Response.json({"runs": state.checkpoint_catalog()})
        downloads = {"/progress/vae.csv": ("vae.csv", "VAE"), "/progress/diffuser.csv": ("diffuser.csv", "Diffuser")}
        if path in downloads:
            filename, stage = downloads[path]
            target = state.run_dir / "progress" / filename
            if not target.is_file():
                return Response.json({"error": "progress log is not available yet"}, HTTPStatus.NOT_FOUND)
            return Response(target.read_bytes(), "text/csv; charset=utf-8", headers={
                "Content-Disposition": f'attachment; filename="HENTAI-Studio-{stage}-progress.csv"',
            })
        if path.startswith("/samples/"):
            target = self._confined_file(state.sample_dir, path.removeprefix("/samples/"))
            if target and target.suffix.lower() == ".png":
                return Response(target.read_bytes(), "image/png")
            return Response.json({"error": "sample not found"}, HTTPStatus.NOT_FOUND)
        target = self._confined_file(self.static_root, "index.html" if path == "/" else path.lstrip("/"))
        types = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}
        if target and target.suffix in types:
            return Response(target.read_bytes(), types[target.suffix] + "; charset=utf-8")
        return Response.json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    @staticmethod
    def _confined_file(root: Path, name: str) -> Path | None:
        target = (root / name).resolve()
        return target if target.is_relative_to(root.resolve()) and target.is_file() else None
