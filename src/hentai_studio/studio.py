from pathlib import Path
from .api.app import create_app
from .api.server import serve


def run_studio(workspace: Path, host: str = "127.0.0.1", port: int = 7860) -> None:
    serve(create_app(workspace), host, port)
