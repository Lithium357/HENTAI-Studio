import json
from unittest.mock import patch
import pytest

from hentai_studio.dashboard import DashboardState


def state(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"run_dir": "runs/active", "resolution": 512, "batch_size": 2, "gradient_accumulation": 1}))
    return DashboardState(tmp_path, config, tmp_path / "samples")


def test_progress_handles_duplicate_log_steps_and_rolling_pace(tmp_path):
    dashboard = state(tmp_path)
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "scratch-v2-training.log").write_text("1/10 2.0s/it loss=3.0\n2/10 4.0s/it loss=2.5\n2/10 3.0s/it loss=2.0\n")
    progress, history = dashboard.progress()
    assert progress["step"] == 2
    assert progress["secondsPerStep"] == 3.0
    assert history == [{"step": 1.0, "loss": 3.0}, {"step": 2.0, "loss": 2.0}]


def test_idle_telemetry_never_launches_hardware_helpers(tmp_path):
    dashboard = state(tmp_path)
    with patch("hentai_studio.dashboard_app.telemetry.subprocess.run") as run:
        first = dashboard.hardware_metrics([])
        second = dashboard.hardware_metrics([])
    assert first is second
    assert not first["available"]
    run.assert_not_called()


def test_checkpoint_listing_ignores_partial_directory_names(tmp_path):
    dashboard = state(tmp_path)
    root = dashboard.run_dir / "checkpoints/vae"
    (root / "step-incomplete").mkdir(parents=True)
    (root / "step-10").mkdir()
    assert [item["step"] for item in dashboard.checkpoints()] == [10]


def test_resume_refuses_fixed_watchdog_for_another_run_and_stays_paused(tmp_path):
    dashboard = state(tmp_path)
    dashboard.pause_file.parent.mkdir(parents=True)
    dashboard.pause_file.write_text("paused")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "train_scratch_v2_watchdog.sh").write_text('PROJECT="/somewhere/else"\nRUN_DIR="$PROJECT/runs/other"\n')
    with patch.object(DashboardState, "trainer_pids", return_value=[]), \
         patch.object(DashboardState, "watchdog_pids", return_value=[]), \
         patch("hentai_studio.dashboard_app.controls.subprocess.Popen") as launch:
        with pytest.raises(RuntimeError, match="fixed paths"):
            dashboard.resume()
    assert dashboard.pause_file.is_file()
    launch.assert_not_called()
