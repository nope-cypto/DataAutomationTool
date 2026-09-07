# 貢獻指南

感謝參與資料自動化工具。提交改動前請確保：

1. 功能仍只在本機執行，不新增帳號系統、遙測或專案自有云端依賴。
2. 下載步驟只儲存第三方服務返回的原始檔案；不要加入跨批次彙總、合併去重、特徵計算或分析報表。
3. 不提交 Cookie、cURL、真實 ASIN/關鍵詞資料、任務輸出或瀏覽器使用者目錄。
4. 新增網路請求時保留合理超時、停止與斷點續抓能力，並避免在日誌中輸出憑據。
5. 提交前執行 Python 測試、開源邊界測試和前端構建。

```powershell
cd DataAutomationTool-source
python -m pytest
cd web_workbench\frontend
npm test
npm run build
```

問題回報請提供可復現步驟、系統版本和已經脫敏的錯誤資訊，不要附上完整 cURL 或請求頭。

## 從原始碼執行

需要 Python 3.11–3.13、Node.js 22+、npm 和 Google Chrome。在 Windows PowerShell 中執行：

```powershell
cd DataAutomationTool-source
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
cd web_workbench\frontend
npm ci
npm run dev
```

另開一個 PowerShell，在同一虛擬環境與前端目錄中執行 `npm run electron:dev`。

## 構建 Windows 安裝包

在 Windows 上安裝 Python 3.12 x64、Node.js 22+，並在前端目錄執行：

```powershell
npm run dist:win
```

安裝包輸出到前端目錄的 `release/`，構建日誌位於 `.build-logs/`。這些本地產物不提交到原始碼倉庫。發布時同時提供 `LICENSE`、`DISCLAIMER.md` 和 SHA-256 校驗檔案。
