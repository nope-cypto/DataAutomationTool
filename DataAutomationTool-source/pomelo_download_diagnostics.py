from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Iterable


_FLAGS = {
    "download_control_missing": (False, False),
    "download_wait_started": (False, False),
    "download_event_received": (True, False),
    "download_save_started": (True, False),
    "download_save_completed": (True, True),
}
_NEXT = {
    None: {"download_control_missing", "download_wait_started"},
    "download_control_missing": set(),
    "download_wait_started": {"download_event_received"},
    "download_event_received": {"download_save_started"},
    "download_save_started": {"download_save_completed"},
    "download_save_completed": set(),
}
_KEYS = {"attempt", "substage", "downloadStarted", "downloadCompleted"}


@dataclass(frozen=True)
class DownloadAttemptDiagnostic:
    attempt: int
    substage: str
    download_started: bool
    download_completed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "attempt": self.attempt,
            "substage": self.substage,
            "downloadStarted": self.download_started,
            "downloadCompleted": self.download_completed,
        }


class DownloadStageRecorder:
    def __init__(self, attempt: int) -> None:
        if type(attempt) is not int or attempt not in {1, 2}:
            raise ValueError("download_diagnostic_attempt_invalid")
        self.attempt = attempt
        self._snapshot: DownloadAttemptDiagnostic | None = None

    def mark(self, substage: str) -> None:
        current = self._snapshot.substage if self._snapshot else None
        if type(substage) is not str or substage not in _NEXT[current]:
            raise ValueError("download_diagnostic_transition_invalid")
        started, completed = _FLAGS[substage]
        self._snapshot = DownloadAttemptDiagnostic(self.attempt, substage, started, completed)

    def snapshot(self) -> DownloadAttemptDiagnostic | None:
        return self._snapshot


def validate_download_attempts(value: object) -> list[dict[str, object]] | None:
    if not isinstance(value, (list, tuple)):
        return None
    normalized: list[dict[str, object]] = []
    seen: set[int] = set()
    for item in value:
        raw = item.to_dict() if isinstance(item, DownloadAttemptDiagnostic) else item
        if not isinstance(raw, dict) or set(raw) != _KEYS:
            return None
        attempt = raw["attempt"]
        substage = raw["substage"]
        started = raw["downloadStarted"]
        completed = raw["downloadCompleted"]
        if type(attempt) is not int or attempt not in {1, 2} or attempt in seen:
            return None
        if type(substage) is not str or substage not in _FLAGS:
            return None
        if type(started) is not bool or type(completed) is not bool:
            return None
        if (started, completed) != _FLAGS[substage]:
            return None
        if normalized and attempt <= int(normalized[-1]["attempt"]):
            return None
        seen.add(attempt)
        normalized.append(
            {
                "attempt": attempt,
                "substage": substage,
                "downloadStarted": started,
                "downloadCompleted": completed,
            }
        )
    return normalized


def serialize_download_attempts(value: Iterable[DownloadAttemptDiagnostic] | object) -> str:
    normalized = validate_download_attempts(
        list(value) if not isinstance(value, (list, tuple)) else value
    )
    if normalized is None:
        raise ValueError("download_diagnostic_invalid")
    return json.dumps(normalized, ensure_ascii=True, separators=(",", ":"))


def parse_download_attempts_json(value: object) -> list[dict[str, object]] | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return validate_download_attempts(decoded)
