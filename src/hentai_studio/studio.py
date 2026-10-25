"""API-only server entry point."""
from pathlib import Path


def run_studio(project: str | Path, storage_root: str | Path, host: str = "127.0.0.1", port: int = 7861) -> None:
    from .api.app import create_app
    from .api.server import serve
    from .api.services.runs import RunService

    serve(create_app(RunService(Path(project), Path(storage_root))), host, port)
