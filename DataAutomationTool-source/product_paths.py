"""Path helpers for source mode and frozen Windows product packages."""

from __future__ import annotations

from pathlib import Path
import sys


def app_root() -> Path:
    """Return the product root in source mode or frozen exe mode."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    """Return a resource path in source mode or PyInstaller frozen mode."""
    root = app_root()
    primary = root.joinpath(*parts)
    if primary.exists() or not getattr(sys, "frozen", False):
        return primary
    internal = root.joinpath("_internal", *parts)
    if internal.exists():
        return internal
    return primary


def user_data_path(*parts: str) -> Path:
    """Return a writable user-data path under the product root for P1 packaging."""
    return app_root().joinpath(*parts)
