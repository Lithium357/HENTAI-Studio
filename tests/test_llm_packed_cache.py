import csv
import json

from hentai_studio.workloads.llm.config import load_llm_config
from hentai_studio.workloads.llm.dataset import split_name
from hentai_studio.workloads.llm.packed_cache import PackedBlocks, build_packed_cache, load_manifest


class FixtureTokenizer:
    eos_token_id = 0

    def __call__(self, text, **_kwargs):
        return {"input_ids": [ord(char) % 251 + 1 for char in text]}


def test_packed_cache_builds_and_round_trips_fixed_blocks(tmp_path):
    candidates = [f"document {index} with enough text to fill a block" for index in range(100)]
    train_text = next(text for text in candidates if split_name(text, 42, 0.25) == "train")
    validation_text = next(text for text in candidates if split_name(text, 42, 0.25) == "validation")
    data = tmp_path / "data"
    data.mkdir()
    with (data / "records.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["message"])
        writer.writeheader()
        for text in (train_text, train_text, validation_text, validation_text):
            writer.writerow({"message": text})

    cache = tmp_path / "cache"
    raw = {
        "schema_version": 1,
        "workload_type": "llm.causal",
        "mode": "lora",
        "run_dir": str(tmp_path / "run"),
        "seed": 42,
        "dataset": {
            "root": str(data),
            "schema": "text",
            "packed_cache": str(cache),
            "validation_fraction": 0.25,
            "context_length": 16,
        },
        "tokenizer": {"mode": "base_model", "base_model": str(tmp_path / "base")},
        "model": {"base_model": str(tmp_path / "base"), "max_position_embeddings": 16},
        "training": {},
        "checkpointing": {},
        "evaluation": {},
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    config = load_llm_config(config_path)
    tokenizer = FixtureTokenizer()

    built = build_packed_cache(config, tokenizer, cache)
    loaded = load_manifest(cache, config, str(config.tokenizer.base_model))

    assert built == loaded
    assert built.train_blocks > 0
    assert built.validation_blocks > 0
    blocks = list(PackedBlocks(cache, "train", 16, built.train_blocks, limit=1))
    assert len(blocks) == 1
    assert len(blocks[0]) == 16
