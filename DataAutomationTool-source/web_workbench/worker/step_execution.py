from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from .action_errors import SafeActionError, safe_local_action_failure
from .files import beijing_timestamp, is_transient_workflow_file
from .job_manager import CHECKPOINT_PATH_KEYS, JobConflict, JobManager
from .step_results import StepResult
from .steps.step0 import read_step0_market
from pomelo_download_diagnostics import validate_download_attempts


LOCAL_ACTION_STEPS = {
    "pomelo_parse": "step1",
    "pomelo_download": "step1",
    "wheat_connect": "step2",
    "wheat_download": "step2",
    "pomelo_keywords_connect": "step9",
    "pomelo_keywords_test_two_batches": "step9",
    "pomelo_keywords_download": "step9",
}
READ_ONLY_LOCAL_ACTIONS = {"pomelo_parse"}


@dataclass(frozen=True)
class LocalActionOutcome:
    status: str
    outputs: dict[str, str]
    checkpoint: dict[str, object] | None = None
    data: dict[str, object] | None = None
    error_code: str | None = None


class DefaultLocalRuntime:
    def __init__(self, task_dir: Path, *, runtime_attacher=None, pomelo_collector=None) -> None:
        self.task_dir = task_dir
        self.runtime_attacher = runtime_attacher
        self.pomelo_collector = pomelo_collector

    def prepare_pomelo_runtime(self):
        import browser as browser_helpers

        attach_runtime = self.runtime_attacher or browser_helpers.attach_with_fallback
        return attach_runtime("http://localhost:9222")

    def _resolve_task_path(self, value: object) -> Path:
        path = Path(str(value or ""))
        resolved = (path if path.is_absolute() else self.task_dir / path).resolve()
        if not resolved.is_relative_to(self.task_dir.resolve()):
            raise FileNotFoundError("path_outside_task")
        return resolved

    def _task_reference(self, path: Path) -> str:
        return path.resolve().relative_to(self.task_dir.resolve()).as_posix()

    def _step0_market(self, checkpoint: dict[str, object] | None = None) -> str:
        path = self.task_dir / "Step0_ASIN_Input" / "Step0_ASIN_Input.xlsx"
        try:
            market = read_step0_market(path)
        except (OSError, ValueError):
            raise SafeActionError("step0_market_invalid") from None
        if checkpoint is not None and checkpoint.get("market") and str(checkpoint["market"]) != market:
            raise SafeActionError("step0_market_changed")
        return market

    def execute(
        self,
        action_id: str,
        payload: dict[str, object],
        *,
        checkpoint: dict[str, object] | None,
        save_checkpoint,
        stop_requested,
        publish_progress,
        attached_runtime=None,
    ) -> LocalActionOutcome:
        if action_id == "pomelo_parse":
            return self._parse_pomelo(payload)
        if action_id == "pomelo_download":
            return self._run_pomelo(
                payload,
                checkpoint,
                save_checkpoint,
                stop_requested,
                publish_progress,
                attached_runtime,
            )
        if action_id == "wheat_connect":
            return self._test_wheat_connectivity()
        if action_id == "wheat_download":
            return self._run_wheat(
                payload,
                checkpoint,
                save_checkpoint,
                stop_requested,
                publish_progress,
            )
        if action_id in {"pomelo_keywords_connect", "pomelo_keywords_test_two_batches", "pomelo_keywords_download"}:
            return self._run_pomelo_keywords(
                action_id,
                payload,
                checkpoint,
                save_checkpoint,
                stop_requested,
                publish_progress,
            )
        raise RuntimeError("unsupported_local_action")

    def _parse_pomelo(self, payload: dict[str, object]) -> LocalActionOutcome:
        from input_parser import parse_file

        source_path = Path(str(payload.get("sourcePath") or ""))
        if not source_path.is_file() or is_transient_workflow_file(source_path):
            raise FileNotFoundError("missing_pomelo_import")
        parsed = parse_file(source_path)
        items = [
            {
                "country": item.country,
                "asin": item.asin,
                "status": item.status,
                "error": item.error,
            }
            for item in parsed
        ]
        runnable_count = sum(1 for item in parsed if item.status != "已跳过")
        return LocalActionOutcome(
            "succeeded",
            {},
            data={
                "items": items,
                "count": len(items),
                "runnableCount": runnable_count,
                "skippedCount": len(items) - runnable_count,
            },
        )

    def _run_pomelo(
        self,
        payload,
        checkpoint,
        save_checkpoint,
        stop_requested,
        publish_progress,
        attached_runtime=None,
    ) -> LocalActionOutcome:
        from input_parser import AsinTask, finalize_tasks

        step_root = (self.task_dir / "Step1_Pomelo_Data").resolve()
        output_dir = (
            self._resolve_task_path(checkpoint["outputDir"])
            if checkpoint and checkpoint.get("outputDir")
            else step_root / beijing_timestamp()
        )
        raw_items = payload.get("items")
        input_file_value = (checkpoint or {}).get("inputFile")
        if (not isinstance(raw_items, list) or not raw_items) and input_file_value:
            snapshot = json.loads(self._resolve_task_path(input_file_value).read_text(encoding="utf-8"))
            raw_items = snapshot.get("items") if isinstance(snapshot, dict) else None
        if not isinstance(raw_items, list) or not raw_items:
            raise FileNotFoundError("missing_pomelo_items")
        raw_tasks = [
            AsinTask(str(item.get("country") or ""), str(item.get("asin") or ""), "electron")
            for item in raw_items
            if isinstance(item, dict)
        ]
        completed_base = int((checkpoint or {}).get("completed", 0))
        parsed = finalize_tasks(raw_tasks)[completed_base:]
        if not parsed:
            raise FileNotFoundError("missing_pomelo_items")

        attached = attached_runtime or self.prepare_pomelo_runtime()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            input_file = output_dir / ".pomelo_input.json"
            input_payload = {"items": [{"country": task.country, "asin": task.asin} for task in raw_tasks]}
            input_temp = input_file.with_suffix(".json.tmp")
            input_temp.write_text(json.dumps(input_payload, ensure_ascii=False), encoding="utf-8")
            input_temp.replace(input_file)
            return self._run_pomelo_attached(
                output_dir,
                input_file,
                raw_tasks,
                parsed,
                completed_base,
                checkpoint,
                save_checkpoint,
                stop_requested,
                publish_progress,
                attached.context,
            )
        finally:
            attached.close()

    def _run_pomelo_attached(
        self,
        output_dir,
        input_file,
        raw_tasks,
        parsed,
        completed_base,
        checkpoint,
        save_checkpoint,
        stop_requested,
        publish_progress,
        context,
    ) -> LocalActionOutcome:
        from batch_runner import BatchRunner

        output_reference = self._task_reference(output_dir)
        input_reference = self._task_reference(input_file)
        item_statuses = {
            int(item["index"]): str(item["status"])
            for item in ((checkpoint or {}).get("itemStatuses") or [])
            if isinstance(item, dict)
            and isinstance(item.get("index"), int)
            and str(item.get("status") or "") in {"运行中", "重试中", "成功", "失败"}
        }

        def safe_checkpoint(completed: int) -> dict[str, object]:
            return {
                "completed": completed,
                "outputDir": output_reference,
                "inputFile": input_reference,
                "itemStatuses": [
                    {"index": index, "status": item_statuses[index]}
                    for index in sorted(item_statuses)
                ],
            }

        task_indexes: dict[tuple[str, str], int] = {}
        for index, item in enumerate(parsed):
            task_indexes.setdefault((item.country, item.asin), completed_base + index)

        def checkpoint_status(task, status, _message):
            if status not in {"运行中", "重试中", "成功", "失败"}:
                return
            index = task_indexes.get((str(task.country), str(task.asin)))
            if index is None:
                return
            item_statuses[index] = status
            completed = max(completed_base, index if status in {"运行中", "重试中", "失败"} else index + 1)
            save_checkpoint(safe_checkpoint(completed), completed, len(raw_tasks))

        def checkpoint_asin(_value, completed, _total):
            absolute = completed_base + completed
            save_checkpoint(safe_checkpoint(absolute), absolute, len(raw_tasks))

        save_checkpoint(safe_checkpoint(completed_base), completed_base, len(raw_tasks))
        runner_arguments = {
            "run_output_dir": output_dir,
            "status_callback": checkpoint_status,
            "save_checkpoint": checkpoint_asin,
            "stop_requested": stop_requested,
            "publish_progress": lambda completed, _total: publish_progress(completed_base + completed, len(raw_tasks)),
            "context": context,
        }
        if self.pomelo_collector is not None:
            runner_arguments["collector"] = self.pomelo_collector
        results = BatchRunner(**runner_arguments).run(parsed)
        failed_results = [result for result in results if str(result.status) == "失败"]
        status = "resumable" if stop_requested() else "failed" if failed_results else "succeeded"
        result_items = [
            {
                "country": result.task.country,
                "asin": result.task.asin,
                "status": result.status,
                "error": result.error,
            }
            for result in results
        ]
        selected_records = (
            failed_results[0].download_attempts
            if failed_results
            else results[0].download_attempts if len(results) == 1 else ()
        )
        return LocalActionOutcome(
            status,
            {"runDir": str(output_dir)},
            safe_checkpoint(completed_base),
            data={"items": result_items, "downloadAttempts": validate_download_attempts(selected_records) or []},
            error_code=failed_results[0].error_code or "pomelo_collection_failed" if failed_results else None,
        )

    def _run_wheat(self, payload, checkpoint, save_checkpoint, stop_requested, publish_progress) -> LocalActionOutcome:
        from wheat_expansion.exporter import WheatRequestInterrupted, fetch_from_curl_and_asins

        market = self._step0_market(checkpoint)
        curl_path = self.task_dir / "Step2_Wheat_Expansion" / "Step2_Request.txt"
        step0_path = self.task_dir / "Step0_ASIN_Input" / "Step0_ASIN_Input.xlsx"
        output_dir = Path(str((checkpoint or {}).get("outputDir") or self.task_dir / "Step2_Wheat_Expansion" / beijing_timestamp()))
        latest_checkpoint = dict(checkpoint or {})

        def checkpoint_batch(value):
            nonlocal latest_checkpoint
            value = dict(value)
            value["market"] = market
            latest_checkpoint = value
            save_checkpoint(value, int(value.get("completedBatch", 0)), int(value["totalBatches"]))

        try:
            raw, meta, _rows = fetch_from_curl_and_asins(
                curl_path,
                step0_path,
                output_dir=output_dir,
                country=market,
                max_batches=int(payload["maxBatches"]) if payload.get("maxBatches") else None,
                resume=checkpoint is not None,
                resume_checkpoint=checkpoint,
                save_checkpoint=checkpoint_batch,
                stop_requested=stop_requested,
                publish_progress=publish_progress,
            )
        except WheatRequestInterrupted:
            if int(latest_checkpoint.get("lastSavedPage") or 0) <= 0:
                raise
            latest_checkpoint["interruptionReason"] = "request_failed"
            checkpoint_batch(latest_checkpoint)
            return LocalActionOutcome("resumable", {"runDir": str(output_dir)}, latest_checkpoint)
        status = "resumable" if stop_requested() else "succeeded"
        return LocalActionOutcome(
            status,
            {"rawPages": str(raw), "runMeta": str(meta), "runDir": str(output_dir)},
            latest_checkpoint,
        )

    def _test_wheat_connectivity(self) -> LocalActionOutcome:
        from wheat_expansion.exporter import test_curl_and_asins_connectivity

        market = self._step0_market()
        test_curl_and_asins_connectivity(
            self.task_dir / "Step2_Wheat_Expansion" / "Step2_Request.txt",
            self.task_dir / "Step0_ASIN_Input" / "Step0_ASIN_Input.xlsx",
            country=market,
        )
        return LocalActionOutcome("succeeded", {})

    def _run_pomelo_keywords(self, action_id, payload, checkpoint, save_checkpoint, stop_requested, publish_progress) -> LocalActionOutcome:
        import pomelo_keywords_export as exporter

        curl_path = self.task_dir / "Step9_Pomelo_Keywords" / "Step9_Request.txt"
        market = self._step0_market(checkpoint)
        checkpoint_keywords = (checkpoint or {}).get("keywordsFile")
        keywords_path = (
            self._resolve_task_path(checkpoint_keywords)
            if checkpoint_keywords
            else Path(str(payload.get("keywordsPath") or "")).expanduser().resolve()
        )
        if (
            not keywords_path.is_file()
            or keywords_path.suffix.lower() not in {".xlsx", ".xlsm", ".csv", ".txt"}
            or is_transient_workflow_file(keywords_path)
        ):
            raise FileNotFoundError("invalid_step9_keywords_file")
        if action_id == "pomelo_keywords_connect":
            request = exporter.load_curl(curl_path)
            keywords = exporter.load_keywords(str(keywords_path), request.payload, exporter.DEFAULT_KEYWORDS_SHEET, 1)
            data = exporter.post_json(request, exporter.payload_for_batch(request.payload, market, keywords[:1], 48), timeout=10)
            exporter.validate_response(data)
            return LocalActionOutcome("succeeded", {})
        if action_id == "pomelo_keywords_download" and not bool(payload.get("confirmFull")):
            raise RuntimeError("pomelo_keywords_download_confirmation_required")

        is_test = action_id == "pomelo_keywords_test_two_batches"
        output_dir = (
            self._resolve_task_path(checkpoint["outputDir"])
            if checkpoint and checkpoint.get("outputDir")
            else self.task_dir / "Step9_Pomelo_Keywords" / (f"test_{beijing_timestamp()}" if is_test else beijing_timestamp())
        )
        if not checkpoint_keywords:
            output_dir.mkdir(parents=True, exist_ok=True)
            snapshot = output_dir / f"关键词输入{keywords_path.suffix.lower()}"
            temp = snapshot.with_name(f".{snapshot.name}.tmp")
            try:
                shutil.copy2(keywords_path, temp)
                temp.replace(snapshot)
            finally:
                temp.unlink(missing_ok=True)
            keywords_path = snapshot
        keywords_reference = self._task_reference(keywords_path)
        output_reference = self._task_reference(output_dir)

        def checkpoint_batch(value):
            value = dict(value)
            value.update({"market": market, "outputDir": output_reference, "keywordsFile": keywords_reference})
            save_checkpoint(value, int(value.get("completedBatch", 0)), int(value.get("totalBatches", 0)))

        try:
            raw_path = exporter.run_export(
                curl_path=curl_path,
                keywords_path=str(keywords_path),
                sheet_name=exporter.DEFAULT_KEYWORDS_SHEET,
                batch_size=200,
                max_batches=2 if is_test else None,
                limit=None,
                delay=0,
                output_dir=output_dir,
                country=market,
                asins_count=48,
                timeout=60,
                confirm_full=True,
                resume=checkpoint is not None,
                save_checkpoint=checkpoint_batch,
                stop_requested=stop_requested,
                publish_progress=publish_progress,
            )
            status = "resumable" if stop_requested() else "succeeded"
        except exporter.BatchIncompleteError as exc:
            checkpoint_batch({"completedBatch": exc.completed_batch, "totalBatches": exc.total_batches})
            raw_path = exc.raw_path
            status = "resumable"
        result_checkpoint = {
            "market": market,
            "outputDir": output_reference,
            "keywordsFile": keywords_reference,
        }
        return LocalActionOutcome(status, {"rawPages": str(raw_path), "runDir": str(output_dir)}, result_checkpoint)


class StepExecutor:
    def __init__(self, task_dir: Path | None, *, local_runtime=None) -> None:
        self.task_dir = task_dir
        self.local_runtime = local_runtime if local_runtime is not None else DefaultLocalRuntime(task_dir) if task_dir else None
        self._local_payloads: dict[str, dict[str, object]] = {}

    def _require_task(self, step_id: str) -> StepResult | None:
        if self.task_dir is None:
            return StepResult(False, step_id, "blocked", "请先选择任务目录。", code="task_not_selected")
        return None

    def _runtime_checkpoint(self, checkpoint: dict[str, object] | None) -> dict[str, object] | None:
        if checkpoint is None or self.task_dir is None:
            return checkpoint
        restored = dict(checkpoint)
        for key, value in checkpoint.items():
            compact_key = "".join(character for character in str(key).lower() if character.isalnum())
            if compact_key not in CHECKPOINT_PATH_KEYS or value in {None, ""}:
                continue
            path = Path(str(value))
            resolved = (path if path.is_absolute() else self.task_dir / path).resolve()
            if not resolved.is_relative_to(self.task_dir.resolve()):
                raise FileNotFoundError("checkpoint_path_outside_task")
            restored[str(key)] = str(resolved)
        return restored

    def _local_result(self, step_id: str, action_id: str, job_id: str, outcome: LocalActionOutcome) -> StepResult:
        outputs = {str(key): str(value) for key, value in outcome.outputs.items()}
        manager = JobManager(self.task_dir)
        if outcome.status == "resumable":
            manager.pause_local(job_id, outputs)
            return StepResult(True, step_id, "resumable", "下载已暂停，可继续。", outputs=list(outputs.values()), job_id=job_id, data=outcome.data or {})
        if outcome.status == "succeeded":
            manager.complete(job_id, outputs)
            return StepResult(True, step_id, "succeeded", "下载完成。", outputs=list(outputs.values()), job_id=job_id, data=outcome.data or {})
        failure = SafeActionError(outcome.error_code or {
            "pomelo_download": "pomelo_collection_failed",
            "wheat_connect": "wheat_connect_failed",
            "wheat_download": "wheat_download_failed",
            "pomelo_keywords_connect": "pomelo_keywords_connect_failed",
            "pomelo_keywords_test_two_batches": "pomelo_keywords_test_failed",
            "pomelo_keywords_download": "pomelo_keywords_download_failed",
        }[action_id])
        saved = manager.fail(job_id, failure.code, outputs)
        if saved.status == "resumable":
            return StepResult(True, step_id, "resumable", f"{failure.safe_message}已保存断点，可继续。", outputs=list(outputs.values()), job_id=job_id, code=failure.code, retryable=True, data=outcome.data or {})
        return StepResult(False, step_id, "failed", failure.safe_message, outputs=list(outputs.values()), job_id=job_id, code=failure.code, retryable=failure.retryable, data=outcome.data or {})

    def _execute_local_job(self, job_id: str, action_id: str, payload: dict[str, object], checkpoint: dict[str, object] | None, *, attached_runtime=None) -> StepResult:
        if self.task_dir is None or self.local_runtime is None:
            return StepResult(False, LOCAL_ACTION_STEPS.get(action_id, "unknown"), "blocked", "本地运行环境不可用。", code="local_runtime_unavailable")
        manager = JobManager(self.task_dir)

        def save_checkpoint(value: dict[str, object], completed: int, total: int) -> None:
            manager.checkpoint(job_id, value, completed=completed, total=total)

        def stop_requested() -> bool:
            return manager.get(job_id).status in {"stopping", "resumable", "failed"}

        def publish_progress(completed: int, total: int) -> None:
            current = manager.get(job_id)
            if current.checkpoint is not None:
                manager.checkpoint(job_id, current.checkpoint, completed=completed, total=total)

        try:
            arguments = {
                "checkpoint": self._runtime_checkpoint(checkpoint),
                "save_checkpoint": save_checkpoint,
                "stop_requested": stop_requested,
                "publish_progress": publish_progress,
            }
            if attached_runtime is not None:
                arguments["attached_runtime"] = attached_runtime
            outcome = self.local_runtime.execute(action_id, payload, **arguments)
        except Exception as exc:
            failure = safe_local_action_failure(action_id, exc)
            saved = manager.fail(job_id, failure.code)
            if saved.status == "resumable":
                return StepResult(True, LOCAL_ACTION_STEPS[action_id], "resumable", f"{failure.safe_message}已保存断点，可继续。", job_id=job_id, code=failure.code, retryable=True)
            return StepResult(False, LOCAL_ACTION_STEPS[action_id], "failed", failure.safe_message, job_id=job_id, code=failure.code, retryable=failure.retryable, diagnostic_id=failure.diagnostic_id)
        return self._local_result(LOCAL_ACTION_STEPS[action_id], action_id, job_id, outcome)

    def run_action(self, action_id: str, payload: dict[str, object]) -> StepResult:
        step_id = LOCAL_ACTION_STEPS.get(action_id)
        if step_id is None:
            return StepResult(False, "unknown", "blocked", "不支持的下载动作。", code="unknown_action")
        if blocked := self._require_task(step_id):
            return blocked
        if self.local_runtime is None:
            return StepResult(False, step_id, "blocked", "本地运行环境不可用。", code="local_runtime_unavailable")
        if action_id in READ_ONLY_LOCAL_ACTIONS:
            try:
                outcome = self.local_runtime.execute(action_id, payload, checkpoint=None, save_checkpoint=lambda *_: None, stop_requested=lambda: False, publish_progress=lambda *_: None)
            except Exception as exc:
                failure = safe_local_action_failure(action_id, exc)
                return StepResult(False, step_id, "failed", failure.safe_message, code=failure.code, retryable=failure.retryable)
            return StepResult(True, step_id, "succeeded", "输入文件解析完成。", data=outcome.data or {})

        attached_runtime = None
        if action_id == "pomelo_download":
            try:
                attached_runtime = self.local_runtime.prepare_pomelo_runtime()
            except Exception as exc:
                failure = safe_local_action_failure(action_id, exc)
                return StepResult(False, step_id, "failed", failure.safe_message, code=failure.code, retryable=failure.retryable, diagnostic_id=failure.diagnostic_id)
        manager = JobManager(self.task_dir)
        try:
            job = manager.start(step_id, action_id, "local", payload)
        except JobConflict:
            if attached_runtime is not None:
                attached_runtime.close()
            return StepResult(False, step_id, "blocked", "当前任务已有下载正在运行。", code="task_job_already_active", retryable=True)
        self._local_payloads[job.id] = dict(payload)
        result = self._execute_local_job(job.id, action_id, payload, None, attached_runtime=attached_runtime)
        if result.status != "resumable":
            self._local_payloads.pop(job.id, None)
        return result

    def resume_job(self, job_id: str) -> StepResult:
        if self.task_dir is None:
            return StepResult(False, "unknown", "blocked", "请先选择任务目录。", code="task_not_selected")
        manager = JobManager(self.task_dir)
        try:
            job = manager.resume(job_id)
        except (FileNotFoundError, JobConflict):
            return StepResult(False, "unknown", "blocked", "当前任务不能继续。", code="job_resume_not_allowed")
        payload = self._local_payloads.get(job.id, job.inputs)
        attached_runtime = None
        if job.actionId == "pomelo_download" and self.local_runtime is not None:
            try:
                attached_runtime = self.local_runtime.prepare_pomelo_runtime()
            except Exception as exc:
                failure = safe_local_action_failure(job.actionId, exc)
                manager.pause_local(job.id, job.outputs)
                return StepResult(False, job.stepId, "resumable", failure.safe_message, job_id=job.id, code=failure.code, retryable=failure.retryable)
        result = self._execute_local_job(job.id, job.actionId, payload, job.checkpoint, attached_runtime=attached_runtime)
        if result.status != "resumable":
            self._local_payloads.pop(job.id, None)
        return result

    def restart_job(self, job_id: str) -> StepResult:
        if self.task_dir is None:
            return StepResult(False, "unknown", "blocked", "请先选择任务目录。", code="task_not_selected")
        manager = JobManager(self.task_dir)
        try:
            old = manager.get(job_id)
            job = manager.restart(job_id)
        except (FileNotFoundError, JobConflict):
            return StepResult(False, "unknown", "blocked", "当前任务不能重启。", code="job_restart_not_allowed")
        payload = self._local_payloads.get(old.id, old.inputs)
        self._local_payloads[job.id] = dict(payload)
        return self._execute_local_job(job.id, job.actionId, payload, None)
