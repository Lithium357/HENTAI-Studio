from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StorageRoots:
    """Explicitly allowlisted bulk storage locations for workload artifacts."""

    root: Path

    @property
    def datasets(self) -> Path:
        return self.root / "datasets" / "llm"

    @property
    def models(self) -> Path:
        return self.root / "models" / "base"

    @property
    def cache(self) -> Path:
        return self.root / "caches" / "huggingface"

    @property
    def runs(self) -> Path:
        return self.root / "runs" / "llm"

    def resolve_under(self, candidate: str | Path, *, allowed: tuple[Path, ...] | None = None) -> Path:
        resolved = Path(candidate).expanduser().resolve()
        roots = allowed or (self.datasets.resolve(), self.models.resolve(), self.cache.resolve(), self.runs.resolve())
        if not any(resolved.is_relative_to(root) for root in roots):
            raise ValueError(f"path is outside configured HENTAI storage roots: {resolved}")
        return resolved
