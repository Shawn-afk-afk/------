# 知序 · LLM 理解與實作評量

獨立運作的教材評量網站，採用本機 SQLite、Ollama 與 WSL2。介面使用本機提供的 98.css。未來整合其他專案時，可沿用 HTTP API 與題庫 JSON 匯入／匯出。

## 啟動

在此資料夾開啟 PowerShell：

```powershell
.\scripts\Prepare-Runner.ps1
.\scripts\Prepare-Model.ps1
.\scripts\Start-App.ps1
```

開啟 http://127.0.0.1:8765，親自建立第一位管理者。沒有預設正式帳密。後台「設定」預設使用 `gpt-oss:20b`，推理程度為中，可調整低／中／高。需要先啟動 Ollama 本機服務；下載模型不等於已驗證推論。

## 使用順序

1. 在「題庫與覆核」檢查草稿、詳解、閱讀位置、原始論文與分項規準，確認後核准。
2. 建立組員帳戶；每人只會看到自己的評量及已發布報告。
3. 建立評量，選題、配分、指定組員與截止時間，決定是否允許練習及自動發布。
4. 作答提交後，後端依序執行批改工作；人工可調整分項、註記及發布。原始 AI 結果與調整紀錄保留。重新開放作答會產生新的作答版本。
5. 查看能力分項與改善建議。分析區分練習／正式評量及題型、難度與支援条件，不把作答紀錄直接解讀成學習動機。

## 題庫與詳解

目前原始題庫共 61 題，涵蓋第一章 1.1–1.5、第二章 2.1–2.6。最新版本為 31 題英文、30 題中文，15 題提供不需執行的程式閱讀材料；另外保留 5 題 Python 實作與 8 題研究／教學案例延伸。英文題允許中英文解釋，詳解仍以中文為主。已取消獨立手算題型，著重資料流、狀態、標籤、可見範圍與公平評測。案例不是組員自己的實驗。

2026-10-13 的語言與邏輯修訂建立 41 個新草稿版本，不覆寫原題或已分配快照。請先覆核並核准新版，再加入新評量；題庫可依語言篩選。`backend/revise_bank.py` 可重複執行，不重複建立版本，也不改動使用者後續編輯的版本。

新增選擇與互動題預設各 12 分：後端核對選项／操作結果占 6 分，AI 評分理由占 6 分。複選的操作分需全對，漏選、多選或重複選項不得操作分；人工仍可依分項規準調整。正解只存於私有答案欄位，不傳給組員。

每題管理者詳解包含參考答案、解題步驟、常見錯誤、實務用途與教材章節／頁碼／搜尋關鍵字。實作提供參考程式，可在後台執行公開與隱藏測試。公開論文延伸題會標明來源與可接受的替代方案；參考答案是原創教學說明，仍需人工覆核。組員介面不提供詳解、私有規準或隱藏測試答案。

題目版本、教材來源文件、作答、評分及人工紀錄儲存在 `backend/assessment.sqlite3`。題目修改產生新版本，已分配評量保留當時核准內容。

## 批改與程式執行

客觀互動以規則核對；Python 由主機 WSL2 重新執行公開及隱藏測試；其他分項由本機 AI 依核准規準給 0–3 等級、引用作答證據與回饋，再換算指定配分。無效 JSON、證據不符或模型失敗會保留待批改，不產生假的完成分數。實作預設需要人工覆核後發布。

WSL2 Ubuntu 使用 bubblewrap 與 prlimit：隔離網路、限制 CPU／記憶體／輸出及程序數。學生程式不會取得隱藏測試的預期答案。沒有 Docker 或 GPU 需求。學生瀏覽器的 Pyodide 只供公開測試練習，第一次載入需要網路；正式分數不信任瀏覽器傳回的結果。此題庫程式以 Python 標準函式庫為主。

## ngrok

先建立本機管理者，再安裝 [ngrok 官方 Windows 版本](https://ngrok.com/download/windows)，依官方說明設定自己的免費帳戶。腳本讀取既有設定，請勿把 token 放入原始碼。

```powershell
.\scripts\Start-Tunnel.ps1 -NgrokPath 'C:\工具\ngrok.exe'
```

此腳本重新啟動網站為 HTTPS cookie 模式，再建立通道。網址可在本機 http://127.0.0.1:4040/api/tunnels 查看。免費方案有額度限制，請從自己的 ngrok 儀表板確認。主機需保持開機；Ollama 不對外開放。

```powershell
.\scripts\Backup-Database.ps1
.\scripts\Stop-App.ps1
```

備份包含完整資料庫。停止腳本只停止本網站與其通道，不停止共用 Ollama 或 WSL2。

## 驗證

```powershell
$env:ASSESSMENT_TEST_WSL='1'
python -m unittest discover -s tests -p 'test_*.py' -v
python tests/smoke_ai.py
```

自動測試使用隔離資料庫，涵蓋權限、題目版本、分配、提交、AI 證據檢查、人工覆核、重新作答、全部參考程式與沙箱限制。`smoke_ai.py` 是實際本機模型測試，不寫入正式成績；單次測試不能代表所有題目的批改準確度。

## iPad AI 協作白板測試

新增三題第一／二章概念延伸白板草稿 `LAB-AI-001`～`003`，總題數 64（英文 32、中文 32）。管理者先查看詳解與来源、核准再分配。iPad 透過瀏覽器輸入，主機以 Gemma 視覺模型辨識並追問，以 gpt-oss:20b 批改；白板題必須人工覆核發布。

完整操作、測試邊界與 M5 Max 遷移事項：[iPad 白板測試指南](planning/iPad白板測試指南.md)。正式網站可由 `scripts/Start-Tunnel.ps1` 建立 ngrok HTTPS 通道；不要求測試者與主機在同一 Wi-Fi。


## ExamCrafter 與模型轉接槽

已整合 Shawn-afk-afk/------ 的教材解析、考卷生成、英文圖片題與 Word 匯出引擎，入口為管理側欄「教材出題工作室」。出題預設 Gemma 4 12B，批改仍為 gpt-oss:20b。新增「模型轉接槽」可為出題、白板與批改分別登錄及切換 Ollama 或本機相容 API 來源，保留之後 LoRA 版本的接口。

[操作與 LoRA 接入指南](planning/ExamCrafter整合與模型轉接指南.md)。新環境安裝 `requirements-exam.txt`；原文、快照、模型來源、審題修改歷程與 Word 檔均保存於 SQLite。

## 四語介面與原版系統音效

工作列支援繁體中文、英文、日文、西班牙文；介面切換保留題目、答案與白板內容。Windows 98 WAV提供按鈕、視窗、通知、錯誤與完成回饋，具靜音、音量和開機音試聽；帳戶偏好存入SQLite。[操作與來源說明](planning/介面語言與Windows98音效.md)。

## 本機模型磁碟庫與 OmniEdu LoRA

模型轉接槽支援 Ollama、LM Studio、本機相容 API及原生OmniEdu LoRA。可查詢Hugging Face公開GGUF、下載到主機、分塊上傳權重並核對後切換；沒有雲端推論或付費服務。[操作、安裝與實測限制](planning/本機模型下載與OmniEdu接入.md)。

從GitHub新安裝前，請取得ZJU教材來源（`git clone https://github.com/ZJU-LLMs/Foundations-of-LLMs.git`，放在本整合目錄旁，或設定`ASSESSMENT_SOURCE_DIR`指向該目錄），安裝`requirements-exam.txt`後執行`backend/build_draft_bank.py`。教材、帳號、答案、模型權重、虛擬環境及本機音效原檔不隨程式碼提交；原版Windows98音效來源與雜湊保留於`static/vendor/win98-sounds/PROVENANCE.md`與`manifest.json`，需自行依原授權準備。

## 教材優先與自動 Dense RAG

工作室依序為教材輸入、組成考卷、審題匯出。儲存教材會自動建立本機EmbeddingGemma向量索引；可預覽原文、頁碼與向量相似度，出題檢索原文保留於工作快照。[操作與實作說明](planning/教材工作室DenseRAG.md)。先下載`ollama pull embeddinggemma`，再啟動網站；沒有向量資料庫額外port或雲端推論。
