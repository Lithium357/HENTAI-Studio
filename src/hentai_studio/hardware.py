"""Read-only backend-host telemetry. No model imports, driver changes, or job signals."""

import copy
import csv
import io
import math
import os
import platform
import re
import shutil
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import psutil
from pydantic import Field

from .models_base import Model

MIB = 1024 * 1024


class GPUReading(Model):
    id: str
    name: str
    vendor: str
    source: str
    utilization_pct: float | None = None
    memory_used_mb: float | None = None
    memory_total_mb: float | None = None
    shared_memory_mb: float | None = None
    temperature_c: float | None = None
    power_w: float | None = None


class HardwareSnapshot(Model):
    scope: str = "backend_host"
    hostname: str
    platform: str
    sampled_at: str | None = None
    age_seconds: float | None = None
    stale: bool = True
    collecting: bool = True
    cpu_pct: float | None = None
    ram_used_mb: float | None = None
    ram_total_mb: float | None = None
    gpus: list[GPUReading] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


def number(value, *, maximum=None):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if (
        not math.isfinite(result)
        or result < 0
        or maximum is not None
        and result > maximum
    ):
        return None
    return result


def command(arguments, timeout=5):
    result = subprocess.run(
        arguments,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    return result.stdout


def parse_smi(text, vendor, source):
    """NVIDIA SMI and Intel XPU-SMI 2.x use the same explicit CSV query fields."""
    readings = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) != 8:
            continue
        identity, name, bus, usage, used, total, temperature, power = (
            v.strip() for v in row
        )
        if not name or not identity:
            continue
        readings.append(
            GPUReading(
                id=f"{vendor.lower()}:{bus}:{identity}",
                name=name,
                vendor=vendor,
                source=source,
                utilization_pct=number(usage, maximum=100),
                memory_used_mb=number(used),
                memory_total_mb=number(total),
                temperature_c=number(temperature, maximum=200),
                power_w=number(power),
            )
        )
    return readings


def smi_gpus(executable, vendor):
    fields = "uuid,name,pci.bus_id,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"
    return parse_smi(
        command([executable, "--query-gpu=" + fields, "--format=csv,noheader,nounits"]),
        vendor,
        Path(executable).stem,
    )


def read_number(path, divisor=1, maximum=None):
    try:
        value = number(path.read_text().strip())
        return number(value / divisor, maximum=maximum) if value is not None else None
    except OSError:
        return None


def linux_gpus(root=Path("/sys/class/drm")):
    readings = []
    for card in sorted(root.glob("card[0-9]*")):
        if not re.fullmatch(r"card\d+", card.name):
            continue
        device = card / "device"
        try:
            vendor_id = device.joinpath("vendor").read_text().strip().lower()
            vendor = {"0x1002": "AMD", "0x8086": "Intel", "0x10de": "NVIDIA"}.get(
                vendor_id
            )
            if vendor is None:
                continue
            device_id = device.joinpath("device").read_text().strip()
        except OSError:
            continue
        reading = GPUReading(
            id="pci:" + device.resolve().name,
            vendor=vendor,
            name=f"{vendor} GPU {device_id} ({card.name})",
            source="Linux DRM/sysfs",
            utilization_pct=read_number(device / "gpu_busy_percent", maximum=100),
            memory_used_mb=read_number(device / "mem_info_vram_used", MIB),
            memory_total_mb=read_number(device / "mem_info_vram_total", MIB),
        )
        for sensor in sorted(device.glob("hwmon/hwmon*")):
            reading.temperature_c = read_number(
                sensor / "temp1_input", 1000, maximum=200
            )
            reading.power_w = read_number(sensor / "power1_average", 1_000_000)
            if reading.power_w is None:
                reading.power_w = read_number(sensor / "power1_input", 1_000_000)
            if reading.temperature_c is not None or reading.power_w is not None:
                break
        readings.append(reading)
    return readings


def collect_gpus():
    readings, issues, covered = [], [], set()
    for executable, vendor in (("nvidia-smi", "NVIDIA"), ("xpu-smi", "Intel")):
        path = shutil.which(executable)
        if (
            not path
            and vendor == "NVIDIA"
            and Path("/usr/lib/wsl/lib/nvidia-smi").is_file()
        ):
            path = "/usr/lib/wsl/lib/nvidia-smi"
        # NVIDIA installs this on PATH in current drivers, but older Windows drivers do not.
        if not path and os.name == "nt" and vendor == "NVIDIA":
            candidate = (
                Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
                / "NVIDIA Corporation/NVSMI/nvidia-smi.exe"
            )
            path = str(candidate) if candidate.is_file() else None
        if path:
            try:
                devices = smi_gpus(path, vendor)
                if devices:
                    readings.extend(devices)
                    covered.add(vendor)
                else:
                    issues.append(
                        f"{executable}: no readable GPU rows; check the driver/tool version."
                    )
            except (OSError, subprocess.SubprocessError) as error:
                issues.append(
                    f"{executable}: {type(error).__name__}; driver readings unavailable."
                )
    try:
        if os.name == "nt":
            from .hardware_windows import windows_gpus

            devices, warnings = windows_gpus()
            issues.extend(warnings)
        elif platform.system() == "Linux":
            devices = linux_gpus()
        else:
            devices = []
            issues.append("GPU monitoring is supported on Windows and Linux backends.")
        readings.extend(device for device in devices if device.vendor not in covered)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        issues.append(
            f"OS GPU monitoring: {type(error).__name__}; readings unavailable."
        )
    if not readings:
        issues.append(
            "No GPU is visible to this backend. Check its driver and GPU passthrough/container/WSL access."
        )
    for gpu in readings:
        if gpu.utilization_pct is None:
            issues.append(f"{gpu.name}: utilization unavailable from {gpu.source}.")
            if gpu.vendor == "Intel" and gpu.source == "Linux DRM/sysfs":
                issues.append(
                    "Install Intel XPU-SMI 2.x on this backend for Intel utilization and memory telemetry."
                )
    return readings, issues


class HardwareMonitor:
    """One lazy sampler per server, shared by every window. Requests never wait on drivers."""

    def __init__(self, interval=3):
        self.interval = interval
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._sample_time = None
        self._value = HardwareSnapshot(
            hostname=platform.node(), platform=platform.system()
        )

    def snapshot(self):
        with self._lock:
            if self._thread is None and not self._stop.is_set():
                self._thread = threading.Thread(
                    target=self._run, name="studio-hardware", daemon=True
                )
                self._thread.start()
            result = copy.deepcopy(self._value)
            if self._sample_time is not None:
                result.age_seconds = round(time.monotonic() - self._sample_time, 2)
                result.stale = result.age_seconds > max(15, self.interval * 3)
            return result

    def _run(self):
        psutil.cpu_percent(
            interval=None
        )  # Prime the rate counter on this sampling thread.
        while not self._stop.wait(self.interval):
            try:
                gpus, issues = collect_gpus()
                cpu = psutil.cpu_percent(interval=None)
                ram = psutil.virtual_memory()
                value = HardwareSnapshot(
                    hostname=platform.node(),
                    platform=platform.system(),
                    sampled_at=datetime.now(UTC).isoformat(),
                    collecting=False,
                    stale=False,
                    cpu_pct=cpu,
                    ram_used_mb=ram.used / MIB,
                    ram_total_mb=ram.total / MIB,
                    gpus=gpus,
                    issues=issues,
                )
                with self._lock:
                    self._value = value
                    self._sample_time = time.monotonic()
            except Exception as error:  # noqa: BLE001 - keep the sampling daemon alive after driver failures
                # A provider failure must never affect training admission or other API routes.
                with self._lock:
                    self._value.issues = [
                        f"Hardware sampler failed: {type(error).__name__}."
                    ]
                    self._value.collecting = False

    def close(self):
        self._stop.set()
