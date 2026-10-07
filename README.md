# ExamCrafter AI (智慧考卷生成系統)

> 🎓 **本地離線優先 (Offline-First) · 國中英語科與全科客製化段考/會考出卷平台**  
> 結合本地大語言模型 (`gemma4:e4b`)、科目感知 RAG 知識庫、300 DPI 圖表引擎與成套 Word 專業考卷匯出。

---

## 🌟 核心特色功能

### 1. 雙軌出題架構 (Dual-Track Generation)
* **方案 A：預設常規模板自訂**
  * 支援靈活配置題型配分、大題自訂（單選題、閱讀題組、字彙選擇等）。
  * 支援設定閱讀題組文章篇數與每篇子題數量（如 8 篇 × 3 題）。
* **方案 B：舊考卷骨架克隆 (Skeleton Cloner)**
  * 上傳既有段考或會考 PDF/Word 考卷，三段式容錯管線自動解析原有試卷之題型分布、配分架構，原樣套用並注入新教材知識點。

### 2. 動態教材匯入與知識庫 (Subject-Aware RAG)
* **自主載入教材**：不限制單元數與檔案大小，支援 PDF、Word (`.docx`)、純文字 (`.txt`) 及直接貼上課文段落。
* **智慧科目切片**：自動提取單元標題、單字庫 (`Words for Production`)、文法句型與課文。
* **靈活單元管理**：支援單元動態勾選、覆蓋更新防重複、以及**個別單元垃圾桶刪除 (`🗑️`)**。
* **健壯容錯門禁**：支援多重編碼嘗試 (UTF-8, Big5, GB18030)、純圖片掃描檔攔截警示不卡死。

### 3. 假單字雙層防線門禁 (Word Guard Validator)
* **防線 1 (Prompt 白名單約束)**：顯式宣告絕對禁止火星文或非真實字彙（如 `ecu`, `dhu`, `aqz`），情境鎖定國中校園與日常生活。
* **防線 2 (後端極速字典與詞形還原)**：
  * 內建教育部國中 1200 / 2000 核心詞庫與教材單字庫（校驗耗時 `< 0.01ms`）。
  * 智慧詞形還原 (Lemmatization)：完整支援 `-s/-es/-ies`、`-ed/-ied`、`-ing`、`-er/-est`、`-ly` 及常見不規則動詞形，合法的時態變化不誤判。
  * 短句對話逐詞解析：選項為片語或交際用語時逐詞校驗。
  * 重試上限與保底替換：自動重試最多 3 次，極端狀況下自真實單字庫抽取同詞性單字替換，確保試卷 100% 正確。

### 4. 圖片題與純文字題雙向切換 (Image Question Dual Toggle)
* **審題面板雙向切換**：在審題面板中，所有單選題均提供 **「🖼️ 轉為圖片題」** 與 **「📝 轉回純文字題」** 自由切換。
* **三大標準會考圖表題型**：
  * **生活告示 / 菜單 / 營業時間 (70%)**：精確繪製含營業時間、特價優惠與規範之高對比圖表。
  * **空間方位地圖 (20%)**：十字路口、建築物方位與 "YOU ARE HERE" 看圖指路題。
  * **統計長條圖 (10%)**：學生喜好調查與百分比統計圖。
* **高解析度向量繪製**：由 Matplotlib 自動生成 300 DPI 黑白高對比圖片，並適配雙欄考卷寬度。

### 5. 成套專業 Word 考卷匯出 (Triple-Document Export)
* **試題卷**：標準 A4 雙欄排版、密封線、學生資訊欄、題幹與選項對齊排版，圖片完美嵌入題幹下方不破版。
* **解答卷**：標準雙欄簡答，便於教師閱卷。
* **詳細解析卷**：包含每道題目的繁體中文核心考點與完整詳解。

---

## 🛠️ 技術棧 (Tech Stack)

* **後端架構**：Python 3.10+, FastAPI, Uvicorn
* **文檔與繪圖**：Python-docx, pdfplumber, Matplotlib
* **AI 模型驅動**：本地 Ollama (`gemma4:e4b` / RTX 4060 離線加速)
* **前端介面**：原生 HTML5, 原生現代化 CSS (嚴格無 TailwindCSS 依賴), 原生 JavaScript (ES6+)

---

## 🚀 快速開始 (Quick Start)

### 1. 複製專案
```bash
git clone https://github.com/<your-username>/ExamCrafter-AI.git
cd ExamCrafter-AI
```

### 2. 安裝 Python 依賴
```bash
pip install -r requirements.txt
```

### 3. 下載並啟動本地 Ollama 模型
確保電腦已安裝 [Ollama](https://ollama.com/)：
```bash
ollama run gemma4:e4b
```

### 4. 啟動網站伺服器
* **方法 A**：雙擊根目錄下的 `啟動考卷生成網站.bat`
* **方法 B**：終端機執行指令：
```bash
python app.py
```

### 5. 開啟瀏覽器
開啟瀏覽器進入系統：
👉 **http://127.0.0.1:8000**

---

## 📁 專案目錄結構

```text
ExamCrafter-AI/
├── .gitignore                   # Git 忽略設定 (排除快取、二進位與暫存檔)
├── requirements.txt             # Python 依賴套件清單
├── README.md                    # 專案中文完整說明文件
├── 啟動考卷生成網站.bat          # Windows 一鍵啟動腳本
│
├── app.py                       # FastAPI 伺服器主入口與 RESTful API
├── agent_service.py             # 考卷生成核心大腦與骨架克隆管線
├── word_guard.py                # 單字門禁防線與詞形還原引擎
├── chart_registry.py            # 會考三大圖表繪圖引擎 (300 DPI)
├── rag_service.py               # 教材動態解析與科目感知 RAG 知識庫
├── generate_exam_docx.py        # 成套 Word 文件渲染排版器
│
├── static/                      # 前端靜態資源
│   ├── app.js                   # 前端應用邏輯 (SSE 即時進度、審題面板、題型切換)
│   └── style.css                # 現代化響應式 UI 樣式
└── templates/
    └── index.html               # 現代化單頁出題操作介面
```

---

## 📄 授權條款 (License)

本專案採用 [MIT License](LICENSE) 授權開源。
