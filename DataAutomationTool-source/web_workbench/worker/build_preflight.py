"""Fail fast when the Python interpreter cannot produce the x64 Worker."""

from __future__ import annotations

import argparse
import platform
import sys
import sysconfig


class BuildEnvironmentError(RuntimeError):
    pass


def validate_build_environment(version: str, platform_tag: str, os_name: str) -> None:
    normalized_os = str(os_name).strip().lower()
    normalized_platform = str(platform_tag).strip().lower().replace("_", "-")
    version_parts = str(version).strip().split(".")
    major_minor = tuple(int(part) for part in version_parts[:2]) if len(version_parts) >= 2 else ()

    if normalized_os != "windows":
        raise BuildEnvironmentError("Windows is required to build the Windows installer.")
    if "arm64" in normalized_platform or "aarch64" in normalized_platform:
        raise BuildEnvironmentError(
            "Windows ARM64 Python cannot build this x64 installer. Install Python 3.12 x64 "
            "from python.org; the x64 interpreter also runs on Windows 11 ARM."
        )
    if major_minor != (3, 12):
        raise BuildEnvironmentError(
            f"Python 3.12 x64 is required for deterministic packaging; detected Python {version}."
        )
    if not any(marker in normalized_platform for marker in ("amd64", "x86-64")):
        raise BuildEnvironmentError(
            f"Python 3.12 x64 is required; detected platform {platform_tag}."
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    version = platform.python_version()
    platform_tag = sysconfig.get_platform()
    try:
        validate_build_environment(version, platform_tag, platform.system())
    except (BuildEnvironmentError, ValueError) as exc:
        print(f"BUILD PREFLIGHT FAILED: {exc}", file=sys.stderr)
        return 2
    if not args.quiet:
        print(f"Build Python: {sys.executable} ({version}, {platform_tag})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
