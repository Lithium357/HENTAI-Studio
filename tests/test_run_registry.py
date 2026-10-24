import json

import pytest

from hentai_studio.core.run_registry import RunRegistry
from hentai_studio.core.storage import StorageRoots


def test_registry_discovers_legacy_and_llm_runs(tmp_path):
    legacy = tmp_path / "runs" / "old-diffusion"
    legacy.mkdir(parents=True)
    (legacy / "config.json").write_text(json.dumps({"run_dir": "runs/old-diffusion", "resolution": 512}))
    llm = tmp_path / "data" / "runs" / "llm" / "small"
    llm.mkdir(parents=True)
    (llm / "run.json").write_text(json.dumps({"schema_version": 1, "run_id": "small", "display_name": "Small", "workload_type": "llm.causal", "state": "prepared"}))
    runs = RunRegistry(tmp_path, tmp_path / "data" / "runs" / "llm").discover()
    assert {(item.run_id, item.workload_type) for item in runs} == {("old-diffusion", "diffusion"), ("small", "llm.causal")}


def test_storage_rejects_escape(tmp_path):
    roots = StorageRoots(tmp_path / "data")
    with pytest.raises(ValueError, match="outside"):
        roots.resolve_under(tmp_path / "outside")
