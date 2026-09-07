from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SafeErrorDefinition:
    message: str
    retryable: bool = False


SAFE_ACTION_ERRORS = {
    "pomelo_driver_package_missing": SafeErrorDefinition("Playwright 驱动不完整，请重新构建或安装。"),
    "pomelo_playwright_start_failed": SafeErrorDefinition("Playwright 启动失败，请重启软件。", True),
    "pomelo_cdp_connect_failed": SafeErrorDefinition("未连接到调试 Chrome，请先启动调试 Chrome。", True),
    "pomelo_browser_context_missing": SafeErrorDefinition("调试 Chrome 尚未就绪，请关闭后重新启动。", True),
    "pomelo_login_required": SafeErrorDefinition("请在调试 Chrome 中登录柚子后重试。"),
    "pomelo_page_render_failed": SafeErrorDefinition("柚子页面未显示下载结果，请检查登录状态。", True),
    "pomelo_download_failed": SafeErrorDefinition("柚子文件下载失败，请保持调试 Chrome 打开。", True),
    "pomelo_workbook_invalid": SafeErrorDefinition("下载的 Excel 无有效数据，请重试。", True),
    "pomelo_collection_failed": SafeErrorDefinition("柚子数据下载未完成，请检查页面和网络。", True),
    "pomelo_import_parse_failed": SafeErrorDefinition("任务文件解析失败，请检查国家和 ASIN 列。"),
    "wheat_connect_failed": SafeErrorDefinition("麦子连通测试失败，请检查 cURL、ASIN 输入和网络。", True),
    "wheat_download_failed": SafeErrorDefinition("麦子拓展数据下载失败，已保存的原始分页可用于继续下载。", True),
    "pomelo_keywords_connect_failed": SafeErrorDefinition("柚子关键词连通测试失败，请检查 cURL 和关键词输入。", True),
    "pomelo_keywords_test_failed": SafeErrorDefinition("柚子关键词两批测试失败，请检查请求。", True),
    "pomelo_keywords_download_failed": SafeErrorDefinition("柚子关键词下载失败，已保存的原始分页可用于继续下载。", True),
    "step0_market_invalid": SafeErrorDefinition("ASIN 输入表的国家无效，且所有 ASIN 必须属于同一站点。"),
    "step0_market_changed": SafeErrorDefinition("ASIN 输入表的国家已改变，不能继续原断点。"),
}


class SafeActionError(RuntimeError):
    def __init__(self, code: str) -> None:
        definition = SAFE_ACTION_ERRORS.get(code)
        if definition is None:
            raise ValueError("unsupported safe action error")
        self.code = code
        self.safe_message = definition.message
        self.retryable = definition.retryable
        self.diagnostic_id = None
        super().__init__(definition.message)


LOCAL_ACTION_FALLBACKS = {
    "pomelo_parse": "pomelo_import_parse_failed",
    "pomelo_download": "pomelo_collection_failed",
    "wheat_connect": "wheat_connect_failed",
    "wheat_download": "wheat_download_failed",
    "pomelo_keywords_connect": "pomelo_keywords_connect_failed",
    "pomelo_keywords_test_two_batches": "pomelo_keywords_test_failed",
    "pomelo_keywords_download": "pomelo_keywords_download_failed",
}


def safe_local_action_failure(action_id: str, exc: Exception) -> SafeActionError:
    if isinstance(exc, SafeActionError):
        return exc
    return SafeActionError(LOCAL_ACTION_FALLBACKS.get(action_id, "pomelo_collection_failed"))
