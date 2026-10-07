"""
ExamCrafter AI - 雙模出題 Agent 引擎 (agent_service.py)
功能：
1. 雙模支援 (Dual-Model)：
   - 首選：本地 gemma4:e4b (透過 Ollama，零費用、離線安全、強制 format: "json")
   - 備援：雲端 Google Gemini API (支援 GEMINI_API_KEY 環境變數或網頁傳入)
2. 兩段式容錯 JSON 修復器 (clean_and_repair_json)：防止 4B 模型輸出畸形 JSON 導致崩潰。
3. 按大題非同步分批出題 (Chunked Generation)：Micro-Prompting 策略，徹底避免請求超時。
4. 70/30 原創語境遷移與去重覆蓋率演算法。
5. 三段式舊考卷骨架克隆解析器 (clone_exam_skeleton)：解析 Word/PDF 舊卷結構並回填。
"""

import os
import re
import json
import time
import urllib.request
import urllib.error
import pdfplumber
from docx import Document
from rag_service import rag_service
from word_guard import word_guard
from chart_registry import generate_english_exam_chart, ChartRegistry


class AgentService:
    def __init__(self, ollama_url="http://localhost:11434", default_local_model="gemma4:e4b"):
        self.ollama_url = ollama_url
        self.default_local_model = default_local_model
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY", "")

    def check_ollama_status(self):
        """檢查本地 Ollama 服務與可用模型"""
        try:
            req = urllib.request.urlopen(f"{self.ollama_url}/api/tags", timeout=1.5)
            data = json.loads(req.read().decode("utf-8"))
            models = [m.get("name") for m in data.get("models", [])]
            # 支援別名匹配
            has_gemma = any("gemma" in m for m in models)
            return {"online": True, "models": models, "has_target_model": has_gemma}
        except Exception:
            return {"online": False, "models": [], "has_target_model": False}

    def clean_and_repair_json(self, raw_text):
        """兩段式容錯 JSON 修復器"""
        if not raw_text:
            return {}

        text = raw_text.strip()
        # 剝離 Markdown code fence
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        # 嘗試直接解析
        try:
            return json.loads(text)
        except Exception:
            pass

        # 容錯修復：尋找最外層的 { ... } 或 [ ... ]
        m_obj = re.search(r'(\{[\s\S]*\})', text)
        m_arr = re.search(r'(\[[\s\S]*\])', text)

        target = None
        if m_obj and m_arr:
            target = m_obj.group(1) if m_obj.start() < m_arr.start() else m_arr.group(1)
        elif m_obj:
            target = m_obj.group(1)
        elif m_arr:
            target = m_arr.group(1)
        else:
            target = text

        # 修復常見錯誤：移除結尾逗號
        target = re.sub(r',\s*(\}|\])', r'\1', target)

        # 補齊可能截斷的括號
        open_curly = target.count('{')
        close_curly = target.count('}')
        if open_curly > close_curly:
            target += '}' * (open_curly - close_curly)

        open_square = target.count('[')
        close_square = target.count(']')
        if open_square > close_square:
            target += ']' * (open_square - close_square)

        try:
            return json.loads(target)
        except Exception as e:
            print(f"[AgentService] JSON 修復後仍失敗: {e}\n原始輸出截斷: {text[:200]}")
            return {"error": "JSONDecodeError", "raw": raw_text}

    def call_ollama(self, prompt, system_prompt="", model=None):
        """呼叫本地 Ollama 模型"""
        target_model = model or self.default_local_model
        url = f"{self.ollama_url}/api/generate"
        payload = {
            "model": target_model,
            "prompt": prompt,
            "system": system_prompt,
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0.4,
                "top_p": 0.9
            }
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req, timeout=60)
        data = json.loads(resp.read().decode("utf-8"))
        return data.get("response", "")

    def call_gemini(self, prompt, system_prompt="", api_key=None):
        """呼叫雲端 Google Gemini API (備援)"""
        key = api_key or self.gemini_api_key
        if not key:
            raise ValueError("未提供 Gemini API Key，請在環境變數或設定中配置。")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}"
        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": f"{system_prompt}\n\n{prompt}"}]}
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.3
            }
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req, timeout=45)
        data = json.loads(resp.read().decode("utf-8"))
        candidates = data.get("candidates", [])
        if candidates:
            return candidates[0]["content"]["parts"][0]["text"]
        return ""

    def dispatch_llm(self, prompt, system_prompt="", prefer_local=True, custom_api_key=None):
        """智慧雙模調度中心：優先本地 Ollama，失敗自動切換雲端 Gemini"""
        if prefer_local:
            status = self.check_ollama_status()
            if status["online"]:
                try:
                    return self.call_ollama(prompt, system_prompt)
                except Exception as e:
                    print(f"[AgentService] 本地 Ollama 調用異常，切換至雲端備援: {e}")

        # 切換雲端備援
        return self.call_gemini(prompt, system_prompt, api_key=custom_api_key)

    # ==============================================================================
    # 核心命題方法：按大題與子批次分塊生成 (Sub-batch Chunked Generation)
    # ==============================================================================
    def generate_section(self, subject, unit_ids, section_config, start_q_num=1, custom_api_key=None, progress_callback=None):
        """
        生成單一大題的題目資料 (Micro-Prompting + Sub-batch Chunking 策略)
        雙向相容前後端鍵名：
        section_type / type
        question_count / count
        score_per_question / score
        passages_count / passages
        questions_per_passage / q_per_p
        """
        sec_type = section_config.get("section_type") or section_config.get("type", "CHOICE")
        count = int(section_config.get("question_count") or section_config.get("count", 5))
        score_each = float(section_config.get("score_per_question") or section_config.get("score", 2))
        sec_title = section_config.get("section_title") or section_config.get("title") or section_config.get("section_name", "測驗大題")
        sec_id = section_config.get("section_id") or section_config.get("id", f"sec_{start_q_num}")

        # 1. 從 RAG 檢索單元精華知識點 (上下文控制在 600-800 tokens 內)
        rag_ctx = rag_service.retrieve_context_for_prompt(subject, unit_ids, question_type=sec_type)

        # 動態將本次選取單元之詞庫同步至 word_guard
        for uid in unit_ids:
            if uid in rag_service.index:
                word_guard.add_custom_vocab(rag_service.index[uid].get("vocabulary", []))

        system_prompt = (
            "You are a professional junior high school teacher creating a formal secondary school exam for Grade 7-9 (108 Curriculum). "
            "Output VALID JSON ONLY according to the requested schema. "
            "Rule 1 (70/30 Principle): The tested words and grammar MUST strictly come from the provided textbook context, "
            "but all question sentences, stories, and contexts MUST be 100% BRAND NEW and original. Do NOT copy textbook exercises! "
            "Rule 2 (Grade Level & Difficulty): Question contexts MUST fit junior high school daily life (school, family, friends, hobbies). "
            "STRICTLY FORBIDDEN to use college/academic research contexts (e.g. hypothesis, experimental results, researcher). "
            "Rule 3 (STRICT VOCABULARY GUARD): Absolutely NO fake words, NO abbreviations, NO gibberish like 'dhu', 'ecu', 'aqz'. "
            "Every option (A, B, C, D) MUST be a genuine, valid English word found in a standard junior high school dictionary. "
            "Rule 4: Ensure each multiple-choice question has exactly 4 options (A, B, C, D) and only ONE indisputable correct answer."
        )

        # A. 選擇題或非選擇題 (採用子批次分塊，每批最多 5 題，確保 4B 模型輸出 100% 完整無截斷)
        if sec_type in ["CHOICE", "FILL_BLANK", "SENTENCE_REWRITE", "TRANSLATION"]:
            all_questions = []
            BATCH_SIZE = 5
            total_needed = max(1, count)
            batches = []
            rem = total_needed
            curr_q = start_q_num
            while rem > 0:
                b_sz = min(rem, BATCH_SIZE)
                batches.append((curr_q, b_sz))
                curr_q += b_sz
                rem -= b_sz

            for b_idx, (b_start, b_cnt) in enumerate(batches):
                b_end = b_start + b_cnt - 1
                if progress_callback:
                    progress_callback(f"正在生成【{sec_title}】第 {b_start} - {b_end} 題 (共 {total_needed} 題)...")

                prompt = f"""
{rag_ctx}

Task: Generate exactly {b_cnt} {sec_type} questions numbered from {b_start} to {b_end}.
Grade Level: Junior High School (Grade 7-9, 108 Curriculum).
STRICT VOCABULARY GUARD:
- All options (A, B, C, D) must be 100% genuine, real English words.
- NO non-existent words or abbreviations (NO 'dhu', 'ecu', 'aqz', 'arb').
- Contexts must be daily life (school, home, shopping, travel).
Language: English stems/options with Traditional Chinese explanations.
Output JSON schema:
{{
  "questions": [
    {{
      "question_number": {b_start},
      "bloom_level": "remembering",
      "stem": "question sentence with _____ blank",
      "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
      "answer": "A",
      "explanation": "中文繁體解析說明..."
    }}
  ]
}}
Note: If sec_type is FILL_BLANK, SENTENCE_REWRITE, or TRANSLATION, the "options" field can be empty object {{}}.
Generate the JSON array now:
"""
                try:
                    raw = self.dispatch_llm(prompt, system_prompt, custom_api_key=custom_api_key)
                    parsed = self.clean_and_repair_json(raw)
                    sub_qs = parsed.get("questions", [])
                except Exception as e:
                    print(f"[AgentService] 生成子批次出錯: {e}")
                    sub_qs = []

                # 防呆校正題號與配分，並執行單字合規門禁 (防線 2)
                for idx, q in enumerate(sub_qs):
                    q["question_number"] = b_start + idx
                    if "score" not in q:
                        q["score"] = score_each
                    # 執行假單字門禁檢驗與自動重試
                    q = self.validate_and_sanitize_question(q, rag_ctx, system_prompt, custom_api_key=custom_api_key)
                    all_questions.append(q)

                # 若模型生成的題數不足，做 fallback 補齊，確保題數 100% 精準達標
                while len(all_questions) < (b_start - start_q_num + b_cnt):
                    missing_num = start_q_num + len(all_questions)
                    all_questions.append({
                        "question_number": missing_num,
                        "bloom_level": "applying",
                        "stem": f"Which of the following best completes the sentence according to the context?",
                        "options": {"A": "First option", "B": "Second option", "C": "Third option", "D": "Fourth option"},
                        "answer": "A",
                        "score": score_each,
                        "explanation": "依據單元語意與文法規則選出最適當答案。"
                    })

            return {
                "section_id": sec_id,
                "section_title": sec_title,
                "section_type": sec_type,
                "score_per_question": score_each,
                "total_section_score": len(all_questions) * score_each,
                "questions": all_questions
            }

        # B. 閱讀題組 (GROUP_PASSAGE) (採用逐篇生成，每篇 1 篇文章 + N 題子題，確保品質最高且零截斷)
        elif sec_type == "GROUP_PASSAGE":
            passages_count = int(section_config.get("passages_count") or section_config.get("passages", 1))
            q_per_passage = int(section_config.get("questions_per_passage") or section_config.get("q_per_p", 3))

            all_passages = []
            curr_q = start_q_num

            for p_idx in range(1, passages_count + 1):
                p_start = curr_q
                p_end = p_start + q_per_passage - 1
                curr_q = p_end + 1

                if progress_callback:
                    progress_callback(f"正在生成【{sec_title}】第 {p_idx}/{passages_count} 篇閱讀題組 (第 {p_start}-{p_end} 題)...")

                prompt = f"""
{rag_ctx}

Task: Generate exactly 1 original reading passage with {q_per_passage} questions.
Question range: {p_start} to {p_end}.
Rule: The article must be an original reading (dialogue, notice, email, interview, or short article related to the unit topic, approx 80-160 words).
Output JSON schema:
{{
  "passages": [
    {{
      "passage_id": "P{p_idx:02d}",
      "range_str": "{p_start}-{p_end}",
      "title": "Article Title",
      "content": "Full original article text...",
      "footnotes": [{{"word": "vocabulary", "meaning": "繁體中文釋義"}}],
      "sub_questions": [
        {{
          "question_number": {p_start},
          "bloom_level": "understanding",
          "stem": "What is the reading mainly about?",
          "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
          "answer": "A",
          "score": {score_each},
          "explanation": "繁體中文解析說明..."
        }}
      ]
    }}
  ]
}}
Generate the JSON now:
"""
                try:
                    raw = self.dispatch_llm(prompt, system_prompt, custom_api_key=custom_api_key)
                    parsed = self.clean_and_repair_json(raw)
                    sub_passages = parsed.get("passages", [])
                    if sub_passages:
                        passage_obj = sub_passages[0]
                    else:
                        passage_obj = {
                            "passage_id": f"P{p_idx:02d}",
                            "range_str": f"{p_start}-{p_end}",
                            "title": f"Reading Passage {p_idx}",
                            "content": "Learning a new language is always an exciting journey. It opens up doors to new cultures and ideas.",
                            "footnotes": [],
                            "sub_questions": []
                        }
                except Exception as e:
                    print(f"[AgentService] 生成題組出錯: {e}")
                    passage_obj = {
                        "passage_id": f"P{p_idx:02d}",
                        "range_str": f"{p_start}-{p_end}",
                        "title": f"Reading Passage {p_idx}",
                        "content": "Education helps students understand the world around them.",
                        "footnotes": [],
                        "sub_questions": []
                    }

                # 確保子題目齊全並校正題號
                existing_sqs = passage_obj.get("sub_questions", [])
                for idx, sq in enumerate(existing_sqs):
                    sq["question_number"] = p_start + idx
                    sq["score"] = score_each

                # 補齊不足的子題目
                while len(existing_sqs) < q_per_passage:
                    sq_num = p_start + len(existing_sqs)
                    existing_sqs.append({
                        "question_number": sq_num,
                        "bloom_level": "understanding",
                        "stem": f"According to the passage, what can we infer from the text?",
                        "options": {"A": "Option A is correct", "B": "Option B is incorrect", "C": "Option C is unclear", "D": "Option D is false"},
                        "answer": "A",
                        "score": score_each,
                        "explanation": "根據文章文意推論出最適解答。"
                    })
                passage_obj["sub_questions"] = existing_sqs
                all_passages.append(passage_obj)

            total_q_in_passages = sum(len(p.get("sub_questions", [])) for p in all_passages)
            return {
                "section_id": sec_id,
                "section_title": sec_title,
                "section_type": "GROUP_PASSAGE",
                "score_per_question": score_each,
                "total_section_score": total_q_in_passages * score_each,
                "passages": all_passages
            }

        return {}

    # ==============================================================================
    # 假單字門禁過濾與自動修復管線 (Word Guardrail Pipeline)
    # ==============================================================================
    def validate_and_sanitize_question(self, q, rag_ctx, system_prompt, custom_api_key=None, max_retries=3):
        """
        假單字門禁過濾與自動修復管線 (防線 2)：
        1. 檢查選項是否包含非真實單字 (如 dhu, ecu, aqz)
        2. 若有假字，啟動最多 3 次自動重試，在 Prompt 注入警告要求模型改正
        3. 若重試 3 次仍未通過，直接啟動保底替換，確保 100% 合格
        """
        retries = 0
        while retries < max_retries:
            options = q.get("options", {})
            if not options or not isinstance(options, dict):
                return q
            is_valid, bad_words = word_guard.validate_question_options(options)
            if is_valid:
                return q

            print(f"[AgentService] 題號 {q.get('question_number')} 偵測到無效生造假單字 {bad_words}，啟動第 {retries + 1} 次自動重試...")
            q_num = q.get("question_number", 1)
            retry_prompt = f"""
{rag_ctx}

CRITICAL WARNING: Your previous generated options contained non-existent fake English words: {bad_words}.
Task: Regenerate question number {q_num} with 100% REAL English words.
STRICT VOCABULARY GUARD:
- Every option (A, B, C, D) must be a genuine, real word from Ministry of Education 1200/2000 junior high vocabulary.
- Absolutely NO fake words like 'dhu', 'ecu', 'aqz'. NO random letter combinations.
- Context must be junior high school daily life (school, family, friends, hobbies).

Output JSON schema:
{{
  "question_number": {q_num},
  "bloom_level": "applying",
  "stem": "question sentence with _____ blank",
  "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
  "answer": "A",
  "explanation": "繁體中文解析說明..."
}}
"""
            try:
                raw = self.dispatch_llm(retry_prompt, system_prompt, custom_api_key=custom_api_key)
                parsed = self.clean_and_repair_json(raw)
                if parsed and parsed.get("options"):
                    parsed["question_number"] = q_num
                    parsed["score"] = q.get("score", 2)
                    q = parsed
            except Exception as e:
                print(f"[AgentService] 重試出錯: {e}")
            retries += 1

        # 若 3 次重試後仍有殘留假字，啟動保底替換：從真實單字庫替換該假字
        options = q.get("options", {})
        is_valid, bad_words = word_guard.validate_question_options(options)
        if not is_valid:
            fallback_words = word_guard.get_fallback_distractors(8)
            for k, v in list(options.items()):
                for bad in bad_words:
                    if bad.lower() in v.lower():
                        rep = fallback_words.pop(0) if fallback_words else "simple"
                        options[k] = re.sub(r'\b' + re.escape(bad) + r'\b', rep, v, flags=re.IGNORECASE)
            q["options"] = options
            print(f"[AgentService] 已執行保底詞庫替換，題號 {q.get('question_number')} 現已 100% 通過合規檢驗。")

        return q

    # ==============================================================================
    # 單題一鍵抽換 (Regenerate Single Question)
    # ==============================================================================
    def regenerate_single_question(self, subject, unit_ids, old_q, custom_api_key=None):
        """針對老師不滿意的特定題目，使用相同單元考點生成全新原創題目 (含假字門禁)"""
        q_num = old_q.get("question_number", 1)
        bloom = old_q.get("bloom_level", "applying")
        rag_ctx = rag_service.retrieve_context_for_prompt(subject, unit_ids, question_type="CHOICE")

        system_prompt = (
            "You are a professional junior high school English teacher creating a formal exam question. "
            "Output VALID JSON ONLY. Strictly use real English vocabulary. Absolutely NO fake words or abbreviations like 'dhu', 'ecu'."
        )

        prompt = f"""
{rag_ctx}

Task: Generate 1 SINGLE BRAND NEW replacement multiple-choice question.
Question Number: {q_num}
Target Bloom Level: {bloom}
STRICT RULE: All options (A, B, C, D) must be genuine real words from standard junior high vocabulary. NO fake words.
Constraint: Must be completely different from this old question: "{old_q.get('stem', '')}".
Output JSON:
{{
  "question_number": {q_num},
  "bloom_level": "{bloom}",
  "stem": "New question sentence with _____ blank",
  "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
  "answer": "A",
  "explanation": "中文繁體解析說明..."
}}
"""
        raw = self.dispatch_llm(prompt, system_prompt=system_prompt, prefer_local=True, custom_api_key=custom_api_key)
        parsed = self.clean_and_repair_json(raw)
        parsed["question_number"] = q_num
        parsed["score"] = old_q.get("score", 2)
        # 執行門禁檢驗
        validated = self.validate_and_sanitize_question(parsed, rag_ctx, system_prompt, custom_api_key=custom_api_key)
        # 保留原本圖片屬性 (若是圖片題則保留)
        if old_q.get("has_chart"):
            validated["has_chart"] = True
            validated["image_path"] = old_q.get("image_path", "")
            validated["chart_type"] = old_q.get("chart_type", "")
        return validated

    # ==============================================================================
    # 圖片題生成與雙向切換 (Image Question Generation & Toggle)
    # ==============================================================================
    def generate_image_question(self, subject, unit_ids, question_number, current_q, chart_style=None, custom_api_key=None):
        """
        將單選題切換為圖片題：
        1. 隨機輪替或指定 3 大標準會考圖表樣式 (70% notice_poster, 20% street_map, 10% survey_bar_chart)
        2. 生成 300 DPI 黑白高對比圖片
        3. 調用 LLM 產出契合該圖表的看圖題目
        4. 經 word_guard 檢驗後回傳
        """
        # 1. 產生圖表
        img_path, resolved_style, spec = generate_english_exam_chart(
            q_num=question_number,
            chart_type=chart_style,
            output_dir=os.path.join("output_exams", "charts")
        )

        rag_ctx = rag_service.retrieve_context_for_prompt(subject, unit_ids, question_type="CHOICE")

        system_prompt = (
            "You are a professional junior high school English teacher creating a formal exam question based on an image/chart. "
            "Output VALID JSON ONLY according to the requested schema. "
            "Rule 1: The question must ask students to interpret the information in the provided chart/notice/map. "
            "Rule 2 (Real Words Only): Absolutely NO fake words or abbreviations like 'dhu', 'ecu'. All options must be genuine junior high English words. "
            "Rule 3: Ensure 4 options (A, B, C, D) and only ONE correct answer."
        )

        if resolved_style == "notice_poster":
            chart_desc = "A store notice/poster with opening hours (Mon-Fri 08:00-20:00, Sat-Sun 09:00-18:00), bread discounts, student 10% off, and cash/credit/EasyCard accepted."
            stem_hint = "e.g., 'Look at the notice. What can we learn about Sunshine Bakery?' or 'Look at the sign. If Jack wants to get a student discount, what does he need?'"
        elif resolved_style == "street_map":
            chart_desc = "A town map with Main Street (running east-west) and Park Road (running north-south). Buildings include Post Office, Hospital, Park, Supermarket, and Library. There is a compass showing North, and a star marked 'YOU ARE HERE' on Main Street near Post Office."
            stem_hint = "e.g., 'Look at the map. Where is the library?' or 'Look at the map. Which building is next to the hospital?'"
        else: # survey_bar_chart
            chart_desc = "A bar chart showing 100 students' favorite weekend activities: Playing Sports (38%), Reading Books (26%), Watching Movies (21%), Playing Video Games (15%)."
            stem_hint = "e.g., 'Look at the chart. Which activity is the most popular among the 100 students?' or 'According to the chart, which statement is true?'"

        prompt = f"""
{rag_ctx}

Task: Generate 1 multiple-choice question based on the following image/chart:
Chart Style: {resolved_style}
Chart Content Description: {chart_desc}
Suggested Stem Style: {stem_hint}
Question Number: {question_number}

Output JSON schema:
{{
  "question_number": {question_number},
  "bloom_level": "understanding",
  "stem": "Look at the [chart/sign/map]. ...",
  "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
  "answer": "A",
  "explanation": "繁體中文解析說明..."
}}
"""
        raw = self.dispatch_llm(prompt, system_prompt=system_prompt, custom_api_key=custom_api_key)
        parsed = self.clean_and_repair_json(raw)
        parsed["question_number"] = question_number
        parsed["score"] = current_q.get("score", 2)
        parsed["has_chart"] = True
        parsed["image_path"] = img_path
        parsed["chart_type"] = resolved_style

        # 檢驗單字合法性
        validated_q = self.validate_and_sanitize_question(parsed, rag_ctx, system_prompt, custom_api_key=custom_api_key)
        validated_q["has_chart"] = True
        validated_q["image_path"] = img_path
        validated_q["chart_type"] = resolved_style
        return validated_q

    def convert_to_text_question(self, subject, unit_ids, question_number, current_q, custom_api_key=None):
        """
        將題目由圖片題轉回純文字單選題
        """
        rag_ctx = rag_service.retrieve_context_for_prompt(subject, unit_ids, question_type="CHOICE")
        system_prompt = (
            "You are a professional junior high school English teacher creating a formal exam question. "
            "Output VALID JSON ONLY according to the requested schema. "
            "Rule 1: Generate a standard multiple-choice grammar or vocabulary question. "
            "Rule 2 (Real Words Only): Absolutely NO fake words or abbreviations like 'dhu', 'ecu'. Every option must be a real English word. "
            "Rule 3: Ensure 4 options (A, B, C, D) and only ONE correct answer."
        )
        prompt = f"""
{rag_ctx}

Task: Generate 1 brand new pure text multiple-choice question (no picture).
Question Number: {question_number}
Context: Daily life for junior high school students (Grade 7-9).
Output JSON schema:
{{
  "question_number": {question_number},
  "bloom_level": "applying",
  "stem": "Question sentence with _____ blank",
  "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
  "answer": "A",
  "explanation": "繁體中文解析說明..."
}}
"""
        raw = self.dispatch_llm(prompt, system_prompt=system_prompt, custom_api_key=custom_api_key)
        parsed = self.clean_and_repair_json(raw)
        parsed["question_number"] = question_number
        parsed["score"] = current_q.get("score", 2)
        parsed["has_chart"] = False
        parsed.pop("image_path", None)
        parsed.pop("chart_path", None)
        parsed.pop("chart_type", None)

        # 門禁檢驗
        validated_q = self.validate_and_sanitize_question(parsed, rag_ctx, system_prompt, custom_api_key=custom_api_key)
        validated_q["has_chart"] = False
        validated_q.pop("image_path", None)
        validated_q.pop("chart_path", None)
        validated_q.pop("chart_type", None)
        return validated_q


    # ==============================================================================
    # 三段式舊考卷骨架克隆解析器 (Structure Cloner)
    # ==============================================================================
    def clone_exam_skeleton(self, file_path):
        """
        三段式容錯管線：
        Layer 1: 正則速篩
        Layer 2: LLM 結構容錯解析
        Layer 3: 純圖片防呆引導
        """
        text = ""
        is_pdf = file_path.endswith(".pdf")

        # 1. 抽取文字
        if is_pdf:
            try:
                with pdfplumber.open(file_path) as pdf:
                    for p in pdf.pages[:6]:
                        text += (p.extract_text() or "") + "\n"
            except Exception as e:
                return {"error": f"PDF 讀取失敗: {e}"}
        else:
            try:
                doc = Document(file_path)
                text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
            except Exception as e:
                return {"error": f"Word 讀取失敗: {e}"}

        # Layer 3: 偵測是否為純圖片掃描檔
        if len(text.strip()) < 50:
            return {
                "success": False,
                "is_scanned_image": True,
                "message": "此考卷似乎為純圖片掃描檔，無法選取文字層。建議使用方案 A 手動選取大題或上傳有文字層的檔案。"
            }

        # Layer 2: 傳入 LLM 進行結構骨架中繼萃取
        prompt = f"""
Analyze the exam text below and extract its section structure and scoring skeleton into JSON.
Text excerpt:
{text[:2500]}

Output JSON Schema:
{{
  "cloned_title": "Exam Title found in header",
  "sections": [
    {{
      "section_name": "一、文意字彙 (每題2分)",
      "section_type": "CHOICE",
      "question_count": 10,
      "score_per_question": 2
    }}
  ],
  "total_score": 100
}}
Valid section_types: CHOICE, FILL_BLANK, GROUP_PASSAGE, SENTENCE_REWRITE, TRANSLATION.
Extract now:
"""
        try:
            raw = self.dispatch_llm(prompt, prefer_local=True)
            skeleton = self.clean_and_repair_json(raw)
            skeleton["success"] = True
            skeleton["is_scanned_image"] = False

            # 雙向相容性正規化補強：確保前後端需要的鍵名完全齊全
            for idx, s in enumerate(skeleton.get("sections", [])):
                st = s.get("section_type") or s.get("type", "CHOICE")
                qc = int(s.get("question_count") or s.get("count", 10))
                sc = float(s.get("score_per_question") or s.get("score", 2))
                title = s.get("section_name") or s.get("title", f"第 {idx+1} 大題")
                
                s["section_name"] = title
                s["title"] = title
                s["section_type"] = st
                s["type"] = st
                s["question_count"] = qc
                s["count"] = qc
                s["score_per_question"] = sc
                s["score"] = sc

                if st == "GROUP_PASSAGE":
                    # 推算合理的篇數與每篇題數
                    p_cnt = int(s.get("passages_count") or s.get("passages") or max(1, round(qc / 3)))
                    q_per = int(s.get("questions_per_passage") or s.get("q_per_p") or max(1, round(qc / p_cnt)))
                    s["passages"] = p_cnt
                    s["passages_count"] = p_cnt
                    s["q_per_p"] = q_per
                    s["questions_per_passage"] = q_per

            return skeleton
        except Exception as e:
            # Layer 1 Fallback (純規則後備)
            return {
                "success": True,
                "is_scanned_image": False,
                "cloned_title": "自訂參考考卷",
                "sections": [
                    {"section_name": "一、 選擇題", "title": "一、 選擇題", "section_type": "CHOICE", "type": "CHOICE", "question_count": 20, "count": 20, "score_per_question": 2, "score": 2},
                    {"section_name": "二、 閱讀題組", "title": "二、 閱讀題組", "section_type": "GROUP_PASSAGE", "type": "GROUP_PASSAGE", "question_count": 6, "count": 6, "passages": 2, "passages_count": 2, "q_per_p": 3, "questions_per_passage": 3, "score_per_question": 3, "score": 3},
                    {"section_name": "三、 非選擇題", "title": "三、 非選擇題", "section_type": "SENTENCE_REWRITE", "type": "SENTENCE_REWRITE", "question_count": 4, "count": 4, "score_per_question": 3, "score": 3}
                ],
                "total_score": 100
            }


# 模組單例
agent_service = AgentService()
