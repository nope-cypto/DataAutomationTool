"""Attach Playwright to a user-launched Chrome debugging session."""

from __future__ import annotations

import asyncio
import glob
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
from typing import Any
from dataclasses import dataclass
import warnings

from web_workbench.worker.action_errors import SafeActionError


_RUNTIME_ENVIRONMENT_LOCK = threading.Lock()


@dataclass
class AttachedRuntime:
    runtime: str
    playwright: Any
    browser: Any
    context: Any
    cleanup_temp: bool = True

    def close(self) -> None:
        detach(self.playwright, clean_temp=self.cleanup_temp)


def _playwright_environment() -> dict[str, str]:
    environment = dict(os.environ)
    executable = Path(sys.executable).resolve()
    packaged = getattr(sys, "frozen", False) or executable.name.lower() == "dataautomationtoolworker.exe"
    if not packaged:
        return environment

    driver_dir = executable.parent / "playwright" / "driver"
    node = driver_dir / "node.exe"
    cli = driver_dir / "package" / "cli.js"
    if not node.is_file() or not cli.is_file():
        raise SafeActionError("pomelo_driver_package_missing")
    environment["PLAYWRIGHT_NODEJS_PATH"] = str(node)
    environment.pop("ELECTRON_RUN_AS_NODE", None)
    return environment


def _start_playwright(environment: dict[str, str]) -> Any:
    """Start Playwright while applying only its process-launch environment."""
    from playwright.sync_api import sync_playwright

    keys = ("PLAYWRIGHT_NODEJS_PATH", "ELECTRON_RUN_AS_NODE")
    with _RUNTIME_ENVIRONMENT_LOCK:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            if sys.platform == "win32" and not isinstance(
                asyncio.get_event_loop_policy(), asyncio.WindowsProactorEventLoopPolicy
            ):
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

        previous_stderr = sys.stderr
        owned_stderr = None
        if sys.platform == "win32":
            try:
                if previous_stderr is None or previous_stderr.closed or previous_stderr.fileno() < 0:
                    raise ValueError("stderr unavailable")
            except (AttributeError, OSError, ValueError):
                owned_stderr = open(os.devnull, "w", encoding="utf-8")
                sys.stderr = owned_stderr

        previous = {key: os.environ.get(key) for key in keys}
        try:
            for key in keys:
                value = environment.get(key)
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            return sync_playwright().start()
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            if owned_stderr is not None:
                sys.stderr = previous_stderr
                owned_stderr.close()


def attach(cdp_url: str = "http://localhost:9222") -> tuple[Any, Any, Any]:
    """Attach to Chrome via CDP and reuse its logged-in browser context."""
    try:
        playwright = _start_playwright(_playwright_environment())
    except SafeActionError:
        raise
    except Exception as exc:
        raise SafeActionError("pomelo_playwright_start_failed") from exc
    try:
        connected = playwright.chromium.connect_over_cdp(endpoint_url=cdp_url)
    except Exception as exc:
        playwright.stop()
        raise SafeActionError("pomelo_cdp_connect_failed") from exc
    try:
        context = connected.contexts[0]
    except (AttributeError, IndexError, TypeError) as exc:
        playwright.stop()
        raise SafeActionError("pomelo_browser_context_missing") from exc
    return playwright, connected, context


def attach_with_fallback(cdp_url: str, *, cleanup_temp: bool = True) -> AttachedRuntime:
    """Compatibility entry point retained for the Worker action adapter."""
    playwright, connected, context = attach(cdp_url)
    return AttachedRuntime("playwright", playwright, connected, context, cleanup_temp)


def detach(playwright: Any, clean_temp: bool = True) -> None:
    """Detach Playwright control without closing the user's Chrome window."""
    try:
        playwright.stop()
    except Exception:
        pass
    if clean_temp:
        _clean_playwright_artifacts()


def _clean_playwright_artifacts() -> int:
    """Remove temporary Playwright download folders; never touch output files."""
    roots = {value for value in (os.environ.get("TEMP"), os.environ.get("TMP"), tempfile.gettempdir()) if value}
    removed = 0
    for root in roots:
        for value in glob.glob(os.path.join(root, "playwright-artifacts-*")):
            try:
                shutil.rmtree(value)
                removed += 1
            except Exception:
                pass
    return removed
