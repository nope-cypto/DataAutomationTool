from __future__ import annotations

import json
from pathlib import Path
import threading
import urllib.request

import openpyxl

import pomelo_keywords_export as pomelo_keywords_downloader
import wheat_expansion.exporter as wheat_downloader
from web_workbench.worker.api import create_server
from web_workbench.worker.files import STEP_DIRS, ensure_task_dir, validate_task_directory
from web_workbench.worker.job_manager import CURRENT_WORKFLOW_VERSION, migrate_workflow
from web_workbench.worker.step_execution import DefaultLocalRuntime


def _write_step0(path: Path, country: str = "US", asin: str = "B000123456") -> None:
    workbook = openpyxl.Workbook()
    try:
        sheet = workbook.active
        sheet.append(["国家", "竞品ASIN", "竞品强弱"])
        sheet.append([country, asin, ""])
        workbook.save(path)
    finally:
        workbook.close()


def test_task_structure_contains_only_download_steps(tmp_path: Path) -> None:
    task = ensure_task_dir(tmp_path / "custom-task", allow_non_standard=True)

    for dirname in STEP_DIRS:
        assert (task / dirname).is_dir()
    assert (task / "Step2_Wheat_Expansion" / "Step2_Request.txt").is_file()
    assert (task / "Step9_Pomelo_Keywords" / "Step9_Request.txt").is_file()
    for removed in ["step1_2_aba", "step1_3", "step2_1_2", "step2_1_4"]:
        assert not (task / removed).exists()


def test_legacy_task_folders_and_request_files_are_renamed(tmp_path: Path) -> None:
    task = tmp_path / "custom-task"
    legacy_step0 = task / "Step0_Competitor_ASINS"
    legacy_step2 = task / "step1_1_2_sellersprite"
    legacy_step3 = task / "step2_1_xiyou_top_asins"
    legacy_step0.mkdir(parents=True)
    (task / "step1_1_1_xiyou").mkdir()
    legacy_step2.mkdir()
    legacy_step3.mkdir()
    _write_step0(legacy_step0 / "Step0_Competitor_ASINS.xlsx")
    (legacy_step2 / "request.txt").write_text("step-2-secret", encoding="utf-8")
    (legacy_step3 / "request_top_asins.txt").write_text("step-3-secret", encoding="utf-8")

    ensure_task_dir(task, allow_non_standard=True)

    assert not legacy_step0.exists()
    assert not (task / "step1_1_1_xiyou").exists()
    assert not legacy_step2.exists()
    assert not legacy_step3.exists()
    assert (task / "Step0_ASIN_Input" / "Step0_ASIN_Input.xlsx").is_file()
    assert (task / "Step2_Wheat_Expansion" / "Step2_Request.txt").read_text(encoding="utf-8") == "step-2-secret"
    assert (task / "Step9_Pomelo_Keywords" / "Step9_Request.txt").read_text(encoding="utf-8") == "step-3-secret"


def test_previous_step3_folder_is_migrated_to_step9(tmp_path: Path) -> None:
    task = tmp_path / "custom-task"
    previous_step3 = task / "Step3_Pomelo_Keywords"
    previous_step3.mkdir(parents=True)
    (previous_step3 / "Step3_Request.txt").write_text("saved-current-curl", encoding="utf-8")

    ensure_task_dir(task, allow_non_standard=True)

    assert not previous_step3.exists()
    assert (task / "Step9_Pomelo_Keywords" / "Step9_Request.txt").read_text(encoding="utf-8") == "saved-current-curl"


def test_mistaken_wheat_keyword_folder_is_corrected(tmp_path: Path) -> None:
    task = tmp_path / "custom-task"
    mistaken_step3 = task / "Step3_Wheat_Keywords"
    mistaken_step3.mkdir(parents=True)
    (mistaken_step3 / "Step3_Request.txt").write_text("saved-curl", encoding="utf-8")

    ensure_task_dir(task, allow_non_standard=True)

    assert not mistaken_step3.exists()
    assert (task / "Step9_Pomelo_Keywords" / "Step9_Request.txt").read_text(encoding="utf-8") == "saved-curl"


def test_step3_workflow_and_job_references_are_migrated_to_step9(tmp_path: Path) -> None:
    task = tmp_path / "custom-task"
    jobs_dir = task / ".workflow" / "jobs"
    jobs_dir.mkdir(parents=True)
    workflow_path = task / ".workflow" / "workflow.json"
    workflow_path.write_text(
        json.dumps({"version": 3, "steps": {"step3": {"jobId": "job-1", "status": "resumable"}}}),
        encoding="utf-8",
    )
    job_path = jobs_dir / "job-1.json"
    job_path.write_text(
        json.dumps({
            "schemaVersion": 3,
            "id": "job-1",
            "stepId": "step3",
            "actionId": "pomelo_keywords_download",
            "checkpoint": {
                "outputDir": "Step3_Pomelo_Keywords/run-1",
                "requestFile": "Step3_Pomelo_Keywords/Step3_Request.txt",
            },
        }),
        encoding="utf-8",
    )

    migrate_workflow(task, CURRENT_WORKFLOW_VERSION)

    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    job = json.loads(job_path.read_text(encoding="utf-8"))
    assert CURRENT_WORKFLOW_VERSION == 4
    assert workflow["version"] == 4
    assert "step3" not in workflow["steps"]
    assert workflow["steps"]["step9"]["jobId"] == "job-1"
    assert job["stepId"] == "step9"
    assert job["checkpoint"]["outputDir"] == "Step9_Pomelo_Keywords/run-1"
    assert job["checkpoint"]["requestFile"] == "Step9_Pomelo_Keywords/Step9_Request.txt"


def test_pomelo_parser_preserves_each_input_country(tmp_path: Path) -> None:
    source = tmp_path / "asins.csv"
    source.write_text("国家,ASIN\nJP,B000123456\nDE,B000654321\n", encoding="utf-8")

    result = DefaultLocalRuntime(tmp_path)._parse_pomelo({"sourcePath": str(source)})

    assert [item["country"] for item in result.data["items"]] == ["JP", "DE"]
    assert result.data["runnableCount"] == 2


def test_pomelo_keyword_download_writes_raw_response_only(tmp_path: Path, monkeypatch) -> None:
    keywords = tmp_path / "keywords.txt"
    keywords.write_text("phone case\ncharger\n", encoding="utf-8")
    output = tmp_path / "top-output"
    response = {"entities": [{"asin": "B000123456"}], "opaque": {"kept": True}}
    monkeypatch.setattr(
        pomelo_keywords_downloader,
        "load_curl",
        lambda _path: pomelo_keywords_downloader.CurlRequest("https://example.test", {}, {"resource": {}, "biz": {}}),
    )
    monkeypatch.setattr(pomelo_keywords_downloader, "post_json", lambda *_args, **_kwargs: response)

    raw_path = pomelo_keywords_downloader.run_export(
        curl_path=tmp_path / "request.txt",
        keywords_path=str(keywords),
        sheet_name=pomelo_keywords_downloader.DEFAULT_KEYWORDS_SHEET,
        batch_size=200,
        max_batches=None,
        limit=None,
        delay=0,
        output_dir=output,
        country="US",
        asins_count=48,
        timeout=1,
        confirm_full=True,
    )

    record = json.loads(raw_path.read_text(encoding="utf-8").strip())
    assert record["response"] == response
    assert {path.name for path in output.iterdir()} == {
        pomelo_keywords_downloader.RAW_JSONL_NAME,
        pomelo_keywords_downloader.RUN_META_NAME,
    }


def test_wheat_export_writes_raw_response_only(tmp_path: Path, monkeypatch) -> None:
    workbook_path = tmp_path / "asins.xlsx"
    _write_step0(workbook_path)
    curl_path = tmp_path / "request.txt"
    curl_path.write_text("curl https://example.test --data-raw '{}'", encoding="utf-8")
    output = tmp_path / "seller-output"
    request = wheat_downloader.CurlRequest(
        "https://example.test",
        "POST",
        {},
        {"market": 1, "asins": ["B000000000"], "page": 1, "size": 100},
    )
    response = {"data": {"items": [{"keywords": "phone case", "opaque": 7}], "total": 1}}
    monkeypatch.setattr(wheat_downloader, "parse_curl_file", lambda _path: request)
    monkeypatch.setattr(
        wheat_downloader,
        "fetch_wheat_asin_page",
        lambda *_args, **_kwargs: response,
    )

    raw_path, meta_path, count = wheat_downloader.fetch_from_curl_and_asins(
        curl_path,
        workbook_path,
        output_dir=output,
        delay=0,
        country="US",
    )

    record = json.loads(raw_path.read_text(encoding="utf-8").strip())
    assert record["response"] == response
    assert count == 1
    assert {path.name for path in output.iterdir()} == {raw_path.name, meta_path.name}


def test_wheat_stops_after_saved_page_and_resumes(tmp_path: Path, monkeypatch) -> None:
    workbook_path = tmp_path / "asins.xlsx"
    _write_step0(workbook_path)
    curl_path = tmp_path / "request.txt"
    curl_path.write_text("curl https://example.test --data-raw '{}'", encoding="utf-8")
    output = tmp_path / "seller-resume"
    request = wheat_downloader.CurlRequest(
        "https://example.test",
        "POST",
        {},
        {"market": 1, "asins": ["B000000000"], "page": 1, "size": 1},
    )
    monkeypatch.setattr(wheat_downloader, "parse_curl_file", lambda _path: request)
    monkeypatch.setattr(
        wheat_downloader,
        "fetch_wheat_asin_page",
        lambda _request, _body, page, **_kwargs: {
            "data": {"items": [{"keywords": f"page-{page}"}], "total": 3}
        },
    )
    stop_checks = 0

    def stop_after_first_page() -> bool:
        nonlocal stop_checks
        stop_checks += 1
        return stop_checks >= 2

    raw_path, _meta_path, count = wheat_downloader.fetch_from_curl_and_asins(
        curl_path,
        workbook_path,
        output_dir=output,
        delay=0,
        country="US",
        stop_requested=stop_after_first_page,
    )
    assert count == 1
    assert len(raw_path.read_text(encoding="utf-8").splitlines()) == 1

    raw_path, _meta_path, count = wheat_downloader.fetch_from_curl_and_asins(
        curl_path,
        workbook_path,
        output_dir=output,
        delay=0,
        country="US",
        resume=True,
        stop_requested=lambda: False,
    )
    records = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines()]
    assert count == 3
    assert [record["page"] for record in records] == [1, 2, 3]
    assert records[-1]["batchComplete"] is True


def test_worker_api_exposes_three_download_steps(tmp_path: Path) -> None:
    secret = "test-session"
    server = create_server("127.0.0.1", 0, session_secret=secret)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/workspace",
            headers={"X-Data-Automation-Session": secret},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["mode"] == "local-only"
        assert [step["id"] for step in payload["steps"]] == ["step1", "step2", "step9"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_new_task_is_created_under_user_selected_parent(tmp_path: Path) -> None:
    secret = "test-session"
    server = create_server("127.0.0.1", 0, session_secret=secret)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps({"taskName": "phone_case_us", "parentDir": str(tmp_path)}).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/task/create",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Data-Automation-Session": secret,
            },
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        task_dir = Path(payload["currentTask"])
        assert task_dir.parent == tmp_path.resolve()
        assert task_dir.name.endswith("_phone_case_us")
        assert (task_dir / "Step0_ASIN_Input" / "Step0_ASIN_Input.xlsx").is_file()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_user_selected_writable_mapped_drive_is_allowed(tmp_path: Path) -> None:
    selected_parent = tmp_path / "mapped-drive-folder"
    selected_parent.mkdir()

    result = validate_task_directory(
        selected_parent,
        drive_type="remote",
        sync_roots=[],
        writable=True,
    )

    assert result == selected_parent.resolve()
