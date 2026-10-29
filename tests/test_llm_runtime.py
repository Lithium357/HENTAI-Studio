"""Opt-in CPU integration test: random tiny model -> checkpoint -> real chat inference."""

import json
import os
import sys
import time

import pytest
from fastapi.testclient import TestClient

from hentai_studio.api.app import create_app

pytestmark = pytest.mark.skipif(
    os.environ.get("STUDIO_TEST_LLM") != "1",
    reason="Set STUDIO_TEST_LLM=1 in an environment with the llm extra for the offline CPU smoke test.",
)


def test_scratch_training_resume_and_local_chat(tmp_path):
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from transformers import GPT2Config, PreTrainedTokenizerFast

    vocabulary = {
        word: index
        for index, word in enumerate(
            [
                "[PAD]",
                "[UNK]",
                "[EOS]",
                "hello",
                "world",
                "user",
                "assistant",
                ":",
                "test",
                "model",
            ]
        )
    }
    raw = Tokenizer(WordLevel(vocabulary, unk_token="[UNK]"))
    raw.pre_tokenizer = Whitespace()
    tokenizer = PreTrainedTokenizerFast(
        tokenizer_object=raw, unk_token="[UNK]", pad_token="[PAD]", eos_token="[EOS]"
    )
    model_root = tmp_path / "config"
    model_root.mkdir()
    GPT2Config(
        vocab_size=len(tokenizer),
        n_positions=64,
        n_embd=16,
        n_layer=1,
        n_head=2,
        bos_token_id=2,
        eos_token_id=2,
        pad_token_id=0,
    ).save_pretrained(model_root)
    tokenizer.save_pretrained(model_root)
    dataset = tmp_path / "train.jsonl"
    dataset.write_text(
        "\n".join(
            json.dumps({"text": "hello world test model hello world"}) for _ in range(4)
        )
        + "\n"
    )
    app = create_app(tmp_path / "workspace")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        project = client.post(
            "/api/projects",
            json={
                "id": "tiny",
                "name": "Tiny scratch",
                "root": str(tmp_path),
                "llm": {
                    "python": sys.executable,
                    "model": str(model_root),
                    "tokenizer": str(model_root),
                    "dataset": str(dataset),
                    "max_length": 32,
                    "max_steps": 1,
                    "save_steps": 1,
                    "gradient_accumulation": 1,
                    "gradient_checkpointing": False,
                },
            },
        )
        assert project.status_code == 201, project.text
        job = client.post("/api/jobs", json={"project_id": "tiny"}).json()
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            current = client.get(f"/api/jobs/{job['id']}").json()
            if current["state"] not in {"starting", "running", "stopping"}:
                break
            time.sleep(0.25)
        logs = client.get(f"/api/jobs/{job['id']}/logs").json()["text"]
        assert current["state"] == "succeeded", logs
        assert "Scratch model initialized" in logs
        assert client.get(f"/api/jobs/{job['id']}/metrics").json()["items"]
        loaded = client.post(
            "/api/projects/tiny/chat/load",
            json={"checkpoint": "model", "job_id": job["id"]},
        )
        assert loaded.status_code == 200, loaded.text
        reply = client.post(
            "/api/projects/tiny/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 4,
                "temperature": 0,
            },
        )
        assert reply.status_code == 200, reply.text
        assert 0 < reply.json()["tokens"] <= 4
        assert client.post("/api/projects/tiny/chat/unload").status_code == 200
        assert (
            client.post(
                "/api/projects/tiny/chat/load",
                json={"checkpoint": "../..", "job_id": job["id"]},
            ).status_code
            == 422
        )
        # Reuse the same budget: an already-complete checkpoint must not run another step.
        resumed = client.post(f"/api/jobs/{job['id']}/resume", json={}).json()
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            current = client.get(f"/api/jobs/{resumed['id']}").json()
            if current["state"] not in {"starting", "running", "stopping"}:
                break
            time.sleep(0.25)
        assert current["state"] == "succeeded", client.get(
            f"/api/jobs/{resumed['id']}/logs"
        ).json()["text"]
