"""
ExamCrafter AI - 本地科目感知 RAG 檢索服務 (rag_service.py)
功能：
1. 動態教材匯入：支援老師自訂上傳 PDF、Word (.docx)、純文字 (.txt) 或直接貼上文字內容。
2. 科目感知智能切片 (Subject-Aware Chunking)：
   - 英文科：自動解析單元標題、單字庫 (Words for Production)、文法句型 (Sentence Patterns)、課文段落 (Reading Passages)。
   - 國文與社會科 (歷史/地理/公民)：自動按標題與概念切片、核心概念術語、閱讀材料。
3. 動態知識容量評估 (Knowledge Capacity Check)：計算單元知識總量並提供出題邊界。
4. 結構化 Prompt 注入：提供 Micro-Prompt 上下文檢索，保持 600-800 tokens 精簡聚焦。
5. 支援一鍵載入示範教材 (12 單元) 與隨時清空重設。
"""

import os
import re
import json
import pdfplumber
from docx import Document


class RAGService:
    def __init__(self, textbook_dir="B04_教師用書pdf檔", cache_file="rag_index_cache.json"):
        self.textbook_dir = textbook_dir
        self.cache_file = cache_file
        self.index = {}
        # 啟動時預設載入快取，若無則為空字典 (等待老師上傳)
        self.load_cache()

    def load_cache(self):
        """載入快取檔案"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    self.index = json.load(f)
                print(f"[RAGService] 已載入 {len(self.index)} 個單元教材快取。")
            except Exception as e:
                print(f"[RAGService] 快取讀取失敗: {e}")
                self.index = {}

    def save_cache(self):
        """將目前索引存入快取"""
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.index, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[RAGService] 存入快取失敗: {e}")

    def clear_all(self):
        """清空所有已載入的教材索引"""
        self.index = {}
        if os.path.exists(self.cache_file):
            try:
                os.remove(self.cache_file)
            except Exception:
                pass
        print("[RAGService] 教材索引已清空。")

    def delete_unit(self, unit_id):
        """單獨刪除特定單元教材"""
        if unit_id in self.index:
            del self.index[unit_id]
            self.save_cache()
            print(f"[RAGService] 單元 {unit_id} 已移除。")
            return True
        return False

    def load_sample_units(self):
        """載入內建範例教材 (12 個單元)"""
        print("[RAGService] 正在載入內建範例教材...")
        if not os.path.exists(self.textbook_dir):
            return {"success": False, "message": f"找不到範例教材目錄: {self.textbook_dir}"}

        files = os.listdir(self.textbook_dir)
        count = 0
        for f in files:
            if "套紅" in f and f.endswith(".pdf"):
                m = re.search(r'(L\d\d|R\d\d)', f)
                unit_id = m.group(1) if m else f[:3]
                full_path = os.path.join(self.textbook_dir, f)
                self.ingest_file(full_path, f, subject="English", unit_id=unit_id)
                count += 1

        self.save_cache()
        return {"success": True, "count": count, "units": self.get_units_summary()}

    def get_units_summary(self):
        """回傳目前已索引單元的摘要清單"""
        summary = []
        for uid, data in self.index.items():
            summary.append({
                "unit_id": uid,
                "title": data.get("title", uid),
                "filename": data.get("filename", ""),
                "subject": data.get("subject", "English"),
                "vocab_count": len(data.get("vocabulary", [])),
                "grammar_count": len(data.get("grammar_patterns", [])),
                "passages_count": len(data.get("reading_passages", [])),
                "preview_vocab": data.get("vocabulary", [])[:8]
            })
        return summary

    # ==============================================================================
    # 核心檔案動態解析器 (支援 PDF, DOCX, TXT)
    # ==============================================================================
    def ingest_file(self, file_path, filename, subject="English", unit_id=None):
        """解析任意上傳的教材檔案並建立結構化切片索引"""
        ext = os.path.splitext(filename)[1].lower()
        full_text = ""

        try:
            if ext == ".pdf":
                with pdfplumber.open(file_path) as pdf:
                    for p_idx, page in enumerate(pdf.pages):
                        txt = page.extract_text() or ""
                        full_text += f"\n--- Page {p_idx+1} ---\n" + txt
            elif ext in [".docx", ".doc"]:
                try:
                    doc = Document(file_path)
                    full_text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
                except Exception as doc_err:
                    return {
                        "unit_id": unit_id or os.path.splitext(filename)[0][:20],
                        "filename": filename,
                        "is_corrupted": True,
                        "title": filename,
                        "message": f"檔案【{filename}】Word 文件解析失敗 ({doc_err})，若為舊版 .doc 請先轉存為 .docx 後再上傳。"
                    }
            elif ext in [".txt", ".md", ".csv"]:
                full_text = None
                for enc in ["utf-8", "cp950", "gb18030", "latin1"]:
                    try:
                        with open(file_path, "r", encoding=enc) as f:
                            full_text = f.read()
                        break
                    except (UnicodeDecodeError, Exception):
                        continue
                if full_text is None:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        full_text = f.read()
            else:
                return {
                    "unit_id": unit_id or os.path.splitext(filename)[0][:20],
                    "filename": filename,
                    "is_scanned_image": False,
                    "title": filename,
                    "message": f"檔案【{filename}】格式不支援，請上傳 PDF、Word (.docx) 或純文字 (.txt) 檔案。"
                }
        except Exception as e:
            print(f"[RAGService] 讀取檔案 {filename} 發生錯誤: {e}")
            return {
                "unit_id": unit_id or os.path.splitext(filename)[0][:20],
                "filename": filename,
                "is_corrupted": True,
                "title": filename,
                "message": f"檔案【{filename}】讀取解析失敗: {e}"
            }

        # 偵測是否為純圖片/掃描檔 (無文字層)
        if len(full_text.strip()) < 30:
            return {
                "unit_id": unit_id or os.path.splitext(filename)[0][:20],
                "filename": filename,
                "is_scanned_image": True,
                "title": filename,
                "message": f"檔案【{filename}】為純圖片掃描檔，文字層不足（少於 30 字），已略過。請改傳有包含文字內容的 PDF/Word 檔案，或使用「直接貼上教材文字內容」功能。"
            }

        lines = [l.strip() for l in full_text.split("\n") if l.strip()]

        # 自動推斷 unit_id 與標題 (問題3: 智慧標題識別與自動遞增編號)
        if not unit_id:
            # 1. 嘗試從檔名尋找 Unit / Lesson / Chapter
            m = re.search(r'(Unit\s*\d+|Lesson\s*\d+|Chapter\s*\d+|第\s*[0-9一二三四五六七八九十]+\s*[課單章節篇]|L\d+|U\d+|R\d+)', filename, re.IGNORECASE)
            
            # 2. 若檔名無規律，嘗試從內文前 15 行尋找單元關鍵字
            if not m:
                for l in lines[:15]:
                    if not l.startswith("--- Page") and not re.match(r'^\d+$', l):
                        m_line = re.search(r'(Unit\s*\d+|Lesson\s*\d+|Chapter\s*\d+|第\s*[0-9一二三四五六七八九十]+\s*[課單章節篇]|L\d+|U\d+|R\d+)', l, re.IGNORECASE)
                        if m_line:
                            m = m_line
                            break
            
            if m:
                unit_id = m.group(1).replace(" ", "_")
            else:
                # 檔名混亂無規律 (例如 新建文件(1).pdf)，採用自動遞增編號
                next_idx = len(self.index) + 1
                unit_id = f"Unit_{next_idx:02d}"

        unit_data = self._parse_text_to_unit(unit_id, filename, full_text, subject)

        # 覆蓋更新防重複 (問題4: 單元名稱重複時覆蓋更新)
        self.index[unit_id] = unit_data
        self.save_cache()
        return unit_data

    def ingest_pasted_text(self, title, text, subject="English"):
        """解析老師直接在網頁文字框貼上的教材文字內容"""
        clean_title = title.strip() or "自訂教材單元"
        m = re.search(r'(Unit\s*\d+|Lesson\s*\d+|第\s*[0-9一二三四五六七八九十]+\s*[課單章節篇]|L\d+|U\d+)', clean_title, re.IGNORECASE)
        unit_id = m.group(1).replace(" ", "_") if m else f"U_{len(self.index)+1:02d}"

        unit_data = self._parse_text_to_unit(unit_id, clean_title, text, subject)
        self.index[unit_id] = unit_data
        self.save_cache()
        return unit_data

    def _parse_text_to_unit(self, unit_id, source_name, full_text, subject="English"):
        """科目感知核心切片分析器"""
        unit_data = {
            "unit_id": unit_id,
            "filename": source_name,
            "subject": subject,
            "title": "",
            "vocabulary": [],
            "grammar_patterns": [],
            "reading_passages": [],
            "raw_text_length": len(full_text)
        }

        lines = [l.strip() for l in full_text.split("\n") if l.strip()]

        # 1. 抽取單元標題
        # 先嘗試從檔名抓取括號內容，例如: L02-教師用書pdf檔(套紅)(Goodbye, John).pdf -> Goodbye, John
        fn_matches = re.findall(r'\(([^)]+)\)', source_name)
        if fn_matches:
            cand = [m for m in fn_matches if "套紅" not in m and "教師" not in m and "pdf" not in m.lower()]
            if cand:
                unit_data["title"] = cand[-1].strip()

        if not unit_data["title"]:
            for l in lines[:15]:
                if len(l) > 3 and not l.startswith("--- Page") and not re.match(r'^\d+$', l):
                    if any(k in l.lower() for k in ["unit", "lesson", "chapter", "第", "課", "title", "主題"]):
                        unit_data["title"] = l
                        break
        if not unit_data["title"] and lines:
            unit_data["title"] = lines[0][:40]

        # 2. 針對科目進行特定切片
        if subject == "English":
            # 抽取單字 (包含單字標籤、詞性標籤與常見英文詞彙)
            # 優先搜尋包含詞性 (n., v., adj., adv.) 或中文解釋的行
            vocab_candidates = set()
            for l in lines:
                # 匹配模式如: apple (n.) 蘋果, challenge (v.) 挑戰, explore 探索
                words_with_pos = re.findall(r'\b([a-zA-Z]{3,20})\b\s*(?:\([a-z\.]+\))?\s*[\u4e00-\u9fa5]', l)
                for w in words_with_pos:
                    if w.lower() not in ["the", "and", "for", "with", "word", "words", "unit", "lesson"]:
                        vocab_candidates.add(w.lower())

                # 尋找 Words for Production / Vocabulary 區塊
                if any(h in l for h in ["Words for Production", "Vocabulary", "單字", "New Words", "Word Bank"]):
                    words = re.findall(r'\b[a-zA-Z]{3,20}\b', l)
                    for w in words:
                        if w.lower() not in ["the", "and", "for", "with", "word", "words", "production", "unit", "lesson", "vocabulary"]:
                            vocab_candidates.add(w.lower())

            # 若沒萃取到足夠單字，則從全文中抓取長度大於 4 的顯著名詞/動詞
            if len(vocab_candidates) < 5:
                all_eng_words = re.findall(r'\b[a-zA-Z]{4,15}\b', full_text)
                freq = {}
                stop_words = {"this", "that", "there", "their", "about", "which", "would", "could", "should", "from", "with", "page", "unit", "lesson"}
                for w in all_eng_words:
                    wl = w.lower()
                    if wl not in stop_words:
                        freq[wl] = freq.get(wl, 0) + 1
                sorted_words = sorted(freq.keys(), key=lambda x: freq[x], reverse=True)
                vocab_candidates.update(sorted_words[:30])

            unit_data["vocabulary"] = sorted(list(vocab_candidates))

            # 抽取文法句型 (Sentence Patterns / Grammar)
            for l in lines:
                if any(k in l for k in ["Sentence Pattern", "Grammar", "句型", "文法焦點", "S +", "It is", "The +", "V-ing", "p.p.", "not only", "whether", "because"]):
                    if len(l) > 6 and l not in unit_data["grammar_patterns"]:
                        unit_data["grammar_patterns"].append(l[:100])

            # 抽取閱讀篇章 (尋找英文自然段落，長度 > 80 字元)
            paragraphs = [p.strip() for p in full_text.split("\n\n") if len(p.strip()) > 80]
            # 篩選主要是英文句子的段落
            eng_paragraphs = []
            for p in paragraphs:
                eng_letters = len(re.findall(r'[a-zA-Z]', p))
                if eng_letters > 40:
                    eng_paragraphs.append(p)
            unit_data["reading_passages"] = eng_paragraphs[:8]

        else:
            # 國文、歷史、地理、公民科切片
            concepts = set()
            for l in lines:
                # 抽取粗體、引號、書名號、或重點標記的概念詞
                quoted = re.findall(r'[「【《“]([^」】》”\n]{2,15})[」】》”]', l)
                concepts.update(quoted)
                if any(k in l for k in ["重點", "概念", "考點", "名詞解釋", "定義"]):
                    concepts.add(l[:30])
            unit_data["vocabulary"] = list(concepts)[:40]

            # 閱讀篇章/段落 (長度 > 60 字元)
            paragraphs = [p.strip() for p in full_text.split("\n\n") if len(p.strip()) > 60 and not p.strip().startswith("---")]
            unit_data["reading_passages"] = paragraphs[:8]

        return unit_data

    # ==============================================================================
    # 知識庫容量與出題上下文檢索
    # ==============================================================================
    def get_unit_capacity(self, subject, unit_ids):
        """
        知識容量檢測：評估指定單元的單字量與知識點總量
        回傳: (單字數量, 語法點數量, 建議題數上限)
        """
        total_vocab = 0
        total_grammar = 0
        for uid in unit_ids:
            if uid in self.index:
                total_vocab += len(self.index[uid].get("vocabulary", []))
                total_grammar += len(self.index[uid].get("grammar_patterns", []))

        recommended_max = max(total_vocab, 25)
        return total_vocab, total_grammar, recommended_max

    def retrieve_context_for_prompt(self, subject, unit_ids, question_type="CHOICE", limit_tokens=800):
        """
        為出題 Agent 組裝專屬 Micro-Prompt 上下文 (保持精簡聚焦，小於 800 tokens)
        """
        combined_vocab = []
        combined_grammar = []
        combined_texts = []
        unit_titles = []

        for uid in unit_ids:
            if uid in self.index:
                u = self.index[uid]
                unit_titles.append(f"{uid}: {u.get('title', uid)}")
                combined_vocab.extend(u.get("vocabulary", []))
                combined_grammar.extend(u.get("grammar_patterns", []))
                combined_texts.extend(u.get("reading_passages", []))

        # 去重
        combined_vocab = list(dict.fromkeys(combined_vocab))[:35]
        combined_grammar = list(dict.fromkeys(combined_grammar))[:6]

        context_md = f"### [教材單元知識點]\n"
        context_md += f"- **出題範圍**: {', '.join(unit_titles) if unit_titles else ', '.join(unit_ids)}\n"

        if combined_vocab:
            context_md += f"- **核心目標單字/概念庫**: {', '.join(combined_vocab[:25])}\n"
        if combined_grammar:
            context_md += f"- **核心句型與語法焦點**:\n"
            for g in combined_grammar:
                context_md += f"  * {g}\n"

        if question_type == "GROUP_PASSAGE" and combined_texts:
            sample_reading = combined_texts[0][:300] if combined_texts else ""
            context_md += f"- **課文主題風格範例** (僅供語境與難度參考，題幹文章須全新原創):\n> {sample_reading}...\n"

        return context_md


# 模組單例
rag_service = RAGService()
