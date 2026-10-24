from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .runtime import hardware_probe, process_entries


PROGRESS_RE = re.compile(
    r"(?P<step>\d+)/(?P<total>\d+).*?(?P<seconds>\d+(?:\.\d+)?)s/it.*?loss=(?P<loss>\d+(?:\.\d+)?)"
)


@dataclass(slots=True)
class DashboardState:
    project: Path
    config: Path
    sample_dir: Path
    sample_job: subprocess.Popen[bytes] | None = None
    sample_started: float | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    hardware_cache: dict[str, object] = field(default_factory=dict)
    hardware_sample_at: float = 0.0
    process_ticks: int | None = None
    process_ticks_at: float | None = None
    energy_kwh: float | None = None
    energy_at: float | None = None

    @property
    def run_dir(self) -> Path:
        raw = json.loads(self.config.read_text(encoding="utf-8"))
        run_dir = Path(raw["run_dir"])
        return run_dir if run_dir.is_absolute() else self.project / run_dir

    @property
    def raw_config(self) -> dict[str, object]:
        return json.loads(self.config.read_text(encoding="utf-8"))

    @property
    def is_sdxl_lora(self) -> bool:
        return str(self.raw_config.get("architecture", "")).startswith("sdxl_lora")

    @property
    def is_x4_latent(self) -> bool:
        return int(self.raw_config.get("latent_downsample_factor", 8)) == 4

    @property
    def training_name(self) -> str:
        if self.is_sdxl_lora:
            return "sdxl"
        return "scratch-v3-x4" if self.is_x4_latent else "scratch-v2"

    def trainer_pids(self) -> list[int]:
        matches: list[int] = []
        for entry in process_entries():
            if not entry.name.isdigit():
                continue
            try:
                command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
            except (OSError, PermissionError):
                continue
            if (
                "scratchtag train-diffusion" in command
                or "scratchtag train-vae" in command
                or "train_dreambooth_lora_sdxl.py" in command
            ) and "multiprocessing" not in command:
                matches.append(int(entry.name))
        return sorted(matches)

    def process_tree(self, roots: list[int]) -> set[int]:
        result = set(roots)
        children: dict[int, list[int]] = {}
        for entry in process_entries():
            if not entry.name.isdigit():
                continue
            try:
                fields = (entry / "stat").read_text().split()
                children.setdefault(int(fields[3]), []).append(int(entry.name))
            except (OSError, ValueError, IndexError):
                continue
        pending = list(roots)
        while pending:
            for child in children.get(pending.pop(), []):
                if child not in result:
                    result.add(child)
                    pending.append(child)
        return result

    def hardware_metrics(self, roots: list[int]) -> dict[str, object]:
        now = time.monotonic()
        with self.lock:
            if self.hardware_cache and now - self.hardware_sample_at < 3.0:
                return self.hardware_cache

        pids = self.process_tree(roots)
        ticks = 0
        rss_bytes = 0
        for pid in pids:
            try:
                fields = Path(f"/proc/{pid}/stat").read_text().split()
                ticks += int(fields[13]) + int(fields[14])
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
        if probe.exists():
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
        energy_file = self.run_dir / "hardware-energy.json"
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
        return metrics

    def watchdog_pids(self) -> list[int]:
        matches: list[int] = []
        for entry in process_entries():
            if not entry.name.isdigit():
                continue
            try:
                command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
            except (OSError, PermissionError):
                continue
            if (
                "scripts/train_watchdog.sh" in command
                or "scripts/train_scratch_v2_watchdog.sh" in command
                or "scripts/train_scratch_v3_x4_watchdog.sh" in command
                or "scripts/train_sdxl_watchdog.sh" in command
            ):
                matches.append(int(entry.name))
        return sorted(matches)

    @property
    def pause_file(self) -> Path:
        return self.run_dir / "PAUSED"

    def latest_log(self) -> Path | None:
        logs = self.project / "logs"
        preferred = logs / f"{self.training_name}-training.log"
        if preferred.exists() and not self.is_sdxl_lora:
            return preferred
        candidates = sorted(logs.glob("*diffusion*.log"), key=lambda path: path.stat().st_mtime)
        return candidates[-1] if candidates else None

    def progress(self) -> tuple[dict[str, object], list[dict[str, float]]]:
        log = self.latest_log()
        if log is None:
            return {}, []
        with log.open("rb") as handle:
            size = log.stat().st_size
            handle.seek(max(0, size - 2_000_000))
            text = handle.read().decode(errors="ignore")
        if not self.is_sdxl_lora:
            marker = text.rfind("Training the scratch-")
            if marker >= 0:
                text = text[marker:]
        matches = list(PROGRESS_RE.finditer(text))
        if not matches:
            return {"log": log.name}, []
        latest = matches[-1]
        step = int(latest["step"])
        total = int(latest["total"])
        timing_by_step: dict[int, float] = {}
        for match in matches:
            timing_by_step[int(match["step"])] = float(match["seconds"])
        timing_window = list(timing_by_step.values())[-500:]
        sorted_timings = sorted(timing_window)
        seconds = sorted_timings[len(sorted_timings) // 2]
        loss = float(latest["loss"])
        history_raw = [(int(match["step"]), float(match["loss"])) for match in matches]
        deduplicated: dict[int, float] = {}
        for history_step, history_loss in history_raw:
            deduplicated[history_step] = history_loss
        history_items = list(deduplicated.items())[-240:]
        history = [{"step": float(item[0]), "loss": item[1]} for item in history_items]
        return (
            {
                "step": step,
                "total": total,
                "percent": step / total * 100 if total else 0,
                "loss": loss,
                "secondsPerStep": seconds,
                "paceWindow": len(timing_window),
                "imagesPerSecond": (
                    int(self.raw_config.get("batch_size", 1))
                    * int(self.raw_config.get("gradient_accumulation", 1))
                    / seconds
                    if seconds
                    else 0
                ),
                "etaSeconds": max(0, total - step) * seconds,
                "log": log.name,
                "updatedAt": log.stat().st_mtime,
            },
            history,
        )

    def checkpoints(self) -> list[dict[str, object]]:
        if self.is_sdxl_lora:
            root = self.run_dir
        else:
            diffusion_root = self.run_dir / "checkpoints" / "diffusion"
            vae_root = self.run_dir / "checkpoints" / "vae"
            root = diffusion_root if (self.run_dir / "models" / "vae").is_dir() else vae_root
        pattern = "checkpoint-*" if self.is_sdxl_lora else "step-*"
        result: list[dict[str, object]] = []
        for path in sorted(root.glob(pattern), key=lambda item: int(item.name.split("-")[-1]), reverse=True):
            size = sum(file.stat().st_size for file in path.rglob("*") if file.is_file())
            result.append(
                {
                    "name": path.name,
                    "step": int(path.name.split("-")[-1]),
                    "size": size,
                    "modifiedAt": path.stat().st_mtime,
                }
            )
        return result[:8]

    def checkpoint_catalog(self) -> list[dict[str, object]]:
        runs_root = (self.project / "runs").resolve()
        result: list[dict[str, object]] = []
        if not runs_root.is_dir():
            return result
        for run_dir in sorted(runs_root.iterdir(), key=lambda path: path.name):
            config_path = run_dir / "config.json"
            checkpoint_root = run_dir / "checkpoints" / "diffusion"
            if not config_path.is_file() or not checkpoint_root.is_dir():
                continue
            try:
                run_config = json.loads(config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            checkpoints: list[dict[str, object]] = []
            for checkpoint in sorted(
                (path for path in checkpoint_root.glob("step-*") if re.fullmatch(r"step-\d+", path.name)),
                key=lambda path: int(path.name.split("-")[-1]),
                reverse=True,
            ):
                complete = (
                    (checkpoint / "unet" / "config.json").is_file()
                    and any((checkpoint / "unet").glob("*.safetensors"))
                    and (checkpoint / "text_encoder.safetensors").is_file()
                    and (run_dir / "models" / "vae" / "config.json").is_file()
                    and (run_dir / "vocab.json").is_file()
                )
                if complete:
                    checkpoints.append(
                        {
                            "id": checkpoint.name,
                            "step": int(checkpoint.name.split("-")[-1]),
                            "modifiedAt": checkpoint.stat().st_mtime,
                        }
                    )
            if checkpoints:
                result.append(
                    {
                        "id": run_dir.name,
                        "label": run_dir.name.replace("-", " ").title(),
                        "resolution": int(run_config.get("resolution", 0)),
                        "checkpoints": checkpoints,
                    }
                )
        result.sort(
            key=lambda run: max(float(item["modifiedAt"]) for item in run["checkpoints"]),
            reverse=True,
        )
        return result

    def resolve_historical_checkpoint(self, run_id: str, checkpoint_id: str) -> tuple[Path, Path]:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", run_id) or not re.fullmatch(r"step-\d+", checkpoint_id):
            raise RuntimeError("invalid historical checkpoint selection")
        run_dir = (self.project / "runs" / run_id).resolve()
        checkpoint = (run_dir / "checkpoints" / "diffusion" / checkpoint_id).resolve()
        runs_root = (self.project / "runs").resolve()
        if not run_dir.is_relative_to(runs_root) or not checkpoint.is_relative_to(run_dir):
            raise RuntimeError("checkpoint selection escaped the runs directory")
        valid = any(
            run["id"] == run_id
            and any(item["id"] == checkpoint_id for item in run["checkpoints"])
            for run in self.checkpoint_catalog()
        )
        if not valid:
            raise RuntimeError("the selected diffusion checkpoint is missing or incomplete")
        return run_dir, checkpoint

    def samples(self) -> list[dict[str, object]]:
        self.sample_dir.mkdir(parents=True, exist_ok=True)
        files = list(self.sample_dir.glob("*.png"))
        now = time.time()
        # WSL can briefly inherit a bad clock around a Windows reboot. Repair
        # future-dated gallery files so they cannot permanently hide new samples.
        for path in files:
            if path.stat().st_mtime > now + 60:
                os.utime(path, (now - 86_400, now - 86_400))
        files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return [
            {
                "name": path.name,
                "url": f"/samples/{path.name}",
                "modifiedAt": path.stat().st_mtime,
                "size": path.stat().st_size,
            }
            for path in files[:12]
        ]

    def snapshot(self) -> dict[str, object]:
        progress, history = self.progress()
        raw = self.raw_config
        vae_total = int(raw.get("vae_max_steps", 0))
        diffusion_total = int(raw.get("max_steps", 0))
        vae_complete = (self.run_dir / "models" / "vae").is_dir()
        active_stage = "diffusion" if vae_complete else "vae"
        active_step = int(progress.get("step", 0))
        vae_step = vae_total if vae_complete else min(active_step, vae_total)
        diffusion_step = min(active_step, diffusion_total) if vae_complete else 0
        overall_total = vae_total + diffusion_total
        stages = {
            "active": active_stage,
            "vae": {
                "step": vae_step,
                "total": vae_total,
                "percent": vae_step / vae_total * 100 if vae_total else 0,
            },
            "diffusion": {
                "step": diffusion_step,
                "total": diffusion_total,
                "percent": diffusion_step / diffusion_total * 100 if diffusion_total else 0,
            },
            "overall": {
                "step": vae_step + diffusion_step,
                "total": overall_total,
                "percent": (vae_step + diffusion_step) / overall_total * 100 if overall_total else 0,
            },
        }
        usage = shutil.disk_usage(self.project)
        with self.lock:
            if self.sample_job is not None and self.sample_job.poll() is not None:
                self.sample_job = None
                self.sample_started = None
            sampling = self.sample_job is not None
        pids = self.trainer_pids()
        return {
            "running": bool(pids),
            "architectureLabel": "SCRATCH V3 / 4X LATENT" if self.is_x4_latent else "SCRATCH V2 / 8X LATENT",
            "pids": pids,
            "watchdogRunning": bool(self.watchdog_pids()),
            "paused": self.pause_file.exists(),
            "progress": progress,
            "stages": stages,
            "lossHistory": history,
            "checkpoints": self.checkpoints(),
            "checkpointCatalog": self.checkpoint_catalog(),
            "samples": self.samples(),
            "sampling": sampling,
            "sampleStarted": self.sample_started,
            "checkpointEvery": int(self.raw_config.get("checkpoint_every", 1000)),
            "disk": {"free": usage.free, "total": usage.total},
            "hardware": self.hardware_metrics(pids),
            "serverTime": time.time(),
        }

    def stop(self) -> None:
        self.pause_file.parent.mkdir(parents=True, exist_ok=True)
        self.pause_file.write_text("Paused intentionally from HENTAI Studio.\n", encoding="utf-8")
        for pid in self.trainer_pids():
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

    def resume(self) -> None:
        self.pause_file.unlink(missing_ok=True)
        if self.trainer_pids() or self.watchdog_pids():
            return
        log = self.project / "logs" / "training-watchdog-launch.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["HENTAI_PROJECT"] = str(self.project)
        env["HENTAI_CONFIG"] = str(self.config)
        with log.open("ab", buffering=0) as output:
            subprocess.Popen(
                [
                    "/usr/bin/bash",
                    str(
                        self.project
                        / "scripts"
                        / (
                            "train_sdxl_watchdog.sh"
                            if self.is_sdxl_lora
                            else ("train_scratch_v3_x4_watchdog.sh" if self.is_x4_latent else "train_scratch_v2_watchdog.sh")
                        )
                    ),
                ],
                cwd=self.project,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

    def start_diffusion(self) -> None:
        if self.is_sdxl_lora:
            raise RuntimeError("stage switching is only available for scratch training")
        final = self.run_dir / "models" / "vae"
        if final.is_dir():
            raise RuntimeError("diffuser stage has already been selected")
        checkpoint_root = self.run_dir / "checkpoints" / "vae"
        candidates = sorted(
            checkpoint_root.glob("step-*"),
            key=lambda path: int(path.name.split("-")[-1]),
            reverse=True,
        )
        checkpoint = next(
            (
                path
                for path in candidates
                if (path / "training_state.pt").is_file()
                and (path / "model" / "config.json").is_file()
                and any((path / "model").glob("*.safetensors"))
            ),
            None,
        )
        if checkpoint is None:
            raise RuntimeError("no complete VAE checkpoint is available yet")

        self.pause_file.parent.mkdir(parents=True, exist_ok=True)
        self.pause_file.write_text(
            "Promoting the latest VAE checkpoint before diffuser training.\n",
            encoding="utf-8",
        )
        for pid in self.trainer_pids():
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 30
        while self.trainer_pids() and time.monotonic() < deadline:
            time.sleep(0.25)
        if self.trainer_pids():
            raise RuntimeError("VAE trainer did not stop; training remains safely paused")

        temporary = self.run_dir / "models" / ".vae-promoting"
        temporary.parent.mkdir(parents=True, exist_ok=True)
        if temporary.exists():
            shutil.rmtree(temporary)
        shutil.copytree(checkpoint / "model", temporary)
        os.replace(temporary, final)
        marker = self.run_dir / "EARLY_VAE_STOP.json"
        marker.write_text(
            json.dumps(
                {
                    "checkpoint": checkpoint.name,
                    "promoted_at": time.time(),
                    "original_vae_target": int(self.raw_config.get("vae_max_steps", 0)),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        self.pause_file.unlink(missing_ok=True)
        self.resume()

    def generate_sample(self, payload: dict[str, object]) -> None:
        with self.lock:
            if self.sample_job is not None and self.sample_job.poll() is None:
                raise RuntimeError("a sample is already being generated")
            tags = str(payload.get("tags", "1girl,solo,looking_at_viewer,smile,portrait"))
            steps = min(60, max(5, int(payload.get("steps", 20))))
            guidance = min(12.0, max(1.0, float(payload.get("guidance", 5.0))))
            historical = str(payload.get("source", "current")) == "historical"
            vae_active = (
                not historical
                and not self.is_sdxl_lora
                and not (self.run_dir / "models" / "vae").is_dir()
            )
            seed = secrets.randbits(63) if vae_active else int(payload.get("seed", 357))
            selected_run: Path | None = None
            selected_checkpoint: Path | None = None
            if historical:
                selected_run, selected_checkpoint = self.resolve_historical_checkpoint(
                    str(payload.get("runId", "")), str(payload.get("checkpointId", ""))
                )
                checkpoint_step = int(selected_checkpoint.name.split("-")[-1])
            else:
                checkpoints = self.checkpoints()
                checkpoint_step = int(checkpoints[0]["step"]) if checkpoints else 0
            prefix = selected_run.name if selected_run else ("vae" if vae_active else "step")
            filename = f"{prefix}-{checkpoint_step}_seed-{seed}_{int(time.time())}.png"
            output = self.sample_dir / filename
            env = os.environ.copy()
            env["OMP_NUM_THREADS"] = "6"
            if vae_active:
                command = [
                    sys.executable,
                    "-m",
                    "scratchtag.tools.vae_snapshot",
                    "--config",
                    str(self.config),
                    "--output",
                    str(output),
                    "--seed",
                    str(seed),
                    "--size",
                    "1080",
                ]
            else:
                selected_config = selected_run / "config.json" if selected_run else self.config
                command = [
                    sys.executable,
                    "-m",
                    ("scratchtag.tools.sdxl_checkpoint_sample" if self.is_sdxl_lora else "scratchtag.tools.diffusion_checkpoint_sample"),
                    "--config",
                    str(selected_config),
                    "--tags",
                    tags,
                    "--output",
                    str(output),
                    "--steps",
                    str(steps),
                    "--guidance",
                    str(guidance),
                    "--seed",
                    str(seed),
                ]
                if selected_checkpoint is not None:
                    command.extend(["--checkpoint", str(selected_checkpoint)])
            self.sample_job = subprocess.Popen(
                command,
                cwd=self.project,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
            )
            self.sample_started = time.time()


def run_dashboard(
    project: str | Path,
    config: str | Path,
    host: str = "127.0.0.1",
    port: int = 7860,
    storage_root: str | Path = "/mnt/d/HENTAI-Data",
) -> None:
    project_path = Path(project).resolve()
    config_path = Path(config)
    if not config_path.is_absolute():
        config_path = (project_path / config_path).resolve()
    state = DashboardState(project_path, config_path, project_path / "dashboard_samples")
    # This control-plane object is dependency-light: legacy dashboard startup
    # still does not import Torch, Transformers, or an LLM model backend.
    from .studio import StudioService

    studio = StudioService(project_path, Path(storage_root))
    static_root = Path(__file__).with_name("dashboard_static")

    class Handler(BaseHTTPRequestHandler):
        server_version = "HENTAIStudio/1.0"

        def log_message(self, format: str, *args: object) -> None:
            return

        def send_bytes(self, data: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_bytes(json.dumps(payload).encode(), "application/json; charset=utf-8", status)

        def send_download(self, target: Path, filename: str) -> None:
            if not target.is_file():
                self.send_json({"error": "progress log is not available yet"}, HTTPStatus.NOT_FOUND)
                return
            data = target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            parts = [unquote(part) for part in path.split("/") if part]
            try:
                if parts == ["api", "v1", "runs"]:
                    self.send_json({"runs": studio.runs()})
                    return
                if parts == ["api", "v1", "storage"]:
                    self.send_json(studio.storage_status())
                    return
                if len(parts) == 5 and parts[:3] == ["api", "v1", "runs"] and parts[4] == "status":
                    self.send_json(studio.status(parts[3]))
                    return
                if len(parts) == 5 and parts[:3] == ["api", "v1", "runs"] and parts[4] == "checkpoints":
                    self.send_json({"checkpoints": studio.checkpoints(parts[3])})
                    return
            except ValueError as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                return
            if path == "/api/status":
                self.send_json(state.snapshot())
                return
            if path == "/api/checkpoint-catalog":
                self.send_json({"runs": state.checkpoint_catalog()})
                return
            if path == "/progress/vae.csv":
                self.send_download(state.run_dir / "progress" / "vae.csv", "HENTAI-Studio-VAE-progress.csv")
                return
            if path == "/progress/diffuser.csv":
                self.send_download(
                    state.run_dir / "progress" / "diffuser.csv",
                    "HENTAI-Studio-Diffuser-progress.csv",
                )
                return
            if path.startswith("/samples/"):
                name = Path(unquote(path.removeprefix("/samples/"))).name
                target = state.sample_dir / name
                if target.is_file() and target.suffix.lower() == ".png":
                    self.send_bytes(target.read_bytes(), "image/png")
                else:
                    self.send_json({"error": "sample not found"}, HTTPStatus.NOT_FOUND)
                return
            target_name = "index.html" if path == "/" else path.lstrip("/")
            target = static_root / Path(target_name).name
            content_types = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8"}
            if target.is_file() and target.suffix in content_types:
                self.send_bytes(target.read_bytes(), content_types[target.suffix])
            else:
                self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            parts = [unquote(part) for part in path.split("/") if part]
            if len(parts) == 5 and parts[:3] == ["api", "v1", "runs"] and parts[4] == "chat":
                if int(self.headers.get("Content-Length", "0")) > 131_072:
                    self.send_json({"error": "request too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                    return
                try:
                    payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
                    self.send_json(studio.chat(parts[3], payload.get("messages", []), int(payload.get("maxNewTokens", 256))))
                except (ValueError, OSError, json.JSONDecodeError) as error:
                    self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                return
            if path != "/api/action":
                self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            if int(self.headers.get("Content-Length", "0")) > 16_384:
                self.send_json({"error": "request too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                return
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
                action = payload.get("action")
                if action == "stop":
                    state.stop()
                elif action == "resume":
                    state.resume()
                elif action == "sample":
                    state.generate_sample(payload)
                elif action == "start_diffusion":
                    state.start_diffusion()
                else:
                    raise ValueError("unknown action")
                self.send_json({"ok": True})
            except (ValueError, RuntimeError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"HENTAI Studio: http://localhost:{port}", flush=True)
    server.serve_forever()
