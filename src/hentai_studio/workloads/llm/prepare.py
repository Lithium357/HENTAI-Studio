from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .config import LLMConfig
from .dataset import fingerprint, source_files


def prepare_run(config: LLMConfig, config_path: str | Path, run_id: str, display_name: str | None = None) -> Path:
    if not run_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in run_id):
        raise ValueError("run_id may contain only letters, numbers, dots, underscores, and dashes")
    run_dir = config.output.resolve()
    if run_dir.exists() and any(run_dir.iterdir()):
        raise ValueError(f"refusing to prepare into non-empty run directory: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    tokenizer_identity = f"{config.tokenizer.mode}:{config.tokenizer.base_model or config.tokenizer.vocab_size}"
    sources = source_files(config.dataset.root)
    if not sources:
        raise ValueError("dataset root contains no supported .jsonl or .csv source files")
    dataset_fingerprint = fingerprint(sources, config.dataset, tokenizer_identity)
    identity = {
        "schema_version": 1,
        "run_id": run_id,
        "display_name": display_name or run_id.replace("-", " ").title(),
        "workload_type": "llm.causal",
        "config_path": "config.json",
        "created_at": datetime.now(UTC).isoformat(),
        "state": "prepared",
    }
    (run_dir / "config.json").write_text(Path(config_path).read_text(encoding="utf-8"), encoding="utf-8")
    (run_dir / "run.json").write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
    (run_dir / "dataset-fingerprint.json").write_text(json.dumps({"fingerprint": dataset_fingerprint, "tokenizer_identity": tokenizer_identity, "source_files": len(sources)}, indent=2) + "\n", encoding="utf-8")
    for relative in ("progress", "checkpoints/weights", "checkpoints/resume", "models", "generations"):
        (run_dir / relative).mkdir(parents=True, exist_ok=True)
    return run_dir
