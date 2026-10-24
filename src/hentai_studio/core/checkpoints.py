from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path


def atomic_checkpoint(directory: Path, step: int, writer: Callable[[Path], None], required: tuple[str, ...]) -> Path:
    """Write a complete checkpoint beside its destination, then publish it atomically."""
    if step < 0:
        raise ValueError("checkpoint step must be non-negative")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"step-{step}"
    if target.exists():
        raise ValueError(f"checkpoint already exists: {target}")
    temporary = Path(tempfile.mkdtemp(prefix=f".step-{step}-", dir=directory))
    try:
        writer(temporary)
        missing = [name for name in required if not (temporary / name).is_file()]
        if missing:
            raise ValueError(f"checkpoint writer did not create required files: {', '.join(missing)}")
        os.replace(temporary, target)
        return target
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def rotate_complete(directory: Path, keep: int, required: tuple[str, ...]) -> list[Path]:
    if keep <= 0:
        raise ValueError("keep must be positive")
    candidates: list[tuple[int, Path]] = []
    for path in directory.glob("step-*") if directory.is_dir() else ():
        try:
            step = int(path.name.removeprefix("step-"))
        except ValueError:
            continue
        if all((path / name).is_file() for name in required):
            candidates.append((step, path))
    candidates.sort(reverse=True)
    removed: list[Path] = []
    for _, path in candidates[keep:]:
        shutil.rmtree(path)
        removed.append(path)
    return removed
