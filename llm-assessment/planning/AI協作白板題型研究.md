# AI 協作白板題：研究與本機整合提案

查核日期：2026-10-13。這是研究提案，尚未實作新題型、未下載模型，也未驗證 iPad 實機或手寫辨識準確度。

## 可參考的設計

- Maastricht University 的「An AI Tutor System with a Virtual Whiteboard for Statistics Learning」（EDUCON 2026）結合對話與白板，允許書寫、圖形及標註，AI 以文字和圖形回應。其原型使用 GPT4.1；可借用互動形式，再另做本機模型實作。研究原型的效果不直接等同我們的 LLM 教材評量效果。
  https://cris.maastrichtuniversity.nl/en/publications/an-ai-tutor-system-with-a-virtual-whiteboard-for-statistics-learn/
- SocraticAI（2025）研究有結構的電腦科學學習對話與反思要求，適合借鑑「先追問理由，再給分層提示」的流程。
  https://arxiv.org/abs/2512.03501
- Excalidraw 是 MIT 授權的白板，可嵌入應用程式，支援圖形、箭頭與自由筆畫。嵌入元件本身不包含完整多人協作後端；本題型的學生與 AI 互動仍需自行串接。
  https://github.com/excalidraw/excalidraw
  https://docs.excalidraw.com/docs/@excalidraw/excalidraw/faq

## 建議題型

統一新增 `ai_collab_canvas` 題型，以下情境仍只檢測第一／二章概念，不以複雜手算為主：

1. **畫圖解釋與追問**：畫 encoder-decoder 資料流，標示 Q／K／V 來源與注意力可見範圍。AI 追問「這個箭頭傳的是什麼？」「是否能看到未來標籤？」學生修改並解釋。評分關係與機制，不評畫圖美觀。
2. **圈出程式問題**：在已給定的 MLM、next-token 或 RNN 小程式上圈選問題行，手寫修正，畫資料或狀態流。AI 詢問失敗原因、邊界與驗證案例；保留實作題的後端測試作驗證依據。
3. **與 AI 核對一項建議**：題目提供待核對的建議，例如「把前一步生成 token 改成測試集真實 token，生成就會更好」。學生接受、拒絕或修正，指出 teacher forcing／生成条件差別並提出驗證方式。不可把 AI 的答案當標準答案。
4. **共同設計下一步實驗**：手畫基準、修改項、控制變因、指標與預算的對照表。AI 追問混淆因素，學生改進。可延伸 Chinchilla 配置或 Mamba／Transformer 公平比較，使用來源資料解讀而非要求計算比值。
5. **反向教 AI**：學生畫因果遮罩或架構圖並解釋，AI 作為提問者詢問反例；最後換一個未討論的小情境，由學生獨立作答，以區分協作表現與遷移證據。

## 本地模型分工

已讀取本機 Ollama：有 `gpt-oss:20b` 與 `gemma4:12b-it-q4_K_M`；後者回報 `vision` 能力。顯示卡為 RTX 5070 Ti Laptop GPU，約 12GB 顯示記憶體。

- `gpt-oss:20b`：官方文件明確列為文字輸入／輸出，不支援圖像。用於追問、核對概念與依規準產生評分草稿。
- 已安裝的 Gemma 4：先作為白板視覺辨識候選，提取文字、節點、箭頭、圈選位置及看不清的區域。支援圖像不等於已驗證中文手寫辨識。
- 備選 `qwen3-vl:4b`／`qwen3-vl:8b`：官方提供視覺／OCR 能力，Ollama 有本機版本。模型下載檔約 3.3GB／6.1GB，這不是完整推論記憶體需求。只有在現有模型實測不足時，再比較此候選。

來源：
https://developers.openai.com/api/docs/models/gpt-oss-20b
https://ollama.com/library/gemma4
https://github.com/QwenLM/Qwen3-VL
https://ollama.com/library/qwen3-vl
https://docs.ollama.com/capabilities/vision

## iPad 操作與流程

網頁保留現有 98.css 外框，作答區使用適合觸控的大白板。支援筆、橡皮擦、復原、文字、框線、箭頭、圈選及縮放；手寫圖與可編輯文字都可用。文字欄可利用支援裝置的 Apple Pencil Scribble；自由筆畫則保留筆跡，由視覺模型判讀。Scribble 不等於白板圖形辨識。

Apple 說明：https://support.apple.com/en-euro/guide/ipad/ipad355ab2a7/27/ipados/27
WebKit Pointer Events：https://webkit.org/blog/10247/new-webkit-features-in-safari-13-1/

流程：

1. 先完成初稿，保存可比較的第一版。
2. 按「請 AI 檢查這一步」，送出白板畫面、結構資料與當前問題。
3. 本機視覺模型回傳讀到的內容；看不清時請學生確認，不將辨識失敗算成概念錯誤。
4. `gpt-oss:20b` 收到核准題目、對應章節資料、規準與已確認的白板內容，每輪提出一個聚焦問題或有限提示。
5. AI 可提出高亮、框選或箭頭建議，由白板顯示成獨立建議圖層；學生決定採用並說明。
6. 保存修改過程與最終答案，再做一個獨立的小情境檢查。

模型在主機執行，iPad 只作輸入與顯示。外網仍經 ngrok 連到網站，因此不是完全離線；模型推論不必使用雲端 API。iPad 的 localhost 指 iPad 自己，應使用網站的 ngrok HTTPS 網址或配置好的主機區網入口。

第一版採按鈕觸發、排隊推論與串流文字回覆。約 12GB VRAM 下不可假定兩個模型能同時完整駐留；應測試依序載入、上下文與影像大小，再決定是否提供停筆後自動檢查。不要承諾每個筆畫都能即時獲得模型回饋。

如果雙模型來回載入太慢，可讓同一個視覺模型完成看圖與簡短追問，只在階段結束時交給 gpt-oss 做深入核對與評分。兩種流程應以實際字跡辨識與互動延遲比較，再選正式配置。

## 後端與評量

題目設定、規準與詳解繼續存 SQLite。新增資料包括白板 scene／筆跡 JSON、畫面快照 BLOB、辨識與確認紀錄、對話、提示層級、學生／AI 分別提出的修改、模型版本及評分草稿。保留初稿與每輪版本，允許教師回放覆核。

AI 白板操作回傳受限制的結構命令，如標註、框選與箭頭，交由前端驗證並繪製；不把任意模型程式當成畫布腳本執行。圖表關係能以結構資料驗證時，優先與視覺判讀交叉核對。

評量分開呈現：初稿概念證據、核對 AI 建議的理由、修改後機制是否正確、驗證方案、最後獨立情境。提示與协作條件需標記，不把獲得提示後的正確答案直接當成獨立精熟，也不以對話次數推斷是否認真。

## 第一版範圍與驗收

先試三個情境：MLM 標籤圈選、encoder-decoder 箭頭解釋、公平評測實驗圖。先取得實際 iPad 的中英文字跡與簡圖樣本，比較本機辨識、回饋是否洩漏答案、延遲與教師分項一致性，再開放正式評量。這些需要後续實作與實機測試，尚不能宣稱已可用。
