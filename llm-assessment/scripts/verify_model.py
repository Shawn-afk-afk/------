"""Wait for the requested local model, then run a real non-writing grading check."""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--wait-seconds',type=int,default=0)
args=parser.parse_args()
deadline=time.monotonic()+max(0,args.wait_seconds)
while True:
    try:
        with urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=5) as response:
            ready=any(item['name']=='gpt-oss:20b' for item in json.load(response).get('models',[]))
    except Exception:
        ready=False
    if ready:break
    if time.monotonic()>=deadline:raise SystemExit('gpt-oss:20b 尚未下載完成，尚未驗證推論。')
    time.sleep(30)
print('模型已就緒；開始實際批改測試。',flush=True)
check=subprocess.run([sys.executable,str(ROOT/'tests/smoke_ai.py')],cwd=ROOT,timeout=1000)
raise SystemExit(check.returncode)
