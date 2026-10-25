"""Public dashboard entry point; application services live in dashboard_app."""
from __future__ import annotations

from pathlib import Path

from .dashboard_app.state import DashboardState

__all__ = ["DashboardState", "run_dashboard"]


def run_dashboard(
    project: str | Path,
    config: str | Path,
    host: str = "127.0.0.1",
    port: int = 7860,
    storage_root: str | Path = "/mnt/d/HENTAI-Data",
) -> None:
    from .studio import StudioService
    from .web.application import StudioApplication
    from .web.server import serve

    project = Path(project).resolve()
    state = DashboardState(project, Path(config), project / "dashboard_samples")
    app = StudioApplication(StudioService(project, Path(storage_root)), state)
    serve(app, host, port)
