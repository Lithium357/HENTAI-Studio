import json
from pathlib import Path
from unittest.mock import patch

from hentai_studio.dashboard import DashboardState
from hentai_studio.dashboard_app import processes


def make_state(tmp_path):
    project = tmp_path / "engine"
    project.mkdir()
    config = project / "active.json"
    config.write_text(json.dumps({"run_dir": "runs/active"}))
    return DashboardState(project, config, project / "samples")


def proc(tmp_path, pid, args, environment=""):
    entry = tmp_path / "proc" / str(pid)
    entry.mkdir(parents=True)
    (entry / "cmdline").write_bytes("\0".join(args).encode())
    (entry / "environ").write_bytes(environment.encode())
    return entry


def test_discovery_excludes_other_diffusion_runs(tmp_path, monkeypatch):
    state = make_state(tmp_path)
    other = state.project / "other.json"
    other.write_text('{"run_dir":"runs/other"}')
    entries = [
        proc(tmp_path, 100, ["python", "/venv/bin/scratchtag", "train-vae", "--config", str(state.config)]),
        proc(tmp_path, 200, ["python", "/venv/bin/scratchtag", "train-diffusion", "--config", str(other)]),
        proc(tmp_path, 300, ["python", "-m", "scratchtag.cli", "train-diffusion", "--config", str(state.config)]),
        proc(tmp_path, 400, ["python", "train_dreambooth_lora_sdxl.py", "--output_dir", str(state.run_dir)]),
        proc(tmp_path, 500, ["python", "/venv/bin/scratchtag", "train-vae", f"--config={state.config}"]),
    ]
    monkeypatch.setattr(processes, "process_entries", lambda: entries)
    assert state.trainer_pids() == [100, 300, 400, 500]


def test_watchdog_discovery_respects_config_and_engine(tmp_path, monkeypatch):
    state = make_state(tmp_path)
    script = state.project / "scripts/train_scratch_v3_x4_watchdog.sh"
    other = state.project / "other.json"
    other.write_text('{"run_dir":"runs/other"}')
    entries = [
        proc(tmp_path, 100, ["bash", str(script)], f"HENTAI_CONFIG={state.config}\0"),
        proc(tmp_path, 200, ["bash", str(script)], f"HENTAI_CONFIG={other}\0"),
        proc(tmp_path, 300, ["bash", str(tmp_path / "elsewhere/scripts" / script.name)]),
    ]
    monkeypatch.setattr(processes, "process_entries", lambda: entries)
    assert state.watchdog_pids() == [100]


def test_stop_targets_only_selected_trainers_and_workers(tmp_path):
    state = make_state(tmp_path)
    with patch.object(DashboardState, "trainer_pids", return_value=[100]), \
         patch.object(processes, "process_tree", return_value={100, 101}), \
         patch.object(processes.os, "kill") as kill:
        state.stop()
    assert state.pause_file.is_file()
    assert [call.args[0] for call in kill.call_args_list] == [101, 100]
