# 資料自動化工具

在 Windows 本機執行的資料下載工具，支援柚子資料、麥子拓展資料和柚子關鍵詞下載。

## 下載安裝

前往 [最新版本下載頁](https://github.com/nope-cypto/DataAutomationTool/releases/latest)，下載 `DataAutomationTool-Setup-<版本>-x64.exe` 後安裝。

- 適用平台：Windows x64；請預先安裝 Google Chrome。
- 直接使用安裝包不需要安裝 Python 或 Node.js。
- 下載頁提供 SHA-256 校驗檔案、免責聲明及授權條款。目前 v1.1.5 安裝包未附程式碼簽章，Windows 可能顯示未知發布者提示；請核對來源及校驗值，不要關閉系統安全防護。

## 使用前請閱讀

**本專案是獨立的第三方工具，與所涉及的平台不存在官方隸屬、授權或背書關係。只能在獲得相應權限並遵守適用法律及平台規則的前提下使用；開源許可不代表取得第三方資料或介面的使用權。**

**軟體按現狀提供，不保證持續可用、資料準確完整或帳號不受限制。在適用法律允許的範圍內，作者和貢獻者不提供擔保，並依 MIT 授權條款限制責任；法律不得排除或限制的責任不受影響。**

完整內容見 [免責聲明](DISCLAIMER.md) 和 [安全說明](SECURITY.md)。cURL 可能包含 Cookie 或存取權杖，請勿分享或上傳。

## 使用步驟

| 步驟 | 操作 | 結果 |
| --- | --- | --- |
| Step 0 | 輸入任務名，選擇儲存位置 | 建立任務目錄與 ASIN 輸入表 |
| Step 1 | 選擇國家並匯入 ASIN 的 CSV/XLSX | 下載柚子資料 XLSX 和結果清單 |
| Step 2 | 提供 ASIN 輸入表及已授權請求的 cURL | 儲存麥子拓展原始回應 JSONL |
| Step 3 | 提供關鍵詞 TXT/CSV/XLSX 及已授權請求的 cURL | 儲存柚子關鍵詞原始回應 JSONL |

任務輸出儲存在所選目錄中。請先用少量資料驗證結果，並備份重要檔案。

## 開發與回饋

原始碼執行、測試和 Windows 打包步驟見 [貢獻指南](CONTRIBUTING.md)。普通問題可提交 [問題回報](https://github.com/nope-cypto/DataAutomationTool/issues)，請先移除憑據和業務資料；漏洞報告請按 [安全說明](SECURITY.md) 操作。

本專案採用 [MIT 授權條款](LICENSE)，另提供 [繁體中文參考譯文](LICENSE.zh-TW.md)。
