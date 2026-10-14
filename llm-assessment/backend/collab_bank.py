"""Three draft-only pilot tasks within chapters 1–2."""
import copy
from storage import db,initialize,latest_questions,question
from server import add_version

PILOTS=[
('LAB-AI-001','ZJU-022','Read, mark and discuss an MLM bug','en',
 'On the whiteboard, circle the line that creates an incorrect MLM label and annotate your reasoning. Write your initial explanation before requesting AI feedback. Discuss the issue with the local tutor, explain what you accepted or rejected, then complete the final independent question. Chinese or English explanations are accepted.',
 'original = tokens.copy()\nmasked = tokens.copy()\nmasked[mask_index] = "[MASK]"\nlabel = masked[mask_index]',
 'Without tutor hints: a causal next-token training script sets inputs=tokens[:-1] and targets=tokens[:-1]. Explain the problem, the intended alignment, and one padding-related check.',
 '初稿應定位 label 讀取已被覆寫的 masked 位置；原值應來自 original。理由需連結輸入損壞與復原目標，不能只圈某行。修改理由需回應助教問題並用程式資料來源支持。最後獨立題應指出 targets 同位置未位移，應使用 tokens[1:] 配 tokens[:-1]，並核對 padding／loss mask。'),
('LAB-AI-002','ZJU-025','AI 白板：畫出 encoder-decoder 資料流','zh-TW',
 '畫出 encoder、decoder 與 cross-attention，標示 Q、K、V 來源和箭頭方向。先寫下初稿理由，再請本機 AI 追問。你可以接受或拒絕建議，但要解釋原因。完成協作後，回答一個關閉 AI 提示的小情境。',None,
 '獨立作答：若 decoder 的第 2 個位置能讀到尚未生成的第 4 個目標 token，與正常自回歸生成有何矛盾？指出應限制哪一種注意力；不要把來源 encoder 的內容一起禁止。',
 '初稿應將 Q 連到 decoder 隱藏表示，K、V 連到 encoder 輸出；可共享輸出來源但投影與作用不同。圖的關係與文字理由需一致。獨立題應區分 decoder causal self-attention 的未來目標限制與 cross-attention 可讀已知 encoder 來源，避免禁止所有來源資訊。'),
('LAB-AI-003','ZJU-039','AI 白板：改善一個不公平的比較','zh-TW',
 '畫出 Mamba／Transformer 比較計畫：基準、修改因素、固定條件、品質與資源指標。情境：兩次測試的硬體、batch 與序列長度不同，卻只以速度宣布勝負。先提出初稿，再與本機 AI 核對並修改；不需要計算數值。',None,
 '獨立作答：某模型在相同硬體下更快，但測試任務與另一模型不同。能否宣布它全面更好？列出兩個需補齊的條件與一個能否定你改善假設的結果。',
 '初稿需辨識多個混淆因素，圖中區分固定與修改項。固定任務、輸入長度、batch、dtype、硬體與測量階段，並比較任務品質、延遲／吞吐、記憶體及重複量測。修改需回應證據而非只接受 AI。獨立題需指出任務與品質要求不可比，並提出品質退步或資源超預算等可否定假設的結果。'),
]

def seed(c):
    originals={row['question_id']:question(row,True) for row in latest_questions(c)};created=0
    for qid,source,title,language,prompt,code,independent,solution in PILOTS:
        if c.execute('SELECT 1 FROM questions WHERE id=?',(qid,)).fetchone():continue
        q=copy.deepcopy(originals[source]);q.update(title=title,kind='ai_collab_canvas',scope='chapter_concept_collaboration',difficulty_design='pilot',tests={},runtime={'gpu_required_on_student':False,'inference_location':'host','model_provider':'ollama_local','human_review_required':True})
        q['prompt']=prompt;q['payload']={'language':language,'max_turns':4,'independent_prompt':independent,'reading_code':code,'code_reading':bool(code),'pilot':True}
        g=q['answer']['teaching_guide'];g.update(reference_answer=solution,reference_code=None,steps=['先記錄初稿與理由，不使用提示。','與助教逐輪核對；辨識建議中的合理與不合理部分。','說明修改理由，再在關閉提示的階段完成新情境。'],common_errors=['把 AI 的轉錄／建議當作自己的理由。','圖中箭頭與文字矛盾；未處理比較條件。'],practical_transfer='將架構、資料流程或實驗條件畫清楚，再以對照與小型程式測試核對。',authorship='原創 AI 協作試驗題；依教材第一／二章概念，待教師覆核。')
        q['answer']={'expected_elements':[solution],'teaching_guide':g,'allow_equivalent_answers':True}
        entries=[('initial','初稿概念證據','只依 canvas.initial_text，未提供原始理由不可用後來的 AI 回應補分'),('revision','核對与修改理由','依 text 看是否以條件與證據接受、拒絕或修正提示'),('coherence','圖與解釋一致性','核對已確認的圖像內容與學生解釋；辨識失敗不當作概念錯誤，圖像仍待教師覆核'),('transfer','獨立遷移','只依 canvas.independent_text 評估最後新情境，不用 AI 提示內容當獨立證據')]
        q['rubric']={'version':1,'total_points':12,'requires_human_review':True,'criteria':[{'id':key,'name':name,'points':3,'max_level':3,'levels':{'0':'未展現或關鍵矛盾；'+anchor,'1':'只有名詞或有關鍵遺漏；'+anchor,'2':'核心正確但有小幅遺漏；'+anchor,'3':'完整連結題目條件、機制與限制；'+anchor}} for key,name,anchor in entries]}
        q['analysis_metadata']={'target_skill':q['skill_id'],'language':language,'support_condition':'local_ai_collaboration','pilot':True,'grading_note':'需教師核對實際圖像；協作與獨立表現分開','not_allowed_inference':['motivation','personality']}
        c.execute('INSERT INTO questions VALUES(?,?)',(qid,q['skill_id']));add_version(c,q,None,qid);created+=1
    return created

if __name__=='__main__':
    initialize()
    with db() as c:print({'new_pilot_drafts':seed(c)})
