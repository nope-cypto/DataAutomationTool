from __future__ import annotations

import ctypes
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

try:
    import openpyxl
except Exception:  # pragma: no cover
    openpyxl = None


class FileBoundaryError(RuntimeError):
    """Raised when a worker path escapes the active task boundary."""


BEIJING_TZ = timezone(timedelta(hours=8))
STEP_DIRS = [
    "Step0_ASIN_Input",
    "Step1_Pomelo_Data",
    "Step2_Wheat_Expansion",
    "Step9_Pomelo_Keywords",
]
LEGACY_STEP_DIRS = {
    "Step0_Competitor_ASINS": "Step0_ASIN_Input",
    "step1_1_1_xiyou": "Step1_Pomelo_Data",
    "step1_1_2_sellersprite": "Step2_Wheat_Expansion",
    "step2_1_xiyou_top_asins": "Step9_Pomelo_Keywords",
    "Step3_Pomelo_Keywords": "Step9_Pomelo_Keywords",
    "Step3_Wheat_Keywords": "Step9_Pomelo_Keywords",
}
STEP0_WORKBOOK_NAME = "Step0_ASIN_Input.xlsx"
STEP0_HEADERS = ["国家", "竞品ASIN", "竞品强弱"]
STANDARD_TASK_DIR_PATTERN = re.compile(r"task_20\d{6}_[a-z0-9_]+(?:_\d{2})?", re.IGNORECASE)
MAX_TASK_SLUG_LENGTH = 80
WINDOWS_FIXED_DRIVE = 3
WINDOWS_REMOTE_DRIVE = 4
TRANSIENT_FILE_SUFFIXES = (".tmp", ".part", ".crdownload")
TRANSIENT_FILE_INFIXES = tuple(f"{suffix}." for suffix in TRANSIENT_FILE_SUFFIXES)


def is_transient_workflow_file(path: str | Path) -> bool:
    name = Path(path).name.casefold()
    return (
        name.startswith(("~$", "."))
        or name.endswith(TRANSIENT_FILE_SUFFIXES)
        or any(marker in name for marker in TRANSIENT_FILE_INFIXES)
    )


def beijing_timestamp() -> str:
    return datetime.now(BEIJING_TZ).strftime("%Y%m%d_%H%M%S")


def sanitize_task_slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    return re.sub(r"_+", "_", text).strip("_") or "task"


def ensure_task_structure(task_dir: Path) -> Path:
    resolved = task_dir.expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    for legacy_name, current_name in LEGACY_STEP_DIRS.items():
        legacy_path = resolved / legacy_name
        current_path = resolved / current_name
        if legacy_path.is_dir() and not current_path.exists():
            legacy_path.rename(current_path)
    for dirname in STEP_DIRS:
        (resolved / dirname).mkdir(parents=True, exist_ok=True)
    for directory, legacy_names, current_name in [
        ("Step0_ASIN_Input", ("Step0_Competitor_ASINS.xlsx",), STEP0_WORKBOOK_NAME),
        ("Step2_Wheat_Expansion", ("request.txt",), "Step2_Request.txt"),
        ("Step9_Pomelo_Keywords", ("request_top_asins.txt", "Step3_Request.txt"), "Step9_Request.txt"),
    ]:
        for legacy_name in legacy_names:
            legacy_path = resolved / directory / legacy_name
            current_path = resolved / directory / current_name
            if legacy_path.is_file() and not current_path.exists():
                legacy_path.rename(current_path)
    step0_path = resolved / "Step0_ASIN_Input" / STEP0_WORKBOOK_NAME
    if not step0_path.exists():
        if openpyxl is None:
            raise FileBoundaryError("openpyxl_required")
        workbook = openpyxl.Workbook()
        try:
            sheet = workbook.active
            sheet.title = "ASIN输入"
            sheet.append(STEP0_HEADERS)
            workbook.save(step0_path)
        finally:
            workbook.close()
    for dirname, filename in {
        "Step2_Wheat_Expansion": "Step2_Request.txt",
        "Step9_Pomelo_Keywords": "Step9_Request.txt",
    }.items():
        request_path = resolved / dirname / filename
        if not request_path.exists():
            request_path.write_text("", encoding="utf-8")
    return resolved


def create_task_dir(task_root: Path, task_name: str) -> Path:
    root = task_root.expanduser().resolve()
    validate_task_directory(root)
    root.mkdir(parents=True, exist_ok=True)
    slug = sanitize_task_slug(task_name)
    if len(slug) > MAX_TASK_SLUG_LENGTH:
        raise FileBoundaryError("task_name_too_long")
    base_name = f"task_{beijing_timestamp()[:8]}_{slug}"
    for index in range(1, 100):
        suffix = "" if index == 1 else f"_{index:02d}"
        candidate = root / f"{base_name}{suffix}"
        if not candidate.exists():
            return ensure_task_dir(candidate)
    raise FileBoundaryError("task_directory_conflict_limit")


def ensure_task_dir(path: Path, *, allow_non_standard: bool = False) -> Path:
    resolved = path.expanduser().resolve()
    if not allow_non_standard and not STANDARD_TASK_DIR_PATTERN.fullmatch(resolved.name):
        raise FileBoundaryError("invalid_task_directory_name")
    validate_task_directory(resolved)
    (resolved / ".workflow" / "jobs").mkdir(parents=True, exist_ok=True)
    return ensure_task_structure(resolved)


def validate_existing_task_dir(
    path: Path,
    *,
    allow_non_standard: bool = False,
    check_writable: bool = True,
) -> Path:
    resolved = path.expanduser().resolve()
    if not allow_non_standard and not STANDARD_TASK_DIR_PATTERN.fullmatch(resolved.name):
        raise FileBoundaryError("invalid_task_directory_name")
    if not resolved.is_dir():
        raise FileBoundaryError("task_directory_missing")
    return validate_task_directory(resolved, check_writable=check_writable)


def _system_drive_type(path: Path) -> str:
    if os.name != "nt":
        return "fixed"
    try:
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor))
        if drive_type == WINDOWS_FIXED_DRIVE:
            return "fixed"
        if drive_type == WINDOWS_REMOTE_DRIVE:
            return "remote"
        return "unsupported"
    except (AttributeError, OSError):
        return "unknown"


def _known_sync_roots() -> list[Path]:
    roots = [Path(value) for name in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial") if (value := os.environ.get(name))]
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        roots.extend(Path(user_profile) / name for name in ("Dropbox", "Google Drive", "My Drive"))
    return roots


def validate_task_directory(
    path: Path,
    *,
    drive_type: str | None = None,
    sync_roots: list[Path] | None = None,
    writable: bool | None = None,
    create_structure: bool = False,
    check_writable: bool = True,
) -> Path:
    if str(path).startswith("\\\\"):
        raise FileBoundaryError("unsupported_task_location")
    resolved = path.expanduser().resolve()
    if (drive_type or _system_drive_type(resolved)).lower() not in {"fixed", "remote"}:
        raise FileBoundaryError("unsupported_task_location")
    for sync_root in _known_sync_roots() if sync_roots is None else sync_roots:
        root = Path(sync_root).expanduser().resolve()
        if resolved == root or root in resolved.parents:
            raise FileBoundaryError("unsupported_task_location")
    if writable is False or (resolved.exists() and not resolved.is_dir()):
        raise FileBoundaryError("task_directory_not_writable")
    if check_writable:
        probe_dir = resolved if resolved.exists() else next((parent for parent in resolved.parents if parent.exists()), None)
        if probe_dir is not None:
            probe = probe_dir / f".automation-write-probe-{uuid4().hex}.tmp"
            try:
                probe.write_text("probe", encoding="utf-8")
            except OSError as exc:
                raise FileBoundaryError("task_directory_not_writable") from exc
            finally:
                probe.unlink(missing_ok=True)
    if create_structure:
        return ensure_task_dir(resolved, allow_non_standard=True)
    return resolved


def assert_inside(root: Path, candidate: Path) -> Path:
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve()
    if root_resolved != candidate_resolved and root_resolved not in candidate_resolved.parents:
        raise FileBoundaryError("path_outside_task")
    return candidate_resolved
