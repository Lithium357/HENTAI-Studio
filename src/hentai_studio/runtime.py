"""Locations owned by the installed Studio application."""
from __future__ import annotations

import os
from pathlib import Path


def hardware_probe() -> Path:
    override = os.environ.get("HENTAI_HARDWARE_PROBE")
    return Path(override) if override else Path(__file__).with_name("bin") / "hardware_probe.exe"


def process_entries():
    """Process telemetry is available under Linux/WSL, and absent elsewhere."""
    root = Path("/proc")
    return root.iterdir() if root.is_dir() else ()
