import json

import pytest
from types import SimpleNamespace
from unittest.mock import Mock

from hentai_studio.api.errors import ApiError
from hentai_studio.api.services.runs import RunService
from hentai_studio.api.schemas import ChatMessage
from hentai_studio.core.workload import CheckpointInfo, RunDescription


def test_same_named_runs_have_unambiguous_workload_ids(tmp_path):
    diffusion = tmp_path / "runs" / "same"
    diffusion.mkdir(parents=True)
    (diffusion / "config.json").write_text('{"run_dir":"runs/same","resolution":512}')
    storage = tmp_path / "bulk"
    llm = storage / "runs/llm/same"
    llm.mkdir(parents=True)
    (llm / "run.json").write_text(json.dumps({
        "schema_version": 1, "run_id": "same", "workload_type": "llm.causal", "state": "prepared",
    }))
    (llm / "config.json").write_text('{"mode":"scratch"}')
    service = RunService(tmp_path, storage)
    assert {item.id for item in service.list_runs()} == {"diffusion:same", "llm.causal:same"}
    assert [item.id for item in service.list_runs("llm.causal")] == ["llm.causal:same"]
    assert service.get_run("diffusion:same").workload_type == "diffusion"
    detail = service.get_run("llm.causal:same")
    assert detail.workload_type == "llm.causal"
    assert not detail.capabilities.chat
    with pytest.raises(ApiError) as error:
        service.get_run("llm.causal:missing")
    assert error.value.status == 404


def chat_fixture(tmp_path, monkeypatch):
    service = RunService(tmp_path, tmp_path / "bulk")
    run = tmp_path / "run"
    base = tmp_path / "base"
    base.mkdir()
    checkpoint = run / "checkpoints/weights/step-10"
    (checkpoint / "adapter").mkdir(parents=True)
    (checkpoint / "adapter/adapter_config.json").write_text("{}")
    description = RunDescription("fixture", "Fixture", "llm.causal", run, "running")
    service.registry = Mock()
    service.registry.discover.return_value = [description]
    adapter = service.adapters["llm.causal"] = Mock()
    adapter.status.return_value = {"state": "running"}
    adapter.checkpoints.return_value = [CheckpointInfo("weights/step-10", 10, checkpoint, True, 1, 100)]
    service.chat_backend = Mock()
    service.chat_backend.reply.return_value = "Hello"
    monkeypatch.setattr("hentai_studio.api.services.runs.load_llm_config", lambda path: SimpleNamespace(
        mode="lora", model=SimpleNamespace(base_model=str(base)),
    ))
    return service, base


def test_chat_uses_the_selected_checkpoint_and_releases_training_memory(tmp_path, monkeypatch):
    service, _ = chat_fixture(tmp_path, monkeypatch)
    assert service.get_run("llm.causal:fixture").capabilities.chat
    result = service.complete_chat("llm.causal:fixture", [ChatMessage(role="user", content="Hi")], 32)
    assert result.message.content == "Hello" and result.device == "cpu"
    assert result.checkpoint_id == "weights/step-10"
    service.chat_backend.unload.assert_called_once()


def test_missing_base_disables_chat_without_loading_models(tmp_path, monkeypatch):
    service, base = chat_fixture(tmp_path, monkeypatch)
    base.rmdir()
    assert not service.get_run("llm.causal:fixture").capabilities.chat
    with pytest.raises(ApiError) as error:
        service.complete_chat("llm.causal:fixture", [ChatMessage(role="user", content="Hi")], 32)
    assert error.value.status == 409
    service.chat_backend.reply.assert_not_called()


def test_failed_chat_unloads_and_returns_a_backend_error(tmp_path, monkeypatch):
    service, _ = chat_fixture(tmp_path, monkeypatch)
    service.chat_backend.reply.side_effect = RuntimeError("backend unavailable")
    with pytest.raises(ApiError) as error:
        service.complete_chat("llm.causal:fixture", [ChatMessage(role="user", content="Hi")], 32)
    assert error.value.status == 503
    service.chat_backend.unload.assert_called_once()
