import json
from pathlib import Path

from hentai_studio.studio import StudioService


def test_studio_service_lists_runs_without_heavy_backend(tmp_path):
    legacy = tmp_path / "runs" / "legacy"
    legacy.mkdir(parents=True)
    (legacy / "config.json").write_text(json.dumps({"run_dir": "runs/legacy", "resolution": 512}))
    service = StudioService(tmp_path, tmp_path / "data")
    assert service.runs() == [{"id": "legacy", "displayName": "Legacy", "workloadType": "diffusion", "state": "legacy", "legacy": True}]
    assert service.status("legacy")["workloadType"] == "diffusion"


def test_legacy_dashboard_registry_uses_same_run_discovery_contract(tmp_path):
    config = tmp_path / "config.json"
    run = tmp_path / "runs" / "legacy"
    run.mkdir(parents=True)
    config.write_text(json.dumps({"run_dir": str(run), "resolution": 512, "latent_downsample_factor": 8}))
    (run / "config.json").write_text(json.dumps({"run_dir": str(run), "resolution": 512}))
    assert StudioService(tmp_path, tmp_path / "data").runs()[0]["id"] == "legacy"


def test_dashboard_assets_define_separate_diffusion_and_llm_workspaces():
    root = Path(__file__).parents[1] / "src" / "hentai_studio" / "dashboard_static"
    markup = (root / "index.html").read_text(encoding="utf-8")
    script = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.js"))
    assert 'data-workspace="diffusion"' in markup
    assert 'data-workspace="llm"' in markup
    assert 'id="llmWorkspace"' in markup
    assert 'id="llmChatTranscript"' in markup
    assert 'requestJSON("/api/v1/runs"' in script
    assert '/chat`' in script
    assert 'CPU ONLY' in script
    assert 'selectedStatus?.state' in script
    assert 'eval-line' in markup
    assert 'eval-points' in markup
    assert 'point.evalLoss' in script
    styles = (root / "styles.css").read_text(encoding="utf-8")
    assert '#llmWorkspace[hidden] { display: none !important; }' in styles
