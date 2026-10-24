import json

import pytest

from hentai_studio.workloads.llm.config import load_llm_config


def valid_config(tmp_path):
    return {
        "schema_version": 1,
        "workload_type": "llm.causal",
        "mode": "scratch",
        "run_dir": str(tmp_path / "run"),
        "seed": 357,
        "dataset": {"root": str(tmp_path / "data"), "schema": "text", "context_length": 128},
        "tokenizer": {"mode": "train_bpe", "vocab_size": 256},
        "model": {"hidden_size": 96, "intermediate_size": 256, "num_hidden_layers": 2, "num_attention_heads": 6, "num_key_value_heads": 2, "max_position_embeddings": 128},
        "training": {"max_steps": 2},
        "checkpointing": {},
        "evaluation": {},
    }


def test_llm_config_is_strict(tmp_path):
    raw = valid_config(tmp_path)
    raw["unexpected"] = True
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="unknown LLM config"):
        load_llm_config(path)


def test_scratch_requires_trained_tokenizer(tmp_path):
    raw = valid_config(tmp_path)
    raw["tokenizer"]["mode"] = "base_model"
    raw["tokenizer"]["base_model"] = "/local/model"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="scratch mode"):
        load_llm_config(path)


def test_unimplemented_full_finetune_mode_is_rejected(tmp_path):
    raw = valid_config(tmp_path)
    raw["mode"] = "full_finetune"
    raw["tokenizer"] = {"mode": "base_model", "base_model": "/local/model"}
    raw["model"]["base_model"] = "/local/model"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="scratch or lora"):
        load_llm_config(path)
