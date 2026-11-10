from pathlib import Path

from .api.app import create_app
from .api.schemas import StudioLocation
from .api.server import serve


def run_studio(
    workspace: Path,
    host: str = "127.0.0.1",
    port: int = 7860,
    log_file: Path | None = None,
    *,
    location: StudioLocation = "local",
) -> None:
    serve(create_app(workspace, host=host, location=location), host, port, log_file)
