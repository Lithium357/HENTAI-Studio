from pathlib import Path

from .api.app import create_app
from .api.server import serve


def run_studio(
    workspace: Path,
    host: str = "127.0.0.1",
    port: int = 7860,
    log_file: Path | None = None,
) -> None:
    serve(create_app(workspace, host=host), host, port, log_file)
