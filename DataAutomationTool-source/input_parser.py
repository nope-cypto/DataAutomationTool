"""Input parsing for pasted text, CSV, and Excel task lists."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

try:
    import openpyxl
except Exception:  # pragma: no cover - dependency is checked at runtime
    openpyxl = None

SUPPORTED_COUNTRIES = {"US", "UK", "DE", "FR", "IT", "ES", "CA", "JP", "MX"}
COUNTRY_HEADERS = {"country", "国家", "site", "站点", "marketplace", "国家站点"}
ASIN_HEADERS = {"asin", "ASIN", "子ASIN", "子asin", "目标ASIN", "目标asin"}
ASIN_RE = re.compile(r"^[A-Z0-9]{8,15}$")


@dataclass(frozen=True)
class AsinTask:
    country: str
    asin: str
    source: str = "manual"


@dataclass(frozen=True)
class ParsedTask:
    country: str
    asin: str
    status: str = "待运行"
    error: str = ""
    source: str = "manual"

    @property
    def task(self) -> AsinTask:
        return AsinTask(self.country, self.asin, self.source)


def normalize_country(country: object) -> str:
    return str(country or "").strip().upper()


def normalize_asin(asin: object) -> str:
    return str(asin or "").strip().upper()


def is_valid_asin(asin: str) -> bool:
    return bool(ASIN_RE.match(normalize_asin(asin)))


def split_task_line(line: str) -> tuple[str, str] | None:
    normalized = line.strip().replace("，", ",").replace("\t", " ")
    if not normalized:
        return None
    if "," in normalized:
        parts = [part.strip() for part in normalized.split(",") if part.strip()]
    else:
        parts = [part.strip() for part in normalized.split() if part.strip()]
    if len(parts) < 2:
        return None
    return parts[0], parts[1]


def finalize_tasks(raw_tasks: list[AsinTask]) -> list[ParsedTask]:
    """Normalize, validate, and mark duplicates while keeping row order."""
    seen: set[tuple[str, str]] = set()
    parsed: list[ParsedTask] = []
    for raw in raw_tasks:
        country = normalize_country(raw.country)
        asin = normalize_asin(raw.asin)
        if not country or not asin:
            parsed.append(ParsedTask(country, asin, "已跳过", "国家或 ASIN 为空", raw.source))
            continue
        if country not in SUPPORTED_COUNTRIES:
            parsed.append(ParsedTask(country, asin, "已跳过", "不支持的国家", raw.source))
            continue
        if not is_valid_asin(asin):
            parsed.append(ParsedTask(country, asin, "已跳过", "ASIN 格式错误", raw.source))
            continue
        key = (country, asin)
        if key in seen:
            parsed.append(ParsedTask(country, asin, "已跳过", "重复任务", raw.source))
            continue
        seen.add(key)
        parsed.append(ParsedTask(country, asin, "待运行", "", raw.source))
    return parsed


def parse_pasted_text(text: str) -> list[AsinTask]:
    """Parse pasted country/ASIN lines into raw tasks for backward compatibility."""
    tasks: list[AsinTask] = []
    for raw_line in text.splitlines():
        parts = split_task_line(raw_line)
        if parts:
            tasks.append(AsinTask(country=parts[0].upper(), asin=parts[1].upper(), source="manual"))
    return tasks


def parse_pasted_text_validated(text: str) -> list[ParsedTask]:
    return finalize_tasks(parse_pasted_text(text))


def _column_indexes(headers: list[object]) -> tuple[int, int]:
    normalized = [str(header or "").strip() for header in headers]
    country_index = -1
    asin_index = -1
    for index, header in enumerate(normalized):
        if header in COUNTRY_HEADERS or header.lower() in COUNTRY_HEADERS:
            country_index = index
        if header in ASIN_HEADERS or header.lower() in ASIN_HEADERS:
            asin_index = index
    if asin_index >= 0:
        return country_index, asin_index
    return 0, 1


def parse_csv_file(path: str | Path) -> list[ParsedTask]:
    file_path = Path(path)
    raw_rows: list[list[str]] = []
    with file_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        raw_rows = [row for row in reader if any(str(cell).strip() for cell in row)]
    if not raw_rows:
        return []
    country_index, asin_index = _column_indexes(list(raw_rows[0]))
    data_rows = raw_rows[1:] if _looks_like_header(raw_rows[0]) else raw_rows
    raw_tasks = [
        AsinTask(row[country_index] if country_index >= 0 else "", row[asin_index], source=str(file_path))
        for row in data_rows
        if len(row) > asin_index
    ]
    return finalize_tasks(raw_tasks)


def parse_excel_file(path: str | Path) -> list[ParsedTask]:
    if openpyxl is None:
        raise RuntimeError("缺少 openpyxl，无法导入 Excel。")
    file_path = Path(path)
    workbook = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        rows = [list(row) for row in sheet.iter_rows(values_only=True) if any(str(cell or "").strip() for cell in row)]
    finally:
        workbook.close()
    if not rows:
        return []
    country_index, asin_index = _column_indexes(rows[0])
    data_rows = rows[1:] if _looks_like_header(rows[0]) else rows
    raw_tasks = [
        AsinTask(row[country_index] if country_index >= 0 else "", row[asin_index], source=str(file_path))
        for row in data_rows
        if len(row) > asin_index
    ]
    return finalize_tasks(raw_tasks)


def parse_file(path: str | Path) -> list[ParsedTask]:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        return parse_csv_file(file_path)
    if suffix in {".xlsx", ".xlsm"}:
        return parse_excel_file(file_path)
    raise RuntimeError(f"不支持的导入文件类型：{suffix}")


def _looks_like_header(row: list[object]) -> bool:
    cells = {str(cell or "").strip() for cell in row}
    lower_cells = {cell.lower() for cell in cells}
    return bool((cells | lower_cells) & (COUNTRY_HEADERS | ASIN_HEADERS))
