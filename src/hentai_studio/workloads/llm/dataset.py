from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Iterable

from .config import DatasetConfig


@dataclass(frozen=True, slots=True)
class AuditReport:
    files: int = 0
    records: int = 0
    valid: int = 0
    invalid: int = 0
    empty: int = 0
    characters: int = 0
    duplicates: int = 0

    def as_dict(self) -> dict[str, int]:
        return {"files": self.files, "records": self.records, "valid": self.valid, "invalid": self.invalid, "empty": self.empty, "characters": self.characters, "duplicates": self.duplicates}


def jsonl_files(root: str | Path) -> list[Path]:
    path = Path(root)
    if path.is_file() and path.suffix == ".jsonl":
        return [path]
    return sorted(item for item in path.rglob("*.jsonl") if item.is_file())


def source_files(root: str | Path) -> list[Path]:
    """Return supported local corpus files for provenance fingerprints.

    Training adapters may own their parsing rules (the ERP archive is CSV), but
    every prepared run must fingerprint the physical input corpus rather than an
    empty JSONL-only selection.
    """
    path = Path(root)
    if path.is_file():
        return [path] if path.suffix.lower() in {".jsonl", ".csv"} else []
    return sorted(item for suffix in ("*.jsonl", "*.csv") for item in path.rglob(suffix) if item.is_file())


def text_from_record(record: object, schema: str) -> str:
    if not isinstance(record, dict):
        raise ValueError("row must be an object")
    if schema == "text":
        value = record.get("text")
        if not isinstance(value, str):
            raise ValueError("text row requires string text")
        return value
    if schema == "prompt_completion":
        prompt, completion = record.get("prompt"), record.get("completion")
        if not isinstance(prompt, str) or not isinstance(completion, str):
            raise ValueError("prompt_completion row requires string prompt and completion")
        return prompt + completion
    messages = record.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages row requires a non-empty messages list")
    parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant"} or not isinstance(message.get("content"), str):
            raise ValueError("invalid chat message")
        parts.append(message["content"])
    return "\n".join(parts)


def _configure_csv_field_limit() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def audit_jsonl(config: DatasetConfig) -> AuditReport:
    report = AuditReport(files=len(source_files(config.root)))
    hashes: set[str] = set()
    duplicates = 0
    for file in source_files(config.root):
        if file.suffix.lower() == ".csv":
            _configure_csv_field_limit()
            with file.open(encoding="utf-8", errors="replace", newline="") as handle:
                for row in csv.DictReader(handle):
                    report = AuditReport(**{**report.as_dict(), "records": report.records + 1})
                    text = row.get("message")
                    if not isinstance(text, str):
                        report = AuditReport(**{**report.as_dict(), "invalid": report.invalid + 1})
                        continue
                    if not text.strip():
                        report = AuditReport(**{**report.as_dict(), "empty": report.empty + 1})
                        continue
                    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                    duplicates += digest in hashes
                    hashes.add(digest)
                    report = AuditReport(**{**report.as_dict(), "valid": report.valid + 1, "characters": report.characters + len(text), "duplicates": duplicates})
            continue
        with file.open(encoding="utf-8") as handle:
            for raw in handle:
                if not raw.strip():
                    continue
                report = AuditReport(**{**report.as_dict(), "records": report.records + 1})
                try:
                    text = text_from_record(json.loads(raw), config.schema)
                except (ValueError, json.JSONDecodeError):
                    report = AuditReport(**{**report.as_dict(), "invalid": report.invalid + 1})
                    continue
                if not text.strip():
                    report = AuditReport(**{**report.as_dict(), "empty": report.empty + 1})
                    continue
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                duplicates += digest in hashes
                hashes.add(digest)
                report = AuditReport(**{**report.as_dict(), "valid": report.valid + 1, "characters": report.characters + len(text), "duplicates": duplicates})
    return report


def split_name(text: str, seed: int, validation_fraction: float) -> str:
    value = int.from_bytes(hashlib.blake2b(f"{seed}\0{text}".encode("utf-8"), digest_size=8).digest(), "big")
    return "validation" if value / 2**64 < validation_fraction else "train"


def fingerprint(paths: Iterable[Path], config: DatasetConfig, tokenizer_identity: str) -> str:
    payload = {"files": [{"path": str(path.resolve()), "size": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns} for path in paths], "schema": config.schema, "context_length": config.context_length, "packing": config.packing, "tokenizer": tokenizer_identity}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
