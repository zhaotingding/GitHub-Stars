import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def module():
    spec = importlib.util.spec_from_file_location("stars_launcher", Path(__file__).resolve().parents[1] / "tools/launcher.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_launcher_uses_explicit_project_env_and_cleans_foreign_python(tmp_path, monkeypatch):
    launcher = module()
    manager = tmp_path / "conda.exe"
    manager.write_bytes(b"test")
    monkeypatch.setenv("CONDA_EXE", str(manager))
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "unrelated-project")
    monkeypatch.setenv("CONDA_SHLVL", "1")
    monkeypatch.setenv("CONDA_PREFIX_1", "old-env")
    monkeypatch.setenv("PYTHONPATH", "unrelated-path")
    monkeypatch.setenv("PYTHONHOME", "unrelated-python")
    checks, launched = [], []
    def check(command, **kwargs):
        checks.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"environment": "github-stars", "valid": True}), stderr="")
    monkeypatch.setattr(launcher.subprocess, "run", check)
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda command, **kwargs: launched.append((command, kwargs)))
    launcher.launch([])
    assert checks[0][0][checks[0][0].index("-n") + 1] == "github-stars"
    assert len(launched) == 1
    env = launched[0][1]["env"]
    assert "PYTHONPATH" not in env and "PYTHONHOME" not in env
    assert env["PYTHONNOUSERSITE"] == "1"
    assert env["CONDA_SHLVL"] == "0" and "CONDA_PREFIX_1" not in env


def test_launcher_refuses_base_and_missing_manager(monkeypatch):
    launcher = module()
    with pytest.raises(ValueError, match="base"):
        launcher.launch(["--env", "base"])
    monkeypatch.delenv("CONDA_EXE", raising=False)
    monkeypatch.setattr(launcher.shutil, "which", lambda _: None)
    with pytest.raises(ValueError, match="找不到 Conda"):
        launcher.launch([])
