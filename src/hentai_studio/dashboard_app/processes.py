"""Discover only the processes associated with the selected engine run."""
from __future__ import annotations

import json
import os
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..runtime import process_entries

if TYPE_CHECKING:
    from .state import DashboardState


def process_tree(roots: list[int]) -> set[int]:
    children: dict[int, list[int]] = {}
    for entry in process_entries():
        if not entry.name.isdigit():
            continue
        try:
            # The comm field may contain spaces or parentheses.
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            children.setdefault(int(fields[1]), []).append(int(entry.name))
        except (OSError, ValueError, IndexError):
            continue
    result, pending = set(roots), list(roots)
    while pending:
        for child in children.get(pending.pop(), []):
            if child not in result:
                result.add(child)
                pending.append(child)
    return result


def option(args: list[str], name: str) -> str:
    for index, arg in enumerate(args):
        if arg == name:
            return args[index + 1]
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
    raise ValueError(f"missing {name}")


@dataclass(slots=True)
class TrainerProcesses:
    context: DashboardState

    def _same_run(self, config: Path, cwd: Path) -> bool:
        config = (cwd / config).resolve()
        if config == self.context.config:
            return True
        try:
            raw = json.loads(config.read_text(encoding="utf-8"))
            return (cwd / raw["run_dir"]).resolve() == self.context.run_dir.resolve()
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def trainer_pids(self) -> list[int]:
        result = []
        for entry in process_entries():
            if not entry.name.isdigit():
                continue
            try:
                args = (entry / "cmdline").read_bytes().decode().split("\0")
                command = " ".join(args)
                if "multiprocessing" in command or not any(
                    marker in command for marker in (
                        "scratchtag train-vae", "scratchtag train-diffusion",
                        "scratchtag.cli train-vae", "scratchtag.cli train-diffusion",
                        "train_dreambooth_lora_sdxl.py",
                    )
                ):
                    continue
                cwd = (entry / "cwd").resolve()
                if "train_dreambooth_lora_sdxl.py" in command:
                    matches = (cwd / option(args, "--output_dir")).resolve() == self.context.run_dir.resolve()
                else:
                    matches = self._same_run(Path(option(args, "--config")), cwd)
                if matches:
                    result.append(int(entry.name))
            except (OSError, ValueError, IndexError, UnicodeError):
                continue
        return sorted(result)

    def watchdog_pids(self) -> list[int]:
        defaults = {
            "train_watchdog.sh": "rx7800xt-256.json",
            "train_scratch_v2_watchdog.sh": "rx7800xt-256.json",
            "train_scratch_v3_x4_watchdog.sh": "rx7800xt-scratch-v3-x4-512.json",
            "train_sdxl_watchdog.sh": "rx7800xt-sdxl-lora-1024.json",
        }
        result = []
        for entry in process_entries():
            if not entry.name.isdigit():
                continue
            try:
                args = (entry / "cmdline").read_bytes().decode().split("\0")
                cwd = (entry / "cwd").resolve()
                script = next((Path(arg) for arg in args if Path(arg).name in defaults), None)
                if script is None or (cwd / script).resolve().parent != self.context.project / "scripts":
                    continue
                environment = dict(
                    value.split("=", 1) for value in (entry / "environ").read_bytes().decode().split("\0")
                    if "=" in value
                )
                config = Path(environment.get("HENTAI_CONFIG") or self.context.project / "configs" / defaults[script.name])
                if self._same_run(config, self.context.project):
                    result.append(int(entry.name))
            except (OSError, ValueError, UnicodeError):
                continue
        return sorted(result)

    def terminate_trainers(self) -> None:
        # A process group can contain an unrelated trainer started by the same
        # shell. Signal only this run's trainers and their worker descendants.
        roots = self.context.trainer_pids()
        for pid in sorted(process_tree(roots) - set(roots)) + roots:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
