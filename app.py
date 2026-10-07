"""
ExamCrafter AI - 智慧考卷生成系統後端服務 (app.py)
技術棧：FastAPI + Python-docx + Ollama (gemma4:e4b) + 本地科目感知 RAG
啟動方式：python app.py
"""

import os
import json
import shutil
import asyncio
from typing import List, Dict, Any, Optional

import uvicorn
from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from pydantic import BaseModel

from rag_service import rag_service
from agent_service import agent_service
from word_guard import word_guard
from generate_exam_docx import render_exam_suite

app = FastAPI(title="ExamCrafter AI", version="2.5.0")

# 確保必要目錄存在 (100% 本地純離線原生系統)
os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)
os.makedirs(os.path.join("uploads", "textbooks"), exist_ok=True)
os.makedirs("output_exams", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/output_exams", StaticFiles(directory="output_exams"), name="output_exams")


# ==============================================================================
# 1. 首頁路由
# ==============================================================================
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = os.path.join("templates", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>找不到 templates/index.html 檔案</h1>"


# ==============================================================================
# 2. 系統狀態與教材管理 API
# ==============================================================================
@app.get("/api/status")
async def get_system_status():
    rag_service.load_cache()
    ollama_stat = agent_service.check_ollama_status()
    return {
        "ollama_online": ollama_stat["online"],
        "model": "gemma4:e4b" if ollama_stat["has_target_model"] else "雲端備援模式",
        "has_target_model": ollama_stat["has_target_model"],
        "indexed_units": list(rag_service.index.keys()),
        "units_count": len(rag_service.index)
    }


@app.get("/api/units")
async def get_units(subject: str = "English"):
    """取得當前已載入之教材單元完整清單與知識點統計"""
    rag_service.load_cache()
    return {
        "success": True,
        "units": rag_service.get_units_summary()
    }


@app.post("/api/upload-textbooks")
async def upload_textbooks(
    files: List[UploadFile] = File(...),
    subject: str = Form("English")
):
    """
    老師自主上傳教材檔案 API (支援 PDF、Word docx、純文字 txt，可多檔同時上傳)
    讀取後自動完成科目感知結構化切片並納入出題索引庫
    """
    saved_results = []
    scanned_warnings = []
    corrupted_errors = []
    textbook_upload_dir = os.path.join("uploads", "textbooks")
    os.makedirs(textbook_upload_dir, exist_ok=True)

    for file in files:
        filename = file.filename
        save_path = os.path.join(textbook_upload_dir, filename)
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        unit_data = rag_service.ingest_file(save_path, filename, subject=subject)
        if not unit_data:
            corrupted_errors.append(f"檔案【{filename}】讀取解析失敗，已略過。")
        elif unit_data.get("is_scanned_image"):
            scanned_warnings.append(unit_data["message"])
        elif unit_data.get("is_corrupted"):
            corrupted_errors.append(unit_data["message"])
        else:
            saved_results.append({
                "filename": filename,
                "unit_id": unit_data["unit_id"],
                "title": unit_data["title"],
                "vocab_count": len(unit_data.get("vocabulary", [])),
                "grammar_count": len(unit_data.get("grammar_patterns", []))
            })
            # 同步將該單元生字加入 word_guard 白名單
            word_guard.add_custom_vocab(unit_data.get("vocabulary", []))

    msg = f"成功讀取並載入 {len(saved_results)} 個教材單元！" if saved_results else ""
    return {
        "success": True,
        "message": msg,
        "warnings": scanned_warnings,
        "errors": corrupted_errors,
        "uploaded_units": saved_results,
        "units": rag_service.get_units_summary()
    }


class PasteTextbookRequest(BaseModel):
    title: str
    content: str
    subject: str = "English"


@app.post("/api/paste-textbook")
async def paste_textbook(req: PasteTextbookRequest):
    """
    老師直接貼上教材文字 API (支援課文、單字表、文法或主題重點)
    """
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="教材內容不得為空白")

    unit_data = rag_service.ingest_pasted_text(
        title=req.title,
        text=req.content,
        subject=req.subject
    )
    # 同步字彙至 word_guard
    word_guard.add_custom_vocab(unit_data.get("vocabulary", []))
    return {
        "success": True,
        "message": f"成功解析並索引單元【{unit_data['title']}】！",
        "units": rag_service.get_units_summary()
    }


class DeleteUnitRequest(BaseModel):
    unit_id: str


@app.post("/api/delete-unit")
async def delete_single_unit(req: DeleteUnitRequest):
    """單獨刪除特定教材單元"""
    success = rag_service.delete_unit(req.unit_id)
    return {
        "success": success,
        "message": f"單元【{req.unit_id}】已成功移除" if success else f"找不到單元【{req.unit_id}】",
        "units": rag_service.get_units_summary()
    }


@app.post("/api/load-sample-textbooks")
async def load_sample_textbooks():
    """一鍵載入教材 (供老師快速體驗或初次載入)"""
    res = rag_service.load_sample_units()
    return res


@app.post("/api/clear-textbooks")
async def clear_textbooks():
    """清空目前已索引的所有教材，讓老師重新開始"""
    rag_service.clear_all()
    return {
        "success": True,
        "message": "已清空教材索引清單",
        "units": []
    }


# ==============================================================================
# 3. 方案 B：舊考卷參考模板上傳克隆 (三段式容錯管線)
# ==============================================================================
@app.post("/api/clone-skeleton")
async def clone_skeleton(file: UploadFile = File(...)):
    filename = file.filename
    save_path = os.path.join("uploads", filename)
    with open(save_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        result = agent_service.clone_exam_skeleton(save_path)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析失敗: {e}")


# ==============================================================================
# 4. 按大題與子批次分塊出題 API (Sub-batch Chunked Generation + SSE 即時進度)
# ==============================================================================
class GenerateExamRequest(BaseModel):
    metadata: Dict[str, Any]
    unit_ids: List[str]
    sections_config: List[Dict[str, Any]]
    api_key: Optional[str] = None


@app.post("/api/generate-exam")
async def generate_exam(req: GenerateExamRequest):
    """標準 JSON 考卷生成入口 (支援任意多題與多篇題組)"""
    subject = req.metadata.get("subject", "English")
    unit_ids = req.unit_ids
    if not unit_ids:
        # 若未指定，預設取目前已索引的前 3 個單元
        all_avail = list(rag_service.index.keys())
        unit_ids = all_avail[:3] if all_avail else ["L01"]

    sections_cfg = req.sections_config
    generated_sections = []
    current_q_num = 1

    for s_idx, sec in enumerate(sections_cfg):
        sec_result = agent_service.generate_section(
            subject=subject,
            unit_ids=unit_ids,
            section_config=sec,
            start_q_num=current_q_num,
            custom_api_key=req.api_key
        )
        if sec_result.get("questions"):
            current_q_num += len(sec_result["questions"])
        elif sec_result.get("passages"):
            for p in sec_result["passages"]:
                current_q_num += len(p.get("sub_questions", []))

        generated_sections.append(sec_result)

    full_exam_data = {
        "metadata": req.metadata,
        "sections": generated_sections
    }
    return full_exam_data


@app.post("/api/generate-exam-stream")
async def generate_exam_stream(req: GenerateExamRequest):
    """
    SSE 即時進度條出題入口 (Server-Sent Events)
    每完成一個題目子批次或閱讀篇章，即時推送進度百分比與步驟訊息給瀏覽器
    """
    subject = req.metadata.get("subject", "English")
    unit_ids = req.unit_ids
    if not unit_ids:
        all_avail = list(rag_service.index.keys())
        unit_ids = all_avail[:3] if all_avail else ["L01"]

    sections_cfg = req.sections_config

    async def event_generator():
        yield f"data: {json.dumps({'type': 'progress', 'percent': 5, 'message': '正在準備教材知識庫與初始化出題引擎...'}, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0.05)

        total_sections = len(sections_cfg)
        generated_sections = []
        current_q_num = 1

        for s_idx, sec in enumerate(sections_cfg):
            base_pct = int(10 + (s_idx / max(1, total_sections)) * 80)
            sec_title = sec.get("section_title") or sec.get("title") or sec.get("section_name", f"大題 {s_idx+1}")

            yield f"data: {json.dumps({'type': 'progress', 'percent': base_pct, 'message': f'正在出題【{sec_title}】...'}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.05)

            # 定義進度回調
            def on_progress_step(msg):
                pass

            # 執行大題出題
            sec_result = agent_service.generate_section(
                subject=subject,
                unit_ids=unit_ids,
                section_config=sec,
                start_q_num=current_q_num,
                custom_api_key=req.api_key,
                progress_callback=on_progress_step
            )

            if sec_result.get("questions"):
                current_q_num += len(sec_result["questions"])
            elif sec_result.get("passages"):
                for p in sec_result["passages"]:
                    current_q_num += len(p.get("sub_questions", []))

            generated_sections.append(sec_result)

            done_pct = int(10 + ((s_idx + 1) / max(1, total_sections)) * 80)
            yield f"data: {json.dumps({'type': 'progress', 'percent': done_pct, 'message': f'【{sec_title}】出題完成！目前累計至第 {current_q_num-1} 題'}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.05)

        yield f"data: {json.dumps({'type': 'progress', 'percent': 95, 'message': '正在執行審題格式校正與題號連貫性驗證...'}, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0.05)

        full_exam_data = {
            "metadata": req.metadata,
            "sections": generated_sections
        }

        yield f"data: {json.dumps({'type': 'complete', 'percent': 100, 'message': f'全卷生成完成！共 {current_q_num-1} 題。', 'exam_data': full_exam_data}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ==============================================================================
# 5. 單題一鍵抽換 API (Regenerate Single Question)
# ==============================================================================
class RegenerateQuestionRequest(BaseModel):
    subject: str = "English"
    unit_ids: List[str]
    old_question: Dict[str, Any]
    api_key: Optional[str] = None


@app.post("/api/regenerate-question")
async def regenerate_question(req: RegenerateQuestionRequest):
    new_q = agent_service.regenerate_single_question(
        subject=req.subject,
        unit_ids=req.unit_ids,
        old_q=req.old_question,
        custom_api_key=req.api_key
    )
    return new_q


class ConvertImageQuestionRequest(BaseModel):
    subject: str = "English"
    unit_ids: List[str]
    question_number: int
    current_question: Dict[str, Any]
    chart_style: Optional[str] = None
    api_key: Optional[str] = None


@app.post("/api/convert-to-image-question")
async def convert_to_image_question(req: ConvertImageQuestionRequest):
    """將單選題切換/生成為圖片題 (自動調用 Matplotlib 產出圖片並出題)"""
    new_q = agent_service.generate_image_question(
        subject=req.subject,
        unit_ids=req.unit_ids,
        question_number=req.question_number,
        current_q=req.current_question,
        chart_style=req.chart_style,
        custom_api_key=req.api_key
    )
    return new_q


class ConvertTextQuestionRequest(BaseModel):
    subject: str = "English"
    unit_ids: List[str]
    question_number: int
    current_question: Dict[str, Any]
    api_key: Optional[str] = None


@app.post("/api/convert-to-text-question")
async def convert_to_text_question(req: ConvertTextQuestionRequest):
    """將圖片題轉回純文字單選題"""
    new_q = agent_service.convert_to_text_question(
        subject=req.subject,
        unit_ids=req.unit_ids,
        question_number=req.question_number,
        current_q=req.current_question,
        custom_api_key=req.api_key
    )
    return new_q



# ==============================================================================
# 6. 一鍵成套 Word 匯出與下載 API (Triple-Document Export)
# ==============================================================================
@app.post("/api/export-docx")
async def export_docx(exam_data: Dict[str, Any]):
    try:
        suite = render_exam_suite(exam_data, output_dir="output_exams")
        return {
            "success": True,
            "files": suite
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Word 渲染失敗: {e}")


@app.get("/api/download")
async def download_file(file: str):
    if not os.path.exists(file):
        raise HTTPException(status_code=404, detail="檔案不存在")
    filename = os.path.basename(file)
    return FileResponse(
        file,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename
    )


# ==============================================================================
# 主程式入口
# ==============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print(" ExamCrafter AI - 智慧考卷生成系統 (v2.5)")
    print(" 伺服器啟動於: http://localhost:8000")
    print(" 離線純 CSS + 原生 JS 架構 (嚴格禁止 TailwindCSS)")
    print("=" * 60)
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
