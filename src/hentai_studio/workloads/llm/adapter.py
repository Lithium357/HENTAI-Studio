from __future__ import annotations

import json
import csv
import os
import subprocess
import time
from pathlib import Path

from ...runtime import hardware_probe, process_entries
from ...core.workload import CheckpointInfo, RunDescription, ValidationResult
from .checkpoint import RESUME_REQUIRED, WEIGHTS_REQUIRED
from .config import load_llm_config


class CausalLLMAdapter:
    workload_type = "llm.causal"

    def __init__(self) -> None:
        self._cpu_samples: dict[str, tuple[float, int]] = {}

    def validate_config(self, path: Path) -> ValidationResult:
        try:
            load_llm_config(path)
            return ValidationResult(True)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            return ValidationResult(False, (str(error),))

    def describe_run(self, run_dir: Path) -> RunDescription:
        identity = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        return RunDescription(str(identity["run_id"]), str(identity.get("display_name", identity["run_id"])), self.workload_type, run_dir, str(identity.get("state", "prepared")))

    def status(self, run_dir: Path) -> dict[str, object]:
        identity = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        rows: list[dict[str, object]] = []
        progress_file = run_dir / "progress" / "train.csv"
        if progress_file.is_file():
            with progress_file.open(encoding="utf-8", newline="") as handle:
                for raw in csv.DictReader(handle):
                    try:
                        eval_loss = raw.get("eval_loss")
                        rows.append({"step": int(raw["step"]), "total_steps": int(raw.get("total_steps") or 0), "loss": float(raw["train_loss"]), "eval_loss": float(eval_loss) if eval_loss else None, "seconds_per_step": float(raw.get("seconds_per_step") or 0), "tokens_per_second": float(raw.get("tokens_per_second") or 0), "tokens_seen": int(raw.get("tokens_seen") or 0)})
                    except (KeyError, TypeError, ValueError):
                        continue
        latest = rows[-1] if rows else {}
        pids: list[int] = []
        for entry in process_entries():
            if not entry.name.isdigit():
                continue
            try:
                arguments = [item for item in (entry / "cmdline").read_bytes().split(b"\0") if item]
                command = b" ".join(arguments).decode(errors="ignore")
                executable = (entry / "comm").read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if not ((executable.startswith("python") or executable in ("hentai-studio", "hentai-studio.exe")) and ("hentai-studio llm-train" in command or "hentai_studio.cli llm-train" in command) and "multiprocessing" not in command):
                continue
            try:
                config_index = arguments.index(b"--config")
                active_config = Path(arguments[config_index + 1].decode())
                if not active_config.is_absolute():
                    active_config = ((entry / "cwd").resolve() / active_config).resolve()
                active_run = Path(json.loads(active_config.read_text(encoding="utf-8"))["run_dir"]).resolve()
            except (OSError, ValueError, IndexError, KeyError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            if active_run == run_dir.resolve():
                pids.append(int(entry.name))
        now = time.monotonic(); cpu_ticks = 0
        for pid in pids:
            try:
                fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
                cpu_ticks += int(fields[13]) + int(fields[14])
            except (OSError, ValueError, IndexError):
                continue
        previous = self._cpu_samples.get(str(identity["run_id"]))
        self._cpu_samples[str(identity["run_id"])] = (now, cpu_ticks)
        cpu_usage = None if previous is None or not pids else max(0.0, min(100.0, (cpu_ticks - previous[1]) / os.sysconf("SC_CLK_TCK") / (now - previous[0]) / (os.cpu_count() or 1) * 100))
        rss = 0
        for pid in pids:
            try:
                for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                    if line.startswith("VmRSS:"):
                        rss += int(line.split()[1]) * 1024
            except (OSError, ValueError, IndexError):
                continue
        running = bool(pids)
        gpu: dict[str, object] = {}
        probe = hardware_probe()
        if running and probe.is_file():
            try:
                completed = subprocess.run([str(probe)], capture_output=True, text=True, timeout=4, check=False)
                line = next((item for item in reversed(completed.stdout.splitlines()) if item.startswith("{")), "")
                if line:
                    gpu = json.loads(line)
            except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
                pass
        gpu_power = gpu.get("gpu_board_power_w") if running else None
        cpu_power = None if cpu_usage is None else cpu_usage / 100 * 65.0
        workload_power = (float(gpu_power) if gpu_power is not None else 0.0) + (cpu_power or 0.0) if running else None
        hardware = {
            "available": running,
            "cpu_usage_pct": cpu_usage if running else None,
            "cpu_ram_bytes": rss if running else None,
            "cpu_ram_total_bytes": os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") if hasattr(os, "sysconf") else None,
            "gpu_usage_pct": gpu.get("gpu_usage_pct") if running else None,
            "gpu_vram_bytes": int(gpu["gpu_vram_mb"]) * 1024 * 1024 if running and gpu.get("gpu_vram_mb") is not None else None,
            "gpu_vram_total_bytes": 16 * 1024**3,
            "gpu_temp_c": gpu.get("gpu_temp_c") if running else None,
            "gpu_hotspot_c": gpu.get("gpu_hotspot_c") if running else None,
            "gpu_fan_rpm": gpu.get("gpu_fan_rpm") if running else None,
            "workload_power_w": workload_power,
            "scope_note": "CPU/RAM are attributed to the selected LLM trainer. Workload power is GPU board power plus a CPU-load estimate; WSL does not expose a reliable CPU package-power sensor." if running else "No active LLM trainer is registered for this run.",
        }
        return {"state": "running" if running else identity.get("state", "prepared"), "run_dir": str(run_dir), "workload_type": self.workload_type, "pids": sorted(pids), "progress": latest, "loss_history": rows[-240:], "hardware": hardware}

    def checkpoints(self, run_dir: Path) -> list[CheckpointInfo]:
        result: list[CheckpointInfo] = []
        mode = json.loads((run_dir / "config.json").read_text(encoding="utf-8")).get("mode")
        if mode == "lora":
            checkpoint_types = (("weights", WEIGHTS_REQUIRED), ("resume", RESUME_REQUIRED))
        else:
            checkpoint_types = (
                ("weights", ("model.safetensors", "metadata.json")),
                ("resume", ("model.safetensors", "metadata.json", "optimizer.pt", "trainer-state.json")),
            )
        for kind, required in checkpoint_types:
            root = run_dir / "checkpoints" / kind
            for path in root.glob("step-*") if root.is_dir() else ():
                try:
                    step = int(path.name.removeprefix("step-"))
                except ValueError:
                    continue
                complete = all((path / item).is_file() for item in required)
                size = sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
                result.append(CheckpointInfo(f"{kind}/{path.name}", step, path, complete, path.stat().st_mtime, size))
        return sorted(result, key=lambda item: item.modified_at, reverse=True)
