from __future__ import annotations

from pathlib import Path

import pytest

from web_workbench.worker.build_preflight import BuildEnvironmentError, validate_build_environment


def test_windows_arm64_python_is_rejected_before_scons() -> None:
    with pytest.raises(BuildEnvironmentError, match=r"ARM64.*Python 3\.12 x64"):
        validate_build_environment("3.13.15", "win-arm64", "Windows")


def test_windows_x64_python_312_is_supported() -> None:
    validate_build_environment("3.12.10", "win-amd64", "Windows")


def test_worker_build_uses_pyinstaller_without_scons() -> None:
    script = Path(__file__).parents[1] / "web_workbench" / "worker" / "build_worker.ps1"
    source = script.read_text(encoding="utf-8")
    assert "build_preflight" in source
    assert "-m PyInstaller" in source
    assert "--collect-all=playwright" in source
    assert "-m nuitka" not in source.lower()
