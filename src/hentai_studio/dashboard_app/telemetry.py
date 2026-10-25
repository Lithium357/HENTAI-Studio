from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..runtime import hardware_probe
from .processes import process_tree

if TYPE_CHECKING:
    from .state import DashboardState


@dataclass(slots=True)
class Telemetry:
    context: DashboardState
    process_ticks_at: float | None = None
    energy_at: float | None = None
    energy_kwh: float | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)
    hardware_cache: dict[str, object] = field(default_factory=dict)
    process_ticks: int | None = None
    hardware_sample_at: float = 0.0
    sample_roots: tuple[int, ...] = ()

    def hardware_metrics(self, roots: list[int]) -> dict[str, object]:
        with self.lock:
            return self._sample(roots)

    def _sample(self, roots: list[int]) -> dict[str, object]:
        now = time.monotonic()
        with self.lock:
            if self.hardware_cache and tuple(roots) == self.sample_roots and now - self.hardware_sample_at < 3.0:
                return self.hardware_cache

        pids = process_tree(roots)
        ticks = 0
        rss_bytes = 0
        for pid in pids:
            try:
                fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
                ticks += int(fields[11]) + int(fields[12])
                for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                    if line.startswith("VmRSS:"):
                        rss_bytes += int(line.split()[1]) * 1024
                        break
            except (OSError, ValueError, IndexError):
                continue

        cpu_pct: float | None = None
        if self.process_ticks is not None and self.process_ticks_at is not None and roots:
            elapsed = now - self.process_ticks_at
            if elapsed > 0:
                used_seconds = (ticks - self.process_ticks) / os.sysconf("SC_CLK_TCK")
                cpu_pct = max(0.0, used_seconds / elapsed / (os.cpu_count() or 1) * 100)
        self.process_ticks = ticks
        self.process_ticks_at = now

        mem_total = 0
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1]) * 1024
                    break
        except OSError:
            pass

        gpu: dict[str, object] = {}
        probe = hardware_probe()
        if roots and probe.exists():
            try:
                completed = subprocess.run(
                    [str(probe)], capture_output=True, text=True, timeout=4, check=False
                )
                line = next((item for item in reversed(completed.stdout.splitlines()) if item.startswith("{")), "")
                if line:
                    gpu = json.loads(line)
            except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
                pass

        cpu_package_w: float | None = None
        if roots:
            try:
                completed = subprocess.run(
                    [
                        "/mnt/c/Windows/System32/typeperf.exe",
                        r"\Energy Meter(rapl_package0_pkg)\Power", "-sc", "1",
                    ],
                    capture_output=True, text=True, timeout=6, check=False,
                )
                values = re.findall(r',"([\d.]+)"', completed.stdout)
                cpu_package_w = float(values[-1]) / 1000
            except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
                pass

        board_power = gpu.get("gpu_board_power_w") if roots else None
        cpu_attributed_w = (
            cpu_package_w * min(1.0, cpu_pct / 100) if cpu_package_w is not None and cpu_pct is not None else None
        )
        workload_w = (
            float(board_power or 0) + float(cpu_attributed_w or 0)
            if roots and (board_power is not None or cpu_attributed_w is not None) else None
        )
        energy_file = self.context.run_dir / "hardware-energy.json"
        if self.energy_kwh is None:
            try:
                self.energy_kwh = float(json.loads(energy_file.read_text())["kwh"])
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                self.energy_kwh = 0.0
        if self.energy_at is not None and workload_w is not None:
            elapsed = now - self.energy_at
            if 0 < elapsed < 30:
                self.energy_kwh += workload_w * elapsed / 3_600_000
        self.energy_at = now
        try:
            energy_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = energy_file.with_suffix(".tmp")
            temporary.write_text(json.dumps({"kwh": self.energy_kwh, "updatedAt": time.time()}))
            temporary.replace(energy_file)
        except OSError:
            pass

        metrics: dict[str, object] = {
            "available": bool(roots),
            "cpuUsagePct": cpu_pct,
            "cpuRamBytes": rss_bytes if roots else None,
            "cpuRamTotalBytes": mem_total or None,
            "cpuTempC": None,
            "cpuPackagePowerW": cpu_package_w,
            "gpuUsagePct": gpu.get("gpu_usage_pct") if roots else None,
            "gpuVramBytes": int(gpu["gpu_vram_mb"]) * 1024 * 1024 if roots and gpu.get("gpu_vram_mb") is not None else None,
            "gpuVramTotalBytes": 16 * 1024**3,
            "gpuTempC": gpu.get("gpu_temp_c") if roots else None,
            "gpuHotspotC": gpu.get("gpu_hotspot_c") if roots else None,
            "gpuFanRpm": gpu.get("gpu_fan_rpm") if roots else None,
            "gpuBoardPowerW": board_power,
            "workloadPowerW": workload_w,
            "energyKwh": self.energy_kwh,
            "scopeNote": "GPU sensors are attributed while the trainer owns the compute workload; CPU and RAM are the trainer process tree.",
        }
        with self.lock:
            self.hardware_cache = metrics
            self.hardware_sample_at = now
            self.sample_roots = tuple(roots)
        return metrics
