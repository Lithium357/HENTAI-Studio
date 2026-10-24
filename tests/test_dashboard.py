import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hentai_studio.dashboard import DashboardState


class DashboardCheckpointCatalogTests(unittest.TestCase):
    def make_state(self, root: Path) -> DashboardState:
        active_config = root / "configs" / "active.json"
        active_config.parent.mkdir(parents=True)
        active_config.write_text(json.dumps({"run_dir": "runs/active"}), encoding="utf-8")
        return DashboardState(root, active_config, root / "samples")

    def make_checkpoint(self, root: Path, run_name: str, step: int) -> None:
        run = root / "runs" / run_name
        (run / "checkpoints" / "diffusion" / f"step-{step}" / "unet").mkdir(parents=True)
        (run / "models" / "vae").mkdir(parents=True, exist_ok=True)
        (run / "config.json").write_text(
            json.dumps({"run_dir": f"runs/{run_name}", "resolution": 256}), encoding="utf-8"
        )
        (run / "vocab.json").write_text("{}", encoding="utf-8")
        checkpoint = run / "checkpoints" / "diffusion" / f"step-{step}"
        (checkpoint / "unet" / "config.json").write_text("{}", encoding="utf-8")
        (checkpoint / "unet" / "model.safetensors").write_bytes(b"model")
        (checkpoint / "text_encoder.safetensors").write_bytes(b"encoder")
        (run / "models" / "vae" / "config.json").write_text("{}", encoding="utf-8")

    def test_catalog_lists_only_complete_diffusion_checkpoints(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_checkpoint(root, "previous-run", 114000)
            state = self.make_state(root)
            catalog = state.checkpoint_catalog()
            self.assertEqual(catalog[0]["id"], "previous-run")
            self.assertEqual(catalog[0]["checkpoints"][0]["id"], "step-114000")

    def test_selection_cannot_escape_runs_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.make_state(Path(directory))
            with self.assertRaises(RuntimeError):
                state.resolve_historical_checkpoint("../outside", "step-1")

    def test_generation_uses_exact_selected_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_checkpoint(root, "previous-run", 110000)
            self.make_checkpoint(root, "previous-run", 114000)
            state = self.make_state(root)
            fake_process = type("FakeProcess", (), {"poll": lambda self: None})()
            with patch("hentai_studio.dashboard.subprocess.Popen", return_value=fake_process) as popen:
                state.generate_sample(
                    {
                        "source": "historical",
                        "runId": "previous-run",
                        "checkpointId": "step-110000",
                        "tags": "female, portrait",
                        "seed": 357,
                        "steps": 5,
                        "guidance": 5,
                    }
                )
            command = popen.call_args.args[0]
            self.assertEqual(command[1:3], ["-m", "scratchtag.tools.diffusion_checkpoint_sample"])
            checkpoint_argument = command[command.index("--checkpoint") + 1]
            self.assertTrue(
                Path(checkpoint_argument).as_posix().endswith("previous-run/checkpoints/diffusion/step-110000")
            )

    def test_resume_passes_selected_engine_project_and_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = self.make_state(root)
            with patch.object(DashboardState, "trainer_pids", return_value=[]), \
                 patch.object(DashboardState, "watchdog_pids", return_value=[]), \
                 patch("hentai_studio.dashboard.subprocess.Popen") as popen:
                state.resume()
            kwargs = popen.call_args.kwargs
            self.assertEqual(kwargs["cwd"], root)
            self.assertEqual(kwargs["env"]["HENTAI_PROJECT"], str(root))
            self.assertEqual(kwargs["env"]["HENTAI_CONFIG"], str(state.config))


if __name__ == "__main__":
    unittest.main()
