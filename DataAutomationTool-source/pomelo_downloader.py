"""Single-ASIN Pomelo keyword reverse-lookup collection."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import browser as browser_helpers
from web_workbench.worker.action_errors import SafeActionError
from pomelo_download_diagnostics import DownloadStageRecorder

SITE_NAMES = {
    "US": "美国站",
    "UK": "英国站",
    "DE": "德国站",
    "FR": "法国站",
    "IT": "意大利站",
    "ES": "西班牙站",
    "CA": "加拿大站",
    "JP": "日本站",
    "MX": "墨西哥站",
}

ASIN_URL = "https://www.xydc.com/asin"
LogCallback = Callable[[str], None]


def normalize_country(country: str) -> str:
    """Normalize country code for Pomelo site selection."""
    return country.strip().upper()


def is_supported_country(country: str) -> bool:
    """Return whether Pomelo site selection supports this country code."""
    return normalize_country(country) in SITE_NAMES


def log_message(message: str, callback: LogCallback | None = None) -> None:
    if callback:
        callback(message)
    else:
        print(message)


def safe_visible(locator_or_element: Any) -> bool:
    try:
        return locator_or_element.is_visible()
    except Exception:
        return False


def click_first_visible(locator: Any) -> bool:
    for index in range(locator.count()):
        element = locator.nth(index)
        if safe_visible(element):
            try:
                element.scroll_into_view_if_needed()
            except Exception:
                pass
            element.click()
            return True
    return False


def close_promo(page: Any) -> None:
    """Best-effort close for Pomelo promo/login overlays."""
    for selector in ["[class*=close]", ".el-dialog__headerbtn", "img[class*=close]"]:
        locator = page.locator(selector)
        for index in range(min(locator.count(), 5)):
            element = locator.nth(index)
            try:
                if element.is_visible():
                    element.click()
                    time.sleep(0.4)
            except Exception:
                pass
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    time.sleep(0.6)


def open_tool(context: Any, url: str = ASIN_URL, settle_ms: int = 5000) -> Any:
    """Open or reuse a Pomelo tab and navigate to the ASIN reverse-lookup tool."""
    page = None
    for existing in context.pages:
        try:
            if "xydc" in existing.url or "pomelo" in existing.url:
                page = existing
                break
        except Exception:
            pass
    if page is None:
        page = context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception:
        log_message("柚子页面正在继续加载。")
    page.wait_for_timeout(settle_ms)
    close_promo(page)
    return page


def select_site(page: Any, country: str, callback: LogCallback | None = None) -> None:
    """Select Pomelo marketplace site. If already selected, continue."""
    normalized = normalize_country(country)
    if not is_supported_country(normalized):
        raise RuntimeError(f"不支持的国家：{country}")
    site_name = SITE_NAMES[normalized]
    site_input = page.get_by_placeholder("请选择站点").first
    if site_input.count() == 0:
        if page.get_by_text(site_name, exact=True).count():
            log_message("站点已确认，继续采集。", callback)
            return
        site_input = page.locator(".el-select input, input").first
    try:
        site_input.click()
        time.sleep(1)
        option = page.get_by_text(site_name, exact=True)
        if click_first_visible(option):
            log_message("站点已选择。", callback)
        else:
            log_message("站点选择未变化，继续检查当前页面。", callback)
    except Exception:
        log_message("站点选择未确认，继续检查当前页面。", callback)
    time.sleep(0.8)


def fill_asin(page: Any, asin: str, callback: LogCallback | None = None) -> None:
    asin_input = page.get_by_placeholder("请输入亚马逊「子ASIN」").first
    if asin_input.count() == 0:
        raise SafeActionError("pomelo_login_required")
    asin_input.click()
    asin_input.fill(asin.strip().upper())
    time.sleep(0.4)
    log_message("已填写当前 ASIN。", callback)


def click_reverse(page: Any, callback: LogCallback | None = None) -> None:
    button = page.locator("button:has-text('反查关键词'), [class*=btn]:has-text('反查关键词')")
    if not click_first_visible(button):
        if not click_first_visible(page.get_by_text("反查关键词", exact=True)):
            raise SafeActionError("pomelo_page_render_failed")
    log_message("已点「反查关键词」，等待结果…", callback)


def wait_keyword_table(page: Any, timeout: int = 40) -> bool:
    end_time = time.time() + timeout
    while time.time() < end_time:
        if page.locator(".el-table__row, table tbody tr").count() > 10:
            return True
        time.sleep(1)
    return False


def set_time_range(page: Any, label: str = "3个月", callback: LogCallback | None = None) -> None:
    locator = page.get_by_text(label, exact=True)
    clicked = False
    for index in range(locator.count()):
        element = locator.nth(index)
        if safe_visible(element):
            try:
                element.scroll_into_view_if_needed()
                time.sleep(0.3)
                element.click()
                clicked = True
                break
            except Exception:
                pass
    if clicked:
        log_message(f"时间范围设为：{label}", callback)
    else:
        log_message(f"未点到时间范围 {label}，继续尝试下载。", callback)
    time.sleep(1.5)


def block_text(element: Any) -> str:
    """Read ancestor text to identify which visual block a download button belongs to."""
    try:
        return element.evaluate(
            "e => { let n=e; for(let k=0;k<6;k++){ if(n.parentElement) n=n.parentElement; } return (n.innerText||''); }"
        )
    except Exception:
        return ""


def has_visible_login_challenge(page: Any) -> bool:
    def marker_visible(marker: str) -> bool:
        locator = page.get_by_text(marker, exact=True)
        return any(safe_visible(locator.nth(index)) for index in range(locator.count()))

    return (
        marker_visible("\u5207\u6362\u5230\u77ed\u4fe1\u767b\u5f55")
        or marker_visible("\u626b\u7801\u767b\u5f55")
    ) and (
        marker_visible("\u9690\u79c1\u534f\u8bae") or marker_visible("\u670d\u52a1\u6761\u6b3e")
    )


def download_keyword_list(
    page: Any,
    out_path: str | Path,
    timeout: int = 60000,
    *,
    diagnostics: DownloadStageRecorder | None = None,
) -> tuple[Path, str]:
    """Download the keyword-list block's xlsx and save it to ``out_path``."""
    output = Path(out_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    downloads = page.locator("span.download")
    target = None
    for index in range(downloads.count()):
        element = downloads.nth(index)
        if safe_visible(element) and "关键词列表" in block_text(element):
            target = element
            break
    if target is None:
        visible = [downloads.nth(index) for index in range(downloads.count()) if safe_visible(downloads.nth(index))]
        target = visible[-1] if visible else None
    if target is None:
        if diagnostics is not None:
            diagnostics.mark("download_control_missing")
        raise SafeActionError("pomelo_download_failed")
    close_promo(page)
    target.scroll_into_view_if_needed()
    time.sleep(0.5)
    try:
        if diagnostics is not None:
            diagnostics.mark("download_wait_started")
        with page.expect_download(timeout=timeout) as download_info:
            target.click()
            time.sleep(1.2)
            if has_visible_login_challenge(page):
                raise SafeActionError("pomelo_login_required")
            for option in ["确定", "下载", "导出", "全部"]:
                button = page.get_by_role("button", name=option)
                if button.count() and safe_visible(button.first):
                    try:
                        button.first.click()
                    except Exception:
                        pass
                    break
        if diagnostics is not None:
            diagnostics.mark("download_event_received")
        download = download_info.value
        if diagnostics is not None:
            diagnostics.mark("download_save_started")
        download.save_as(str(output))
        if diagnostics is not None:
            diagnostics.mark("download_save_completed")
    except SafeActionError:
        raise
    except Exception as exc:
        raise SafeActionError("pomelo_download_failed") from exc
    return output, download.suggested_filename


def check_login(cdp_url: str = "http://localhost:9222") -> bool:
    """Lightweight login check used by the UI."""
    pw, _browser, context = browser_helpers.attach(cdp_url)
    try:
        page = open_tool(context, settle_ms=3000)
        return page.get_by_placeholder("请输入亚马逊「子ASIN」").first.count() > 0
    finally:
        browser_helpers.detach(pw)


def collect_keywords_with_context(
    context: Any,
    country: str,
    asin: str,
    out_path: str | Path,
    callback: LogCallback | None = None,
    *,
    download_diagnostics: DownloadStageRecorder | None = None,
) -> Path:
    """Collect one ASIN's keyword reverse lookup xlsx through an existing browser context."""
    normalized_country = normalize_country(country)
    normalized_asin = asin.strip().upper()
    if not is_supported_country(normalized_country):
        raise RuntimeError(f"不支持的国家：{country}")
    log_message("① 打开柚子数据工具页…", callback)
    try:
        page = open_tool(context)
    except Exception as exc:
        raise SafeActionError("pomelo_page_render_failed") from exc
    log_message("② 选站点 + 填 ASIN + 反查…", callback)
    select_site(page, normalized_country, callback)
    fill_asin(page, normalized_asin, callback)
    click_reverse(page, callback)
    if not wait_keyword_table(page):
        raise SafeActionError("pomelo_page_render_failed")
    row_count = page.locator(".el-table__row, table tbody tr").count()
    log_message(f"关键词列表已出现，共 {row_count} 行。", callback)
    log_message("③ 关键词列表时间范围设 3个月…", callback)
    set_time_range(page, "3个月", callback)
    log_message("④ 下载关键词反查结果…", callback)
    saved, suggested = download_keyword_list(
        page,
        out_path,
        diagnostics=download_diagnostics,
    )
    log_message("关键词反查文件已下载并保存。", callback)
    return saved


def collect_keywords(
    country: str,
    asin: str,
    out_path: str | Path,
    cdp_url: str = "http://localhost:9222",
    callback: LogCallback | None = None,
) -> Path:
    """Collect one ASIN's keyword reverse lookup xlsx through an existing Chrome session."""
    normalized_country = normalize_country(country)
    normalized_asin = asin.strip().upper()
    if not is_supported_country(normalized_country):
        raise RuntimeError(f"不支持的国家：{country}")
    pw, _browser, context = browser_helpers.attach(cdp_url)
    try:
        return collect_keywords_with_context(context, normalized_country, normalized_asin, out_path, callback)
    finally:
        browser_helpers.detach(pw)
