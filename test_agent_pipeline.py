import json
import time
from agent_service import agent_service

print("=== 1. Checking Ollama Status ===")
status = agent_service.check_ollama_status()
print("Ollama Status:", status)

print("\n=== 2. Testing JSON Repair Pipeline ===")
broken_json = '```json\n{"test": [1, 2, 3,], "unterminated": "yes"'
repaired = agent_service.clean_and_repair_json(broken_json)
print("Repaired JSON:", repaired)

print("\n=== 3. Testing Real Question Generation (Micro-Prompting) ===")
t0 = time.time()
sec_cfg = {
    "section_id": "sec_1",
    "section_title": "一、 文意字彙選擇",
    "section_type": "CHOICE",
    "question_count": 2,
    "score_per_question": 5
}
generated_sec = agent_service.generate_section("English", ["L01"], sec_cfg, start_q_num=1)
t1 = time.time()
print(f"Time taken: {t1 - t0:.2f} s")
print("Generated Section Title:", generated_sec.get("section_title"))
print("Generated Questions Count:", len(generated_sec.get("questions", [])))
if generated_sec.get("questions"):
    print("Q1 Stem:", generated_sec["questions"][0].get("stem"))
    print("Q1 Options:", generated_sec["questions"][0].get("options"))
    print("Q1 Answer:", generated_sec["questions"][0].get("answer"))
    print("Q1 Explanation:", generated_sec["questions"][0].get("explanation"))

print("\n=== 4. Testing Clone Exam Skeleton from PDF ===")
cloned = agent_service.clone_exam_skeleton("歷史段考考卷.pdf")
print("Cloned Skeleton Success:", cloned.get("success"))
print("Cloned Title:", cloned.get("cloned_title"))
print("Cloned Sections Count:", len(cloned.get("sections", [])))
