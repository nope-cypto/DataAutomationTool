# 资料自动化工具

这是一个在 Windows 本机运行的资料下载工具，界面按 Step 0 至 Step 3 组织：

| 步骤 | 功能 | 主要输入 | 输出 |
| --- | --- | --- | --- |
| Step 0 | 建立项目 | 任务名称 + 用户选择保存位置 | 任务目录 + `Step0_ASIN_Input.xlsx` |
| Step 1 | 柚子数据下载 | 国家 + ASIN 的 CSV/XLSX | 网页下载的 XLSX 和结果清单 |
| Step 2 | 麦子拓展数据下载 | ASIN 输入表 + cURL | 完整响应 JSONL |
| Step 3 | 柚子关键词下载 | 关键词 TXT/CSV/XLSX + cURL | 完整响应 JSONL |

## 使用方式

1. 在 Step 0 输入任务名，点击“新建任务并选择位置”，由用户自行选择保存目录。
2. 在同一个 Step 0 区块打开 ASIN 输入表，并按界面示例填写。
3. 依序执行 Step 1、Step 2 和 Step 3，运行状态统一显示在页面顶部。

> cURL 通常包含 Cookie 或授权资讯。请勿分享或提交到 Git，并仅下载你有权访问的数据。

## 从源码运行

需要 Python 3.11–3.13、Node.js 22+、npm 和 Google Chrome。

```powershell
cd DataAutomationTool-source
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

cd web_workbench\frontend
npm ci
npm run dev
```

另开一个 PowerShell，在相同虚拟环境中运行桌面程序：

```powershell
cd DataAutomationTool-source\web_workbench\frontend
npm run electron:dev
```

## 测试

```powershell
cd DataAutomationTool-source
python -m pytest

cd web_workbench\frontend
npm ci
npm test
npm run build
```

## 构建 Windows 安装包

打包固定使用 Python 3.12 x64。在 Windows PowerShell 中执行：

```powershell
cd DataAutomationTool-source\web_workbench\frontend
npm run dist:win
```

构建日志保存在 `web_workbench/frontend/.build-logs/`，完成后安装包位于 `web_workbench/frontend/release/`，档名格式为 `DataAutomationTool-Setup-<version>-x64.exe`。

## 技术结构

- Electron：本地窗口、档案选择、调试 Chrome 与 Worker 生命周期。
- React/Vite：Step 0–3 操作界面。
- Python Worker：仅监听 `127.0.0.1:18137`，使用每次启动随机产生的会话密钥。
- Playwright：通过 Chrome DevTools Protocol 连接用户启动的调试 Chrome。

源码采用 [MIT License](LICENSE)。请同时阅读 [贡献指南](CONTRIBUTING.md) 和 [安全说明](SECURITY.md)。
