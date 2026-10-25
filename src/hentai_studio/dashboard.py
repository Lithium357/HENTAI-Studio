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
    from .api.app import create_app
    from .api.services.runs import RunService
    from .api.services.diffusion import DiffusionService
    from .api.server import serve

    project = Path(project).resolve()
    state = DashboardState(project, Path(config), project / "dashboard_samples")
    app = create_app(RunService(project, Path(storage_root)), DiffusionService(state))
    serve(app, host, port)
