# 四語介面與 Windows 98 音效

## 操作

底部工作列可選繁體中文、English、日本語、Español。切換即時套用，不重新載入作答頁，不改動未送出的表單、白板和答案。題幹、程式碼、教材原文、個人答案、模型回饋及已儲存名稱保留原文，避免影響題目與批改證據。介面日期以台北時區、所選語言格式顯示。

工作列喇叭按鈕切換靜音，旁邊小三角開啟音效設定。預設開啟、音量35%，可調0–100%。首次互動後才播放，頁面載入不自動播開機音。按鈕與選項使用start，視窗使用ding，一般訊息使用notify，操作錯誤使用chord，完成提示使用tada。開機音僅供主動試聽。輸入文字、背景自動保存、繪圖筆跡保持安靜。

登入後，語言、靜音及音量分別保存於後端users的ui_locale、ui_sounds、ui_volume欄位，獨立帳戶不互相覆寫。未登入使用瀏覽器本機偏好。偏好API具登入、CSRF及來源驗證。Web Audio GainNode調整音量，避免iOS不支援直接設定HTMLAudio音量的限制。

## 音效來源

所有音效源自Windows 98系統WAV典藏：https://lelegofrog.github.io/winwav98.html 。檔名及位元組數符合Microsoft舊KB Q188439光碟清單：https://ftp.zx.net.nz/pub/archive/ftp.microsoft.com/MISC/KB/en-us/188/439.HTM 。來源、檔案雜湊與格式記錄於static/vendor/win98-sounds/manifest.json及PROVENANCE.md。start原始ADPCM保留，另解碼為PCM供Safari等瀏覽器播放；音效內容未改編。

音效權利屬Microsoft及原始貢獻者；音效不是開源授權的一部分。正式對外散布時需確認音效再散布授權。

## 驗證範圍

隔離QA網站驗證四種介面語言、語言往返切換、原始答案與白板標籤不消失、音效載入播放、靜音、試聽及帳戶隔離。自動測試驗證偏好輸入、CSRF、所有播放WAV為PCM、資源可存取且符合雜湊。尚需實體iPad Safari確認喇叭輸出、靜音開關與實際聽感；瀏覽器自動播放限制可能要求再按一次試聽。
