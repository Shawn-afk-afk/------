import urllib.request
import json
import time

body = {
    "model": "gemma4:e4b",
    "prompt": "You are an English exam creator for grade 7. Create 1 multiple-choice question testing the vocabulary 'schedule' in JSON format with keys: question_number (1), stem, options (A,B,C,D), answer, explanation. Output valid JSON only.",
    "format": "json",
    "stream": False
}

t0 = time.time()
req = urllib.request.Request(
    "http://localhost:11434/api/generate",
    data=json.dumps(body).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)

try:
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read().decode("utf-8"))
    t1 = time.time()
    print(f"Generation Time: {t1 - t0:.2f} seconds")
    print("Response text:\n", data.get("response"))
    parsed = json.loads(data.get("response"))
    print("Parsed successfully! Keys:", list(parsed.keys()))
except Exception as e:
    print("Error:", e)
