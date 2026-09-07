"""Serial batch runner for ASIN keyword downloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import browser as browser_helpers
from input_parser import AsinTask, ParsedTask
from output_writer import (
    append_manifest_row,
    backup_existing_file,
    ensure_run_output_dir,
    keyword_output_path,
    validate_keyword_xlsx,
)
from web_workbench.worker.action_errors import SafeActionError
from pomelo_download_diagnostics import serialize_download_attempts
from pomelo_downloader import collect_keywords, collect_keywords_with_context
from pomelo_download_diagnostics import DownloadAttemptDiagnostic, DownloadStageRecorder

StatusCallback = Callable[[AsinTask, str, str], None]
Collector = Callable[[str, str, str | Path, str, Callable[[str], None] | None], Path]
ProductionCollector = Callable[
    [str, str, str | Path, Callable[[str], None] | None, DownloadStageRecorder],
    Path,
]


@dataclass
class TaskResult:
    task: AsinTask
    status: str
    output_file: Path | None = None
    error: str = ""
    attempts: int = 0
    error_code: str = ""
    download_attempts: tuple[DownloadAttemptDiagnostic, ...] = ()


class BatchRunner:
    """Run ASIN keyword collection tasks serially with retry and status callbacks."""

    def __init__(
        self,
        retry_count: int = 1,
        cdp_url: str = "http://localhost:9222",
        status_callback: StatusCallback | None = None,
        log_callback: Callable[[str], None] | None = None,
        collector: Collector | None = None,
        run_output_dir: str | Path | None = None,
        save_checkpoint: Callable[[dict[str, object], int, int], None] | None = None,
        stop_requested: Callable[[], bool] | None = None,
        publish_progress: Callable[[int, int], None] | None = None,
        context=None,
    ):
        self.retry_count = retry_count
        self.cdp_url = cdp_url
        self.status_callback = status_callback
        self.log_callback = log_callback
        self.collector = collector
        self.run_output_dir = ensure_run_output_dir(run_output_dir)
        self.save_checkpoint = save_checkpoint
        self.external_stop_requested = stop_requested
        self.publish_progress = publish_progress
        self.context = context
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True
        self.log("收到停止请求：当前任务结束后停止。")

    def reset_stop(self) -> None:
        self._stop_requested = False

    def preview_output(self, task: AsinTask) -> Path:
        return keyword_output_path(task.country, task.asin, run_output_dir=self.run_output_dir)

    def emit(self, task: AsinTask, status: str, message: str = "") -> None:
        if self.status_callback:
            self.status_callback(task, status, message)

    def log(self, message: str) -> None:
        if self.log_callback:
            self.log_callback(message)
        else:
            print(message)

    def run(self, parsed_tasks: list[ParsedTask]) -> list[TaskResult]:
        """Run all runnable tasks. Skipped rows are recorded directly."""
        self.reset_stop()
        if self.collector is not None:
            return self._run_serial(parsed_tasks)
        if self.context is not None:
            return self._run_serial(
                parsed_tasks,
                production_collector=self.production_collector(self.context),
            )

        pw = None
        try:
            pw, _browser, context = browser_helpers.attach(self.cdp_url)
            return self._run_serial(
                parsed_tasks,
                production_collector=self.production_collector(context),
            )
        finally:
            if pw is not None:
                browser_helpers.detach(pw)

    def production_collector(self, context: object) -> ProductionCollector:
        return lambda country, asin, out_path, callback, recorder: collect_keywords_with_context(
            context,
            country,
            asin,
            out_path,
            callback,
            download_diagnostics=recorder,
        )

    def _run_serial(
        self,
        parsed_tasks: list[ParsedTask],
        collector: Collector | None = None,
        production_collector: ProductionCollector | None = None,
    ) -> list[TaskResult]:
        collector = collector or self.collector or collect_keywords
        results: list[TaskResult] = []
        total = len(parsed_tasks)
        for index, parsed in enumerate(parsed_tasks, start=1):
            task = parsed.task
            if parsed.status == "已跳过":
                result = TaskResult(task, "已跳过", error=parsed.error, attempts=0)
                self.emit(task, "已跳过", parsed.error)
                self.write_manifest(result)
                results.append(result)
                continue
            if self._stop_requested or (self.external_stop_requested and self.external_stop_requested()):
                break
            result = self.run_one(task, collector, production_collector)
            results.append(result)
            if self.save_checkpoint:
                self.save_checkpoint({"asin": task.asin, "completed": index, "outputDir": str(self.run_output_dir)}, index, total)
            if self.publish_progress:
                self.publish_progress(index, total)
        return results

    def run_one(
        self,
        task: AsinTask,
        collector: Collector | None = None,
        production_collector: ProductionCollector | None = None,
    ) -> TaskResult:
        collector = collector or self.collector or collect_keywords
        output = self.preview_output(task)
        max_attempts = self.retry_count + 1
        last_error = ""
        download_attempts: list[DownloadAttemptDiagnostic] = []
        for attempt in range(1, max_attempts + 1):
            status = "运行中" if attempt == 1 else "重试中"
            self.emit(task, status, f"第 {attempt}/{max_attempts} 次")
            self.log(f"{status}：当前任务第 {attempt}/{max_attempts} 次")
            try:
                backup_existing_file(output)
                recorder = DownloadStageRecorder(attempt)
                try:
                    if production_collector is not None:
                        saved = production_collector(
                            task.country,
                            task.asin,
                            output,
                            self.log,
                            recorder,
                        )
                    else:
                        saved = collector(task.country, task.asin, output, self.cdp_url, self.log)
                finally:
                    snapshot = recorder.snapshot()
                    if snapshot is not None:
                        download_attempts.append(snapshot)
                validation = validate_keyword_xlsx(saved)
                if not validation.ok:
                    raise SafeActionError("pomelo_workbook_invalid")
                result = TaskResult(
                    task,
                    "成功",
                    Path(saved),
                    "",
                    attempt,
                    download_attempts=tuple(download_attempts),
                )
                self.emit(task, "成功", f"{Path(saved).name}，{validation.rows} 行")
                self.write_manifest(result)
                return result
            except Exception as exc:
                safe_error = exc if isinstance(exc, SafeActionError) else SafeActionError("pomelo_collection_failed")
                last_error = safe_error.safe_message
                self.log(f"柚子采集失败：{last_error}")
                if safe_error.retryable and attempt < max_attempts:
                    self.emit(task, "重试中", last_error)
                else:
                    result = TaskResult(
                        task,
                        "失败",
                        None,
                        last_error,
                        attempt,
                        safe_error.code,
                        tuple(download_attempts),
                    )
                    self.emit(task, "失败", last_error)
                    self.write_manifest(result)
                    return result
        result = TaskResult(
            task,
            "失败",
            None,
            last_error or "柚子采集未完成。",
            max_attempts,
            "pomelo_collection_failed",
            tuple(download_attempts),
        )
        self.write_manifest(result)
        return result

    def write_manifest(self, result: TaskResult) -> Path:
        return append_manifest_row(
            {
                "run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "country": result.task.country,
                "asin": result.task.asin,
                "status": result.status,
                "output_file": result.output_file.name if result.output_file else "",
                "error": result.error,
                "attempts": result.attempts,
                "download_diagnostics": serialize_download_attempts(result.download_attempts),
            },
            run_output_dir=self.run_output_dir,
        )
