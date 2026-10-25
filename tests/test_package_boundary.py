import importlib.resources
import subprocess
import sys
from unittest.mock import patch
from hentai_studio.cli import main


def test_cli_needs_only_a_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("hentai_studio.studio.run_studio") as run:
        assert main(["serve", "--workspace", "workspace"]) == 0
    assert run.call_args.args == ((tmp_path / "workspace").resolve(), "127.0.0.1", 7860)


def test_application_imports_without_any_training_packages():
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import importlib.abc
import sys
class RejectTrainingImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'scratchtag', 'torch', 'diffusers', 'transformers', 'peft', 'hentai'}:
            raise AssertionError('Forbidden training import: ' + fullname)
sys.meta_path.insert(0, RejectTrainingImports())
from hentai_studio.api.app import create_app
from hentai_studio.cli import _parser
from tempfile import TemporaryDirectory
with TemporaryDirectory() as directory:
    app = create_app(directory)
    assert app.state.workspace.list_projects() == []
_parser()
""",
        ],
        check=True,
    )


def test_assets_are_owned_by_studio():
    package = importlib.resources.files("hentai_studio")
    assert (package / "dashboard_static/index.html").is_file()
