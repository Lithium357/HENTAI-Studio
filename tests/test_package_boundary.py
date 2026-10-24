import importlib.resources
import subprocess
import sys
from unittest.mock import patch

import pytest

from hentai_studio.cli import main
from hentai_studio.runtime import hardware_probe


@pytest.mark.parametrize("command,module,function,extra", [
    ("dashboard", "dashboard", "run_dashboard", ["--config", "configs/local.json"]),
    ("studio", "studio", "run_studio", ["--storage-root", "data"]),
])
def test_project_is_explicit_and_independent_of_working_directory(tmp_path, monkeypatch, command, module, function, extra):
    project = tmp_path / "engine"
    project.mkdir()
    other = tmp_path / "unrelated"
    other.mkdir()
    monkeypatch.chdir(other)
    with patch(f"hentai_studio.{module}.{function}") as run:
        assert main([command, "--project", str(project), *extra]) == 0
    assert run.call_args.args[0] == project.resolve()


def test_dashboard_and_api_start_without_model_libraries():
    subprocess.run([sys.executable, "-c", """
import sys
from hentai_studio.cli import _parser
from hentai_studio.dashboard import DashboardState
from hentai_studio.studio import StudioService
_parser()
assert not any(name.split('.')[0] in {'torch', 'diffusers', 'transformers', 'peft'} for name in sys.modules)
"""], check=True)


def test_assets_and_probe_belong_to_installed_studio(monkeypatch, tmp_path):
    monkeypatch.delenv("HENTAI_HARDWARE_PROBE", raising=False)
    monkeypatch.chdir(tmp_path)
    package = importlib.resources.files("hentai_studio")
    assert (package / "dashboard_static/index.html").is_file()
    assert hardware_probe().is_file()
    assert hardware_probe().parent.name == "bin"
    custom = tmp_path / "custom.exe"
    monkeypatch.setenv("HENTAI_HARDWARE_PROBE", str(custom))
    assert hardware_probe() == custom
