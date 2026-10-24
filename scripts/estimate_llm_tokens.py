"""Estimate archive token count from a deterministic local CSV sample."""
from __future__ import annotations

import argparse
import csv
import math
import random
from pathlib import Path
import sys


def configure_csv_field_limit() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("tokenizer")
    parser.add_argument("--rows", type=int, default=12_000)
    parser.add_argument("--files", type=int, default=24)
    parser.add_argument("--full-character-count", action="store_true", help="stream the whole archive without retaining text or duplicate hashes")
    parser.add_argument("--tokens-per-step", type=int, default=8_192)
    parser.add_argument("--validation-fraction", type=float, default=0.01)
    args = parser.parse_args()
    from transformers import AutoTokenizer

    files = sorted(args.archive.glob("*.csv"))
    selected = random.Random(42).sample(files, min(args.files, len(files)))
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, local_files_only=True)
    characters = tokens = rows = 0
    configure_csv_field_limit()
    for path in selected:
        with path.open(encoding="utf-8", errors="replace", newline="") as stream:
            for row in csv.DictReader(stream):
                text = row.get("message", "")
                if text:
                    characters += len(text)
                    tokens += len(tokenizer(text, add_special_tokens=False)["input_ids"])
                    rows += 1
                if rows >= args.rows:
                    break
        if rows >= args.rows:
            break
    if not characters or not tokens:
        raise ValueError("sample contained no non-empty message rows")
    report = {"sample_rows": rows, "sample_characters": characters, "sample_tokens": tokens, "tokens_per_character": tokens / characters, "characters_per_token": characters / tokens}
    if args.full_character_count:
        full_characters = full_rows = 0
        for path in files:
            with path.open(encoding="utf-8", errors="replace", newline="") as stream:
                for row in csv.DictReader(stream):
                    text = row.get("message", "")
                    if text:
                        full_rows += 1
                        full_characters += len(text)
        estimated_tokens = full_characters * tokens / characters
        training_tokens = estimated_tokens * (1 - args.validation_fraction)
        report.update({
            "full_rows": full_rows,
            "full_characters": full_characters,
            "estimated_total_tokens": estimated_tokens,
            "estimated_training_tokens": training_tokens,
            "estimated_optimizer_steps": math.ceil(training_tokens / args.tokens_per_step),
            "tokens_per_step": args.tokens_per_step,
        })
    print(report)


if __name__ == "__main__":
    main()
