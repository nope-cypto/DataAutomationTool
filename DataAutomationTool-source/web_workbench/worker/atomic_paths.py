from __future__ import annotations

from pathlib import Path
from uuid import uuid4


def atomic_temp_path(path: Path) -> Path:
    return path.parent / f".kw-{uuid4().hex}.tmp"
