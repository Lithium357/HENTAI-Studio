from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import DashboardState


@dataclass(slots=True)
class TrainingControls:
    context: DashboardState

    def stop(self) -> None:
        self.context.pause_file.parent.mkdir(parents=True, exist_ok=True)
        self.context.pause_file.write_text("Paused intentionally from HENTAI Studio.\n", encoding="utf-8")
        self.context.process_monitor.terminate_trainers()

    def resume(self) -> None:
        if self.context.trainer_pids() or self.context.watchdog_pids():
            self.context.pause_file.unlink(missing_ok=True)
            return
        script = self._watchdog_script()
        log = self.context.project / "logs" / "training-watchdog-launch.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["HENTAI_PROJECT"] = str(self.context.project)
        env["HENTAI_CONFIG"] = str(self.context.config)
        with log.open("ab", buffering=0) as output:
            subprocess.Popen(
                [
                    "/usr/bin/bash",
                    str(script),
                ],
                cwd=self.context.project,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        self.context.pause_file.unlink(missing_ok=True)

    def _watchdog_script(self):
        name = "train_sdxl_watchdog.sh" if self.context.is_sdxl_lora else (
            "train_scratch_v3_x4_watchdog.sh" if self.context.is_x4_latent else "train_scratch_v2_watchdog.sh"
        )
        script = self.context.project / "scripts" / name
        text = script.read_text(encoding="utf-8")
        if "${HENTAI_PROJECT" in text and "${HENTAI_CONFIG" in text:
            return script
        # Earlier engine watchdogs hard-code their paths and ignore overrides.
        # Read only literal assignments; never evaluate shell source in Studio.
        values = {}
        for line in text.splitlines():
            match = re.fullmatch(r'(PROJECT|CONFIG|RUN_DIR)="([^"]+)"', line)
            if match:
                value = match[2]
                for key, resolved in values.items():
                    value = value.replace("$" + key, resolved)
                values[match[1]] = value
        default_config = "rx7800xt-sdxl-lora-1024.json" if self.context.is_sdxl_lora else "rx7800xt-256.json"
        expected_config = self.context.project / "configs" / default_config
        if (
            values.get("PROJECT") != str(self.context.project)
            or values.get("RUN_DIR") != str(self.context.run_dir)
            or self.context.config != expected_config.resolve()
        ):
            raise RuntimeError("This engine watchdog has fixed paths for another project or run. Update the engine watchdog to honor HENTAI_PROJECT and HENTAI_CONFIG before resuming from Studio.")
        return script

    def start_diffusion(self) -> None:
        if self.context.is_sdxl_lora:
            raise RuntimeError("stage switching is only available for scratch training")
        final = self.context.run_dir / "models" / "vae"
        if final.is_dir():
            raise RuntimeError("diffuser stage has already been selected")
        checkpoint_root = self.context.run_dir / "checkpoints" / "vae"
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

        self.context.pause_file.parent.mkdir(parents=True, exist_ok=True)
        self.context.pause_file.write_text(
            "Promoting the latest VAE checkpoint before diffuser training.\n",
            encoding="utf-8",
        )
        self.context.process_monitor.terminate_trainers()
        deadline = time.monotonic() + 30
        while self.context.trainer_pids() and time.monotonic() < deadline:
            time.sleep(0.25)
        if self.context.trainer_pids():
            raise RuntimeError("VAE trainer did not stop; training remains safely paused")

        temporary = self.context.run_dir / "models" / ".vae-promoting"
        temporary.parent.mkdir(parents=True, exist_ok=True)
        if temporary.exists():
            shutil.rmtree(temporary)
        shutil.copytree(checkpoint / "model", temporary)
        os.replace(temporary, final)
        marker = self.context.run_dir / "EARLY_VAE_STOP.json"
        marker.write_text(
            json.dumps(
                {
                    "checkpoint": checkpoint.name,
                    "promoted_at": time.time(),
                    "original_vae_target": int(self.context.raw_config.get("vae_max_steps", 0)),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        self.context.pause_file.unlink(missing_ok=True)
        self.context.resume()
