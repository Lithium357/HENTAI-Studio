from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import DashboardState


PROGRESS_RE = re.compile(
    r"(?P<step>\d+)/(?P<total>\d+).*?(?P<seconds>\d+(?:\.\d+)?)s/it.*?loss=(?P<loss>\d+(?:\.\d+)?)"
)


@dataclass(slots=True)
class ProgressReader:
    context: DashboardState

    def latest_log(self) -> Path | None:
        logs = self.context.project / "logs"
        preferred = logs / f"{self.context.training_name}-training.log"
        if preferred.exists() and not self.context.is_sdxl_lora:
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
        if not self.context.is_sdxl_lora:
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
                    int(self.context.raw_config.get("batch_size", 1))
                    * int(self.context.raw_config.get("gradient_accumulation", 1))
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
