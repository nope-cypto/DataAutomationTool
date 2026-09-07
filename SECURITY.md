# 安全說明

## 敏感資料

從瀏覽器複製的 cURL 很可能包含 Cookie、Authorization header 或其他短期憑據。程式將它儲存到目前任務目錄的 `Step2_Request.txt` 或 `Step3_Request.txt`。執行任務時會向對應第三方服務傳送必要的認證資訊；任何能讀取任務目錄的人都可能取得其中的憑據，本地同步或備份軟體也可能複製這些檔案。

- 不要將任務目錄、cURL、瀏覽器除錯目錄或原始輸出提交到 GitHub。
- 使用完成後可刪除請求檔案內容，並在第三方網站退出會話或撤銷相應憑據。
- 分享日誌或截圖前，應移除請求頭、Cookie、帳號資訊及業務資料。

## 報告漏洞

請透過 [GitHub 私密安全報告](https://github.com/nope-cypto/DataAutomationTool/security/advisories/new) 提交漏洞，不要在公開問題回報中附上可用憑據或真實使用者資料。報告應包含受影響版本、復現方式、影響和建議修復方向。

本專案沒有後台服務，也不會透過聊天、郵件或問題回報 索取你的 cURL、Cookie 或帳號密碼。
