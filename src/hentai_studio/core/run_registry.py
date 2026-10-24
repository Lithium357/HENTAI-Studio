from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .workload import RunDescription

_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


@dataclass(frozen=True, slots=True)
class RunRegistry:
    project: Path
    llm_runs: Path

    def discover(self) -> list[RunDescription]:
        runs = [*self._legacy_diffusion_runs(), *self._managed_runs()]
        return sorted(runs, key=lambda item: (item.workload_type, item.display_name.lower()))

    def get(self, run_id: str) -> RunDescription:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("invalid run id")
        for item in self.discover():
            if item.run_id == run_id:
                return item
        raise ValueError("run was not found")

    def _legacy_diffusion_runs(self) -> list[RunDescription]:
        root = self.project / "runs"
        if not root.is_dir():
            return []
        result: list[RunDescription] = []
        for run_dir in root.iterdir():
            config = run_dir / "config.json"
            if not run_dir.is_dir() or not config.is_file() or (run_dir / "run.json").is_file():
                continue
            try:
                raw = json.loads(config.read_text(encoding="utf-8"))
                if "run_dir" not in raw or "resolution" not in raw:
                    continue
            except (OSError, json.JSONDecodeError):
                continue
            result.append(RunDescription(run_dir.name, run_dir.name.replace("-", " ").title(), "diffusion", run_dir, "legacy", True))
        return result

    def _managed_runs(self) -> list[RunDescription]:
        if not self.llm_runs.is_dir():
            return []
        result: list[RunDescription] = []
        for run_dir in self.llm_runs.iterdir():
            identity = run_dir / "run.json"
            if not run_dir.is_dir() or not identity.is_file():
                continue
            try:
                raw = json.loads(identity.read_text(encoding="utf-8"))
                if raw.get("schema_version") != 1 or raw.get("workload_type") != "llm.causal":
                    continue
                run_id = str(raw["run_id"])
                if not _RUN_ID.fullmatch(run_id):
                    continue
                result.append(RunDescription(run_id, str(raw.get("display_name", run_id)), "llm.causal", run_dir, str(raw.get("state", "prepared"))))
            except (OSError, KeyError, TypeError, json.JSONDecodeError):
                continue
        return result
