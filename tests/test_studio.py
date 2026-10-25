import json
from pathlib import Path

from hentai_studio.api.services.runs import RunService


def test_studio_service_lists_runs_without_heavy_backend(tmp_path):
    legacy = tmp_path / "runs" / "legacy"
    legacy.mkdir(parents=True)
    (legacy / "config.json").write_text(json.dumps({"run_dir": "runs/legacy", "resolution": 512}))
    service = RunService(tmp_path, tmp_path / "data")
    assert [item.model_dump() for item in service.list_runs()] == [{"id": "diffusion:legacy", "display_name": "Legacy", "workload_type": "diffusion", "state": "legacy"}]
    assert service.get_run("diffusion:legacy").workload_type == "diffusion"


def test_legacy_dashboard_registry_uses_same_run_discovery_contract(tmp_path):
    config = tmp_path / "config.json"
    run = tmp_path / "runs" / "legacy"
    run.mkdir(parents=True)
    config.write_text(json.dumps({"run_dir": str(run), "resolution": 512, "latent_downsample_factor": 8}))
    (run / "config.json").write_text(json.dumps({"run_dir": str(run), "resolution": 512}))
    assert RunService(tmp_path, tmp_path / "data").list_runs()[0].id == "diffusion:legacy"


def test_dashboard_assets_define_separate_diffusion_and_llm_workspaces():
    root = Path(__file__).parents[1] / "src" / "hentai_studio" / "dashboard_static"
    markup = (root / "index.html").read_text(encoding="utf-8")
    assert 'data-workspace="diffusion"' in markup
    assert 'data-workspace="llm"' in markup
    assert 'id="llmWorkspace"' in markup
    assert 'id="llmChatTranscript"' in markup
    assert 'eval-line' in markup
    assert 'eval-points' in markup
    styles = (root / "styles.css").read_text(encoding="utf-8")
    assert '#llmWorkspace[hidden] { display: none !important; }' in styles
