from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


FORBIDDEN_MARKERS = ["Authorization:", "Cookie:", "Bearer ", "password", "access_token", "refresh_token"]


def assert_no_secret_markers(payload: dict[str, Any]) -> None:
    text = str(payload)
    for marker in FORBIDDEN_MARKERS:
        if marker in text:
            raise ValueError(f"secret marker found in step response: {marker}")


@dataclass
class StepResult:
    """Credential-safe step response; message is the safe message shown to users."""

    ok: bool
    step_id: str
    status: str
    message: str
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    job_id: str | None = None
    error: str | None = None
    missing: list[str] = field(default_factory=list)
    code: str | None = None
    retryable: bool = False
    diagnostic_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "ok": self.ok,
            "stepId": self.step_id,
            "status": self.status,
            "message": self.message,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "jobId": self.job_id,
            "code": self.code or self.error,
            "retryable": self.retryable,
            "diagnosticId": self.diagnostic_id,
            "error": self.error or self.code,
            "missing": self.missing,
            "data": self.data,
        }
        assert_no_secret_markers(payload)
        return payload
