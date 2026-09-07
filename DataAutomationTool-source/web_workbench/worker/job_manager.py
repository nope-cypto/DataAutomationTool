from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .atomic_paths import atomic_temp_path
from .security import sanitize_persisted_job_inputs


ACTIVE_STATUSES = {"queued", "running", "stopping"}
CHECKPOINT_PATH_KEYS = {"inputfile", "keywordsfile", "outputdir"}
CURRENT_WORKFLOW_VERSION = 4
_TASK_LOCKS_GUARD = threading.Lock()
_TASK_LOCKS: dict[str, threading.RLock] = {}


class JobConflict(RuntimeError):
    pass


class WorkflowMigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class JobRecord:
    schemaVersion: int
    id: str
    stepId: str
    actionId: str
    executionKind: str
    status: str
    inputs: dict[str, object] = field(default_factory=dict)
    completed: int = 0
    total: int = 0
    checkpoint: dict[str, object] | None = None
    outputs: dict[str, str] = field(default_factory=dict)
    allowedAction: str | None = None
    mutexHeld: bool = True
    restartedByJobId: str | None = None
    startedAt: str = ""
    updatedAt: str = ""
    finishedAt: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schemaVersion,
            "id": self.id,
            "stepId": self.stepId,
            "actionId": self.actionId,
            "executionKind": self.executionKind,
            "status": self.status,
            "inputs": self.inputs,
            "completed": self.completed,
            "total": self.total,
            "checkpoint": self.checkpoint,
            "outputs": self.outputs,
            "allowedAction": self.allowedAction,
            "mutexHeld": self.mutexHeld,
            "restartedByJobId": self.restartedByJobId,
            "startedAt": self.startedAt,
            "updatedAt": self.updatedAt,
            "finishedAt": self.finishedAt,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "JobRecord":
        return cls(
            schemaVersion=int(payload.get("schemaVersion", 1)),
            id=str(payload["id"]),
            stepId=str(payload["stepId"]),
            actionId=str(payload.get("actionId") or payload["stepId"]),
            executionKind="local",
            status=str(payload.get("status", "failed")),
            inputs=dict(payload.get("inputs") or {}),
            completed=int(payload.get("completed", 0)),
            total=int(payload.get("total", 0)),
            checkpoint=dict(payload["checkpoint"]) if isinstance(payload.get("checkpoint"), dict) else None,
            outputs={str(key): str(value) for key, value in dict(payload.get("outputs") or {}).items()},
            allowedAction=str(payload["allowedAction"]) if payload.get("allowedAction") else None,
            mutexHeld=bool(payload.get("mutexHeld", False)),
            restartedByJobId=str(payload["restartedByJobId"]) if payload.get("restartedByJobId") else None,
            startedAt=str(payload.get("startedAt", "")),
            updatedAt=str(payload.get("updatedAt", "")),
            finishedAt=str(payload["finishedAt"]) if payload.get("finishedAt") else None,
        )


@dataclass(frozen=True)
class WorkflowInspection:
    version: int
    read_only: bool
    allowed_actions: list[str]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task_lock(task_dir: Path) -> threading.RLock:
    key = str(task_dir.expanduser().resolve()).casefold()
    with _TASK_LOCKS_GUARD:
        return _TASK_LOCKS.setdefault(key, threading.RLock())


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = atomic_temp_path(path)
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _workflow_path(task_dir: Path) -> Path:
    return task_dir / ".workflow" / "workflow.json"


def inspect_workflow(task_dir: Path, *, supported_version: int = CURRENT_WORKFLOW_VERSION) -> WorkflowInspection:
    path = _workflow_path(task_dir.expanduser().resolve())
    if not path.exists():
        return WorkflowInspection(CURRENT_WORKFLOW_VERSION, False, ["create"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    version = int(payload.get("version", 1))
    return WorkflowInspection(version, version > supported_version, [] if version > supported_version else ["run", "resume", "restart"])


def initialize_workflow(task_dir: Path, *, version: int = CURRENT_WORKFLOW_VERSION) -> WorkflowInspection:
    path = _workflow_path(task_dir.expanduser().resolve())
    if not path.exists():
        _write_json_atomic(path, {"version": version, "steps": {}})
    return inspect_workflow(task_dir, supported_version=version)


def _migrate_step9_references(value: object) -> object:
    if isinstance(value, str):
        return value.replace("Step3_Pomelo_Keywords", "Step9_Pomelo_Keywords").replace("Step3_Request.txt", "Step9_Request.txt")
    if isinstance(value, list):
        return [_migrate_step9_references(item) for item in value]
    if isinstance(value, dict):
        migrated = {str(key): _migrate_step9_references(item) for key, item in value.items()}
        if migrated.get("stepId") == "step3":
            migrated["stepId"] = "step9"
        return migrated
    return value


def migrate_workflow(task_dir: Path, target_version: int) -> WorkflowInspection:
    path = _workflow_path(task_dir.expanduser().resolve())
    if not path.exists():
        return initialize_workflow(task_dir, version=target_version)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        current = int(payload.get("version", 1))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise WorkflowMigrationError("invalid_workflow_state") from exc
    if current > target_version:
        raise WorkflowMigrationError("unknown_workflow_version")
    if current < 4 <= target_version:
        steps = payload.get("steps")
        if isinstance(steps, dict) and "step3" in steps:
            steps.setdefault("step9", steps.pop("step3"))
        jobs_dir = task_dir / ".workflow" / "jobs"
        try:
            for job_path in jobs_dir.glob("*.json") if jobs_dir.is_dir() else ():
                job_payload = json.loads(job_path.read_text(encoding="utf-8"))
                migrated_job = _migrate_step9_references(job_payload)
                if isinstance(migrated_job, dict):
                    _write_json_atomic(job_path, migrated_job)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise WorkflowMigrationError("invalid_workflow_state") from exc
    payload["version"] = target_version
    payload["steps"] = payload.get("steps") if isinstance(payload.get("steps"), dict) else {}
    _write_json_atomic(path, payload)
    return inspect_workflow(task_dir, supported_version=target_version)


def _relative_reference(task_dir: Path, value: str | Path) -> str:
    path = Path(value)
    resolved = (path if path.is_absolute() else task_dir / path).resolve()
    try:
        return resolved.relative_to(task_dir.resolve()).as_posix()
    except ValueError as exc:
        raise WorkflowMigrationError("path_outside_task") from exc


def _normalize_checkpoint(task_dir: Path, checkpoint: dict[str, object]) -> dict[str, object]:
    normalized = dict(checkpoint)
    for key, value in checkpoint.items():
        compact = "".join(character for character in str(key).lower() if character.isalnum())
        if compact in CHECKPOINT_PATH_KEYS and value not in {None, ""}:
            normalized[str(key)] = _relative_reference(task_dir, str(value))
    return normalized


class JobManager:
    def __init__(self, task_dir: Path) -> None:
        self.task_dir = task_dir.expanduser().resolve()
        self.jobs_dir = self.task_dir / ".workflow" / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = _task_lock(self.task_dir)

    def _path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.json"

    def _save_workflow(self, job: JobRecord) -> None:
        path = _workflow_path(self.task_dir)
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": CURRENT_WORKFLOW_VERSION, "steps": {}}
        payload["version"] = CURRENT_WORKFLOW_VERSION
        steps = payload.get("steps")
        if not isinstance(steps, dict):
            steps = {}
            payload["steps"] = steps
        steps[job.stepId] = {"jobId": job.id, "status": job.status}
        _write_json_atomic(path, payload)

    def _save(self, job: JobRecord, *, update_workflow: bool = True) -> JobRecord:
        with self._lock:
            saved = replace(job, updatedAt=_now())
            _write_json_atomic(self._path(saved.id), saved.to_dict())
            if update_workflow:
                self._save_workflow(saved)
            return saved

    def list_all(self) -> list[JobRecord]:
        with self._lock:
            return [JobRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))) for path in sorted(self.jobs_dir.glob("*.json"))]

    def get(self, job_id: str) -> JobRecord:
        with self._lock:
            return JobRecord.from_dict(json.loads(self._path(job_id).read_text(encoding="utf-8")))

    def _assert_mutex_free(self, *, exclude_job_id: str | None = None) -> None:
        if any(job.id != exclude_job_id and (job.mutexHeld or job.status in ACTIVE_STATUSES) for job in self.list_all()):
            raise JobConflict("task_job_already_active")

    def start(self, step_id: str, action_id: str, execution_kind: str, inputs: dict[str, object], **_ignored) -> JobRecord:
        with self._lock:
            self._assert_mutex_free()
            now = _now()
            job = JobRecord(
                schemaVersion=3,
                id=str(uuid4()),
                stepId=step_id,
                actionId=action_id,
                executionKind="local",
                status="running",
                inputs=sanitize_persisted_job_inputs(inputs),
                startedAt=now,
                updatedAt=now,
            )
            return self._save(job)

    def checkpoint(self, job_id: str, checkpoint: dict[str, object], *, completed: int, total: int) -> JobRecord:
        job = self.get(job_id)
        return self._save(replace(job, checkpoint=_normalize_checkpoint(self.task_dir, checkpoint), completed=completed, total=total))

    def complete(self, job_id: str, outputs: dict[str, str]) -> JobRecord:
        job = self.get(job_id)
        normalized = {key: _relative_reference(self.task_dir, value) for key, value in outputs.items()}
        return self._save(replace(job, status="succeeded", allowedAction=None, outputs=normalized, mutexHeld=False, finishedAt=_now()))

    def fail(self, job_id: str, code: str, outputs: dict[str, str] | None = None) -> JobRecord:
        job = self.get(job_id)
        inputs = {**job.inputs, "failureCode": code}
        normalized = {key: _relative_reference(self.task_dir, value) for key, value in (outputs or {}).items()}
        resumable = job.checkpoint is not None
        return self._save(replace(
            job,
            status="resumable" if resumable else "failed",
            allowedAction="resume" if resumable else "restart",
            outputs=normalized,
            inputs=inputs,
            mutexHeld=False,
            finishedAt=_now(),
        ))

    def pause_local(self, job_id: str, outputs: dict[str, str]) -> JobRecord:
        job = self.get(job_id)
        normalized = {key: _relative_reference(self.task_dir, value) for key, value in outputs.items()}
        return self._save(replace(job, status="resumable", allowedAction="resume", outputs=normalized, mutexHeld=False, finishedAt=_now()))

    def request_stop(self, job_id: str) -> JobRecord:
        job = self.get(job_id)
        if job.status not in ACTIVE_STATUSES:
            raise JobConflict("job_stop_not_allowed")
        return self._save(replace(job, status="stopping", allowedAction=None, mutexHeld=True))

    def resume(self, job_id: str) -> JobRecord:
        job = self.get(job_id)
        if job.allowedAction != "resume":
            raise JobConflict("job_resume_not_allowed")
        self._assert_mutex_free(exclude_job_id=job.id)
        return self._save(replace(job, status="running", allowedAction=None, mutexHeld=True, finishedAt=None))

    def restart(self, job_id: str) -> JobRecord:
        old = self.get(job_id)
        if old.allowedAction != "restart":
            raise JobConflict("job_restart_not_allowed")
        new = self.start(old.stepId, old.actionId, "local", old.inputs)
        self._save(replace(old, restartedByJobId=new.id), update_workflow=False)
        return new

    def reconcile_startup(self) -> list[JobRecord]:
        recovered = []
        for job in self.list_all():
            if job.status not in {"running", "stopping"}:
                continue
            recovered_job = replace(
                job,
                status="resumable" if job.checkpoint else "failed",
                allowedAction="resume" if job.checkpoint else "restart",
                mutexHeld=False,
                finishedAt=_now(),
            )
            recovered.append(self._save(recovered_job))
        return recovered

    def list_recoverable(self) -> list[JobRecord]:
        return [job for job in self.list_all() if job.allowedAction in {"resume", "restart"}]
