import json

import pytest

from hentai_studio.cli import main
from hentai_studio.core.checkpoints import atomic_checkpoint, rotate_complete
from hentai_studio.core.progress import append_progress
from hentai_studio.workloads.llm.config import load_llm_config
from hentai_studio.workloads.llm.prepare import prepare_run
from hentai_studio.workloads.llm.smoke import smoke_test
from hentai_studio.workloads.llm.training import train_scratch
from hentai_studio.workloads.llm.lora_cpt import _complete_resume, _complete_weights, _write_run_state
from hentai_studio.workloads.llm.checkpoint import verify_lora_checkpoint


def test_atomic_checkpoint_and_rotation(tmp_path):
    root = tmp_path / "checkpoints"
    def writer(destination):
        (destination / "metadata.json").write_text("{}")
        (destination / "model.safetensors").write_bytes(b"weights")
    atomic_checkpoint(root, 1, writer, ("metadata.json", "model.safetensors"))
    atomic_checkpoint(root, 2, writer, ("metadata.json", "model.safetensors"))
    assert [item.name for item in rotate_complete(root, 1, ("metadata.json", "model.safetensors"))] == ["step-1"]
    assert (root / "step-2").is_dir()


def test_lora_resume_requires_every_durable_artifact(tmp_path):
    checkpoint = tmp_path / "step-500"
    (checkpoint / "adapter").mkdir(parents=True)
    for name in ("adapter/adapter_config.json", "adapter/adapter_model.safetensors", "optimizer.pt", "rng-state.pt", "trainer-state.json", "metadata.json"):
        (checkpoint / name).write_bytes(b"x")
    assert _complete_resume(checkpoint)
    (checkpoint / "optimizer.pt").unlink()
    assert not _complete_resume(checkpoint)


def test_lora_weights_require_a_complete_adapter(tmp_path):
    checkpoint = tmp_path / "step-500"
    (checkpoint / "adapter").mkdir(parents=True)
    for name in ("adapter/adapter_config.json", "adapter/adapter_model.safetensors", "metadata.json"):
        (checkpoint / name).write_bytes(b"x")
    assert _complete_weights(checkpoint)
    (checkpoint / "adapter" / "adapter_model.safetensors").unlink()
    assert not _complete_weights(checkpoint)


def test_lora_run_state_update_is_atomic_and_preserves_identity(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "run.json").write_text(json.dumps({"run_id": "fixture", "state": "prepared"}))
    _write_run_state(run, "running", session_id="fixture-session", resumed_from_step=500)
    state = json.loads((run / "run.json").read_text())
    assert state["run_id"] == "fixture"
    assert state["state"] == "running"
    assert state["session_id"] == "fixture-session"
    assert state["resumed_from_step"] == 500
    assert "updated_at" in state
    assert not (run / ".run.json.tmp").exists()


def test_lora_checkpoint_verifier_requires_weights_and_resume(tmp_path):
    for kind, names in (("weights", ("adapter/adapter_config.json", "adapter/adapter_model.safetensors", "metadata.json")), ("resume", ("adapter/adapter_config.json", "adapter/adapter_model.safetensors", "metadata.json", "optimizer.pt", "rng-state.pt", "trainer-state.json"))):
        root = tmp_path / "checkpoints" / kind / "step-500"
        (root / "adapter").mkdir(parents=True)
        for name in names:
            (root / name).write_text('{"step":500}' if name == "metadata.json" else "x")
    report = verify_lora_checkpoint(tmp_path, 500)
    assert report["complete"] is True
    assert report["weights"]["step"] == 500
    (tmp_path / "checkpoints" / "resume" / "step-500" / "metadata.json").write_text('{"step":499}')
    assert verify_lora_checkpoint(tmp_path, 500)["complete"] is False


def test_lora_checkpoint_verifier_cli_returns_nonzero_for_missing_checkpoint(tmp_path):
    assert main(["llm-checkpoint-verify", "--run-dir", str(tmp_path), "--step", "500"]) == 2


def test_progress_is_append_only_with_stable_header(tmp_path):
    path = tmp_path / "train.csv"
    append_progress(path, {"step": 1, "train_loss": 2.0})
    append_progress(path, {"step": 2, "train_loss": 1.0})
    assert len(path.read_text().splitlines()) == 3


def test_prepare_creates_identity_and_refuses_non_empty_target(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "records.jsonl").write_text('{"text":"hello"}\n')
    target = tmp_path / "run"
    raw = {
        "schema_version": 1, "workload_type": "llm.causal", "mode": "scratch", "run_dir": str(target), "seed": 1,
        "dataset": {"root": str(data), "schema": "text", "context_length": 128},
        "tokenizer": {"mode": "train_bpe", "vocab_size": 256},
        "model": {"hidden_size": 96, "intermediate_size": 256, "num_hidden_layers": 2, "num_attention_heads": 6, "num_key_value_heads": 2, "max_position_embeddings": 128},
        "training": {"max_steps": 2}, "checkpointing": {}, "evaluation": {},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    prepared = prepare_run(load_llm_config(path), path, "fixture")
    assert json.loads((prepared / "run.json").read_text())["run_id"] == "fixture"
    with pytest.raises(ValueError, match="non-empty"):
        prepare_run(load_llm_config(path), path, "fixture")


def test_tiny_synthetic_smoke_never_reads_dataset(tmp_path):
    raw = {
        "schema_version": 1, "workload_type": "llm.causal", "mode": "scratch", "run_dir": str(tmp_path / "run"), "seed": 1,
        "dataset": {"root": str(tmp_path / "missing-data"), "schema": "text", "context_length": 32},
        "tokenizer": {"mode": "train_bpe", "vocab_size": 256},
        "model": {"hidden_size": 96, "intermediate_size": 256, "num_hidden_layers": 2, "num_attention_heads": 6, "num_key_value_heads": 2, "max_position_embeddings": 32},
        "training": {"max_steps": 2}, "checkpointing": {}, "evaluation": {},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    result = smoke_test(load_llm_config(path), tiny=True)
    assert result["ok"] is True


def test_scratch_train_writes_and_resumes_a_real_checkpoint(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "records.jsonl").write_text("".join('{"text":"a compact training fixture has enough repeated words for a tokenizer."}\n' for _ in range(20)))
    target = tmp_path / "run"
    raw = {
        "schema_version": 1, "workload_type": "llm.causal", "mode": "scratch", "run_dir": str(target), "seed": 1,
        "dataset": {"root": str(data), "schema": "text", "validation_fraction": 0.1, "context_length": 16},
        "tokenizer": {"mode": "train_bpe", "vocab_size": 256},
        "model": {"hidden_size": 32, "intermediate_size": 64, "num_hidden_layers": 1, "num_attention_heads": 4, "num_key_value_heads": 2, "max_position_embeddings": 16},
        "training": {"gradient_accumulation": 1, "max_steps": 2, "learning_rate": 0.001},
        "checkpointing": {"weights_every": 1, "resume_every": 1, "keep_weights": 2, "keep_resume": 2}, "evaluation": {},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    config = load_llm_config(path)
    prepare_run(config, path, "fixture")
    train_scratch(config, config_path=path, device="cpu")
    assert (target / "checkpoints" / "resume" / "step-2" / "optimizer.pt").is_file()
