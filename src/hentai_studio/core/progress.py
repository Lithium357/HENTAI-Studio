from __future__ import annotations

import csv
from pathlib import Path
from typing import Mapping


LLM_PROGRESS_COLUMNS = (
    "timestamp_utc", "session_id", "resumed_from_step", "step", "total_steps", "progress_percent",
    "train_loss", "eval_loss", "perplexity", "learning_rate", "gradient_norm", "seconds_per_step",
    "tokens_per_second", "tokens_seen", "sequences_seen", "micro_batch_size", "gradient_accumulation", "context_length",
)


def append_progress(path: Path, row: Mapping[str, object], columns: tuple[str, ...] = LLM_PROGRESS_COLUMNS) -> None:
    unknown = set(row) - set(columns)
    if unknown:
        raise ValueError(f"unknown progress fields: {', '.join(sorted(unknown))}")
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="raise")
        if new:
            writer.writeheader()
        writer.writerow({column: row.get(column, "") for column in columns})
        handle.flush()
