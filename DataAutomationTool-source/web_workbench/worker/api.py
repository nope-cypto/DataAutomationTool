from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .files import FileBoundaryError, create_task_dir, ensure_task_dir, validate_existing_task_dir
from .job_manager import (
    CURRENT_WORKFLOW_VERSION,
    JobConflict,
    JobManager,
    WorkflowMigrationError,
    initialize_workflow,
    inspect_workflow,
    migrate_workflow,
)
from .security import SessionAuthError, require_session
from .step_execution import LOCAL_ACTION_STEPS, StepExecutor
from .steps.step0 import validate_step0_workbook


WORKFLOW_STEPS = [
    {"id": "step1", "number": "1", "title": "柚子数据下载", "runner": "local_chrome", "status": "ready"},
    {"id": "step2", "number": "2", "title": "麦子拓展数据下载", "runner": "local_http", "status": "ready"},
    {"id": "step9", "number": "9", "title": "柚子关键词下载", "runner": "local_http", "status": "ready"},
]
MAX_JSON_BODY_BYTES = 1_048_576


class WorkerRuntime:
    def __init__(self, session_secret: str) -> None:
        self.session_secret = session_secret
        self.current_task: Path | None = None
        self.workflow_version: int | None = None
        self.workflow_read_only = False
        self.logs = [{"time": "local", "level": "INFO", "message": "本地自动化服务已启动"}]
        self._step_executor: StepExecutor | None = None
        self._step_executor_task: Path | None = None

    def step_executor(self) -> StepExecutor:
        if self._step_executor is None or self._step_executor_task != self.current_task:
            self._step_executor = StepExecutor(self.current_task)
            self._step_executor_task = self.current_task
        return self._step_executor

    def select_task(self, task_dir: Path, *, version: int, read_only: bool) -> None:
        self.current_task = task_dir
        self.workflow_version = version
        self.workflow_read_only = read_only
        self._step_executor = None
        self._step_executor_task = None


def _action_id_from_payload(payload: dict[str, Any]) -> str:
    action_id = str(payload.get("actionId") or "").strip()
    return action_id if action_id in LOCAL_ACTION_STEPS else ""


def create_server(host: str, port: int, *, session_secret: str) -> ThreadingHTTPServer:
    runtime = WorkerRuntime(session_secret=session_secret)

    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Data-Automation-Session")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(body)

        def _require(self) -> bool:
            try:
                require_session(dict(self.headers.items()), runtime.session_secret)
                return True
            except SessionAuthError:
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "invalid_session"})
                return False

        def _read_payload(self) -> dict[str, Any] | None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_content_length"})
                return None
            if length < 0 or length > MAX_JSON_BODY_BYTES:
                status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE if length > MAX_JSON_BODY_BYTES else HTTPStatus.BAD_REQUEST
                self._json(status, {"error": "payload_too_large" if length > MAX_JSON_BODY_BYTES else "invalid_content_length"})
                return None
            if length == 0:
                return {}
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
                return None
            if not isinstance(payload, dict):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "json_object_required"})
                return None
            return payload

        def _error(self, status: int, code: str, message: str) -> None:
            self._json(status, {
                "ok": False,
                "status": "failed",
                "code": code,
                "error": code,
                "message": message,
                "retryable": False,
                "missing": [],
                "outputs": [],
            })

        def _job_route(self) -> tuple[str, str | None] | None:
            parts = self.path.strip("/").split("/")
            if len(parts) < 3 or parts[:2] != ["api", "jobs"]:
                return None
            action = parts[3] if len(parts) == 4 else None
            if len(parts) > 4 or action not in {None, "stop", "resume", "restart"}:
                return None
            return parts[2], action

        def _job_manager(self) -> JobManager | None:
            if runtime.current_task is None:
                self._error(HTTPStatus.CONFLICT, "task_not_selected", "请先选择任务目录。")
                return None
            return JobManager(runtime.current_task)

        def _activate_task(self, task_dir: Path, allow_non_standard: bool) -> dict[str, object]:
            inspection = inspect_workflow(task_dir, supported_version=CURRENT_WORKFLOW_VERSION)
            if not inspection.read_only:
                if inspection.version < CURRENT_WORKFLOW_VERSION:
                    migrate_workflow(task_dir, CURRENT_WORKFLOW_VERSION)
                task_dir = ensure_task_dir(task_dir, allow_non_standard=allow_non_standard)
                JobManager(task_dir).reconcile_startup()
                inspection = inspect_workflow(task_dir, supported_version=CURRENT_WORKFLOW_VERSION)
            runtime.select_task(task_dir, version=inspection.version, read_only=inspection.read_only)
            return {
                "currentTask": str(task_dir),
                "workflowVersion": inspection.version,
                "workflowReadOnly": inspection.read_only,
            }

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._json(HTTPStatus.NO_CONTENT, {})

        def do_GET(self) -> None:  # noqa: N802
            if not self._require():
                return
            if self.path == "/api/health":
                self._json(HTTPStatus.OK, {"ok": True, "service": "data-automation-tool-worker"})
            elif self.path == "/api/workspace":
                self._json(HTTPStatus.OK, {
                    "product": "资料自动化工具",
                    "mode": "local-only",
                    "currentTask": str(runtime.current_task) if runtime.current_task else None,
                    "workflowVersion": runtime.workflow_version,
                    "workflowReadOnly": runtime.workflow_read_only,
                    "steps": WORKFLOW_STEPS,
                })
            elif self.path == "/api/logs":
                self._json(HTTPStatus.OK, {"items": runtime.logs})
            elif self.path == "/api/jobs/resumable":
                manager = self._job_manager()
                if manager is not None:
                    active = [job for job in manager.list_all() if job.status in {"queued", "running", "stopping"}]
                    jobs = {job.id: job for job in [*active, *manager.list_recoverable()]}
                    self._json(HTTPStatus.OK, {"items": [job.to_dict() for job in jobs.values()]})
            elif (job_route := self._job_route()) is not None and job_route[1] is None:
                manager = self._job_manager()
                if manager is not None:
                    try:
                        self._json(HTTPStatus.OK, manager.get(job_route[0]).to_dict())
                    except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError):
                        self._error(HTTPStatus.NOT_FOUND, "job_not_found", "任务记录不存在。")
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._require():
                return
            if self.path == "/api/task/create":
                payload = self._read_payload()
                if payload is None:
                    return
                task_name = str(payload.get("taskName") or "").strip()
                parent_dir = str(payload.get("parentDir") or "").strip()
                if not task_name:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "task_name_required"})
                    return
                if not parent_dir:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "parent_directory_required"})
                    return
                try:
                    task_dir = create_task_dir(Path(parent_dir), task_name)
                    initialize_workflow(task_dir)
                    result = self._activate_task(task_dir, False)
                except (FileBoundaryError, WorkflowMigrationError, OSError, ValueError) as exc:
                    self._error(HTTPStatus.BAD_REQUEST, str(exc), "无法创建任务目录。")
                    return
                runtime.logs.insert(0, {"time": "local", "level": "OK", "message": "已创建本地下载任务"})
                self._json(HTTPStatus.OK, result)
            elif self.path == "/api/task/select":
                payload = self._read_payload()
                if payload is None:
                    return
                task_dir_value = str(payload.get("taskDir") or "").strip()
                allow_non_standard = bool(payload.get("allowNonStandard"))
                try:
                    task_dir = validate_existing_task_dir(Path(task_dir_value), allow_non_standard=allow_non_standard)
                    result = self._activate_task(task_dir, allow_non_standard)
                except (FileBoundaryError, WorkflowMigrationError, OSError, ValueError, json.JSONDecodeError) as exc:
                    self._error(HTTPStatus.BAD_REQUEST, str(exc), "无法打开任务目录。")
                    return
                self._json(HTTPStatus.OK, result)
            elif self.path == "/api/preflight":
                step0 = validate_step0_workbook(runtime.current_task / "Step0_ASIN_Input" / "Step0_ASIN_Input.xlsx") if runtime.current_task else None
                checks = [
                    {"id": "task_folder", "label": "任务目录", "ok": runtime.current_task is not None, "detail": str(runtime.current_task) if runtime.current_task else "未选择"},
                    {"id": "asin_workbook", "label": "ASIN 输入表", "ok": bool(step0 and step0.get("ok")), "detail": f"ASIN {step0.get('asinCount', 0)} 条" if step0 else "未检查"},
                ]
                ok_count = sum(1 for check in checks if check["ok"])
                self._json(HTTPStatus.OK, {"task": str(runtime.current_task) if runtime.current_task else None, "checks": checks, "okCount": ok_count, "missingCount": len(checks) - ok_count})
            elif self.path == "/api/steps/step0/validate":
                if runtime.current_task is None:
                    self._error(HTTPStatus.CONFLICT, "task_not_selected", "请先选择任务目录。")
                else:
                    result = validate_step0_workbook(runtime.current_task / "Step0_ASIN_Input" / "Step0_ASIN_Input.xlsx")
                    self._json(HTTPStatus.OK, result)
            elif self.path.startswith("/api/steps/") and self.path.endswith("/run"):
                if runtime.current_task is None:
                    self._error(HTTPStatus.CONFLICT, "task_not_selected", "请先选择任务目录。")
                    return
                if runtime.workflow_read_only:
                    self._error(HTTPStatus.CONFLICT, "workflow_read_only", "该任务来自更高版本，只能查看。")
                    return
                payload = self._read_payload()
                if payload is None:
                    return
                action_id = _action_id_from_payload(payload)
                if not action_id:
                    self._error(HTTPStatus.BAD_REQUEST, "unknown_action", "不支持的下载动作。")
                    return
                route_step_id = self.path.strip("/").split("/")[2]
                if LOCAL_ACTION_STEPS[action_id] != route_step_id:
                    self._error(HTTPStatus.BAD_REQUEST, "action_step_mismatch", "下载动作与步骤不匹配。")
                    return
                result = runtime.step_executor().run_action(action_id, payload)
                self._json(HTTPStatus.OK if result.ok else HTTPStatus.BAD_REQUEST, result.to_dict())
            elif (job_route := self._job_route()) is not None and job_route[1] is not None:
                manager = self._job_manager()
                if manager is None:
                    return
                job_id, action = job_route
                try:
                    if action == "stop":
                        job = manager.request_stop(job_id)
                        self._json(HTTPStatus.ACCEPTED, {"ok": True, "jobId": job.id, "job": job.to_dict()})
                    elif action == "resume":
                        result = runtime.step_executor().resume_job(job_id)
                        self._json(HTTPStatus.OK if result.ok else HTTPStatus.CONFLICT, result.to_dict())
                    else:
                        result = runtime.step_executor().restart_job(job_id)
                        self._json(HTTPStatus.OK if result.ok else HTTPStatus.CONFLICT, result.to_dict())
                except FileNotFoundError:
                    self._error(HTTPStatus.NOT_FOUND, "job_not_found", "任务记录不存在。")
                except (JobConflict, ValueError, TypeError, json.JSONDecodeError) as exc:
                    self._error(HTTPStatus.CONFLICT, str(exc), "当前不能执行这个任务动作。")
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)
